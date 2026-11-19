r"""心情页（2026-11-16 晚，兄长定“看回话 + 心情页”，AGENT.md 第十节）。

为什么：训练里的心情几乎都是“开心6 精神6 紧绷1 亲近5”（H 小试、K 原作、K 人工样本都窄），线上从“开心1 紧绷9”到“开心9”都有；
读书那天这种极端心情，几行聊天推不出来，只在她自己的生活里有。这一页让兄长写：同一张规划器卡，两种心情下她会怎么说 → K 的金数据。

  低落回合：11-15 读书那天等开心 < 0.4 或紧绷 ≥ 0.6 的线上回合，A = 她当时的心情，B = 换成开心（考试 exam_p3 的“开心”那组读数）
  平常回合：同一批回放里心情平常的回合，A = 当时的心情，B = 换成读书那天最低落的那组（开心 0.05、紧绷 0.97，刚读完悲伤小说）
卡 = PLAN v5 的规划器卡（replay4\plans_cmp\v5.jsonl，局面 + 要接住的 / 要说到的 / 背景），不带方向（兄长定方向只记不进卡），
心情行用线上同一个函数（kaju_core.heart.mood_line）。当时发出去的那句折起来只作参考。
输出：review\mood_page.html（collection mood，每条 {a, b, note}），对照 data\rounds_v4\replay4\mood_page_items.json
用法（AstrBot 的 Python）：python -I -X utf8 scripts\build_mood_page.py
"""
import glob
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402  sys.path / KAJU_DATA
import train_keys  # noqa: E402,F401
from kaju_core.heart.mood_line import mood_line  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
STYLE = r"D:\JiashuBot\kaju_data\self\kaju_style"
D = os.path.join(rt.ROOT, "replay4")
HAPPY = {"mood": {"joy": 0.88, "energy": 0.78, "stress": 0.06, "warm": 0.72},  # 和 exam_p3.MOODS["开心"] 一样
         "recent": [{"emo": "开心", "i": 2, "src": "person"}, {"emo": "得意", "i": 1, "src": "person"}], "threads": []}
N_NORMAL = 7


def records():
    out = {}
    for p in sorted(glob.glob(os.path.join(STYLE, "rewrites", "*.jsonl"))):
        for line in open(p, encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if (d.get("mood") or {}).get("mood"):
                out[str(d["t"])] = d
    return out


def card_of(rec, p):
    jm = p["局面"].rstrip("。")
    if p.get("要回应的"):
        jm += "。要接住的：" + p["要回应的"].rstrip("。")
    lines = [f"场合：{rec.get('kind') or '私聊'}", f"对象：{rec.get('title') or '无'}", f"局面：{jm}",
             "要说到的：" + ("；".join(x.rstrip("。；;") for x in p.get("事实") or []) or "无")]
    if p.get("背景"):
        lines.append("背景：" + "；".join(x.rstrip("。；;") for x in p["背景"][:3]))
    return "\n".join(lines)


def causes(snap):
    return [f"{e.get('emo')}{e.get('i')}：{e.get('cause')}" for e in (snap.get("recent") or []) if e.get("cause")][-4:]


def main():
    recs = records()
    plans = {str(d["t"]): d["plan"] for d in rt.jl(os.path.join(D, "plans_cmp", "v5.jsonl")) if d.get("plan")}
    low, normal = [], []
    for t, p in plans.items():
        rec = recs.get(t)
        if not rec:
            continue
        m = rec["mood"]["mood"]
        (low if m["joy"] < 0.4 or m["stress"] >= 0.6 else normal).append((t, rec, p))
    low.sort(key=lambda x: float(x[0]))
    saddest = min((r for _, r, _ in low), key=lambda r: r["mood"]["mood"]["joy"] - r["mood"]["mood"]["stress"])["mood"]
    rng = random.Random(20261116)
    normal = [x for x in normal if x[1]["mood"]["mood"]["joy"] >= 0.6 and x[1]["mood"]["mood"]["stress"] < 0.3]
    rng.shuffle(normal)
    normal = sorted(normal[:N_NORMAL], key=lambda x: float(x[0]))
    items = []
    for kind, rows in (("low", low), ("normal", normal)):
        for t, rec, p in rows:
            a, b = rec["mood"], (HAPPY if kind == "low" else saddest)
            items.append({"id": f"mood-{len(items) + 1}", "t": t, "kind": kind, "src": "group" if rec.get("kind") == "群聊" else "private",
                          "to": rec.get("title") or "无", "ctx": (rec.get("ctx") or [])[-6:] or ["（没有前文）"],
                          "card": card_of(rec, p),
                          "a": {"line": mood_line(a), "label": "她当时的心情", "causes": causes(a)},
                          "b": {"line": mood_line(b), "label": "换成开心" if kind == "low" else "换成读书那天最低落的时候", "causes": causes(b)},
                          "sent": rec.get("final") or ""})
    json.dump(items, open(os.path.join(D, "mood_page_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "mood.template.html"), encoding="utf-8").read()
    html = os.path.join(rt.VT, "review", "mood_page.html")
    open(html, "w", encoding="utf-8", newline="\n").write(tpl.replace("__ITEMS__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/")))
    print(f"心情页 {html}：{len(items)} 条（低落 {len(low)}、平常 {len(normal)}）；最低落那组：{mood_line(saddest)}", flush=True)


if __name__ == "__main__":
    main()
