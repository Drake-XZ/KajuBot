"""离得远了就引用：她这次回的那条消息，和回复之间已经隔了别的消息，就用 QQ 的"引用"带上那条。

2026-11-02：兄长连着发"而且节奏很快""也没多少剧情"，她两轮回复挤在一起（3 句 + 4 句），
哪几句回的是哪条看不出来。兄长想要：回复离他那句话比较远时，引用一下那条。

"中间隔了多少"= 这条消息之后、她这次回复之前，聊天里新出现的东西：
- 别人（或他自己）又发的消息，每条算 1；
- 她自己发出去的气泡：整段回复在这条之后才开始发，按气泡数算；这条到的时候她正在发，只算 1。
私聊隔了 ≥ private_gap（默认 1）、群聊 ≥ group_gap（默认 2，群里话多）就引用。
"""

from __future__ import annotations

import time
from collections import deque


class Seen:
    """每个聊天最近出现的消息和她发出去的回复。时钟可注入（测试用）。"""

    def __init__(self, clock=time.time, keep_seconds: float = 3600):
        self.clock = clock
        self.keep = keep_seconds
        self._msgs: dict[str, deque] = {}
        self._replies: dict[str, deque] = {}  # (开始发, 发完, 几个气泡)

    def message(self, umo: str, t: float | None = None) -> float:
        t = self.clock() if t is None else t
        q = self._msgs.setdefault(umo, deque(maxlen=300))
        if q and t <= q[-1]:  # 同一时刻到的几条也要分得出先后
            t = q[-1] + 1e-6
        q.append(t)
        return t

    def reply(self, umo: str, start: float, end: float | None = None, bubbles: int = 1) -> None:
        end = self.clock() if end is None else end
        q = self._replies.setdefault(umo, deque(maxlen=100))
        q.append((start, end, max(1, int(bubbles))))

    def gap(self, umo: str, since: float) -> int:
        """since（他那条到的时间）之后出现了几样东西。"""
        now = self.clock()
        n = sum(1 for t in self._msgs.get(umo, ()) if t > since and now - t < self.keep)
        for start, end, bubbles in self._replies.get(umo, ()):
            if now - end > self.keep:
                continue
            if start > since:
                n += bubbles
            elif end > since:
                n += 1
        return n


def bubbles_of(chain, segmented: bool) -> int:
    """一次发出去几个气泡：分段发时每段一个（引用/@ 不算）；不分段就是一个。"""
    body = [c for c in chain or [] if type(c).__name__ not in ("Reply", "At")]
    if not body:
        return 0
    return len(body) if segmented else 1


def should_quote(gap: int, group: bool, private_gap: int = 1, group_gap: int = 2) -> bool:
    need = group_gap if group else private_gap
    return need > 0 and gap >= need
