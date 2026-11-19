"""分层 writer 第一轮数据（2026-11-07，方案见 voice_train\\分层writer方案.md）。

    D:\\JiashuBot\\voice_train\\venv\\Scripts\\python.exe -I build_layered.py group  [--limit N]   群友发言 → 去名字 → 抽卡
    ...                                                       align  [--limit N]   原作/兄长认可的回复：草稿 → 抽卡 → 和答案一致才留
    ...                                                       facts  [--limit N]   原作 → "关于自己"的事实（逐段）
    ...                                                       merge-facts          事实去重合并 → 给兄长大人过目的清单
    ...                                                       assemble             拼成 stage1.jsonl（H）/ stage2.jsonl（K）

输出都在 voice_train\\data\\layered_v1\\。每一步的结果按 id 追加缓存，断了重跑会接着做，不重复花钱。
只用 deepseek-flash，全部关掉思考（输出少一个数量级）。不打印 API key。

数据原则（兄长大人 11-07 定的）：
- H（说人话 / 群聊）的目标都是真人说的话：LCCC、兄长大人自己的私聊、群友的发言（名字、QQ 号、链接换掉）。
- K（佳树口吻）的目标只用原作原句和兄长大人认可的回复；stage2b/2c 里 DeepSeek 写的"理想回复"不当答案（那是 AI 腔的来源）。
- K 的卡一部分照线上的样子从 DeepSeek 草稿里抽（对齐），一部分从答案里抽（教它忠实照卡写）；草稿和答案说的不是一回事的扔掉。
- 和评测题（ab5、第二批留出题）上下文重叠的不进训练。
"""
import argparse
import asyncio
import glob
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = r"D:\JiashuBot"
VT = os.path.join(ROOT, "voice_train")
DATA = os.path.join(VT, "data")
OUT = os.path.join(DATA, "layered_v1")
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
PD = os.path.join(CORE, "data", "plugin_data")
NOVEL = r"D:\Persona\Kaju\txt"
NOVEL_FILES = ["败北女角太多了！ - 01.txt", "败北女角太多了！ - 02.txt", "败北女角太多了！ - 03.txt", "败北女角太多了！ - 04.txt",
               "败北女角太多了！ - 05.txt", "败北女角太多了！ - 06.txt", "败北角太多了！ - 07.txt", "第八卷__8台版.txt",
               "8.5__8.5最新版（看这个）.txt", "9全卷_修复.txt", "败北角太多了！ SSS-篇集 - 01 (1).txt"]
OWNER = "111111111"
sys.path.insert(0, os.path.join(ROOT, "bot_setup", "kaju_core", "voice"))
import card  # noqa: E402

from openai import AsyncOpenAI  # noqa: E402

_cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
_src = next(s for s in _cfg["provider_sources"] if s["id"] == "deepseek_source")
_key = _src.get("key")
# 训练专用接口（2026-11-09）：voice_train\train_api.json 填了 key 就走它（如 bb-api 中转），没填走机器人那份 DeepSeek 官方
try:
    TRAIN_API = json.load(open(os.path.join(VT, "train_api.json"), encoding="utf-8-sig"))
except (OSError, ValueError):
    TRAIN_API = {}
if TRAIN_API.get("key") and TRAIN_API.get("enabled", True):
    ds = AsyncOpenAI(api_key=TRAIN_API["key"], base_url=TRAIN_API["api_base"], timeout=120)
    MODEL = TRAIN_API.get("model") or "deepseek-flash"
    PRICE = TRAIN_API.get("price_per_m") or {"in": 2, "cached": 0.04, "out": 8}
    YUAN_PER_UNIT = float(TRAIN_API.get("yuan_per_unit", 1))
    PRICE_NOTE = f"{TRAIN_API.get('name') or '训练专用接口'}价"
else:
    ds = AsyncOpenAI(api_key=_key[0] if isinstance(_key, list) else _key, base_url=_src["api_base"], timeout=120)
    MODEL = "deepseek-flash"
    PRICE = {"in": 1, "cached": 0.02, "out": 4}  # 空闲时段价；高峰翻倍
    YUAN_PER_UNIT = 1.0
    PRICE_NOTE = "DeepSeek 官方空闲价；高峰 ×2"
SEM = asyncio.Semaphore(16)
NOTHINK = {"thinking": {"type": "disabled"}}
USAGE = {"in": 0, "cached": 0, "out": 0, "calls": 0}


