"""把兄长大人给过的选择和改写整理成偏好训练数据（2026-11-10，方案见 参考MaiBot和强化学习方案.md 第三、四节）。

不花钱、不调 DeepSeek：卡片全用已有的（stage2 里的人工样本行、ab5c_cards、cardlive_replay）。
输出 data\\prefs_v1\\：
  dpo.jsonl      成对：同一份上下文 + 同一张卡，chosen = 兄长的写法/他挑的，rejected = 写手（或草稿）原来那句
  kto.jsonl      单条：盲选里他选的（good）、"都不好"的（bad）——两边卡片不一样的盲选只能这样用
  heldout.jsonl  成对，来自 review4/5/6/7_eval（考试题，不进训练）：只用来量"没见过的题上，是不是更偏向兄长的写法"
  ab7.jsonl      ab7 盲选里旧写手 r003 那一边（也不进训练，exam 里有这些题）：他选的 / 说都不好的，量同一件事

成对的来源（rejected 是什么）：
  gold-r6  第六批线上回复：写手当时发出去的那句
  gold-r4  第四批（先复述）：她当时的回复
  gold-r5  第五批（改了意思/漏了要紧的，Claude 照卡写的对的）：写手当时那句 —— 这批是"别丢信息"的方向
  gold-r7  ab6 备注里他写的：旧卡那一边页面上的那句
  gold-c   第三批：没被选中的候选（改写器的、草稿）
  gold-ab  ab3 盲选：输的那边；他改写了的 → 两边都算 rejected
  gold-s/b 第一、二批：DeepSeek 草稿；他另写了的 → 原来那份"理想回复"也算
不用的："这条不要"（多半是这条不该回或上下文坏了，不一定是句子差）、没有卡的 ab4、ab7（留着当考题）。

用法（AstrBot venv）：python -I build_prefs.py
"""
import collections
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import rewrite  # noqa: E402  (tidy_ctx)

DATA = os.path.join(bl.VT, "data")
OUT = os.path.join(DATA, "prefs_v1")


def J(name):
    return json.load(open(os.path.join(DATA, name), encoding="utf-8"))


def store(folder):
    out = {}
    for p in glob.glob(os.path.join(DATA, folder, "*", "*.json")):
        d = json.load(open(p, encoding="utf-8"))
        out[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d) if isinstance(d, dict) else {}
    return out


def msgs(t):
    """页面上几条之间用 / 隔开 → 换行（和训练目标一个样子）；不动标点，写手原来怎么写就怎么留。"""
    t = re.sub(r"\s+[/／]\s+", "\n", str(t or "").strip())
    return "\n".join(l.strip() for l in t.split("\n") if l.strip())


def norm(t):
    return re.sub(r"[\s。，,！!？?～~…、.]", "", t or "")


