"""第三轮标注 → 训练数据。

先把页面上的标注存到本地（Claude 用 ArtifactData list，out_dir = data/review3_labels），再跑：
  python -I make_gold3.py [--labels data/review3_labels/labels] [--dry]

写两样东西：
  data/stage2b_gold.jsonl   追加（先删掉上次跑出来的 c* 行，所以可以反复跑）
                            gold = "user"（他改过）或 "pick:draft|rewrite|ideal"（原样挑了一条）
  data/review3_prefs.jsonl  偏好对：他要的那条 vs 他没选的候选（以后想做 DPO 时用）
"这条不要"的和空着的都跳过。
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(t):
    return re.sub(r"\s", "", t or "")


def tidy(t):
    """His typing → training target: drop （发个表情包）notes, fix typos he kept, 。 → new message."""
    t = re.sub(r"[（(][^）)]*[）)]", "", t or "")
    t = t.replace("兄大人", "兄长大人").replace("兄长长大人", "兄长大人").replace("味增", "味噌")
    t = re.sub(r"。+(?=.)", "\n", t).replace("。", "")
    return "\n".join(l.strip() for l in t.split("\n") if l.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=os.path.join(ROOT, "data", "review3_labels", "labels"))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    items = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "review3_items.json"), encoding="utf-8"))}
    split = json.load(open(os.path.join(ROOT, "data", "review3_split.json"), encoding="utf-8"))
    for_rewriter = set(split["style"]) | set(split["feeling"])
    content = []
    gold_path = os.path.join(ROOT, "data", "stage2b_gold.jsonl")
    gold = [json.loads(l) for l in open(gold_path, encoding="utf-8") if l.strip()]
    gold = [g for g in gold if not re.fullmatch(r"c\d+", g["id"])]

    added, prefs, why = [], [], Counter()
    for p in sorted(glob.glob(os.path.join(a.labels, "*.json"))):
        raw = json.load(open(p, encoding="utf-8"))
        v = raw.get("data", raw)
        it = items.get(os.path.basename(p)[:-5])
        if not it:
            why["不认识的 id"] += 1
            continue
        raw_text = (v.get("text") or "").strip()
        text = tidy(raw_text)
        if v.get("skip"):
            why["这条不要"] += 1
            continue
        if it["id"] not in for_rewriter:
            # 改了意思 / 纠正理解：是 DeepSeek 那层的事，留着做那边的考卷
            content.append({"id": it["id"], "src": it["src"], "to": it["to"], "ctx": it["ctx"], "draft": it["draft"],
                            "his": raw_text, "cands": it["cands"]})
            why["改了意思（另存）"] += 1
            continue
        if not text:
            why["空着"] += 1
            continue
        pick = next((c["k"] for c in it["cands"] if norm(c["text"]) == norm(text)), None)
        added.append({"src": it["src"], "id": it["id"], "ctx": it["ctx"], "draft": it["draft"], "target": text,
                      "gold": f"pick:{pick}" if pick else "user", "note_meta": "", "orig": ""})
        rejected = [c["text"] for c in it["cands"] if norm(c["text"]) != norm(text)]
        if rejected:
            prefs.append({"id": it["id"], "src": it["src"], "ctx": it["ctx"], "draft": it["draft"],
                          "chosen": text, "rejected": rejected})
        why["用了"] += 1

    picks = Counter(r["gold"] for r in added)
    print(f"第三轮：{dict(why)}；{dict(picks)}；gold 一共 {len(gold) + len(added)} 条")
    for r in added:
        if r["gold"] == "user":
            print(f"  {r['id']}: {r['target'].replace(chr(10), ' / ')}")
    if a.dry:
        return
    with open(gold_path, "w", encoding="utf-8") as f:
        for r in gold + added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(ROOT, "data", "review3_prefs.jsonl"), "w", encoding="utf-8") as f:
        for r in prefs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(ROOT, "data", "review3_content.jsonl"), "w", encoding="utf-8") as f:
        for r in content:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


main()
