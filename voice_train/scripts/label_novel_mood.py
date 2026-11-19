r"""给原作那 2668 条 K 层样本（stage2 里 src=novel）补上“她开口那一刻的心情”（2026-11-12，决定 16 之后兄长说“可以给原作标心情”）。

和线上对齐的两件事：
1. 线上记下的心情（HeartMind.mood_snapshot）是“读到这条消息、还没对它起反应”时的状态：对这条消息的感受要回完才算进去
   （kaju_heart 的 appraise 在 on_done 里跑）。所以这里也只标她最后这句话之前发生的事，不把她这句话本身的情绪算进去。
2. 数字不让模型猜：模型只说“之前发生了哪些事”（感受用 kaju_heart 的感受表、强度 0~3、起因、来自人还是内容、多久以前、
   有没有放不下的心事），心情四个数和心事分量由 kaju_core.heart.heart 里线上同一套公式算出来，强弱分布和线上一样。
   输出的 snapshot 和 mood_snapshot() 同一个结构：{mood:{joy,energy,stress,warm}, recent:[...], threads:[...]}。
   心情那一行的格式还没定（决定 16），这里只存原始读数，以后拼成哪种格式都行。

模型：Gemini 3.8 Flash（中转平台，accounts\gemini.json，文字走它的 /v1/chat/completions）。

    python -I label_novel_mood.py pilot 15     → 先标 15 条看看（结果照样存，不会重跑）
    python -I label_novel_mood.py run          → 全部标完（已有的跳过，可以随时停、接着跑）
    python -I label_novel_mood.py show 20      → 随机挑 20 条打印出来看
结果：data\novel_mood\labels.jsonl（一行一条：id、模型给的原始事件、算出来的 snapshot、用量）
"""
import asyncio
import json
import os
import random
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(os.path.dirname(VT), "bot_setup")
sys.path.insert(0, SETUP)
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")  # 找 accounts\gemini.json
from kaju_core.heart import heart  # noqa: E402
from kaju_core.senses import omni  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_keys  # noqa: E402  (训练专用的 Gemini 接口，见 train_keys.py)

STAGE2 = os.path.join(VT, "train_pack", "kaju_train_pack", "data", "stage2.jsonl")
TXT_DIR = r"D:\Persona\Kaju\txt"
OUT_DIR = os.path.join(VT, "data", "novel_mood")
OUT = os.path.join(OUT_DIR, "labels.jsonl")
BEFORE_CHARS = 2400       # 往前带多少原文
OWNER_W = 1.3             # kaju_heart 线上设置 mood.owner_weight
TURN_CAP = 0.25           # mood.turn_cap
MIN_INTENSITY = 2         # threads.min_intensity：强度到 2 才记成心事
RECENT_S, MAX_RECENT = 7200, 6   # 和 mood_snapshot() 默认一样

EMOS = "、".join(heart.EMOTIONS)
THREAD_EMOS = "、".join(sorted(heart.THREAD_EMOTIONS))

PROMPT = """下面是轻小说里的一段原文，最后一句是温水佳树（初三女生，主角温水和彦的妹妹，叫他“兄长大人”）说的话。
我要知道：**佳树说最后这句话之前**，她心里是什么状态。只看这句话之前发生的事；她对最后那句“前文”的反应、以及最后这句话本身流露的情绪都不要算进去。

请列出：
1. hour：这时大概是几点（0~23 的整数，按场景推，比如早饭 7、放学后 17、晚饭后 20、深夜 23；看不出就按最可能的写）。
2. events：这段原文里、最后那句前文之前，发生在佳树身上、让她有感受的事，按发生先后排，最多 6 件；没有就空列表。每件：
   - emo：她的感受，只能从这些里选一个：{emos}
   - i：强度 1~3（1 一点点，2 明显，3 很强烈）。多数日常小事是 1。
   - src："person" 是人对她说了 / 做了什么；"content" 是她看的、读的、吃的、玩的东西本身让她有感受
   - from_brother：这件事是不是兄长大人（温水和彦）对她做的 / 说的（true / false）
   - toward_her：这件事是不是冲着她来的（别人之间的事、她旁观的为 false）
   - cause：起因，20 字以内，用第三人称写事实，比如“兄长大人夸她做的便当好吃”
   - min_ago：离最后那句话大概几分钟前（整数）
3. carried：原文里明确写到、在这段之前就压在她心里、到现在还没放下的事（比如前一天吵架还委屈、一直在担心考试）。一般没有，就空列表。每件：
   - emo：只能从这些里选：{thread_emos}
   - c：现在还有多重，0.5~3
   - hours_ago：大概是几小时前开始的
   - from_brother：true / false
   - cause：20 字以内

只输出一个 JSON 对象，不要别的字：{{"hour": 17, "events": [...], "carried": [...]}}

原文（最后几行就是对话的前文；最后一行是佳树要说的话）：
{text}
"""


def norm_with_map(s):
    keep, idx = [], []
    for i, ch in enumerate(s):
        if ch.isspace() or ch in "…。，、！？!?,.「」“”\"『』~～—-":
            continue
        keep.append(ch)
        idx.append(i)
    return "".join(keep), idx


