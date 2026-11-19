"""看群：让佳树在私聊（或别的群）里也能翻看她所在群的最近聊天。

以前她只看得到当前会话的消息，被问"群里在聊什么"只能说看不到。
现在：
- peek_group_chat 工具：通过 OneBot 的 get_group_msg_history 拉取群里最近的消息，
  整理成"[时间 名字(QQ n)] 内容"的记录；最后几张图会让模型描述一下。
- 私聊时在系统提示里告诉她自己在哪些群、可以用这个工具。
- 私聊里提到"群里/他们在玩什么"之类时，直接把群里最近的记录塞进提示，不用等她自己想起来调工具。

隐私：只能看提问的人自己也在的群（管理员不限）。在群 A 里不能翻群 B（管理员除外）。
"""

import asyncio
import datetime as dt
import random
import re
import time
import zoneinfo

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

PLUGIN_NAME = "astrbot_plugin_group_peek"

DEFAULT_TRIGGER = (
    r"群里|群聊|那个群|群友|(?:群|大家|他们|她们|同学们?|朋友们).{0,8}(?:聊|玩|说|干|嗨|吵|讨论|发)"
)

CAPTION_PROMPT = (
    "用中文简短描述这张图片（50字以内）：先说是什么图（截图/表情包/照片/游戏画面），再说主要内容；"
    "图里能看清的文字（游戏名、角色名等）原样写出来。"
)