JUDGE = {"by": "deepseek"}  # 2026-11-13 兄长：本机微调的“说不说得通”和考试评判换 Gemini（use_gemini()）
GEM_SEM = asyncio.Semaphore(4)  # 中转站并发别太高


def use_gemini() -> None:
    """这个进程里的 ask() 改问 Gemini（gemini_keys.json 从上往下，和机器人出卡同一套：omni.text）。
    round_train.py（AGREE）、exam_p3.py / exam_v2.py（评判）开头调用。temperature 不传（Gemini 走默认），思考 low。"""
    import train_keys  # noqa: F401  设好 KAJU_DATA、把 bot_setup 放进 sys.path
    JUDGE["by"] = "gemini"
    print("评判 / 核对改用 Gemini（gemini_keys.json 顺序）", flush=True)


async def _ask_gemini(system, user):
    from kaju_core.senses import omni
    async with GEM_SEM:
        for attempt in range(3):
            try:
                out, _ = await omni.text(system, user, timeout=60, thinking="low")
                USAGE["calls"] += 1
                return out or ""
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"  Gemini 调用失败 {type(e).__name__}: {str(e)[:80]}")
                    return ""
                await asyncio.sleep(3 * (attempt + 1))


async def ask(system, user, temperature=0.3):
    if JUDGE["by"] == "gemini":
        return await _ask_gemini(system, user)
    async with SEM:
        for attempt in range(3):
            try:
                r = await ds.chat.completions.create(model=MODEL, temperature=temperature, extra_body=NOTHINK,
                                                     messages=[{"role": "system", "content": system},
                                                               {"role": "user", "content": user}])
                u = r.usage
                USAGE["calls"] += 1
                USAGE["in"] += getattr(u, "prompt_tokens", 0) or 0
                USAGE["out"] += getattr(u, "completion_tokens", 0) or 0
                hit = getattr(u, "prompt_cache_hit_tokens", 0)  # DeepSeek 官方的写法
                if not hit:  # 中转站多半是 OpenAI 的写法
                    hit = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0)
                USAGE["cached"] += hit or 0
                return r.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"  调用失败 {type(e).__name__}: {str(e)[:80]}")
                    return ""
                await asyncio.sleep(3 * (attempt + 1))


def cost():
    if JUDGE["by"] == "gemini":
        return f"{USAGE['calls']} 次 Gemini 调用（gemini_keys.json 里的中转，按各家价格另算）"
    miss = USAGE["in"] - USAGE["cached"]
    unit = (miss * PRICE["in"] + USAGE["cached"] * PRICE["cached"] + USAGE["out"] * PRICE["out"]) / 1e6
    yuan = unit * YUAN_PER_UNIT
    return (f"{USAGE['calls']} 次调用（{MODEL}），输入 {USAGE['in']/1e6:.2f}M（缓存 {USAGE['cached']/1e6:.2f}M），"
            f"输出 {USAGE['out']/1e6:.3f}M，约 {yuan:.2f} 元（{PRICE_NOTE}）")


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def append(path, rows):
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def done_ids(path):
    return {r["id"] for r in load(path)}


def ctx_key(ctx):
    return "|".join((ctx or [])[-2:])


def eval_keys():
    keys = {ctx_key(x["ctx"]) for x in json.load(open(os.path.join(DATA, "ab5_items.json"), encoding="utf-8"))}
    keys |= {ctx_key(x.get("ctx", [])) for x in load(os.path.join(DATA, "curated_second_batch_holdout.jsonl"))}
    return keys


# ====================================================================== H：群友发言
MEDIA = re.compile(r"^(\[(图片|表情|视频|语音|文件[^\]]*|动画表情|小黄脸[^\]]*)\]\s*)+$")


def scrub_names():
    """kaju_life 记下的昵称 + 称呼簿里的称呼：长的先换，免得短名把长名拆开。"""
    names = json.load(open(os.path.join(PD, "astrbot_plugin_kaju_life", "names.json"), encoding="utf-8"))
    addr = json.load(open(os.path.join(PD, "astrbot_plugin_address_book", "addresses.json"), encoding="utf-8"))
    by_uid = {}
    for uid, n in (names.get("people") or {}).items():
        by_uid.setdefault(uid, set()).add(n)
    for uid, v in addr.items():
        if isinstance(v, dict) and v.get("address"):
            by_uid.setdefault(uid, set()).add(v["address"])
    groups = [g for g in (names.get("groups") or {}).values() if g and not g.isdigit()]
    return by_uid, groups


