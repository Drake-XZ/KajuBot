"""聪明插话：替代内置的"每条消息 15% 概率随机回复"。

内置主动回复的问题：
- 每条消息掷一次骰子，"嗷嗷""是吧"这种碎语也会触发；
- 触发后只把那一条消息当成问题丢给模型，于是她总是"复述一句 + 点评一句"；
- 一旦触发就必须说话，没法选择不说。

这里的做法：
1. 等群里安静几秒（一波消息说完）再判断；打分看最近两分钟的整段聊天（不只是刚才这一波），
   再按新消息占比折算概率，所以一句一停的慢聊和一口气刷屏，插话频率差不多。
2. 按内容打分：纯碎语不插话；有人在群里提问、聊到她关心的话题（吃饭、学习、睡觉、学姐、小说……）、
   聊得热闹时，插话概率更高。
3. 插话时告诉她：这次没人叫你，接住大家在聊的话题本身，别只挑一句复述点评；插不上话就输出 [SKIP]，
   [SKIP] 的回复不会发出去，也不会写进对话历史。
4. 冷却和每小时上限，防止刷屏；她正在回别人时不插话。
5. 接着聊：她刚回过某人（被叫到或主动插话），这个人几分钟内再发消息、没 @ 别人，
   就可能是在接着跟她说话——不看冷却和概率，等对方说完（几秒）就让她看看要不要接着回；
   她判断这条其实是跟别人说的，就输出 [SKIP]。引用她的消息本来就会唤醒她，不用这里管。
   不算接着聊（2026-10-31 她替兄长大人回答了别人 @ 他的问题）：
   - 这一波里 TA 后来又 @ 了别人 / 引用了别人的消息；
   - 她跟 TA 说完话之后，有别人 @ 过 TA 或引用过 TA（TA 多半在回那个人）；
   - 这条消息她回上一句时已经看到过了。
   - 她自己插话那次（2026-11-05）：最后说话的人没在跟她聊，不算接着聊的对象；她插话时问了 TA 什么才算。
   插话/接着聊的提醒里写明：没叫名字、没 @、没戳、没引用她时，群友话里的"你"是在叫别人，不是她；
   发言人最近跟谁互相 @ / 引用过，就告诉她"你"多半指那个人。
6. 被叫到时先等对方说完：有人 @ 她 / 叫她名字后，等这个人安静 wake_quiet_seconds 秒（最多等
   wake_max_wait 秒）再开始回复；同一个人又叫了她一次，就只回最新那次（前面那条在群聊记录里一起看到）。
   内置群聊上下文只把"叫她那条之前"的消息给她看，叫她之后、开始回复之前新来的消息这里补进本轮请求，
   这样她一次看完整段再回，而不是一句一句地回。
7. 回之前再看一眼（2026-11-01，跟私聊连发合并同一个思路）：等完之后还要排队（她正在回别人），排队时同一个人又叫了她，
   这次就不回了，交给后面那次一起回（不然这次的"新来的消息"里已经有后面那句，后面那次又回一遍）；
   别人也在排队等她回时，提醒她这次只回眼前这个人；对方是在她上一条回复（回给 TA 的）发出去之前打的字，提醒她别重复。
8. 同一个人连着发，回一次（2026-11-07 555 发红包 → 她插话那轮还在生成时，555 又说"给佳树爆米"叫了她 → 两条回复各回一半）：
   - 她这轮回复写好、还没发出去时，同一个人在这条之后又叫了她 → 这轮不发、不进历史，群聊记录放回去，
     交给叫她那次一起回（提醒她前面那条也还没回）。
   - 接着聊在等的时候，同一个人还有消息在路上（到了但还在等图片描述，比如表情包）→ 等它到了一起看，
     不然先回"0.11"、再单独回那张竖大拇指的表情包。

需要把内置的 主动回复(active_reply) 关掉，群聊上下文(group_icl) 保持开启。
"""

import asyncio
import random
import sys
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Image, Plain, Reply
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart

try:  # 她正在跑一轮回复时不要插话
    from astrbot.core.pipeline.process_stage.follow_up import _ACTIVE_AGENT_RUNNERS
except Exception:  # noqa: BLE001
    _ACTIVE_AGENT_RUNNERS = {}

PLUGIN_NAME = "astrbot_plugin_smart_chime_in"

FILLER = re.compile(
    r"^(哈+|嗯+|哦+|噢+|啊+|嗷+|草+|艹+|6+|666+|好+|好的|是吧|是的|对+|确实|行|可以|笑死|绷|乐|"
    r"\?+|？+|。+|…+|\.+|ok|OK|hhh+|233+|wc|卧槽|牛|nb|NB|[!！~～]+)$"
)
QUESTION = re.compile(r"[?？]|吗$|吗[。!！]|有没有|谁知道|谁会|怎么|为什么|为啥|什么|啥|咋|哪个|哪里|多少|推荐")
# 佳树会想插嘴的话题（人设相关）
TOPICS = re.compile(
    r"吃|饭|饿|点心|蛋糕|甜|做饭|外卖|奶茶|零食|"
    r"睡|困|熬夜|累|"
    r"考试|学习|作业|复习|期末|期中|上课|老师|学校|学生会|"
    r"妹妹|女生|女朋友|对象|学姐|约会|"
    r"小说|动画|番|漫画|游戏|"
    r"抽卡|抽到|抽了|抽个|抽谁|卡池|保底|十连|出货|歪了|角色|联动|皮肤|氪|首充|充值|版本|活动|"
    r"up池|副本|排位|上分|开黑|手游|二次元|声优|cos|"
    r"生日|礼物|天气|下雨|冷|热|感冒|生病",
    re.IGNORECASE,
)
# 插话时她嘴上说"插不上话"其实就是不想说，按 [SKIP] 处理
DEFLECT = re.compile(r"插不上(嘴|话)|聊点别的|换个话题|这些话题佳树|佳树(也)?(不太|不)懂(这些|这个)")

