r"""解码第 7 轮 K 重训盲选（build_ab_r7k.py 那页）：votes_raw\votes\*.json + ab_key.json → 计票 + 逐条（带卡、两边的话、备注）。
输出：data\rounds_v4\r7k\ab_result.md、ab_result.json
用法：python -I -X utf8 scripts\decode_ab_r7k.py
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    key = json.load(open(os.path.join(R7K, "ab_key.json"), encoding="utf-8"))
    html = open(os.path.join(VT, "review", "round_r7k_ab.html"), encoding="utf-8").read()
    items = {x["id"]: x for x in json.loads(re.search(r'<script id="items" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))}
    votes = {}
    for f in glob.glob(os.path.join(R7K, "votes_raw", "votes", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        d = d.get("data", d)
        votes[os.path.basename(f)[:-5]] = d
    tally = {"new": 0, "live": 0, "same": 0, "neither": 0, "": 0}
    by_src = {}
    rows = []
    for iid in sorted(key, key=lambda s: int(s.split("-")[1])):
        k, v, it = key[iid], votes.get(iid, {}), items[iid]
        c = v.get("choice", "")
        who = k[c] if c in ("A", "B") else c
        tally[who] = tally.get(who, 0) + 1
        by_src.setdefault(it["src"], {}).setdefault(who, 0)
        by_src[it["src"]][who] += 1
        texts = {k["A"]: it["A"]["text"], k["B"]: it["B"]["text"]}
        rows.append({"id": iid, "exam": k["exam"], "src": it["src"], "to": it["to"], "win": who, "note": v.get("note", ""),
                     "card": it["draft"], "ctx": it["ctx"], "live": texts["live"], "new": texts["new"]})
    L = [f"# 第 7 轮盲选结果（r6 线上 vs r7k）", "", f"总：r7k {tally['new']} : r6 {tally['live']}，差不多 {tally['same']}，都不好 {tally['neither']}，没选 {tally['']}", ""]
    for s, t in by_src.items():
        L.append(f"- {s}：" + "，".join(f"{a} {b}" for a, b in t.items()))
    L.append("")
    for r in rows:
        L += [f"## {r['id']}（{r['exam']}，{r['src']}，回给 {r['to']}）→ **{r['win'] or '没选'}**" + (f"　备注：{r['note']}" if r["note"] else ""), "",
              "```", *r["ctx"][-4:], "```", "卡：" + r["card"].replace("\n", " ｜ "), "", f"- r6：{r['live']}", f"- r7k：{r['new']}", ""]
    open(os.path.join(R7K, "ab_result.md"), "w", encoding="utf-8").write("\n".join(L))
    json.dump({"tally": tally, "by_src": by_src, "rows": rows}, open(os.path.join(R7K, "ab_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n".join(L[:8]))


if __name__ == "__main__":
    main()
