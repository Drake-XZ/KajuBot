"""把兄长大人在抽查页上的意见变成训练数据和范例。

- 写了改法（note）的条目：答案 = 他写的那句（去掉括号里的说明，空格处断成多条消息）
- 点了"可以"、没写改法的：答案 = 当时的理想回复
输出 data/stage2b_gold.jsonl：{src, ctx, draft, target, gold: "user"|"ok", note_meta}
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
items = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "review1_items.json"), encoding="utf-8"))}
out = []
for p in sorted(glob.glob(os.path.join(ROOT, "data", "review1_verdicts", "verdicts", "*.json"))):
    raw = json.load(open(p, encoding="utf-8"))
    v = raw.get("data", raw)
    it = items[os.path.basename(p)[:-5]]
    note = (v.get("note") or "").strip()
    meta = " ".join(re.findall(r"[（(]([^）)]*)[）)]", note))
    note = re.sub(r"[（(][^）)]*[）)]", "", note).strip()
    if note:
        target = "\n".join(s for s in re.split(r"(?<=[^\x00-\x7f])\s+(?=[^\x00-\x7f])", note) if s.strip())
        gold = "user"
    elif v.get("v") == "ok":
        target, gold = it["ideal"], "ok"
    else:
        continue
    out.append({"src": it["src"], "id": it["id"], "ctx": it["ctx"], "draft": it["draft"], "target": target,
                "gold": gold, "note_meta": meta, "orig": it.get("orig", "")})
with open(os.path.join(ROOT, "data", "stage2b_gold.jsonl"), "w", encoding="utf-8") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(out), "gold;", sum(r["gold"] == "user" for r in out), "rewritten by him,", sum(r["gold"] == "ok" for r in out), "approved")
for r in out:
    if r["gold"] == "user":
        print(f"  {r['id']}: {r['target'].replace(chr(10), ' / ')}" + (f"   [说明：{r['note_meta']}]" if r["note_meta"] else ""))
