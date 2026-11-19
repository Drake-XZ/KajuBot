r"""第二阶段：卡上加一行“背景（可以不说）”的训练数据（2026-11-14，交接-佳树-向MaiBot做法看齐 第一节第 2 步）。

为什么：第 2 轮拆开验证（r21 / r22）——兄长的句子里有卡上没有的内容（前文、草稿、看过的东西），配在“无”卡上，写手就学成
在空卡上自己往下编、打转。办法：卡上多一行“背景”，把这些来路写清楚；再放几件相关但没用上的，让写手学会背景可以不说。

卡的样子（第五版，v4 + 一行）：
  场合 / 对象 / 局面 / 要说到的 / 背景：甲；乙 / 心情（有才写）
  背景为空就不写这一行。写手的系统提示和用户消息格式不变（和训练包一字不差），格式靠数据教。

背景怎么来（Gemini，只整理材料，不写答案；答案仍是原作原句、真人原话、兄长写的）：
  1. 回复里用到、但聊天和“要说到的”里都没有的事 → 一定写进背景（让回复里的每件事都有来路）。感受、评价、玩笑是她自己的，不算。
  2. 再从草稿 / 材料 / 聊天前文里挑 0～3 件相关、但回复没用到的事（教她背景可以不说）。挑不出就不挑，不许编。

  pilot   兄长的金句（第 2 轮 29 条 + 2b 盲选 8 条）+ 原作 15 条 + 真人群聊 15 条 → data\stage2bg\pilot.jsonl、pilot.md
  （全量另说：花钱前先给兄长看 pilot 和估价）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_bg.py pilot
"""
import argparse
import asyncio
import glob
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402
import prepare_r2 as p2  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = os.path.join(rt.VT, "data", "stage2bg")
PACK = os.path.join(rt.PACK, "data")

BG = """下面是一段聊天、交给{me}的材料（局面、要说到的），可能还有她当时手边的东西（草稿、看过的内容、记得的事），以及{me}真正说出去的那句回复。
请补一栏“背景”：交给{me}的、可以用也可以不用的相关事实。只输出 JSON：{{"背景": ["..."]}}

一定要写进背景的：回复里用到了、但聊天和“要说到的”里都没有的事（以前发生的事、看过的东西的细节、她知道的事）。
  这样回复里的每件事都有来路。回复里的感受、评价、玩笑、撒娇、关心、提问是她自己的，不算，不写。
可以再加 0～3 件：手边的东西或聊天前文里，和这一回合相关、但回复没用到的事。没有合适的就不加，不许编材料里没有的事。
每条一个十来个字的短事实；不写语气、不写该怎么说、不照抄回复的句子；最多 5 条。
**不写这些**：“要说到的”里已经有的事（意思一样也不行）；聊天里刚明说过的；你自己的知识、解释和推测（解释黑话、猜谁是谁、补背景知识）——
  每条都必须在聊天、材料或手边的东西里明明白白写着。
提到她自己写“{me}”，别人用聊天里的称呼。什么都不用写时输出 {{"背景": []}}。"""


