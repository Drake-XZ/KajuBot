"""触景生情（纯逻辑，不依赖 astrbot）。

思路来自"小凌"的可检索性设计：一段记忆平时还在，只是很难被主动想起；
某一天一句话、一个名字、一首歌和当年对上了，它会自己冒出来——先冒出来的常常只是一个片段。

可检索性 R = sigmoid(0.9·意义 + 0.8·情绪残留 + 4.13·线索 + 0.4·新近 + 0.3·想起过的次数 − 0.7·干扰 − 3.44)
（权重沿用视频里的：同一段重要的记忆，线索 0.05 时 R≈0.12，线索 0.9 时 R≈0.82）
- 意义 = 分量/3，情绪残留 = 当时情绪强度（memory_weight 打分量时记下的），干扰 = 同一个聊天里差不多的事有多少。
- 线索：这句话和这段记忆共有的词，越少见的词越算数（一个"欺负""出头"比十个"今天""表情"有用）；
  只有很常见的词对上，线索打对折。
memorix 自己的检索只按"这句话问的是什么"找最像的几条，这里补的是"被一个词勾起来"的那种回忆。
"""

from __future__ import annotations

import math
import re

W = {"s": 0.9, "e": 0.8, "cue": 4.13, "recency": 0.4, "recall": 0.3, "interf": 0.7, "bias": -3.44}

# 记忆开头的时间、场合和心里话的套话，对上了也不算线索
CUE_STOP = set("""
上午 中午 下午 晚上 深夜 凌晨 早上 傍晚 半夜 今晚 昨晚 今早 那天 当时 后来 刚才 一会儿 现在 最近
私聊 群聊 群里 心里 心声 记下 以后 出来 别人 别的 时候 一下 有点 他说 她说 发来 说出 出口 起来 一直
兄长 兄长大人 佳树 温水 温水佳树 学长 学姐 群友 大家 对方 一起 东西 事情 感觉 觉得 好像 可能 还是 就是
早安 晚安 午安 早上好 晚上好 中午好 下午好 拜拜 再见 谢谢 哈哈 哈哈哈 嘿嘿 嗯嗯 好的 好吧 没事 不用 惦记 喜欢 开心 难过
""".split())


def idf_norm(df: int, n: int) -> float:
    """0~1：这个词在所有记忆里有多少见（只在一条里出现 ≈ 1，到处都有 ≈ 0）。"""
    if n <= 1:
        return 1.0
    return max(0.0, min(1.0, math.log((n + 1) / (df + 0.5)) / math.log(n + 1)))


_GENERAL: dict = {}


def general_rarity(term: str) -> float:
    """0~1：这个词在平常说话里有多少见（jieba 自带的词频；"那种""重要"≈0，"欺负"≈0.5，"我爱你""pjsk"≈1）。
    记忆只有几百条，光看记忆里的词频，"那种""的话"也显得很少见。"""
    if term in _GENERAL:
        return _GENERAL[term]
    try:
        from .weigh import _get_jieba
    except ImportError:  # 离线单独导入时
        from weigh import _get_jieba  # type: ignore
    jb = _get_jieba()
    if not jb:
        return 1.0
    dt_ = jb.dt
    if not getattr(dt_, "initialized", True):
        dt_.initialize()
    freq = dt_.FREQ.get(term, 0)
    r = max(0.0, min(1.0, (math.log(max(1, dt_.total) / (freq + 1)) - 9.5) / 4))
    _GENERAL[term] = r
    return r


def cue_score(msg_kw: set[str], mem_kw: set[str], df: dict, n: int, common: set[str],
              strong_at: float = 0.5) -> tuple[float, list[str]]:
    """这句话对这段记忆的线索强度（0~1）和对上的词（按少见程度排）。"""
    hits = [t for t in (msg_kw & mem_kw) if t not in common and t not in CUE_STOP and len(t) >= 2]
    if not hits:
        return 0.0, []
    ws = {t: idf_norm(int(df.get(t, 1)), n) * (0.15 + 0.85 * general_rarity(t)) for t in hits}
    hits.sort(key=lambda t: (-ws[t], -len(t), t))
    score = 1 - math.exp(-sum(ws.values()))
    if max(ws.values()) < strong_at:
        score *= 0.5  # 只对上了到处都有的词
    elif len(hits) == 1 and len(hits[0]) < 3 and ws[hits[0]] < 0.5:
        score *= 0.6  # 只对上一个不太特别的两个字的词，多半是巧合
    return round(score, 3), hits


def retrievability(s: float, e: float, cue: float, recency: float, recall: float, interf: float) -> float:
    z = (W["s"] * s + W["e"] * e + W["cue"] * cue + W["recency"] * recency + W["recall"] * recall
         - W["interf"] * interf + W["bias"])
    return 1 / (1 + math.exp(-z))


def features(p: dict, now: float, recency_days: float = 30.0, inner: bool = False) -> dict:
    """inner：她自己的心里话本身就是"留下来的感觉"，情绪残留至少算 0.5。"""
    anchor = float(p.get("last_used") or p.get("created") or now)
    e = min(1.0, float(p.get("e") or 0))
    return {"s": min(1.0, int(p.get("g") or 0) / 3), "e": max(e, 0.5) if inner else e,
            "recency": 2 ** (-max(0.0, now - anchor) / 86400 / recency_days),
            "recall": min(1.0, int(p.get("uses") or 0) / 3), "interf": min(1.0, float(p.get("i") or 0))}


def worth(p: dict, inner: bool, min_s: float = 0.66, min_e: float = 0.4) -> bool:
    """琐碎的事不会被"勾起来"：要么当时要紧/郑重，要么当时情绪明显，要么是她自己的心里话。"""
    f = features(p, 0)
    return inner or f["s"] >= min_s or f["e"] >= min_e


def fragment(text: str, terms: list[str], max_sentences: int = 2, longer_than: int = 80) -> str:
    """长的聊天摘要：先冒出来的只是被勾到的那一两句（含对上的词的句子），不是整段。"""
    if len(text) <= longer_than:
        return text
    parts = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    keep = [i for i, s in enumerate(parts) if any(t in s for t in terms)][:max_sentences]
    if not keep:
        return text
    out = "".join(parts[i] for i in keep).strip()
    return ("……" if keep[0] > 0 else "") + out + ("……" if keep[-1] < len(parts) - 1 else "")


def when_words(days: float) -> str:
    if days < 2:
        return "前两天"
    if days < 7:
        return "前几天"
    if days < 21:
        return "前阵子"
    if days < 60:
        return "一两个月前"
    if days < 300:
        return "好几个月前"
    return "很久以前"


NOTE = ("【触景生情】对方这句话里的「{terms}」让你一下想起了{when}的一件事：{text}{feel}\n"
        "这是自己冒出来的回忆，不是对方问的：可以自然地带一句（比如\"说到{term0}，佳树突然想起……\"），"
        "也可以只让它在心里、在语气里轻轻带过；先回应对方这句话本身，别整段复述；没写到的细节别补。")
