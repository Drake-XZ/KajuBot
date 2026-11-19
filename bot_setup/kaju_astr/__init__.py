"""kaju_core 在 AstrBot 上的那一层：用 AstrBot 的模型、设置、QQ 接口实现 kaju_core.body.Body。

各插件这样用（log 要在插件自己的模块里取，AstrBot 才知道日志是哪个插件的）：
    from astrbot.api import logger
    from kaju_astr import AstrBody, plugin_log
    body = AstrBody(self.context, plugin_log(logger))

和 kaju_core 一起部署（botctl deploy kaju_core）；改了要重启 AstrBot。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from kaju_core import parts
from kaju_core.body import Body


def plugin_log(logger):
    """把插件拿到的 astrbot.api.logger 绑成固定的几个方法（必须在插件模块里调用）。"""
    return SimpleNamespace(info=logger.info, warning=logger.warning, debug=logger.debug, error=logger.error)


def _in_any_slot(pid: str) -> bool:
    try:
        from kaju_core import slots
        return any(pid in ids for ids in slots.table().values())
    except Exception:  # noqa: BLE001
        return False


class AstrBody(Body):
    def __init__(self, context, log=None):
        super().__init__(log)
        self.context = context

    async def think(self, prompt: str, system: str = "", who: str = "", model: str = "",
                    timeout: float | None = None) -> str:
        ctx = self.context
        if model:
            prov = ctx.get_provider_by_id(model)
        elif who:
            prov = await ctx.get_using_provider_async(who)
        else:
            prov = ctx.get_using_provider()
        if prov is None:
            raise RuntimeError("没有可用的模型")
        pid = (getattr(prov, "provider_config", None) or {}).get("id") or prov.meta().id
        if not pid:
            raise RuntimeError("没有可用的模型")
        return await self.generate(pid, prompt, system, timeout)

    def _fallbacks(self, pid: str) -> list[str]:
        """pid 是主模型时，接上 AstrBot 配置里主模型的后备（agent_runner.config.model.fallback_provider_ids）。
        2026-11-13 主模型换成 Gemini 中转后：中转常 502/503/卡住，心情、记忆、核对这些单独调模型的也要能换后备。
        2026-11-18 每项工作一格（kaju_core/slots.py）：pid 是某一格里的，先接那一格里排在它后面的，最后再接主模型和它的后备。"""
        try:
            m = self.context.get_config()["agent_runner"]["config"]["model"]
            main = m.get("provider_id")
            main_chain = [x for x in [main] + list(m.get("fallback_provider_ids") or []) if x]
        except Exception:  # noqa: BLE001
            main, main_chain = "", []
        if pid and pid == main:
            return [x for x in main_chain if x != pid]
        try:
            from kaju_core import slots
            rest = slots.slot_rest(pid)
        except Exception:  # noqa: BLE001
            rest = []
        if not rest and not (pid and _in_any_slot(pid)):
            return []
        out = []
        for x in rest + main_chain:
            if x and x != pid and x not in out and self.context.get_provider_by_id(x) is not None:
                out.append(x)
        return out

    async def slot_model(self, slot: str, model: str = "", who: str = "") -> str:
        if not model:
            try:
                from kaju_core import slots
                for pid in slots.providers(slot):
                    if self.context.get_provider_by_id(pid) is not None:
                        return pid
            except Exception:  # noqa: BLE001
                pass
        return await self.model_id(model, who)

    @staticmethod
    def _pid(prov) -> str:
        return (getattr(prov, "provider_config", None) or {}).get("id") or prov.meta().id

    async def model_id(self, model: str = "", who: str = "") -> str:
        prov = self.context.get_provider_by_id(model) if model else None
        if prov is None:
            prov = await (self.context.get_using_provider_async(who) if who else self.context.get_using_provider_async())
        return self._pid(prov) if prov is not None else ""

    async def generate(self, model_id: str, prompt: str, system: str = "", timeout: float | None = None) -> str:
        """调一个模型；它是主模型就按后备一个个试（第一个只给一部分时间，留给后备）。"""
        chain = [model_id] + self._fallbacks(model_id)
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout if timeout else None
        last: Exception | None = None
        for i, pid in enumerate(chain):
            left = (end - loop.time()) if end else None
            if left is not None and left <= 1:
                break
            share = left
            if i + 1 < len(chain):  # 后面还有后备：这个最多给一部分时间（没给总时限时 45 秒）
                share = max(8.0, left * 0.4) if left is not None else 45.0
            try:
                call = self.context.llm_generate(chat_provider_id=pid, prompt=prompt, system_prompt=system)
                resp = await asyncio.wait_for(call, timeout=share) if share else await call
                if getattr(resp, "role", "") == "err" and i + 1 < len(chain):
                    raise RuntimeError(getattr(resp, "completion_text", "") or "模型报错")
                if i:
                    self.log.info(f"kaju: {chain[0]} 没答上来，换后备 {pid} 答了")
                return getattr(resp, "completion_text", "") or ""
            except Exception as e:  # noqa: BLE001
                last = e
                if i + 1 < len(chain):
                    self.log.warning(f"kaju: 模型 {pid} 没答上来，换下一个 {type(e).__name__}: {str(e)[:80]}")
        raise last or asyncio.TimeoutError()

    async def chat(self, messages: list[dict], temperature: float | None = None, extra_body: dict | None = None,
                   timeout: float | None = None) -> str | None:
        """llm_generate 会丢掉额外参数（关不了思考）→ 能拿到提供方自己的 OpenAI 客户端就直接用；拿不到退回 llm_generate。"""
        prov = await self.context.get_using_provider_async()
        if prov is None:
            return None
        client = getattr(prov, "client", None)
        if client is not None and hasattr(prov, "get_model"):
            kw = {"model": prov.get_model(), "messages": messages}
            if temperature is not None:
                kw["temperature"] = temperature
            if extra_body is not None:
                kw["extra_body"] = extra_body
            r = await asyncio.wait_for(client.chat.completions.create(**kw), timeout=timeout)
            return r.choices[0].message.content or ""
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return await self.generate(self._pid(prov), user, system, timeout)

    async def conversation_id(self, who: str) -> str:
        return await self.context.conversation_manager.get_curr_conversation_id(who)

    def qq(self):
        """(aiocqhttp 平台, 它的客户端)；没连上是 (None, None)。"""
        try:
            platform = self.context.get_platform("aiocqhttp")
            return platform, (platform.get_client() if platform else None)
        except Exception:  # noqa: BLE001
            return None, None

    def settings(self) -> dict:
        try:
            return self.context.get_config() or {}
        except Exception:  # noqa: BLE001
            return {}

    async def group_name(self, turn, gid: str) -> str:
        """先看消息里带的群名，没有再问 QQ（get_group_info）。"""
        name = ""
        try:
            grp = getattr(getattr(turn, "message_obj", None), "group", None)
            name = getattr(grp, "group_name", "") or ""
            if not name and hasattr(turn, "bot"):
                info = await turn.bot.call_action("get_group_info", group_id=int(gid))
                info = info.get("data", info) if isinstance(info, dict) else {}
                name = str(info.get("group_name", "") or "")
        except Exception:  # noqa: BLE001
            pass
        return name

    def stars(self) -> list:
        return list(self.context.get_all_stars() or [])

    def find(self, attr: str):
        """先在她自己的部分里找（kaju_core.parts），没有再翻 AstrBot 的插件表（称呼簿、memorix 这些外面的插件）。"""
        own = parts.find(attr)
        if own is not None:
            return own
        for meta in self.context.get_all_stars() or []:
            star = getattr(meta, "star_cls", None)
            if star is not None and hasattr(star, attr):
                return star
        return None

    async def send(self, where: str, text: str = "", image: str = "") -> bool:
        """往会话 where（unified_msg_origin）发一条：图（本机文件）在前、文字在后。"""
        from astrbot.api.event import MessageChain
        from astrbot.api.message_components import Image, Plain

        parts = ([Image.fromFileSystem(image)] if image else []) + ([Plain(text)] if text else [])
        if not parts:
            return False
        if ":GroupMessage:" in str(where):  # 显卡在训练 / 兄长在控制台暂停了群聊（2026-11-17；kaju_astr 改了要重启才生效）
            try:
                from kaju_core import gpu_busy
                if gpu_busy.quiet_group():
                    return False
            except Exception:  # noqa: BLE001
                pass
        return bool(await self.context.send_message(where, MessageChain(parts)))

    def private_chat_id(self, user_id: str, like: str = "") -> str:
        """QQ 上和 user_id 私聊的会话 id：平台名借 like（一段已知会话），没有就问 aiocqhttp 平台。"""
        pid = str(like or "").split(":", 1)[0]
        if not pid:
            try:
                pid = self.context.get_platform("aiocqhttp").meta().id
            except Exception:  # noqa: BLE001
                pid = "aiocqhttp"
        return f"{pid}:FriendMessage:{user_id}"

    async def qq_call(self, action: str, turn=None, **params):
        """调 OneBot 接口：消息自己带着 QQ 客户端（turn.bot）就用它的，不然用平台的；返回去掉 status/retcode 外壳的 data。"""
        bot = getattr(turn, "bot", None) if turn is not None else None
        if bot is None:
            _, bot = self.qq()
        if bot is None:
            raise RuntimeError("连不上 QQ")
        res = await bot.call_action(action, **params)
        if isinstance(res, dict) and "data" in res and ("retcode" in res or "status" in res):
            return res["data"]
        return res

    async def add_to_history(self, where: str, user: str, assistant: str) -> bool:
        """往会话 where 当前的对话里补一轮（AstrBot 的 conversation_manager）；这段聊天还没有对话返回 False。"""
        cm = self.context.conversation_manager
        cid = await cm.get_curr_conversation_id(where)
        if not cid:
            return False
        await cm.add_message_pair(cid, {"role": "user", "content": user}, {"role": "assistant", "content": assistant})
        return True