def load_txts():
    out = []
    for name in sorted(os.listdir(TXT_DIR)):
        if name.endswith(".txt"):
            raw = open(os.path.join(TXT_DIR, name), encoding="utf-8", errors="ignore").read()
            n, idx = norm_with_map(raw)
            out.append((name, raw, n, idx))
    return out


def locate(txts, ctx):
    """原文里找到前文最后一行的位置，返回它前面 BEFORE_CHARS 个字到它结尾。"""
    for line in reversed(ctx or []):
        k, _ = norm_with_map(line)
        k = k[:24]
        if len(k) < 6:
            continue
        for name, raw, n, idx in txts:
            p = n.find(k)
            if p >= 0:
                end_n = min(len(idx) - 1, p + len(norm_with_map(line)[0]) - 1)
                end = idx[end_n] + 1
                start = max(0, idx[p] - BEFORE_CHARS)
                cut = raw.find("\n", start)
                start = cut + 1 if 0 <= cut < idx[p] else start
                return name, raw[start:end].strip()
    return None, None


def rows():
    return [r for r in (json.loads(l) for l in open(STAGE2, encoding="utf-8")) if r.get("src") == "novel"]


def done_ids():
    if not os.path.exists(OUT):
        return {}
    d = {}
    for l in open(OUT, encoding="utf-8"):
        try:
            r = json.loads(l)
            d[r["id"]] = r
        except (json.JSONDecodeError, KeyError):
            continue
    return d


def ask(k, prompt):
    body = {"model": k["model"], "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(k["base_url"].rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client",
                                  "Authorization": "Bearer " + k["api_key"]})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    return (j["choices"][0]["message"]["content"] or "").strip(), j.get("usage") or {}


def parse(text):
    try:
        d = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    ev, ca = [], []
    for e in d.get("events") or []:
        emo = str(e.get("emo", ""))
        if emo not in heart.EMOTIONS:
            continue
        ev.append({"emo": emo, "i": max(0, min(3, int(e.get("i", 1) or 0))),
                   "src": "content" if e.get("src") == "content" else "person",
                   "from_brother": bool(e.get("from_brother")), "toward_her": e.get("toward_her", True) is not False,
                   "cause": str(e.get("cause", ""))[:40], "min_ago": max(0, int(e.get("min_ago", 5) or 0))})
    for e in d.get("carried") or []:
        emo = str(e.get("emo", ""))
        if emo not in heart.THREAD_EMOTIONS:
            continue
        ca.append({"emo": emo, "c": max(0.0, min(3.0, float(e.get("c", 1) or 0))),
                   "hours_ago": max(0.0, float(e.get("hours_ago", 12) or 0)),
                   "from_brother": bool(e.get("from_brother")), "cause": str(e.get("cause", ""))[:40]})
    try:
        hour = max(0, min(23, int(d.get("hour", 17))))
    except (TypeError, ValueError):
        hour = 17
    return {"hour": hour, "events": sorted(ev, key=lambda x: -x["min_ago"]), "carried": ca}


def simulate(lab, now=1_000_000_000.0):
    """照 HeartMind.apply / mood_now / mood_snapshot 的算法，从“平常的心情”开始把这些事一件件推进去。"""
    threads = []
    for c in lab["carried"]:
        t0 = now - c["hours_ago"] * 3600
        th = {"kind": "person", "emo": c["emo"], "status": "open", "cause": c["cause"], "t0": t0}
        # 模型给的是“现在还有多重”：反推开始时的分量，让它按半衰期淡到现在正好是这个数
        hl = heart.THREAD_HALF_LIFE_H.get(c["emo"], 12.0)
        heart.set_charge(th, c["c"] / 0.5 ** (c["hours_ago"] / hl), t0)
        threads.append(th)

    def mood_at(t, cur):
        base = heart.baselines(lab["hour"], True, heart.thread_offsets(threads, t))
        return {**base, "t": t} if not cur else heart.decay(cur, t, base)

    mood, events = None, []
    for e in lab["events"]:
        t = now - e["min_ago"] * 60
        w = (1.0 if e["toward_her"] else 0.5) * (OWNER_W if e["from_brother"] else 1.0)
        strong = e["i"] >= MIN_INTENSITY
        if e["src"] == "content":
            if strong and e["emo"] in heart.CONTENT_EMOTIONS:
                th = {"kind": "content", "emo": e["emo"], "status": "open", "cause": e["cause"], "t0": t}
                heart.set_charge(th, float(e["i"]), t)
                threads.append(th)
        elif strong and e["emo"] in heart.THREAD_EMOTIONS and (e["toward_her"] or e["emo"] == "担心"):
            th = {"kind": "person", "emo": e["emo"], "status": "open", "cause": e["cause"], "t0": t}
            heart.set_charge(th, float(e["i"]) * (OWNER_W if e["from_brother"] else 1.0), t)
            threads.append(th)
        mood = heart.push(mood_at(t, mood), e["emo"], e["i"], w, TURN_CAP)
        mood["t"] = t
        if e["i"] > 0 and e["emo"] != "平静":
            events.append({"t": t, **e})
    m = mood_at(now, mood)
    recent = [{"emo": e["emo"], "i": e["i"], "src": e["src"], "cause": e["cause"][:40], "ago": int(now - e["t"])}
              for e in events if now - e["t"] <= RECENT_S][-MAX_RECENT:]
    ths = []
    for th in threads:
        c = round(heart.thread_charge(th, now), 2)
        if c >= 0.1:
            ths.append({"emo": th["emo"], "c": c, "kind": th["kind"], "cause": th["cause"][:40]})
    return {"mood": {d: round(float(m[d]), 3) for d in heart.DIMS}, "recent": recent, "threads": ths}


