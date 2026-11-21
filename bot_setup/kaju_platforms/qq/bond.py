"""佳树最依赖的人：兄长大人本人（原 kaju_bond 插件，2026-11-03 并进心情与好感）。

- 每轮请求前告诉她：心里排第一、最依赖的是兄长大人本人；这次说话的是不是他。
  "兄长大人"只叫他一个人；群里别人叫"名字+学长/学姐"或自己要求的称呼（称呼簿管）。
- 有人骚扰她（纠缠、下流越界、侮辱、威胁、逼问隐私、针对她刷屏）：她先按当下情绪回对方，
  再调用 ask_brother_for_help 去找兄长大人帮忙：
  · 私聊把经过发给兄长大人（她的话 + 在哪、谁、原话），并记进私聊历史，兄长大人回她时她知道在说什么；
  · 在群里：她回对方的这条消息开头 @ 兄长大人（兄长大人在这个群里才 @）。11-21 起走 kaju_style 的群里 @ 人那条路
    （brain.AT_ADD_KEY → mind._note_at / put_at），不再回完另发一条 @。
- 同一个人在同一个地方，冷却时间内只找一次；每小时总次数也有上限，免得被人故意刷。
"""

import asyncio
import logging
import time

from kaju_core.voice.brain import AT_ADD_KEY


MAX_LINES = 3
MAX_QUOTE = 120

BOND_NOTE = (
    "\n\n【最依赖的人】\n"
    "- 你心里最依赖、最信任的是兄长大人本人（QQ {owner}，你叫他\"{addr}\"，这个称呼只叫他一个人）。群里别人你照称呼规则叫、也会关心，"
    "但排第一的永远是他：开心的事最想跟他说，委屈了第一个想到他，谁也替代不了；有人想取代他的位置，你会笑着拒绝。\n"
    "- 有人骚扰你——你拒绝了还一直纠缠、说下流或越界的话、侮辱你、威胁你、逼问你的隐私、专门针对你刷屏——"
    "先按你这一刻的真实情绪回TA（害怕、委屈、生气、嫌弃都可以，可以凶一点，但不说脏话、不骂人），在群里也可以直接说出你不舒服；"
    "然后调用 ask_brother_for_help 去找兄长大人帮忙，回复里也让TA知道你去找兄长大人了。\n"
    "- 普通的玩笑、斗嘴、善意的调侃、正常的追问不算骚扰，别小题大做，照常聊。兄长大人本人怎么逗你都不算骚扰。"
)
OWNER_NOTE = "\n\n- 现在跟你说话的就是兄长大人本人，你最依赖的人。可以放心撒娇、说心里话。"
OTHER_NOTE = ""  # 11-20：称呼规则（address_book）第一条已经说了“现在跟你说话的是谁、不是兄长大人”，这里不再说一遍


