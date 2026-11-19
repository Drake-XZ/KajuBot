r"""第 6 轮（H、K 一起重训）的数据（2026-11-17，voice_train\H和K重训方案-20261117.md 第 2～3 步）。

  gold   兄长写的句子 → 规划器卡（GOLD：要说到的只留他真说了的、改写成短事实；他用到的、卡上没有的事进背景（有来路）；心情行用当时的）
         来源：心情页（mood-1 的 A 不进，兄长定）、replay4 备注、第 5 轮旧卡盲选备注（三条是点评不是句子，跳过 / 只取句子）、第 5 轮金句 62 条
         → data\rounds_v4\r6\gold.jsonl
  pairs  心情对子（心情页同卡：配 A 心情时 A 好、B 不要；反过来再一对）+ 毛病对子（同卡：写手串卡 / 佳树连用 / 念背景 / 太长的那句不要、兄长的好）
         → r6\pairs.jsonl（不拿“都不好”的整句当反例，不给删减型改写加重权）
  pack   拼 H、K 的训练目录：r6\h_data（stage1 = H 新卡 ~2000 + 旧 H 抽 2000，不用贴吧）、r6\k_data（stage2 = 原作新卡 1000 + 旧卡原作 600
         + 旧人工样本 + 金句；prefs = 对子，留一成；stage1 = 同 h_data，给阶段二复习用）
  exam   考题换成规划器卡：exam_v6 的卡把“要说到的”改写成短事实（不看参考答案）→ data\stage2bg\exam_v7.json
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r6.py gold|pairs|pack|exam
"""
import argparse
import asyncio
import glob
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import train_keys  # noqa: E402,F401
import prepare_h_plan as hp  # noqa: E402  card_with / 两字片段
import build_mood_page as bmp  # noqa: E402  card_of
from kaju_core.heart.mood_line import mood_line, normalize  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
R4 = rt.ROOT
R6 = os.path.join(R4, "r6")
PACKDATA = os.path.join(rt.PACK, "data")
SKIP_NOTES = {"rp4-9", "r5ab-1", "r5ab-7"}  # 是点评，不是句子
NOTE_AFTER = {"r5ab-3": "后面："}  # 只取这几个字后面的句子

GOLD = """下面是一段聊天、交给佳树的材料（卡），和兄长写的“佳树这时会说的话”。请按规划器的写法把卡整理好。只输出 JSON：
{"要接住的": "...", "要说到的": ["..."], "背景": ["..."], "方向": "..."}

要接住的：最后那句（或最后几句）里需要佳树接住的是哪件事，一句话，主语是说话的人；只写是什么事。材料里已经有就照它（可以改得更准）。
要说到的：只留兄长那句**真说了的事**（事实、答复、打算）；每条一件事、一句短话（二十字以内），写成第三人称的事实，
  **换掉他那句的说法**（人名、物名、数字除外），能合成一条的合成，最多 3 条；不写态度、感受、撒娇、关心、提问、玩笑；都没有就 []。
背景：0～3 条短话：
  1. 他那句里用到了、但局面和要说到的里都没有的事，从材料原来的背景或聊天前文里找出来写进来；找不到出处的，就照他那句写成一条事实（不许编别的）；
  2. 材料原来的背景里，再留 0～1 件他没用到的（教写手背景可以不说）。
  不写对人对事的定性评价、她该怎么说话、她的心情和想法、你自己的知识。
方向：佳树这句的反应，一个短语（十个字以内），态度或回应动作。不写句子。"""

EXAM = """下面是一段聊天和交给佳树的材料（卡）。请只把卡里“要说到的”重写一遍，别的不动。只输出 JSON：{"要说到的": ["..."]}
每条一件事、一句短话（二十字以内），写成第三人称的事实（“佳树没听过 Dafny”“佳树答应先读完上卷”），能合成一条的合成，最多 3 条；
不写态度、感受、语气、该怎么说；只用卡上本来有的事，不加新的；卡上是“无”就 []。"""


def jl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if os.path.exists(p) else []