async def label(todo, conc=4, provider="gemini"):
    """provider 默认 Gemini。"deepseek" 只给 Gemini 拦下的那些条用（Google 内容政策拦了约 8%，多是兄妹亲近的段落；
    兄长 11-12："这些部分用deepseek，用完立马换回gemini"）——只在 `deepseek` 命令里传，别的命令一律 Gemini。"""
    bl = None
    if provider == "deepseek":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_layered as bl  # noqa: PLC0415  (DeepSeek 客户端，关思考)
    k = train_keys.gemini()
    assert k, "accounts\\gemini_keys.json 一个 key 都没填"
    os.makedirs(OUT_DIR, exist_ok=True)
    txts = load_txts()
    sem = asyncio.Semaphore(conc)
    tot = {"in": 0, "out": 0, "ok": 0, "fail": 0}
    lock = asyncio.Lock()

    async def one(r):
        name, text = locate(txts, r["ctx"])
        if not text:
            text, name = "\n".join(r["ctx"]), None
        text = text + "\n佳树：" + r["target"]
        async with sem:
            lab, usage = None, {}
            for _ in range(2):
                try:
                    prompt = PROMPT.format(emos=EMOS, thread_emos=THREAD_EMOS, text=text)
                    if bl:
                        out, usage = (await bl.ask("你只回 JSON。", prompt, 0.2)).strip(), {}
                    else:
                        out, usage = await asyncio.to_thread(ask, k, prompt)
                except Exception as e:  # noqa: BLE001
                    out = ""
                    print("ERR", r["id"], type(e).__name__, str(e)[:120], flush=True)
                lab = parse(out) if out else None
                if lab:
                    break
        async with lock:
            tot["in"] += int(usage.get("prompt_tokens", 0) or 0)
            tot["out"] += int(usage.get("completion_tokens", 0) or 0)
            if not lab:
                tot["fail"] += 1
                print("FAIL", r["id"], flush=True)
                return
            rec = {"id": r["id"], "src_file": name, "label": lab, "snapshot": simulate(lab),
                   "by": bl.MODEL if bl else k["model"], "usage": usage, "t": int(time.time())}
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tot["ok"] += 1
            if tot["ok"] % 50 == 0:
                print(f"{tot['ok']} 条，输入 {tot['in']} 输出 {tot['out']} tokens", flush=True)

    await asyncio.gather(*(one(r) for r in todo))
    print(f"完成 {tot['ok']} 条，失败 {tot['fail']}；输入 {tot['in']} tokens，输出 {tot['out']} tokens → {OUT}")
    if bl:
        print(bl.cost())


def show(n):
    by = {r["id"]: r for r in rows()}
    d = list(done_ids().values())
    random.seed()
    for rec in random.sample(d, min(n, len(d))):
        r = by.get(rec["id"], {})
        s = rec["snapshot"]
        print("=====", rec["id"], rec["src_file"], "| 点钟", rec["label"]["hour"])
        print("前文:", " / ".join(r.get("ctx", [])[-2:])[:160])
        print("佳树:", r.get("target", ""))
        print("心情:", " ".join(f"{k}{v:.2f}" for k, v in s["mood"].items()))
        for e in rec["label"]["events"]:
            print(f"  事: {e['emo']}{e['i']} {e['src']}{' 兄长' if e['from_brother'] else ''} {e['min_ago']}分钟前 {e['cause']}")
        for c in rec["label"]["carried"]:
            print(f"  旧心事: {c['emo']} {c['c']} {c['hours_ago']}小时前 {c['cause']}")
        for t in s["threads"]:
            print(f"  → 心事 {t['emo']} {t['c']} ({t['kind']}) {t['cause']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    have = done_ids()
    todo = [r for r in rows() if r["id"] not in have]
    if cmd == "pilot":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        random.seed(12)
        asyncio.run(label(random.sample(todo, min(n, len(todo)))))
    elif cmd == "run":
        print(len(todo), "条要标（已有", len(have), "条）")
        asyncio.run(label(todo))
    elif cmd == "deepseek":  # 只补 Gemini 拦下的；补完就结束，下次 run / pilot 仍走 Gemini
        print(len(todo), "条用 DeepSeek 补（已有", len(have), "条）")
        asyncio.run(label(todo, provider="deepseek"))
    elif cmd == "show":
        show(int(sys.argv[2]) if len(sys.argv) > 2 else 20)


if __name__ == "__main__":
    main()
