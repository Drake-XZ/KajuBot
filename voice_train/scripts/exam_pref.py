"""偏好训练后的考试（2026-11-10）：新写手和线上 r003 用**同一张卡**（第一版卡）、同一句系统提示，各写 3 遍。

不让 DeepSeek 判谁更像佳树（两次都和兄长大人判反了）。只看两类硬指标：
  1. 信息有没有丢：exam_points 的逐条要点核对（漏点、最后一条漏、问漏了、说错、主语错、编了、答非所问）。
     这一项要调 DeepSeek（关思考、温度 0），99 题 × 3 遍约 300 次，高峰价约 0.3 元。r003 那边的核对结果直接用
     data\\exam_points.json 里现成的，不重花钱。
  2. 旁证（不调 DeepSeek）：照抄卡片的比例、长度、分几条；--metrics 给上 train_pref 的 metrics.json 时，
     把"没训过的题上，模型更偏向兄长的写法还是写手原句"也列进报告。
     （试过从兄长不要的句子里数常见片段当"AI 味词表"：在没训过的题上分不出好坏，没用，删了。
       拿 DeepSeek 草稿对真人语料数多出来的片段也试了：排前面的全是"佳树""兄长大人"，也没用。）
AI 味到底少没少，只有兄长盲选说了算（build_ab8.py）。
输出 data\\exam_pref_<tag>.json（盲选页从这里挑）+ data\\daily\\reports\\exam-pref-<tag>.md
用法（AstrBot venv）：python -I exam_pref.py --new kaju-writer-l1a-r003-p1 --tag p1 [--metrics results\\prefs\\p1\\metrics.json] [--no-check]
"""
import asyncio
import json
import math
import os
import re
import sys

ARGS = sys.argv[1:]
sys.argv = sys.argv[:1]
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exam_points as ep  # noqa: E402
import exam_v2 as ev  # noqa: E402  (write：和 r003 那 3 遍同一个写法)

bl, card, dl = ep.bl, ep.card, ev.dl
DATA = os.path.join(bl.VT, "data")
COLS = ["回复", "要点", "漏", "说错", "最后一条漏", "全说到", "问漏了", "主语错", "编了", "答非所问", "长度中位", "分几条", "照抄卡片"]


