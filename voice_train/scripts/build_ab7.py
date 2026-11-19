"""第二版写手盲选页：从 exam_v2.py 的结果挑 N 对（私聊、群聊各一半，线上题优先），A/B 随机。

输入 data\\exam_v2.json；输出 review\\ab7.html（页面）+ data\\ab7_items.json + data\\ab7_key.json（old/new 是哪边，页面里没有）。
挑法：每题只出一对（第一遍），两句一样或有一边没写出来的不要；线上真实题优先。
用法：python -I build_ab7.py [--n 30] [--seed 77]
"""
import argparse
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(VT, "data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=77)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = json.load(open(os.path.join(DATA, "exam_v2.json"), encoding="utf-8"))
    norm = lambda s: re.sub(r"\s+", "", s or "")
    ok = [it for it in items if it["old"][0] and it["new"][0] and norm(it["old"][0]) != norm(it["new"][0])]
    pools = {}
    for it in ok:
        pools.setdefault("group" if it["kind"] == "群聊" else "private", []).append(it)
    picked = []
    for k, pool in pools.items():
        rng.shuffle(pool)
        pool.sort(key=lambda it: it["set"] != "线上")  # 线上真实题在前（sort 稳定，前面的打乱保留）
        picked += pool[: a.n // 2]
    if len(picked) < a.n:  # 一边不够就从另一边补
        rest = [it for it in ok if it not in picked]
        rng.shuffle(rest)
        picked += rest[: a.n - len(picked)]
    rng.shuffle(picked)
    page, key = [], {}
    for n, it in enumerate(picked):
        iid = f"ab7-{n + 1}"
        order = ["old", "new"]
        rng.shuffle(order)
        key[iid] = {"A": order[0], "B": order[1], "rec": it["id"]}
        page.append({"id": iid, "n": n + 1, "src": "group" if it["kind"] == "群聊" else "private", "to": it["title"] or "无", "draft": it["ref"],
                     "draft_label": "原稿（DeepSeek 写的）" if it["ref_is"] == "草稿" else "参考回复（真人或佳树原话）",
                     "ctx": it["ctx"][-6:] or ["（没有前文）"],
                     "A": {"text": it[order[0]][0], "blocked": ""}, "B": {"text": it[order[1]][0], "blocked": ""}})
    json.dump(page, open(os.path.join(DATA, "ab7_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(DATA, "ab7_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "ab7.template.html"), encoding="utf-8").read()
    blob = json.dumps(page, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(VT, "review", "ab7.html"), "w", encoding="utf-8").write(tpl.replace("__ITEMS__", blob))
    print(f"{len(page)} 对（私聊 {sum(p['src'] == 'private' for p in page)}，群聊 {sum(p['src'] == 'group' for p in page)}）→ review\\ab7.html")


if __name__ == "__main__":
    main()
