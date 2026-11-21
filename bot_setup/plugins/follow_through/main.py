"""说到做到：佳树说要做的事，真的去做；做的过程出了问题要说；做完要汇报结果。

三层保障：
1. 每次请求 LLM 前，按这一轮实际拥有的工具，告诉她"你真的能做到哪些事"，并要求：
   - 说要做就在这一轮调用工具做完，不能只说"佳树去……""等下……"；
   - 属于以后的事（到点提醒）用 future_task 真的约好；
   - 只有工具返回成功才能说"发好啦/存好了"，失败要如实说明；
   - 做完简单汇报做了什么、结果怎样。
2. 回复后核对"嘴上说的"和"实际做的"：
   - 答应/声称做了某件事（搜索、发说说、存表情、改称呼、定时提醒、记住），但这一轮没调用对应工具
     → 后台用同样的人设和上下文，只给对应工具，把事情补做完，再在群里汇报结果或说明遇到的问题；
   - 工具其实失败了，她却说"好啦/成功了" → 后台让她更正，说明遇到了什么问题（能重试就重试一次）。
3. 补做的结果补进对话历史，下一轮她记得自己做过什么。
4. 没人让她做、她却说已经做了（目前只管存表情包：2026-10-31 测试里她收到表情包就说"佳树存下来了"，
   其实没存）：不替她补做（不该自作主张收图），而是在发出去之前把这句删掉，存进历史的那份也删掉。
   兄长让她存、表情包插件已经当场存好的那一轮不算（插件自己存，不经过 save_meme 工具）。
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.tool import ToolSet

PLUGIN_NAME = "astrbot_plugin_follow_through"
MEME_SAVER_RESULT = "meme_saver_result"  # 表情包插件当场处理了收藏时留下的标记（见 meme_saver）
RETRACT_KEY = "_ft_retract"  # 这一轮从回复里删掉了谎称的话：Action.key


@dataclass(frozen=True)
class Action:
    key: str
    desc: str  # 给模型看的"这件事是什么"
    tools: tuple[str, ...]  # 工具名前缀，调用其中任意一个就算真的做了
    promise: re.Pattern | None = None  # 答应要做
    claim: re.Pattern | None = None  # 声称已经做了
    user_ask: re.Pattern | None = None  # 只有对方提出要求时才核对（避免对随口一句"记住啦"也大动干戈）
    silent: bool = False  # 补做成功后不必再发消息（她已经说过了，比如"记住了"）
    retract_unasked: bool = False  # 没人要求、没做却说做了：删掉这句，而不是去补做


ACTIONS: tuple[Action, ...] = (
    Action(
        "search",
        "上网查资料、打开链接看",
        ("web_search", "deepseek_fetch", "tavily_", "exa_", "firecrawl_", "bocha"),
        promise=re.compile(
            r"(去|先|这就|马上|立刻|待会儿?|等会儿?|等下|回头|稍后|晚点)(再)?(帮.{0,6})?"
            r"(搜|查|找找|找一下|研究|学习?一下|了解|翻翻|打听)"
            r"|搜搜看|查查看|搜一下|查一下|搜一搜|查一查|上网看看"
            r"|(待会儿?|等会儿?|等下|回头|晚点|稍后|之后)(再)?.{0,6}(告诉|讲给|讲讲|汇报|说给)"
            # 11-19：“这就去看 Hoody 那个”——说去看链接 / 网站，这一轮却什么都没调
            r"|(这就|马上|立刻|现在就)(去)?(一起|帮.{0,6})?(看|点开|点进去|打开)"
            r"|(去|先)(看看|看一下|看一眼|点开|点进去|打开)"
        ),
        claim=re.compile(r"(查|搜)(到|过)(了|啦)"),
    ),
    Action(
        "qzone",
        "在QQ空间发说说",
        ("post_qzone",),
        promise=re.compile(r"(去|这就|马上|帮.{0,4}|给.{0,4}|待会儿?|等下|晚点)发.{0,4}(说说|空间|动态)"),
        claim=re.compile(r"(说说|空间|动态).{0,8}(发好|发了|发出去|发上去|写好)|发好(啦|了)"),
    ),
    Action(
        "meme",
        "把图存成表情包",
        ("save_meme",),
        promise=re.compile(r"(去|这就|马上|帮.{0,4})(存|收藏|保存).{0,4}(表情|图)"),
        # 说已经存了（"收下了"不算：那是表情包插件暂存图、问放哪个分类时的说法，也常是"心意收下了"）
        claim=re.compile(
            r"(表情|图|它|这张|这个|这只|那张|那个|那只).{0,8}(存好|存下|存起来|收藏好|收藏了|收藏起来了|保存好|保存了)"
            r"|(存|收藏|保存)(下来|起来|进去|好|下)(了|啦)"
            r"|已经(帮.{0,4})?(存|收藏|保存)(下|好|起来|进|到)"
            r"|(存|收|放|加)(进|到)(了)?(表情包|表情库|收藏夹?)(里)?(了|啦|哦|啰)"
            r"|收藏(啦|好啦)"
        ),
        user_ask=re.compile(r"存|收藏|保存|表情包|表情库|加进|放进|收进|收下"),
        retract_unasked=True,
    ),
    Action(
        "address",
        "记住/修改对某人的专属称呼",
        ("set_address", "clear_address"),
        claim=re.compile(r"以后(就|都)?(叫|称呼|喊)|改口(叫|啦|了)"),
        user_ask=re.compile(r"叫我|称呼|别叫|改叫|喊我"),
    ),
    Action(
        "remind",
        "到点提醒、以后再做的事（定时任务）",
        ("future_task",),
        promise=re.compile(
            r"(明天|明早|今晚|下午|早上|晚上|到时候?|[\d一二三四五六七八九十两]+\s*(点|分钟|小时)).{0,10}"
            r"(提醒|叫你|喊你|叫醒|通知|告诉你|跟你说)"
            r"|(待会儿?|等会儿?|等下|晚点|到点).{0,6}(提醒|叫醒|叫你起|喊你起)"
            r"|佳树(会|来)?提醒"
        ),
        claim=re.compile(r"(约好|定好|设好)(了|啦).{0,10}(提醒|闹钟)|(提醒|闹钟).{0,6}(设好|定好|约好)"),
    ),
    Action(
        "remember",
        "把重要的事存进长期记忆",
        ("ingest_text", "ingest_summary"),
        claim=re.compile(r"记(住|下|好|着)(了|啦)?"),
        user_ask=re.compile(r"记住|记一下|记下|别忘|记得|记着|帮我记"),
        silent=True,
    ),
    Action(
        "group_send",
        "去群里发消息/在群里接着回复某人",
        ("send_group_message",),
        promise=re.compile(r"(去|这就|马上|现在就|帮.{0,4}|替.{0,4}|待会儿?|等下)(到|在|去)?群里.{0,6}(说|回|发|讲|接)"),
        claim=re.compile(r"(在|往|到)?群里(回|发|说)(好|过)(了|啦)|(回|发)到群里(了|啦)|群里.{0,4}(回好|发好)(了|啦)"),
        # 只在对方让她去群里说话时核对，免得"兄长大人在群里说了…"之类被当成她答应了
        user_ask=re.compile(r"群里.{0,12}(回|说|发|接|讲)|去群|到群"),
    ),
)

# 这一轮能用的工具 → 给她看的能力说明
CAPABILITY_LABELS = {
    "web_search": "上网搜索资料",
    "deepseek_fetch": "打开网页看全文",
    "post_qzone": "在自己的QQ空间发说说",
    "qzone_activity": "看自己QQ空间说说最近谁点了赞、谁留了言",
    "save_meme": "把群里的图存成表情包",
    "search_memes": "找表情包发出来",
    "set_address": "记住对某人的专属称呼",
    "ingest_text": "把重要的事存进长期记忆",
    "search_memory": "回忆以前聊过的事",
    "future_task": "建定时任务（到点提醒、以后再做的事）",
    "peek_group_chat": "翻看你所在的群最近的聊天",
    "send_group_message": "去你所在的群里发消息、接着回复某人",
    "ask_brother_for_help": "被人骚扰、欺负时去找兄长大人本人帮忙（私聊告诉他，在群里回对方的那条开头会 @ 他）",
    "recall_shared_file": "翻出兄长大人以前分享给你的文件重读一遍",
    "browse_bilibili": "兄长大人允许时自己去刷一会儿B站（在后台看，看完的记在心里）",
    "recall_knowledge": "想一想自己以前学到、知道的东西（看过的、听人讲过的、上网查过的）",
    "reading_pace": "改自己读那本长书的节奏（读快点、一口气读完、先停一下、接着读、不读了）",
    "answer_dm_request": "兄长大人答复B站私信那边的事（同意或不同意关注某人、看某人多发的视频），去照办",
}

# 只看结果开头：搜索结果正文里出现"错误""无法"之类的词不算失败
FAIL_HINT = re.compile(
    r'"success"\s*:\s*false|^\s*error|^\s*\{?\s*"error"|^.{0,40}(失败|出错|异常|无法|超时|not found|traceback)',
    re.I | re.S,
)
SUCCESS_WORDS = re.compile(r"好(啦|了)|成功|搞定|完成|弄好|办好|发出去|存下|记(下|住|好)|设好|约好|改好|写好|查到")
ACK_FAILURE = re.compile(r"失败|没成功|没能|出错|出问题|不行|没发出去|没存上|做不到|没办法|发不出|存不了")

TURN_NOTE = (
    "【说到做到】你真的能做到的事只有这些（通过工具完成）：{caps}。\n"
    "- 说要做上面的事，就在这一轮先调用工具做完，再回复。千万不要只说\"佳树去……\"\"等下……\"\"回头……\"然后什么都不做——"
    "这条回复发出去这一轮就结束了，你没有\"等下\"。\n"
    "- 真正属于以后的事（到点提醒、明天叫TA），用定时任务真的约好：note 里写清楚到时要在这里对谁说什么"
    "（到点时用 send_message_to_user 发出来）；约好后告诉对方约在了什么时候。"
    "现在这一轮的回复直接写出来就会发出去，不要再用工具把同样的话发一遍。\n"
    "- 只有工具返回成功，才能说\"发好啦/存好了/记下了/改好了\"。工具报错或做不到，就如实告诉对方遇到了什么问题"
    "（用佳树的口吻，不提工具名），合适的话重试一次。\n"
    "- 做完后简单说一下你做了什么、结果怎样（比如查到了什么、发了什么内容、约在几点提醒）。\n"
    "- 上面以外的事你做不到（比如看不清的图、改头像、出门、打电话），就别答应，坦白说做不到；"
    "纯角色扮演的小动作（泡茶、摸头）不算答应。\n"
    "- 讲解查到的东西、汇报结果时可以放宽到 2~4 句、120 字以内，仍然不分点、不用 Markdown。"
)

FOLLOW_UP_PROMPT = (
    "（后台提示，不是群友说的话）你刚才回复了\"{reply}\"，但其中答应/声称要做的这些事还没真的做：{todo}。\n"
    "现在就用工具把它们做完。然后：\n"
    "- 做成了：用佳树的口吻在群里接着汇报你刚才做了什么、结果怎样（查到了什么就讲出来、发了什么、约在几点提醒）。"
    "不要重复刚才那句话。{silent_hint}\n"
    "- 出错或做不到：如实说明遇到了什么问题，以及对方可以怎么办，不要假装做成了。\n"
    "- 如果仔细看其实只是随口一说、并没有需要做的事，只输出 [SKIP]。\n"
    "2~4 句、120 字以内，不分点、不用 Markdown、不提工具名。"
)

CORRECTION_PROMPT = (
    "（后台提示，不是群友说的话）你刚才回复了\"{reply}\"，但实际上这件事没做成：{failures}。\n"
    "如果看起来是偶然出错，可以再试一次。然后用佳树的口吻跟对方更正：\n"
    "- 重试成功了：说清楚现在做好了、结果是什么；\n"
    "- 还是不行：坦白说没做成、遇到了什么问题（说人话，不要贴报错原文，不提工具名），对方可以怎么办。\n"
    "1~3 句、80 字以内，不分点、不用 Markdown。"
)


def plan_promises(plan) -> list[str]:
    """大脑指导里“答应：…”那几条（kaju_style 记在 event extra _ks_plan）。"""
    if not isinstance(plan, dict):
        return []
    return [str(x) for x in (plan.get("要表达的") or []) if str(x).startswith("答应")]


def _tool_matches(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(p) for p in prefixes)


_MEME_TAG = re.compile(r"&&[^&\n]{1,60}&&")


def _has_words(text: str) -> bool:
    return bool(re.search(r"\w", _MEME_TAG.sub("", text or "")))


_NEGATION = re.compile(r"没|不|别|无法|没法")


def claims(claim: re.Pattern, text: str) -> bool:
    """Whether `text` makes the claim (a match right after 没/不/别/没法 doesn't count)."""
    for m in claim.finditer(text or ""):
        if not _NEGATION.search(text[max(0, m.start() - 3):m.start() + 1]):
            return True
    return False


def retract_claims(text: str, claim: re.Pattern) -> str | None:
    """Remove the false claim from a reply.

    Drops whole lines that make the claim; if that would leave no words, drops only the clauses instead.

    Returns:
        The cleaned reply, the same text when nothing matched, or None when nothing would be left.
    """
    if not claims(claim, text or ""):
        return text
    kept = [line for line in text.split("\n") if not claims(claim, line)]
    if not _has_words("\n".join(kept)):
        kept = []
        for line in text.split("\n"):
            parts = [p for p in re.split(r"[，,；;]", line) if not claims(claim, p)]
            kept.append("，".join(p.strip() for p in parts if p.strip()))
        if not _has_words("\n".join(kept)):
            return None
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip("\n")
    return out


def _result_text(tool_result) -> str:
    if tool_result is None:
        return ""
    parts = []
    for c in getattr(tool_result, "content", None) or []:
        t = getattr(c, "text", None)
        if t:
            parts.append(str(t))
    if not parts:
        parts.append(str(tool_result))
    return "\n".join(parts)


@register(PLUGIN_NAME, "dsh", "说到做到：答应的事真的去做，出问题会说，做完会汇报", "2.3.1")
class FollowThrough(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._last_follow_up: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---------- hooks ----------
    @filter.on_llm_request(priority=-100)  # 最后执行，拿到其它插件注入后的完整人设
    async def remember_request(self, event: AstrMessageEvent, req: ProviderRequest):
        names = req.func_tool.names() if req.func_tool else []
        if self.config.get("inject_prompt", True) and names:
            caps = []
            for prefix, label in CAPABILITY_LABELS.items():
                if any(n.startswith(prefix) for n in names) and label not in caps:
                    caps.append(label)
            if caps:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + TURN_NOTE.format(caps="、".join(caps))
        event.set_extra(
            "_ft_req",
            {
                "system_prompt": req.system_prompt,
                "contexts": list(req.contexts or []),
                "prompt": req.prompt or "",
                "user_text": event.message_str or "",
                "func_tool": req.func_tool,
            },
        )
        event.set_extra("_ft_calls", [])

    @filter.on_llm_tool_respond()
    async def record_tool(self, event: AstrMessageEvent, tool, tool_args, tool_result):
        calls = event.get_extra("_ft_calls") or []
        text = _result_text(tool_result)
        name = getattr(tool, "name", "")
        if _tool_matches(name, ACTIONS[0].tools + ("search_",)):
            # 搜索结果是网页摘要，正文里什么词都可能有；只有明确的 Error 才算失败
            ok = not text.lstrip().lower().startswith("error")
        else:
            ok = not FAIL_HINT.search(text[:600])
        calls.append(
            {
                "name": name,
                "ok": ok,
                "result": text[:300],
            }
        )
        event.set_extra("_ft_calls", calls)

    @filter.on_llm_response()
    async def check(self, event: AstrMessageEvent, resp: LLMResponse):
        snap = event.get_extra("_ft_req")
        if not snap:
            return
        reply = (getattr(resp, "completion_text", "") or "").strip()
        if not reply:
            return
        calls = event.get_extra("_ft_calls") or []
        available = snap["func_tool"].names() if snap.get("func_tool") else []
        handled_by_meme_saver = event.get_extra(MEME_SAVER_RESULT) is not None

        # 0) 没人让她做、她也没做，却说做了：删掉这句（不替她补做）
        if self.config.get("retract_false_claims", True):
            for act in ACTIONS:
                if not act.retract_unasked or not act.claim:
                    continue
                if act.key == "meme" and handled_by_meme_saver:
                    continue
                if act.user_ask and act.user_ask.search(snap["user_text"]):
                    continue  # 让她做了：走下面的补做
                if any(c["ok"] and _tool_matches(c["name"], act.tools) for c in calls):
                    continue
                new = retract_claims(reply, act.claim)
                if new is None or new == reply:
                    if new is None:
                        logger.warning(f"follow_through: 整条回复都是谎称{act.desc}，没法只删那一句: {reply[:60]}")
                    continue
                logger.info(f"follow_through: 没人让她{act.desc}、也没做，删掉谎称的话: {reply[:60]!r} -> {new[:60]!r}")
                resp.completion_text = reply = new
                event.set_extra(RETRACT_KEY, act.key)

        if not self.config.get("enable_follow_up", True):
            return

        # 1) 嘴上答应/声称了，但没调用对应工具
        # 主模型当大脑时（kaju_style rewrite.main_role = brain），这里看到的已经是回复器写的话；
        # 大脑定下的“答应：…”也一起看（11-19：“答应：去查 Hoody 平台”，说出口变成“这就去看Hoody那个”）
        heard = reply + "".join(f"\n{x}" for x in plan_promises(event.get_extra("_ks_plan")))
        missing: list[Action] = []
        for act in ACTIONS:
            if not any(_tool_matches(n, act.tools) for n in available):
                continue  # 这一轮根本没有这个能力，交给提示词去约束
            if act.key == "meme" and handled_by_meme_saver:
                continue  # 表情包插件已经当场存好（或问了分类），不经过 save_meme 工具
            said = (act.promise and act.promise.search(heard)) or (act.claim and act.claim.search(reply))
            if not said:
                continue
            if act.user_ask and not act.user_ask.search(snap["user_text"]):
                continue
            if any(_tool_matches(c["name"], act.tools) for c in calls):
                continue
            if act.key == "search" and any(c["name"] == "browse_bilibili" for c in calls):
                continue  # "马上去搜五条悟"说的是去刷B站找视频（后台在刷），不是上网搜文字资料
            missing.append(act)

        # 2) 工具失败了，却说成功了
        failures = [c for c in calls if not c["ok"]]
        claimed_ok = SUCCESS_WORDS.search(reply) and not ACK_FAILURE.search(reply)

        mode = None
        if failures and claimed_ok:
            mode = "correct"
        elif missing:
            mode = "do"
        if mode is None:
            return

        umo = event.unified_msg_origin
        now = time.time()
        if now - self._last_follow_up.get(umo, 0) < float(self.config.get("cooldown_seconds", 30)):
            logger.info(f"follow_through: {mode} needed but in cooldown ({umo})")
            return
        self._last_follow_up[umo] = now
        event.set_extra("_ft_req", None)  # 同一条消息只处理一次

        if mode == "do":
            logger.info(
                f"follow_through: 答应了却没做 {[a.key for a in missing]}，后台补做: {reply[:40]}"
            )
            self._note_miss(event, reply, missing)
            coro = self._follow_up(event, snap, reply, missing)
        else:
            logger.info(f"follow_through: 工具失败但回复说成功了 {[c['name'] for c in failures]}，后台更正")
            coro = self._correct(event, snap, reply, failures)
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @filter.on_agent_done()
    async def retract_history(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        """存进历史的那份回复在回复钩子之前就写好了：把删掉的谎称在那里也删掉，下一轮她不会以为自己存过。"""
        key = event.get_extra(RETRACT_KEY)
        act = next((a for a in ACTIONS if a.key == key), None)
        if act is None or act.claim is None:
            return
        try:
            msgs = run_context.messages
            if not msgs or msgs[-1].role != "assistant":
                return
            msg = msgs[-1]
            if isinstance(msg.content, str):
                msg.content = retract_claims(msg.content, act.claim) or msg.content
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if getattr(part, "type", None) == "text" and getattr(part, "text", None):
                        part.text = retract_claims(part.text, act.claim) or part.text
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"follow_through: 历史里的谎称没删掉: {exc!r}")

    @staticmethod
    def _note_miss(event: AstrMessageEvent, reply: str, missing: list[Action]) -> None:
        """记一笔“答应了却没做”（kaju_data\\self\\follow_through\\misses.jsonl）：kaju_learn 每晚复盘时当程序记录用（11-19）。"""
        try:
            from kaju_core import paths

            gid = str(event.get_group_id() or "")
            chat = f"g{gid}" if gid else f"p{event.get_sender_id()}"
            folder = paths.self_dir("follow_through")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "misses.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "chat": chat, "reply": reply[:120],
                                    "what": "、".join(a.desc for a in missing)}, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"follow_through: 没记下这次答应了没做 {exc!r}")

    # ---------- background work ----------
    @staticmethod
    def _pick_tools(snap: dict, prefixes: tuple[str, ...]) -> ToolSet | None:
        src: ToolSet | None = snap.get("func_tool")
        if not src:
            return None
        tools = ToolSet()
        for name in src.names():
            if _tool_matches(name, prefixes):
                tool = src.get_tool(name)
                if tool is not None:
                    tools.add_tool(tool)
        return tools if tools.names() else None

    def _router_order(self) -> list[str]:
        """kaju_basics 挑模型（router.py）现排的顺序；没有就空。
        11-19 12:34：补做只用 AstrBot 默认模型，那家卡了 100 多秒，整轮 120 秒超时，答应的事就没了。"""
        for meta in self.context.get_all_stars() or []:
            router = getattr(getattr(meta, "star_cls", None), "_router", None)
            if router is None or not callable(getattr(router, "order", None)):
                continue
            try:
                if callable(getattr(router, "on", None)) and not router.on():
                    return []
                return [x["pid"] for x in router.order("low") if x.get("pid")]
            except Exception as exc:  # noqa: BLE001
                logger.info(f"follow_through: 挑模型出错，用默认模型 {exc!r}")
                return []
        return []

    async def _run_agent(self, event: AstrMessageEvent, snap: dict, reply: str, prompt: str, tools):
        """按挑模型的顺序试：每家最多 attempt_seconds 秒，卡住就换下一家；总共不超过 timeout_seconds（超了抛 TimeoutError）。"""
        umo = event.unified_msg_origin
        default = await self.context.get_current_chat_provider_id(umo)
        order = self._router_order() or [default]
        tries = max(1, int(self.config.get("max_providers", 3)))
        pids = list(dict.fromkeys(p for p in order if p))[:tries] or [default]
        contexts = list(snap["contexts"])
        if snap["prompt"]:
            contexts.append({"role": "user", "content": snap["prompt"]})
        contexts.append({"role": "assistant", "content": reply})
        total = float(self.config.get("timeout_seconds", 150))
        per = float(self.config.get("attempt_seconds", 70))
        start = time.monotonic()
        last: BaseException | None = None
        for pid in pids:
            left = total - (time.monotonic() - start)
            if left < 10:
                break
            try:
                resp = await asyncio.wait_for(
                    self.context.tool_loop_agent(
                        event=event,
                        chat_provider_id=pid,
                        prompt=prompt,
                        system_prompt=snap["system_prompt"],
                        contexts=contexts,
                        tools=tools,
                        max_steps=int(self.config.get("max_steps", 6)),
                        tool_call_timeout=60,
                    ),
                    timeout=min(per, left),
                )
            except Exception as exc:  # noqa: BLE001 - 这家不行换下一家
                last = exc
                logger.info(f"follow_through: 补做用 {pid} 没成（{type(exc).__name__}），换下一家")
                continue
            text = self._clean(getattr(resp, "completion_text", "") or "")
            if text:
                return text
            logger.info(f"follow_through: 补做用 {pid} 什么都没说，换下一家")
        if isinstance(last, Exception) and not isinstance(last, asyncio.TimeoutError):
            raise last
        raise asyncio.TimeoutError()

    async def _follow_up(self, event: AstrMessageEvent, snap: dict, reply: str, missing: list[Action]) -> None:
        try:
            # 先让第一句话发出去，再开始做
            await asyncio.sleep(float(self.config.get("delay_seconds", 3)))
            prefixes = tuple(p for a in missing for p in a.tools) + ("search_memory",)
            if any(a.key == "remind" for a in missing):
                prefixes += ("send_message_to_user",)
            tools = self._pick_tools(snap, prefixes)
            if tools is None:
                logger.warning("follow_through: 找不到对应工具，跳过补做")
                return
            all_silent = all(a.silent for a in missing)
            silent_hint = (
                "这件事你刚才已经说过了，做成了的话只输出 [DONE] 就好，不用再说一遍。" if all_silent else ""
            )
            prompt = FOLLOW_UP_PROMPT.format(
                reply=reply[:80],
                todo="、".join(a.desc for a in missing),
                silent_hint=silent_hint,
            )
            text = await self._run_agent(event, snap, reply, prompt, tools)
            await self._deliver(event, text, snap)
        except asyncio.TimeoutError:
            logger.warning("follow_through: 补做超时")
            # 只给意思，说法交给回复器（kaju_style polish）；没有 kaju_style 才照这句原样发
            # 11-19：原来写“请对方等一下”，回复器照着前文她那句写回成“这就去查”，核对连拦 4 遍，什么都没发出去。
            # 这里把意思说死：没查成、不是还在查。
            todo = "、".join(a.desc for a in missing)
            await self._deliver(
                event,
                f"刚才说要{todo}的事没做成：查的时候卡住了，什么结果都没拿到。"
                "跟对方说一声这次没查到，对方还想要的话再叫佳树一次。不要再说“这就去查”。",
                snap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"follow_through: 补做失败: {exc!r}")

    async def _correct(self, event: AstrMessageEvent, snap: dict, reply: str, failures: list[dict]) -> None:
        try:
            await asyncio.sleep(float(self.config.get("delay_seconds", 3)))
            names = tuple({f["name"] for f in failures})
            tools = self._pick_tools(snap, names)
            desc = "；".join(f"{f['name']} 返回：{f['result'][:120]}" for f in failures[:3])
            prompt = CORRECTION_PROMPT.format(reply=reply[:80], failures=desc)
            text = await self._run_agent(event, snap, reply, prompt, tools)
            await self._deliver(event, text, snap)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"follow_through: 更正失败: {exc!r}")

    def _style(self):
        """kaju_style（有 polish 的那个插件）：补做的话交给它按她的口吻重写（大脑模式下主模型不扮佳树说话）。"""
        for meta in self.context.get_all_stars() or []:
            star = getattr(meta, "star_cls", None)
            if star is not None and callable(getattr(star, "polish", None)):
                return star
        return None

    async def _voice(self, event: AstrMessageEvent, text: str, snap: dict | None) -> list[str] | None:
        """补做的话 → 发出去的几行。有 kaju_style：交给 polish（回复器写）；它只发写手的话时写不成 → None（这次不发）。"""
        style = self._style()
        if style is None:
            return [text]
        group = bool(event.get_group_id())
        title = event.get_extra("_ks_rw_title") or ("" if group else "兄长大人")
        ctx = []
        for m in list((snap or {}).get("contexts") or [])[-4:]:
            c = m.get("content") if isinstance(m, dict) else ""
            if isinstance(c, list):
                c = " ".join(str(p.get("text") or "") for p in c if isinstance(p, dict))
            if c:
                who = "佳树" if m.get("role") == "assistant" else (title or "群里")
                ctx.append(f"{who}：{str(c).replace(chr(10), ' / ')[:160]}")
        only_writer = bool(getattr(style, "writer_only", lambda: False)())
        try:
            out = await style.polish(text, ctx, said=(snap or {}).get("user_text", ""),
                                     title=title or "兄长大人", kind="群聊" if group else "私聊")
        except Exception as e:  # noqa: BLE001
            if only_writer:
                logger.info(f"follow_through: 回复器没写成，这次不补发 {type(e).__name__}: {e}")
                return None
            out = text
        if not (out or "").strip():
            if only_writer:
                logger.info("follow_through: 回复器没写成，这次不补发")
                return None
            out = text
        return [ln.strip() for ln in out.splitlines() if ln.strip()]

    async def _deliver(self, event: AstrMessageEvent, text: str, snap: dict | None = None) -> None:
        """text 当意思交给回复器（_voice）；没有 kaju_style 才原样发。"""
        upper = text.upper()
        if not text or "[SKIP]" in upper:
            logger.info("follow_through: 模型判断不需要补发")
            return
        if "[DONE]" in upper:
            logger.info("follow_through: 已补做完成（无需再说）")
            return
        umo = event.unified_msg_origin
        if event.get_extra("qzone_comment"):  # QQ 空间评论那一轮：补发会变成私聊，不发
            logger.info(f"follow_through: QQ空间评论那一轮，不补发: {text[:60]}")
            return
        if event.get_group_id():  # 显卡在训练 / 兄长在控制台暂停了群聊（2026-11-17）
            try:
                from kaju_core import gpu_busy
                q = getattr(gpu_busy, "quiet_group", None)
                why = q() if q else gpu_busy.busy()
            except Exception:  # noqa: BLE001
                why = ""
            if why:
                logger.info(f"follow_through: 群聊暂停中（{why}），不补发: {text[:60]}")
                return
        lines = await self._voice(event, text, snap)
        if not lines:
            return
        for i, ln in enumerate(lines):
            if i:
                await asyncio.sleep(1.0)
            await self.context.send_message(umo, MessageChain().message(ln))
        said = "\n".join(lines)
        logger.info(f"follow_through: 已补发后文: {said[:60]}")
        await self._append_to_history(umo, said)

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"<ref>.*?</ref>|\[\d+\]", "", text, flags=re.S)
        text = re.sub(r"&&[^&\n]{1,60}&&", "", text)  # 这里直接发，不经过表情包插件
        text = re.sub(r"[*#`>]+", "", text)
        return text.strip()

    async def _append_to_history(self, umo: str, text: str) -> None:
        """把补发的话接到她上一条回复后面，这样下一轮她记得自己做过什么。"""
        try:
            conv_mgr = self.context.conversation_manager
            cid = await conv_mgr.get_curr_conversation_id(umo)
            if not cid:
                return
            await asyncio.sleep(1)  # 等主流程先把历史写完
            conv = await conv_mgr.get_conversation(umo, cid)
            if not conv:
                return
            history = json.loads(conv.history) if isinstance(conv.history, str) and conv.history else (conv.history or [])
            last = next((m for m in reversed(history) if m.get("role") == "assistant"), None)
            if last is not None and isinstance(last.get("content"), str):
                last["content"] = last["content"] + "\n" + text
            else:
                history.append({"role": "assistant", "content": text})
            await conv_mgr.update_conversation(umo, cid, history=history)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"follow_through: 写入对话历史失败: {exc!r}")