def dump(p, rows):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def split_mood(card):
    lines = [x for x in str(card).split("\n") if x.strip()]
    m = next((x for x in lines if x.startswith("心情：")), "")
    return "\n".join(x for x in lines if not x.startswith("心情：")), normalize(m)


def strip_bg(card):
    lines = card.split("\n")
    bg = next((x[3:] for x in lines if x.startswith("背景：")), "")
    return "\n".join(x for x in lines if not x.startswith("背景：")), [b for b in bg.split("；") if b.strip()]


def note_text(iid, note):
    note = str(note or "").strip()
    if iid in SKIP_NOTES or len(note) < 4:
        return ""
    if iid in NOTE_AFTER and NOTE_AFTER[iid] in note:
        note = note.split(NOTE_AFTER[iid], 1)[1]
    return "\n".join(x.strip() for x in note.split(" / ") if x.strip())


def votes(d):
    out = {}
    for f in glob.glob(os.path.join(d, "*.json")):
        v = json.load(open(f, encoding="utf-8"))
        out[os.path.basename(f)[:-5]] = v.get("data", v)
    return out


def plans_v5():
    return {str(d["t"]): d["plan"] for d in jl(os.path.join(R4, "replay4", "plans_cmp", "v5.jsonl")) if d.get("plan")}