CHIME_IN_NOTE = (
    "【插话模式】这次没有人叫你，是你自己看到群里在聊天，想插一句。上次你说话之后的群聊记录在 <system_reminder> 里，"
    "最后一条是 {sender} 刚发的。\n"
    "- 先看大家整体在聊什么，接住这个话题本身，像群友一样自然地加入：可以接某个人的话、好奇地追问一句、"
    "说说你知道的或查到的具体东西、吐槽或开个玩笑。\n"
    "- 不要只挑最后一句复述再点评（比如\"XX……听起来像……呢\"），不要用\"兄长大人说的是……吗？\"这种复读开头，"
    "也不要每次都说\"佳树不懂\"。\n"
    "- 话题你不了解但值得聊（游戏、新闻、作品、术语），可以先搜一下，说点具体的。\n"
    "- 群友常用外号、谐音梗、emoji 缩写（比如用\"福利链\"指芙莉莲、\"1🐔\"指某个角色）。"
    "没把握某个词指什么、或者不知道他们在玩哪个游戏时，不准瞎猜着说泛泛的话："
    "要么先搜一下弄明白，要么像群友一样好奇地问一句（\"1🐔是哪个角色呀？\"），问一句也是很自然的插话。\n"
    "- 如果你插不上话、大家只是在闲扯碎语、话题擦边或不适合你、或者是两个人在私聊某件事、插嘴会打扰别人，"
    "就只输出 [SKIP]，什么也别说。宁可不说，也别硬说。\n"
    "- 不要把\"插不上嘴\"\"聊点别的吧\"\"佳树不懂这些\"说出来——这种情况直接输出 [SKIP]。\n"
    "- 这些话都不是对你说的：没人叫你名字、没人 @你、没人戳你、也没人引用你的话。"
    "群友之间也天天说「你」「你们」，这里的「你」是发言人在叫群里的别人，不是你，也不是在说你"
    "（只有内容明摆着是在回你上一条说的话时例外）。"
    "别把别人的话认到自己头上：「你变了」接「佳树本来就没变呀」、「你更新了吗」接「佳树不用更新呀」，都是认错了人。"
    "要插话就以旁边群友的身份接话题本身。{hint}"
)
# 插话时补一句：发言人最近在跟谁说话（@ / 引用来回），TA 话里的"你"多半是那个人
TALKING_TO_HINT = "\n- {sender} 刚才在跟 {other} 说话（互相 @ / 引用过），TA 话里的「你」多半指 {other}。"

FOLLOW_NOTE = (
    "【可能在接着跟你聊】你刚才在群里和 {partner} 说过话，TA 现在又发了消息：「{text}」，"
    "没有 @你、没叫你名字、也没引用你的话。群里大多数时候，这样的话是说给别人听的。"
    "先看 <system_reminder> 里的群聊记录弄清楚：\n"
    "- 只有内容明显是在接你刚才那句（回答你问 TA 的事、接着你说的那件事、对你的话表态）→ "
    "像正常对话一样接着回 TA，别问\"你是在跟佳树说话吗\"。\n"
    "- 话里有「你」不算证据：群友互相也说「你」。是在回答别人的问题、接别人的话、跟别人说话（哪怕提到了你）、"
    "自己嘀咕，或者别人已经接上了话 → 只输出 [SKIP]。"
    "不要替被问的人回答，也不要把别人之间说的话当成对你的要求。拿不准时就 [SKIP]。"
)
# 她插话时问了对方什么（她问句常以"呀/嘛"结尾、不带问号）
ASKED = re.compile(r"[?？]|吗|哪|谁|什么|啥|怎么|咋|多少|是不是|要不要|好不好|能不能|有没有")

MERGED_NOTE = (
    "\n\n【这条消息】{name} 前面还叫过你（{texts}，在上面的群聊记录里），和这条是连着说的："
    "合在一起看，回一次就好，别分开回。"
)
OTHERS_NOTE = "\n\n【还在等你回的】{names} 也叫了你，那几条等会儿会单独回：这次先只回 {name}，别替那几条回答。"
ALSO_NOTE = (
    "\n\n【也在等你回的】你排队的时候，{who} 也在接着跟你说话（在上面的群聊记录里）。"
    "这次一起看完再回一次：该接谁的话就接谁的，可以一句话照顾到几个人；只有他们其实都不是在跟你说话时才 [SKIP]。"
)
# 2026-11-13 妖妖群：她插完一句，兄长大人问"怎么突然回了zsy一句"，三秒后 555 说"这勾八佳树"叫醒她——
# 她只对着 555 回，兄长大人的问题没人管（那条没叫她名字，也不算接着聊）。叫她那次把这些也给她看。
WAITING_NOTE = (
    "\n\n【你上一条之后群里还有】{who} 也说了话（在上面的群聊记录里），没 @别人、也没引用别人的话。"
    "群里这样的话多数是接着自己的话题在说、不是对你说的：只有内容在说你、问你、明显接你那句，才一起接上（可以一句话照顾到几个人）；"
    "不然就当没看见，别把它当成有人在叫你。"
)
UNANSWERED_NOTE = (
    "\n\n【这条消息】{name} 叫你之前还发了 {texts}（在上面的群聊记录里），你还没回：和这条是连着的一件事，"
    "合在一起看，回一次就好，别分成两件事各说一遍。"
)
UNSEEN_NOTE = (
    "\n\n【这条消息】{name} 发这些的时候，你上一条回给 TA 的话还没发出去（你们是同时在打字），TA 多半还没看到："
    "你上一条已经说过的意思别再说一遍，接着回应新说的就好。"
)


def _wake_text(event: AstrMessageEvent) -> str:
    text = " ".join((_plain_text(event) or event.get_message_str() or "").split())
    if not text:
        text = "[图片]" if any(isinstance(c, Image) for c in event.get_messages()) else "（叫了你一声）"
    return text[:40] + ("…" if len(text) > 40 else "")


LATE_NOTE = (
    "<system_reminder>你被叫到之后、开始回复之前，群里又有这些新消息（可能是叫你的人在接着补充，"
    "也可能是别人在说话）。把它们和上面那条一起看完、弄明白大家整体的意思，再一起回一次，不要一句一句地回：\n"
    "--- BEGIN ---\n{lines}\n--- END ---\n</system_reminder>"
)


