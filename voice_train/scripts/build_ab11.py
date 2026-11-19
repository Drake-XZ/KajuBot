"""换卡写法的盲选页（2026-11-12，try_fixes.py 的两项，写手都是 kaju-writer-p4-8b-k，不重新训练）：
  1–9   “无”卡：原来的“无”卡 vs 补上“要接住什么”的卡（Claude 手写，hand_cards.json）；卡上写“不用回”的那边显示（不回）
  10–17 看完感想：感受写在括号里 vs 感受写进事实里（Claude 手写）
两边都取第一遍（不挑好看的），A/B 随机。哪边是新写法在 data\\ab11_key.json（before/after）。
输出 review\\ab11.html + data\\ab11_items.json + data\\ab11_key.json。票：db collection votes，doc ab11-N。
用法：python -I -X utf8 build_ab11.py [--seed 1112]
"""
import argparse
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(VT, "data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1112)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    nop = json.load(open(os.path.join(DATA, "try_fixes", "nopoint_hand.json"), encoding="utf-8"))
    felt = json.load(open(os.path.join(DATA, "try_fixes", "felt_hand.json"), encoding="utf-8"))
    page, key = [], {}
    rows = [("nopoint", r) for r in nop] + [("felt", r) for r in felt]
    for n, (part, r) in enumerate(rows):
        iid = f"ab11-{n + 1}"
        texts = {"before": r["before"][0], "after": (r["after"][0] if r["after"] else "（不回）")}
        order = ["before", "after"]
        rng.shuffle(order)
        key[iid] = {"A": order[0], "B": order[1], "rec": r["id"], "part": part}
        src = "felt" if part == "felt" else ("group" if r.get("kind") == "群聊" else "private")
        page.append({"id": iid, "n": n + 1, "src": src, "to": r.get("title") or "兄长大人", "draft": r["ref"],
                     "draft_label": "参考回复（你改过的或你写的）", "ctx": r["ctx"][-6:] or ["（没有前文）"],
                     "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
    json.dump(page, open(os.path.join(DATA, "ab11_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(DATA, "ab11_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "ab11.template.html"), encoding="utf-8").read()
    blob = json.dumps(page, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(VT, "review", "ab11.html"), "w", encoding="utf-8").write(tpl.replace("__ITEMS__", blob))
    print(f"“无”卡 {len(nop)} 对 + 看完感想 {len(felt)} 对 → review\\ab11.html")


if __name__ == "__main__":
    main()