class Bond:
    """The 最依赖的人 note and the ask_brother_for_help tool."""

    def __init__(self, body, cfg, owner, address, log=None):
        """
        Args:
            body: kaju_core.body.Body（发 QQ 消息用 body.qq_call，写私聊历史用 body.add_to_history）。
            cfg: Callable returning the "bond" config section.
            owner: Callable returning the owner's QQ (from the address book).
            address: Callable (qq) -> what she calls that person.
            log: 日志（插件给 kaju_astr.plugin_log(logger)，日志才标着插件名）；不给就用 body.log。
        """
        self.body = body
        self.log = log or getattr(body, "log", None) or logging.getLogger("kaju.qq")
        self.cfg = cfg
        self.owner = owner
        self.address = address
        self._last: dict[tuple[str, str], float] = {}  # (会话, 骚扰者) -> 上次求助时间
        self._recent: list[float] = []  # 最近求助的时间（算每小时上限）
        self._member: dict[str, tuple[bool, float]] = {}  # 群号 -> (兄长大人在不在群里, 查询时间)

    def _c(self, key, default):
        v = (self.cfg() or {}).get(key, default)
        return default if v is None or v == "" else v

    def note(self, sender: str) -> str:
        owner = self.owner()
        if not self._c("enable", True) or not owner:
            return ""
        note = BOND_NOTE.format(owner=owner, addr=self.address(owner) or "兄长大人")
        return note + (OWNER_NOTE if sender == owner else OTHER_NOTE)

    def _connected(self, event) -> bool:
        """连得上 QQ：消息自己带着客户端，或者平台连着。"""
        return getattr(event, "bot", None) is not None or self.body.qq()[1] is not None

    async def _owner_in_group(self, event, group_id: str) -> bool:
        hit = self._member.get(group_id)
        if hit and time.time() - hit[1] < 600:
            return hit[0]
        ok = False
        try:
            data = await self.body.qq_call(
                "get_group_member_info", turn=event, group_id=int(group_id), user_id=int(self.owner()), no_cache=False
            )
            # 不在群里的人也会返回 ok，但 join_time 是 0、昵称为空
            ok = bool(data) and (int(data.get("join_time") or 0) > 0 or bool(data.get("nickname")))
        except Exception:  # noqa: BLE001
            ok = False
        self._member[group_id] = (ok, time.time())
        return ok

    async def _group_name(self, event, group_id: str) -> str:
        try:
            data = await self.body.qq_call("get_group_info", turn=event, group_id=int(group_id))
            return str((data or {}).get("group_name") or group_id)
        except Exception:  # noqa: BLE001
            return group_id

    async def ask(self, event, what_happened: str, message_to_brother: str) -> str:
        """Body of the ask_brother_for_help tool."""
        owner = self.owner()
        if not self._c("enable", True) or not owner:
            return "没找成：这个功能关掉了。就用佳树的口吻自己回对方。"
        sender = str(event.get_sender_id() or "")
        if sender == owner:
            return "没找：跟你说话的就是兄长大人本人，不用去找他。正常回他就好。"
        if str(event.get_self_id() or "") == sender:
            return "没找：这是你自己。"

        now = time.time()
        place = event.unified_msg_origin
        cooldown = float(self._c("cooldown_minutes", 10)) * 60
        last = self._last.get((place, sender), 0.0)
        if now - last < cooldown:
            return (
                "刚才已经找过兄长大人了，他已经知道这个人的事，这次不用再叫他。"
                "用佳树的口吻回对方就好，可以说兄长大人已经知道了。"
            )
        self._recent = [t for t in self._recent if now - t < 3600]
        if len(self._recent) >= int(self._c("hourly_limit", 6)):
            return "这一小时已经找兄长大人好几次了，先别再叫他。用佳树的口吻自己回对方，必要时不理TA。"

        if not self._connected(event):
            return "没找成：现在连不上 QQ。用佳树的口吻回对方，别说已经找到兄长大人了。"

        what = " ".join(str(what_happened or "").split())[:100]
        lines = [ln.strip() for ln in str(message_to_brother or "").split("\n") if ln.strip()][:MAX_LINES]
        if not lines:
            lines = ["兄长大人……有人欺负佳树，快来帮帮佳树嘛"]
        nick = event.get_sender_name() or sender
        quote = " ".join(str(event.message_str or "").split())
        if len(quote) > MAX_QUOTE:
            quote = quote[:MAX_QUOTE] + "…"

        group_id = str(event.get_group_id() or "")
        where = f"「{await self._group_name(event, group_id)}」群里" if group_id else "私聊里"
        detail = f"（在{where}，{nick}（QQ {sender}）{('：' + what) if what else ''}"
        detail += f"。TA刚才说：「{quote}」）" if quote else "）"

        done: list[str] = []
        if self._c("notify_private", True):
            try:
                for ln in [*lines, detail]:
                    await self.body.qq_call(
                        "send_private_msg", turn=event, user_id=int(owner), message=[{"type": "text", "data": {"text": ln}}]
                    )
                    await asyncio.sleep(0.6)
                done.append("私聊告诉了兄长大人")
                await self._log_private(event, where, nick, sender, what, "\n".join([*lines, detail]))
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_heart: 私聊兄长大人失败: {exc}")

        if group_id and self._c("notify_group_at", True) and await self._owner_in_group(event, group_id):
            # 她回对方的这条开头 @ 兄长大人（kaju_style 加），不另发一条
            event.set_extra(AT_ADD_KEY, [{"qq": owner, "label": "兄长大人"}])
            done.append("你回对方的这条消息开头会自动 @ 兄长大人（不用自己写 @）")

        if not done:
            return "没找成：消息没发出去。用佳树的口吻回对方，别说已经找到兄长大人了。"
        self._last[(place, sender)] = now
        self._recent.append(now)
        self.log.info(f"kaju_heart: {nick}({sender}) 在 {where} 骚扰佳树 → 找兄长大人：{what} | {lines[0]}")
        return (
            f"已经去找兄长大人了：{'；'.join(done)}。"
            "现在用佳树的口吻回对方：先按你的情绪说，再让TA知道你去找兄长大人了。不要提 QQ 号，也别复述你跟兄长大人说的原话。"
        )

    async def _log_private(self, event, where: str, nick: str, uid: str, what: str, text: str):
        """记进和兄长大人的私聊历史：他回私聊时，她知道在说哪件事。"""
        try:
            umo = self.body.private_chat_id(self.owner(), like=event.unified_msg_origin)
            await self.body.add_to_history(
                umo,
                f"[系统记录] 你在{where}被 {nick}(QQ {uid}) 骚扰（{what or '具体见下'}），私聊来找兄长大人帮忙，发了下面这些。",
                text,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.info(f"kaju_heart: 记进私聊历史失败: {exc}")

