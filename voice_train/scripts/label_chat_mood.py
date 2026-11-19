r"""给人工样本补“心情”（决定 19，2026-11-12）：原作 2668 条已有心情；人工样本也要有，否则心情行会变成“原作腔”开关。

对象（按 id 去重）：训练包 stage2 的人工样本（curated，去掉重复份）、训练包 eval（考试题）、第八批 gold8（train + eval）、
第八批 30/36 代写（review8_selfrec_drafts.json）。以后的新人工样本（ab9 等）也用它补。
做法和原作一样：Gemini 只列“她回这句之前”发生的事，数字用 label_novel_mood.simulate（线上 kaju_heart 公式）算。
看完东西的那些（第八批）把当时的感受记录给它，算成一件来自“看的东西”的事。

    python -I label_chat_mood.py pilot 8   → 小试，打印
    python -I label_chat_mood.py run       → data\chat_mood\labels.jsonl（按 key 续跑）
"""
import asyncio
import json
import os
import random
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import label_novel_mood as L  # noqa: E402  (parse / simulate / ask / 感受表)
import train_keys  # noqa: E402

VT = r"D:\JiashuBot\voice_train"
PACK = os.path.join(VT, "train_pack", "kaju_train_pack", "data")
OUT_DIR = os.path.join(VT, "data", "chat_mood")
OUT = os.path.join(OUT_DIR, "labels.jsonl")
FELT = os.path.join(VT, "data", "review8_felt_g.json")

PROMPT = """下面是一段聊天，最后一行是温水佳树（初三女生，叫哥哥“兄长大人”）的回复。
我要知道：**佳树回最后这句之前**，她心里是什么状态。只看这之前发生的事；她正在回应的那一句（最后一行之前的那句）本身、以及她这句回复流露的情绪都不要算进去。
{felt}
请列出：
1. hour：这时大概是几点（0~23 的整数；看不出就按最可能的写）。
2. events：聊天里、她正在回应的那句之前，发生在她身上、让她有感受的事，按先后排，最多 6 件；没有就空列表。每件：
   - emo：只能从这些里选一个：{emos}
   - i：强度 1~3（1 一点点，2 明显，3 很强烈）。多数日常小事是 1。
   - src："person" 是人对她说了 / 做了什么；"content" 是她看的、读的、听的东西本身让她有感受
   - from_brother：是不是兄长大人对她做的 / 说的（true / false）
   - toward_her：是不是冲着她来的（别人之间的事、她旁观的为 false）
   - cause：起因，20 字以内，第三人称写事实
   - min_ago：离她回这句大概几分钟前（整数；聊天里一来一回大约 1~2 分钟）
3. carried：聊天里明确看得出、之前就压在她心里还没放下的事。一般没有，就空列表。每件：
   - emo：只能从这些里选：{thread_emos}
   - c：现在还有多重，0.5~3
   - hours_ago：大概几小时前开始的
   - from_brother：true / false
   - cause：20 字以内

只输出一个 JSON 对象，不要别的字：{{"hour": 17, "events": [...], "carried": [...]}}

聊天（最后一行是佳树的回复）：
{text}
"""

FELT_NOTE = """
另外：她回这句之前几分钟，刚看完 / 听完一个东西，当时的感受记录如下（这件事要算成一件 src="content" 的事，强度照记录，min_ago 按 1~5 分钟）：
{felt}
"""


