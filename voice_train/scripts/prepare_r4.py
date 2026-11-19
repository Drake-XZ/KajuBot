r"""第 4 轮（2026-11-16，交接-佳树-向MaiBot做法看齐）：教写手“看指导说话”，顺带治三个毛病（兄长 11-16）：
反复“佳树…佳树…”（每个分句都拿“佳树”开头接一条要点）、两条要点粘成病句、前后跳。根子都是把卡上的要点一条条照念。

卡用 v6 = 规划器卡的样子：v5（局面 / 要说到的 / 背景 / 心情）的“局面”后面接“。要接住的：对方做了什么”
（和 replay_planner.py 拼的、兄长盲选看的那种一样；以后第四阶段主模型写指导，线上就是这种卡）。

  gold     金句：replay3 兄长的 24 条备注（规划器卡）+ 第 3 轮的 37 条金句（v5 卡补“要接住的”）。
           他的句子里说到、卡上和聊天里都没有的事，先让 Gemini 补进“要说到的”（r22 教训：不补写手学会编）。
           “第三句不需要”这种删减照做，不加权（第 1 轮教训）。没写备注、选了照指导写的那句 → KTO 好。
  pairs    同一张卡让线上写手写 3 遍，和金句不一样的当“不要的”（同卡才成对，权重 2，和第 3 轮一样）；
           每句标上毛病（连着 3 个分句以“佳树”开头 / Gemini 判不成话、接不上、念卡），有毛病的优先，每条金句最多 2 对。
           不用“都不好”整句当 KTO 反例（第 2 轮教训）。
  convert  原作复习：stage2bg\novel.jsonl 的 v5 卡补“要接住的” → r4\extra_stage2.jsonl（原句不念背景 = 背景可用可不用）；
           考试题：stage2bg\exam_v5.json → exam_v6.json（exam_p3.py --cards v6）。
  all      convert → gold → pairs
不放群聊 / 兄长私聊的复习（K 层把复习都当“佳树说的话”学）。
用法（AstrBot 的 Python；pairs 要 Ollama 开着）：python -I -X utf8 scripts\prepare_r4.py convert|gold|pairs|all
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
BG = os.path.join(rt.VT, "data", "stage2bg")
R3P = os.path.join(rt.ROOT, "replay3")
OUT = rt.rdir(4)

CATCH = """下面是一段聊天和交给佳树的材料（局面、要说到的）。佳树还没回话。
请补一栏“要接住的”：聊天最后那句（或最后几句）里，需要佳树接住的是哪件事——问了什么、要她做什么、在说什么事。
一句话，主语是说话的那个人（“兄长大人问她听没听过 Dafny”“小鞠学姐说自己被卷进人群、全身是白粉”）。
只写“是什么事”，不写“回应…”“表达…”“表现出…”，不写她该怎么回、用什么态度，不写她要说的内容。
只输出 JSON：{"要接住的": "..."}"""

FILL = """下面是一段聊天、交给佳树的材料（局面、要说到的、背景），和佳树真正说出口的话。
找出她这句话里说到的、但聊天和材料里都没有的**具体的事**：她知道的事实、看过的东西里的内容、她自己的事和打算（“佳树现在是初三”“狗头人用日语答完才发现要说英语”“考完那天想给兄长准备一桌菜”）。
不列：态度、安慰、夸奖、语气、感受（“别泄气”“佳树相信你”“好心疼”这类）、对聊天里已有的事的复述、提问。
每条一句，主语清楚，不超过 30 字。没有就 []。只输出 JSON：{"补": ["..."]}"""


def render_v6(card_v5: str, catch: str) -> str:
    if not catch:
        return card_v5
    out = []
    for line in card_v5.splitlines():
        if line.startswith("局面：") and "要接住的：" not in line:
            line = line.rstrip("。") + "。要接住的：" + catch.rstrip("。")
        out.append(line)
    return "\n".join(out)


def add_points(card: str, extra: list[str]) -> str:
    if not extra:
        return card
    out = []
    for line in card.splitlines():
        if line.startswith("要说到的："):
            v = line.split("：", 1)[1].strip()
            pts = [] if v in ("", "无") else [v]
            line = "要说到的：" + "；".join(pts + [x.rstrip("。；;") for x in extra])
        out.append(line)
    return "\n".join(out)


def _json(out, key):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return v.get(key) if isinstance(v, dict) and key in v else None


async def ask(system, user, key, sem):
    from kaju_core.senses import omni
    async with sem:
        for _ in range(3):
            try:
                out, _ = await omni.text(system, user, timeout=60)
                v = _json(out, key)
                if v is not None:
                    return v
            except Exception as e:  # noqa: BLE001
                print("  Gemini 没答上来", type(e).__name__, flush=True)
    return None


def chat(ctx):
    return "聊天：\n" + ("\n".join(ctx[-8:]) if ctx else "（没有前文）")


async def catch_of(ctx, card, sem):
    v = await ask(CATCH, chat(ctx) + "\n\n材料：\n" + card, "要接住的", sem)
    return re.sub(r"\s+", " ", str(v or "")).strip()


# ------------------------------------------------------------------ convert
async def do_convert():
    import train_keys  # noqa: F401
    sem = asyncio.Semaphore(6)
    os.makedirs(OUT, exist_ok=True)
    novel = rt.jl(os.path.join(BG, "novel.jsonl"))
    cache_p = os.path.join(OUT, "catch_cache.json")
    cache = json.load(open(cache_p, encoding="utf-8")) if os.path.exists(cache_p) else {}

    async def one(key, ctx, card):
        if key not in cache:
            cache[key] = await catch_of(ctx, card, sem)
        return cache[key]

    cs = await asyncio.gather(*[one("n:" + r["id"], r["ctx"], r["card_v5"]) for r in novel])
    extra = [{"id": r["id"] + "-v6", "src": "novel", "group": r.get("group") or r["id"], "ctx": r["ctx"],
              "card": render_v6(r["card_v5"], c), "target": r["target"]} for r, c in zip(novel, cs) if c]
    rt.wjl(os.path.join(OUT, "extra_stage2.jsonl"), extra)
    # 考试题
    import exam_p3 as ep
    its = {it["id"]: it for it in ep.items()}
    v5 = json.load(open(os.path.join(BG, "exam_v5.json"), encoding="utf-8"))
    ids = [k for k in v5 if k in its]
    ce = await asyncio.gather(*[one("e:" + k, its[k]["ctx"], v5[k]["card_v5"]) for k in ids])
    v6 = {k: {"card_v6": render_v6(v5[k]["card_v5"], c), "catch": c} for k, c in zip(ids, ce)}
    json.dump(v6, open(os.path.join(BG, "exam_v6.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(cache, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"原作复习 v6 卡 {len(extra)}/{len(novel)}（带背景的 {sum('背景：' in e['card'] for e in extra)}）；"
          f"考试题 v6 卡 {sum(bool(v['catch']) for v in v6.values())}/{len(ids)} → exam_v6.json", flush=True)


# ------------------------------------------------------------------ gold
def replay3_notes():
    """replay3 的票：(行, 票)；行是 write.json 那条，带 card_p、三句输出、选了哪种。"""
    key = json.load(open(os.path.join(R3P, "key.json"), encoding="utf-8"))
    rows = {r["id"]: r for r in json.load(open(os.path.join(R3P, "write.json"), encoding="utf-8"))}
    out = []
    for p in glob.glob(os.path.join(R3P, "votes", "votes", "*.json")):
        v = json.load(open(p, encoding="utf-8"))
        v = v.get("data", v)
        iid = os.path.basename(p)[:-5]
        k = key[iid]
        ch = v.get("choice") or ""
        out.append((iid, rows[k["src"]], k[ch] if ch in ("A", "B", "C") else ch, (v.get("note") or "").strip()))
    return sorted(out, key=lambda x: int(x[0].split("-")[-1]))


def note_target(row, picked, note):
    if note == "第三句不需要":  # rp3-24：他选的那句去掉第三条
        return "\n".join(rt.lines(row[f"out_{picked}"]).split("\n")[:2])
    return rt.lines(note)


async def do_gold():
    import train_keys  # noqa: F401
    sem = asyncio.Semaphore(4)
    gold, kto, todo = [], [], []
    for iid, r, picked, note in replay3_notes():
        if len(note) >= 6:
            todo.append({"id": "r4-" + iid, "ctx": r["ctx"], "card": r["card_p"], "target": note_target(r, picked, note),
                         "from": "replay3", "picked": picked})
        elif picked in ("b", "c"):  # 没写备注、选了照指导写的那句：单条好
            kto.append({"id": "r4-" + iid, "src": "gold", "ctx": r["ctx"], "card": r["card_p"],
                        "text": rt.lines(r[f"out_{picked}"]), "label": "good", "w": 1.0})
    old = rt.jl(os.path.join(BG, "gold.jsonl"))
    cs = await asyncio.gather(*[catch_of(g["ctx"], g["card_v5"], sem) for g in old])
    for g, c in zip(old, cs):
        todo.append({"id": "r4-" + g["id"], "ctx": g["ctx"], "card": render_v6(g["card_v5"], c), "target": g["target"], "from": "r3gold"})
    adds = await asyncio.gather(*[ask(FILL, chat(t["ctx"]) + "\n\n材料：\n" + t["card"] + "\n\n佳树说的：\n" + t["target"], "补", sem)
                                  for t in todo])
    n_fill = 0
    for t, a in zip(todo, adds):
        a = [re.sub(r"\s+", " ", str(x)).strip() for x in (a or []) if str(x).strip()][:4]
        if a:
            n_fill += 1
            t["filled"] = a
        gold.append({"id": t["id"], "src": "live", "group": t["id"], "ctx": t["ctx"], "card": add_points(t["card"], a),
                     "target": t["target"], "from": t["from"], "filled": a})
    os.makedirs(OUT, exist_ok=True)
    rt.wjl(os.path.join(OUT, "gold.jsonl"), gold)
    rt.wjl(os.path.join(OUT, "kto.jsonl"), kto)
    print(f"金句 {len(gold)}（replay3 备注 {sum(g['from'] == 'replay3' for g in gold)}、第 3 轮金句 {sum(g['from'] == 'r3gold' for g in gold)}），"
          f"补了事实的 {n_fill}；单条好 {len(kto)} → {OUT}", flush=True)
    for g in gold:
        if g["filled"]:
            print("  补", g["id"], "：", "；".join(g["filled"])[:120], flush=True)


# ------------------------------------------------------------------ pairs
def jiashu_run(text):
    cs = [c.strip() for c in re.split(r"[，,。！!？?~～…\n/、；;：:]+", text or "") if c.strip()]
    run = best = 0
    for c in cs:
        run = run + 1 if c.startswith("佳树") else 0
        best = max(best, run)
    return best


async def do_pairs(samples):
    import speech_check as sc
    from kaju_core import gpu_busy
    gold = rt.jl(os.path.join(OUT, "gold.jsonl"))
    model = rt.state()["live_model"]
    cand = []
    gpu_busy.mark("第 4 轮数据：线上写手照金句的卡写")
    try:
        for i, g in enumerate(gold):
            for _ in range(samples):
                out = rt.write(model, g["ctx"], g["card"])
                if out and rt.lines(out) != rt.lines(g["target"]):
                    cand.append((g, rt.lines(out)))
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}/{len(gold)}", flush=True)
    finally:
        gpu_busy.clear()
    js = await sc.judge_many([{"ctx": g["ctx"], "reply": o} for g, o in cand])
    by = {}
    for (g, o), j in zip(cand, js):
        bad = []
        if jiashu_run(o) >= 3:
            bad.append("佳树连用")
        if j:
            bad += [k for k, ok in (("不成话", j["成话"]), ("接不上", j["接得上"]), ("念卡", not j["念卡"])) if not ok]
        by.setdefault(g["id"], []).append((len(bad), o, bad, (j or {}).get("毛病", "")))
    pairs = []
    for g in gold:
        for nb, o, bad, why in sorted(by.get(g["id"], []), key=lambda x: -x[0])[:2]:
            pairs.append({"id": g["id"], "src": "live", "group": g["id"], "ctx": g["ctx"], "card": g["card"],
                          "chosen": g["target"], "rejected": o, "w": 2.0, "bad": bad, "why": why})
    rt.wjl(os.path.join(OUT, "pairs.jsonl"), pairs)
    allc = [b for v in by.values() for b in v]
    cnt = lambda k: sum(k in b[2] for b in allc)  # noqa: E731
    print(f"写了 {len(gold) * samples} 遍、和金句不同 {len(allc)}：佳树连用 {cnt('佳树连用')}、不成话 {cnt('不成话')}、"
          f"接不上 {cnt('接不上')}、念卡 {cnt('念卡')}；成对 {len(pairs)}（有毛病的 {sum(bool(p['bad']) for p in pairs)}）→ pairs.jsonl", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["convert", "gold", "pairs", "all"])
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()
    if a.cmd in ("convert", "all"):
        asyncio.run(do_convert())
    if a.cmd in ("gold", "all"):
        asyncio.run(do_gold())
    if a.cmd in ("pairs", "all"):
        asyncio.run(do_pairs(a.samples))


if __name__ == "__main__":
    main()
