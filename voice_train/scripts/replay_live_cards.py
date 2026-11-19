"""要点卡改进第一步的回放（voice_train\\要点卡改进方案.md）：线上抽卡换成 card.EXTRACT_LIVE 会不会更好。

拿线上 rewrites 里有卡的记录（当时的上下文 + DeepSeek 草稿 + 线上用的旧卡）：
  1. 用 EXTRACT_LIVE 从同一份草稿重抽新卡（DeepSeek 关思考）
  2. 线上写手（默认 kaju-writer-l1a-r003）照旧卡、新卡各写 SAMPLES 遍（采样条件一样，不用线上当时发出去的那句）
  3. DeepSeek 两种顺序各判一次（不一致算平）：像真人、像佳树、意思（哪条把草稿的主要意思说对、对方问的有回应），
     以及各自有没有漏掉对方问的 / 编了草稿里没有的事
输出：data\\cardlive_replay.json（全部结果，盲选页从这里挑）+ data\\daily\\reports\\cardlive-replay.md
用法（AstrBot venv）：python -I replay_live_cards.py [--writer kaju-writer-l1a-r003] [--limit N] [--samples 2]
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import card  # noqa: E402
import rewrite as live_rw  # noqa: E402

REWRITES = os.path.join(bl.PD, "astrbot_plugin_kaju_style", "rewrites")
OLLAMA = "http://127.0.0.1:11435/v1/chat/completions"
OUT = os.path.join(bl.VT, "data", "cardlive_replay.json")
REPORT = os.path.join(bl.VT, "data", "daily", "reports", "cardlive-replay.md")
MAX_POINTS = 3

JUDGE = """你在帮忙挑聊天回复。下面是一段聊天、一份回复草稿（回复的人本来想说的意思），和两条最后要发出去的回复 A、B。
回复的人是温水佳树：初三女生，叫哥哥"兄长大人"，自称"佳树"，说话软、黏人、爱用语气词，但也是个普通人在 QQ 上随手打字。
草稿常常写得太满，A、B 不用把草稿每件事都说到，说对最要紧的就好。

