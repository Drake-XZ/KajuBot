"""回复器（2026-11-18 兄长：“那按照他们这个思路试试”→ 回放盲选 28:9 赢 →“做上线开关”；AGENT.md 第十节）。

照 MaiBot 的做法：大脑（主模型，brain.py）想清楚这一轮要表达什么，回复器（API 大模型）用她的口吻写出来；不训练模型。
回复器的提示 = 她是谁 + 她是什么样的人（kaju_data\\self\\persona\\character.md）+ 几条说话方式 + 最近 10 条聊天
+ 这一轮对方的话 + 大脑的指导 + 按场合挑出的几句她以前说过的话（MaiBot 的“表达方式”：当对方说…时，她说…）。

例子库 kaju_data\\self\\kaju_style\\replyer_bank.json：[{situation, line, src, vec}]（voice_train\\scripts\\build_replyer_bank.py 造）；
按“这一轮对方的话 + 要接住的”用本机 bge-m3 挑最近的几句，原作的最多 2 句；向量服务不在就不放例子。
11-20 晚起再加上 kaju_learn 每晚从她真实聊天里挑的效果好的话（replyer_learned.json，src = "live"，一轮最多 rewrite.replyer_live_max 句）。
模型在 kaju_data\\accounts\\text_models.json，按 rewrite.replyer_models 的名字前缀从前往后试，一个不行换下一个；都不行返回 ''（mind.py 退回本地写手）。
开关 rewrite.replyer = "api"（默认 "local" = 照旧本地写手），只在大脑模式（main_role = "brain"）下用。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time

from kaju_core.voice import brain

BANK_FILE = ("kaju_style", "replyer_bank.json")
LEARNED_FILE = "replyer_learned.json"  # 从真实聊天里长的例句（11-20 晚）
# 回复器看的聊天里她自己那几行（11-18 晚，照 MaiBot 的“{bot_name}(你)”：自己说过的话和别人的分清）
ME_LABEL = "佳树(你)"
CHAT_NOTE = (f"最近的聊天（标着“{ME_LABEL}”的是你自己说过的话，注意和别人的区分；“（回复X：…）”是这句在回谁的哪句话，"
             "“@佳树”是有人 @ 了你，“[图片：…]”是图里的内容）：")
DEFAULT_MODELS = ["bb-api · claude-sonnet-5", "hardysapi · claude-sonnet-5-5"]

STYLE = """说话方式：
- 写她在 QQ 上会发的话，一条消息一行；通常一两句，事情多才多一点。
- 她自称“佳树”、叫哥哥“兄长大人”，但一句话里不反复自称、不反复叫人。
- 不复述对方刚说的话，也不把你自己最近几条说过的意思再说一遍；不写时间、名字前缀、括号里的动作和心理描写。
- 大脑的指导是这一轮要表达的意思，照着说到，但用她自己的话；指导里没有的事不加（对方没说累、没说吃饭，就不顺手叮嘱吃饭、休息），
  尤其不编她自己的经历（指导里没写她试过、用过、去过、看过的，就别说“佳树之前试过”）。
