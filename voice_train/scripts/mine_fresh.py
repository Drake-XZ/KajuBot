r"""换法挖反例（2026-11-12，兄长："换法挖"）：在训练没见过的卡上让 8b-A 写，挑出差的当单条反例（KTO 的 bad）。

为什么换：mine_prefs.py 在训练过的卡上挖，8b-A 七成一字不差背出原答案，挖不到东西。
这里的卡是新出的：
  1. 上下文：AstrBot 聊天记录（astrbot_plugin_kaju_life\log）里"轮到佳树回"的地方——她真回过的那一刻，取前面最多 8 行。
  2. 卡：Gemini 3.8 Flash 按训练包的新格式出"局面 / 要说到的"（和第 14 条线上普通聊天一致；不带"长短"、不带心情）。
  3. 8b-A（本机 Ollama，关思考）照卡写 2 句，用检测打分，差的记成反例；chosen 不需要（KTO 单条）。
检测只用来挑训练用的反例，线上不改她一个字：
  念卡   卡里每条要点被回复里 4 个字以上的原样片段盖住了几成（写手照念的那种 ≥ 0.8）
  我     自称"我"（引号里的不算）
  哥     私聊兄长大人时叫"哥 / 哥哥"
  套话   "今天累不累"这类
  打转   同一段四个字重复 4 次以上
  漏卡   回复里冒出"要说到的："这类卡片格式

    python -I mine_fresh.py pilot 5     → 小试 5 张卡，打印出来看
    python -I mine_fresh.py run [N]     → data\prefs_v2\fresh_cards.jsonl / fresh_raw.jsonl（都可续跑）→ fresh_kto.jsonl
    python -I mine_fresh.py pick        → 只按已有样本重新挑
"""
import glob
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
sys.path.insert(0, r"D:\JiashuBot\bot_setup")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kaju_core.senses import omni  # noqa: E402
import train_keys  # noqa: E402  (训练专用的 Gemini 接口，见 train_keys.py)
import mine_prefs as mp  # noqa: E402  (写手调用、lcs、打转检测)

VT = mp.VT
OUT = mp.OUT
CARDS = os.path.join(OUT, "fresh_cards.jsonl")
RAW = os.path.join(OUT, "fresh_raw.jsonl")
KTO = os.path.join(OUT, "fresh_kto.jsonl")
INST = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
LOGS = os.path.join(INST, "data", "plugin_data", "astrbot_plugin_kaju_life", "log")
OWNER = "111111111"
MAX = 300
TAILS = mp.TAILS
LEAK = re.compile(r"要说到的|^(场合|对象|局面)：", re.M)

PLAN = """你替佳树想好这一回要说什么，写成一张"要点卡"，交给另一个只会照卡说话的写手。
只回 JSON：{"局面": "…", "要说到的": ["…", "…"]}
- 局面：一两句交代刚才聊到哪、谁说了什么、这一句在问什么，最后写"轮到佳树回。"不写佳树的心情。
- 要说到的：佳树这一回真正要说出来的内容，每条一件、6 到 20 个字的短事实，0 到 4 条；只是应一声、没有要说的具体内容就给空列表。
  不要替她写成句子，不写语气词和口癖。不编聊天里和她身上没有的事。
- 卡里提到她自己写"佳树"，不写"我"；称呼按聊天里的名字写，兄长大人只在他真在这段聊天里时才写。
- 不该她插话、或者她说什么都多余，也照样给一张：要说到的留空。"""


JUDGE = """你在帮忙挑训练用的反例。下面是一段聊天、交给写手的要点卡、和写手照卡写出的佳树的回复。
佳树是兄长大人的妹妹，自称"佳树"，叫哥哥"兄长大人"。兄长大人改她的回复时，一贯会改掉下面这些毛病：
  我：自称"我"（引号里引用别人的话不算）
  叫法：私聊里叫兄长"哥 / 哥哥 / 你"，或者叫错人、对着不在场的人说话（比如群里没有兄长大人却喊兄长大人）
  念卡：把要点卡上的字一条条照念出来，像在报告，不像聊天
  套话：和这段聊天无关的客套尾巴，比如"今天累不累呀""兄长大人在忙什么呀"
  说过头：情绪说得比事情本身夸张很多
  编造：说了聊天和卡里都没有的具体事实
  没接住：没回应对方这句在说的、在问的，答非所问
  漏点：卡上"要说到的"有一条以上没说到
  别扭：读不通、半截话、重复打转
只看明显的毛病，拿不准就不算。每个毛病都要从回复里原样摘出出问题的那几个字当证据。
只回 JSON：{"bad": [{"label": "叫法", "quote": "回复里原样的几个字"}], "why": "一句话"}，没有毛病就 {"bad": [], "why": ""}。"""
JUDGE_LABELS = ("我", "叫法", "念卡", "套话", "说过头", "编造", "没接住", "漏点", "别扭")
# 小试里 Gemini 判"我""漏点""没接住"常判错（回复里没有"我"也说有、说到了也说漏），这几样只靠规则或删要点的反例；
# 其余几样也要摘得出原话才算。
JUDGE_KEEP = ("叫法", "套话", "说过头", "编造", "别扭")
JUDGED = os.path.join(OUT, "fresh_judge.jsonl")


