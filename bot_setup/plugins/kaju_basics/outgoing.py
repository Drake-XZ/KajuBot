"""发出去之前的检查（2026-10-31：群里同一段话连发三遍，其中一遍还带着 "&&confused&&"）。

那次是模型在同一轮里：先写了回复正文（还附带一个工具调用，AstrBot 会把这段正文先发出去），
又用内置工具 send_message_to_user 把同一段话发了一遍（工具直接发，不经过表情包插件，所以
&&confused&& 原样发了出去），最后的回复又是同一段话。

- 平常聊天不给她 send_message_to_user（她直接回复就行；定时提醒那种后台任务不受影响，见 main.py）。
- 同一轮里已经发过的行，后面再出现就不发（drop_repeated）。
- 表情包插件没认出来的 &&标签&&，发出去之前去掉（strip_meme_tags）。
"""

import re

MEME_TAG = re.compile(r"&&[^&\n]{1,60}&&")
# 按小句比较：同一段话重说时标点常常变（"，"变"！"、"——"变"，"），小句本身不变
_UNIT_SPLIT = re.compile(r"[\s。！？!?，,、;；:：~～…\.·\-—]+")
_NOISE = re.compile(r"[\"“”'‘’（）()「」『』]+")


def strip_meme_tags(text: str) -> str:
    """Remove leftover &&tag&& markers and the blank lines they leave behind."""
    if "&&" not in (text or ""):
        return text
    out = MEME_TAG.sub("", text)
    return "\n".join(line for line in out.split("\n") if line.strip()) if out.strip() else ""


def units(text: str) -> list[str]:
    """Clauses of a reply (split on any punctuation), without meme tags, quotes or one-character bits."""
    out = []
    for piece in _UNIT_SPLIT.split(MEME_TAG.sub("", text or "")):
        piece = _NOISE.sub("", piece)
        if len(piece) >= 2:
            out.append(piece)
    return out


def drop_repeated(text: str, said: set[str]) -> tuple[str, int]:
    """Drop lines whose every clause was already sent earlier in this turn.

    Args:
        text: The reply about to be sent (may contain meme tags).
        said: Clauses (see units) already sent in this turn.

    Returns:
        (kept text, number of dropped lines). When every line with words was dropped, the kept text
        is "" (a lone meme tag is not worth sending on its own).
    """
    kept, dropped, words_left = [], 0, False
    for line in (text or "").split("\n"):
        us = units(line)
        if us and all(u in said for u in us):
            dropped += 1
            continue
        if us:
            words_left = True
        kept.append(line)
    if dropped and not words_left:
        return "", dropped
    return "\n".join(kept), dropped
