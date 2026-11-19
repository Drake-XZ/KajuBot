"""套路量尺（2026-11-10，减AI味完整方案-v2 第 0 步）。判断和线上发之前查的是同一份：kaju_core\\voice\\routine.py。

两种量法：
  线上记录  按会话、按时间顺序重放：每句发出去的话和它之前的 50 句比（和线上"只记不拦"记下来的应该一致）。
            python -I routine_stats.py live [--days 14]
  考试结果  每个写手在同一批题上写的话：书面套路命中率、开头最常见的 3 种占多少、和她线上发过的话太像的占多少。
            python -I routine_stats.py exam data\\exam_pref_p2.json old p
不调模型，不花钱。输出 data\\daily\\reports\\routine-<live|exam>.md
"""
import collections
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(VT)
sys.path.insert(0, os.path.join(ROOT, "bot_setup"))
from kaju_core.voice import routine  # noqa: E402

REWRITES = os.path.join(ROOT, "kaju_data", "self", "kaju_style", "rewrites")
REPORTS = os.path.join(VT, "data", "daily", "reports")


def live_rows(days):
    rows = []
    for path in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl")))[-days:]:
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("umo") and (r.get("final") or "").strip():
                rows.append(r)
    rows.sort(key=lambda r: r.get("t", 0))
    return rows


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def live(days):
    rows = live_rows(days)
    sent = collections.defaultdict(list)
    n = 0
    kinds = collections.Counter()
    by_outcome = collections.Counter()
    ex = []
    for r in rows:
        text = routine.MEME_TAG.sub("", r["final"]).strip()
        hits = routine.check(text, sent[r["umo"]])
        sent[r["umo"]].append(text)
        n += 1
        if hits:
            who = "写手" if r.get("used") else "DeepSeek原稿"
            by_outcome[who] += 1
            for h in hits:
                kinds[h.split(":")[0]] += 1
            ex.append((r.get("kind", ""), who, text, hits))
    used = sum(bool(r.get("used")) for r in rows)
    L = ["# 套路量尺：线上记录", "",
         f"最近 {days} 天的重说记录 {n} 句（写手写的 {used} 句，其余发的是 DeepSeek 原稿），{len(sent)} 个会话。", "",
         f"- 撞了套路的：{sum(by_outcome.values())} 句（{pct(sum(by_outcome.values()), n)}）；其中写手写的 {by_outcome['写手']}（占写手句子的 {pct(by_outcome['写手'], used)}），"
         f"原稿 {by_outcome['DeepSeek原稿']}（{pct(by_outcome['DeepSeek原稿'], n - used)}）",
         f"- 和旧话太像 {kinds['same']}，开头连着三次一样 {kinds['opener']}，书面套路两条以上 {kinds['soft']}", "",
         "## 撞上的句子（全部）", ""]
    for kind, who, text, hits in ex:
        L += [f"- {kind}·{who}：{text.replace(chr(10), ' / ')}", f"  - {'；'.join(hits)}"]
    return "live", L


def exam(path, sides):
    items = json.load(open(path, encoding="utf-8"))
    corpus = [routine.MEME_TAG.sub("", r["final"]).strip() for r in live_rows(60)]
    L = ["# 套路量尺：考试结果", "", f"{os.path.basename(path)}，{len(items)} 题。和线上发过的 {len(corpus)} 句比。", "",
         "| | 句数 | 书面套路一条以上 | 两条以上 | 开头最常见 3 种占 | 最常见的开头 | 和线上发过的话太像 |", "|---|---|---|---|---|---|---|"]
    for s in sides:
        texts = [t for it in items for t in (it.get(s) or []) if t]
        soft = [routine.soft_hits(t) for t in texts]
        ops = collections.Counter(o for o in (routine.opener(t) for t in texts) if o)
        top = ops.most_common(3)
        # 考试题有一部分就是线上记录：和"一模一样的那句"比没意义，重合 1.0 的不算
        alike = sum(1 for t in texts if routine.SAME <= max((routine.sim(t, c) for c in corpus), default=0) < 0.999)
        L.append(f"| {s} | {len(texts)} | {pct(sum(bool(x) for x in soft), len(texts))} | {pct(sum(len(x) >= 2 for x in soft), len(texts))} | "
                 f"{pct(sum(c for _, c in top), len(texts))} | {'、'.join(f'{o}×{c}' for o, c in top)} | {pct(alike, len(texts))} |")
    return "exam", L


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "exam":
        name, L = exam(a[1], a[2:] or ["old"])
    else:
        name, L = live(int(a[a.index("--days") + 1]) if "--days" in a else 14)
    out = os.path.join(REPORTS, f"routine-{name}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:60]))
    print("报告", out)