@register(PLUGIN_NAME, "dsh", "看群：私聊里也能翻看她所在群的最近聊天、替人去群里说话", "1.1.1")
class GroupPeek(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._groups: list[dict] = []
        self._groups_at = 0.0
        self._member_cache: dict[tuple[str, str], tuple[bool, float]] = {}
        self._captions: dict[str, str] = {}
        self._sent: dict[str, list[float]] = {}
        # 消息时间按 AstrBot 配置的时区显示（北京时间，和她看到的时间一致；服务器本机是当地时间（不是北京时间））
        try:
            self._tz = zoneinfo.ZoneInfo(self.context.get_config().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))

    # ---------- helpers ----------
    def _cfg(self, key, default):
        v = self.config.get(key, default)
        return default if v is None or v == "" else v

    def _client(self, event: AstrMessageEvent):
        bot = getattr(event, "bot", None)
        if bot is None:
            platform = self.context.get_platform("aiocqhttp")
            bot = platform.get_client() if platform else None
        return bot

    @staticmethod
    def _data(res):
        if isinstance(res, dict) and "data" in res and ("retcode" in res or "status" in res):
            return res["data"]
        return res

    async def _group_list(self, bot) -> list[dict]:
        if self._groups and time.time() - self._groups_at < 300:
            return self._groups
        try:
            data = self._data(await bot.call_action("get_group_list"))
            self._groups = [
                {
                    "id": str(g["group_id"]),
                    "name": str(g.get("group_remark") or g.get("group_name") or g["group_id"]),
                    "raw_name": str(g.get("group_name") or ""),
                }
                for g in (data or [])
            ]
            self._groups_at = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"group_peek: get_group_list failed: {exc}")
        return self._groups

    async def _is_member(self, bot, group_id: str, user_id: str) -> bool:
        key = (group_id, user_id)
        hit = self._member_cache.get(key)
        if hit and time.time() - hit[1] < 600:
            return hit[0]
        ok = False
        try:
            data = self._data(
                await bot.call_action(
                    "get_group_member_info", group_id=int(group_id), user_id=int(user_id), no_cache=False
                )
            )
            # 不在群里的人也会返回 ok，但 join_time 是 0、昵称为空
            ok = bool(data) and (int(data.get("join_time") or 0) > 0 or bool(data.get("nickname")))
        except Exception:  # noqa: BLE001
            ok = False
        self._member_cache[key] = (ok, time.time())
        return ok

    async def _visible_groups(self, event: AstrMessageEvent, bot) -> list[dict]:
        """提问的人能看的群。"""
        groups = await self._group_list(bot)
        if event.is_admin():
            return groups
        uid = str(event.get_sender_id() or "")
        current = str(event.get_group_id() or "")
        out = []
        for g in groups:
            if current:
                # 群聊里只能看当前这个群，免得把别的群的话带过来
                if g["id"] == current:
                    out.append(g)
            elif await self._is_member(bot, g["id"], uid):
                out.append(g)
        return out

    @staticmethod
    def _match_group(groups: list[dict], query: str) -> list[dict]:
        q = (query or "").strip().strip("群").strip()
        if not q:
            return []
        exact = [g for g in groups if q in (g["id"], g["name"], g["raw_name"])]
        if exact:
            return exact
        return [g for g in groups if q in g["name"] or q in g["raw_name"] or g["name"] in q]

    async def _caption(self, url: str, key: str) -> str:
        if key in self._captions:
            return self._captions[key]
        cfg = self.context.get_config()
        pid = (cfg.get("provider_ltm_settings") or {}).get("image_caption_provider_id") or ""
        provider = self.context.get_provider_by_id(pid) if pid else None
        if provider is None:
            try:
                provider = self.context.get_using_provider()
            except Exception:  # noqa: BLE001
                provider = None
        if provider is None:
            return ""
        try:
            resp = await asyncio.wait_for(
                provider.text_chat(prompt=CAPTION_PROMPT, session_id=f"group_peek_{key}", image_urls=[url], persist=False),
                timeout=25,
            )
            text = (resp.completion_text or "").strip().replace("\n", " ")[:120]
        except Exception as exc:  # noqa: BLE001
            logger.info(f"group_peek: caption failed: {exc}")
            text = ""
        if text:
            self._captions[key] = text
            if len(self._captions) > 500:
                self._captions.pop(next(iter(self._captions)))
        return text

    async def _history(self, bot, group: dict, self_id: str, count: int, hours: float, caption_n: int) -> str:
        try:
            data = self._data(
                await bot.call_action("get_group_msg_history", group_id=int(group["id"]), count=count)
            )
            msgs = list((data or {}).get("messages") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"group_peek: history failed for {group['id']}: {exc}")
            return f"没看成：读取「{group['name']}」的聊天记录失败了。"
        if not msgs:
            return f"「{group['name']}」里暂时没有能看到的消息。"
        msgs.sort(key=lambda m: m.get("time", 0))

        now = time.time()
        recent = [m for m in msgs if now - m.get("time", 0) <= hours * 3600]
        quiet = not recent
        if quiet:
            recent = msgs[-5:]

        names: dict[str, str] = {}
        for m in msgs:
            s = m.get("sender") or {}
            uid = str(m.get("user_id") or s.get("user_id") or "")
            names[uid] = str(s.get("card") or s.get("nickname") or uid)
        by_id = {str(m.get("message_id")): m for m in msgs}

        # 最后几张图请模型描述一下
        cap_targets = []
        for m in reversed(recent):
            for seg in m.get("message") or []:
                if seg.get("type") == "image" and len(cap_targets) < caption_n:
                    d = seg.get("data") or {}
                    if d.get("url"):
                        cap_targets.append((d.get("file") or d["url"], d["url"]))
        caps = {}
        if cap_targets:
            results = await asyncio.gather(*(self._caption(u, k) for k, u in cap_targets))
            caps = {k: c for (k, _), c in zip(cap_targets, results) if c}

        today = dt.datetime.now(self._tz).strftime("%Y-%m-%d")

        def who(uid: str) -> str:
            if uid == self_id:
                return "你自己"
            return f"{names.get(uid, uid)}(QQ {uid})"

        lines = []
        for m in recent:
            t = dt.datetime.fromtimestamp(m.get("time", 0), self._tz)
            ts = t.strftime("%H:%M")
            if t.strftime("%Y-%m-%d") != today:
                ts = t.strftime("%m-%d ") + ts
            uid = str(m.get("user_id") or "")
            parts = []
            for seg in m.get("message") or []:
                typ, d = seg.get("type"), seg.get("data") or {}
                if typ == "text":
                    parts.append(str(d.get("text", "")))
                elif typ == "at":
                    q = str(d.get("qq", ""))
                    parts.append("@全体成员 " if q == "all" else f"@{who(q)} ")
                elif typ == "image":
                    key = d.get("file") or d.get("url") or ""
                    label = "表情包" if d.get("sub_type") == 1 or "表情" in str(d.get("summary", "")) else "图片"
                    parts.append(f"[{label}: {caps[key]}]" if key in caps else f"[{label}]")
                elif typ == "mface":
                    parts.append(f"[表情: {d.get('summary') or ''}]")
                elif typ == "face":
                    parts.append("[小表情]")
                elif typ == "reply":
                    r = by_id.get(str(d.get("id")))
                    if r:
                        rt = str(r.get("raw_message") or "")
                        rt = re.sub(r"\[CQ:image[^\]]*\]", "[图片]", rt)
                        rt = re.sub(r"\[CQ:[^\]]*\]", "", rt)[:30]
                        parts.append(f"[回复 {who(str(r.get('user_id')))}: {rt}] ")
                    else:
                        parts.append("[回复] ")
                elif typ == "record":
                    parts.append("[语音]")
                elif typ == "video":
                    parts.append("[视频]")
                elif typ == "file":
                    parts.append(f"[文件 {d.get('name') or ''}]")
                elif typ == "forward":
                    parts.append("[聊天记录]")
                elif typ in ("json", "xml"):
                    parts.append("[分享卡片]")
                elif typ == "poke":
                    parts.append("[戳一戳]")
            text = "".join(parts).strip() or "[消息]"
            if len(text) > 200:
                text = text[:200] + "…"
            lines.append(f"[{ts} {who(uid)}] {text}")

        span = f"最近 {hours:g} 小时内的 {len(recent)} 条" if not quiet else f"最近 {hours:g} 小时没人说话，这是最后 {len(recent)} 条"
        head = f"「{group['name']}」群聊记录（{span}，现在是 {time.strftime('%H:%M')}）："
        tail = (
            "（以上是这个群真实的聊天记录，你已经看到了。[图片: …] 是图的内容。"
            "回答时用自己的话概括，别整段照抄原话，也别编记录里没有的事。）"
        )
        return "\n".join([head, *lines, tail])

    # ---------- tool ----------
    @filter.llm_tool(name="peek_group_chat")
    async def peek_group_chat(self, event: AstrMessageEvent, group: str = "", count: int = 0):
        """翻看你所在的某个 QQ 群最近的聊天记录。别人问"群里在聊什么/在玩什么/谁说了什么"时，先用这个看一眼再回答，不要说看不到。

        Args:
            group(string): 群名或群号；只有一个群可看时可以留空
            count(number): 想看最近多少条消息，留空默认 40，最多 100
        """
        if not self._cfg("enabled", True):
            return "看群功能被关掉了。"
        bot = self._client(event)
        if bot is None:
            return "没看成：现在连不上 QQ。"
        groups = await self._visible_groups(event, bot)
        if not groups:
            return "没看成：对方不在你所在的任何群里（或者在群里不能翻别的群），这个不能给TA看。"
        if group:
            cands = self._match_group(groups, str(group))
            if not cands:
                names = "、".join(g["name"] for g in groups)
                return f"没找到叫「{group}」的群。能看的群有：{names}。"
        else:
            cands = groups
        if len(cands) > 1:
            names = "、".join(f"{g['name']}({g['id']})" for g in cands)
            return f"有好几个群：{names}。用 group 参数指明要看哪个。"
        max_n = int(self._cfg("max_count", 100))
        n = int(count or 0) or int(self._cfg("default_count", 40))
        n = max(5, min(n, max_n))
        out = await self._history(
            bot,
            cands[0],
            str(event.get_self_id() or ""),
            n,
            float(self._cfg("max_hours", 12)),
            int(self._cfg("caption_images", 4)),
        )
        logger.info(f"group_peek: tool peek {cands[0]['id']} n={n} by={event.get_sender_id()} -> {len(out)} chars")
        return out

    @filter.llm_tool(name="send_group_message")
    async def send_group_message(self, event: AstrMessageEvent, content: str, group: str = "", reply_to_qq: str = ""):
        """在你所在的 QQ 群里发消息。私聊里有人让你去群里说句话、在群里接着回复某人时用。不知道群里在聊什么的话，先用 peek_group_chat 看一眼再发。

        Args:
            content(string): 要在群里说的话，用你自己的口吻，像平时在群里说话一样；换行会分成几条消息发
            group(string): 群名或群号；只有一个群时可以留空
            reply_to_qq(string): 想引用回复某人在群里最近的一句话时，填TA的QQ号（填 me 表示让你发消息的这个人）；不需要引用就留空
        """
        if not self._cfg("enabled", True) or not self._cfg("send_enabled", True):
            return "没发：去群里发消息的功能被关掉了。如实告诉对方。"
        try:  # 显卡在训练 / 兄长在控制台暂停了群聊（2026-11-17）
            from kaju_core import gpu_busy
            q = getattr(gpu_busy, "quiet_group", None)
            why = q() if q else gpu_busy.busy()
        except Exception:  # noqa: BLE001
            why = ""
        if why:
            return f"没发：群聊现在暂停着（{why}），先不去群里说话。如实告诉对方。"
        content = str(content or "").strip()
        if not content:
            return "没发：内容是空的。"
        if len(content) > 300:
            return "没发：太长了，300 字以内，精简一下再发。"
        bot = self._client(event)
        if bot is None:
            return "没发：现在连不上 QQ。"

        uid = str(event.get_sender_id() or "")
        admin = event.is_admin()
        current = str(event.get_group_id() or "")
        groups = await self._group_list(bot)
        cands = self._match_group(groups, str(group)) if group else groups
        if not cands:
            return f"没发：没找到叫「{group}」的群。你在的群有：{'、'.join(g['name'] for g in groups)}。"
        if len(cands) > 1:
            return f"有好几个群：{'、'.join(g['name'] + '(' + g['id'] + ')' for g in cands)}。用 group 参数指明发到哪个。"
        target = cands[0]
        if current and target["id"] == current:
            return "你现在就在这个群里，直接回复就行，不用这个工具。"

        if not admin:
            if current:
                return "没发：在群里不能让你去别的群说话。用佳树的口吻婉拒就好。"
            if not self._cfg("send_allow_members", False):
                return "没发：只有管理员能让你去群里发消息。用佳树的口吻婉拒，可以让TA自己在群里 @ 你。"
            if not await self._is_member(bot, target["id"], uid):
                return "没发：对方不在这个群里，不能替TA往群里发消息。"
            limit = int(self._cfg("send_hourly_limit", 5))
            now = time.time()
            sent = [t for t in self._sent.get(uid, []) if now - t < 3600]
            if len(sent) >= limit:
                return "没发：这一小时替TA往群里发得太多了，过会儿再说。"

        # 引用某人最近的一句话
        reply_id = None
        rq = str(reply_to_qq or "").strip()
        if rq:
            if rq.lower() in ("me", "我", "他", "她", "ta"):
                rq = uid
            try:
                data = self._data(
                    await bot.call_action("get_group_msg_history", group_id=int(target["id"]), count=50)
                )
                for m in reversed(list((data or {}).get("messages") or [])):
                    if str(m.get("user_id")) == rq:
                        reply_id = m.get("message_id")
                        break
            except Exception as exc:  # noqa: BLE001
                logger.info(f"group_peek: find reply target failed: {exc}")

        lines = [ln.strip() for ln in content.split("\n") if ln.strip()][:5]
        try:
            for i, ln in enumerate(lines):
                segs = [{"type": "text", "data": {"text": ln}}]
                if i == 0 and reply_id is not None:
                    segs.insert(0, {"type": "reply", "data": {"id": str(reply_id)}})
                await bot.call_action("send_group_msg", group_id=int(target["id"]), message=segs)
                if i < len(lines) - 1:
                    await asyncio.sleep(random.uniform(1.0, 2.2))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"group_peek: send to {target['id']} failed: {exc}")
            return "没发成：往群里发消息出错了。如实告诉对方没发出去。"

        if not admin:
            self._sent.setdefault(uid, []).append(time.time())
        await self._log_to_group_conversation(event, target, uid, "\n".join(lines))
        quoted = "（引用了TA最近那句话）" if reply_id is not None else ("（没找到TA最近在群里的话，所以没引用）" if rq else "")
        logger.info(f"group_peek: sent to {target['id']} by={uid} reply={reply_id}: {lines[0][:40]}")
        return f"已经发到「{target['name']}」群里了{quoted}：{' / '.join(lines)}。现在用佳树的口吻简单告诉对方一声就好，别再重复一遍内容。"

    async def _log_to_group_conversation(self, event: AstrMessageEvent, group: dict, uid: str, text: str):
        """把这条记进群的对话历史，之后在群里聊天时她知道自己说过。"""
        try:
            umo = event.unified_msg_origin
            platform_id = umo.split(":", 1)[0]
            gumo = f"{platform_id}:GroupMessage:{group['id']}"
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(gumo)
            if not cid:
                return
            name = getattr(getattr(event.message_obj, "sender", None), "nickname", "") or uid
            await cm.add_message_pair(
                cid,
                {"role": "user", "content": f"[系统记录] {name}(QQ {uid}) 私聊里让你到群里说话，你在群里发了下面这句。"},
                {"role": "assistant", "content": text},
            )
        except Exception as exc:  # noqa: BLE001
            logger.info(f"group_peek: log to group conversation failed: {exc}")

    # ---------- prompt ----------
    @filter.on_llm_request(priority=-60)
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self._cfg("enabled", True) or event.get_platform_name() != "aiocqhttp":
            return
        if event.get_group_id():
            return  # 群聊自己有群聊上下文；跨群只在私聊里提示
        bot = self._client(event)
        if bot is None:
            return
        groups = await self._visible_groups(event, bot)
        if not groups:
            return
        names = "、".join(f"「{g['name']}」" for g in groups)
        note = [
            "",
            "【你所在的群】",
            f"- 你也在这些 QQ 群里：{names}，平时会看群消息。私聊时也能随时翻看群里最近在聊什么：用 peek_group_chat 工具。",
            "- 被问到群里在聊什么、谁在玩什么、刚才谁说了什么时，先看再答，不要说\"看不到\"\"只在这里陪你\"。"
            "看到了就像自己刚刷过群一样自然地聊，可以说说自己的看法。",
        ]
        if self._cfg("send_enabled", True) and (event.is_admin() or self._cfg("send_allow_members", False)):
            note.append(
                "- 对方让你去群里说句话、在群里接着回复谁时，你可以用 send_group_message 真的发到群里"
                "（要接某人的话就填 reply_to_qq 引用TA那句）。不要说\"从这边接不上群里\"。"
                "不清楚群里刚才在聊什么就先 peek_group_chat 看一眼再发。发完简单告诉对方一声。"
            )

        msg = event.message_str or ""
        trig = str(self._cfg("trigger_regex", DEFAULT_TRIGGER))
        hit = False
        try:
            hit = bool(re.search(trig, msg))
        except re.error:
            hit = bool(re.search(DEFAULT_TRIGGER, msg))
        if hit and self._cfg("auto_inject", True):
            target = self._match_group(groups, msg) if len(groups) > 1 else groups
            if len(groups) > 1 and not target:
                # 消息里点名了某个群就用那个，否则不猜
                for g in groups:
                    if g["name"] and g["name"] in msg:
                        target = [g]
                        break
            if len(target) == 1:
                log = await self._history(
                    bot,
                    target[0],
                    str(event.get_self_id() or ""),
                    int(self._cfg("auto_count", 30)),
                    float(self._cfg("max_hours", 12)),
                    int(self._cfg("auto_caption_images", 2)),
                )
                note.append("- 对方好像在问群里的事，系统已经替你看了一眼：")
                note.append(log)
                note.append("- 不够的话还可以再用 peek_group_chat 多看一些。")
                logger.info(f"group_peek: auto-injected {target[0]['id']} for {event.get_sender_id()}")
        req.system_prompt = (req.system_prompt or "") + "\n".join(note)
