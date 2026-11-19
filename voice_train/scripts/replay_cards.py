r"""出卡跟兄长的改法学 · 回放盲选（2026-11-13 兄长：“做回放盲选”）。

问题：草稿说多少、卡就抄多少、写手就说多少。第 1 轮兄长删掉的多余话一半本来就列在卡上（看视频讲细节、复述前文、一串追问）。
11-09 “卡上最多 3 条”盲选输 14:3（切掉了他想留的感受和追问），所以这次不设条数，只把他标过的“改前 / 改后”拿给出卡的 Gemini 当例子，
让它学他会删哪类、会留哪类。每条只用**别的**条目当例子（留一法），不让它看到自己的答案。

两步：
  cards  现在就能跑（只用 Gemini）：26 条按新办法重新出卡 → data\rounds_v4\r1\replay\cards.json，打印每条卡上点数的变化
  page   要显卡（等第 1 轮训练 / 考试跑完）：同一个线上写手，旧卡、新卡各写一遍 → 盲选页 review\replay_cards_r1.html
         （collection votes；对照 replay\ab_key.json：A/B 哪个是 old=旧卡、new=新卡）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\replay_cards.py cards|page [--round 1]
"""
import argparse
import asyncio
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I 不把脚本目录放进 sys.path
import round_train as rt  # noqa: E402  # 设好 sys.path / KAJU_DATA，借用 write()、labels_of()、lines()

sys.stdout.reconfigure(encoding="utf-8")

INTRO = """

—— 兄长大人的口味（从他改过的例子学） ——
兄长大人看过以前交给佳树的材料和她照着说出的话，改过一些。下面每个例子：草稿、当时整理出的“要说到的”、他觉得这一回该说到的。
他删掉的就是不该写进“要说到的”的那类（比如把对方发来的视频一段段讲一遍、把前面说过的再说一遍、本来没有的猜想、一下子问好几个问题）；
他照留的说明那样就好。没有条数限制：他想留的感受、追问照留，只是别把草稿里多出来的东西也搬进去。
"""


STYLE = {"v": "full"}  # full：整张旧卡 + 他的版本；cut：只列他删掉的点


def rdir(n):
    return os.path.join(rt.rdir(n), "replay" if STYLE["v"] == "full" else "replay_cut")


def points(card_text):
    line = next((x for x in (card_text or "").splitlines() if x.startswith("要说到的：")), "要说到的：")
    return [p for p in line.split("：", 1)[1].split("；") if p.strip()]


def load(n):
    """26 条：items.json + 兄长的标注 + 线上记录里的草稿、看完东西没有 + data 步骤重新整理过的卡（重点条）。"""
    items = json.load(open(os.path.join(rt.rdir(n), "items.json"), encoding="utf-8"))
    lb = rt.labels_of(n)
    recs = {str(r.get("t")): r for r in __import__("round_pick").records()}
    redone = {}
    for p in rt.jl(os.path.join(rt.rdir(n), "data", "prefs", "dpo.jsonl")) + rt.jl(os.path.join(rt.rdir(n), "data", "prefs", "heldout.jsonl")):
        if str(p.get("id", "")).startswith(f"live-r{n}-") and p.get("recarded"):
            redone[p["id"][len(f"live-r{n}-"):]] = p["card"]
    out = []
    for it in items:
        v, r = lb.get(it["id"]) or {}, recs.get(str(it["t"])) or {}
        c = (r.get("card") or [{}])[-1]
        if v.get("skip"):
            want, how = None, "不要"
        elif v.get("ok") or rt.lines(v.get("text")) == rt.lines(it["reply_raw"]):
            want, how = points(it["card"]), "照留"
        else:
            want, how = (points(redone[str(it["t"])]) if str(it["t"]) in redone else points(it["card"])), "改了"
        out.append({**it, "draft": r.get("draft") or "", "felt": "felt" in c, "label": v, "want": want, "how": how})
    return out


INTRO_CUT = """

—— 兄长大人删过的东西（从他改过的例子学） ——
兄长大人看过以前交给佳树的材料和她照着说出的话。下面是他删掉的“要说到的”：这些本来是从草稿里整理出来的，他觉得佳树这一回不该说。
整理这一份时，草稿里同一类的东西也别写进“要说到的”。别的照常整理，不用为了少而删：他想留的感受、追问照留。
"""


def examples_cut(rows, skip_id):
    """第二种给法：只列他删掉的点（第一种连旧卡整张给，Gemini 照着旧卡的长度写）。"""
    from difflib import SequenceMatcher
    cut = []
    for r in rows:
        if r["id"] == skip_id or r["want"] is None:
            continue
        for p in points(r["card"]):
            if max((SequenceMatcher(None, p, w).ratio() for w in r["want"]), default=0) < 0.5:
                cut.append(p)
    return INTRO_CUT + "\n".join(f"- {p}" for p in cut)