COMMON = {"佳树", "兄长", "兄长大人", "学长", "学姐", "哥哥", "姐姐", "妹妹", "大家", "我"}


def scrub(text, label_of, by_uid, groups):
    s = re.sub(r"https?://\S+", "[链接]", text)
    s = re.sub(r"\d{5,}", "[号码]", s)
    for g in groups:
        s = s.replace(g, "群里")
    pairs = []
    for uid, ns in by_uid.items():
        for n in ns:
            if len(n) >= 2 and n not in COMMON:
                pairs.append((n, label_of(uid)))
    for n, lab in sorted(pairs, key=lambda p: -len(p[0])):
        s = s.replace(n, lab)
    return s


def group_samples():
    by_uid, groups = scrub_names()
    recs = []
    for p in sorted(glob.glob(os.path.join(PD, "astrbot_plugin_kaju_life", "log", "*.jsonl"))):
        day = os.path.basename(p)[:-6]
        for i, r in enumerate(load(p)):
            if str(r.get("c", "")).startswith("g"):
                recs.append((day, i, r))
    by_chat = {}
    for day, i, r in recs:
        by_chat.setdefault(r["c"], []).append((day, i, r))
    out = []
    for chat, rs in by_chat.items():
        for j, (day, i, r) in enumerate(rs):
            x = str(r.get("x") or "").strip()
            if r.get("u") == "self" or len(x) < 2 or MEDIA.match(x) or x.startswith("/"):
                continue
            prev = [q for _, _, q in rs[max(0, j - 8):j]]
            labels = {}
            me = str(r.get("u"))

            def mention(uid):
                """正文里提到某人：一律换成"群友X"（说话人自己也一样），只有行首的说话人标签用"我"。"""
                if uid == "self":
                    return "佳树"
                if uid not in labels:
                    labels[uid] = "群友" + "ABCDEFGH"[min(len(labels), 7)]
                return labels[uid]

            def speaker(uid):
                return "我" if uid == me else mention(uid)

            def clean(t):
                t = scrub(t, mention, by_uid, groups)
                t = re.sub(r"\(\[号码\]\)", "", t)
                return re.sub(r"\s*\n\s*", " / ", t).strip()
            ctx = []
            for q in prev:
                qx = str(q.get("x") or "").strip()
                if not qx:
                    continue
                ctx.append(f"{speaker(str(q.get('u')))}：{clean(qx)[:120]}")
            target = clean(x)
            if MEDIA.match(target) or len(re.sub(r"\[[^\]]*\]", "", target).strip()) < 2:
                continue
            out.append({"src": "group", "id": f"g-{day}-{i}", "kind": "群聊", "ctx": ctx[-6:], "target": target[:200],
                        "group": f"{chat}-{day}"})
    return out


async def run_group(limit):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "h_group_cards.jsonl")
    have = done_ids(path)
    todo = [s for s in group_samples() if s["id"] not in have]
    if limit:
        todo = todo[:limit]
    print(f"群友发言待抽卡 {len(todo)} 条（已有 {len(have)}）")

    async def one(s):
        cards = []
        for t in (0.3, 0.8):
            c = card.parse(await ask(card.EXTRACT, card.extract_prompt(s["ctx"], s["target"], "群聊", ""), t))
            if c:
                cards.append(card.render(c, "群聊", ""))
        return {**s, "cards": cards}
    rows = await asyncio.gather(*(one(s) for s in todo))
    append(path, [r for r in rows if r["cards"]])
    print(f"写入 {sum(1 for r in rows if r['cards'])} 条 → {path}\n{cost()}")


# ====================================================================== K：对齐卡
AGREE = """下面是一张要点卡和一句回复。判断：一个人只看这张卡，写出这句回复，算不算"照卡写"？
- 回复说的主要内容卡上都有（回复可以比卡短、省掉次要的点、语气不同）→ 算
- 回复的主要意思卡上没有（得自己编），或者和卡上的意思相反、对象弄反 → 不算
只输出 JSON：{"ok": true/false, "why": "一句话"}"""


