r"""第 2 轮的金数据（2026-11-14，《说人话和要点卡-整合方案》第七节）：兄长两次盲选里写的 26 条备注 + 他选中 / 否掉的句子。

来源
  replay2  三种卡盲选（data\rounds_v4\replay2：key.json、write.json、votes\votes\*.json；页面 review\replay2_abc.html）
  r1ab     第 1 轮盲选（data\rounds_v4\r1：ab_key.json、ab_votes\votes\*.json；页面 review\round_r1_ab.html）——考试题，
           用了就从考试里拿掉（data\rounds_v4\exam_exclude.json，exam_p3.py 读它）

怎么变成训练数据
  金句   他亲手写的（整句改写照用；“第一句改成… / 第二句可以不要 / 前两句可以改成…”套到他选中的那句上，见 EDITS）。
         卡照他的句子倒着写（build_guide_v3 的 HIND，和训练卡同一个写法，不用线上的 EXTRACT_V4），接上当时卡的心情行。
  成对   同一张金卡，线上写手自己写 2 遍当“不要的那句”（两句是同一张卡，DPO 才成立）；写得和金句一样的丢掉。
  单条   他原样选中的（没改）→ 好；他点“都不好”的三句 → 不好（各用当时自己的卡）。
权重这里不定（第 1 轮的教训见 state.json rounds.1.verdict），交给 round_train。
输出 data\rounds_v4\r2\：gold.jsonl、pairs.jsonl、kto.jsonl、report.md。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r2.py
"""
import asyncio
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402
import build_guide_v3 as g3  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
R = rt.ROOT
OUT = os.path.join(R, "r2")

# 套到他选中那句上的改法：页面条目 id → (做法, 内容)。
#   first   换掉第一条；firstn  换掉前 n 条（内容用 / 分条）；keep  只留前 n 条；asis  他只是评论，原句照用
EDITS = {
    ("replay2", "rc2-1"): ("asis", None),            # “B其实不一定是数学题，但她这么写也可以接受”（他选的是 A）
    ("replay2", "rc2-5"): ("first", "佳树看完了兄长大人！这两个小动物好可爱啊！"),
    ("replay2", "rc2-11"): ("keep", 1),             # “第二句的原因其实说的不对，可以去掉”
    ("replay2", "rc2-13"): ("keep", 1),             # “第二句可以不要”
    ("replay2", "rc2-16"): ("firstn", (2, "兄长大人说的佳树也有点兴趣了呢")),
    ("r1ab", "r1ab-2"): ("first", "嗯，兄长大人试完之后，要把好不好吃告诉佳树哦"),
    ("r1ab", "r1ab-13"): ("rest", ["她还背了个电磁炮，名叫“光之剑：超新星”，佳树猜大部分学生都拿不动呢",
                                   "她好像还是游戏开发部的，特别爱跟同部门的学生一起玩RPG类的游戏"]),  # 换掉第二、三句
}


def page_items(path):
    html = open(path, encoding="utf-8").read()
    m = re.search(r'<script id="items" type="application/json">(.*?)</script>', html, re.S)
    return {x["id"]: x for x in json.loads(m.group(1).replace("<\\/", "</"))}


def votes(folder):
    out = {}
    for p in glob.glob(os.path.join(folder, "**", "*.json"), recursive=True):
        d = json.load(open(p, encoding="utf-8"))
        out[os.path.splitext(os.path.basename(p))[0]] = d.get("data", d)
    return out


def split(t):
    return [x for x in rt.lines(t).split("\n") if x]


def apply(how, base, note):
    lines = split(base)
    kind, arg = how
    if kind == "asis":
        return base
    if kind == "first":
        return "\n".join([arg] + lines[1:])
    if kind == "firstn":
        n, text = arg
        return "\n".join(split(text) + lines[n:])
    if kind == "keep":
        return "\n".join(lines[:arg])
    if kind == "rest":
        return "\n".join(lines[:1] + arg)
    raise ValueError(kind)


def mood_of(card):
    return next((x for x in (card or "").splitlines() if x.startswith("心情：")), "")


