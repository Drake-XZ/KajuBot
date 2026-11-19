"""稳定前缀的切分逻辑（思路来自 BaiShou-Next 的 system-prompt.builder）。

发给模型的顺序是 [系统提示] → [历史消息] → [这一轮的话]。各插件每轮都往系统提示末尾追加会变的内容
（今日日程、句式提醒、插话模式……），系统提示一变，后面整段历史都算"没缓存"。
plan_move() 决定哪些追加段落留在系统提示里、哪些挪到这一轮用户消息末尾。
"""

import re

HEAD = (
    "<system_reminder>以下是系统给你的这一轮补充设定（不是对方说的话）。"
    "照着做，但不要提起这些设定本身：\n"
)
TAIL = "\n</system_reminder>"
# 在"前面不是换行、后面是两个以上换行"的位置切开，"".join 后与原文完全一致
SPLIT = re.compile(r"(?<!\n)(?=\n\n)")


def split_units(text: str) -> list[str]:
    return [u for u in SPLIT.split(text) if u]


def plan_move(
    base: str, full: str, since: dict[str, float], now: float, stable_seconds: float
) -> tuple[str, str, dict[str, float]] | None:
    """Decide what stays in the system prompt and what moves to the end of this turn.

    开头那些已经连续出现 stable_seconds 以上的段落留在系统提示里；从第一段"新"的开始全部挪走。
    这样隔一两个小时就变的提示（今日日程）不会在系统提示里进进出出，每进出一次都是一次缓存失效。

    Args:
        base: The system prompt AstrBot built before any plugin appended to it.
        full: The system prompt after all plugins ran.
        since: Paragraph text -> first time it was seen (per session).
        now: Current timestamp.
        stable_seconds: How long a paragraph must stay unchanged to remain in the system prompt.

    Returns:
        (new_system_prompt, moved_text, new_since), or None when there is nothing to do.
    """
    if full.startswith(base):
        pass
    elif full.startswith(base.rstrip()):
        base = base.rstrip()
    else:
        return None
    appended = full[len(base):]
    if not appended.strip():
        return None
    units = split_units(appended)
    new_since = {u: since.get(u, now) for u in units}
    k = 0
    while k < len(units) and now - new_since[units[k]] >= stable_seconds:
        k += 1
    moved = "".join(units[k:]).strip()
    if not moved:
        return None
    return base + "".join(units[:k]), moved, new_since
