r"""第 3 轮三选一盲选页（2026-11-14）：考试题上三种写法各取第 1 遍，打乱成 A/B/C。

  live_v4  线上写手 + 现在线上的卡（exam_p3_kaju-writer-p4-8b-k.json）
  live_v5  线上写手 + 带背景的卡（exam_p3_kaju-writer-p4-8b-k_v5.json）
  r3_v5    第 3 轮写手 + 带背景的卡（exam_p3_kaju-writer-p4-8b-r3_v5.json）
三句都写出来、互不相同的题里挑，私聊群聊尽量各一半。灰框里放三句共同的“要说到的”（背景只有两种卡有，不放，免得看出是哪种）。
输出 review\abc_r3.html（模板 abc.template.html，collection votes）、data\rounds_v4\r3\abc_key.json。
用法：python -I -X utf8 scripts\build_abc_r3.py [--n 24]
"""
import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def load(name):
    return {it["id"]: it for it in json.load(open(os.path.join(rt.VT, "data", f"exam_p3_{name}.json"), encoding="utf-8"))}


def first(it):
    return ((it or {}).get("new") or [""])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    a = ap.parse_args()
    live, new = rt.state()["live_model"], rt.model_name(3)
    src = {"live_v4": load(live), "live_v5": load(live + "_v5"), "r3_v5": load(new + "_v5")}
    ids = [k for k in src["r3_v5"] if all(first(s.get(k)) for s in src.values())
           and len({rt.lines(first(s[k])) for s in src.values()}) == 3]
    rng = random.Random(20261114)
    rng.shuffle(ids)
    grp = [k for k in ids if src["r3_v5"][k].get("kind") == "群聊"]
    prv = [k for k in ids if k not in grp]
    pick = (grp[:a.n // 2] + prv)[:a.n] if len(grp) < a.n // 2 else grp[:a.n // 2] + prv[:a.n - a.n // 2]
    rng.shuffle(pick)
    page, key = [], {}
    for k in pick:
        it = src["live_v4"][k]
        order = list(src)
        rng.shuffle(order)
        iid = f"abc3-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "C": order[2], "exam": k}
        must = (re.search(r"^要说到的：(.*)$", it.get("new_card") or "", re.M) or [None, it.get("must") or "无"])[1]
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if it.get("kind") == "群聊" else "private", "to": it.get("title") or "无",
                     "ctx": (it.get("ctx") or [])[-6:] or ["（没有前文）"], "draft": must,
                     **{s: {"text": first(src[order[i]][k])} for i, s in enumerate("ABC")}})
    json.dump(key, open(os.path.join(rt.rdir(3), "abc_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "abc.template.html"), encoding="utf-8").read()
    tpl = (tpl.replace("<title>三种卡盲选</title>", "<title>第 3 轮三选一</title>")
              .replace("<h1>三种卡盲选</h1>", "<h1>第 3 轮三选一</h1>")
              .replace("同一句话、同一个线上写手，只是交给她的卡不一样，写出三句。",
                       "同一道考试题写出三句：写手和交给她的卡各有不同。")
              .replace("灰框里是她当时的草稿（三张卡都从它来），想看再点开。", "灰框里是三句都要说到的事，想看再点开。")
              .replace('"她当时的草稿"', '"卡上要说到的"'))
    html = os.path.join(rt.VT, "review", "abc_r3.html")
    open(html, "w", encoding="utf-8", newline="\n").write(tpl.replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 条（私聊 {sum(p['src'] == 'private' for p in page)}、群聊 {sum(p['src'] == 'group' for p in page)}；"
          f"三句都不同的题 {len(ids)} 道）", flush=True)


if __name__ == "__main__":
    main()