def field(card, name):
    m = re.search(rf"^{name}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def collect():
    """[{src, page_id, ctx, kind, to, target, edited, base_card, picked, rejected:[(text, card)]}]"""
    rows = []
    # ---- replay2：三种卡
    key = json.load(open(os.path.join(R, "replay2", "key.json"), encoding="utf-8"))
    write = {r["id"]: r for r in json.load(open(os.path.join(R, "replay2", "write.json"), encoding="utf-8"))}
    for iid, v in votes(os.path.join(R, "replay2", "votes")).items():
        k, r = key[iid], write[key[iid]["src"]]
        outs = {c: (r[f"out_{c}"], r[f"card_{c}"]) for c in "abc"}
        ch, note = v.get("choice") or "", (v.get("note") or "").strip()
        picked = k[ch] if ch in ("A", "B", "C") else None
        row = {"src": "replay2", "page_id": iid, "ctx": r["ctx"], "kind": r["kind"], "to": r["to"], "choice": ch, "note": note,
               "rejected": [outs[c] for c in "abc" if c != picked] if ch in ("A", "B", "C", "neither") else []}
        if picked:
            base, card = outs[picked]
            how = EDITS.get(("replay2", iid))
            if how:
                row.update(target=apply(how, base, note), edited=how[0] != "asis", base_card=card)
            elif note and ch:
                row.update(target=rt.lines(note), edited=rt.lines(note) != rt.lines(base), base_card=card)  # 选中又写了整句（#21、#22）
            else:
                row.update(target=rt.lines(base), edited=False, base_card=card)
        elif note:
            row.update(target=rt.lines(note), edited=True, base_card=r["card_a"])
        else:
            row.update(target="", edited=False, base_card=r["card_a"])
        rows.append(row)
    # ---- r1ab：第 1 轮盲选（考试题）
    key = json.load(open(os.path.join(R, "r1", "ab_key.json"), encoding="utf-8"))
    page = page_items(os.path.join(rt.VT, "review", "round_r1_ab.html"))
    exam = {it["id"]: it for it in json.load(open(os.path.join(rt.VT, "data", f"exam_p3_{rt.state()['live_model']}.json"), encoding="utf-8"))}
    for iid, v in votes(os.path.join(R, "r1", "ab_votes")).items():
        note = (v.get("note") or "").strip()
        if not note:
            continue
        k, it = key[iid], page[iid]
        ex = exam[k["exam"]]
        card = ex["new_card"]
        texts = {k["A"]: it["A"]["text"], k["B"]: it["B"]["text"]}
        ch = v.get("choice") or ""
        picked = k[ch] if ch in ("A", "B") else None
        how = EDITS.get(("r1ab", iid))
        target = apply(how, texts[picked], note) if how else rt.lines(note)
        rows.append({"src": "r1ab", "page_id": iid, "exam_id": k["exam"], "ctx": ex["ctx"], "kind": ex.get("kind") or "私聊",
                     "to": ex.get("title") or field(card, "对象"), "choice": ch, "note": note, "target": target, "edited": True,
                     "base_card": card, "rejected": [(t, card) for who, t in texts.items() if who != picked]})
    return rows


async def gold_card(row):
    """照他的句子倒着写卡（训练卡的写法），接上心情行。"""
    from kaju_core.voice import card as cd
    user = (f"场合：{row['kind']}\n佳树在回的人：{row['to'] or '无'}\n\n聊天：\n" + "\n".join(row["ctx"] or ["（没有前文）"]) +
            f"\n\n佳树发出去的回复：\n{row['target']}")
    for t in (0.3, 0.55):
        g = g3.parse(await rt_ask(g3.HIND.format(me="佳树"), user, t))
        if g:
            return cd.render_v4(row["kind"], row["to"], g, mood_of(row["base_card"]))
    return ""


async def rt_ask(system, user, t):
    import build_layered as bl
    return await bl.ask(system, user, t)


async def main():
    import build_layered as bl
    bl.use_gemini()
    rows = collect()
    golds = [r for r in rows if r.get("target") and r.get("edited")]
    keeps = [r for r in rows if r.get("target") and not r.get("edited")]
    cards = await asyncio.gather(*[gold_card(r) for r in golds])
    model = rt.state()["live_model"]
    os.makedirs(OUT, exist_ok=True)
    gold, pairs, kto = [], [], []
    for r, c in zip(golds, cards):
        if not c:
            print("  卡没出成，跳过", r["src"], r["page_id"], flush=True)
            continue
        rid = f"r2-{r['src']}-{r['page_id']}"
        base = {"id": rid, "src": "live", "group": rid, "ctx": r["ctx"], "card": c}
        gold.append({**base, "target": r["target"], "from": r["src"], "note": r["note"]})
        for _ in range(2):
            out = rt.write(model, r["ctx"], c)
            if out and rt.lines(out) != rt.lines(r["target"]):
                pairs.append({**base, "chosen": r["target"], "rejected": rt.lines(out), "w": 2.0})
        print(f"  {len(gold)} {rid} 点数 {len([p for p in field(c, '要说到的').split('；') if p and p != '无'])}", flush=True)
    for r in keeps:
        rid = f"r2-{r['src']}-{r['page_id']}"
        kto.append({"id": rid, "src": "live", "ctx": r["ctx"], "card": r["base_card"], "text": r["target"], "label": "good", "w": 1.0})
    for r in rows:
        if r["choice"] == "neither":
            for i, (t, c) in enumerate(r["rejected"]):
                if t and c:
                    kto.append({"id": f"r2-{r['src']}-{r['page_id']}-x{i}", "src": "taste", "ctx": r["ctx"], "card": c,
                                "text": rt.lines(t), "label": "bad", "w": 1.0})
    rt.wjl(os.path.join(OUT, "gold.jsonl"), gold)
    rt.wjl(os.path.join(OUT, "pairs.jsonl"), pairs)
    rt.wjl(os.path.join(OUT, "kto.jsonl"), kto)
    excl = sorted({r["exam_id"] for r in rows if r["src"] == "r1ab"})
    json.dump({"_说明": "这些考试题的兄长写法进了第 2 轮训练，考试时跳过（exam_p3.py）", "ids": excl},
              open(os.path.join(R, "exam_exclude.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# 第 2 轮金数据", "", f"- 金句 {len(gold)} 条（replay2 {sum(g['from'] == 'replay2' for g in gold)}、r1ab {sum(g['from'] == 'r1ab' for g in gold)}）",
          f"- 成对 {len(pairs)} 对（同一张金卡，线上写手自己写的当不要的）", f"- 单条 好 {sum(k['label'] == 'good' for k in kto)}、不好 {sum(k['label'] == 'bad' for k in kto)}",
          f"- 考试拿掉 {len(excl)} 题：{', '.join(excl)}", "", "## 金句和卡", ""]
    for g in gold:
        md += [f"### {g['id']}", "聊天最后：" + (g["ctx"][-1] if g["ctx"] else ""), "",
               "卡：" + " ｜ ".join(x for x in g["card"].splitlines() if x.startswith(("局面", "要说到的"))), "",
               "他写的：" + g["target"].replace("\n", " / "), ""]
        for p in [p for p in pairs if p["id"] == g["id"]]:
            md.append("写手写的（不要）：" + p["rejected"].replace("\n", " / "))
        md.append("")
    open(os.path.join(OUT, "report.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md[:7]), "\n→", OUT, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
