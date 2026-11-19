r"""第 1 步回放（2026-11-14，《说人话和要点卡-整合方案-20261113》第三节第 1 步）：同一批线上记录、三种卡、同一个线上写手。

  A 线上：当时线上那张卡（原样）
  B 新写法：同一份草稿，EXTRACT_V4 + 每条怎么写的四条（一件事一条、语气情绪不写进去、通顺短句、专有名词照留），不限条数
  C 规划器：同一份聊天和草稿，照 MaiBot 的规划器，只写这一回合真人会说出口的那一两件事（问到的一定答）

三种卡都接上当时那张卡的心情行，同一个写手（state.json 的 live_model）各写一遍，再用 speech_check 的量尺量。
  cards   出 B、C 两种卡（Gemini）→ data\rounds_v4\replay2\cards.json
  write   三种卡各写一遍 + 量尺 → write.json、report.md（要显卡：Ollama 里的线上写手）
  page    三选一盲选页 review\replay2_abc.html（collection votes；对照 replay2\key.json）
用法：python -I -X utf8 scripts\replay_cards2.py cards|write|page|all
"""
import argparse
import asyncio
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402  sys.path / KAJU_DATA、write()、lines()
import speech_check as sc  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay2")
REWRITES = r"D:\JiashuBot\kaju_data\self\kaju_style\rewrites"

RULES = """

—— 每一条怎么写 ——
- 一件事写一条：同一句话里的意思合成一条，不要拆成两条；一条里也别把同一件事说两遍（“佳树看过每一帧并认真看过了”就是说了两遍）。
- 语气、情绪、动作不写进“要说到的”：哼、取笑、撒娇、生气、委屈、笑、认错的样子，她自己会带出来（心情另有一行）。“要说到的”只写事。比如草稿“哼，兄长大人还要取笑佳树！”这一句里没有要说的事，就不写。
- 每条写成一句通顺的短句，谁做什么写清楚，不写电报体（不写“佳树哼兄长大人取笑佳树”“怪兄长大人不要怪佳树”）。
- 草稿里的专有名词、作品名、技术名词照原样留在条目里（比如“形式化验证”“王国之泪”）。"""

PLAN = """你替佳树做回话前的准备。下面是一段聊天，和她心里打算回的话（草稿，常常写得太满：一口气想说好几件事，还带着顺手的夸奖、关心和总结）。
真人在聊天里接一句话，通常只说一两件事。请整理这一回合交给她的材料：她只看聊天和这份材料，自己把话说出来。材料里只有要说的事，没有现成的句子。只输出 JSON：
{"局面": "...", "要说到的": ["..."]}

局面：一两句话，只根据聊天写，不许用草稿里才有的信息。聊到哪了、最后这句是谁对谁说的、接的是前面哪句，最后写“轮到佳树回。”
  不写佳树接下来说什么、该怎么回、什么情绪、什么语气。最后一句里有“那个”“他”“你说的”这种指代，聊天里看得出指的是什么，顺手点明。

要说到的：这一回合她真会说出口的事，一条一件：
  - 对方问了、要她回答的，答案一定写上（是什么、名字、数字、是还是不是）；
  - 其余从草稿里挑她这一回合最想说的一两件；顺手的夸奖、关心叮嘱、总结、和她刚才说过的重复的，不写；
  - 看完视频、听完歌的感想，挑最有感觉的那一处，事实和感受写在同一条里，用平常说话的词，不用括号；
  - 至少写一条：没有要说的事时，写她怎么接住对方这一句（“佳树答应陪兄长大人聊轻松的”“佳树问学姐是不是打错字了”）。
  用概括的说法，不照抄草稿的句子，不写语气词。提到她自己写“佳树”，不写“我”；别人用聊天里的称呼，兄长大人只在他真在这段聊天里时才写；不写“你”“对方”。""" + RULES


def load() -> list[dict]:
    st = rt.state()
    model = st["live_model"]
    out = []
    for p in sorted(__import__("glob").glob(os.path.join(REWRITES, "*.jsonl"))):
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            if (d.get("config") or {}).get("card_model") != model or d.get("outcome") not in ("used", "guard_rejected"):
                continue
            c = (d.get("card") or [{}])[-1]
            card = c.get("card", "") or ""
            if "局面：" not in card or not d.get("draft"):
                continue
            out.append({"id": str(d["t"]), "kind": d.get("kind") or "私聊", "to": d.get("title") or "",
                        "ctx": d.get("ctx") or [], "draft": d["draft"], "felt": "felt" in c, "card_a": card,
                        "live": d.get("final") if d.get("outcome") == "used" else "", "outcome": d.get("outcome")})
    return out


