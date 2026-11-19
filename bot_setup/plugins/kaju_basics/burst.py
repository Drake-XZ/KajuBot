"""私聊连发合并：对方一口气连着发几条（一句话、一张图、再补一句），合成一轮、回一次。

2026-11-01：兄长引用她的话说"不是这个哦"，接着发了张图，又补一句"是上面图这样的"。三条各自触发一轮，
图那一轮和补充那一轮把同一张图回了两遍（"原来是打歌用的手台呀～……""原来是这种打歌台呀……"）。

两道关：
1. 等对方说完（hold）：私聊消息到了先等 quiet 秒；这期间又来一条，就并进新来的那条（旧的不单独回了）。
   QQ 推来"对方正在输入"时多等 grace 秒。从这一串第一条算起最多等 max_hold 秒。
2. 回之前再看一眼（catch up）：真要请求模型时（拿到会话锁，前一轮刚回完），后面又有还没回的消息，
   这一条就交给最新那条一起回（max_total 秒内；再久就先回了，免得对方一直说、她一直不回）。
   新消息一到就记下（arrived），要是已经到了、还没排进来，先等它几秒（catch_up_wait）再看。

并起来的那条：消息链按顺序拼起来（图片、引用、文件都还在，AstrBot 照常处理），文字一条一行，
只有图/视频/文件的那条写成 [图片]/[视频]/[文件 名字]，让模型知道先后。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from astrbot.api.message_components import File, Image, Json, Record, Reply, Video

HOLDING, WAITING, YIELDED = "holding", "waiting", "yielded"
QUOTE_CHARS = 40


@dataclass
class Part:
    """对方发的一条消息。"""

    t: float
    text: str
    comps: list = field(default_factory=list)

    def kinds(self) -> list[str]:
        out = []
        for c in self.comps:
            k = ("图" if isinstance(c, Image) else "视频" if isinstance(c, Video) else "文件" if isinstance(c, File)
                 else "语音" if isinstance(c, Record) else "卡片" if isinstance(c, Json) else "")
            if k and k not in out:
                out.append(k)
        if self.text.strip():
            out.insert(0, "文字")
        return out or ["文字"]

    def quote(self):
        for c in self.comps:
            if isinstance(c, Reply):
                return c
        return None


@dataclass
class Pending:
    event: object
    seq: int
    sender: str
    parts: list[Part]
    state: str = HOLDING

    @property
    def first_t(self) -> float:
        return min(p.t for p in self.parts)

    @property
    def last_t(self) -> float:
        return max(p.t for p in self.parts)


def placeholder(comps) -> str:
    out = []
    for c in comps:
        if isinstance(c, Image):
            out.append("[图片]")
        elif isinstance(c, Video):
            out.append("[视频]")
        elif isinstance(c, File):
            out.append(f"[文件 {getattr(c, 'name', '') or ''}]".replace(" ]", "]"))
        elif isinstance(c, Record):
            out.append("[语音]")
    return "".join(out)


def quote_text(reply) -> str:
    text = " ".join(str(getattr(reply, "message_str", "") or "").split())
    if len(text) > QUOTE_CHARS:
        text = text[:QUOTE_CHARS] + "…"
    who = getattr(reply, "sender_nickname", "") or "一条消息"
    return f"（引用{who}：「{text}」）" if text else f"（引用了{who}的消息）"


def merged_text(parts: list[Part]) -> str:
    """一条一行。第一条带引用的由 AstrBot 自己处理（<Quoted Message>），后面的引用写进这一行。"""
    lines, quoted = [], False
    for part in parts:
        media = placeholder(part.comps)
        text = part.text.strip()
        if media and text.startswith(media):  # 有的平台 message_str 里已经写了 [图片]
            media = ""
        line = " ".join(x for x in (media, text) if x)
        q = part.quote()
        if q is not None:
            if quoted:
                line = quote_text(q) + line
            quoted = True
        if line:
            lines.append(line)
    return "\n".join(lines)


def apply(event, parts: list[Part]) -> None:
    """把几条合成的内容写回这个事件（消息链原地改，别的插件拿着的引用也跟着变）。"""
    if len(parts) < 2:
        return
    chain = event.get_messages()
    comps = [c for p in parts for c in p.comps]
    if chain is not None:
        chain[:] = comps
    text = merged_text(parts)
    event.message_str = text
    obj = getattr(event, "message_obj", None)
    if obj is not None and hasattr(obj, "message_str"):
        obj.message_str = text


def describe(parts: list[Part]) -> str:
    """给模型看的先后：文字、图、文字。"""
    return "、".join("+".join(p.kinds()) for p in parts)


def is_input_status(raw) -> bool:
    get = getattr(raw, "get", None)
    if get is None:
        return False
    try:
        return get("post_type") == "notice" and get("sub_type") == "input_status"
    except Exception:  # noqa: BLE001
        return False


class Bursts:
    """每个私聊一串还没回的消息。时钟可注入（测试用）。"""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._q: dict[str, list[Pending]] = {}
        self._typing: dict[str, float] = {}
        self.typing_kind: dict[str, object] = {}
        self._reply: dict[str, tuple[float, float]] = {}  # 聊天 → (最近一次开始发回复, 最近一次发完)
        self._arrived: dict[str, list[tuple[float, str, object]]] = {}  # 聊天 → 刚到、还没排进来的 (时间, 谁, 事件)
        self._seq = 0

    # ---------------------------------------------------------------- 刚到的
    def arrived(self, umo: str, event, sender: str, t: float | None = None) -> None:
        """一条消息刚到（别的插件还在记它，过一会儿才排进来）。

        2026-11-02：她正要回"而且节奏很快"，43 毫秒前"也没多少剧情"已经到了，可还没走到排队那一步，
        回之前那一眼没看见它 → 两条各回一遍，连着 7 句。"""
        t = self.clock() if t is None else t
        lst = [x for x in self._arrived.get(umo, []) if t - x[0] < 60]
        lst.append((t, sender, event))
        self._arrived[umo] = lst

    def forget(self, umo: str, event) -> None:
        lst = [x for x in self._arrived.get(umo, []) if x[2] is not event]
        if lst:
            self._arrived[umo] = lst
        else:
            self._arrived.pop(umo, None)

    def on_the_way(self, umo: str, p: "Pending", limit: float = 10.0) -> int:
        """比 p 晚到、同一个人、还没排进来的有几条（被别的插件拦下的、太久的不算）。"""
        now, n = self.clock(), 0
        for t, sender, ev in self._arrived.get(umo, []):
            if ev is p.event or sender != p.sender or t < p.last_t or now - t > limit:
                continue
            try:
                if ev.is_stopped():
                    continue
            except Exception:  # noqa: BLE001
                pass
            n += 1
        return n

    # ---------------------------------------------------------------- 记录
    def typing(self, umo: str, t: float | None = None, kind=None) -> None:
        """QQ 推来"对方正在输入"（OneBot notice input_status；kind = 它的 event_type，含义还没摸清，只记日志）。"""
        self._typing[umo] = self.clock() if t is None else t
        self.typing_kind[umo] = kind

    def typed_after(self, umo: str, t: float) -> float | None:
        tt = self._typing.get(umo)
        return tt if tt is not None and tt > t else None

    def reply_started(self, umo: str, t: float | None = None) -> None:
        _, end = self._reply.get(umo, (0.0, 0.0))
        self._reply[umo] = (self.clock() if t is None else t, end)

    def reply_sent(self, umo: str, t: float | None = None) -> None:
        start, _ = self._reply.get(umo, (0.0, 0.0))
        self._reply[umo] = (start, self.clock() if t is None else t)

    def unseen_reply(self, umo: str, since: float) -> bool:
        """对方从 since 开始发的这些，是不是在她上一条回复发完之前发的（对方多半还没看到那条回复）。"""
        start, end = self._reply.get(umo, (0.0, 0.0))
        if end > since:
            return True
        # 回复正在发（分段发要几秒）；after_message_sent 偶尔不触发，超过 60 秒就不算
        return start > end and start > since - 60 and self.clock() - start < 60

    # ---------------------------------------------------------------- 一串消息
    def add(self, umo: str, event, part: Part, sender: str) -> Pending:
        """来了一条：还在等的旧消息都并进这条（旧的不单独回了）。"""
        self._seq += 1
        self.forget(umo, event)
        p = Pending(event=event, seq=self._seq, sender=sender, parts=[part])
        queue = [x for x in self._q.get(umo, []) if self._alive(x)]
        older = [x for x in queue if x.state == HOLDING and x.sender == sender]
        if older:
            p.parts = [pt for x in older for pt in x.parts] + p.parts
            for x in older:
                x.state = YIELDED
            queue = [x for x in queue if x not in older]
            apply(event, p.parts)
        queue.append(p)
        self._q[umo] = queue
        return p

    def hold_until(self, umo: str, p: Pending, quiet: float, grace: float, max_hold: float) -> float:
        until = p.last_t + quiet
        tt = self.typed_after(umo, p.last_t)
        if tt is not None:
            until = max(until, tt + grace)
        return min(until, p.first_t + max_hold)

    def newer(self, umo: str, p: Pending) -> Pending | None:
        """比 p 晚来、还没回的消息里最新的一条。"""
        best = None
        for x in self._q.get(umo, []):
            if x is p or x.seq <= p.seq or x.sender != p.sender or x.state not in (HOLDING, WAITING):
                continue
            if not self._alive(x):
                continue
            if best is None or x.seq > best.seq:
                best = x
        return best

    def hand_over(self, umo: str, p: Pending, n: Pending) -> None:
        """p 不单独回了，内容放到 n 前面一起回。"""
        n.parts = p.parts + n.parts
        p.state = YIELDED
        self.done(umo, p)
        apply(n.event, n.parts)

    def done(self, umo: str, p: Pending) -> None:
        queue = [x for x in self._q.get(umo, []) if x is not p and self._alive(x)]
        if queue:
            self._q[umo] = queue
        else:
            self._q.pop(umo, None)

    def _alive(self, x: Pending) -> bool:
        ev = x.event
        if x.state == YIELDED or self.clock() - x.last_t > 300:
            return False
        try:
            if ev.is_stopped():
                return False
            # 被 AstrBot 当成追问并进了正在跑的那一轮（follow-up），它不会自己再回了
            if ev.get_extra("_follow_up_captured"):
                return False
        except Exception:  # noqa: BLE001
            pass
        return True
