r"""线上回复器的例子库（2026-11-18 兄长：“做上线开关”；kaju_core\voice\replyer.py；AGENT.md 第十节）。

来源：
  1. 回放试过的例子库 data\rounds_v4\replay8\bank.json（r9\k_data stage2 已去恋爱 / 亲密：兄长认可过的线上回复 + 原作里她接带「」的话；
     不顺手叮嘱吃饭休息的筛过）
  2. 兄长在 replay8 两轮盲选里亲手写的备注 gold.jsonl / gold_c.jsonl（30 条，最像他要的样子）
每条 {situation（她接的是哪句）, line（她说的）, src, vec（bge-m3）}，写到 kaju_data\self\kaju_style\replyer_bank.json。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\build_replyer_bank.py
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8")
R8 = os.path.join(VT, "data", "rounds_v4", "replay8")
OUT = r"D:\JiashuBot\kaju_data\self\kaju_style\replyer_bank.json"
EMBED = "http://127.0.0.1:11435/api/embed"


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def embed(texts):
    out = []
    for i in range(0, len(texts), 32):
        req = urllib.request.Request(EMBED, data=json.dumps({"model": "bge-m3", "input": texts[i:i + 32]}).encode(),
                                     headers={"Content-Type": "application/json"})
        out += json.load(urllib.request.urlopen(req, timeout=120))["embeddings"]
    return out


def main():
    bank = [{k: b[k] for k in ("situation", "line", "src", "vec")} for b in json.load(open(os.path.join(R8, "bank.json"), encoding="utf-8"))]
    gold = []
    for name in ("gold.jsonl", "gold_c.jsonl"):
        p = os.path.join(R8, name)
        if os.path.exists(p):
            gold += jl(p)
    seen = set()
    add = []
    for g in gold:
        line = re.sub(r"\s*\n\s*", " / ", g["target"].strip())
        if line in seen or len(line) < 4:
            continue
        seen.add(line)
        add.append({"situation": g["said"].replace("\n", " / ")[:120], "line": line, "src": "owner"})
    for a, v in zip(add, embed([a["situation"] for a in add])):
        a["vec"] = v
    out = add + bank
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"例子库 {len(out)} 句（兄长亲手写的 {len(add)}、认可过的线上回复 {sum(b['src'] not in ('novel', 'owner') for b in bank)}、"
          f"原作 {sum(b['src'] == 'novel' for b in bank)}）→ {OUT}")


if __name__ == "__main__":
    main()