# ------------------------------------------------------------------ 收兄长写的句子
def collect():
    items = []
    seen = set()

    def add(kind, iid, ctx, card_in, mood, target, extra=None):
        key = hp._n(target)
        if not target or key in seen:
            return
        seen.add(key)
        items.append({"id": f"g6-{iid}", "from": kind, "group": f"g6-{iid.split('-side')[0]}", "ctx": list(ctx)[-8:],
                      "card_in": card_in, "mood": mood, "target": target, **(extra or {})})

    # 1. 心情页（mood-1 的 A 不进）
    page = {x["id"]: x for x in json.load(open(os.path.join(R4, "replay4", "mood_page_items.json"), encoding="utf-8"))}
    for iid, v in sorted(votes(os.path.join(R4, "replay4", "mood_votes", "mood")).items(), key=lambda kv: int(kv[0].split("-")[1])):
        it = page[iid]
        for side in "ab":
            if iid == "mood-1" and side == "a":
                continue
            t = (v.get(side) or "").strip()
            if t:
                add("mood_page", f"{iid}-side{side}", it["ctx"], it["card"], it[side]["line"], t, {"page": iid, "side": side, "t": it["t"]})
    # 2. replay4 备注（卡用 v5 指导）
    w4 = {str(r["id"]): r for r in json.load(open(os.path.join(R4, "replay4", "write.json"), encoding="utf-8"))}
    key4 = json.load(open(os.path.join(R4, "replay4", "key.json"), encoding="utf-8"))
    p5 = plans_v5()
    for iid, v in votes(os.path.join(R4, "replay4", "votes", "votes")).items():
        t = note_text(iid, v.get("note"))
        src = key4[iid]["src"]
        r = w4.get(src)
        if not t or not r:
            continue
        rec = {"kind": r.get("kind"), "title": r.get("to")}
        card_in = bmp.card_of(rec, p5[src]) if src in p5 else split_mood(r["card_p"])[0]
        add("replay4", iid, r["ctx"], card_in, split_mood(r["card_p"])[1], t, {"t": src, "page_item": iid})
    # 3. 第 5 轮旧卡盲选备注（找回线上记录：前文最后几行对上）
    import round_pick as rpk
    recs = [d for d in rpk.records() if d.get("outcome") == "used"]
    html = open(os.path.join(rt.VT, "review", "round_r5_ab.html"), encoding="utf-8").read()
    page5 = json.loads(re.search(r'<script id="items" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    for it in page5:
        v = votes(os.path.join(R4, "r5", "ab_votes", "votes")).get(it["id"]) or {}
        t = note_text(it["id"], v.get("note"))
        if not t:
            continue
        rec = None
        for d in recs:
            ctx = rpk.parse(d.get("ctx"))
            if ctx and ctx[-6:] == it["ctx"][-6:]:
                rec = d
        if rec is None:
            print("  找不到线上记录：", it["id"])
            continue
        tt = str(rec["t"])
        c = rpk.parse(rec.get("card"))
        live_card = (c[-1].get("card") if c else "") or ""
        card_in = bmp.card_of({"kind": rec.get("kind"), "title": rec.get("title")}, p5[tt]) if tt in p5 else split_mood(live_card)[0]
        mood = mood_line(rec["mood"]) if (rec.get("mood") or {}).get("mood") else split_mood(live_card)[1]
        add("r5ab", it["id"], rpk.parse(rec.get("ctx")), card_in, mood, t, {"t": tt})
    # 4. 第 5 轮金句（以前各轮整理好的）
    for r in jl(os.path.join(R4, "r5", "gold.jsonl")):
        card_in, mood = split_mood(r["card"])
        add("r5gold", r["id"], r["ctx"], card_in, mood, r["target"])
    return items


async def convert(items, prompt=GOLD):
    from kaju_core.senses import omni
    sem = asyncio.Semaphore(6)

    async def one(it):
        card0, old_bg = strip_bg(it["card_in"])
        mat = card0 + ("\n背景：" + "；".join(old_bg) if old_bg else "")
        u = f"聊天：\n{chr(10).join(it['ctx'])}\n\n交给佳树的材料：\n{mat}\n\n兄长写的佳树会说的话：\n{it['target']}"
        async with sem:
            for attempt in range(3):
                try:
                    out, _ = await omni.text(prompt, u, timeout=40)
                    m = re.search(r"\{.*\}", out or "", re.S)
                    v = json.loads(m.group(0)) if m else None
                    if isinstance(v, dict) and "要说到的" in v:
                        catch = str(v.get("要接住的") or "").strip()
                        must = [str(x).strip() for x in (v.get("要说到的") or []) if str(x).strip()][:3]
                        bg = [str(x).strip() for x in (v.get("背景") or []) if str(x).strip()][:3]
                        base = re.sub(r"。要接住的：.*$", "", card0, flags=re.M) if catch else card0
                        card = hp.card_with(base, catch, bg, must) if catch else hp.card_with(card0, "", bg, must)
                        if it["mood"]:
                            card += "\n" + it["mood"]
                        return {**it, "catch": catch, "must": must, "bg": bg, "direction": str(v.get("方向") or "").strip(), "card": card}
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(5 * (attempt + 1))
        print("  没整理成：", it["id"])
        return None

    return [x for x in await asyncio.gather(*(one(it) for it in items)) if x]


def do_gold():
    import usage_meter
    usage_meter.patch()
    items = collect()
    from collections import Counter
    print(f"兄长的句子 {len(items)} 条：{dict(Counter(i['from'] for i in items))}", flush=True)
    rows = asyncio.run(convert(items))
    for r in rows:
        r["src"] = "curated"  # 训练时按人工样本重复采样（--curated-repeat）
    dump(os.path.join(R6, "gold.jsonl"), rows)
    u = usage_meter.report(os.path.join(R6, "usage-gold.json"))
    print(f"整理好 {len(rows)} 条 → {os.path.join(R6, 'gold.jsonl')}；估 {u['rmb']} 元", flush=True)


# ------------------------------------------------------------------ 对子
def _clauses(t):
    return [c for c in re.split(r"[，。！？!?\n~…、]+|\.{2,}|……", t) if c.strip()]


def faults(card, text, mine):
    """写手那句有没有兄长说的那几种毛病：串卡（要点原字照搬过半）、佳树连用、念背景、比他的长一倍还多。"""
    def field(k):
        m = re.search(rf"^{k}：(.*)$", card, re.M)
        return [] if not m or m.group(1).strip() == "无" else [x for x in m.group(1).split("；") if x.strip()]
    out = []
    pts, bgs = field("要说到的"), field("背景")
    cov = lambda p: len(hp._bi(p) & hp._bi(text)) / max(1, len(hp._bi(p)))  # noqa: E731
    if pts and sum(cov(p) for p in pts) / len(pts) >= 0.5:
        out.append("串卡")
    run = best = 0
    for c in _clauses(text):
        run = run + 1 if c.strip().startswith("佳树") else 0
        best = max(best, run)
    if best >= 3:
        out.append("佳树连用")
    if any(cov(b) >= 0.4 for b in bgs):
        out.append("念背景")
    if len(text) > max(60, 2 * len(mine)):
        out.append("太长")
    return out


def do_pairs():
    gold = {r["id"]: r for r in jl(os.path.join(R6, "gold.jsonl"))}
    pairs = []
    # 心情对子
    by_page = {}
    for r in gold.values():
        if r["from"] == "mood_page":
            by_page.setdefault(r["page"], {})[r["side"]] = r
    for pid, sides in by_page.items():
        if "a" in sides and "b" in sides:
            for me, other in (("a", "b"), ("b", "a")):
                g = sides[me]
                pairs.append({"id": f"mood6-{pid}-{me}", "src": "mood", "group": f"g6-{pid}", "ctx": g["ctx"], "card": g["card"],
                              "chosen": g["target"], "rejected": sides[other]["target"], "w": 1.0})
    # 毛病对子：replay4（写手照规划器卡写的两句 + 当时发的）、第 5 轮旧卡盲选（两个写手）
    w4 = {str(r["id"]): r for r in json.load(open(os.path.join(R4, "replay4", "write.json"), encoding="utf-8"))}
    html = open(os.path.join(rt.VT, "review", "round_r5_ab.html"), encoding="utf-8").read()
    page5 = {x["id"]: x for x in json.loads(re.search(r'<script id="items" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))}
    for g in gold.values():
        if g["from"] == "replay4":
            r = w4[g["t"]]
            cands = [r["out_a"], r["out_b"], r["out_c"]]
        elif g["from"] == "r5ab":
            it = page5[g["id"][3:]]
            cands = [it["A"]["text"], it["B"]["text"]]
        else:
            continue
        for k, c in enumerate(cands):
            why = faults(g["card"], c or "", g["target"])
            # 光是“太长”不算：只靠长短分好坏，写手会学成丢要点变短（11-10、第 1 轮的教训）
            if c and set(why) - {"太长"} and hp._n(c) != hp._n(g["target"]):
                pairs.append({"id": f"fault6-{g['id'][3:]}-{k}", "src": "fault", "group": g["group"], "ctx": g["ctx"], "card": g["card"],
                              "chosen": g["target"], "rejected": c, "why": why, "w": 1.0})
    dump(os.path.join(R6, "pairs.jsonl"), pairs)
    from collections import Counter
    print(f"对子 {len(pairs)}：{dict(Counter(p['src'] for p in pairs))}；毛病：{dict(Counter(w for p in pairs for w in p.get('why', [])))}", flush=True)


# ------------------------------------------------------------------ 拼训练目录
def do_pack():
    rng = random.Random(20261117)
    sysj = os.path.join(PACKDATA, "system.json")
    old1 = jl(os.path.join(PACKDATA, "stage1.jsonl"))
    old2 = jl(os.path.join(PACKDATA, "stage2.jsonl"))
    keep = ("src", "id", "group", "ctx", "target", "card")
    # H：新规划器卡 + 旧 H（不用贴吧）抽一样多
    h_new = [dict({k: r[k] for k in keep if k in r}, card=r["card_final"], src="h6_" + r["src"]) for r in jl(os.path.join(rt.VT, "data", "stage_h_plan", "full.jsonl"))]
    pool = [r for r in old1 if r["src"] != "tieba"]
    rng.shuffle(pool)
    h_old = pool[:len(h_new)]
    stage1 = h_new + h_old
    rng.shuffle(stage1)
    for d in ("h_data", "k_data"):
        os.makedirs(os.path.join(R6, d, "prefs"), exist_ok=True)
        open(os.path.join(R6, d, "system.json"), "w", encoding="utf-8").write(open(sysj, encoding="utf-8").read())
        dump(os.path.join(R6, d, "stage1.jsonl"), stage1)
    # K：原作新卡 1000 + 旧卡原作 600 + 旧人工样本 + 金句
    k_new = [dict({k: r[k] for k in keep if k in r}, card=r["card_final"], src="novel") for r in jl(os.path.join(rt.VT, "data", "stage_k_plan", "novel.jsonl"))]
    new_ids = {r["id"] for r in k_new}
    old_novel = [dict(r, card=normalize(r["card"])) for r in old2 if r["src"] == "novel" and r["id"] not in new_ids]
    rng.shuffle(old_novel)
    old_cur = [dict(r, card=normalize(r["card"]), src="curated_old") for r in old2 if r["src"] == "curated"]
    gold = [{k: r[k] for k in keep if k in r} for r in jl(os.path.join(R6, "gold.jsonl"))]
    stage2 = k_new + old_novel[:600] + old_cur + gold
    rng.shuffle(stage2)
    dump(os.path.join(R6, "k_data", "stage2.jsonl"), stage2)
    # 对子：按对话留一成
    pairs = jl(os.path.join(R6, "pairs.jsonl"))
    groups = sorted({p["group"] for p in pairs})
    rng.shuffle(groups)
    held = set(groups[:max(2, len(groups) // 10)])
    dump(os.path.join(R6, "k_data", "prefs", "dpo.jsonl"), [p for p in pairs if p["group"] not in held])
    dump(os.path.join(R6, "k_data", "prefs", "heldout.jsonl"), [p for p in pairs if p["group"] in held])
    dump(os.path.join(R6, "k_data", "prefs", "kto.jsonl"), [])
    info = {"H": {"新规划器卡": len(h_new), "旧H（不含贴吧）": len(h_old)},
            "K": {"原作新卡": len(k_new), "旧卡原作": min(600, len(old_novel)), "旧人工样本": len(old_cur), "金句": len(gold),
                  "带心情行": sum("\n心情：" in r["card"] for r in stage2)},
            "对子": {"训练": len(pairs) - sum(p["group"] in held for p in pairs), "留出": sum(p["group"] in held for p in pairs)}}
    json.dump(info, open(os.path.join(R6, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1), flush=True)


# ------------------------------------------------------------------ 考题
def do_exam():
    from kaju_core.senses import omni
    import usage_meter
    usage_meter.patch()
    src = json.load(open(os.path.join(rt.VT, "data", "stage2bg", "exam_v6.json"), encoding="utf-8"))
    sem = asyncio.Semaphore(6)

    async def one(iid, it):
        card = it["card_v6"]
        base, mood = split_mood(card)
        u = f"聊天：\n{chr(10).join((it.get('ctx') or [])[-8:])}\n\n交给佳树的材料：\n{base}"
        async with sem:
            for attempt in range(3):
                try:
                    out, _ = await omni.text(EXAM, u, timeout=40)
                    m = re.search(r"\{.*\}", out or "", re.S)
                    v = json.loads(m.group(0)) if m else None
                    if isinstance(v, dict) and "要说到的" in v:
                        must = [str(x).strip() for x in (v.get("要说到的") or []) if str(x).strip()][:3]
                        if re.search(r"^要说到的：\s*无\s*$", base, re.M):
                            must = []
                        new = hp.card_with(base, "", [], must)
                        return iid, dict(it, card_v7=new + ("\n" + mood if mood else ""))
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(5 * (attempt + 1))
        return iid, dict(it, card_v7=card)

    async def go():
        return await asyncio.gather(*(one(i, it) for i, it in src.items()))
    out = dict(asyncio.run(go()))
    p = os.path.join(rt.VT, "data", "stage2bg", "exam_v7.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    u = usage_meter.report()
    print(f"考题 {len(out)} 道 → {p}；估 {u['rmb']} 元", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gold", "pairs", "pack", "exam"])
    a = ap.parse_args()
    {"gold": do_gold, "pairs": do_pairs, "pack": do_pack, "exam": do_exam}[a.cmd]()


if __name__ == "__main__":
    main()