@dataclass
class GroupState:
    seq: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=80))  # 最近的群消息（打分看最近几分钟）
    pending: int = 0  # 上次做决定之后新来的消息数
    last_spoke: float = 0.0
    chime_times: deque = field(default_factory=lambda: deque(maxlen=50))
    partners: dict = field(default_factory=dict)  # 她刚回过的人：QQ -> 最后一次对 TA 说话的时间
    follow: dict | None = None  # 这一波里有人可能在接着跟她聊：{"sender", "name", "text", "t"}
    addressed: dict = field(default_factory=dict)  # 被别人 @ / 引用过的人：QQ -> 时间
    last_from: dict = field(default_factory=dict)  # 每个人最后一次发消息的时间
    wake_tokens: dict = field(default_factory=dict)  # 每个人正在等着回的那次"叫她"
    wake_pending: dict = field(default_factory=dict)  # 叫了她、还没开始回复的：token -> 时间
    seen_until: float = 0.0  # 她最近一次开始回复（请求模型）的时间：这之前的消息她都看过了
    wake_info: dict = field(default_factory=dict)  # 叫了她还没回的：token -> {event, sender, name, text, t, t0, earlier}
    reply_start: tuple = (0.0, "")  # 她最近一次开始发回复：(时间, 回给谁)
    reply_end: tuple = (0.0, "")  # 她最近一次发完回复
    follows: dict = field(default_factory=dict)  # 排着队的"接着聊"：token -> {event, sender, name, text, t, also}
    links: dict = field(default_factory=dict)  # 谁 @ / 引用了谁：(from QQ, to QQ) -> 时间
    names: dict = field(default_factory=dict)  # QQ -> 群里的名字
    coming: dict = field(default_factory=dict)  # 到了、还没走到 maybe_chime_in 的消息（多半在等图片描述）：id(event) -> (QQ, 时间, event)
    waiting: dict = field(default_factory=dict)  # 正在等她说完 / 等 TA 下一条的"接着聊"：QQ -> follow


def _plain_text(event: AstrMessageEvent) -> str:
    return "".join(c.text for c in event.get_messages() if isinstance(c, Plain)).strip()