def opt(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


def flat(t):
    return re.sub(r"[\s，,。.！!？?～~…、：:；;「」“”\"'（）()&\-—/]", "", t or "")


def stats(group, sides):
    out = {}
    for s in sides:
        vs = [(it, j, it[f"pts_{s}"][j]) for it in group for j in range(len(it[s])) if (it.get(f"pts_{s}") or [None] * 9)[j]]
        texts = [it[s][j] for it in group for j in range(len(it[s])) if it[s][j]]
        lens = sorted(len(re.sub(r"\s", "", t)) for t in texts) or [0]
        row = {"回复": len(texts), "长度中位": lens[len(lens) // 2],
               "分几条": f"{sum(len([x for x in t.split(chr(10)) if x.strip()]) for t in texts) / max(1, len(texts)):.2f}",
               "照抄卡片": f"{sorted(card.copy_ratio(it[s][j], it['old_card']) for it in group for j in range(len(it[s])) if it[s][j])[len(texts) // 2]:.2f}" if texts else "-"}
        if vs:
            n_pt = sum(len(v["要点"]) for _, _, v in vs)
            last = [v["要点"][-1] for _, _, v in vs if len(v["要点"]) >= 2]
            asks = [v["问"] for _, _, v in vs if v.get("问") is not None]
            row.update({"要点": n_pt, "漏": ep.pct(sum(x == "没说" for _, _, v in vs for x in v["要点"]), n_pt),
                        "说错": ep.pct(sum(x == "说错" for _, _, v in vs for x in v["要点"]), n_pt),
                        "最后一条漏": ep.pct(sum(x == "没说" for x in last), len(last)),
                        "全说到": ep.pct(sum(all(x == "说了" for x in v["要点"]) for _, _, v in vs), len(vs)),
                        "问漏了": ep.pct(sum(q is False for q in asks), len(asks)),
                        "主语错": ep.pct(sum(bool(v.get("主语错")) for _, _, v in vs), len(vs)),
                        "编了": ep.pct(sum(bool(v.get("编了")) for _, _, v in vs), len(vs)),
                        "答非所问": ep.pct(sum(bool(v.get("答非所问")) for _, _, v in vs), len(vs))})
        out[s] = row
    return out


def miss_sign(items, new):
    """按题比漏点数（3 遍加起来）：新的漏得多的题 / 漏得少的题，和单边符号检验的 p（新的更差）。"""
    worse = better = 0
    for it in items:
        a = sum(x != "说了" for v in it.get("pts_old") or [] if v for x in v["要点"])
        b = sum(x != "说了" for v in it.get(f"pts_{new}") or [] if v for x in v["要点"])
        worse += b > a
        better += b < a
    n = worse + better
    p = sum(math.comb(n, k) for k in range(worse, n + 1)) / 2 ** n if n else 1.0
    return worse, better, p


async def main():
    model, tag = opt("--new"), opt("--tag", "p1")
    samples = int(opt("--samples", "3"))
    out_p = os.path.join(DATA, f"exam_pref_{tag}.json")
    items = json.load(open(out_p if os.path.exists(out_p) else os.path.join(DATA, "exam_points.json"), encoding="utf-8"))
    for it in items:
        it["p_card"] = it["old_card"]
    if not all(len(it.get("p") or []) == samples for it in items):
        dl.ollama_unload([x for x in dl.ollama_loaded() if x.startswith("kaju-writer")])
        for n, it in enumerate(items):
            it["p"] = [ev.write(model, card.WRITE_SYSTEM[2], it["ctx"], it["old_card"], it["draft"], it["title"]) for _ in range(samples)]
            if n % 20 == 0:
                print(f"  写到第 {n + 1}/{len(items)} 题", flush=True)
        dl.ollama_unload([model])
        json.dump(items, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if "--no-check" not in ARGS and not all(it.get("pts_p") and all(it["pts_p"]) for it in items):
        jobs = [(it, j) for it in items for j in range(samples) if not (it.get("pts_p") or [None] * samples)[j]]
        res = await asyncio.gather(*(ep.check(it, "p", j) for it, j in jobs))
        for (it, j), v in zip(jobs, res):
            it.setdefault("pts_p", [None] * samples)[j] = v
        json.dump(items, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(bl.cost())

    L = [f"# 偏好训练考试：线上 r003 对 {model}（同一张第一版卡）", "",
         "每题两边各写 3 遍。逐条要点核对由 DeepSeek 做（关思考、温度 0，只数说没说到，不判谁更像佳树）。",
         "照抄卡片 = 回复里 4 字片段原样出现在卡上的比例（中位）。", ""]
    mp = opt("--metrics")
    if mp and os.path.exists(mp):
        ms = json.load(open(mp, encoding="utf-8"))
        keys = [k for k in ms[0] if k not in ("tag", "各批")]
        L += ["## 没训过的题上，模型自己更偏向哪句（训练时量的，不调 DeepSeek）", "",
              "留出的是第四～七批里每 3 条留 1 条的考试题：同一张卡，兄长的写法 对 写手当时那句。", "",
              "| | " + " | ".join(keys) + " | 各批（比起点更偏向） |", "|---|" + "---|" * (len(keys) + 1)]
        L += [f"| {m['tag']} | " + " | ".join(str(m[k]) for k in keys) + f" | {m.get('各批', '')} |" for m in ms]
        L += ["", "偏向兄长写法 = 按每个字平均的概率，兄长那句比写手那句高的题占多少；比起点更偏向 = 和训练前比，差距往兄长那边挪了的题占多少；"
              "ab7 两列 = ab7 盲选里 r003 那句的对数概率变了多少（他选的应该不降，“都不好”的应该降）；原作台词损失升高 = 佳树口吻被带偏。", ""]
    groups = {"全部": items, "私聊": [it for it in items if it["kind"] == "私聊"], "群聊": [it for it in items if it["kind"] == "群聊"],
              "线上": [it for it in items if it["set"] == "线上"]}
    for g, grp in groups.items():
        st = stats(grp, ("old", "p"))
        L += [f"## {g}（{len(grp)} 题）", "", "| | " + " | ".join(COLS) + " |", "|---|" + "---|" * len(COLS)]
        for s, name in (("old", "线上 r003"), ("p", f"新 {tag}")):
            L.append(f"| {name} | " + " | ".join(str(st[s].get(c, "-")) for c in COLS) + " |")
        if any(it.get("pts_p") for it in grp):
            w, b, p = miss_sign(grp, "p")
            L += ["", f"按题比漏掉或说错的要点：新的更多 {w} 题、更少 {b} 题（新的更差的 p = {p:.2f}，小于 0.1 才算明显变差）"]
        L.append("")
    L += ["", "## 新的漏点、说错、主语错的例子", ""]
    n = 0
    for it in items:
        for j, v in enumerate(it.get("pts_p") or []):
            if v and (v.get("主语错") or "说错" in v["要点"] or v["要点"].count("没说") >= 2) and n < 25:
                n += 1
                L += [f"- {it['id']}：{v.get('说明')}", f"  - 卡：{'；'.join(ep.points_of(it['old_card']))}", f"  - 新：{it['p'][j]}",
                      f"  - r003：{it['old'][j]}"]
    rp = os.path.join(DATA, "daily", "reports", f"exam-pref-{tag}.md")
    open(rp, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:36]))
    print(f"报告 {rp}")


if __name__ == "__main__":
    asyncio.run(main())
