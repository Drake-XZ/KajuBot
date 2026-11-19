"""第五批：写手照卡写时改了意思的例子 → K 层训练数据 + 考试题（2026-11-09）。

来源：guard_eval（线上核对记录 124 条，Claude 标的 M=改了意思/编了事/安错了人、D=漏了要紧的），
答案在 data/review5_targets.json（每条按当时那张卡写一遍对的，尽量贴着写手原来的说法）。
卡片就用线上当时那张（写手真正看到的），上下文也是当时那份。

  python -I make_gold5.py [--dry]

做的事（和 make_gold4 一样）：
  1. 先让 DeepSeek 判一下答案算不算照卡写（AGREE）；不算的打印出来、不用。
  2. 每 3 条留 1 条做考试题 → data/review5_eval.jsonl（daily_learn 的考试会读）；
     其余追加进 data/layered_v1/stage2.jsonl（K 层：原作台词 + 兄长大人的样本），src "curated"，id "gold-r5-…"。
     先删掉上次跑出来的 gold-r5 行，所以可以反复跑。
不打印 API key。
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_layered as bl  # noqa: E402

DATA = os.path.join(bl.VT, "data")
ITEMS = os.path.join(bl.VT, "guard_eval", "items.json")
TARGETS = os.path.join(DATA, "review5_targets.json")
STAGE2 = os.path.join(DATA, "layered_v1", "stage2.jsonl")
EVAL = os.path.join(DATA, "review5_eval.jsonl")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    items = {str(i["id"]): i for i in json.load(open(ITEMS, encoding="utf-8"))}
    targets = {k: v for k, v in json.load(open(TARGETS, encoding="utf-8")).items() if not k.startswith("_")}

    async def agrees(card_text, target):
        j = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{card_text}\n\n回复：\n{target}", 0.0) or "", re.S)
        try:
            v = json.loads(j.group(0)) if j else {}
        except ValueError:
            v = {}
        return bool(v.get("ok")), str(v.get("why") or "判断失败")

    todo = [(k, items[k], t) for k, t in targets.items()]
    res = await asyncio.gather(*(agrees(it["card"], t) for _, it, t in todo))
    rows, dropped = [], []
    for (k, it, t), (ok, why) in zip(todo, res):
        if not ok:
            dropped.append((k, why))
            continue
        rows.append({"src": "curated", "id": f"gold-r5-{it['day']}-{k}", "ctx": it["ctx"], "card": it["card"],
                     "target": t, "to": it["title"], "kind": it["kind"], "card_from": "线上当时的卡"})
    for k, why in dropped:
        print(f"不算照卡，不用：#{k} {why}\n  卡：{items[k]['card'].splitlines()[-2]}\n  答：{targets[k]}")
    train = [r for i, r in enumerate(rows) if i % 3 != 2]
    exam = [r for i, r in enumerate(rows) if i % 3 == 2]
    print(f"能用 {len(rows)} 条：进 K 层训练 {len(train)} 条，留作考试题 {len(exam)} 条\n{bl.cost()}")
    if a.dry:
        return
    kept = [r for r in bl.load(STAGE2) if not str(r.get("id", "")).startswith("gold-r5-")]
    with open(STAGE2, "w", encoding="utf-8") as f:
        for r in kept + train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(EVAL, "w", encoding="utf-8") as f:
        for r in exam:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写好：{STAGE2}（共 {len(kept) + len(train)} 行）、{EVAL}")


if __name__ == "__main__":
    asyncio.run(main())
