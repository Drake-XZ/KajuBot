"""要点卡第一步盲选页：从 replay_live_cards.py 的结果挑 N 对（私聊、群聊各一半），A/B 随机。

输入 data\\cardlive_replay.json；输出 review\\ab6.html（页面）+ data\\ab6_items.json + data\\ab6_key.json（哪边是新卡，页面里没有）。
挑法：每条记录只出一对（第一遍），两句一样或有一边没写出来的不要；第六批标过的记录往后放（兄长看过）。
用法：python -I build_ab6.py [--n 30] [--seed 66]
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
    ap.add_argument("--seed", type=int, default=66)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = json.load(open(os.path.join(DATA, "cardlive_replay.json"), encoding="utf-8"))
    used6 = set(json.load(open(os.path.join(DATA, "review6_used.json"), encoding="utf-8")))
    norm = lambda s: re.sub(r"\s+", "", s or "")
    ok = [it for it in items if it["old"][0] and it["new"][0] and norm(it["old"][0]) != norm(it["new"][0])]
    pools = {}
    for it in ok:
        pools.setdefault("group" if it["kind"] == "群聊" else "private", []).append(it)
    picked = []
    for k, pool in pools.items():
        rng.shuffle(pool)
        pool.sort(key=lambda it: str(it["t"]) in used6)  # 没标过的在前（sort 稳定，前面的打乱保留）
        picked += pool[: a.n // 2]
    if len(picked) < a.n:  # 一边不够就从另一边补
        rest = [it for it in ok if it not in picked]
        rng.shuffle(rest)
        picked += rest[: a.n - len(picked)]
    rng.shuffle(picked)
    page, key = [], {}
    for n, it in enumerate(picked):
        iid = f"ab6-{n + 1}"
        order = ["old", "new"]
        rng.shuffle(order)
        key[iid] = {"A": order[0], "B": order[1], "rec": it["id"]}
        page.append({"id": iid, "n": n + 1, "src": "group" if it["kind"] == "群聊" else "private", "to": it["title"] or "无",
                     "ctx": it["ctx"][-6:] or ["（没有前文）"], "draft": it["draft"],
                     "A": {"text": it[order[0]][0], "blocked": ""}, "B": {"text": it[order[1]][0], "blocked": ""}})
    json.dump(page, open(os.path.join(DATA, "ab6_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(DATA, "ab6_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "ab6.template.html"), encoding="utf-8").read()
    blob = json.dumps(page, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(VT, "review", "ab6.html"), "w", encoding="utf-8").write(tpl.replace("__ITEMS__", blob))
    print(f"{len(page)} 对（私聊 {sum(p['src'] == 'private' for p in page)}，群聊 {sum(p['src'] == 'group' for p in page)}）→ review\\ab6.html")


if __name__ == "__main__":
    main()
