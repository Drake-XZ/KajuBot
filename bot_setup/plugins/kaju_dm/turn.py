"""把一段B站/抖音私信当成"这个人发来的私聊"送进 AstrBot 的完整流程（做法同 qzone_post/turn.py）。

完整流程 = 人设、长期记忆、心情和好感、称呼、看视频看图、写手……都和 QQ 私聊一样。
会话：兄长本人 → 就是他的 QQ 私聊（同一段聊天记录，在哪边聊她都记得）；别人 → "bili_<uid>" 自己一段。
区别只有发出去这一步：她每说一句（含看视频前那句"先去看"），不发 QQ，交给 on_line 发成私信。
私信不靠 QQ 本身：只借 AstrBot 的 aiocqhttp 适配器把消息送进流程；QQ 没连上（拿不到客户端）就用 NoQQ 顶上。
"""

from __future__ import annotations

import asyncio
import time
import uuid

DM_KEY = "kaju_dm"        # event extra：这一轮是私信（值：{site, uid, name, note...}）
DONE_KEY = "_kaju_dm_done"  # on_agent_done 时写入 {t, err}


class NoQQ:
    """QQ 客户端拿不到时顶上：私信这一轮用不到 QQ，谁要调 QQ 接口就报错（调的地方本来都接着异常）。"""

    async def call_action(self, action: str, **params):
        raise RuntimeError(f"QQ 没连上（{action}）")


def plain_lines(message) -> list[str]:
    """MessageChain → 里面的文字（图片另外由 chain_images() 拿）。"""
    text = "".join(getattr(c, "text", "") for c in getattr(message, "chain", []) or []
                   if type(c).__name__ == "Plain")
    text = text.strip()
    if not text or text.upper() == "[SKIP]":
        return []
    return [text]


def chain_images(message) -> list:
    """MessageChain 里的图片（表情包之类）。"""
    return [c for c in getattr(message, "chain", []) or [] if type(c).__name__ == "Image"]


def make_event(platform, bot, self_id: str, session: str, sender: str, name: str, text: str,
               images: list[str], extra: dict, on_line, on_image=None):
    """造一条私聊事件（aiocqhttp 的事件类，只改了 send）。on_line(text) / on_image(Image) 是协程：发成私信。"""
    from astrbot.api.message_components import Image, Plain
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

    class DmEvent(AiocqhttpMessageEvent):
        sent: list[str]
        last_send: float

        async def send(self, message) -> None:
            if message is None:
                return
            for line in plain_lines(message):
                self.sent.append(line)
                try:
                    await on_line(line)
                except Exception:  # noqa: BLE001 — 发不出去由 on_line 自己记日志
                    pass
            for img in (chain_images(message) if on_image else []):
                self.sent.append("[图片]")
                try:
                    await on_image(img)
                except Exception:  # noqa: BLE001
                    pass
            self.last_send = time.time()
            await AstrMessageEvent.send(self, message)  # 只记"发过"，不发到 QQ

        async def send_streaming(self, generator, use_fallback: bool = False) -> None:
            async for chain in generator:
                await self.send(chain)

        async def send_typing(self) -> None:
            return

    comps = ([Plain(text)] if text else []) + [Image.fromURL(u) for u in images]
    obj = AstrBotMessage()
    obj.type = MessageType.FRIEND_MESSAGE
    obj.self_id = str(self_id)
    obj.session_id = str(session)
    obj.message_id = "dm-" + uuid.uuid4().hex[:16]
    obj.sender = MessageMember(user_id=str(sender), nickname=name)
    obj.message = comps
    obj.message_str = text
    obj.raw_message = {"post_type": "message", "message_type": "private", "message": [],
                       "user_id": str(sender), "self_id": str(self_id), "kaju_dm": True}
    obj.timestamp = int(time.time())
    ev = DmEvent(text, obj, platform.meta(), str(session), bot)
    ev.sent = []
    ev.last_send = 0.0
    ev.set_extra(DM_KEY, extra)
    return ev


async def run(platform, event, timeout: float, settle: float = 6.0, sleep=None) -> str:
    """提交事件，等她说完。→ ok / err（模型出错）/ timeout（没跑完：被别的插件拦了、或她没回）。"""
    sleep = sleep or asyncio.sleep
    platform.commit_event(event)
    start = time.time()
    while time.time() - start < timeout:
        await sleep(1.0)
        done = event.get_extra(DONE_KEY)
        if not done:
            continue
        if done.get("err"):
            return "err"
        # 回复按行一句句发（每句间隔一两秒），安静一会儿才算发完
        if time.time() - max(float(done["t"]), event.last_send) >= settle:
            return "ok"
    return "timeout"
