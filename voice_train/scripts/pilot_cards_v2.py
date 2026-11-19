"""第二版要点卡试抽（要点卡改进方案第二步，2026-11-09）：重抽全部训练卡之前，先拿约 200 条看新卡对不对。

三类样本：
  train  H/K 训练用、从真人回复抽的卡（lccc / group / owner / tieba / bili / curated）：card.EXTRACT_V2 从回复抽
         DeepSeek 查新旧两张卡各自：漏了回复里的事、加了回复里没有的事、主语或因果弄错 → 统计
  novel  K 层原作对齐卡（从 DeepSeek 草稿抽）：card.EXTRACT_V2_LIVE 从草稿抽，再用 AGREE 看原句算不算照卡（对齐率新旧比）
  live   ab6 盲选的 30 条线上草稿：EXTRACT_V2_LIVE 从草稿抽；兄长写过回复的一起列出来，给兄长看
输出 data\\pilot_v2.json + review\\pilot_v2.html（对照页的数据） + data\\daily\\reports\\pilot-v2.md
用法（AstrBot venv）：python -I pilot_cards_v2.py [--seed 7]
"""
import argparse
import asyncio
import ast
import glob
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402
import make_gold7 as g7  # noqa: E402

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import card  # noqa: E402
import rewrite  # noqa: E402

DATA = os.path.join(bl.VT, "data")
TAKE = {"lccc": 30, "group": 25, "owner": 10, "tieba": 25, "bili": 20, "curated": 20, "novel": 40}

CHECK = """下面是一段聊天、其中一条回复，和从这条回复提炼出的要点卡。要点卡的用处：别人只看卡就能写出意思一样的回复。
检查这张卡：
- 漏了：回复里说了、卡上没有的事（只算内容，语气词、客套不算）
- 加了：卡上有、回复里没说的事
- 弄错：卡上把谁做的事弄错了，或者把转折、因果弄反、把不相干的事连在一起
只输出 JSON：{"漏了": "没有就写无", "加了": "没有就写无", "弄错": "没有就写无"}"""


def ctx_list(v):
    if isinstance(v, list):
        return v
    try:
        x = ast.literal_eval(v)
        return x if isinstance(x, list) else [str(v)]
    except (ValueError, SyntaxError):
        return [str(v)] if v else []


def kind_of(r):
    return r.get("kind") or {"novel": "当面", "curated": r.get("kind") or "私聊"}.get(r["src"], "群聊")


def card_kind(card_text):
    m = re.search(r"^场合：(.*)$", card_text or "", re.M)
    return m.group(1) if m else "群聊"


def card_to(card_text):
    m = re.search(r"^对象：(.*)$", card_text or "", re.M)
    return "" if not m or m.group(1) == "无" else m.group(1)


def samples(rng):
    rows = bl.load(os.path.join(DATA, "layered_v1", "stage1.jsonl")) + bl.load(os.path.join(DATA, "layered_v1", "stage2.jsonl"))
    for p in sorted(glob.glob(os.path.join(DATA, "daily", "rounds", "*", "new.jsonl"))):
        rows += bl.load(p)
    pools = {}
    for r in rows:
        if r.get("src") in TAKE and r.get("src") != "novel" and r.get("card") and r.get("target"):
            pools.setdefault(r["src"], []).append(r)
    out = []
    for src, pool in pools.items():
        for r in rng.sample(pool, min(TAKE[src], len(pool))):
            out.append({"type": "train", "src": src, "id": r["id"], "ctx": ctx_list(r["ctx"]), "reply": r["target"],
                        "kind": card_kind(r["card"]), "to": card_to(r["card"]), "old_card": r["card"]})
    k = [r for r in bl.load(os.path.join(DATA, "layered_v1", "k_aligned.jsonl")) if r.get("draft")]
    for r in rng.sample(k, min(TAKE["novel"], len(k))):
        out.append({"type": "novel", "src": "novel", "id": r["id"], "ctx": ctx_list(r["ctx"]), "draft": r["draft"],
                    "reply": r["target"], "kind": r.get("kind") or "当面", "to": r.get("to", ""), "old_card": r.get("card", ""),
                    "old_ok": str(r.get("ok")) == "True"})
    key = json.load(open(os.path.join(DATA, "ab6_key.json"), encoding="utf-8"))
    rep = {x["id"]: x for x in json.load(open(os.path.join(DATA, "cardlive_replay.json"), encoding="utf-8"))}
    for iid in sorted(key, key=lambda s: int(s.split("-")[1])):
        r = rep[key[iid]["rec"]]
        out.append({"type": "live", "src": "live", "id": iid, "ctx": rewrite.tidy_ctx(r["ctx"])[-6:], "draft": r["draft"],
                    "kind": r["kind"], "to": r["title"], "old_card": r["old_card"],
                    "owner": g7.g6.lines(g7.WRITTEN[iid]) if iid in g7.WRITTEN else ""})
    return out


async def extract(prompt, s, text):
    for _ in range(2):
        c = card.parse(await bl.ask(prompt, card.extract_prompt(s["ctx"], text, s["kind"], s["to"]), 0.3))
        if c:
            return card.render(c, s["kind"], s["to"])
    return ""


