"""去掉"草稿没忠实转述原话"的配对：原话的字二元组至少 RECALL 比例要出现在草稿里。

不然模型会学到"可以加草稿里没有的内容"（上线后就是编事实）。
用法：python -I filter_pairs.py data/stage1.jsonl data/stage2.jsonl  → 原地改写，旧文件留 .raw.jsonl
"""
import json
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
RECALL = 0.45


def grams(t):
    t = re.sub(r"[\W_]", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def recall(target, draft):
    g = grams(target)
    if not g:
        return 1.0
    return len(g & grams(draft)) / len(g)


for path in sys.argv[1:]:
    raw = path.replace(".jsonl", ".raw.jsonl")
    if not os.path.exists(raw):
        shutil.copyfile(path, raw)
    rows = [json.loads(l) for l in open(raw, encoding="utf-8") if l.strip()]
    keep = [r for r in rows if r.get("same") or recall(r["target"], r["draft"]) >= RECALL]
    with open(path, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = {}
    for r in rows:
        by.setdefault(r["src"], [0, 0])[0] += 1
    for r in keep:
        by[r["src"]][1] += 1
    print(path, {k: f"{v[1]}/{v[0]}" for k, v in by.items()})
