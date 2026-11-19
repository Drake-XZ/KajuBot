r"""解码 replay7 盲选（replay_brain.py 那页）：A = 草稿卡、B = 大脑卡（同一个写手 r7k）；rp7q-* 是“该回 / 不回也行”。
输出：data\rounds_v4\replay7\ab_result.md / .json
用法：python -I -X utf8 scripts\decode_replay7.py
"""
import glob
import json
import os
import re
import sys

VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(VT, "data", "rounds_v4", "replay7")
sys.stdout.reconfigure(encoding="utf-8")
NAME = {"a": "草稿卡", "b": "大脑卡", "same": "差不多", "neither": "都不好", "": "没选", "reply": "该回", "skip": "不回也行"}


def must(c):
    m = re.search(r"要说到的：(.*)", c or "")
    v = m.group(1) if m else ""
    return "" if v.strip() == "无" else v


def main():
    key = json.load(open(os.path.join(D, "key.json"), encoding="utf-8"))
    rows = {r["id"]: r for r in json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))}
    votes = {}
    for f in glob.glob(os.path.join(D, "votes_raw", "votes", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        votes[os.path.basename(f)[:-5]] = d.get("data", d)
    tally, by, out, quiet = {}, {}, [], []
    for iid in sorted(key, key=lambda s: int(s.split("-")[1])):
        k, v = key[iid], votes.get(iid, {})
        r = rows[k["src"]]
        c = v.get("choice", "")
        if k.get("single"):
            quiet.append({"id": iid, "said": r["said"], "vote": NAME.get(c, c), "note": v.get("note", ""), "out_a": r["out_a"]})
            continue
        who = k[c] if c in ("A", "B") else c
        tally[who] = tally.get(who, 0) + 1
        by.setdefault(r["kind"], {}).setdefault(who, 0)
        by[r["kind"]][who] += 1
        out.append({"id": iid, "src": k["src"], "kind": r["kind"], "win": who, "note": v.get("note", ""), "said": r["said"],
                    "draft": r["draft"], "card_a": r["card_a"], "card_b": r["card_b"], "a": r["out_a"], "b": r["out_b"], "long": r["long"]})
    L = ["# replay7 盲选结果（同一个写手 r7k：草稿卡 vs 大脑卡）", "",
         "总：" + "，".join(f"{NAME[k]} {v}" for k, v in sorted(tally.items(), key=lambda x: -x[1])), ""]
    for g, t in by.items():
        L.append(f"- {g}：" + "，".join(f"{NAME[k]} {v}" for k, v in t.items()))
    for q in quiet:
        L.append(f"- 该不该回（{q['said'][:30]!r}）：{q['vote']}" + (f"　备注：{q['note']}" if q["note"] else ""))
    L.append("")
    for o in out:
        L += [f"## {o['id']}（{o['kind']}）→ **{NAME[o['win']]}**" + (f"　备注：{o['note']}" if o["note"] else ""), "",
              "```", *o["long"][-4:], "```", "草稿：" + o["draft"].replace("\n", " / "), "",
              "草稿卡要说：" + (must(o["card_a"]) or "无"), "大脑卡要说：" + (must(o["card_b"]) or "无"), "",
              f"- 草稿卡：{o['a']}", f"- 大脑卡：{o['b']}", ""]
    open(os.path.join(D, "ab_result.md"), "w", encoding="utf-8").write("\n".join(L))
    json.dump({"tally": tally, "by": by, "quiet": quiet, "rows": out}, open(os.path.join(D, "ab_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n".join(L[:8]))
    for o in out:
        if o["note"] or o["win"] == "neither":
            print(f"=== {o['id']} {o['kind']} → {NAME[o['win']]} | 对方：{o['said'][:50]!r}")
            print("   大脑卡要说：", must(o["card_b"]) or "无")
            print("   草稿卡：", o["a"].replace("\n", " / ")[:110])
            print("   大脑卡：", o["b"].replace("\n", " / ")[:110])
            if o["note"]:
                print("   备注：", o["note"])


if __name__ == "__main__":
    main()
