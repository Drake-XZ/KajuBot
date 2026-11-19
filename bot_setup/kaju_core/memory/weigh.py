"""记忆轻重的纯逻辑：保留强度（遗忘曲线）、关键词、"有没有用上"、解析 memorix 注入的检索结果。

不依赖 astrbot，方便离线测试。
"""

from __future__ import annotations

import math
import re
from collections import Counter

# 分量 → 没用过时的半衰期（天）。用上一次，半衰期翻倍（最多 ×32），并从用上那一刻重新算。
DEFAULT_HALF_LIFE = {0: 4.0, 1: 15.0, 2: 90.0, 3: 365.0}
GRAVITY_NAMES = {0: "琐碎闲聊", 1: "一般", 2: "要紧", 3: "郑重"}


def half_life_days(gravity: int, uses: int, table: dict | None = None) -> float:
    table = table or DEFAULT_HALF_LIFE
    base = float(table.get(int(gravity), table.get(str(int(gravity)), DEFAULT_HALF_LIFE[1])))
    return base * min(2 ** max(0, int(uses)), 32)


def retention(item: dict, now: float, table: dict | None = None) -> float:
    """0~1：现在还记得多清楚。anchor = 最后一次用上（没用过就是记下的时候）。"""
    anchor = float(item.get("last_used") or item.get("created") or now)
    days = max(0.0, now - anchor) / 86400.0
    return 2.0 ** (-days / half_life_days(item.get("g", 1), item.get("uses", 0), table))


def days_until(item: dict, now: float, threshold: float, table: dict | None = None) -> float:
    """还要多少天保留强度降到 threshold（已经降到了就返回 0）。"""
    r = retention(item, now, table)
    if r <= threshold:
        return 0.0
    return half_life_days(item.get("g", 1), item.get("uses", 0), table) * math.log2(r / threshold)


# ---------------------------------------------------------------- keywords
STOP = set("""
佳树 兄长 兄长大人 大人 哥哥 妹妹 学长 学姐 小佳树 我们 你们 他们 她们 自己 什么 怎么 这个 那个 这样 那样 这些 那些 一下 一点
今天 明天 昨天 现在 时候 知道 觉得 可以 还是 就是 不是 没有 已经 因为 所以 但是 如果 然后 真的 一个 一起
喜欢 东西 事情 问题 看看 说说 一直 有点 还有 这么 那么 怎么样 为什么 好的 好吧 嗯嗯 哈哈 哈哈哈 呢 吧 啊
对方 用户 群友 群里 聊天 对话 提到 表示 询问 回答 回复 表达 告诉 希望 认为 表示 说道 同时 之后 之前 其中
""".split())

_CJK_OR_WORD = re.compile(r"^[一-鿿A-Za-z0-9぀-ヿ]+$")
HONORIFIC = {"大人", "酱", "君", "桑", "殿"}  # "女王" + "大人" → "女王大人"
BASE_WORDS = ["佳树", "小佳树", "兄长大人", "女王大人"]
_jieba = None
_added: set[str] = set()


def _get_jieba():
    global _jieba
    if _jieba is None:
        try:
            import jieba  # type: ignore

            jieba.setLogLevel(60)
            _jieba = jieba
            add_words(BASE_WORDS)
        except Exception:  # noqa: BLE001
            _jieba = False
    return _jieba


def add_words(words) -> None:
    """让分词认识称呼、外号（称呼簿里的、铭记里的），免得"女王大人"被切开。"""
    jb = _get_jieba()
    if not jb:
        return
    for w in words:
        w = str(w or "").strip()
        if 2 <= len(w) <= 12 and w not in _added:
            jb.add_word(w, freq=20000)
            _added.add(w)


def _merge_honorifics(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        if t in HONORIFIC and out and re.match(r"^[一-鿿]+$", out[-1]):
            out[-1] += t
        else:
            out.append(t)
    return out


def _cut(text: str) -> list[str]:
    jb = _get_jieba()
    if jb:
        return _merge_honorifics(jb.lcut(text))
    # 没有 jieba：退化成 2~4 字的片段
    out = []
    for seg in re.findall(r"[一-鿿]+|[A-Za-z0-9]+", text):
        if not re.match(r"[一-鿿]", seg):
            out.append(seg)
            continue
        for n in (2, 3, 4):
            out += [seg[i:i + n] for i in range(len(seg) - n + 1)]
    return out


def keywords(text: str) -> set[str]:
    words = set()
    for w in _cut(text or ""):
        w = w.strip().lower()
        if len(w) < 2 or w in STOP or w.isdigit() or not _CJK_OR_WORD.match(w):
            continue
        words.add(w)
    return words


def doc_freq(docs: list[set[str]]) -> Counter:
    df: Counter = Counter()
    for d in docs:
        df.update(d)
    return df


def common_terms(df: Counter, n_docs: int, ratio: float = 0.15, floor: int = 6) -> set[str]:
    """在很多条记忆里都出现的词（人名、口头禅……）不能拿来判断"用上了哪一条"。"""
    limit = max(floor, int(n_docs * ratio))
    return {t for t, c in df.items() if c > limit}


def used_terms(mem_kw: set[str], reply_kw: set[str], echo_kw: set[str], common: set[str]) -> list[str]:
    """她的回复里出现了这条记忆的哪些特有的词（对方这次自己说过的词不算——那是接话，不是想起来的）。

    算"用上"：至少一个 ≥3 字的特有词，或者至少两个 2 字的特有词。
    """
    hits = sorted((mem_kw & reply_kw) - echo_kw - common, key=lambda t: (-len(t), t))
    if any(len(t) >= 3 for t in hits) or len(hits) >= 2:
        return hits
    return []


def overlap(a: str, b: str) -> float:
    """两句话的字二元组重合度（0~1），用来判断两条铭记是不是同一件事。"""
    def grams(s):
        s = re.sub(r"\W", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


# ---------------------------------------------------------------- memorix 注入块
MEMORIX_MARKER = "【Memorix 自动记忆参考】"
_HIT_LINE = re.compile(r"^(\s*\d+\.\s*)\[([^\]]*)\]\s?(.*)$")


def parse_hits(text: str) -> list[dict]:
    """解析 memorix 注入的"证据列表"：每条 {line, type, hash12, content}。"""
    out = []
    for i, line in enumerate((text or "").split("\n")):
        m = _HIT_LINE.match(line)
        if not m:
            continue
        meta = [s.strip() for s in m.group(2).split("|")]
        h = next((s[5:].strip() for s in meta if s.startswith("hash=")), "")
        if not h:
            continue
        kind = meta[0] if meta and "=" not in meta[0] else ""
        out.append({"line": i, "type": kind, "hash12": h.lower(), "content": m.group(3)})
    return out


def annotate(text: str, labels: dict[int, str]) -> str:
    """在第 line 行末尾加上标注（"这是很郑重的事" / "记得有点模糊了"）。"""
    if not labels:
        return text
    lines = text.split("\n")
    for i, label in labels.items():
        if 0 <= i < len(lines) and label not in lines[i]:
            lines[i] = f"{lines[i]}（{label}）"
    return "\n".join(lines)
