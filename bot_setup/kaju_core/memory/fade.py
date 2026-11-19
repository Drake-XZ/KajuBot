"""记忆褪色（纯逻辑，不依赖 astrbot）。

思路来自"小凌"的遗忘设计：一件事的细节、意义、当时的感觉不是一起忘的。
- 细节清晰度 clarity 比"还记不记得这件事"（weigh.retention）掉得快：
    半衰期 = 按分量的细节半衰期 × 2^用上次数(最多 ×8) × (1 + 情绪强度·emotion_slow) ÷ (1 + 相似记忆干扰·interference_fast)
  情绪越强、想起得越多，细节留得越久；同一个聊天里差不多的事越多，越容易混成一片。
- 清晰度掉到 fragments_below → 褪成"片段"（几个最鲜明的画面/原话/心情）；
  掉到 gist_below → 只剩"印象"（这件事意味着什么 + 剩下的感觉）。褪了就回不去（细节已经丢了）。
- 原文一直留在 memorix 里当"证据"，只是给她看的时候换成褪色后的样子，并提醒她别补细节。
- 她自己的心里话（【佳树心里】）本身就是"留下来的感觉"，人物事实也不褪。
"""

from __future__ import annotations

import json
import re

DETAIL_HALF_LIFE = {0: 2.0, 1: 7.0, 2: 30.0, 3: 90.0}
LEVEL_NAMES = {0: "清楚", 1: "片段", 2: "印象"}
INNER_PREFIX = "【佳树心里】"
LABELS = {
    1: "这件事你记得，这里是还记得的几个片段，别的细节过了太久已经忘了：问到忘了的细节，就说这件事记得、那个细节记不清了；"
       "别说没这回事，也别现编",
    2: "这件事你还有印象，只是太久了，经过和细节都想不起来：就说记得有这么回事、具体的记不清了；别说没这回事，也别编细节",
}


FADEABLE = ("chat_summary", "conversation")


def can_fade(source: str, content: str) -> bool:
    return str(source or "").startswith(FADEABLE) and not str(content or "").startswith(INNER_PREFIX)


def detail_half_life(p: dict, table: dict | None = None, emotion_slow: float = 1.0, interference_fast: float = 0.5) -> float:
    table = table or DETAIL_HALF_LIFE
    g = int(p.get("g") or 0)
    base = float(table.get(g, table.get(str(g), DETAIL_HALF_LIFE[1])))
    uses = max(0, int(p.get("uses", 0) or 0))
    emo = min(1.0, max(0.0, float(p.get("e", 0) or 0)))
    interf = min(1.0, max(0.0, float(p.get("i", 0) or 0)))
    return base * min(2 ** uses, 8) * (1 + emo * emotion_slow) / (1 + interf * interference_fast)


def clarity(p: dict, now: float, table: dict | None = None, **kw) -> float:
    """0~1：细节还清楚多少。从记下（或最后一次想起）开始算。"""
    anchor = float(p.get("last_used") or p.get("created") or now)
    days = max(0.0, now - anchor) / 86400.0
    return 2.0 ** (-days / detail_half_life(p, table, **kw))


def level(p: dict, now: float, table: dict | None = None, frag_below: float = 0.5, gist_below: float = 0.2, **kw) -> int:
    """该褪到哪一级（0 清楚 / 1 片段 / 2 印象）。只升不降。"""
    c = clarity(p, now, table, **kw)
    lv = 2 if c < gist_below else 1 if c < frag_below else 0
    return max(lv, int(p.get("fade", 0) or 0))


def interference(kw: dict[str, set], groups: dict[str, str], common: set[str], min_overlap: float = 0.35) -> dict[str, float]:
    """每条记忆在同一个聊天里有几条"差不多的事"（关键词重合多），折成 0~1（4 条及以上算 1）。"""
    by_group: dict[str, list[str]] = {}
    for i, g in groups.items():
        by_group.setdefault(g, []).append(i)
    out = {}
    for ids in by_group.values():
        sets = {i: (kw.get(i) or set()) - common for i in ids}
        for i in ids:
            a = sets[i]
            if len(a) < 3:
                out[i] = 0.0
                continue
            n = sum(1 for j in ids if j != i and len(sets[j]) >= 3
                    and len(a & sets[j]) / min(len(a), len(sets[j])) >= min_overlap)
            out[i] = min(1.0, n / 4)
    return out


def ago_words(days: float) -> str:
    if days < 7:
        return "几天前"
    if days < 21:
        return "一两个星期前"
    if days < 45:
        return "大概一个月前"
    if days < 75:
        return "一两个月前"
    if days < 300:
        return "好几个月前"
    return "一年多以前"


