r"""第 9 轮打包（2026-11-18 兄长：“开始训练”；AGENT.md 第十节）：人格对子 → r9\k_data（给 pref.py）。

  - prefs\dpo.jsonl：r7k 原来那 24 对（心情、毛病）照旧 + 人格对子（chosen = 佳树原句；rejected = Claude 写的平淡版 w=1、过头版 w=0.7）
  - prefs\heldout.jsonl：r7k 原来的 2 对 + 人格对子按对话留出约 30 句（平淡、过头都留），不训只量
  - stage2.jsonl：pref 拿来复习（防忘），用 r7k 的，去掉恋爱词表、CLOSE 挡的、和写对子时按恋爱 / 亲密跳过的那些句子
  - system.json：照 r7k
卡和聊天照 r7k stage2 那一行（句子卡、长前文）。
用法：python -I -X utf8 scripts\prepare_r9_pack.py
"""
import json
import os
import random
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
from prepare_r8_pack import romance  # noqa: E402
from prepare_r9_claude import CLOSE  # noqa: E402

R7K = os.path.join(VT, "data", "rounds_v4", "r7k", "k_data")
R9 = os.path.join(VT, "data", "rounds_v4", "r9")
OUT = os.path.join(R9, "k_data")
CLOSE_SKIP = re.compile(r"恋爱|亲密|情色|婚礼|怀孕|攻陷|占有|洗澡|表白")


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def wjl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    s2 = jl(os.path.join(R7K, "stage2.jsonl"))
    by_id = {r["id"]: r for r in s2}
    mine = jl(os.path.join(R9, "pairs_claude.jsonl"))
    bad_ids = {d["id"] for d in mine if d.get("skip") and CLOSE_SKIP.search(d["skip"])}
    bad_t = {re.sub(r"\W", "", by_id[i]["target"]) for i in bad_ids}

    def unsafe(r):
        ctx = " ".join((r.get("ctx") or [])[-2:])
        return romance(r) or bool(CLOSE.search(r["target"] + ctx)) or r["id"] in bad_ids or re.sub(r"\W", "", r["target"]) in bad_t

    keep = [r for r in s2 if not unsafe(r)]
    os.makedirs(os.path.join(OUT, "prefs"), exist_ok=True)
    wjl(os.path.join(OUT, "stage2.jsonl"), keep)
    shutil.copy(os.path.join(R7K, "system.json"), os.path.join(OUT, "system.json"))

    pairs = []
    for d in mine:
        if not d.get("flat"):
            continue
        r = by_id[d["id"]]
        base = {"src": "persona", "group": r.get("group") or r["id"], "ctx": r["ctx"], "card": r["card"], "chosen": r["target"]}
        pairs.append({**base, "id": f"persona-{d['id']}-flat", "rejected": d["flat"], "w": 1.0, "kind": "平淡"})
        pairs.append({**base, "id": f"persona-{d['id']}-over", "rejected": d["over"], "w": 0.7, "kind": "过头"})
    groups = sorted({p["group"] for p in pairs})
    random.Random(919).shuffle(groups)
    held_g = set(groups[:30])
    train = [p for p in pairs if p["group"] not in held_g]
    held = [p for p in pairs if p["group"] in held_g]
    old_dpo = jl(os.path.join(R7K, "prefs", "dpo.jsonl"))
    old_held = jl(os.path.join(R7K, "prefs", "heldout.jsonl"))
    wjl(os.path.join(OUT, "prefs", "dpo.jsonl"), old_dpo + train)
    wjl(os.path.join(OUT, "prefs", "heldout.jsonl"), old_held + held)
    open(os.path.join(OUT, "prefs", "kto.jsonl"), "w").close()
    info = {"stage2 原来": len(s2), "stage2 去掉恋爱 / 亲密": len(s2) - len(keep), "stage2 现在": len(keep),
            "人格对子（句）": len(pairs) // 2, "训练对": len(train), "留出对": len(held), "留出句": len(held_g),
            "r7k 原来的对": len(old_dpo), "r7k 原来的留出": len(old_held)}
    json.dump(info, open(os.path.join(R9, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