def field(card, name):
    m = re.search(rf"^{name}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def render_v5(card: str, bg: list[str]) -> str:
    """v4 卡插一行“背景”（在“要说到的”之后、心情之前）；空就原样。"""
    if not bg:
        return card
    out, done = [], False
    for line in card.splitlines():
        if line.startswith("心情：") and not done:
            out.append("背景：" + "；".join(bg))
            done = True
        out.append(line)
    if not done:
        out.append("背景：" + "；".join(bg))
    return "\n".join(out)


def parse_bg(out: str) -> list[str] | None:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(v, dict) or "背景" not in v:
        return None
    x = v["背景"]
    if isinstance(x, str):
        x = [x] if x.strip() and x.strip() not in ("无", "[]") else []
    return [re.sub(r"\s+", " ", str(i)).strip().rstrip("。；;") for i in x if str(i).strip()][:5]


BG_EXAM = """下面是一段聊天和交给{me}的材料（局面、要说到的）。{me}还没回话。
请补一栏“背景”：从聊天前文里挑 0～3 件和这一回合相关、{me}回话时可能用得上（也可以不用）的事。只输出 JSON：{{"背景": ["..."]}}
每条一个十来个字的短事实；不写语气、不写该怎么说；“要说到的”里已有的、最后一句刚说的不写；
不写你自己的知识、解释和推测，每条都必须在聊天里明明白白写着。挑不出就输出 {{"背景": []}}。"""


async def gen_bg_exam(row: dict, me: str = "佳树") -> list[str] | None:
    """考试题：线上规划器给背景时还不知道她会说什么，所以不看答案。"""
    import build_layered as bl
    card = row["card"]
    user = (f"场合：{field(card, '场合')}\n对象：{field(card, '对象')}\n\n聊天：\n" + "\n".join(row["ctx"] or ["（没有前文）"])
            + f"\n\n材料：\n局面：{field(card, '局面')}\n要说到的：{field(card, '要说到的') or '无'}")
    for t in (0.3, 0.6):
        v = parse_bg(await bl.ask(BG_EXAM.format(me=me), user, t))
        if v is not None:
            return v
    return None


async def gen_bg(row: dict, me: str = "佳树") -> list[str] | None:
    import build_layered as bl
    card = row["card"]
    user = (f"场合：{field(card, '场合')}\n对象：{field(card, '对象')}\n\n聊天：\n" + "\n".join(row["ctx"] or ["（没有前文）"])
            + f"\n\n材料：\n局面：{field(card, '局面')}\n要说到的：{field(card, '要说到的') or '无'}"
            + (f"\n\n她手边的东西：\n{row['material'].strip()}" if row.get("material") else "")
            + f"\n\n{me}说出去的回复：\n{row['target']}")
    for t in (0.3, 0.6):
        v = parse_bg(await bl.ask(BG.format(me=me), user, t))
        if v is not None:
            return v
    return None


# ------------------------------------------------------------------ sources
def golds() -> list[dict]:
    """兄长写的句子：第 2 轮 29 条（带当时的草稿 / 旧卡要点当手边的东西）+ 2b 盲选里的整句改写。"""
    out = []
    write = {r["id"]: r for r in json.load(open(os.path.join(rt.ROOT, "replay2", "write.json"), encoding="utf-8"))}
    key2 = json.load(open(os.path.join(rt.ROOT, "replay2", "key.json"), encoding="utf-8"))
    exam = {it["id"]: it for it in json.load(open(os.path.join(rt.VT, "data", f"exam_p3_{rt.state()['live_model']}.json"), encoding="utf-8"))}
    keyr1 = json.load(open(os.path.join(rt.ROOT, "r1", "ab_key.json"), encoding="utf-8"))
    for g in rt.jl(os.path.join(rt.ROOT, "r2", "gold.jsonl")):
        src, pid = g["id"].split("-", 2)[1], g["id"].split("-", 2)[2]
        if src == "replay2":
            material = write[key2[pid]["src"]]["draft"]
        else:
            material = "要点：" + field(exam[keyr1[pid]["exam"]]["new_card"], "要说到的")
        out.append({"id": g["id"], "src": "gold", "ctx": g["ctx"], "card": g["card"], "target": g["target"], "material": material})
    keyb = json.load(open(os.path.join(rt.ROOT, "r22", "ab_key.json"), encoding="utf-8"))
    news = []
    for iid, v in p2.votes(os.path.join(rt.ROOT, "r22", "ab_votes")).items():
        note = (v.get("note") or "").strip()
        if not note or iid in ("r22ab-2", "r22ab-17"):  # 这两条是评论，不是改写
            continue
        ex = exam[keyb[iid]["exam"]]
        news.append({"src": "r22", "page_id": iid, "exam_id": ex["id"], "ctx": ex["ctx"], "kind": ex.get("kind") or "私聊",
                     "to": ex.get("title") or field(ex["new_card"], "对象"), "target": rt.lines(note), "base_card": ex["new_card"]})
    cards = asyncio.get_event_loop().run_until_complete(asyncio.gather(*[p2.gold_card(r) for r in news])) if news else []
    for r, c in zip(news, cards):
        if c:
            out.append({"id": f"r2b-{r['page_id']}", "src": "gold", "ctx": r["ctx"], "card": c, "target": r["target"],
                        "material": "要点：" + field(r["base_card"], "要说到的"), "exam_id": r["exam_id"]})
    return out


def samples(n_novel: int, n_group: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    s2 = [r for r in rt.jl(os.path.join(PACK, "stage2.jsonl")) if r.get("src") == "novel" and len(r.get("ctx") or []) >= 2]
    s1 = [r for r in rt.jl(os.path.join(PACK, "stage1.jsonl")) if r.get("src") == "group" and len(r.get("ctx") or []) >= 2]
    pick = rng.sample(s2, n_novel) + rng.sample(s1, n_group)
    return [{"id": r["id"], "src": r["src"], "ctx": r["ctx"], "card": r["card"], "target": r["target"], "material": ""} for r in pick]


def _bi(t):
    t = re.sub(r"[\s，。！？、,.!?~～…“”\"'：:；;（）()]", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def drop_dups(bg: list[str] | None, card: str) -> list[str] | None:
    """Gemini 常把“要说到的”又抄进背景：和某一条两字片段重合一半以上（或互相包含）的去掉。"""
    if bg is None:
        return None
    pts = [p for p in (field(card, "要说到的") or "").split("；") if p and p != "无"]
    keep = []
    for b in bg:
        bb = _bi(b)
        if any(b in p or p in b or (bb and len(bb & _bi(p)) / len(bb) >= 0.5) for p in pts):
            continue
        keep.append(b)
    return keep


async def build(rows: list[dict]) -> list[dict]:
    import build_layered as bl
    bl.use_gemini()
    bgs = await asyncio.gather(*[gen_bg(r, "佳树" if r["src"] in ("gold", "novel") else "我") for r in rows])
    for r, b in zip(rows, bgs):
        r["bg_raw"] = b
        r["bg"] = drop_dups(b, r["card"])
        r["card_v5"] = render_v5(r["card"], b or [])
    return rows


def report(rows, path):
    md = ["# 第二阶段“背景”卡 · 试做", "", f"{len(rows)} 条：" + "、".join(f"{k} {sum(r['src'] == k for r in rows)}" for k in ("gold", "novel", "group")),
          f"背景没出成 {sum(r['bg'] is None for r in rows)} 条；背景为空 {sum(r['bg'] == [] for r in rows)} 条；"
          f"平均 {sum(len(r['bg'] or []) for r in rows) / max(1, len(rows)):.1f} 条", ""]
    for r in rows:
        md += [f"### {r['id']}（{r['src']}）", "聊天最后：" + (r["ctx"][-1] if r["ctx"] else ""),
               "要说到的：" + (field(r["card"], "要说到的") or "无"), "**背景：" + ("；".join(r["bg"] or []) or "（空）") + "**",
               "回复：" + r["target"].replace("\n", " / "), ""]
    open(path, "w", encoding="utf-8").write("\n".join(md))


def full():
    """全量（11-14 兄长同意）：金句沿用 pilot 的结果；原作 800、真人群聊 400、兄长私聊 106 补背景；考试 40 题出一份带背景的卡。
    输出 data\\stage2bg\\{gold,novel,group,owner}.jsonl（每行原样 + bg + card_v5）、exam_v5.json（考试题 id → 带背景的卡）、full.md。"""
    import build_layered as bl
    bl.use_gemini()
    rng = random.Random(20261114)
    pilot = rt.jl(os.path.join(OUT, "pilot.jsonl"))
    gold = [r for r in pilot if r["src"] == "gold"]
    s2 = [r for r in rt.jl(os.path.join(PACK, "stage2.jsonl")) if r.get("src") == "novel" and len(r.get("ctx") or []) >= 2]
    s1 = rt.jl(os.path.join(PACK, "stage1.jsonl"))
    grp = [r for r in s1 if r.get("src") == "group" and len(r.get("ctx") or []) >= 2]
    own = [r for r in s1 if r.get("src") == "owner"]
    pick = lambda rows, n: rng.sample(rows, min(n, len(rows)))  # noqa: E731
    as_row = lambda r: {"id": r["id"], "src": r["src"], "ctx": r.get("ctx") or [], "card": r["card"], "target": r["target"], "material": ""}  # noqa: E731
    parts = {"novel": [as_row(r) for r in pick(s2, 800)], "group": [as_row(r) for r in pick(grp, 400)], "owner": [as_row(r) for r in own]}
    loop = asyncio.get_event_loop()
    for name, rows in parts.items():
        loop.run_until_complete(build(rows))
        rt.wjl(os.path.join(OUT, f"{name}.jsonl"), rows)
        print(f"  {name} {len(rows)} 条，背景为空 {sum(not r['bg'] for r in rows)}，没出成 {sum(r['bg'] is None for r in rows)}；累计调用 {bl.USAGE.get('calls')}", flush=True)
    rt.wjl(os.path.join(OUT, "gold.jsonl"), gold)
    excl = set(json.load(open(os.path.join(rt.ROOT, "exam_exclude.json"), encoding="utf-8")).get("ids") or [])
    ev = [r for r in rt.jl(os.path.join(PACK, "eval.jsonl")) if r["id"] not in excl]
    bgs = loop.run_until_complete(asyncio.gather(*[gen_bg_exam({"ctx": r.get("ctx") or [], "card": r["card"]}) for r in ev]))
    exam = {r["id"]: {"card_v5": render_v5(r["card"], drop_dups(b, r["card"]) or []), "bg": drop_dups(b, r["card"])} for r, b in zip(ev, bgs)}
    json.dump(exam, open(os.path.join(OUT, "exam_v5.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allrows = gold + [r for rows in parts.values() for r in rows]
    report(allrows[:60] + parts["group"][:20], os.path.join(OUT, "full.md"))
    print(f"考试 {len(exam)} 题带背景，有背景的 {sum(bool(v['bg']) for v in exam.values())}；Gemini 调用共 {bl.USAGE.get('calls')} 次 → {OUT}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pilot", "full"])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.cmd == "full":
        full()
        return
    import build_layered as bl
    bl.use_gemini()
    rows = golds() + samples(15, 15)
    rows = asyncio.get_event_loop().run_until_complete(build(rows))
    rt.wjl(os.path.join(OUT, "pilot.jsonl"), rows)
    report(rows, os.path.join(OUT, "pilot.md"))
    print(f"{len(rows)} 条 → {OUT}\\pilot.md；Gemini 调用 {bl.USAGE.get('calls')} 次", flush=True)


if __name__ == "__main__":
    main()