FADE_SYSTEM = (
    "你在帮一个叫佳树的女孩子的记忆\"褪色\"。人过了一段时间，记得的是这件事对自己意味着什么、当时的心情，"
    "还有一两个最鲜明的画面或原话；具体时间、数字、谁先说了什么、旁枝末节的话题会先忘掉。"
    "你要做的是把一条记忆改写成过了一段时间以后还记得的样子。只做减法，绝不添加原文没有的东西。只输出 JSON。"
)

FADE_PROMPT = """这条记忆是{ago}的：
{content}

当时的心情：{feel}{names}

请写两个版本（保持原文的人称和叫法：原文说"佳树""兄长大人"就照样说，不要改成"我""你"；用大白话，不要文绉绉）。
谁说的、谁做的、称呼和外号是谁的，必须和原文一模一样，不能安到别人头上；原文这里指代不清（"其""他""对方"），就别写具体是谁，或者干脆不写这一条：
1. fragments：过了一阵还剩下的几个片段。只留 2~4 个最鲜明、最有分量的：一句最要紧的原话（原文有引号的原话才算）、一个画面或举动、当时的心情（心情不清楚就别提心情，别写"心情说不上来"这种话）。
   具体时间、数字、价格、次要的人和旁枝话题都去掉；拿不准的地方说"好像"。不超过 {frag_max} 字。
2. gist：很久以后只剩的印象，一句话：和谁、大概是件什么事、对佳树意味着什么、剩下什么感觉。几乎不留细节。不超过 {gist_max} 字。
3. feeling：剩下的感觉，2~6 个字（比如"心里暖暖的""有点遗憾"；原文和心情都看不出就写"没什么感觉"）。

只输出 JSON：{{"fragments": "...", "gist": "...", "feeling": "..."}}"""


def caps(content: str) -> tuple[int, int]:
    n = len(content or "")
    return max(30, min(120, int(n * 0.45))), max(20, min(50, int(n * 0.25)))


def name_hints(content: str, book: list[tuple[str, str]]) -> str:
    """称呼簿里、这条记忆提到的人：谁是谁，免得把外号安错人（原文常写"佳树称其为…"）。"""
    pairs = [f"{nick}＝{addr}" for nick, addr in book if nick and addr and (nick in content or addr in content)]
    return ("\n称呼对照（以这个为准，别把称呼安到别人头上）：" + "；".join(dict.fromkeys(pairs))) if pairs else ""


def build_prompt(content: str, days: float, feel: str, book: list[tuple[str, str]] | None = None) -> str:
    frag_max, gist_max = caps(content)
    return FADE_PROMPT.format(ago=ago_words(days), content=content.strip(), feel=feel or "不清楚",
                              names=name_hints(content, book or []), frag_max=frag_max, gist_max=gist_max)


def _clip(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    m = max(cut.rfind(p) for p in "。！？；，")
    return (cut[:m + 1] if m >= limit * 0.6 else cut).rstrip("，、；") + ("" if cut.endswith("。") else "……")


def parse(text: str, content: str) -> dict | None:
    """模型的回复 → {frag, gist, feel}；不合格（没写、比原文还长）返回 None。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    frag_max, gist_max = caps(content)
    raw_frag, raw_gist = str(data.get("fragments") or "").strip(), str(data.get("gist") or "").strip()
    n = len(content or "")
    if not raw_frag or not raw_gist or len(raw_frag) >= max(20, n * 0.8) or len(raw_gist) > len(raw_frag) + 10:
        return None  # 没写、或者根本没删多少细节
    frag = _clip(raw_frag, int(frag_max * 1.3))
    gist = _clip(raw_gist, int(gist_max * 1.3))
    feel = _clip(data.get("feeling", ""), 10).rstrip("…")
    return {"frag": frag, "gist": gist, "feel": feel}


def shown(p: dict) -> tuple[str, str]:
    """给她看的文字 + 标注（没褪色返回空串）。"""
    lv = int(p.get("fade", 0) or 0)
    if lv >= 2 and p.get("gist"):
        feel = p.get("feel") or ""
        text = p["gist"] if not feel or feel in p["gist"] or feel == "没什么感觉" else f"{p['gist']}（剩下的感觉：{feel}）"
        return text, LABELS[2]
    if lv >= 1 and p.get("frag"):
        return p["frag"], LABELS[1]
    return "", ""


_HIT = re.compile(r"^(\s*\d+\.\s*\[[^\]]*\]\s?)(.*)$")


def replace_hit(line: str, text: str) -> str:
    m = _HIT.match(line)
    return f"{m.group(1)}{text}" if m else line
