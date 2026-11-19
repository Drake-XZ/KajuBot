r"""第 7 轮花钱之前的免费小试（2026-11-17，AGENT.md 第十节）：卡换成规划器 v6、写手看长聊天，照抄会不会少。

同一批 42 轮（replay4 里 v5 / v6 指导都有的，plans_cmp6），本地 r6（线上写手）各写一遍：
  a  旧 v4 卡（当时线上从草稿摘的）+ 短聊天（当时写手看到的那几行）
  b  v6 指导拼的卡 + 短聊天
  c  v6 指导拼的卡 + 长聊天（kaju_life 记录重建，longctx 格式；r6 没学过长聊天，只当参考）
量：照抄率（回复两字片段在“要说到的”里出现的比例）、念局面（局面的两字片段在回复里的比例）、念背景（有一条背景过半写进回复）、
字数、要点数、佳树连用。不调模型、不花钱；写的时候挂 gpu_busy（群里本来就暂停着）。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\test_r7_cards.py [write|report]
结果：data\rounds_v4\r7\cardtest.json、cardtest.md
"""
import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402  sys.path / KAJU_DATA、write()
import replay_planner as rp  # noqa: E402  records、plan_card
import prepare_r7 as p7  # noqa: E402  logs、by_chat、find_in_logs、chat_long
import speech_check as sc  # noqa: E402  metrics、_bigrams

sys.stdout.reconfigure(encoding="utf-8")
R4 = os.path.join(rt.ROOT, "replay4")
OUT = os.path.join(rt.ROOT, "r7")
WRITER = "kaju-writer-p5-8b-r6"


def addr_maker():
    os.environ.setdefault("KAJU_DATA", os.path.dirname(p7.SELF))
    from kaju_core import people
    owner = people.owner()
    addr = json.load(open(os.path.join(p7.SELF, "address_book", "addresses.json"), encoding="utf-8"))
    folks = json.load(open(os.path.join(p7.SELF, "address_book", "people.json"), encoding="utf-8"))

    def addr_of(uid, name):
        if uid == "self":
            return "佳树"
        if uid == owner:
            return "兄长大人"
        v = addr.get(uid) or {}
        if v.get("address") and "兄长" not in v["address"]:
            return v["address"]
        p = folks.get(uid) or {}
        known = [re.sub(r"\s+", "", n) for n in (name, p.get("name"), v.get("nickname")) if n and re.sub(r"\s+", "", n) != uid]
        return (known[0] if known else "") + ("学姐" if p.get("sex") == "female" else "学长")
    return addr_of


def build():
    recs = rp.records(any_model=True)
    v6 = {str(d["t"]): d["plan"] for d in rt.jl(os.path.join(R4, "plans_cmp6", "v6.jsonl")) if d.get("plan")}
    chats = p7.by_chat(p7.logs())
    addr_of = addr_maker()
    rows = []
    for t, plan in sorted(v6.items(), key=lambda x: float(x[0])):
        rec = recs.get(t)
        if not rec:
            continue
        ctx = rec.get("ctx") or []
        hit = p7.find_in_logs(ctx, chats)
        long = p7.chat_long(chats[hit[0]], hit[1], addr_of) if hit else None
        rows.append({"id": t, "kind": rec.get("kind") or "私聊", "ctx": ctx, "long": long,
                     "card_v4": (rec.get("card") or [{}])[-1].get("card") or "", "card_v6": rp.plan_card(rec, plan),
                     "sent": rec.get("final") or "", "said": rec.get("said") or ""})
    return rows


def do_write():
    from kaju_core import gpu_busy
    rows = build()
    print(f"{len(rows)} 轮；长聊天对上记录的 {sum(bool(r['long']) for r in rows)}", flush=True)
    with gpu_busy.hold("第 7 轮小试：r6 照三种卡各写一遍"):
        for i, r in enumerate(rows):
            r["a"] = rt.write(WRITER, r["ctx"], r["card_v4"])
            r["b"] = rt.write(WRITER, r["ctx"], r["card_v6"])
            r["c"] = rt.write(WRITER, r["long"] or r["ctx"], r["card_v6"])
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}/{len(rows)}", flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(rows, open(os.path.join(OUT, "cardtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写完", flush=True)


def line_of(card, key):
    m = re.search(rf"^{key}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def cover(part, reply):
    a = sc._bigrams(re.sub(r"佳树|兄长大人", "", part))
    return len(a & sc._bigrams(reply)) / len(a) if a else 0.0


def measure(reply, card):
    m = sc.metrics(reply, card)
    jm = line_of(card, "局面").split("要接住的：")[0]
    bgs = [x for x in line_of(card, "背景").split("；") if x.strip()]
    m["念局面"] = round(cover(jm, reply), 3)
    m["念背景"] = any(cover(x, reply) >= 0.5 for x in bgs)
    m["有背景"] = bool(bgs)
    return m


def do_report():
    rows = json.load(open(os.path.join(OUT, "cardtest.json"), encoding="utf-8"))
    names = {"a": "旧 v4 卡 + 短聊天", "b": "v6 卡 + 短聊天", "c": "v6 卡 + 长聊天"}
    cards = {"a": "card_v4", "b": "card_v6", "c": "card_v6"}
    stat = {}
    for k in "abc":
        ms = [measure(r[k], r[cards[k]]) for r in rows if r.get(k)]
        med = lambda key: statistics.median(m[key] for m in ms)  # noqa: E731
        withbg = [m for m in ms if m["有背景"]]
        stat[k] = {"写出来的": len(ms), "要点数中位": med("点数"), "字数中位": med("字数"), "照抄率中位": round(med("照抄率"), 2),
                   "照抄率≥0.6": round(sum(m["照抄率"] >= 0.6 for m in ms) / len(ms), 2),
                   "念局面中位": round(med("念局面"), 2),
                   "念背景": f"{sum(m['念背景'] for m in withbg)}/{len(withbg)}",
                   "佳树连用≥3": sum(m["佳树连用"] >= 3 for m in ms)}
    L = ["# 第 7 轮小试：卡和聊天长短（r6 写，42 轮）", "", "| 项 | " + " | ".join(names[k] for k in "abc") + " |", "|---|---|---|---|"]
    for key in stat["a"]:
        L.append(f"| {key} | " + " | ".join(str(stat[k][key]) for k in "abc") + " |")
    L += ["", "照抄率 = 回复里的两字片段有多少出现在卡的“要说到的”里（v4 卡要点多，天然偏高）；念局面 = 局面的两字片段有多少写进了回复；"
          "念背景 = 有背景的卡里，有一条背景过半写进回复的。", "", "## 逐条", ""]
    for r in rows:
        L += [f"### {r['id']}（{r['kind']}）", "", "**短聊天**", "", *[f"> {x}" for x in r["ctx"]], ""]
        if r.get("long"):
            L += [f"<details><summary>长聊天（{len(r['long'])} 行）</summary>", "", *[f"    {x}" for x in r["long"]], "", "</details>", ""]
        L += ["**v4 卡**", "", "```", r["card_v4"], "```", "**v6 卡**", "", "```", r["card_v6"], "```", ""]
        for k in "abc":
            L.append(f"- **{names[k]}**：{r.get(k, '').replace(chr(10), ' / ')}")
        L += [f"- 当时发的：{r['sent'].replace(chr(10), ' / ')}", ""]
    open(os.path.join(OUT, "cardtest.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:14]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="all", choices=["write", "report", "all"])
    a = ap.parse_args()
    if a.cmd in ("write", "all"):
        do_write()
    if a.cmd in ("report", "all"):
        do_report()


if __name__ == "__main__":
    main()