def k_sources(evals):
    """K 的目标：原作原句（stage2b/2c 的 novel，目标就是原文）+ 兄长大人认可的回复（stage2b_gold）。各带当时的 DeepSeek 草稿。"""
    out, seen = [], set()
    for n in ("stage2b.jsonl", "stage2c.jsonl"):
        for r in load(os.path.join(DATA, n)):
            if r.get("src") != "novel" or not r.get("draft") or not r.get("target"):
                continue
            k = (ctx_key(r["ctx"]), r["target"].strip())
            if k in seen or k[0] in evals:
                continue
            seen.add(k)
            out.append({"src": "novel", "id": f"n{len(out)}", "kind": "当面", "to": "", "ctx": r["ctx"],
                        "draft": r["draft"], "target": r["target"].strip()})
    for r in load(os.path.join(DATA, "stage2b_gold.jsonl")):
        if not r.get("draft") or not r.get("target") or ctx_key(r["ctx"]) in evals:
            continue
        kind = "群聊" if r.get("src") == "group" else "私聊"
        to = r.get("to") or ("" if kind == "群聊" else "兄长大人")
        out.append({"src": "gold", "id": f"gold-{r.get('id')}", "kind": kind, "to": to, "ctx": r["ctx"],
                    "draft": r["draft"], "target": r["target"].strip()})
    return out


async def run_align(limit):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "k_aligned.jsonl")
    have = done_ids(path)
    todo = [s for s in k_sources(eval_keys()) if s["id"] not in have]
    if limit:
        todo = todo[:limit]
    print(f"对齐卡待做 {len(todo)} 条（已有 {len(have)}）")

    async def one(s):
        c = card.parse(await ask(card.EXTRACT, card.extract_prompt(s["ctx"], s["draft"], s["kind"], s["to"]), 0.3))
        if not c:
            return {**s, "card": "", "ok": False, "why": "没抽出卡"}
        ct = card.render(c, s["kind"], s["to"])
        j = re.search(r"\{.*\}", await ask(AGREE, f"要点卡：\n{ct}\n\n回复：\n{s['target']}", 0.0) or "", re.S)
        try:
            v = json.loads(j.group(0)) if j else {}
        except ValueError:
            v = {}
        return {**s, "card": ct, "ok": bool(v.get("ok")), "why": str(v.get("why") or "判断失败")}
    rows = await asyncio.gather(*(one(s) for s in todo))
    append(path, rows)
    ok = sum(r["ok"] for r in rows)
    print(f"写入 {len(rows)} 条，一致 {ok} 条 → {path}\n{cost()}")


# ====================================================================== 原作 → 关于自己的事实
FACTS = """下面是轻小说《败犬女主太多了！》的一段原文。温水佳树是主角温水和彦的妹妹。
只从这段里找"关于温水佳树本人、长期稳定"的事实：身份、年级、学校和学生会、家里的人和关系、擅长的事、喜欢和讨厌的东西、
生活习惯、怎么称呼别人、对哥哥和身边人的态度、性格里反复出现的特点。
- 一次性的剧情事件不要（"那天她去了海边"不要；"她每天早上给哥哥做便当"要）
- 只写这段原文能支持的，不推测；这段没提到佳树、或没有稳定事实，就输出空数组
- 每条一句，用"佳树……"开头，写清对象
只输出 JSON 数组：[{"fact": "佳树……", "kind": "身份/家人/学校/擅长/喜好/习惯/称呼/态度/性格", "quote": "原文里最能支持这条的不超过 30 字"}]"""

MERGE = """下面是从小说各段里逐条提取的、关于温水佳树的事实（有大量重复和近似）。请合并成一份清单：
- 意思相同的合成一条，保留最具体的说法；互相矛盾的都留下，标 "conflict": true
- 只留长期稳定的事实，删掉一次性事件和推测
- 按类别分组：身份、家人、学校、擅长、喜好、习惯、称呼、态度、性格
- 总数 40～80 条，每条一句，用"佳树……"开头
只输出 JSON 数组：[{"kind": "…", "fact": "佳树……", "support": 被几段提到（数字）, "conflict": false}]"""


def novel_chunks(size=2500):
    out = []
    for name in NOVEL_FILES:
        text = open(os.path.join(NOVEL, name), encoding="utf-8", errors="ignore").read()
        paras = [p.strip() for p in text.split("\n") if p.strip()]
        buf, n = [], 0
        for p in paras:
            buf.append(p)
            n += len(p)
            if n >= size:
                out.append((name, "\n".join(buf)))
                buf, n = [], 0
        if buf:
            out.append((name, "\n".join(buf)))
    return [(f"{name}#{i}", t) for i, (name, t) in enumerate(out) if "佳树" in t]


