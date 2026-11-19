r"""第 7 轮 K 重训的盲选页（2026-11-17 兄长：“Make the blind vote”；AGENT.md 第十节）。

用 v8 考试里两边写出来的话：同一道题、同一张 v8 卡（规划器的样子）、同一段长聊天，线上 r6 和 r7k 各取一遍
（第 1 遍一样就换第 2、3 遍，三遍都一样的跳过）。说说两道不放（不是聊天）。A / B 每条随机。
输出：review\round_r7k_ab.html、data\rounds_v4\r7k\ab_key.json（A / B 哪个是 live / new，记考题号和第几遍）。
发布成 Artifact：capabilities db + user，collection votes。
用法：python -I -X utf8 scripts\build_ab_r7k.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
LIVE, NEW = "kaju-writer-p5-8b-r6", "kaju-writer-p6-8b-r7k"
sys.stdout.reconfigure(encoding="utf-8")


def load(m):
    return {it["id"]: it for it in json.load(open(os.path.join(VT, "data", f"exam_p3_{m}_v8.json"), encoding="utf-8"))}


def norm(s):
    return "".join((s or "").split())


def main():
    A, B = load(LIVE), load(NEW)
    rng = random.Random(717)
    ids = [k for k in A if k in B and A[k].get("kind") in ("群聊", "私聊")]
    rng.shuffle(ids)
    page, key, same = [], {}, 0
    for k in ids:
        a, b = A[k], B[k]
        j = next((j for j in range(min(len(a["new"]), len(b["new"]))) if a["new"][j] and b["new"][j] and norm(a["new"][j]) != norm(b["new"][j])), None)
        if j is None:
            same += 1
            continue
        order = ["live", "new"]
        rng.shuffle(order)
        texts = {"live": a["new"][j], "new": b["new"][j]}
        iid = f"r7kab-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "live": LIVE, "new": NEW, "exam": k, "sample": j}
        card = "\n".join(x for x in (b.get("new_card") or "").splitlines() if not x.startswith("心情") and not x.startswith("场合"))
        ctx = b.get("ctx_new") or b.get("ctx") or []
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if b["kind"] == "群聊" else "private",
                     "to": b.get("title") or "无", "draft": card, "draft_label": "规划器给写手的卡（两边是同一张）",
                     "ctx": ctx[-10:] or ["（没有前文）"],
                     "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
    json.dump(key, open(os.path.join(R7K, "ab_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    tpl = tpl.replace("同一句话，现在线上的写手写一遍，这一轮本机微调出来的新写手写一遍；两边用同一张卡。",
                      "同一段聊天（长一点的前文，带时间）、同一张规划器卡，现在线上的写手写一遍，第 7 轮只重训 K 的新写手写一遍。")
    html = os.path.join(VT, "review", "round_r7k_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "写手盲选 · 第 7 轮").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 对（三遍都一样跳过 {same}；私聊 {sum(p['src'] == 'private' for p in page)}、"
          f"群聊 {sum(p['src'] == 'group' for p in page)}）；A 是新的 {sum(v['A'] == 'new' for v in key.values())} 条")


if __name__ == "__main__":
    main()
