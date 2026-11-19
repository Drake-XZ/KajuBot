"""第四版（最后一次大训练）写手的盲选页：线上 r003（旧格式卡）对 kaju-writer-p4-8b-k（第四版卡：没有长短、带心情行），同一句话。
从 exam_p3.py 的结果挑：
  - 成对：每题只出第一遍那对（不挑好看的），两句一样或有一边没写出来的不要；私聊（含说说）群聊各一半，A/B 随机。
  - 看完感想：旧写手没有这种卡，只给新写手那句打分（可以发 / 还行 / 不好），一题一句（第一遍）。
输出 review\\ab10.html + data\\ab10_items.json + data\\ab10_key.json（old/new 是哪边，页面里没有）。
用法：python -I build_ab10.py [--model kaju-writer-p4-8b-k] [--n 30] [--seed 1012]
票：Artifact 的 db，collection votes，doc id ab10-1…，内容 {choice: A|B|same|neither|good|meh|bad, note, at}。
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
    ap.add_argument("--model", default="kaju-writer-p4-8b-k")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1012)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = json.load(open(os.path.join(DATA, f"exam_p3_{a.model}.json"), encoding="utf-8"))
    norm = lambda s: re.sub(r"[\s，,。！!？?～~…]", "", s or "")  # noqa: E731
    paired = [it for it in items if it["old_card"] is not None]
    felt = [it for it in items if it["old_card"] is None and it["new"][0]]
    ok = [it for it in paired if it["old"][0] and it["new"][0] and norm(it["old"][0]) != norm(it["new"][0])]
    same = len(paired) - len(ok)
    pools = {}
    for it in ok:
        pools.setdefault("group" if it["kind"] == "群聊" else "private", []).append(it)
    picked = []
    for pool in pools.values():
        rng.shuffle(pool)
        picked += pool[: a.n // 2]
    if len(picked) < a.n:
        rest = [it for it in ok if it not in picked]
        rng.shuffle(rest)
        picked += rest[: a.n - len(picked)]
    rng.shuffle(picked)
    page, key = [], {}
    for n, it in enumerate(picked):
        iid = f"ab10-{n + 1}"
        order = ["old", "new"]
        rng.shuffle(order)
        key[iid] = {"A": order[0], "B": order[1], "rec": it["id"], "model": a.model}
        page.append({"id": iid, "n": n + 1, "src": "group" if it["kind"] == "群聊" else "private", "to": it["title"] or "无",
                     "draft": it["ref"], "draft_label": "原稿（DeepSeek 写的）" if it["ref_is"] == "草稿" else "参考回复（你改过的或佳树原话）",
                     "ctx": it["ctx"][-6:] or ["（没有前文）"],
                     "A": {"text": it[order[0]][0], "blocked": ""}, "B": {"text": it[order[1]][0], "blocked": ""}})
    for k, it in enumerate(felt):
        iid = f"ab10-{len(picked) + k + 1}"
        key[iid] = {"single": "new", "rec": it["id"], "model": a.model}
        page.append({"id": iid, "n": len(picked) + k + 1, "src": "felt", "single": True, "to": it["title"] or "兄长大人",
                     "must": [p.strip() for p in re.split(r"[；;]", it["must"]) if p.strip()],
                     "draft": it["ref"], "draft_label": "你写的那版（第八批）",
                     "ctx": it["ctx"][-6:] or ["（没有前文）"], "A": {"text": it["new"][0], "blocked": ""}})
    json.dump(page, open(os.path.join(DATA, "ab10_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(DATA, "ab10_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "ab10.template.html"), encoding="utf-8").read()
    blob = json.dumps(page, ensure_ascii=False).replace("</", "<\\/")
    open(os.path.join(VT, "review", "ab10.html"), "w", encoding="utf-8").write(tpl.replace("__ITEMS__", blob))
    print(f"{len(paired)} 道成对题里第一遍两边写得差不多一样的 {same} 题；挑了 {len(picked)} 对（私聊 {sum(p['src'] == 'private' for p in page)}，"
          f"群聊 {sum(p['src'] == 'group' for p in page)}）+ 看完感想 {len(felt)} 句 → review\\ab10.html")
    print("各题来源：", {s: sum(it["set"] == s for it in picked) for s in sorted({it["set"] for it in picked})})


if __name__ == "__main__":
    main()