async def run_facts(limit):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "facts_raw.jsonl")
    have = done_ids(path)
    todo = [(cid, t) for cid, t in novel_chunks() if cid not in have]
    if limit:
        todo = todo[:limit]
    print(f"有佳树的段落待读 {len(todo)} 段（已有 {len(have)}）")

    async def one(cid, t):
        m = re.search(r"\[.*\]", await ask(FACTS, t, 0.2) or "", re.S)
        try:
            facts = [f for f in json.loads(m.group(0)) if isinstance(f, dict) and str(f.get("fact", "")).startswith("佳树")] if m else []
        except ValueError:
            facts = []
        return {"id": cid, "facts": facts}
    rows = await asyncio.gather(*(one(c, t) for c, t in todo))
    append(path, rows)
    print(f"写入 {len(rows)} 段，共 {sum(len(r['facts']) for r in rows)} 条原始事实 → {path}\n{cost()}")


async def run_merge_facts():
    rows = load(os.path.join(OUT, "facts_raw.jsonl"))
    facts = [f"{f.get('kind', '')}｜{f['fact']}" for r in rows for f in r["facts"]]
    print(f"原始事实 {len(facts)} 条")
    # 太多就先按类别分批合并，再总合并
    by_kind = {}
    for line in facts:
        by_kind.setdefault(line.split("｜", 1)[0] or "其他", []).append(line)
    partial = []
    for kind, lines in by_kind.items():
        for i in range(0, len(lines), 400):
            m = re.search(r"\[.*\]", await ask(MERGE, "\n".join(lines[i:i + 400]), 0.2) or "", re.S)
            try:
                partial += json.loads(m.group(0)) if m else []
            except ValueError:
                pass
    json.dump(partial, open(os.path.join(OUT, "facts_partial.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    final = await finalize_facts(partial)
    json.dump(final, open(os.path.join(OUT, "facts_merged.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_facts_md(final)


FINAL = """下面是从小说里提取并初步合并的、关于温水佳树的"{kind}"类事实（括号里是被几段原文提到）。
请精选成不超过 {n} 条，作为她对自己的长期认识：
- 只留长期稳定、平时聊天里可能用得上的；一次性的往事、某一章的情节、别人对她的评价删掉
- 意思相近的合成一条；被提到次数多的优先；不同译本的叫法（如"哥哥"和"兄长大人"）合成一条并注明
- 互相矛盾的都留下，标 "conflict": true
- 每条一句，用"佳树……"开头
只输出 JSON 数组：[{{"fact": "佳树……", "support": 数字, "conflict": false}}]"""
FINAL_N = {"身份": 6, "家人": 8, "学校": 6, "擅长": 8, "喜好": 8, "习惯": 10, "称呼": 6, "态度": 10, "性格": 8}


async def finalize_facts(partial):
    by = {}
    for p in partial:
        if isinstance(p, dict) and p.get("fact"):
            by.setdefault(p.get("kind") or "其他", []).append(p)

    async def one(kind, items):
        items = sorted(items, key=lambda p: -int(p.get("support") or 1))[:150]
        body = "\n".join(f"{p['fact']}（{p.get('support', 1)}段）" for p in items)
        m = re.search(r"\[.*\]", await ask(FINAL.format(kind=kind, n=FINAL_N.get(kind, 6)), body, 0.2) or "", re.S)
        try:
            got = json.loads(m.group(0)) if m else []
        except ValueError:
            got = []
        if not got:
            print(f"  {kind} 精选失败，保留初步合并的前 {FINAL_N.get(kind, 6)} 条")
            got = items[:FINAL_N.get(kind, 6)]
        return [{"kind": kind, **{k: g.get(k) for k in ("fact", "support", "conflict")}} for g in got if isinstance(g, dict)]
    groups = await asyncio.gather(*(one(k, v) for k, v in by.items()))
    return [f for g in groups for f in g]


def write_facts_md(final):
    lines = ["# 佳树：关于自己（从原作提炼，待兄长大人过目）", "",
             "每条后面可以写「删」「改：……」，或者直接改字。标 ⚠ 的是不同段落说法不一致。过目后这些会存进她的长期记忆，当成她自己知道的事。", ""]
    by = {}
    for f in final:
        if isinstance(f, dict) and f.get("fact"):
            by.setdefault(f.get("kind") or "其他", []).append(f)
    n = 0
    for kind, fs in by.items():
        lines.append(f"## {kind}")
        for f in fs:
            n += 1
            lines.append(f"{n}. {'⚠ ' if f.get('conflict') else ''}{f['fact']}（{f.get('support', '?')} 段提到）")
        lines.append("")
    open(os.path.join(OUT, "佳树-关于自己-待过目.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"合并成 {n} 条 → {os.path.join(OUT, '佳树-关于自己-待过目.md')}\n{cost()}")


# ====================================================================== 拼数据
def assemble():
    evals = eval_keys()
    rng = random.Random(7)
    v4 = load(os.path.join(DATA, "v4_cards.jsonl"))
    clean = [r for r in v4 if ctx_key(r.get("ctx")) not in evals]
    print(f"v4_cards 去掉和评测题重叠的 {len(v4) - len(clean)} 条")

    # H：LCCC + 兄长大人自己的话 + 群友
    h = [{"src": r["src"], "id": f"{r['src']}-{r['id']}-{r.get('n', 0)}", "ctx": r["ctx"], "card": r["card"],
          "target": r["target"], **({"group": f"{r['src']}-{r['id']}"})} for r in clean if r["src"] in ("lccc", "owner")]
    g = load(os.path.join(OUT, "h_group_cards.jsonl"))
    for r in g:
        for k, c in enumerate(r["cards"]):
            h.append({"src": "group", "id": f"{r['id']}-{k}", "ctx": r["ctx"], "card": c, "target": r["target"],
                      "group": r["group"]})

    # K：原作 / 兄长认可的回复，从答案抽的卡（v4_cards 里现成的）+ 从草稿抽的对齐卡（一致的才要）
    k = [{"src": "curated" if r["src"] == "gold" else r["src"], "id": f"{r['src']}-{r['id']}-{r.get('n', 0)}",
          "ctx": r["ctx"], "card": r["card"], "target": r["target"], "group": f"{r['src']}-{r['id']}"}
         for r in clean if r["src"] in ("novel", "gold")]
    al = load(os.path.join(OUT, "k_aligned.jsonl"))
    for r in al:
        if r.get("ok") and r.get("card"):
            k.append({"src": "curated" if r["src"] == "gold" else "novel", "id": f"al-{r['id']}", "ctx": r["ctx"],
                      "card": r["card"], "target": r["target"], "align": True})
    for r in load(os.path.join(DATA, "curated_first_batch.jsonl")):
        k.append({**r, "src": "curated"})
    rng.shuffle(h)
    rng.shuffle(k)
    json_rows = lambda rows: "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)  # noqa: E731
    open(os.path.join(OUT, "stage1.jsonl"), "w", encoding="utf-8").write(json_rows(h))
    open(os.path.join(OUT, "stage2.jsonl"), "w", encoding="utf-8").write(json_rows(k))
    from collections import Counter
    meta = {"H": dict(Counter(x["src"] for x in h)), "K": dict(Counter(x["src"] for x in k)),
            "K_aligned": sum(1 for x in k if x.get("align")),
            "aligned_total": len(al), "aligned_ok": sum(1 for r in al if r.get("ok"))}
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["group", "align", "facts", "merge-facts", "finalize-facts", "assemble"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.step == "group":
        await run_group(a.limit)
    elif a.step == "align":
        await run_align(a.limit)
    elif a.step == "facts":
        await run_facts(a.limit)
    elif a.step == "merge-facts":
        await run_merge_facts()
    elif a.step == "finalize-facts":  # 只重做最后的分类精选（用已有的初步合并结果）
        src = os.path.join(OUT, "facts_partial.json")
        if not os.path.exists(src):
            src = os.path.join(OUT, "facts_merged.json")
        partial = json.load(open(src, encoding="utf-8"))
        json.dump(partial, open(os.path.join(OUT, "facts_partial.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        final = await finalize_facts(partial)
        json.dump(final, open(os.path.join(OUT, "facts_merged.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_facts_md(final)
    else:
        assemble()


if __name__ == "__main__":
    asyncio.run(main())