async def check(s, ct):
    u = f"聊天：\n{chr(10).join(s['ctx'][-6:]) or '（没有前文）'}\n\n回复：\n{s['reply']}\n\n要点卡：\n{ct}"
    m = re.search(r"\{.*\}", await bl.ask(CHECK, u, 0.0) or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    return {k: ("" if str(v.get(k, "")).strip() in ("", "无", "没有") else str(v[k]).strip()) for k in ("漏了", "加了", "弄错")}


async def agree(ct, target):
    m = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{ct}\n\n回复：\n{target}", 0.0) or "", re.S)
    try:
        return bool(json.loads(m.group(0)).get("ok")) if m else False
    except ValueError:
        return False


async def one(s):
    if s["type"] == "train":
        s["new_card"] = await extract(card.EXTRACT_V2, s, s["reply"])
        if s["new_card"]:
            s["check_old"], s["check_new"] = await asyncio.gather(check(s, s["old_card"]), check(s, s["new_card"]))
    else:
        s["new_card"] = await extract(card.EXTRACT_V2_LIVE, s, s["draft"])
        if s["type"] == "novel" and s["new_card"]:
            s["new_ok"] = await agree(s["new_card"], s["reply"])
    return s


def n_points(ct):
    m = re.search(r"^要点：(.*)$", ct or "", re.M)
    return len([p for p in (m.group(1).split("；") if m else []) if p.strip()])


def has_bg(ct):
    return bool(re.search(r"^背景：", ct or "", re.M))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    todo = samples(rng)
    print(f"{len(todo)} 条：" + "，".join(f"{k} {sum(s['src'] == k for s in todo)}" for k in list(TAKE) + ["live"]), flush=True)
    rows = asyncio.run(_run(todo))
    rows = [s for s in rows if s.get("new_card")]
    json.dump(rows, open(os.path.join(DATA, "pilot_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    L = [f"# 第二版要点卡试抽（seed {a.seed}）", ""]
    tr = [s for s in rows if s["type"] == "train"]
    L += ["## 训练卡（从回复抽）：DeepSeek 查漏了 / 加了 / 弄错", "", "| 来源 | 条数 | 旧 漏/加/错 | 新 漏/加/错 | 要点数 旧→新 | 有背景 |", "|---|---|---|---|---|---|"]
    for src in ["lccc", "group", "owner", "tieba", "bili", "curated", "全部"]:
        g = [s for s in tr if src == "全部" or s["src"] == src]
        if not g:
            continue
        f = lambda side, k: sum(bool(s[f"check_{side}"][k]) for s in g)
        L.append(f"| {src} | {len(g)} | {f('old', '漏了')}/{f('old', '加了')}/{f('old', '弄错')} | "
                 f"{f('new', '漏了')}/{f('new', '加了')}/{f('new', '弄错')} | "
                 f"{sum(n_points(s['old_card']) for s in g) / len(g):.1f}→{sum(n_points(s['new_card']) for s in g) / len(g):.1f} | "
                 f"{sum(has_bg(s['new_card']) for s in g)} |")
    nv = [s for s in rows if s["type"] == "novel"]
    if nv:
        L += ["", f"## 原作对齐卡（从草稿抽）：原句照卡算得通 旧 {sum(s['old_ok'] for s in nv)}/{len(nv)}，新 {sum(s.get('new_ok', False) for s in nv)}/{len(nv)}；"
              f"要点数 旧 {sum(n_points(s['old_card']) for s in nv) / len(nv):.1f} → 新 {sum(n_points(s['new_card']) for s in nv) / len(nv):.1f}"]
    lv = [s for s in rows if s["type"] == "live"]
    L += ["", f"## 线上草稿（ab6 的 30 条）：要点数 旧 {sum(n_points(s['old_card']) for s in lv) / max(1, len(lv)):.1f} → 新 {sum(n_points(s['new_card']) for s in lv) / max(1, len(lv)):.1f}，有背景 {sum(has_bg(s['new_card']) for s in lv)}", ""]
    for s in rows:
        L += [f"### {s['id']}（{s['src']}）", "", "```", *(s["ctx"][-4:] or ["（没有前文）"]), "```"]
        if s.get("draft"):
            L += ["草稿：", "```", s["draft"], "```"]
        if s.get("reply"):
            L += [f"回复：{s['reply']}"]
        if s.get("owner"):
            L += [f"兄长写的：{s['owner']}"]
        L += ["", "| 旧卡 | 新卡 |", "|---|---|", f"| {s['old_card'].replace(chr(10), '<br>')} | {s['new_card'].replace(chr(10), '<br>')} |"]
        for side in ("old", "new"):
            c = s.get(f"check_{side}")
            if c and any(c.values()):
                L.append(f"- {'旧' if side == 'old' else '新'}：" + "；".join(f"{k} {v}" for k, v in c.items() if v))
        if s["type"] == "novel":
            L.append(f"- 原句照卡：旧 {'✓' if s['old_ok'] else '✗'}　新 {'✓' if s.get('new_ok') else '✗'}")
        L.append("")
    rp = os.path.join(DATA, "daily", "reports", "pilot-v2.md")
    open(rp, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:20]))
    print(f"{bl.cost()}\n报告 {rp}")


async def _run(todo):
    return await asyncio.gather(*(one(s) for s in todo))


if __name__ == "__main__":
    main()
