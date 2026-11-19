"""把一条 QQ 空间评论当成"这个人发来的私聊"送进 AstrBot 的完整流程，截下她的回复。

走完整流程 = 人设、长期记忆、心情和好感（回完后照常判断）、称呼、日记聊天记录……都和私聊一样；
会话就是和这个人的私聊（umo 相同），所以以后私聊时她也记得评论区里聊过什么。
区别只有一处：回复不发到 QQ 私聊，而是收集起来，由 main.py 发到评论区。
"""

from __future__ import annotations

import time
import uuid

QZ_KEY = "qzone_comment"   # event extra：这条是 QQ 空间评论（值是给提示用的上下文）
DONE_KEY = "_qzone_done"   # on_agent_done 时写入 {t, err}


def make_event(platform, bot, self_uin: str, uin: str, name: str, text: str, extra: dict):
    """造一条私聊事件（aiocqhttp 的事件类，只改了 send）。"""
    from astrbot.api.message_components import Plain
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

    class QzoneCommentEvent(AiocqhttpMessageEvent):
        collected: list[str]
        last_send: float

        async def send(self, message) -> None:
            if message is None:
                return
            text = "".join(getattr(c, "text", "") for c in getattr(message, "chain", []) or []
                           if type(c).__name__ == "Plain")
            if text.strip():
                self.collected.append(text)
            self.last_send = time.time()
            await AstrMessageEvent.send(self, message)  # 只记"发过"，不真的发到 QQ

        async def send_streaming(self, generator, use_fallback: bool = False) -> None:
            async for chain in generator:
                await self.send(chain)

    obj = AstrBotMessage()
    obj.type = MessageType.FRIEND_MESSAGE
    obj.self_id = str(self_uin)
    obj.session_id = str(uin)
    obj.message_id = "qzone-" + uuid.uuid4().hex[:16]
    obj.sender = MessageMember(user_id=str(uin), nickname=name)
    obj.message = [Plain(text)]
    obj.message_str = text
    obj.raw_message = {"post_type": "message", "message_type": "private", "message": [],
                       "user_id": int(uin), "self_id": int(self_uin), "qzone": True}
    obj.timestamp = int(time.time())
    ev = QzoneCommentEvent(text, obj, platform.meta(), str(uin), bot)
    ev.collected = []
    ev.last_send = 0.0
    ev.set_extra(QZ_KEY, extra)
    return ev


async def run(platform, event, timeout: float, settle: float = 6.0, sleep=None) -> tuple[str, list[str]]:
    """提交事件，等她回完。

    Returns:
        (状态, 收集到的几段)。状态：ok / err（模型出错，不发）/ timeout（没跑完，可能被别的插件拦了或她没回）。
    """
    import asyncio

    sleep = sleep or asyncio.sleep
    platform.commit_event(event)
    start = time.time()
    while time.time() - start < timeout:
        await sleep(1.0)
        done = event.get_extra(DONE_KEY)
        if not done:
            continue
        if done.get("err"):
            return "err", list(event.collected)
        # agent 结束后，回复按行一句句发（每句间隔 1~2.5 秒），安静一会儿才算发完
        if time.time() - max(float(done["t"]), event.last_send) >= settle:
            return "ok", list(event.collected)
    return "timeout", list(event.collected)
