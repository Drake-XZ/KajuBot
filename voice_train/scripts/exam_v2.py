"""第二版写手 kaju-writer-l2a 对线上 kaju-writer-l1a-r003 的考试（2026-11-09）。

两边各用自己的卡片和系统提示，就是各自上线时真会用的输入：
  旧：第一版卡（card_v1 / 线上记录里写手当时看到的那张）+ card.WRITE_SYSTEM[2]
  新：第二版卡（data\\layered_v2\\eval_*.jsonl 的 card；线上记录现抽 EXTRACT_V2_LIVE）+ data\\layered_v2\\system.json
卡不一样，所以"照卡"没法比，DeepSeek 看草稿（她本来想说的意思）或参考回复判：自然 / 佳树 / 意思，加各自漏答、编造。
题：layered_v2 的 eval_*（原来每晚考试的固定题）+ 最近 N 条线上记录（跳过第六、七批标过的）。每题各写 SAMPLES 遍。
输出 data\\exam_v2.json（盲选页从这里挑）+ data\\daily\\reports\\exam-v2.md
用法（AstrBot venv）：python -I exam_v2.py [--old kaju-writer-l1a-r003] [--new kaju-writer-l2a] [--live 40] [--samples 3]
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_learn as dl  # noqa: E402  (ollama_unload、hard_flags、jload、live_rw)
import replay_live_cards as rp  # noqa: E402  (JUDGE、records)

bl, card = dl.bl, dl.card
V2 = os.path.join(bl.VT, "data", "layered_v2")
OUT = os.path.join(bl.VT, "data", "exam_v2.json")
REPORT = os.path.join(bl.VT, "data", "daily", "reports", "exam-v2.md")
SYS_V2 = {int(k): v for k, v in json.load(open(os.path.join(V2, "system.json"), encoding="utf-8")).items()} \
    if os.path.exists(os.path.join(V2, "system.json")) else card.WRITE_SYSTEM


def write(model, system, ctx, card_text, draft, title):
    import urllib.request
    body = {"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 220,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": card.write_prompt(ctx, card_text)}]}
    req = urllib.request.Request(dl.OLLAMA_URL + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)["choices"][0]["message"]["content"]
            new = card.fix_formal(dl.live_rw.clean_output(out), draft or "", title)
            return new if card.sane(new, draft or new) else ""
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return ""


def fixed_items():
    items = []
    for p in sorted(glob.glob(os.path.join(V2, "eval_*.jsonl"))):
        for r in bl.load(p):
            ref = r.get("draft") or r.get("target") or ""
            m = re.search(r"^场合：(.*)$", r["card"], re.M)
            items.append({"id": r["id"], "set": os.path.basename(p)[5:-6], "kind": m.group(1) if m else "私聊",
                          "title": r.get("to", ""), "ctx": r.get("ctx") or [], "ref": ref, "ref_is": "草稿" if r.get("draft") else "参考回复",
                          "old_card": r["card_v1"], "new_card": r["card"], "draft": r.get("draft", "")})
    return items


async def live_items(n):
    used = set(dl.jload(os.path.join(bl.VT, "data", "review6_used.json"), [])) | set(dl.jload(os.path.join(bl.VT, "data", "review7_used.json"), []))
    recs = [r for r in rp.records() if str(r["t"]) not in used][-n:]

    async def one(r):
        c = card.parse(await bl.ask(card.EXTRACT_V2_LIVE, card.extract_prompt(r["ctx"], r["draft"], r["kind"], r["title"]), 0.3))
        return {"id": r["id"], "set": "线上", "kind": r["kind"], "title": r["title"], "ctx": r["ctx"], "ref": r["draft"], "ref_is": "草稿",
                "old_card": r["old_card"], "new_card": card.render(c, r["kind"], r["title"]) if c else "", "draft": r["draft"]}
    return [x for x in await asyncio.gather(*(one(r) for r in recs)) if x["new_card"]]


async def judge(it, old, new):
    jp = rp.JUDGE if it["ref_is"] == "草稿" else rp.JUDGE.replace("一份回复草稿（回复的人本来想说的意思）", "一条参考回复（回复的人本来想说的意思）") \
        .replace("草稿常常写得太满，A、B 不用把草稿每件事都说到", "A、B 不用和参考回复一字一样").replace("草稿和聊天里都没有", "参考回复和聊天里都没有")
    res = []
    for first in ("old", "new"):
        A, B = (old, new) if first == "old" else (new, old)
        u = (f"聊天：\n{chr(10).join(it['ctx'][-6:]) or '（没有前文）'}\n\n{it['ref_is']}：\n{it['ref']}\n\n"
             f"回复 A：\n{A or '（没写出来）'}\n\n回复 B：\n{B or '（没写出来）'}")
        m = re.search(r"\{.*\}", await bl.ask(jp, u, 0.1) or "", re.S)
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
        out[k] = res[0][k] and res[1][k]
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="kaju-writer-l1a-r003")
    ap.add_argument("--new", default="kaju-writer-l2a")
    ap.add_argument("--live", type=int, default=40)
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()
    items = fixed_items() + await live_items(a.live)
    print(f"{len(items)} 题 × {a.samples} 遍：{a.old}（旧卡）对 {a.new}（新卡）", flush=True)
    for side, model, system in (("old", a.old, card.WRITE_SYSTEM[2]), ("new", a.new, SYS_V2[2])):
        dl.ollama_unload([x for x in dl.ollama_loaded() if x.startswith("kaju-writer")])
        for it in items:
            it[side] = [write(model, system, it["ctx"], it[f"{side}_card"], it["draft"], it["title"]) for _ in range(a.samples)]
        print(f"  {side} 写完", flush=True)
    dl.ollama_unload([a.new])
    pairs = [(it, j) for it in items for j in range(a.samples)]
    verdicts = await asyncio.gather(*(judge(it, it["old"][j], it["new"][j]) for it, j in pairs))
    for (it, j), v in zip(pairs, verdicts):
        it.setdefault("verdicts", []).append(v)
        it.setdefault("flags_new", []).append(dl.hard_flags(it["new"][j], []))
        it.setdefault("flags_old", []).append(dl.hard_flags(it["old"][j], []))
    json.dump(items, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    score = {k: {"old": 0, "new": 0, "一样": 0} for k in ("自然", "佳树", "意思")}
    by = {}
    flags = {k: 0 for k in ("old漏答", "new漏答", "old编造", "new编造")}
    hard = {"old": 0, "new": 0}
    for (it, j), v in zip(pairs, verdicts):
        grp = f"{it['set']}·{it['kind']}"
        for k in score:
            score[k][v[k]] += 1
            by.setdefault(grp, {kk: {"old": 0, "new": 0, "一样": 0} for kk in score})[k][v[k]] += 1
        for k in flags:
            flags[k] += v[k]
        hard["old"] += bool(it["flags_old"][j])
        hard["new"] += bool(it["flags_new"][j])
    fmt = lambda d: f"新{d['new']}:旧{d['old']}（平{d['一样']}）"
    summary = (f"{len(pairs)} 对：自然 {fmt(score['自然'])}，佳树 {fmt(score['佳树'])}，意思 {fmt(score['意思'])}，"
               f"漏答 新{flags['new漏答']}/旧{flags['old漏答']}，编造 新{flags['new编造']}/旧{flags['old编造']}，硬伤 新{hard['new']}/旧{hard['old']}")
    L = [f"# 考试：{a.new}（第二版卡）对 {a.old}（第一版卡）（{time.strftime('%Y-%m-%d %H:%M')}）", "", summary, "",
         "两边各用自己上线时会用的卡和系统提示；DeepSeek 对着草稿/参考回复判，两种顺序各判一次，不一致算平；漏答/编造两次都判才算。", "",
         "| 题组 | 自然 | 佳树 | 意思 |", "|---|---|---|---|"] + \
        [f"| {g} | {fmt(d['自然'])} | {fmt(d['佳树'])} | {fmt(d['意思'])} |" for g, d in sorted(by.items())] + ["", "## 每一题", ""]
    for it in items:
        L += [f"### {it['id']}（{it['set']}，{it['kind']}，回{it['title'] or '无'}）", "", "```", *(it["ctx"][-4:] or ["（无）"]), "```",
              f"{it['ref_is']}：{it['ref']}", "", "| 旧卡 | 新卡 |", "|---|---|",
              f"| {it['old_card'].replace(chr(10), '<br>')} | {it['new_card'].replace(chr(10), '<br>')} |", ""]
        for j, v in enumerate(it["verdicts"]):
            tag = "　".join(f"{k}→{v[k]}" for k in ("自然", "佳树", "意思")) + "".join(f"　{k}" for k in flags if v[k])
            L += [f"- 第 {j + 1} 遍　{tag}", f"  - 旧：{it['old'][j]}" + (f"　⚠{'、'.join(it['flags_old'][j])}" if it["flags_old"][j] else ""),
                  f"  - 新：{it['new'][j]}" + (f"　⚠{'、'.join(it['flags_new'][j])}" if it["flags_new"][j] else "")]
        L.append("")
    open(REPORT, "w", encoding="utf-8").write("\n".join(L))
    print(summary)
    print(f"{bl.cost()}\n报告 {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