def mood_of(card: str) -> str:
    return next((x for x in card.splitlines() if x.startswith("心情：")), "")


async def make_cards():
    import build_layered as bl
    bl.use_gemini()
    from kaju_core.senses import omni
    from kaju_core.voice import card
    rows = load()
    sem = asyncio.Semaphore(4)

    async def one(system, r):
        async with sem:
            for attempt in range(3):
                try:
                    out, _ = await omni.text(system, card.extract_prompt_v4(r["ctx"], r["draft"], r["kind"], r["to"], r["felt"]), timeout=60)
                    g = card.parse_v4(out)
                    if g:
                        return card.render_v4(r["kind"], r["to"], g, mood_of(r["card_a"]))
                except Exception as e:  # noqa: BLE001
                    print("  出卡没成", r["id"], type(e).__name__, attempt + 1, flush=True)
            return ""

    b = await asyncio.gather(*[one(card.EXTRACT_V4 + RULES, r) for r in rows])
    c = await asyncio.gather(*[one(PLAN, r) for r in rows])
    for r, cb, cc in zip(rows, b, c):
        r["card_b"], r["card_c"] = cb, cc
    os.makedirs(D, exist_ok=True)
    json.dump(rows, open(os.path.join(D, "cards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k in ("a", "b", "c"):
        n = [len(sc.points(r[f"card_{k}"])) for r in rows if r[f"card_{k}"]]
        print(f"卡 {k.upper()}：{len(n)} 张，3 点以上 {sum(x >= 3 for x in n) / max(1, len(n)):.0%}，平均 {sum(n) / max(1, len(n)):.1f} 点", flush=True)


async def write_all():
    rows = json.load(open(os.path.join(D, "cards.json"), encoding="utf-8"))
    model = rt.state()["live_model"]
    for i, r in enumerate(rows):
        for k in ("a", "b", "c"):
            r[f"out_{k}"] = rt.write(model, r["ctx"], r[f"card_{k}"]) if r[f"card_{k}"] else ""
        print(f"  写了 {i + 1}/{len(rows)}", flush=True)
    items, where = [], []
    for i, r in enumerate(rows):
        for k in ("a", "b", "c"):
            if r[f"out_{k}"]:
                items.append({"ctx": r["ctx"], "reply": r[f"out_{k}"]})
                where.append((i, k))
    js = await sc.judge_many(items)
    for (i, k), j in zip(where, js):
        r = rows[i]
        r[f"m_{k}"] = {**sc.metrics(r[f"out_{k}"], r[f"card_{k}"]), "judge": j}
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = ["# 第 1 步回放：三种卡、同一个线上写手", "", f"{len(rows)} 条线上记录（草稿都在）。量尺见 scripts\\speech_check.py；它偏宽，只拿来三种卡之间比。", "",
             "| 项 | A 线上卡 | B 新写法 | C 规划器 |", "|---|---|---|---|"]
    sums = {k: sc.summarize([{**r[f"m_{k}"]} for r in rows if r.get(f"m_{k}")]) for k in ("a", "b", "c")}
    for key in sums["a"]:
        lines.append(f"| {key} | " + " | ".join(str(sums[k].get(key, "")) for k in ("a", "b", "c")) + " |")
    open(os.path.join(D, "report.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


def make_page(n_max: int = 24):
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(20261114)
    rows = [r for r in rows if r["out_a"] and r["out_b"] and r["out_c"]
            and len({rt.lines(r["out_a"]), rt.lines(r["out_b"]), rt.lines(r["out_c"])}) == 3]
    rng.shuffle(rows)
    page, key = [], {}
    for r in rows[:n_max]:
        order = ["a", "b", "c"]
        rng.shuffle(order)
        iid = f"rc2-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "C": order[2], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["to"] or "无",
                     "ctx": r["ctx"][-6:] or ["（没有前文）"], "draft": r["draft"],
                     **{s: {"text": r[f"out_{order[i]}"]} for i, s in enumerate("ABC")}})
    json.dump(key, open(os.path.join(D, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "abc.template.html"), encoding="utf-8").read()
    html = os.path.join(rt.VT, "review", "replay2_abc.html")
    open(html, "w", encoding="utf-8", newline="\n").write(tpl.replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 条（三句都写出来且互不相同的 {len(rows)} 条里挑）", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cards", "write", "page", "all"])
    a = ap.parse_args()
    if a.cmd in ("cards", "all"):
        asyncio.run(make_cards())
    if a.cmd in ("write", "all"):
        asyncio.run(write_all())
    if a.cmd in ("page", "all"):
        make_page()


if __name__ == "__main__":
    main()
