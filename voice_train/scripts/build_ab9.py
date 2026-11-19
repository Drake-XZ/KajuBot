"""第三版格式新写手的盲选页：线上 r003（旧格式卡）对训练包带回来的新写手（第三版格式卡），同一句话。从 exam_p3.py 的结果挑 N 对，A/B 随机。

输入 data\\exam_p3_<model>.json；输出 review\\ab9.html + data\\ab9_items.json + data\\ab9_key.json（old/new 是哪边，页面里没有）。
挑法和 ab8 一样：每题只出一对（第一遍，不挑好看的），两句一样或有一边没写出来的不要；私聊群聊各一半，线上真实题优先。
用法：python -I build_ab9.py [--model kaju-writer-p3-8b-a] [--n 30] [--seed 99]
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
    ap.add_argument("--model", default="kaju-writer-p3-8b-a")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=99)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = json.load(open(os.path.join(DATA, f"exam_p3_{a.model}.json"), encoding="utf-8"))
    norm = lambda s: re.sub(r"[\s，,。！!？?～~…]", "", s or "")  # noqa: E731
    ok = [it for it in items if it["old"][0] and it["new"][0] and norm(it["old"][0]) != norm(it["new"][0])]
    same = sum(bool(it["old"][0] and it["new"][0]) and norm(it["old"][0]) == norm(it["new"][0]) for it in items)
    pools = {}
    for it in ok:
        pools.setdefault("group" if it["kind"] == "群聊" else "private", []).append(it)
    picked = []
    for pool in pools.values():
        rng.shuffle(pool)
        pool.sort(key=lambda it: it["set"] != "线上")
        picked += pool[: a.n // 2]
    if len(picked) < a.n:
        rest = [it for it in ok if it not in picked]
        rng.shuffle(rest)
        picked += rest[: a.n - len(picked)]
    rng.shuffle(picked)
    page, key = [], {}
    for n, it in enumerate(picked):
        iid = f"ab9-{n + 1}"
        order = ["old", "new"]
        rng.shuffle(order)
        key[iid] = {"A": order[0], "B": order[1], "rec": it["id"], "model": a.model}
        page.append({"id": iid, "n": n + 1, "src": "group" if it["kind"] == "群聊" else "private", "to": it["title"] or "无", "draft": it["ref"],
                     "draft_label": "原稿（DeepSeek 写的）" if it["ref_is"] == "草稿" else "参考回复（真人或佳树原话）",
                     "ctx": it["ctx"][-6:] or ["（没有前文）"],
                     "A": {"text": it[order[0]][0], "blocked": ""}, "B": {"text": it[order[1]][0], "blocked": ""}})
    json.dump(page, open(os.path.join(DATA, "ab9_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(DATA, "ab9_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "ab9.template.html"), encoding="utf-8").read()
    blob = json.dumps(page, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(VT, "review", "ab9.html"), "w", encoding="utf-8").write(tpl.replace("__ITEMS__", blob))
    print(f"{len(items)} 题里第一遍两边写得一样的 {same} 题；挑了 {len(page)} 对（私聊 {sum(p['src'] == 'private' for p in page)}，"
          f"群聊 {sum(p['src'] == 'group' for p in page)}，线上题 {sum(it['set'] == '线上' for it in picked)}，"
          f"参考是真人或原话的 {sum(it['ref_is'] != '草稿' for it in picked)}）→ review\\ab9.html")
    print("各题来源：", {s: sum(it["set"] == s for it in picked) for s in sorted({it["set"] for it in picked})})


if __name__ == "__main__":
    main()