def examples(rows, skip_id):
    """别的条目当例子：他改过、照留的；“不要”的那条看不出该说什么，不当例子。"""
    if STYLE["v"] == "cut":
        return examples_cut(rows, skip_id)
    parts = []
    for r in rows:
        if r["id"] == skip_id or r["want"] is None or not r["draft"]:
            continue
        old = points(r["card"])
        same = old == r["want"]
        parts.append(f"草稿：{r['draft'].strip()}\n当时的要说到的：{'；'.join(old)}\n"
                     + ("他：照留" if same else f"他觉得该说到的：{'；'.join(r['want'])}"))
    return INTRO + "\n\n".join(f"例子 {i + 1}\n{p}" for i, p in enumerate(parts))


async def make_cards(n):
    import build_layered as bl
    bl.use_gemini()
    from kaju_core.senses import omni
    from kaju_core.voice import card
    rows = load(n)
    sem = asyncio.Semaphore(4)

    async def one(r):
        async with sem:
            for attempt in range(3):
                try:
                    out, _ = await omni.text(card.EXTRACT_V4 + examples(rows, r["id"]),
                                             card.extract_prompt_v4(r["train_ctx"], r["draft"], r["kind"], r["to"], r["felt"]), timeout=60)
                    g = card.parse_v4(out)
                    if g:
                        mood = next((x for x in r["card"].splitlines() if x.startswith("心情：")), "")
                        return card.render_v4(r["kind"], r["to"], g, mood)
                except Exception as e:  # noqa: BLE001
                    print("  出卡没成", r["id"], type(e).__name__, attempt + 1, flush=True)
            return ""

    new = await asyncio.gather(*[one(r) for r in rows])
    os.makedirs(rdir(n), exist_ok=True)
    res = [{"id": r["id"], "how": r["how"], "old": r["card"], "new": c, "ctx": r["train_ctx"], "kind": r["kind"], "to": r["to"],
            "draft": r["draft"], "reply": r["reply_raw"], "label": r["label"]} for r, c in zip(rows, new)]
    json.dump(res, open(os.path.join(rdir(n), "cards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    changed = 0
    for x in res:
        o, w = points(x["old"]), points(x["new"])
        changed += o != w
        print(f"{x['id']} [{x['how']}] 点数 {len(o)}→{len(w)}{'' if x['new'] else '  （没出成）'}\n  旧：{'；'.join(o)}\n  新：{'；'.join(w)}", flush=True)
    print(f"\n{len(res)} 条，卡变了的 {changed} 条 → {rdir(n)}\\cards.json", flush=True)


def make_page(n):
    st = rt.state()
    model = st["live_model"]
    res = json.load(open(os.path.join(rdir(n), "cards.json"), encoding="utf-8"))
    rng = random.Random(4242)
    page, key, same = [], {}, 0
    for x in res:
        if not x["new"] or points(x["old"]) == points(x["new"]):
            same += 1
            continue
        a, b = rt.write(model, x["ctx"], x["old"]), rt.write(model, x["ctx"], x["new"])
        if not a or not b or rt.lines(a) == rt.lines(b):
            same += 1
            continue
        iid = f"rc{n}-{len(page) + 1}"
        order = ["old", "new"]
        rng.shuffle(order)
        texts = {"old": a, "new": b}
        key[iid] = {"A": order[0], "B": order[1], "src": x["id"], "how": x["how"], "model": model}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if x["kind"] == "群聊" else "private", "to": x["to"] or "无",
                     "draft": x["draft"], "draft_label": "草稿（两边都从这份草稿出卡）",
                     "ctx": x["ctx"][-6:] or ["（没有前文）"], "A": {"text": texts[order[0]], "blocked": ""}, "B": {"text": texts[order[1]], "blocked": ""}})
        print(f"  {len(page)} 对", flush=True)
    json.dump(key, open(os.path.join(rdir(n), "ab_key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    html = os.path.join(rt.VT, "review", f"replay_cards_r{n}.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "出卡盲选 · 跟兄长改法学").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}（{len(page)} 对，卡没变或两边写得一样的跳过 {same} 条）；对照 {rdir(n)}\\ab_key.json", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cards", "page"])
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--style", choices=["full", "cut"], default="full")
    a = ap.parse_args()
    STYLE["v"] = a.style
    if a.cmd == "cards":
        asyncio.run(make_cards(a.round))
    else:
        make_page(a.round)


if __name__ == "__main__":
    main()