def persona():
    db = sqlite3.connect("file:" + os.path.join(INST, "data", "data_v4.db") + "?mode=ro", uri=True)
    return db.execute("select system_prompt from personas where persona_id='default'").fetchone()[0]


def windows():
    out = []
    for p in sorted(glob.glob(os.path.join(LOGS, "*.jsonl"))):
        day = os.path.basename(p)[:-6]
        rs = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
        by = {}
        for i, r in enumerate(rs):
            by.setdefault(str(r.get("c", "")), []).append(r)
        for chat, xs in by.items():
            group = chat.startswith("g")
            for j, r in enumerate(xs):
                if r.get("u") != "self" or j == 0 or xs[j - 1].get("u") == "self":
                    continue  # 她真回过的那一刻，前一句是别人说的
                prev = xs[max(0, j - 8):j]
                lines = []
                for q in prev:
                    x = re.sub(r"\s*\n\s*", " / ", str(q.get("x") or "").strip())
                    if not x:
                        continue
                    who = "佳树" if q.get("u") == "self" else ("兄长大人" if str(q.get("u")) == OWNER else str(q.get("n") or "群友"))
                    lines.append(f"{who}：{x[:300]}")
                last = prev[-1]
                to = "兄长大人" if str(last.get("u")) == OWNER else str(last.get("n") or "")
                if not lines or len(str(last.get("x") or "")) < 2 or str(last.get("x", "")).startswith("/"):
                    continue
                if not group and str(last.get("u")) != OWNER:
                    continue  # 私聊只取兄长大人的（别人的私聊多是 B 站 / 测试）
                out.append({"id": f"{day}-{chat}-{j}", "kind": "群聊" if group else "私聊", "to": to, "ctx": lines})
    return out


def gemini(k, system, user):
    body = {"model": k["model"], "temperature": 0.3,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(k["base_url"].rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client",
                                  "Authorization": "Bearer " + k["api_key"]})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return (d["choices"][0]["message"]["content"] or "").strip(), d.get("usage") or {}


def plan(k, sysmsg, w):
    user = f"场合：{w['kind']}\n对象：{w['to'] or '无'}\n\n聊天：\n" + "\n".join(w["ctx"])
    for _ in range(3):
        try:
            text, u = gemini(k, sysmsg, user)
            j = json.loads(text[text.find("{"):text.rfind("}") + 1])
            scene = str(j.get("局面") or "").strip()
            pts = [str(x).strip("。；; ") for x in j.get("要说到的") or [] if str(x).strip()][:4]
            if scene:
                card = (f"场合：{w['kind']}\n对象：{w['to'] or '无'}\n局面：{scene}\n要说到的：" + ("；".join(pts) or "无"))
                return card, u
        except Exception as e:  # noqa: BLE001
            print("  重试", type(e).__name__, str(e)[:120], flush=True)
    return "", {}


def cover(point, text, n=4):
    if len(point) < n:
        return 1.0 if point in text else 0.0
    hit = [False] * len(point)
    for i in range(len(point) - n + 1):
        if point[i:i + n] in text:
            for j in range(i, i + n):
                hit[j] = True
    return sum(hit) / len(point)


def judge(w, card, text):
    pts = mp.points(card)
    cv = sum(cover(p, text) for p in pts) / len(pts) if pts else 0.0
    f = {"copy": round(cv, 2), "wo": mp.first_person(text),
         "ge": len(re.findall(r"哥", text)) if w["kind"] == "私聊" else 0,
         "tail": sum(x in text for x in TAILS), "loop": mp.loops(text), "leak": int(bool(LEAK.search(text)))}
    bad = []
    if len(pts) >= 2 and sum(map(len, pts)) >= 24 and cv >= 0.85:  # 短要点（"辛苦了"）说出来本来就是原字，不算念卡
        bad.append("念卡")
    if f["wo"]:
        bad.append("我")
    if f["ge"]:
        bad.append("哥")
    if f["tail"]:
        bad.append("套话")
    if f["loop"] >= 4:
        bad.append("打转")
    if f["leak"]:
        bad.append("漏卡")
    f["bad"] = bad
    return f