@register(PLUGIN_NAME, "dsh", "聪明插话：等一波聊完再按内容决定要不要插话，插不上话就不说", "1.12.0")
class SmartChimeIn(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._groups: dict[str, GroupState] = defaultdict(GroupState)

    def _c(self, key: str, default):
        val = self.config.get(key, default)
        try:
            return type(default)(val)
        except (TypeError, ValueError):
            return default

    # ---------- scoring ----------
    def _mood_factor(self) -> float:
        """心情插件（kaju_heart）给的插话倍数；没装就是 1。"""
        for meta in self.context.get_all_stars() or []:
            fn = getattr(getattr(meta, "star_cls", None), "chime_factor", None)
            if callable(fn):
                try:
                    return float(fn())
                except Exception:  # noqa: BLE001
                    return 1.0
        return 1.0

    @staticmethod
    def _meaningful(t: str) -> bool:
        return len(t) >= 3 and not FILLER.match(t)

    def _score(self, window: list[dict], new_count: int) -> tuple[float, str]:
        """window：她上次说话之后、最近 window_seconds 秒的消息；new_count：其中最后几条是这次新来的。

        先按整段聊天算出"这段聊天值得插一句"的概率 p，再按新消息占整段的比例折算成这一次的概率，
        这样群里一句一停（每条都单独做一次决定）和一口气刷完（只做一次决定），整体插话频率差不多。
        """
        burst = window
        texts = [m["text"] for m in burst if m["text"]]
        meaningful = [t for t in texts if self._meaningful(t)]
        new_meaningful = [m for m in burst[-new_count:] if m["text"] and self._meaningful(m["text"])] if new_count else []
        if not meaningful or not new_meaningful:
            return 0.0, "only filler"
        joined = " ".join(meaningful)
        speakers = {m["sender"] for m in burst}

        p = self._c("base_chance", 0.35)
        why = ["base"]
        if any(QUESTION.search(t) for t in meaningful):
            p += self._c("question_bonus", 0.2)
            why.append("question")
        if TOPICS.search(joined):
            p += self._c("topic_bonus", 0.2)
            why.append("topic")
        if len(meaningful) >= 3 and len(speakers) >= 2:
            p += self._c("lively_bonus", 0.1)
            why.append("lively")
        # 群里大家习惯一句话拆成几条发，只有整波就一句很短的话才降低
        if len(meaningful) == 1 and len(joined) < 6:
            p *= 0.5
            why.append("short")
        # 两个人互相 @ 着聊，多半是私事
        if burst and all(m["at_other"] for m in burst[-2:]):
            p *= 0.5
            why.append("private-ish")
        mood = self._mood_factor()
        if mood != 1.0:  # kaju_heart：开心有精神时多说两句，委屈没精神时少说
            p *= mood
            why.append(f"mood×{mood:.2f}")
        p = min(p, self._c("max_chance", 0.7))
        share = len(new_meaningful) / len(meaningful)
        p_now = 1 - (1 - p) ** share
        why.append(f"{len(new_meaningful)}/{len(meaningful)}条新")
        return p_now, "+".join(why)

    # ---------- 被叫到：等对方说完 ----------
    async def _hold_until_done(self, event: AstrMessageEvent, st: GroupState, sender: str) -> None:
        """Delay a wake-up until `sender` has been quiet for a moment; a newer wake-up from them wins."""
        if (event.get_message_str() or "").lstrip().startswith("/"):
            return  # 指令，不走模型
        # 记下"她马上要回复了"：接着聊的判断要等她这次回复开始之后再做（show_late_messages 里清掉）
        token = object()
        now = time.time()
        st.wake_pending[token] = now
        st.wake_info[token] = {"event": event, "sender": sender, "name": event.get_sender_name() or "群友",
                               "text": _wake_text(event), "t": now, "t0": now, "earlier": []}
        event.set_extra("_chime_wake_token", token)
        quiet = self._c("wake_quiet_seconds", 3.0)
        cap = self._c("wake_max_wait", 12.0)
        if not self._c("wake_hold", True) or quiet <= 0:
            return
        st.wake_tokens[sender] = token
        start = time.time()
        try:
            while True:
                await asyncio.sleep(min(0.5, quiet))
                if st.wake_tokens.get(sender) is not token:
                    logger.info(f"smart_chime_in: {event.get_sender_name()} 又叫了她一次，只回最新那次")
                    self._pass_on(st, token, st.wake_info.get(st.wake_tokens.get(sender)))
                    # 只 stop_event 不够：没有结果的唤醒消息 AstrBot 仍会请求模型，所以把唤醒也撤掉
                    event.is_at_or_wake_command = False
                    event.stop_event()
                    st.wake_pending.pop(token, None)
                    return
                t = time.time()
                if t - st.last_from.get(sender, start) >= quiet or t - start >= cap:
                    break
        finally:
            if st.wake_tokens.get(sender) is token:
                st.wake_tokens.pop(sender, None)
        waited = time.time() - start
        if waited > quiet + 1.0:
            logger.info(f"smart_chime_in: 等 {event.get_sender_name()} 说完才回（{waited:.1f}s）")

    @staticmethod
    def _pass_on(st: GroupState, token, newer: dict | None) -> None:
        """这次叫她的不单独回了：说过的话记到后面那次上（她回那次时提一句"前面还叫过你"）。"""
        info = st.wake_info.pop(token, None)
        st.wake_pending.pop(token, None)
        if info and newer is not None:
            newer["earlier"] = info["earlier"] + [info["text"]] + newer["earlier"]
            newer["t0"] = min(newer["t0"], info["t0"])
            also = newer.setdefault("also", [])
            for name in info.get("also", []):
                if name not in also and name != newer.get("name"):
                    also.append(name)

    @staticmethod
    def _alive_wakes(st: GroupState) -> dict:
        now = time.time()
        for tok, info in list(st.wake_info.items()):
            ev = info["event"]
            gone = now - info["t"] > 120
            try:
                gone = gone or ev.is_stopped() or bool(ev.get_extra("_follow_up_captured"))
            except Exception:  # noqa: BLE001
                pass
            if gone:
                st.wake_info.pop(tok, None)
        return st.wake_info

    @staticmethod
    def _unseen(st: GroupState, sender: str, t0: float) -> bool:
        """TA 从 t0 开始说的这些，是不是在她上一条回给 TA 的话发完之前打的。"""
        (s_t, s_who), (e_t, e_who) = st.reply_start, st.reply_end
        if e_who == sender and e_t > t0:
            return True
        # 回复还在分段发（after_message_sent 偶尔不触发，60 秒后不算）
        return s_who == sender and s_t > e_t and s_t > t0 - 60 and time.time() - s_t < 60

    def _waiting_for_her(self, st: GroupState, waker: str, skip_names: set) -> list[tuple[str, list[str]]]:
        """她上一条发出去之后、可能在跟她说话的别人（叫她的人和已经在排队的人除外）：[(名字, [最近两句])]。
        算“可能在跟她说”：没 @ / 引用别人，并且 是她上一条之后的第一条、或 TA 刚和她聊过、或 @ / 引用了她。"""
        if not self._c("wake_waiting_note", True):
            return []
        end_t = st.reply_end[0]
        now = time.time()
        window = self._c("wake_waiting_seconds", 180.0)
        if not end_t or now - end_t > window:
            return []
        after = [m for m in st.recent if m["t"] > end_t]
        first = after[0] if after else None
        # 她回之前刚在说话的人（最后 3 条里有 TA）：之后没 @ / 引用 / 叫她，多半是接着自己的话头说（2026-11-18：
        # 哆啦a梦学姐“量化我听不懂 / 讲话”→ 她插了一句 → 学姐接着“和他说听不懂了”，被当成在跟她说，兄长纠正时她又理解反了）
        before = [str(m.get("sender") or "") for m in st.recent if m["t"] <= end_t][-3:]
        out: dict[str, tuple[str, list[str]]] = {}
        for m in after:
            who = str(m.get("sender") or "")
            name = m.get("name") or st.names.get(who) or "群友"
            shown = m.get("show") or m.get("text") or ""
            if who == waker or name in skip_names or m.get("at_other") or m.get("quote_other") or not shown:
                continue
            if who in before and not m.get("to_her"):
                continue
            partner = now - st.partners.get(who, 0.0) < self._c("follow_seconds", 180.0)
            if not (m is first or partner or m.get("to_her")):
                continue
            texts = out.setdefault(who, (name, []))[1]
            texts.append(shown[:40] + ("…" if len(shown) > 40 else ""))
        return [(n, ts[-2:]) for n, ts in list(out.values())[:3]]

    def _talking_to(self, st: GroupState, sender: str) -> str | None:
        """sender 最近在跟谁说话：TA @ / 引用过的人，或 @ / 引用过 TA 的人（取最近的一次）。"""
        window = self._c("talking_to_seconds", 600.0)
        now = time.time()
        best, best_t = None, 0.0
        for (a, b), t in st.links.items():
            if now - t > window or t <= best_t:
                continue
            other = b if a == sender else a if b == sender else None
            if other and other != sender:
                best, best_t = other, t
        return st.names.get(best) if best else None

    def _find_group_context(self):
        """AstrBot's built-in group chat context object (records of group lines not yet shown to her)."""
        for meta in self.context.get_all_stars():
            gcc = getattr(getattr(meta, "star_cls", None), "group_chat_context", None)
            if gcc is not None and hasattr(gcc, "raw_records") and hasattr(gcc, "_record_ids"):
                return gcc
        return None

    async def _take_late_records(self, event: AstrMessageEvent) -> list[str]:
        """Group lines that arrived after the message she is answering, taken out of the built-in context.

        The built-in context has already (at priority 0) handed her everything up to that message and kept
        the rest for next time. Only touch its records when it really did that for this event.
        """
        gcc = self._find_group_context()
        record_id = event.get_extra("_group_context_record_id")
        if gcc is None or not isinstance(record_id, str):
            return []
        umo = event.unified_msg_origin
        try:
            async with gcc._get_lock(umo):
                records = gcc.raw_records.get(umo)
                ids = gcc._record_ids.get(umo)
                if not records or ids is None or record_id in ids:
                    return []
                lines = list(records)
                records.clear()
                ids.clear()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"smart_chime_in: 读不了群聊上下文: {exc!r}")
            return []
        return lines

    # ---------- 同一个人还有消息在路上 ----------
    @staticmethod
    def _coming_from(st: GroupState, sender: str, cap: float) -> bool:
        """sender 有消息已经到了、但还没走到 maybe_chime_in（前面的插件在等它的图片描述）。"""
        now = time.time()
        found = False
        for key, (who, t, ev) in list(st.coming.items()):
            try:
                gone = ev.is_stopped()
            except Exception:  # noqa: BLE001
                gone = False
            if gone or now - t > 120:
                st.coming.pop(key, None)
            elif who == sender and now - t < cap:
                found = True
        return found

    # ---------- 回复写好了，同一个人又叫了她：这次不发，交给那次一起回 ----------
    async def _snapshot_records(self, event: AstrMessageEvent) -> None:
        gcc = self._find_group_context()
        if gcc is None or not isinstance(event.get_extra("_group_context_record_id"), str):
            return
        umo = event.unified_msg_origin
        try:
            async with gcc._get_lock(umo):
                recs = list(gcc.raw_records.get(umo) or [])
                ids = list(gcc._record_ids.get(umo) or [])
        except Exception:  # noqa: BLE001
            return
        if len(recs) == len(ids):
            event.set_extra("_chime_records", (recs, ids))

    async def _restore_records(self, event: AstrMessageEvent) -> int:
        """把这一轮拿走的群聊记录（包括这条本身）放回内置上下文，后面那次回复能看到。返回放回的条数。"""
        snap = event.get_extra("_chime_records")
        gcc = self._find_group_context()
        if not snap or gcc is None:
            return 0
        umo = event.unified_msg_origin
        old_recs, old_ids = snap
        try:
            async with gcc._get_lock(umo):
                records = gcc.raw_records[umo]
                ids = gcc._record_ids[umo]
                cur = list(zip(records, ids))
                known = set(old_ids)
                have = {i for _, i in cur}
                merged = list(zip(old_recs, old_ids)) + [(r, i) for r, i in cur if i not in known]
                records.clear()
                ids.clear()
                records.extend(r for r, _ in merged)
                ids.extend(i for _, i in merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"smart_chime_in: 群聊记录没放回去 {exc!r}")
            return 0
        return sum(1 for i in old_ids if i not in have)

    @filter.on_llm_request(priority=sys.maxsize - 3)  # catch_up 之后、内置群聊上下文（priority 0）拿走记录之前
    async def snapshot_records(self, event: AstrMessageEvent, req: ProviderRequest):
        if event.get_group_id() and not event.is_stopped() and self._c("yield_to_wake", True):
            await self._snapshot_records(event)

    @filter.on_llm_response(priority=100001)  # drop_skip（100000）和重说层之前
    async def yield_to_newer_wake(self, event: AstrMessageEvent, resp: LLMResponse):
        if not event.get_group_id() or getattr(resp, "tools_call_name", None) or not self._c("yield_to_wake", True):
            return
        text = (getattr(resp, "completion_text", "") or "").strip()
        if not text or "[SKIP]" in text.upper():
            return
        st = self._groups[event.unified_msg_origin]
        sender = str(event.get_sender_id())
        try:
            arrived = float(getattr(event, "created_at", 0) or 0) or time.time()
        except (TypeError, ValueError):
            arrived = time.time()
        if time.time() - arrived > self._c("yield_max_seconds", 40.0):
            return  # 这一轮已经等很久了（比如查了资料）：先发出去，后面那次自己会看到
        mine = event.get_extra("_chime_wake_token")
        newer = [w for tok, w in self._alive_wakes(st).items()
                 if tok is not mine and w["sender"] == sender and w["t"] > arrived]
        if not newer:
            return
        target = max(newer, key=lambda w: w["t"])
        back = await self._restore_records(event)
        target.setdefault("unanswered", []).append(_wake_text(event))
        target["t0"] = min(target["t0"], arrived)
        mode = event.get_extra("_chime_in")
        if mode:
            st.last_spoke = float(event.get_extra("_chime_prev_spoke") or 0.0)
            if mode is True and st.chime_times:
                st.chime_times.pop()
        resp.completion_text = ""
        try:
            event.clear_result()
        except Exception:  # noqa: BLE001
            pass
        event.stop_event()
        logger.info(f"smart_chime_in: {target['name']} 在这条之后又叫了她，这次写好的「{text[:20]}」不发，"
                    f"交给叫她那次一起回（放回 {back} 条群聊记录）")

    # ---------- hooks ----------
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize - 5)
    async def note_arrival(self, event: AstrMessageEvent):
        """消息一到就记一笔：图片描述要等一阵才走到 maybe_chime_in，接着聊要知道它还在路上。"""
        if self._c("enable", True) and str(event.get_sender_id()) != str(event.get_self_id()):
            st = self._groups[event.unified_msg_origin]
            st.coming[id(event)] = (str(event.get_sender_id()), time.time(), event)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=-10)
    async def maybe_chime_in(self, event: AstrMessageEvent):
        if not self._c("enable", True):
            return
        self._groups[event.unified_msg_origin].coming.pop(id(event), None)
        if str(event.get_sender_id()) == str(event.get_self_id()):
            return
        umo = event.unified_msg_origin
        st = self._groups[umo]
        self_id = str(event.get_self_id())
        sender = str(event.get_sender_id())
        now = time.time()
        st.last_from[sender] = now
        if event.get_sender_name():
            st.names[sender] = event.get_sender_name()
        # 谁在跟谁说话：@ 了谁、引用了谁的消息
        for c in event.get_messages():
            target = None
            if isinstance(c, At):
                target = str(c.qq)
                if getattr(c, "name", None) and target not in st.names:
                    st.names[target] = str(c.name)
            elif isinstance(c, Reply) and c.sender_id is not None:
                target = str(c.sender_id)
                if getattr(c, "sender_nickname", None) and target not in st.names:
                    st.names[target] = str(c.sender_nickname)
            if target and target not in (self_id, "all", sender):
                st.addressed[target] = now
                st.links[(sender, target)] = now
        if len(st.links) > 200:
            for k, t in sorted(st.links.items(), key=lambda kv: kv[1])[:100]:
                st.links.pop(k, None)

        if event.is_at_or_wake_command:
            # 有人叫她，她会正常回复；这波消息就不用再考虑插话了，冷却也从现在算
            # （after_message_sent 不一定每次都触发，这里先记一笔）
            # 她说话之前的消息不再参与打分（打分只看 last_spoke 之后的）
            st.pending = 0
            st.seq += 1
            st.follow = None
            st.last_spoke = time.time()
            st.partners[sender] = time.time()
            await self._hold_until_done(event, st, sender)
            return

        text = _plain_text(event)
        has_image = any(isinstance(c, Image) for c in event.get_messages())
        if not text and not has_image:
            return
        at_other = any(isinstance(c, At) and str(c.qq) not in (self_id, "all") for c in event.get_messages())
        # 引用别人的消息也算在跟别人说话
        quote_other = any(
            isinstance(c, Reply) and c.sender_id is not None and str(c.sender_id) != self_id
            for c in event.get_messages()
        )
        to_her = any((isinstance(c, At) and str(c.qq) == self_id)
                     or (isinstance(c, Reply) and str(c.sender_id) == self_id) for c in event.get_messages())

        st.seq += 1
        my_seq = st.seq
        st.recent.append(
            {"sender": event.get_sender_id(), "text": text, "at_other": at_other,  # text 打分用，别改
             "quote_other": quote_other, "to_her": to_her, "name": event.get_sender_name() or "群友",
             "show": text or "[图片]", "t": time.time()}
        )
        st.pending += 1

        # 接着聊：她刚回过这个人，TA 没 @ 别人又说话了
        talked_at = st.partners.get(sender, 0.0)
        if (at_other or quote_other) and st.follow and st.follow["sender"] == sender:
            # TA 接着转头跟别人说话了：前面那几条也多半不是对她说的
            st.follow = None
        elif (
            self._c("follow_enable", True)
            and not at_other
            and not quote_other
            and time.time() - talked_at < self._c("follow_seconds", 180.0)
            # 她说完之后有别人 @ / 引用过 TA：TA 现在多半在回那个人
            and st.addressed.get(sender, 0.0) < talked_at
        ):
            piece = text or "[图片]"
            t0 = time.time()
            waiting = st.waiting.get(sender)
            if st.follow and st.follow["sender"] == sender:  # 一句话拆成几条发的，拼起来
                piece = (st.follow["text"] + " / " + piece)[-120:]
                t0 = st.follow.get("t0", t0)
            elif waiting:  # TA 前一条的接着聊正在等这条（等图片描述）：拼起来一起回
                piece = (waiting["text"] + " / " + piece)[-120:]
                t0 = waiting.get("t0", waiting["t"])
            st.follow = {"sender": sender, "name": event.get_sender_name() or "群友", "text": piece[:120],
                         "t": time.time(), "t0": t0}

        # 等这一波说完：安静 quiet_seconds 秒内没有新消息，才由最后一条来做决定。
        # 群里一直刷个不停时，攒够 burst_cap 条也做一次决定。接着聊时等得短一些。
        if st.pending < self._c("burst_cap", 15):
            wait = self._c("follow_quiet_seconds", 4.0) if st.follow else self._c("quiet_seconds", 8.0)
            await asyncio.sleep(wait)
            if st.seq != my_seq:
                return
        new_count = st.pending
        st.pending = 0
        follow, st.follow = st.follow, None

        if follow:
            # 她还在回上一条（分段发送中）、或者有人叫了她她还没开始回时，先等她说完；
            # TA 还有消息在路上（表情包还在等描述）也等一等，到了一起看（2026-11-07 先回"0.11"、再单独回表情包）
            coming_cap = self._c("follow_wait_coming", 30.0)
            st.waiting[follow["sender"]] = follow
            for _ in range(240):
                t = time.time()
                for tok, since in list(st.wake_pending.items()):
                    if t - since > 30:  # 叫她的那条没走到模型（出错、被别的插件处理了）
                        st.wake_pending.pop(tok, None)
                if (not st.wake_pending and _ACTIVE_AGENT_RUNNERS.get(umo) is None
                        and not (coming_cap > 0 and self._coming_from(st, follow["sender"], coming_cap))):
                    break
                if st.seq != my_seq:
                    break
                await asyncio.sleep(0.25)
            if st.waiting.get(follow["sender"]) is follow:
                st.waiting.pop(follow["sender"], None)
            if st.seq != my_seq:  # 等的时候又来了新消息，交给新消息那次处理（TA 的新消息已经把这几句拼上了）
                if any(w["sender"] == follow["sender"] and w["t"] > follow["t"] for w in self._alive_wakes(st).values()):
                    return  # TA 接着叫了她：叫她那次会看到这几句
                if st.follow is None:
                    st.follow = follow
                return
            if follow.get("t", 0.0) <= st.seen_until:
                logger.info(f"smart_chime_in: {follow['name']} 这几句她上次回复时已经看过了，不再单独回: {follow['text'][:30]}")
                return
            conv_mgr = self.context.conversation_manager
            cid = await conv_mgr.get_curr_conversation_id(umo)
            conv = await conv_mgr.get_conversation(umo, cid) if cid else None
            if not conv:
                return
            logger.info(f"smart_chime_in: 接着聊，{follow['name']}({follow['sender']}) 多半在跟她说话: {follow['text'][:30]}")
            token = object()
            st.follows[token] = {"event": event, "sender": follow["sender"], "name": follow["name"],
                                 "text": follow["text"], "t": follow["t"], "also": []}
            event.set_extra("_chime_follow_token", token)
            event.set_extra("_chime_prev_spoke", st.last_spoke)
            event.set_extra("_chime_in", "follow")
            event.set_extra("_chime_follow", follow)
            st.last_spoke = time.time()
            st.partners[follow["sender"]] = time.time()
            yield event.request_llm(
                prompt=event.message_str or follow["text"],
                session_id=event.session_id,
                conversation=conv,
            )
            return

        if not text:  # 最后一条是纯图片，没法当作话头
            return
        # 长公告 / 贴过来的大段文字不插话（2026-11-13 555 贴了几千字的海斗更新日志 @全体成员，她看不懂，
        # 插话接到了半小时前女王大人的话上）。有人叫她照常回。
        at_all = any(isinstance(c, At) and str(c.qq) == "all" for c in event.get_messages())
        long_chars = self._c("long_post_chars", 300)
        if at_all or (long_chars > 0 and len(text) > long_chars):
            logger.info(f"smart_chime_in: 不插话（{'@全体成员' if at_all else f'{len(text)} 字的长文'}），话头: {text[:20]}")
            return
        now = time.time()
        # 打分看最近 window_seconds 秒、且是她上次说话之后的聊天，而不只是这一波
        since = max(now - self._c("window_seconds", 120.0), st.last_spoke)
        burst = [m for m in st.recent if m["t"] > since]
        new_count = min(new_count, len(burst))
        head = text[:20]
        cooldown = self._c("cooldown_seconds", 60.0)
        left = cooldown - (now - st.last_spoke)
        if left > 0:
            # 冷却完再看一眼（2026-11-09 哆啦a梦接着她的话说"说的就是你，你去看看autodl"，正赶上冷却，
            # 这条就再没人看）：冷却期间没新消息、她也没再说话，就照常打分决定说不说
            if not self._c("cooldown_recheck", True) or left > self._c("cooldown_recheck_max", 60.0):
                logger.info(f"smart_chime_in: 不插话（冷却中，还剩 {left:.0f}s），{len(burst)} 条，话头: {head}")
                return
            logger.info(f"smart_chime_in: 冷却中（还剩 {left:.0f}s），冷却完再看一眼，话头: {head}")
            spoke = st.last_spoke
            await asyncio.sleep(left + 0.5)
            if st.seq != my_seq or st.last_spoke != spoke:
                logger.info(f"smart_chime_in: 冷却完不用再看（{'又有新消息' if st.seq != my_seq else '她又说过话了'}），话头: {head}")
                return
            now = time.time()
            since = max(now - self._c("window_seconds", 120.0), st.last_spoke)
            burst = [m for m in st.recent if m["t"] > since]
            new_count = min(new_count, len(burst))
        while st.chime_times and now - st.chime_times[0] > 3600:
            st.chime_times.popleft()
        if len(st.chime_times) >= self._c("max_per_hour", 10):
            logger.info(f"smart_chime_in: 不插话（这小时已插话 {len(st.chime_times)} 次），话头: {head}")
            return
        if _ACTIVE_AGENT_RUNNERS.get(umo) is not None:
            logger.info(f"smart_chime_in: 不插话（正在回别人），话头: {head}")
            return

        p, why = self._score(burst, new_count)
        roll = random.random()
        if roll >= p:
            logger.info(f"smart_chime_in: 不插话 p={p:.2f} ({why}) roll={roll:.2f}，{len(burst)} 条，话头: {head}")
            return

        conv_mgr = self.context.conversation_manager
        cid = await conv_mgr.get_curr_conversation_id(umo)
        conv = await conv_mgr.get_conversation(umo, cid) if cid else None
        if not conv:
            return

        logger.info(f"smart_chime_in: 考虑插话 p={p:.2f} ({why})，{len(burst)} 条消息，话头: {text[:30]}")
        event.set_extra("_chime_prev_spoke", st.last_spoke)
        st.last_spoke = now
        st.chime_times.append(now)
        event.set_extra("_chime_in", True)
        yield event.request_llm(
            prompt=event.message_str,
            session_id=event.session_id,
            conversation=conv,
        )

    @filter.on_llm_request(priority=sys.maxsize - 2)  # 在内置群聊上下文（priority 0）拿走记录之前
    async def wake_catch_up(self, event: AstrMessageEvent, req: ProviderRequest):
        """排完队真要回了：同一个人后来又叫了她，这次交给后面那次一起回；否则加几句提醒。"""
        if not event.get_group_id() or event.get_extra("_chime_in"):
            return
        token = event.get_extra("_chime_wake_token")
        st = self._groups[event.unified_msg_origin]
        try:
            wakes = self._alive_wakes(st)
            info = wakes.get(token)
            if info is None:
                return
            newer = [w for tok, w in wakes.items() if tok is not token and w["sender"] == info["sender"]
                     and w["t"] > info["t"]]
            if newer and time.time() - info["t0"] < self._c("catch_up_max_seconds", 30.0):
                self._pass_on(st, token, max(newer, key=lambda w: w["t"]))
                # 这条留在群聊记录里（内置上下文还没拿走），后面那次会看到
                event.is_at_or_wake_command = False
                event.stop_event()
                logger.info(f"smart_chime_in: {info['name']} 排队时又叫了她，这次不单独回，交给后面那次一起回")
                return
            wakes.pop(token, None)
            if not self._c("wake_notes", True):
                return
            others = []
            for w in wakes.values():
                if w["sender"] != info["sender"] and w["name"] not in others:
                    others.append(w["name"])
            unseen = self._unseen(st, info["sender"], info["t0"])
            notes = ""
            if info["earlier"]:
                texts = "、".join(f"「{t}」" for t in info["earlier"][-3:])
                notes += MERGED_NOTE.format(name=info["name"], texts=texts)
            if info.get("unanswered"):
                texts = "、".join(f"「{t}」" for t in info["unanswered"][-3:])
                notes += UNANSWERED_NOTE.format(name=info["name"], texts=texts)
            if others:
                notes += OTHERS_NOTE.format(names="、".join(others), name=info["name"])
            if unseen:
                notes += UNSEEN_NOTE.format(name=info["name"])
            if info.get("also"):
                notes += ALSO_NOTE.format(who="、".join(info["also"]))
            waiting = self._waiting_for_her(st, info["sender"], set(others) | set(info.get("also") or []))
            if waiting:
                notes += WAITING_NOTE.format(who="、".join(f"{n}（「{'」「'.join(ts)}」）" for n, ts in waiting))
            if notes:
                req.system_prompt = (req.system_prompt or "") + notes
                why = [x for x, on in (("前面也叫过", info["earlier"]), ("前面那条还没回", info.get("unanswered")),
                                       ("别人在排队", others),
                                       ("TA 没看到上一条", unseen), ("排队时也有人接着说", info.get("also")),
                                       ("她上一条之后也有人在跟她说：" + "、".join(n for n, _ in waiting), waiting)) if on]
                logger.info(f"smart_chime_in: 回 {info['name']} 前的提醒：{'、'.join(why)}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"smart_chime_in: 回之前再看一眼出错 {exc!r}")

    @staticmethod
    def _alive_follows(st: GroupState) -> dict:
        now = time.time()
        for tok, info in list(st.follows.items()):
            ev = info["event"]
            gone = now - info["t"] > 180
            try:
                gone = gone or ev.is_stopped()
            except Exception:  # noqa: BLE001
                pass
            if gone:
                st.follows.pop(tok, None)
        return st.follows

    @filter.on_llm_request(priority=sys.maxsize - 2)  # 在内置群聊上下文（priority 0）拿走记录之前
    async def follow_catch_up(self, event: AstrMessageEvent, req: ProviderRequest):
        """排完队真要"接着聊"了（2026-11-03 群里聊得热、模型又卡，她一条条回一分多钟前的话）：
        后面又有人在排队等她（接着聊或叫她）→ 这次不单独回，交给最新那次一起看（群聊记录里都在）；
        等太久、群里早聊过去了 → 不回了。"""
        if not event.get_group_id() or event.get_extra("_chime_in") != "follow":
            return
        st = self._groups[event.unified_msg_origin]
        try:
            follows = self._alive_follows(st)
            info = follows.pop(event.get_extra("_chime_follow_token"), None)
            if info is None:
                return
            newer = [w for w in follows.values() if w["t"] > info["t"]]
            newer += [w for w in self._alive_wakes(st).values() if w["t"] > info["t"]]
            prev = float(event.get_extra("_chime_prev_spoke") or 0.0)
            if newer and self._c("follow_merge", True):
                target = max(newer, key=lambda w: w["t"])
                also = target.setdefault("also", [])
                for name in info.get("also", []) + [info["name"]]:
                    if name not in also and name != target.get("name"):
                        also.append(name)
                event.is_at_or_wake_command = False
                event.stop_event()
                logger.info(f"smart_chime_in: {info['name']} 接着说的这条排队时后面又有人等她回（{target['name']}），"
                            f"不单独回，交给后面那次一起看")
                return
            age = time.time() - info["t"]
            after = sum(1 for m in st.recent if m["t"] > info["t"])
            if age > self._c("follow_stale_seconds", 40.0) and after >= self._c("follow_stale_messages", 6):
                event.is_at_or_wake_command = False
                event.stop_event()
                st.last_spoke = prev
                logger.info(f"smart_chime_in: {info['name']} 接着说的「{info['text'][:20]}」等了 {age:.0f}s，"
                            f"群里又聊了 {after} 条，话题已经过去了，不回")
                return
            if info.get("also") and self._c("wake_notes", True):
                req.system_prompt = (req.system_prompt or "") + ALSO_NOTE.format(who="、".join(info["also"]))
                logger.info(f"smart_chime_in: 回 {info['name']} 时一起看：{'、'.join(info['also'])}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"smart_chime_in: 接着聊回之前再看一眼出错 {exc!r}")

    @filter.on_llm_request(priority=-5)  # 在内置群聊上下文（priority 0）之后
    async def show_late_messages(self, event: AstrMessageEvent, req: ProviderRequest):
        """叫她之后、开始回复之前新来的群消息，也放进这一轮给她看。"""
        if not event.get_group_id():
            return
        st = self._groups[event.unified_msg_origin]
        st.seen_until = time.time()
        st.wake_pending.pop(event.get_extra("_chime_wake_token"), None)
        # 只在有人叫她时补：插话/接着聊可能输出 [SKIP]，那样拿走的记录就丢了
        if not self._c("late_messages", True) or not event.is_at_or_wake_command or event.get_extra("_chime_in"):
            return
        lines = await self._take_late_records(event)
        if lines:
            req.extra_user_content_parts.append(TextPart(text=LATE_NOTE.format(lines="\n".join(lines))))
            logger.info(f"smart_chime_in: 回复前又来了 {len(lines)} 条群消息，一起给她看")

    @filter.on_llm_request(priority=-10)
    async def frame_request(self, event: AstrMessageEvent, req: ProviderRequest):
        mode = event.get_extra("_chime_in")
        if not mode:
            return
        follow = event.get_extra("_chime_follow")
        if mode == "follow" and follow:
            note = FOLLOW_NOTE.format(partner=follow["name"], text=follow["text"])
            st = self._groups[event.unified_msg_origin]
            if self._c("wake_notes", True) and self._unseen(st, follow["sender"], follow.get("t0", follow["t"])):
                note += UNSEEN_NOTE.format(name=follow["name"])
                logger.info(f"smart_chime_in: {follow['name']} 接着说的是在她上一条发出去之前打的，提醒别重复")
        else:
            st = self._groups[event.unified_msg_origin]
            sender = event.get_sender_name() or "群友"
            other = self._talking_to(st, str(event.get_sender_id()))
            hint = TALKING_TO_HINT.format(sender=sender, other=other) if other else ""
            note = CHIME_IN_NOTE.format(sender=sender, hint=hint)
        # 放进 system prompt：不会被写进对话历史
        req.system_prompt = (req.system_prompt or "") + "\n\n" + note

    @filter.on_llm_response(priority=100000)
    async def drop_skip(self, event: AstrMessageEvent, resp: LLMResponse):
        if not event.get_extra("_chime_in"):
            return
        text = (getattr(resp, "completion_text", "") or "").strip()
        if text and "[SKIP]" not in text.upper() and text.upper() != "SKIP" and not DEFLECT.search(text):
            return
        # 她选择不说：不发送、不写历史，也不算进冷却
        logger.info(f"smart_chime_in: 佳树觉得插不上话，这次不说（{text[:30]}）")
        st = self._groups[event.unified_msg_origin]
        st.last_spoke = float(event.get_extra("_chime_prev_spoke") or 0.0)
        if event.get_extra("_chime_in") == "follow":
            # 原来不是在跟她说话：别再把这个人的消息当成接着聊
            follow = event.get_extra("_chime_follow") or {}
            st.partners.pop(follow.get("sender"), None)
        elif st.chime_times:
            st.chime_times.pop()
        resp.completion_text = ""
        event.clear_result()
        event.stop_event()

    @filter.on_decorating_result(priority=100002)
    async def mark_reply_start(self, event: AstrMessageEvent):
        chain = getattr(event.get_result(), "chain", None)
        if event.get_group_id() and chain:
            self._groups[event.unified_msg_origin].reply_start = (time.time(), str(event.get_sender_id()))
            text = "".join(c.text for c in chain if isinstance(c, Plain))
            if ASKED.search(text):
                event.set_extra("_chime_asked", True)

    @filter.after_message_sent()
    async def mark_spoke(self, event: AstrMessageEvent):
        if event.get_group_id():
            st = self._groups[event.unified_msg_origin]
            st.last_spoke = time.time()
            st.reply_end = (time.time(), str(event.get_sender_id()))
            sender = str(event.get_sender_id())
            # 她自己插的话：最后说话的人并没有在跟她聊，不算"接着聊"的对象
            # （2026-11-04 插了一句之后，对方接下来跟别人说的话全被当成在跟她说）；
            # 只有她插话时问了 TA 什么，TA 接下来的话才可能是在回她
            chimed = event.get_extra("_chime_in") is True
            if sender and sender != str(event.get_self_id()) and (not chimed or event.get_extra("_chime_asked")):
                st.partners[sender] = time.time()