def rows():
    seen, out = set(), []

    def add(key, ctx, target, felt_id=None, src=""):
        k = (tuple(ctx), target)
        if k in seen:
            return
        seen.add(k)
        out.append({"key": key, "ctx": ctx, "target": target, "felt_id": felt_id, "src": src})

    for line in open(os.path.join(PACK, "stage2.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        if r.get("src") == "curated":
            add(r.get("group") or r["id"], r["ctx"], r["target"], src="curated")
    for line in open(os.path.join(PACK, "eval.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        add("eval:" + r["id"], r["ctx"], r["target"], src="eval")
    for name in ("train", "eval"):
        p = os.path.join(VT, "data", "gold8", name + ".jsonl")
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            fid = re.sub(r"-\d+$", "", r["id"].removeprefix("gold-r8-"))  # 训练行的 id 带 -0 这种份数后缀
            add(r["id"], r["ctx"], r["target"], felt_id=fid, src="gold8-" + name)
    d = json.load(open(os.path.join(VT, "data", "review8_selfrec_drafts.json"), encoding="utf-8"))
    for rid in ("r8-30_browse", "r8-36_browse"):
        if str(d[rid].get("status", "")).startswith("approved"):
            add("gold-" + rid, ["兄长大人：佳树刚才刷到什么了呀"], d[rid]["final"].replace(" / ", "\n"),
                felt_id=rid.removeprefix("r8-"), src="selfrec")
    return out


def felt_text(f):
    if not f:
        return ""
    lines = [f"看的是：{f.get('title') or f.get('topic') or ''}（{f.get('genre', '')}）",
             f"整体感受：{f.get('emotion', '')} 强度 {f.get('intensity', '')}"]
    for m in f.get("moments") or []:
        lines.append(f"{m.get('t', '')} {m.get('what', '')} → {m.get('emo', '')}{m.get('strength', '')}")
    return FELT_NOTE.format(felt="\n".join(lines))


def done_keys():
    if not os.path.exists(OUT):
        return set()
    return {json.loads(x)["key"] for x in open(OUT, encoding="utf-8")}


async def label(todo, conc=4):
    k = train_keys.gemini()
    felt = json.load(open(FELT, encoding="utf-8"))
    os.makedirs(OUT_DIR, exist_ok=True)
    sem = asyncio.Semaphore(conc)
    tot = {"in": 0, "out": 0, "ok": 0, "fail": 0}
    lock = asyncio.Lock()

    async def one(r):
        text = "\n".join(r["ctx"]) + "\n佳树：" + r["target"].replace("\n", " / ")
        prompt = PROMPT.format(felt=felt_text(felt.get(r["felt_id"])) if r["felt_id"] else "",
                               emos=L.EMOS, thread_emos=L.THREAD_EMOS, text=text)
        async with sem:
            lab, usage = None, {}
            for _ in range(2):
                try:
                    out, usage = await asyncio.to_thread(L.ask, k, prompt)
                except Exception as e:  # noqa: BLE001
                    out = ""
                    print("ERR", r["key"], type(e).__name__, str(e)[:120], flush=True)
                lab = L.parse(out) if out else None
                if lab:
                    break
        async with lock:
            tot["in"] += int(usage.get("prompt_tokens", 0) or 0)
            tot["out"] += int(usage.get("completion_tokens", 0) or 0)
            if not lab:
                tot["fail"] += 1
                print("FAIL", r["key"], flush=True)
                return None
            rec = {"key": r["key"], "src": r["src"], "label": lab, "snapshot": L.simulate(lab), "by": k["model"],
                   "usage": usage, "t": int(time.time())}
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tot["ok"] += 1
            return rec

    recs = await asyncio.gather(*(one(r) for r in todo))
    print(f"完成 {tot['ok']} 条，失败 {tot['fail']}；输入 {tot['in']} 输出 {tot['out']} tokens → {OUT}")
    return [x for x in recs if x]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    rs = rows()
    have = done_keys()
    todo = [r for r in rs if r["key"] not in have]
    print(f"要补心情的样本 {len(rs)} 条，还要做 {len(todo)} 条")
    if cmd == "pilot":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        pick = random.Random(3).sample(todo, min(n, len(todo)))
        recs = asyncio.run(label(pick))
        sys.path.insert(0, r"D:\JiashuBot\bot_setup")
        from kaju_core.heart.mood_line import mood_line
        by = {r["key"]: r for r in pick}
        for rec in recs:
            r = by[rec["key"]]
            print("=====", rec["key"], "\n前:", " || ".join(r["ctx"][-3:])[-200:], "\n佳树:", r["target"][:80].replace("\n", " / "))
            for e in rec["label"]["events"]:
                print(f"  {e['emo']}{e['i']} {e['src']} {e['min_ago']}分 {e['cause']}")
            print("  →", mood_line(rec["snapshot"]))
    elif cmd == "run":
        asyncio.run(label(todo))


if __name__ == "__main__":
    main()
