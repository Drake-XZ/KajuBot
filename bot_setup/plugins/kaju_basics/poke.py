"""被戳的时候：戳她的人是谁、TA刚才说了什么（2026-11-09）。

QQ 的戳一戳事件不带昵称（发言人只剩 QQ 号），也不带任何话；原来只告诉她"（有人戳了戳你）"。
11-09 群里哆啦a梦先说"说的就是你，你去看看 autodl 还有卡吗"（没 @、没叫名字，插话又在冷却），
16 秒后戳了她一下 → 她只看到"有人戳了戳你"，回了"444444444学姐是想说点什么呢"。

这里记下群里每个人最近说的话（只记文字），被戳时：
- 名字用 TA 在群里最近用的名字（群名片），不用 QQ 号；
- TA 在她上次说话之后、几分钟内说过的话一起交给她（戳一下多半就是"叫你看我刚才那句"）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

BASE = "（有人戳了戳你）"


class Lines:
    def __init__(self, keep: int = 60):
        self._lines: dict[str, deque] = defaultdict(lambda: deque(maxlen=keep))
        self._replied: dict[str, float] = {}

    def note(self, umo: str, sender: str, name: str, text: str, t: float | None = None) -> None:
        text = " ".join((text or "").split())
        if sender and (text or name):
            self._lines[umo].append((str(sender), name or "", text, t or time.time()))

    def replied(self, umo: str, t: float | None = None) -> None:
        self._replied[umo] = t or time.time()

    def name_of(self, umo: str, sender: str) -> str:
        for s, name, _, _ in reversed(self._lines.get(umo) or ()):
            if s == str(sender) and name and not name.isdigit():
                return name
        return ""

    def recent(self, umo: str, sender: str, window: float = 180.0, n: int = 3, now: float | None = None) -> list[str]:
        """TA 在她上次说话之后、window 秒内说的话（最多 n 条，按时间先后）。"""
        now = now or time.time()
        since = max(now - window, self._replied.get(umo, 0.0))
        out = [text for s, _, text, t in self._lines.get(umo) or () if s == str(sender) and t > since and text]
        return [x[:80] for x in out[-n:]]


def poke_text(recent: list[str]) -> str:
    if not recent:
        return BASE
    said = "".join(f"「{x}」" for x in recent)
    return f"（有人戳了戳你。戳你之前，TA刚说了：{said}）"
