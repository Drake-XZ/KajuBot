"""第二轮抽查意见 → 训练数据（追加到 data/stage2b_gold.jsonl）。

意见写法：
  "第一句：xxx  第三句：yyy"   → 把理想回复的第 1、3 行换成他写的
  "只留第一句" / "只要第一句"  → 只保留第 1 行
  "（然后发个害羞的表情包）"   → 去掉（表情包由 DeepSeek 草稿里的标签决定，重说层原样带过去），记在 note_meta
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
items = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "review2_items.json"), encoding="utf-8"))}
gold_path = os.path.join(ROOT, "data", "stage2b_gold.jsonl")
gold = [json.loads(l) for l in open(gold_path, encoding="utf-8") if l.strip()]
gold = [g for g in gold if not g["id"].startswith("b")]
added = []
for p in sorted(glob.glob(os.path.join(ROOT, "data", "review2_verdicts", "verdicts", "*.json"))):
    raw = json.load(open(p, encoding="utf-8"))
    v = raw.get("data", raw)
    it = items[os.path.basename(p)[:-5]]
    lines = [l for l in it["ideal"].split("\n") if l.strip()]
    note = (v.get("note") or "").strip()
    meta = " ".join(re.findall(r"[（(]([^）)]*)[）)]", note))
    note = re.sub(r"[（(][^）)]*[）)]", "", note).strip()
    if re.fullmatch(r"只(留|要)第(一|1)句", note):
        lines = lines[:1]
    else:
        for m in re.finditer(r"第([一二三四五1-5])句[：:]\s*(.*?)(?=\s*第[一二三四五1-5]句[：:]|$)", note):
            n = NUM.get(m.group(1)) or int(m.group(1))
            while len(lines) < n:
                lines.append("")
            lines[n - 1] = m.group(2).strip()
    if not note and v.get("v") != "ok":
        continue
    target = "\n".join(l for l in lines if l)
    added.append({"src": it["src"], "id": it["id"], "ctx": it["ctx"], "draft": it["draft"], "target": target,
                  "gold": "user" if note else "ok", "note_meta": meta, "orig": it.get("orig", "")})
with open(gold_path, "w", encoding="utf-8") as f:
    for r in gold + added:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"round 2: {len(added)} added ({sum(a['gold'] == 'user' for a in added)} edited by him); gold total {len(gold) + len(added)}")
for a in added:
    if a["gold"] == "user":
        print(f"  {a['id']}: {a['target'].replace(chr(10), ' / ')}" + (f"   [{a['note_meta']}]" if a["note_meta"] else ""))
