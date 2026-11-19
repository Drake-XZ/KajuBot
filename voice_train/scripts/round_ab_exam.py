r"""盲选页（考试题版，2026-11-13）：线上的新回复都进了训练、留出题只有 3 条时，用考试 61 题里两边写出来的话做盲选。

同一道题、同一张卡，线上写手和这一轮写手各取第 1 遍（考试时每题各写 3 遍），写得一样的跳过；随机挑 --n 对。
输出：review\round_r<N>_ab.html（覆盖 round_train.py ab 做的那份）、data\rounds_v4\r<N>\ab_key.json（A/B 哪个是 live / new，
另记 exam 题号）。发布成 Artifact：capabilities db + user，collection votes。
用法：python -I -X utf8 scripts\round_ab_exam.py --round 1 [--n 20]
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    n = a.round
    st = rt.state()
    live, new = st["live_model"], rt.model_name(n)
    load = lambda m: {it["id"]: it for it in json.load(open(os.path.join(rt.VT, "data", f"exam_p3_{m}.json"), encoding="utf-8"))}  # noqa: E731
    A, B = load(live), load(new)
    both = [k for k in A if k in B and (A[k].get("new") or [""])[0] and (B[k].get("new") or [""])[0]
            and rt.lines(A[k]["new"][0]) != rt.lines(B[k]["new"][0])]
    rng = random.Random(500 + n)
    rng.shuffle(both)
    page, key = [], {}
    for k in both[:a.n]:
        it = A[k]
        order = ["live", "new"]
        rng.shuffle(order)
        texts = {"live": A[k]["new"][0], "new": B[k]["new"][0]}
        iid = f"r{n}ab-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "live": live, "new": new, "exam": k}
        card_text = it.get("new_card") or ""
        must = next((x.split("：", 1)[1] for x in card_text.splitlines() if x.startswith("要说到的：")), "") or str(it.get("must") or "")
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if it.get("kind") == "群聊" else "private",
                     "to": it.get("title") or "无", "draft": must, "draft_label": "卡上要说到的（两边是同一张卡）",
                     "ctx": (it.get("ctx") or [])[-6:] or ["（没有前文）"],
                     "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
    json.dump(key, open(os.path.join(rt.rdir(n), "ab_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    html = os.path.join(rt.VT, "review", f"round_r{n}_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", f"写手盲选 · 第 {n} 轮").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 对（两边写得不一样的题 {len(both)} 道，私聊 {sum(p['src'] == 'private' for p in page)}、"
          f"群聊 {sum(p['src'] == 'group' for p in page)}）", flush=True)


if __name__ == "__main__":
    main()
