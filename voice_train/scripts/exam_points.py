"""逐条要点核对（2026-11-10）：AI 味以外的硬指标。拿 exam_v2.json 里每一遍回复，对着它自己那张卡逐条看。

ab7 盲选兄长大人选旧的 14:4，备注和对照看下来主要是：新写手漏后面的要点、把谁做的事安错。exam_v2 的评判提示
说了"草稿太满、不用每件事都说到"，漏点几乎不扣分，所以 DeepSeek 判新的赢。这里不比 A/B，只数：
  漏了几条要点 / 说错几条 / 主语安错 / 编了卡上没有的事 / 答非所问；另算长度、照抄卡片的比例（card.copy_ratio）。
输出 data\\daily\\reports\\exam-points.md + data\\exam_points.json
用法（AstrBot venv）：python -I exam_points.py [--file data\\exam_v2.json]
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import card  # noqa: E402

CHECK = """下面是一段聊天、一张要点卡（回复该说的意思），和照这张卡写出来的回复。回复的人是温水佳树，自称"佳树"。
要点卡里没写是谁的事，就是佳树自己的事。逐条核对：
- 要点：每一条在回复里是"说了"、"没说"，还是"说错"（意思变了、反了、谁做的弄反了）
- 问：卡上"问"那一栏要问的，回复问了没有（卡上是"无"就填 null）
- 主语错：回复把谁做的、谁的感受安错了人（比如兄长的事说成佳树的，佳树要做的说成让兄长做）
- 编了：回复说了卡上和聊天里都没有的事
- 答非所问：回复没接上对方的话
只输出 JSON：{"要点": ["说了|没说|说错", ...], "问": true/false/null, "主语错": false, "编了": false, "答非所问": false, "说明": "一句话，没问题就写无"}"""


def points_of(card_text):
    m = re.search(r"^要点：(.*)$", card_text or "", re.M)
    return [p for p in (m.group(1).split("；") if m else []) if p.strip()]


async def check(it, side, j):
    reply, ct = it[side][j], it[f"{side}_card"]
    pts = points_of(ct)
    if not reply:
        return {"要点": ["没说"] * len(pts), "问": None, "主语错": False, "编了": False, "答非所问": False, "说明": "没写出来"}
    u = f"聊天：\n{chr(10).join(it['ctx'][-6:]) or '（没有前文）'}\n\n要点卡：\n{ct}\n\n回复：\n{reply}"
    for _ in range(2):
        m = re.search(r"\{.*\}", await bl.ask(CHECK, u, 0.0) or "", re.S)
        try:
            v = json.loads(m.group(0)) if m else None
        except ValueError:
            v = None
        if v and isinstance(v.get("要点"), list):
            v["要点"] = (v["要点"] + ["没说"] * len(pts))[:len(pts)]
            return v
    return None


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(bl.VT, "data", "exam_v2.json"))
    a = ap.parse_args()
    items = json.load(open(a.file, encoding="utf-8"))
    jobs = [(it, side, j) for it in items for side in ("old", "new") for j in range(len(it["old"]))]
    res = await asyncio.gather(*(check(it, s, j) for it, s, j in jobs))
    for (it, s, j), v in zip(jobs, res):
        it.setdefault(f"pts_{s}", [None] * len(it[s]))[j] = v
    json.dump(items, open(os.path.join(bl.VT, "data", "exam_points.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def stats(group):
        out = {}
        for s in ("old", "new"):
            vs = [(it, j, it[f"pts_{s}"][j]) for it in group for j in range(len(it[s])) if it[f"pts_{s}"][j]]
            n_pt = sum(len(v["要点"]) for _, _, v in vs)
            miss = sum(x == "没说" for _, _, v in vs for x in v["要点"])
            wrong = sum(x == "说错" for _, _, v in vs for x in v["要点"])
            last = [v["要点"][-1] for _, _, v in vs if len(v["要点"]) >= 2]
            asks = [v["问"] for _, _, v in vs if v.get("问") is not None]
            lens = sorted(len(re.sub(r"\s", "", it[s][j] or "")) for it, j, _ in vs)
            out[s] = {"回复": len(vs), "要点": n_pt, "漏": pct(miss, n_pt), "说错": pct(wrong, n_pt),
                      "最后一条漏": pct(sum(x == "没说" for x in last), len(last)),
                      "全说到": pct(sum(all(x == "说了" for x in v["要点"]) for _, _, v in vs), len(vs)),
                      "问漏了": pct(sum(q is False for q in asks), len(asks)),
                      "主语错": pct(sum(bool(v.get("主语错")) for _, _, v in vs), len(vs)),
                      "编了": pct(sum(bool(v.get("编了")) for _, _, v in vs), len(vs)),
                      "答非所问": pct(sum(bool(v.get("答非所问")) for _, _, v in vs), len(vs)),
                      "长度中位": lens[len(lens) // 2] if lens else 0,
                      "照抄卡片": f"{sorted(card.copy_ratio(it[s][j], it[f'{s}_card']) for it, j, _ in vs)[len(vs) // 2]:.2f}" if vs else "-"}
        return out
    cols = ["回复", "要点", "漏", "说错", "最后一条漏", "全说到", "问漏了", "主语错", "编了", "答非所问", "长度中位", "照抄卡片"]
    L = ["# 逐条要点核对：旧 r003（第一版卡）/ 新 l2a（第二版卡）", "",
         "每遍回复对着它自己的卡逐条看（DeepSeek 关思考，温度 0）。照抄卡片 = 回复里 4 字片段原样出现在卡上的比例（中位）。", ""]
    groups = {"全部": items, "私聊": [it for it in items if it["kind"] == "私聊"], "群聊": [it for it in items if it["kind"] == "群聊"],
              "线上": [it for it in items if it["set"] == "线上"]}
    key_p = os.path.join(bl.VT, "data", "ab7_key.json")
    if os.path.exists(key_p):
        recs = {v["rec"] for v in json.load(open(key_p, encoding="utf-8")).values()}
        groups["ab7 盲选那 30 题"] = [it for it in items if it["id"] in recs]
    for g, grp in groups.items():
        st = stats(grp)
        L += [f"## {g}（{len(grp)} 题）", "", "| | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for s, name in (("old", "旧 r003"), ("new", "新 l2a")):
            L.append(f"| {name} | " + " | ".join(str(st[s][c]) for c in cols) + " |")
        L.append("")
    L += ["## 新的说错、主语错的例子", ""]
    n = 0
    for it in items:
        for j, v in enumerate(it.get("pts_new") or []):
            if v and (v.get("主语错") or "说错" in v["要点"]) and n < 25:
                n += 1
                L += [f"- {it['id']}：{v.get('说明')}", f"  - 卡：{'；'.join(points_of(it['new_card']))}", f"  - 新：{it['new'][j]}"]
    rp = os.path.join(bl.VT, "data", "daily", "reports", "exam-points.md")
    open(rp, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:40]))
    print(f"{bl.cost()}\n报告 {rp}")


if __name__ == "__main__":
    asyncio.run(main())
