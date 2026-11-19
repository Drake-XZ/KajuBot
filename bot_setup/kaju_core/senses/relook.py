"""补看：对方问到刚看过的视频里某个时间点（"2:10那里拿的什么""第30秒是谁""开头那里写的啥"），
她回去把那一小段再仔细看一遍。这里只管从一句话里认出问的是视频的哪一段（纯函数，好测）。
思路来自 bili-vision 插件（先看全片，不清楚的地方指定时间范围、单帧大图再看）。"""

from __future__ import annotations

import re

_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"(?:\d{1,3}|[零〇一二两三四五六七八九十]{1,4})"

# 01:02:03 / 2:10 / 2：10
_CLOCK = re.compile(r"(?<![\d:：])(?:(\d{1,2})[:：])?(\d{1,3})[:：](\d{2})(?![\d:：])")
# 2分10秒 / 2分钟10秒 / 2分10 / 1分半 / 30秒 / 第30秒 / 3分钟
_CN_TIME = re.compile(
    rf"(?:第\s*)?(?:({_NUM})\s*(?:小时|个小时)\s*)?(?:({_NUM})\s*分(?:钟)?\s*(?:(半)|({_NUM})\s*秒?)?|({_NUM})\s*秒)")
_RANGE_SEP = r"\s*(?:到|至|~|～|-|—|－)\s*"

# 问的是画面：问句、"看"、或者"那里/那段/的时候"这类指着视频某处的说法
_POINTING = re.compile(r"那里|那儿|那块|那段|那一段|那下|那一下|那个画面|那幕|那一幕|的时候|左右|那会儿|处|画面|镜头")
_ASKING = re.compile(r"[?？]|什么|啥|谁|哪|怎么|干嘛|干什么|吗|嘛|看清|看看|再看|仔细|写的|是不是|有没有")
_START = re.compile(r"(?:视频|片子)?(?:的)?(?:开头|一开始|刚开始|最开始|开场)")
_END = re.compile(r"(?:视频|片子)?(?:的)?(?:结尾|最后(?:那|几秒|一段|一下|一幕|的画面|面)|末尾|片尾)")


def cn_number(s: str) -> int | None:
    """"30" / "三十" / "十五" / "二十五" / "两" → 整数；认不出返回 None。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        tens = _CN.get(a, None) if a else 1
        ones = _CN.get(b, None) if b else 0
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    if len(s) == 1 and s in _CN:
        return _CN[s]
    return None


def _times(text: str) -> list[tuple[int, int, float]]:
    """句子里所有像视频时间的说法：[(起始位置, 结束位置, 秒)]。"""
    out = []
    for m in _CLOCK.finditer(text):
        h, mm, ss = m.group(1), int(m.group(2)), int(m.group(3))
        if ss < 60:
            out.append((m.start(), m.end(), float((int(h) * 3600 if h else 0) + mm * 60 + ss)))
    for m in _CN_TIME.finditer(text):
        if any(a <= m.start() < b for a, b, _ in out):
            continue
        g_h, g_min, half, g_sec, g_only = m.groups()
        h, mins, secs, only = cn_number(g_h or ""), cn_number(g_min or ""), cn_number(g_sec or ""), cn_number(g_only or "")
        if only is not None:
            t = float(only)
        elif mins is not None:
            t = mins * 60.0 + (30 if half else (secs or 0))
        else:
            continue
        if h:
            t += h * 3600
        out.append((m.start(), m.end(), t))
    return sorted(out)


def parse_moment(text: str, duration: float | None) -> tuple[float, float] | None:
    """这句话问的是视频的哪一段：返回 (从第几秒, 到第几秒)；不像在问视频某处就返回 None。
    单个时间点返回 (t, t)；"开头/结尾"返回开头、结尾那几秒。时间超出视频长度的不算（多半在说别的时间）。"""
    text = (text or "").strip()
    if not text:
        return None
    dur = float(duration or 0)
    found = _times(text)
    if found:
        if not (_POINTING.search(text) or _ASKING.search(text)):
            return None
        start = found[0][2]
        end = start
        if len(found) > 1 and re.fullmatch(_RANGE_SEP, text[found[0][1]:found[1][0]]):
            end = found[1][2]
        if end < start:
            start, end = end, start
        if dur and start > dur + 1:
            return None
        return (start, min(end, dur) if dur else end)
    if not _ASKING.search(text):
        return None
    span = min(6.0, dur) if dur else 6.0
    if _START.search(text):
        return (0.0, span)
    if _END.search(text) and dur:
        return (max(0.0, dur - span), dur)
    return None


def window(start: float, end: float, duration: float | None, frames: int = 4) -> list[float]:
    """补看截哪几帧：一个时间点就取前后各 2 秒；一段就均匀铺开（最多 frames 帧）。"""
    dur = float(duration or 0)
    if end - start < 1:
        start, end = start - 2, start + 2
    if dur:
        start, end = max(0.0, start), min(end, max(0.0, dur - 0.1))
    start = max(0.0, start)
    if end <= start:
        return [start]
    n = max(2, frames)
    return [round(start + (end - start) * i / (n - 1), 2) for i in range(n)]