判断：
1. 自然：哪条更像真人在 QQ 上随手发的一条消息（日常用词、不像 AI、不像小说、不生硬、不堆一串事、不硬加关心或问题）
2. 佳树：哪条更像温水佳树会说的话（称呼、自称、语气、性格）
3. 意思：哪条把这条回复最该说的说对了（接得上对方的话、对方问的或要回应的有回应、没说错）
4. A漏答 / B漏答：对方问了或要她回应的，这条没回应，就是 true
5. A编造 / B编造：这条说了草稿和聊天里都没有的事（她做过的事、别人说过的话、具体的事实），就是 true
差不多就判"一样"。只输出 JSON：{"自然":"A|B|一样","佳树":"A|B|一样","意思":"A|B|一样","A漏答":false,"B漏答":false,"A编造":false,"B编造":false}"""


def js(v, default):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return v if v is not None else default


def ctx_of(user):
    """写手当时看到的上下文（write_prompt 的"上下文："那段）。线上抽卡用的也是同一份 ctx。"""
    m = re.match(r"上下文：\n(.*?)\n\n要点卡：\n", user or "", re.S)
    if not m or m.group(1) == "（没有前文）":
        return []
    return m.group(1).split("\n")


def records():
    out = []
    for p in sorted(glob.glob(os.path.join(REWRITES, "*.jsonl"))):
        for r in bl.load(p):
            w, c = js(r.get("writer"), []), js(r.get("card"), [])
            if not (w and c and w[0].get("user") and c[0].get("card") and r.get("draft")):
                continue
            out.append({"id": f"live-{r['t']}", "t": r["t"], "kind": r.get("kind") or "私聊", "title": r.get("title", ""),
                        "ctx": ctx_of(w[0]["user"]), "draft": r["draft"], "old_card": c[0]["card"],
                        "live_final": r.get("final", ""), "outcome": r.get("outcome", "")})
    return out


async def new_card(it):
    for attempt in range(2):
        c = card.parse(await bl.ask(card.EXTRACT_LIVE, card.extract_prompt(it["ctx"], it["draft"], it["kind"], it["title"]), 0.3))
        if c:
            c["points"] = c["points"][:MAX_POINTS]
            return c
    return None


def write(model, ctx, card_text, draft, title):
    body = {"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 220,
            "messages": [{"role": "system", "content": card.WRITE_SYSTEM[2]},
                         {"role": "user", "content": card.write_prompt(ctx, card_text)}]}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)["choices"][0]["message"]["content"]
            new = card.fix_formal(live_rw.clean_output(out), draft, title)
            return new if card.sane(new, draft) else ""
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return ""


async def judge(it, old, new):
    res = []
    for first in ("old", "new"):
        A, B = (old, new) if first == "old" else (new, old)
        u = (f"聊天：\n{chr(10).join(it['ctx'][-6:]) or '（没有前文）'}\n\n草稿：\n{it['draft']}\n\n"
             f"回复 A：\n{A or '（没写出来）'}\n\n回复 B：\n{B or '（没写出来）'}")
        m = re.search(r"\{.*\}", await bl.ask(JUDGE, u, 0.1) or "", re.S)
        try:
            v = json.loads(m.group(0)) if m else {}
        except ValueError:
            v = {}
        flip = {"A": "old", "B": "new"} if first == "old" else {"A": "new", "B": "old"}
        so, sn = ("A", "B") if first == "old" else ("B", "A")
        res.append({**{k: flip.get(v.get(k), "一样") for k in ("自然", "佳树", "意思")},
                    "old漏答": v.get(f"{so}漏答") is True, "new漏答": v.get(f"{sn}漏答") is True,
                    "old编造": v.get(f"{so}编造") is True, "new编造": v.get(f"{sn}编造") is True})
    out = {k: (res[0][k] if res[0][k] == res[1][k] else "一样") for k in ("自然", "佳树", "意思")}
    for k in ("old漏答", "new漏答", "old编造", "new编造"):
        out[k] = res[0][k] and res[1][k]  # 两次都这么判才算
    return out


def card_stats(card_text):
    get = lambda k: next((ln.split("：", 1)[1] for ln in card_text.split("\n") if ln.startswith(k + "：")), "")
    pts = [p for p in get("要点").split("；") if p.strip()]
    att = [a for a in get("态度").split("、") if a.strip()]
    ask = get("问")
    return {"points": len(pts), "attitudes": len(att), "ask": 0 if ask in ("", "无") else 1 + ask.count("；") + ask.count("、")}


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--writer", default="kaju-writer-l1a-r003")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", type=int, default=2)
    a = ap.parse_args()
    items = records()
    if a.limit:
        items = items[-a.limit:]
    print(f"{len(items)} 条线上记录，新规则重抽卡", flush=True)
    cards = await asyncio.gather(*(new_card(it) for it in items))
    items = [dict(it, new_card=card.render(c, it["kind"], it["title"])) for it, c in zip(items, cards) if c]
    print(f"抽好 {len(items)} 张；{a.writer} 照旧卡、新卡各写 {a.samples} 遍", flush=True)
    for n, it in enumerate(items):
        for side in ("old", "new"):
            it[side] = [write(a.writer, it["ctx"], it[f"{side}_card"], it["draft"], it["title"]) for _ in range(a.samples)]
        if (n + 1) % 20 == 0:
            print(f"  写了 {n + 1}/{len(items)}", flush=True)
    pairs = [(it, j) for it in items for j in range(a.samples)]
    print(f"DeepSeek 评判 {len(pairs)} 对", flush=True)
    verdicts = await asyncio.gather(*(judge(it, it["old"][j], it["new"][j]) for it, j in pairs))
    for (it, j), v in zip(pairs, verdicts):
        it.setdefault("verdicts", []).append(v)
    json.dump(items, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- 报告
    score = {k: {"old": 0, "new": 0, "一样": 0} for k in ("自然", "佳树", "意思")}
    flags = {k: 0 for k in ("old漏答", "new漏答", "old编造", "new编造")}
    by_kind = {}
    for (it, j), v in zip(pairs, verdicts):
        for k in score:
            score[k][v[k]] += 1
            by_kind.setdefault(it["kind"], {kk: {"old": 0, "new": 0, "一样": 0} for kk in score})[k][v[k]] += 1
        for k in flags:
            flags[k] += v[k]
    so = [card_stats(it["old_card"]) for it in items]
    sn = [card_stats(it["new_card"]) for it in items]
    st = lambda S, k: f"中位 {median([s[k] for s in S])}，≥3 的 {sum(s[k] >= 3 for s in S)}，≥2 的 {sum(s[k] >= 2 for s in S)}"
    fmt = lambda d: f"新{d['new']}:旧{d['old']}（平{d['一样']}）"
    lines = [f"# 要点卡第一步回放（{time.strftime('%Y-%m-%d %H:%M')}，写手 {a.writer}）", "",
             f"{len(items)} 条线上记录 × {a.samples} 遍 = {len(pairs)} 对；DeepSeek 两种顺序各判一次，不一致算平；漏答/编造两次都判才算。", "",
             "| | 新卡 | 旧卡 |", "|---|---|---|",
             f"| 自然 | {score['自然']['new']} | {score['自然']['old']} |",
             f"| 佳树 | {score['佳树']['new']} | {score['佳树']['old']} |",
             f"| 意思 | {score['意思']['new']} | {score['意思']['old']} |",
             f"| 漏答 | {flags['new漏答']} | {flags['old漏答']} |",
             f"| 编造 | {flags['new编造']} | {flags['old编造']} |", "",
             "按场合：" + "；".join(f"{k}（{sum(1 for it, _ in pairs if it['kind'] == k)} 对）自然 {fmt(d['自然'])} 佳树 {fmt(d['佳树'])} 意思 {fmt(d['意思'])}"
                                  for k, d in by_kind.items()), "",
             f"卡片：要点 旧 {st(so, 'points')}；新 {st(sn, 'points')}", "",
             f"态度两个：旧 {sum(s['attitudes'] >= 2 for s in so)}，新 {sum(s['attitudes'] >= 2 for s in sn)}；"
             f"问不止一个：旧 {sum(s['ask'] >= 2 for s in so)}，新 {sum(s['ask'] >= 2 for s in sn)}；"
             f"有问：旧 {sum(s['ask'] >= 1 for s in so)}，新 {sum(s['ask'] >= 1 for s in sn)}", "",
             "## 新卡漏答的（重点看：挑重点时是不是把对方问的挑掉了）", ""]
    worst = [(it, j, v) for (it, j), v in zip(pairs, verdicts) if v["new漏答"] and not v["old漏答"]]
    for it, j, v in worst:
        lines += [f"- {it['id']}（{it['kind']}）第 {j + 1} 遍", f"  - 对方：{(it['ctx'] or ['（无）'])[-1]}",
                  f"  - 新：{it['new'][j]}", f"  - 旧：{it['old'][j]}"]
    lines += ["", "## 每一条", ""]
    for it in items:
        lines += [f"### {it['id']}（{it['kind']}，回{it['title']}）", "", "上下文：", "```", *(it["ctx"][-4:] or ["（无）"]), "```",
                  "草稿：", "```", it["draft"], "```", "| 旧卡 | 新卡 |", "|---|---|",
                  f"| {it['old_card'].replace(chr(10), '<br>')} | {it['new_card'].replace(chr(10), '<br>')} |", ""]
        for j, v in enumerate(it["verdicts"]):
            tag = "　".join(f"{k}→{v[k]}" for k in ("自然", "佳树", "意思")) + "".join(
                f"　{k}" for k in ("new漏答", "old漏答", "new编造", "old编造") if v[k])
            lines += [f"- 第 {j + 1} 遍　{tag}", f"  - 旧：{it['old'][j]}", f"  - 新：{it['new'][j]}"]
        lines.append("")
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))
    print(f"自然 {fmt(score['自然'])}，佳树 {fmt(score['佳树'])}，意思 {fmt(score['意思'])}，"
          f"漏答 新{flags['new漏答']}/旧{flags['old漏答']}，编造 新{flags['new编造']}/旧{flags['old编造']}")
    print(f"DeepSeek {bl.USAGE['calls']} 次调用；报告 {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