def jl(p):
    return [json.loads(x) for x in open(p, encoding="utf-8")] if os.path.exists(p) else []


def deepseek_client():
    """和 build_layered 同一个 DeepSeek（关思考），这里要同步调用。"""
    from openai import OpenAI  # noqa: PLC0415
    import build_layered as bl  # noqa: PLC0415
    cli = OpenAI(api_key=bl.ds.api_key, base_url=str(bl.ds.base_url), timeout=120, max_retries=0)

    def call(system, user):
        r = cli.chat.completions.create(model=bl.MODEL, temperature=0.3, extra_body=bl.NOTHINK,
                                        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        u = r.usage
        return (r.choices[0].message.content or "").strip(), {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens}
    return call, bl.MODEL


def judge_all(k, provider="gemini"):
    """按兄长的改法看每一句（已看过的不重看）。默认 Gemini；provider="deepseek" 只在 `judge-ds` 命令里用
    （11-12 夜中转平台 Gemini 全部"账号用尽"，兄长："这步用DeepSeek"），用完下次 run 仍是 Gemini。"""
    have = {x["sid"] for x in jl(JUDGED)}
    todo = [(r, s) for r in jl(RAW) for s in r["samples"] if f"{r['id']}-{s['seed']}" not in have]
    tok = {"in": 0, "out": 0}
    if provider == "deepseek":
        ds, by = deepseek_client()
        ask = lambda system, user: ds(system, user)  # noqa: E731
    else:
        by = k["model"]
        ask = lambda system, user: gemini(k, system, user)  # noqa: E731

    def one(a):
        r, s = a
        user = (f"场合：{r['kind']}\n对象：{r['to'] or '无'}\n\n聊天：\n" + "\n".join(r["ctx"]) +
                f"\n\n要点卡：\n{r['card']}\n\n佳树的回复：\n{s['text']}")
        for _ in range(3):
            try:
                text, u = ask(JUDGE, user)
                j = json.loads(text[text.find("{"):text.rfind("}") + 1])
                tok["in"] += u.get("prompt_tokens", 0)
                tok["out"] += u.get("completion_tokens", 0)
                bad = []
                for b in j.get("bad") or []:
                    lab, q = (b.get("label"), str(b.get("quote") or "").strip()) if isinstance(b, dict) else (b, "")
                    if lab in JUDGE_KEEP and len(q) >= 2 and q in s["text"]:
                        bad.append(lab)
                return {"sid": f"{r['id']}-{s['seed']}", "bad": sorted(set(bad)), "raw": j.get("bad"),
                        "why": str(j.get("why") or "")[:120], "by": by}
            except Exception as e:  # noqa: BLE001
                print("  重试", type(e).__name__, str(e)[:120], flush=True)
        return None

    with ThreadPoolExecutor(4) as ex, open(JUDGED, "a", encoding="utf-8") as fo:
        for x in ex.map(one, todo):
            if x:
                fo.write(json.dumps(x, ensure_ascii=False) + "\n")
    if todo:
        print(f"{by} 看了 {len(todo)} 句，输入 {tok['in']} 输出 {tok['out']} tokens", flush=True)


def judged_bad(g, r, s):
    """DeepSeek 把"叫法"那条读反了（以为该叫"哥哥"、不该叫"兄长大人"），201 条里大半是错的。
    它判的"叫法"只在摘出的原话真是问题时才算：私聊叫"哥 / 你"，或兄长大人不在这段聊天里却喊了他。"""
    bad = set(g.get("bad") or [])
    if not str(g.get("by", "")).startswith("deepseek") or "叫法" not in bad:
        return bad
    bad.discard("叫法")
    owner_here = any(x.startswith("兄长大人：") for x in r["ctx"])
    for b in g.get("raw") or []:
        if not isinstance(b, dict) or b.get("label") != "叫法":
            continue
        q = str(b.get("quote") or "")
        if q not in s["text"]:
            continue
        if (r["kind"] == "私聊" and ("哥" in q.replace("兄长", "") or "你" in q)) or ("兄长大人" in q and not owner_here):
            bad.add("叫法")
    return bad


REVIEW = os.path.join(OUT, "fresh_review.json")


def pick():
    """人工复核（fresh_review.json，11-12 Claude 逐条看了 DeepSeek 判出的 149 句）优先：null = 不算反例，列表 = 最终的毛病。"""
    raw = jl(RAW)
    jd = {x["sid"]: x for x in jl(JUDGED)}
    rev = json.load(open(REVIEW, encoding="utf-8")) if os.path.exists(REVIEW) else {}
    out, why, n = [], {}, 0
    for r in raw:
        for s in r["samples"]:
            n += 1
            g = jd.get(f"{r['id']}-{s['seed']}") or {}
            sid = f"{r['id']}-{s['seed']}"
            if sid in rev:
                if rev[sid]["bad"] is None:
                    continue
                bad = sorted(set(rev[sid]["bad"]) | (set(s["f"]["bad"]) - {"念卡"}))
                out.append({"id": f"fresh-{sid}", "src": "fresh", "ctx": r["ctx"], "card": r["card"], "text": s["text"],
                            "label": "bad", "bad": bad, "why": g.get("why", ""), "flags": s["f"], "reviewed": True})
                for b in bad:
                    why[b] = why.get(b, 0) + 1
                continue
            bad = sorted(set(s["f"]["bad"]) | judged_bad(g, r, s))
            if bad == ["念卡"]:  # 只照念、没别的毛病：抽查里不少只是把卡上的内容说出来，不算反例
                continue
            if bad:
                for b in bad:
                    why[b] = why.get(b, 0) + 1
                out.append({"id": f"fresh-{r['id']}-{s['seed']}", "src": "fresh", "ctx": r["ctx"], "card": r["card"],
                            "text": s["text"], "label": "bad", "bad": bad, "why": g.get("why", ""), "flags": s["f"]})
    with open(KTO, "w", encoding="utf-8") as fo:
        for x in out:
            fo.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"{len(raw)} 张卡、{n} 句，挑出反例 {len(out)} 句（{len(out) / max(1, n):.0%}）；各项：{why} → {KTO}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    os.makedirs(OUT, exist_ok=True)
    if cmd == "pick":
        return pick()
    if cmd == "judge-ds":  # 只把还没看的句子交给 DeepSeek 看，然后挑反例；不出卡、不写
        judge_all({}, provider="deepseek")
        return pick()
    ws = windows()
    random.Random(2026111202).shuffle(ws)
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else (5 if cmd == "pilot" else MAX)
    ws = ws[:limit]
    print(f"轮到佳树回的地方 {len(windows())} 处，这次用 {len(ws)} 处", flush=True)
    k = train_keys.gemini()
    assert k, "accounts\\gemini_keys.json 一个 key 都没填"
    sysmsg = persona() + "\n\n" + PLAN
    have = {c["id"]: c for c in jl(CARDS)}
    todo = [w for w in ws if w["id"] not in have]
    tok = {"in": 0, "out": 0}

    def one(w):
        c, u = plan(k, sysmsg, w)
        tok["in"] += u.get("prompt_tokens", 0)
        tok["out"] += u.get("completion_tokens", 0)
        return w, c

    with ThreadPoolExecutor(4) as ex, open(CARDS, "a", encoding="utf-8") as fo:
        for w, c in ex.map(one, todo):
            if c and ("我" in c.split("局面：")[-1] or "哥哥" in c):
                print("跳过 卡里有我/哥哥", w["id"], flush=True)
            elif c:
                have[w["id"]] = dict(w, card=c)
                fo.write(json.dumps(have[w["id"]], ensure_ascii=False) + "\n")
            else:
                print("FAIL 没出卡", w["id"], flush=True)
    if todo:
        print(f"出卡 {len(todo)} 次，输入 {tok['in']} 输出 {tok['out']} tokens", flush=True)

    done = {r["id"] for r in jl(RAW)}
    rows = [have[w["id"]] for w in ws if w["id"] in have and w["id"] not in done]
    t0 = time.time()
    with open(RAW, "a", encoding="utf-8") as fo:
        for i, r in enumerate(rows, 1):
            ss = []
            for seed in (1001, 1002):
                try:
                    text = mp.write(r["ctx"], r["card"], seed)
                except Exception as e:  # noqa: BLE001
                    print("FAIL 写", r["id"], type(e).__name__, flush=True)
                    continue
                ss.append({"seed": seed, "text": text, "f": judge(r, r["card"], text)})
            if cmd == "pilot":
                print("=====", r["id"], "\n" + r["card"])
                for s in ss:
                    print(f"  {s['f']}\n   {s['text'].replace(chr(10), ' / ')}")
            fo.write(json.dumps(dict(r, samples=ss), ensure_ascii=False) + "\n")
            fo.flush()
            if i % 25 == 0:
                print(f"{i}/{len(rows)}  {(time.time() - t0) / 60:.0f} 分钟", flush=True)
    judge_all(k)
    if cmd == "pilot":
        for x in jl(JUDGED):
            print("  Gemini:", x)
    pick()


if __name__ == "__main__":
    main()