- 聊天里群友说“AI”“机器人”“模型”“训练”，说的是群里别的 AI，不是你：不说自己是不是 AI（不否认、不承认、不说“才不是 AI”），
  也不从 AI、训练数据的角度说话，只照指导接话题本身。"""

_bank_cache: tuple = ((), [])


def traits() -> list[str]:
    return [x for x in brain.character().splitlines() if x.startswith("- ")]


def system_prompt(examples: list[dict], trait_lines: list[str] | None = None) -> str:
    ts = traits() if trait_lines is None else trait_lines
    s = f"你是{brain.ME}。"
    if ts:
        s += "\n\n她是什么样的人：\n" + "\n".join(ts)
    s += "\n\n" + STYLE
    if examples:
        s += ("\n\n你可以视情况参考她以前在类似场合说过的话（只学说法和语气，内容照这一轮的指导，不要照抄）：\n"
              + "\n".join(f"- 当对方说“{b['situation'][:60]}”时，她说：“{b['line'][:100]}”" for b in examples))
    return s


def plan_text(plan: dict) -> str:
    lines = [f"局面：{plan.get('局面', '')}"]
    if plan.get("要接住的"):
        lines.append(f"要接住的：{plan['要接住的']}")
    if plan.get("对方需要"):  # 11-18：对方这一刻要什么（大脑判断，照 anima-brain 的 attunement）
        lines.append(f"对方需要：{plan['对方需要']}")
    lines.append("要表达的：" + ("；".join(plan.get("要表达的") or []) or "（随口接一句）"))
    if plan.get("背景"):
        lines.append("背景：" + "；".join(plan["背景"]))
    if plan.get("情绪"):
        lines.append(f"情绪：{plan['情绪']}")
    if plan.get("底色"):  # 心情底色（kaju_heart，2026-11-18 照 anima-brain：状态直接交给写话的模型）；“情绪”是这一刻对这句话的
        lines.append(f"心情底色：{plan['底色']}")
    return "\n".join(lines)


# 这一轮群聊怎么来的（brain.how_came），照 MaiBot 的“现在X说的：…引起了你的注意”写成中性的一句（11-18 晚：
# 原来一律写“这一轮对方说”，插话时回复器也当成对方在跟她说，写出“被哆啦a梦学姐点名了”）
HOW_LINE = {
    "插话": "现在群里这句引起了她的注意（没人叫她，是她自己想插一句；这句不是对她说的）：\n{said}",
    "接着聊": "现在群里这句引起了她的注意（刚和她说过话的人又发的，没叫她，不一定是对她说的）：\n{said}",
}


def user_prompt(kind: str, title: str, ctx: list[str], plan: dict, said: str = "", ctx_lines: int = 10,
                how: str = "") -> str:
    """ctx_lines：聊天看最后几行；0 = 给多少看多少（线上回复器自己那份：群聊 50 行、私聊 20 行，11-18）。
    how：这一轮群聊怎么来的（"插话" / "接着聊" / "" = 被叫到或私聊）。"""
    lines = list(ctx or [])
    chat = "\n".join(lines[-ctx_lines:] if ctx_lines > 0 else lines) or "（没有前文）"
    said = said or ((ctx or [""])[-1] if ctx else "")
    if how in HOW_LINE:
        head, now = f"场合：{kind or '群聊'}", HOW_LINE[how].format(said=said)
    else:
        head, now = f"场合：{kind or '私聊'}，对象：{title or '无'}", f"这一轮对方说：\n{said}"
    note = CHAT_NOTE if ME_LABEL in chat or "（回复" in chat or "[图片：" in chat or "@佳树" in chat else "最近的聊天："
    return (f"{head}\n\n{note}\n{chat}\n\n{now}\n\n"
            f"大脑的指导：\n{plan_text(plan)}\n\n只输出她要发的话。")


def _read_bank(path: str, learned: bool) -> list[dict]:
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if learned:  # 从真实聊天里长的（kaju_learn 每晚挑，kaju_core\learn\phrases.py）：{items: [...]}，只要还在用的
        d = [x for x in (d.get("items") if isinstance(d, dict) else None) or [] if x.get("status", "active") == "active"]
    return [b for b in d if isinstance(b, dict) and b.get("vec") and b.get("line")]


def load_bank(path: str = "", learned_path: str | None = None) -> list[dict]:
    """原来的例子库 + 从真实聊天里学到的（11-20 晚，replyer_learned.json，src = "live"）；两个文件按改动时间缓存。"""
    global _bank_cache
    if not path:
        try:
            from kaju_core import paths
            folder = paths.self_dir(BANK_FILE[0])
        except Exception:  # noqa: BLE001
            return []
        path = os.path.join(folder, BANK_FILE[1])
        if learned_path is None:
            learned_path = os.path.join(folder, LEARNED_FILE)
    files = [(path, False)] + ([(learned_path, True)] if learned_path else [])
    mt = []
    for f, _ in files:
        try:
            mt.append(os.path.getmtime(f))
        except OSError:
            mt.append(0.0)
    key = (path, learned_path, tuple(mt))
    if key != _bank_cache[0]:
        _bank_cache = (key, [b for f, lr in files if os.path.exists(f) for b in _read_bank(f, lr)])
    return _bank_cache[1]


def _cos(a, b) -> float:
    n = sum(x * y for x, y in zip(a, b))
    d = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return n / d if d else 0.0


_QUERY_NOISE = re.compile(r"^\[发言人：[^\]]*\]\s*|兄长大人|佳树")


def example_query(said: str) -> str:
    """挑例子用的那句：对方的话本身，去掉发言人标注和称呼（称呼到处都有，会把例子拉向“带称呼的”而不是“同话题的”）。"""
    return _QUERY_NOISE.sub("", str(said or "")).strip()[:200]


def pick(bank: list[dict], vec: list[float], k: int = 5, max_novel: int = 2, floor: float = 0.0,
         max_live: int = 2) -> list[dict]:
    """max_live：从真实聊天里学到的（src = "live"）一轮最多几句（她自己的话占多了，越学越像自己、越来越单调）。"""
    scored = sorted(((_cos(vec, b["vec"]), b) for b in bank), key=lambda x: -x[0])
    out, seen, n_novel, n_live = [], set(), 0, 0
    for _s, b in scored:
        if _s < floor:
            break
        key = b["line"][:12]
        if key in seen or (b.get("src") == "novel" and n_novel >= max_novel) or (b.get("src") == "live" and n_live >= max_live):
            continue
        seen.add(key)
        n_novel += b.get("src") == "novel"
        n_live += b.get("src") == "live"
        out.append(b)
        if len(out) >= k:
            break
    return out


async def embed(text: str, url: str, timeout: float = 8) -> list[float] | None:
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.post(url.rstrip("/") + "/api/embed", json={"model": "bge-m3", "input": [text]}) as r:
                if r.status != 200:
                    return None
                d = await r.json()
                return (d.get("embeddings") or [None])[0]
    except Exception:  # noqa: BLE001
        return None


def keys_for(names: list[str]) -> list[dict]:
    from kaju_core.senses import omni
    ks = omni.text_keys()
    out = []
    for n in names:
        out += [k for k in ks if str(k.get("name", "")).startswith(n) and k not in out]
    return out


def clean(out: str) -> str:
    """去掉模型偶尔加的整句引号和首尾空白；不改她的字。"""
    t = (out or "").strip()
    if len(t) >= 2 and t[0] in "“\"「" and t[-1] in "”\"」" and t.count(t[0]) == 1:
        t = t[1:-1].strip()
    return t


async def reply(kind: str, title: str, ctx: list[str], plan: dict, cfg: dict, said: str = "", log=None,
                ctx_lines: int = 10, how: str = "") -> tuple[str, dict]:
    """写一遍。返回 (她的话, 记录)；都不行返回 ('', 记录)。cfg = rewrite 那一段配置。"""
    from kaju_core.senses import omni
    info: dict = {"examples": [], "model": "", "secs": 0.0, "errors": []}
    t0 = time.time()
    examples: list[dict] = []
    try:
        n_ex = int(cfg.get("replyer_examples", 5) or 0)
    except (TypeError, ValueError):
        n_ex = 5
    if n_ex > 0:
        bank = load_bank()
        if bank:
            # 只拿对方这句去挑（11-19：原来还拼上“要接住的”，那里满是“兄长大人让佳树…”，挑出来的全是带称呼的老几句、跟话题无关）；
            # 太不像的不放（宁可不给例子）
            vec = await embed(example_query(said or (ctx or [""])[-1]),
                              str(cfg.get("replyer_embed_url", "http://127.0.0.1:11435")))
            if vec:
                try:
                    floor = float(cfg.get("replyer_example_min", 0.5))
                except (TypeError, ValueError):
                    floor = 0.5
                try:
                    max_live = int(cfg.get("replyer_live_max", 2))
                except (TypeError, ValueError):
                    max_live = 2
                examples = pick(bank, vec, n_ex, floor=floor, max_live=max_live)
    info["examples"] = [b["line"] for b in examples]
    info["live_examples"] = sum(b.get("src") == "live" for b in examples)
    system, user = system_prompt(examples), user_prompt(kind, title, ctx, plan, said, ctx_lines, how)
    info["how"] = how
    names = cfg.get("replyer_models") or DEFAULT_MODELS
    if isinstance(names, str):
        names = [x.strip() for x in names.split(",") if x.strip()]
    try:
        per = float(cfg.get("replyer_timeout", 20) or 20)
    except (TypeError, ValueError):
        per = 20.0
    for k in keys_for(list(names)):
        t1 = time.monotonic()
        try:
            out = await asyncio.wait_for(asyncio.to_thread(
                omni._openai_chat, k, [{"role": "system", "content": system}, {"role": "user", "content": user}], per), per + 3)
            text = clean(out)
            if text:
                info.update(model=k.get("name", ""), secs=round(time.time() - t0, 1))
                return text, info
            info["errors"].append(f"{k.get('name', '')[:20]}: 空")
        except Exception as e:  # noqa: BLE001
            info["errors"].append(f"{k.get('name', '')[:20]}: {type(e).__name__}")
            if log:
                log.info(f"kaju_style: 回复器 {k.get('name', '')[:24]} 没答上来（{time.monotonic() - t1:.0f}s）{type(e).__name__}: {str(e)[:80]}")
    info["secs"] = round(time.time() - t0, 1)
    return "", info


def plan_from_card(card_text: str) -> dict:
    """不是大脑那一轮的要点卡（场合 / 对象 / 局面 / 要说到的 / 背景 / 心情，card.render_v4、brain.card_of 拼的）→ 回复器的指导。
    11-18 晚兄长：“我不想再用本地写手了”——插件让她说话（say_from_card）、草稿摘卡这些也交给回复器写。"""
    p: dict = {"局面": "", "要表达的": []}
    for line in (card_text or "").splitlines():
        k, _, v = line.partition("：")
        v = v.strip()
        if k == "局面":
            jm, _, catch = v.partition("。要接住的：")
            p["局面"], p["要接住的"] = jm.strip(), catch.strip()
        elif k == "要说到的" and v and v != "无":
            p["要表达的"] = [x.strip() for x in v.split("；") if x.strip()]
        elif k == "背景" and v:
            p["背景"] = [x.strip() for x in v.split("；") if x.strip()]
        elif k == "心情" and v:
            p["情绪"] = v
    return {k: v for k, v in p.items() if v or k in ("局面", "要表达的")}


def kind_of(card_text: str) -> str:
    m = re.search(r"^场合：(.*)$", card_text or "", re.M)
    return m.group(1).strip() if m else ""
