"""群聊里太久以前的对话不再带给主模型（2026-11-13 兄长：她“跟不上进度”）。

AstrBot 按条数留会话历史、不看时间：群里说话少时，三天前的对话一直挂在上下文里。11-13 555 说“这勾八佳树”叫醒她，
上下文里还留着 11-10 晚上她和 555 争“食指还是中指”的那几轮，她就接着那场争论回了一句“佳树看的很清楚是食指呢”。

做法：历史里每条用户消息带着 AstrBot 加的“Current datetime: 2026-11-13 14:02”，从最早一条在 max_hours 小时内的
用户消息开始留，之前的整段去掉（从用户消息处切，工具调用不会被切成半截）。一条时间都读不到就不动。
注意：AstrBot 回完会把这一轮的上下文存回会话历史，所以去掉的旧对话也就从群聊历史里没了（长期记忆、日记里还有）。
"""

import datetime as dt
import re

STAMP = re.compile(r"Current datetime: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") if isinstance(p, dict) else str(getattr(p, "text", "") or "")
                       for p in content)
    return ""


def stamp_of(message) -> dt.datetime | None:
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    found = STAMP.findall(_text(message.get("content")))
    if not found:
        return None
    try:
        return dt.datetime.strptime(found[-1], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def trim(contexts: list, now: dt.datetime, max_hours: float) -> tuple[list, int]:
    """(留下的, 去掉了几条)。now 是和 AstrBot 打时间用同一个时区的“现在”（不带时区）。"""
    if not contexts or max_hours <= 0:
        return contexts, 0
    stamped = [(i, s) for i, m in enumerate(contexts) if (s := stamp_of(m)) is not None]
    if not stamped:
        return contexts, 0
    edge = now - dt.timedelta(hours=max_hours)
    cut = next((i for i, s in stamped if s >= edge), None)
    if cut is None:  # 带时间的都太旧：最后一条带时间的用户消息之后的（多半是她的回复）也一起去掉
        cut = len(contexts)
    return contexts[cut:], cut