def main():
    stage2 = [r for r in bl.load(os.path.join(DATA, "layered_v1", "stage2.jsonl")) if r.get("src") == "curated"]
    evals = []
    for n in (4, 5, 6, 7):
        evals += bl.load(os.path.join(DATA, f"review{n}_eval.jsonl"))

    r6 = {"gold-" + it["id"]: it["reply"] for it in J("review6_items.json")}
    r4 = {"gold-" + it["id"]: it["reply"] for it in J("review4_items.json")}
    r5 = {str(it["id"]): it["new"] for it in json.load(open(os.path.join(bl.VT, "guard_eval", "items.json"), encoding="utf-8"))}
    ab6_items = {it["id"]: it for it in J("ab6_items.json")}
    ab6_key = J("ab6_key.json")
    ab6_votes = store("ab6_votes")
    rep = {x["id"]: x for x in J("cardlive_replay.json")}
    r3 = {it["id"]: it for it in J("review3_items.json")}
    ab3 = {it["id"]: it for it in J("ab3_items.json")}
    ab3_votes = store("ab3_votes")
    s12 = {it["id"]: it for it in J("review1_items.json") + J("review2_items.json")}

    def side_text(iid, side):
        k = ab6_key[iid]
        return ab6_items[iid]["A" if k["A"] == side else "B"]["text"]

    def rejected_of(row):
        """这行人工样本对应的"差的那句"（可能好几句）。"""
        rid = row["id"][3:] if row["id"].startswith("al-") else row["id"]
        if rid.startswith("gold-r6-"):
            return [r6.get(rid)], "r6"
        if rid.startswith("gold-r4-"):
            return [r4.get(rid)], "r4"
        if rid.startswith("gold-r5-"):
            return [r5.get(rid.rsplit("-", 1)[1])], "r5"
        if rid.startswith("gold-r7-"):
            return [side_text(rid[8:], "old")], "r7"
        m = re.match(r"gold-(ab|c|s|b)(\d+)", rid)
        if not m:
            return [], ""
        iid = m.group(1) + m.group(2)
        if m.group(1) == "c" and iid in r3:
            return [c["text"] for c in r3[iid]["cands"]], "c"
        if m.group(1) == "ab" and iid in ab3:
            it, v = ab3[iid], ab3_votes.get(iid, {})
            both = [it["A"]["text"], it["B"]["text"]]
            if any(norm(t) == norm(row["target"]) for t in both):  # 他原样选了一边 → 另一边算差的（"差不多"不算）
                return ([t for t in both if norm(t) != norm(row["target"])] if v.get("choice") in ("A", "B") else []), "ab"
            return both, "ab"
        if m.group(1) in "sb" and iid in s12:
            it = s12[iid]
            return [it.get("draft"), it.get("ideal")], m.group(1)
        return [], ""

    def pairs(rows):
        out, by = [], collections.defaultdict(int)
        for row in rows:
            rej, src = rejected_of(row)
            rej = [msgs(t) for t in rej if t and norm(msgs(t)) != norm(row["target"])]
            rej = list(dict.fromkeys(rej))
            if not rej:
                continue
            g = re.sub(r"-\d$", "", row["id"]) if src in ("c", "ab", "s", "b") else row["id"]
            # 同一句话有 2～3 张卡：每张卡轮着配一句不同的 rejected，不重复堆
            t = rej[by[g] % len(rej)]
            by[g] += 1
            out.append({"id": row["id"], "src": src, "ctx": row["ctx"], "card": row["card"],
                        "chosen": row["target"], "rejected": t, "card_from": row.get("card_from", "")})
        return out

    dpo = pairs(stage2)
    held = pairs(evals)

    # ---- 单条（KTO）----
    kto = []
    eval_r7 = {r["id"][8:] for r in evals if r["id"].startswith("gold-r7-")}
    for iid, v in ab6_votes.items():
        ch, note = v.get("choice"), str(v.get("note") or "")
        if iid in eval_r7 or iid not in ab6_key or "不用接" in note:
            continue
        r = rep[ab6_key[iid]["rec"]]
        ctx = rewrite.tidy_ctx(r["ctx"])[-4:] or ["（没有前文）"]
        for side in ("old", "new"):
            won = ab6_key[iid].get(ch) == side
            # 他选的那边算好的（备注里又改写了的不算，那已经在成对里）；"都不好"两边都算差的
            if ch == "neither":
                label = "bad"
            elif won and not note:
                label = "good"
            else:
                continue
            kto.append({"id": f"{iid}-{side}", "src": "ab6", "ctx": ctx, "card": r[f"{side}_card"],
                        "text": msgs(side_text(iid, side)), "label": label, "note": note})
    ly_eval = {r["id"].replace("ly-ab5-", "ab5c-") for r in bl.load(os.path.join(DATA, "layered_v1_eval.jsonl"))}
    ab5_cards, ab5_votes = J("ab5c_cards.json"), store("ab5c_votes")
    for it in J("ab5c_items.json"):
        v = ab5_votes.get(it["id"], {})
        ch = v.get("choice")
        if it["id"] in ly_eval or it["id"] not in ab5_cards or ch not in ("A", "B", "neither"):
            continue
        for s in ("A", "B"):
            if it[s].get("blocked"):
                continue
            if ch == "neither":
                label = "bad"
            elif ch == s and not v.get("note"):
                label = "good"
            else:
                continue
            kto.append({"id": f"{it['id']}-{s}", "src": "ab5c", "ctx": it["ctx"], "card": ab5_cards[it["id"]],
                        "text": msgs(it[s]["text"]), "label": label, "note": str(v.get("note") or "")})

    # ---- ab7：r003 那一边，留着量效果，不训练 ----
    ab7 = []
    exam = {x["id"]: x for x in J("exam_v2.json")}
    ab7_items, ab7_key, ab7_votes = {it["id"]: it for it in J("ab7_items.json")}, J("ab7_key.json"), store("ab7_votes")
    for iid, v in ab7_votes.items():
        k, ch, note = ab7_key[iid], v.get("choice"), str(v.get("note") or "")
        if "不要" in note:
            continue
        label = "good" if k.get(ch) == "old" else "bad" if ch == "neither" else ""
        if not label:
            continue
        x = exam[k["rec"]]
        ab7.append({"id": iid, "rec": k["rec"], "ctx": x["ctx"], "card": x["old_card"],
                    "text": msgs(ab7_items[iid]["A" if k["A"] == "old" else "B"]["text"]), "label": label, "note": note})

    os.makedirs(OUT, exist_ok=True)
    for name, rows in (("dpo", dpo), ("kto", kto), ("heldout", held), ("ab7", ab7)):
        with open(os.path.join(OUT, name + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"成对 {len(dpo)}：{dict(collections.Counter(r['src'] for r in dpo))}")
    print(f"单条 {len(kto)}：{dict(collections.Counter((r['src'], r['label']) for r in kto))}")
    print(f"留着量效果的成对 {len(held)}：{dict(collections.Counter(r['src'] for r in held))}")
    print(f"ab7（r003 那边）{len(ab7)}：{dict(collections.Counter(r['label'] for r in ab7))}")
    L = lambda t: len(norm(t))  # noqa: E731
    for src in ("r6", "r4", "r5", "r7", "c", "ab", "s", "b"):
        ps = [p for p in dpo if p["src"] == src]
        if ps:
            print(f"  {src}: chosen 平均 {sum(L(p['chosen']) for p in ps) / len(ps):.0f} 字，rejected 平均 {sum(L(p['rejected']) for p in ps) / len(ps):.0f} 字")
    for src in ("r6", "r4", "r5", "r7"):
        p = next(p for p in dpo if p["src"] == src)
        print(f"--- {p['id']}\n  卡：{p['card'].splitlines()[-2]}\n  好：{p['chosen']!r}\n  差：{p['rejected']!r}")


if __name__ == "__main__":
    main()
