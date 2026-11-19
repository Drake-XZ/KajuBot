"""佳树的说话习惯：几条管"怎么说话"的小规则 + 写手（要点卡 → 本地写手照卡写）。

- 聊天节奏（rhythm）：按句号等标点分行，去掉句尾句号，默认不在逗号处拆句；可配置拆分长句。
  发送前和存进历史前各处理一次。
- 被纠正提醒（rebuttal）：对方引用/接着她的话在纠正她时，提醒她先接住对方的意思、别沿用原来的说法。
  提醒放在所有提示的最后（离她作答最近）。
- 说具体、说连贯（concrete，1.6.0）：聊一部作品的时候（memory_weight 给了珍藏的内容、刚读了文件/看了视频、或者在问一部作品的看法），
  提醒"用具体的情节、人物、原话说看法，句和句接得上"，这一轮不在逗号处拆消息。
- 写手（rewrite 这一节配置）：主模型写草稿（或 main_role=brain 时只出指导）→ Gemini 整理成第四版要点卡
  （场合/对象/局面/要说到的 + 心情行）→ 回复器 / 本地写手照卡写 → 核对（编了事 / 丢了要紧信息 / 叫错人就再写）；
  只发写手写的话（writer_only）。私聊来消息或群里有人叫她时先把写手加载上（预热）。
  2026-11-18 删了第一版卡（card_format=v1，DeepSeek 抽旧格式卡配 4B 的 r003）和“规划器出卡”（card_source=planner）。
- 2026-11-13 删掉了早就关着的几条：开头少用"诶"、开头别老"好的…"、说话要有变化、说大白话、句子说短、带称呼和语气词，
  还有看草稿改写的旧"重说"模式（kaju-rewriter）。兄长的规矩：说法交给模型和训练数据，不靠提示词和正则改她的话。
- 先回应，别当解说员（respond）：对方在抱怨发泄时提醒先哄一句、站到 TA 那边，原因办法放后面；
  她最近第一句在描述/点评对方（"女王大人这会儿是真上火了呀""学姐这是……呀"）时也提醒，并引用那句。
- 深夜催睡（bedtime）：深夜可以关心早点睡，但同一个人一晚只催一次左右，同一个群刚催过别人也先不催。
  深夜按 AstrBot 配置的时区（北京时间，和她看到的时间一致）算，不按服务器本机时间。
"""

from __future__ import annotations

from ..body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import datetime as dt
import json
import os
import random
import re
import time
import contextvars
import zoneinfo
from collections import defaultdict, deque
from kaju_core.slots import slot_model  # noqa: E402  每项工作一格（11-18）
from kaju_core import parts, paths  # noqa: E402
from kaju_core.voice import asks, brain, card, concrete, emoji, longctx, replyer, rewrite, routine  # noqa: E402
from kaju_core.voice.respond import build_note as respond_note  # noqa: E402
from kaju_core.voice.rhythm import NOTE as RHYTHM_NOTE  # noqa: E402
from kaju_core.voice.rhythm import restyle  # noqa: E402
from kaju_core.voice.routine import clean_reply, text_of  # noqa: E402
from kaju_core.voice import records  # noqa: E402
from kaju_core.voice.rebuttal import build_note as rebuttal_note  # noqa: E402
from kaju_core.voice.rebuttal import is_rebuttal, quoted_own  # noqa: E402

# 这一轮写手看的长前文（rewrite.long_ctx 开着时，重说那一轮里设上；_write_from_card 有它就用它，没有就用短的）。
# 用 ContextVar 不用 self：几个人同时说话时各轮互不串（2026-11-17 第 7 轮：写手多看聊天）。
_WRITER_CTX: contextvars.ContextVar = contextvars.ContextVar("kaju_writer_ctx", default=None)
# 回复器看的前文（rewrite.replyer = api 时，rewrite_snapshot 里按 replyer_ctx_group / replyer_ctx_private 取；没有就用写手那份）
_REPLYER_CTX: contextvars.ContextVar = contextvars.ContextVar("kaju_replyer_ctx", default=None)
# 主模型当大脑时（rewrite.main_role = "brain"）这一轮的指导 {"brain": …}：回复器要用、重出卡时知道不能再问。一样用 ContextVar，各轮不串。
# （11-18 整理：删了“规划器出卡”B 那条路和第一版卡 v1，线上只剩第四版卡这一种）
_PLAN: contextvars.ContextVar = contextvars.ContextVar("kaju_plan", default=None)
# 这一轮群聊怎么来的（brain.how_came："插话" / "接着聊" / ""），给回复器（11-18 晚）
_HOW: contextvars.ContextVar = contextvars.ContextVar("kaju_how", default="")

PLUGIN_NAME = "astrbot_plugin_kaju_style"


# ---- 深夜催睡
NAG_WORDS = re.compile(r"早点睡|早睡|快睡|去睡|睡觉|睡吧|该睡|熬夜|休息|晚安|别太晚|不早了")


USER_SLEEPY = re.compile(r"睡|困|晚安|熬夜|失眠|累")

# Gemini 全挂了时让 DeepSeek 写的通知（2026-11-13 兄长：“由 DeepSeek 用佳树的 QQ、抖音给我发消息告知”）。
# 这是给兄长的故障通知，不是她平时说话；平时的话只由写手写。
GEMINI_DOWN_SYSTEM = "你是温水佳树（《败犬女主太多了！》），兄长大人的妹妹，这会儿在给兄长大人发私聊消息。"
GEMINI_DOWN_PROMPT = ("你这边负责想要说什么的 Gemini 接口刚才没答上来：{what}"
                      "在它恢复之前，你在群里不说话、私聊也没法回。用一两句话照实告诉兄长大人这件事（别说成别的情况），"
                      "请他看一下 Gemini 的 key。只输出要发的话本身。")


def down_summary(why: str, n_keys: int) -> str:
    """GeminiDown 的原因（“… 1:TimeoutError 2:HTTPError …”）→ 给 DeepSeek 的一句实情（不带地址和 key）。
    2026-11-14：原来一律说“N 个 key 都连不上”，其实常常是有的太慢、有的报错，或者根本是主模型那一路没答上来。"""
    import re as _re
    kinds = _re.findall(r"(?<![\w.])\d+:([A-Za-z_]+)", why or "")
    if not kinds:
        if why == "main":
            return "写回复的主模型和它的几个后备都没答上来（多半是中转站太慢或在报错）。"
        return f"{n_keys or '几'}个 Gemini 的 key 都没答上来。"
    slow = sum(1 for k in kinds if "Timeout" in k)
    bad = len(kinds) - slow
    parts = ([f"{slow}个回得太慢、等不及" ] if slow else []) + ([f"{bad}个报错或连不上"] if bad else [])
    return f"{len(kinds)}个 Gemini 的 key 都试了：" + "，".join(parts) + "。"
# 主模型（连后备）全失败时 AstrBot 自己拼的报错（tool_loop_agent_runner / astr_agent_run_util）
MODEL_ERROR = re.compile(r"^(LLM 响应错误|All chat models|All available chat models|Error occurred during AI execution|"
                         r"No messages remain for the LLM)")


class StyleMind:
    """KajuStyle 的逻辑（AstrBot 外壳在 plugins\\kaju_style\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        self._rng = random.Random()
        # 会话 -> 最近回复（对话历史里有就优先用历史）
        self._replies: dict[str, deque] = defaultdict(lambda: deque(maxlen=8))
        # 会话 -> 最近被纠正的时间
        self._rebutted: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        self._rw_warm = 0.0  # 上次预热写手的时间
        self._gem_warm = 0.0  # 上次叫醒出卡用的 Gemini 的时间
        self._gd_told = 0.0  # 上次告诉兄长 Gemini 全挂了的时间

        folder = paths.self_dir(PLUGIN_NAME)
        os.makedirs(folder, exist_ok=True)
        self._bed_path = os.path.join(folder, "bedtime.json")
        try:
            with open(self._bed_path, encoding="utf-8") as f:
                self._bed: dict = json.load(f)
        except FileNotFoundError:
            self._bed = {}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_style: 读不了催睡记录: {exc}")
            self._bed = {}
        self._bed.setdefault("users", {})
        self._bed.setdefault("groups", {})
        try:
            self._tz = zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))
        # 线上每一次重说都原样记下（records.py）：以后出题、改写、攒训练数据用和线上一样的输入
        self._rec = records.Recorder(self, os.path.join(folder, "rewrites"), self._tz)
        self._rec.install()
        # 会话 -> 她最近发过的 50 句（发之前查套路用，routine.py）；重启后第一次用时从重说记录里读回来
        self._sent: dict[str, deque] | None = None

    def _sent_of(self, umo: str) -> deque:
        if self._sent is None:
            self._sent = defaultdict(lambda: deque(maxlen=routine.WINDOW))
            try:
                for k, v in routine.load_sent(self._rec.folder).items():
                    self._sent[k].extend(v)
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_style: 没读回最近发过的话（查套路从空的开始） {type(e).__name__}: {e}")
        return self._sent[umo]

    def _routine_hits(self, event: Turn, new: str, mode: str) -> list[str]:
        """这句撞了哪些套路（和旧话太像 / 开头连着一样 / 书面套路）；顺手记进重说记录。出错当没撞。"""
        try:
            hits = routine.check(new, list(self._sent_of(event.unified_msg_origin)))
            self._rec.note("routine", {"new": new, "hits": hits, "mode": mode})
            return hits
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 查套路出错（当没撞） {type(e).__name__}: {e}")
            return []

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)

    def _sec(self, name: str) -> dict:
        sec = self.config.get(name)
        return sec if isinstance(sec, dict) else {}

    # ------------------------------------------------------------ 深夜催睡
    def _is_late(self) -> bool:
        cfg = self._sec("bedtime")
        if not cfg.get("enable", True):
            return False
        start = int(cfg.get("late_start_hour", 23))
        end = int(cfg.get("late_end_hour", 5))
        h = dt.datetime.now(self._tz).hour
        return h >= start or h < end if start > end else start <= h < end

    def _night_key(self) -> str:
        # 往前推 12 小时，23 点和凌晨 2 点算同一个"晚上"
        return (dt.datetime.now(self._tz) - dt.timedelta(hours=12)).strftime("%Y-%m-%d")

    def _bedtime_note(self, event: Turn) -> str:
        cfg = self._sec("bedtime")
        uid = str(event.get_sender_id() or "")
        gid = str(event.get_group_id() or "")
        rec = self._bed["users"].get(uid)
        nagged = int(rec.get("count", 0)) if rec and rec.get("night") == self._night_key() else 0
        group_gap = float(cfg.get("group_gap_minutes", 30)) * 60
        group_recent = gid and time.time() - float(self._bed["groups"].get(gid, 0)) < group_gap

        if USER_SLEEPY.search(event.message_str or ""):
            return (
                "【深夜关心】对方自己提到了困/睡觉/熬夜，可以自然回应；"
                + ("你今晚已经叮嘱过TA早点睡了，这次简短一句就好，别再长篇唠叨。" if nagged else "简单关心一句就好。")
            )
        if (nagged >= int(cfg.get("max_per_night", 1)) or group_recent
                or self._rng.random() >= float(cfg.get("nag_chance", 0.3))):
            return (
                "【深夜关心】现在虽然很晚了，但这次回复不要催对方睡觉、不要提休息/熬夜/晚安/不早了，"
                "就正常接着话题聊。"
                + ("（你今晚已经叮嘱过TA了，再说就唠叨了。）" if nagged else "")
            )
        return "【深夜关心】现在很晚了，如果自然的话可以在回复末尾顺带轻轻关心一句早点休息，也可以不提；主要还是正常聊天。"

    def _record_nag(self, event: Turn) -> None:
        uid = str(event.get_sender_id() or "")
        gid = str(event.get_group_id() or "")
        night = self._night_key()
        rec = self._bed["users"].get(uid)
        if not rec or rec.get("night") != night:
            rec = {"night": night, "count": 0}
        rec["count"] = int(rec.get("count", 0)) + 1
        rec["last"] = time.time()
        self._bed["users"][uid] = rec
        if gid:
            self._bed["groups"][gid] = time.time()
        # 只留今晚的，文件不会越来越大
        self._bed["users"] = {k: v for k, v in self._bed["users"].items() if v.get("night") == night}
        try:
            with open(self._bed_path, "w", encoding="utf-8") as f:
                json.dump(self._bed, f, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_style: 存催睡记录失败: {exc}")

    # ------------------------------------------------------------ 请求前的提醒
    async def remind(self, event: Turn, req: Request):
        if self._is_late():
            req.system_prompt = (req.system_prompt or "") + "\n\n" + self._bedtime_note(event)

    def _recent_replies(self, event: Turn, req: Request) -> list[str]:
        """Her recent replies in this conversation, oldest first (history preferred over our own log)."""
        from_ctx = [text_of(m.get("content")) for m in (req.contexts or [])
                    if isinstance(m, dict) and m.get("role") == "assistant"]
        from_ctx = [t for t in from_ctx if t.strip() and not t.strip().startswith("[SKIP")]
        mine = list(self._replies[event.unified_msg_origin])
        return from_ctx[-8:] if len(from_ctx) >= len(mine) else mine

    def _rebuttal(self, event: Turn, req: Request) -> str:
        """The 被纠正 note for this request ('' if none). Worked out once per event."""
        cached = event.get_extra("kaju_style_rebuttal")
        if cached is not None:
            return cached
        note = ""
        cfg = self._sec("rebuttal")
        if cfg.get("enable", True):
            replies = self._recent_replies(event, req)
            last = clean_reply(replies[-1]) if replies else ""
            quoted = quoted_own(event, req)
            if is_rebuttal(event.message_str or "", quoted, last):
                times = self._rebutted[event.unified_msg_origin]
                now = time.time()
                times.append(now)
                window = float(cfg.get("window_minutes", 120)) * 60
                note = rebuttal_note(clean_reply(quoted) if quoted else quoted, last,
                                     sum(now - t <= window for t in times))
        event.set_extra("kaju_style_rebuttal", note)
        return note

    async def remind_rhythm(self, event: Turn, req: Request):
        cfg = self._sec("rhythm")
        if cfg.get("enable", True) and cfg.get("prompt_note", True):
            req.system_prompt = (req.system_prompt or "") + RHYTHM_NOTE

    def _concrete(self, event: Turn) -> bool:
        """This turn is about a work (cached per event)."""
        cached = event.get_extra("kaju_style_concrete")
        if cached is not None:
            return bool(cached)
        on = bool(self._sec("concrete").get("enable", True)) and concrete.should_fire(
            event.message_str or "", bool(event.get_extra("memory_weight_shelf_offered")),
            bool(event.get_extra("kaju_docs_read")))
        if on and event.get_extra("_kaju_felt"):
            # 这一轮的视频 / 歌她是带着感受看完的（全模态那条路）：手里拿的是自己的感觉，
            # 再催"用具体情节来说"就又变成把内容讲一遍（2026-11-11 兄长定：这种时候不提醒）
            on = False
        event.set_extra("kaju_style_concrete", on)
        return on

    async def remind_concrete(self, event: Turn, req: Request):
        if self._concrete(event):  # 聊作品：说具体、说连贯
            req.system_prompt = (req.system_prompt or "") + concrete.NOTE
            self.log.info(f"kaju_style: 聊作品，说具体 {event.unified_msg_origin}")

    def _titles(self, event: Turn) -> tuple[str, tuple[str, ...]]:
        """(title for the sender, every registered title) from address_book's 称呼表."""
        path = os.path.join(paths.self_dir("address_book"), "addresses.json")
        try:
            with open(path, encoding="utf-8") as f:
                book = json.load(f)
        except Exception:  # noqa: BLE001
            book = {}
        sender = str(event.get_sender_id() or "")
        mine = ""
        addr = self.body.find("address_of")  # 称呼簿算的称呼（兄长大人本人 / 名字+学长学姐 / 特别称呼）
        if addr is not None:
            try:
                mine = str(addr.address_of(sender, event.get_sender_name() or "") or "")
            except Exception:  # noqa: BLE001
                mine = ""
        mine = mine or (book.get(sender) or {}).get("address") or ("对方" if event.get_group_id() else "兄长大人")
        every = tuple(str(v.get("address") or "") for v in book.values() if isinstance(v, dict))
        return mine, tuple(t for t in every if t)

    async def remind_respond(self, event: Turn, req: Request):
        if not self._sec("respond").get("enable", True):
            return
        title, _ = self._titles(event)
        note = respond_note(event.message_str or "", self._recent_replies(event, req), title)
        if note:
            req.system_prompt = (req.system_prompt or "") + note
            self.log.info(f"kaju_style: 先回应提醒 {event.unified_msg_origin} -> {note[-60:]!r}")

    async def remind_rebuttal(self, event: Turn, req: Request):
        note = self._rebuttal(event, req)
        if note:
            req.system_prompt = (req.system_prompt or "") + note
            self.log.info(f"kaju_style: 被纠正提醒 {event.unified_msg_origin} -> {note[:80]!r}")

    # ------------------------------------------------------------ 问之前先听懂（asks.py）
    # ------------------------------------------------------------ 主模型当大脑（rewrite.main_role，2026-11-17 兄长定）
    def _brain_on(self) -> bool:
        """rewrite.main_role = "brain"：主模型不扮佳树写草稿，只当规划器（大脑）出标签式的指导（brain.py），
        说法全交给写手。默认 "draft"（原来那样）。只在写手开着时有用。"""
        return str(self._sec("rewrite").get("main_role", "draft")) == "brain"

    async def brain_request(self, event: Turn, req: Request):
        """别的插件都加完材料之后：把人设里扮佳树说话的那一段换成大脑的要求（brain.swap_persona），这一轮记上 _ks_brain。
        这一轮不重说（私聊里写手没开、插件自己发起的请求）就不换。"""
        if not self._brain_on() or not self._rewrite_on(event):
            return
        try:
            rcfg = self._sec("rewrite")
            sp = req.system_prompt or ""
            separate = str(rcfg.get("emoji", "brain")) == "separate"
            meme_cats = None
            if separate:  # 表情包单独挑（emoji.py）：那一大段说明不给大脑，留给回复写好以后挑表情包的那一格
                sp, block = emoji.cut_block(sp)
                event.set_extra("_ks_meme_block", block or None)
                meme_cats = emoji.categories(block) or None  # 只告诉大脑她能发、怎么点名（11-19）
            event.set_extra("_ks_how", brain.how_came(sp))  # 被叫 / 插话 / 接着聊：回复器也要知道（11-18 晚）
            self._fix_ctx_clock(req)  # 群聊上下文的时间是本机时钟，改成北京时间（11-18 晚，本机快 3 小时）
            sp = brain.adapt_group_notes(sp)  # 插话 / 接着聊的长说明换成一行“这一轮怎么来的”（11-18）
            req.system_prompt = brain.swap_persona(sp, bool(rcfg.get("brain_character", False)), meme=not separate,
                                                   meme_cats=meme_cats)
            event.set_extra("_ks_brain", True)
            event.set_extra("_ks_brain_req", req)  # 想的时候群里又来了消息就拿它重想一遍（_replan）
        except Exception as e:  # noqa: BLE001  换不成就照原来写草稿
            self.log.warning(f"kaju_style: 换成大脑的提示没成（照原来写草稿） {type(e).__name__}: {e}")

    def _asks_on(self, event: Turn) -> bool:
        if event.get_extra("_ks_brain"):  # 大脑出的是 JSON 指导，不是她要说的话：问句把关不管
            return False
        cfg = self._sec("asks")
        if not cfg.get("enable", True):
            return False
        if event.get_group_id() and not cfg.get("groups", False):
            return False
        return True

    async def asks_snapshot(self, event: Turn, req: Request):
        """记下这一轮的聊天上下文，回复回来时拿去把关。"""
        if not self._asks_on(event):
            return
        try:
            quote = ""
            for c in event.get_messages() or []:
                if type(c).__name__ == "Reply":  # 引用
                    quote = " ".join(str(getattr(c, "message_str", "") or "").split())[:200]
                    break
            lines = asks.context_lines(req.contexts, event.message_str or req.prompt or "", quote)
            event.set_extra("_ks_asks", lines)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 问句把关记上下文出错 {type(e).__name__}: {e}")

    async def _judge(self, prompt: str) -> str:
        cfg = self._sec("asks")
        pid = await slot_model(self.body, "fast", str(cfg.get("provider_id", "") or "").strip())  # 每项工作一格（slots.py）
        if not pid:
            return ""
        return await self.body.generate(pid, prompt, asks.SYSTEM, timeout=float(cfg.get("timeout", 6)))

    async def asks_check(self, event: Turn, resp: Answer):
        """回复里认真问了对方刚说过答案的事：发之前删掉那一行（出错、超时就照原样发）。"""
        lines = event.get_extra("_ks_asks")
        if not lines or getattr(resp, "tools_call_name", None) or event.get_extra("_ks_brain"):
            return
        event.set_extra("_ks_asks", None)  # 一轮只看一次
        reply = getattr(resp, "completion_text", "") or ""
        if not asks.question_lines(reply):
            return
        t0 = time.time()
        try:
            drop = asks.parse(await self._judge(asks.build_prompt(lines, reply)), reply)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 问句把关没做成（照原样发） {type(e).__name__}: {e}")
            return
        if not drop:
            return
        new = asks.drop_lines(reply, drop)
        if new is None or new == reply:
            return
        resp.completion_text = new
        event.set_extra("_ks_asks_dropped", drop)
        self.log.info(f"kaju_style: 问了他刚说过的，删掉 {drop}（{time.time() - t0:.1f}s）")

    async def asks_history(self, event: Turn, run_context, response: Answer):
        """存进历史的那份在回复钩子之前就写好了：也删掉，免得下一轮她以为自己问过。"""
        drop = event.get_extra("_ks_asks_dropped")
        if not drop:
            return
        try:
            msgs = run_context.messages
            if not msgs or msgs[-1].role != "assistant":
                return
            msg = msgs[-1]
            if isinstance(msg.content, str):
                msg.content = asks.drop_lines(msg.content, drop) or msg.content
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if getattr(part, "type", None) == "text" and getattr(part, "text", None):
                        part.text = asks.drop_lines(part.text, drop) or part.text
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 历史里的多余问句没删掉: {e!r}")

    # ------------------------------------------------------------ 重说层（rewrite.py）
    def _address_of(self, qq: str, name: str) -> str:
        book = self.body.find("address_of")
        if book is None:
            return ""
        try:
            return str(book.address_of(qq, name) or "")
        except Exception:  # noqa: BLE001
            return ""

    def _rewrite_on(self, event: Turn) -> bool:
        cfg = self._sec("rewrite")
        if not cfg.get("enable", False):
            return False
        return bool(cfg.get("group", True)) if event.get_group_id() else bool(cfg.get("private", True))

    def _local_writer_on(self) -> bool:
        """rewrite.local_writer（默认开）：关了就不再用本机 Ollama 的写手（11-18 晚兄长：“我不想再用本地写手了”），
        所有要写她的话的地方都交给 API 回复器（rewrite.replyer = api），回复器没写成就这次不说；也不再预热写手。"""
        return bool(self._sec("rewrite").get("local_writer", True))

    async def rewrite_prewarm(self, event: Turn):
        """私聊来消息或群里有人叫她：先让 Ollama 把写手加载上（只加载、不生成），回复写好时它已经热了。"""
        if not self._rewrite_on(event) or (event.get_group_id() and not event.is_at_or_wake_command):
            return
        self._warm_gemini()
        if not self._local_writer_on():
            return
        if time.time() - self._rw_warm < 60:
            return
        self._rw_warm = time.time()
        cfg = self._sec("rewrite")
        base = str(cfg.get("base_url", "http://127.0.0.1:11435/v1")).rstrip("/").removesuffix("/v1")

        async def warm():
            import aiohttp

            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                    async with s.post(base + "/api/generate", json={"model": self._rw_model()}) as r:
                        await r.read()
            except Exception:  # noqa: BLE001 -- best effort; the real request just loads it itself
                pass

        asyncio.create_task(warm())

    @staticmethod
    def _ctx_end(recs: list[dict], event: Turn) -> tuple[int, dict | None]:
        """聊天记录里这一句在哪：返回 (这一句之前有几条, 这一句的记录或 None)。
        记录里存的是到达时的原话；戳一戳那种改写过的，原话包在里面。对不上就到这个人最后一句为止都算前文。"""
        sender = str(event.get_sender_id() or "")
        now = (event.message_str or "").strip()

        def same(x: str) -> bool:
            x = x.strip()
            return bool(x) and (x == now or x in now or (len(now) >= 6 and now[:30] in x))

        end = next((i for i in range(len(recs) - 1, -1, -1)
                    if str(recs[i].get("u")) == sender and same(str(recs[i].get("x") or ""))), None)
        if end is not None:
            # 连发合并（kaju_basics burst）：这一轮的话是他连着发的几条拼起来的，前面那几条也已经在这句里了，
            # 往回退到这一串的第一条，不然长前文里一条条出现一遍、最后一行又整串出现一遍（11-17 16:33 线上看到的）
            while end > 0 and str(recs[end - 1].get("u")) == sender and str(recs[end - 1].get("x") or "").strip() \
                    and str(recs[end - 1].get("x")).strip() in now:
                end -= 1
            return end, recs[end]
        return next((i + 1 for i in range(len(recs) - 1, -1, -1) if str(recs[i].get("u")) == sender), len(recs)), None

    def _long_ctx(self, event: Turn, title_of, sender_title: str, current: str,
                  max_lines: int = longctx.MAX_LINES, max_chars: int = longctx.MAX_CHARS,
                  me: str = "佳树", rich: bool = False) -> list[str] | None:
        """写手看的长前文（rewrite.long_ctx，默认关；2026-11-17 第 7 轮）：kaju_life 的聊天记录里这一句之前的
        最后十几行（带时间、换天插日期，格式见 longctx.py，和训练一字不差），最后一行是对方这一句（current，含引用）。
        拿不到记录 → None（用短的）。"""
        life = self.body.find("log_own")
        diary = getattr(life, "diary", None)
        if diary is None or not hasattr(diary, "recent"):
            return None
        gid = event.get_group_id()
        chat = f"g{gid}" if gid else f"p{event.get_sender_id()}"
        recs = diary.recent(chat, max_lines + 20)
        if not recs:
            return None
        end, hit = self._ctx_end(recs, event)
        now = dt.datetime.now(self._tz)
        day, hm = (hit.get("d"), hit.get("t")) if hit else (now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))
        if rich and hit:  # 这一句也带上引用 / @她 / 图片内容（引用从记录里拿，不用 current 后面拼的那段）
            current = longctx.marked({**hit, "x": (event.message_str or "").replace("\n", " / ")[:160]}, title_of, me)
        return longctx.from_log(recs[:end], title_of, current=(day, hm, sender_title, current),
                                max_lines=max_lines, max_chars=max_chars, me=me, rich=rich)

    def _group_ctx(self, event: Turn, title_of) -> list[str] | None:
        """群聊：这一句之前的几行群聊（称呼：话），和训练时群聊样本一样（build_layered.group_samples 取前 8 行）。

        2026-11-09：原来只用她自己那段对话的最后 3 条，群里别人之间的话抽卡 / 写手 / 核对都看不到——
        哆啦a梦说"感觉两个号比较合适"，她回"用两个号轮着换，最亏的是记忆断掉"，卡上抽成了"佳树用两个号轮着换"
        （重抽 6 次都这样；补上前 8 行群聊 6 次都抽对）。聊天记录在 kaju_life（按到达顺序）。拿不到 → None（用老办法）。"""
        try:
            n = int(self._sec("rewrite").get("group_ctx_lines", 8) or 0)
        except (TypeError, ValueError):
            n = 8
        life = self.body.find("log_own")
        diary = getattr(life, "diary", None)
        if n <= 0 or diary is None or not hasattr(diary, "recent"):
            return None
        recs = diary.recent(f"g{event.get_group_id()}", n + 20)
        if not recs:
            return None
        end, _ = self._ctx_end(recs, event)
        out = []
        for r in recs[max(0, end - n):end]:
            x = str(r.get("x") or "").strip().replace("\n", " / ")[:120]
            if not x:
                continue
            uid, name = str(r.get("u") or ""), str(r.get("n") or "")
            who = "佳树" if uid == "self" else (title_of(uid, name) or name or "身份不明")
            out.append(f"{who}：{x}")
        return out

    def _clock_shift(self) -> int:
        """北京时间（self._tz）比本机时钟快多少秒（本机快 3 小时就是 -10800）。"""
        now = dt.datetime.now(dt.timezone.utc)
        local = now.astimezone().utcoffset() or dt.timedelta(0)
        want = now.astimezone(self._tz).utcoffset() or dt.timedelta(0)
        return int((want - local).total_seconds())

    def _fix_ctx_clock(self, req: Request) -> None:
        """AstrBot 群聊上下文每行的“/HH:MM:SS]:”是本机时钟：这一轮的材料和历史里以前几轮的都挪成北京时间。"""
        shift = self._clock_shift()
        if not shift:
            return
        for p in (getattr(req, "extra_user_content_parts", None) or []):
            if isinstance(getattr(p, "text", None), str):
                p.text = brain.fix_clock(p.text, shift)
        for m in (getattr(req, "contexts", None) or []):
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, str):
                m["content"] = brain.fix_clock(c, shift)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = brain.fix_clock(part["text"], shift)

    def _arrived_since(self, event: Turn) -> list[dict]:
        """群聊：这一句之后、她还没开口之前，群里又来的消息（kaju_life 聊天记录；她自己说了话就到那为止）。"""
        life = self.body.find("log_own")
        diary = getattr(life, "diary", None)
        gid = event.get_group_id()
        if not gid or diary is None or not hasattr(diary, "recent"):
            return []
        recs = diary.recent(f"g{gid}", 40)
        if not recs:
            return []
        end, hit = self._ctx_end(recs, event)
        if hit is None:
            return []
        now = (event.message_str or "").strip()
        out = []
        for r in recs[end + 1:]:
            if str(r.get("u")) == "self":
                break
            x = str(r.get("x") or "").strip()
            if x and x not in now:
                out.append(r)
        return out

    async def _replan(self, event: Turn, plan: dict) -> dict:
        """想的时候群里又来了消息：带上新来的几条让大脑重想一遍（rewrite.replan，默认开；一轮只重想一次）。
        照 MaiBot 的 planner_replan。重想用主模型（走模型挑选和后备），没答上来 / 解析不了就用原来的指导。
        重想了还把新来的几条接到写手 / 回复器看的前文后面（不然它们只看到这句为止）。"""
        cfg = self._sec("rewrite")
        if not cfg.get("replan", True) or not event.get_group_id():
            return plan
        req = event.get_extra("_ks_brain_req")
        new = self._arrived_since(event)
        if req is None or not new:
            return plan
        title_of = lambda qq, name: self._address_of(qq, name) if qq else "身份不明"  # noqa: E731
        lines = [f"{r.get('t', '')} {title_of(str(r.get('u') or ''), str(r.get('n') or ''))}：{longctx._clean(longctx.marked(r, title_of, replyer.ME_LABEL))}".strip()
                 for r in new[-8:]]
        history = [(str(m.get("role")), text_of(m.get("content"))) for m in (req.contexts or [])[-6:]
                   if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
        extra = "".join(getattr(p, "text", "") or "" for p in (getattr(req, "extra_user_content_parts", None) or []))
        prompt = brain.replan_prompt((req.prompt or "") + extra, history, lines)
        t0 = time.time()
        try:
            pid = await self.body.model_id()
            raw = await self.body.generate(pid, prompt, req.system_prompt or "",
                                           timeout=float(cfg.get("replan_timeout", 45) or 45))
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 又来了 {len(new)} 条，重想没答上来（用原来的） {type(e).__name__}: {str(e)[:60]}")
            self._rec.note("replan", {"new": lines, "error": type(e).__name__})
            return plan
        again = brain.parse(raw)
        self._rec.note("replan", {"new": lines, "plan": again, "raw": None if again else (raw or "")[:300],
                                  "secs": round(time.time() - t0, 1)})
        if again is None:
            self.log.info(f"kaju_style: 又来了 {len(new)} 条，重想的解析不了（用原来的） {(raw or '')[:60]!r}")
            return plan
        self.log.info(f"kaju_style: 想的时候又来了 {len(new)} 条，重想了一遍（{time.time() - t0:.0f}s）"
                      f"{again.get('回不回', '')} {again.get('局面', '')[:40]!r}")
        short = [f"{title_of(str(r.get('u') or ''), str(r.get('n') or ''))}：{longctx._clean(longctx.marked(r, title_of, replyer.ME_LABEL))}" for r in new[-8:]]
        for var, add in ((_REPLYER_CTX, lines), (_WRITER_CTX, lines)):
            cur = var.get()
            if cur:
                var.set(list(cur) + add)
        event.set_extra("_ks_replan_ctx", short)
        return again

    async def _action_judge(self, event: Turn, plan: dict, ctx: list[str]) -> dict:
        """没人叫她的群聊轮次（插话 / 接着聊），大脑说要回：快模型（“fast”那一格）看最后 6 条聊天和大脑的想法，
        再定一次回不回（rewrite.action_judge，默认开；照 MaiBot 的 planner_action_judge）。说“不回”就把指导改成不回；
        出错 / 超时 / 认不出来照常回。被叫到的轮次不问。"""
        cfg = self._sec("rewrite")
        how = event.get_extra("_ks_how") or ""
        if not cfg.get("action_judge", True) or how not in ("插话", "接着聊"):
            return plan
        chat = list(_REPLYER_CTX.get() or ctx or [])[-6:]
        t0 = time.time()
        try:
            pid = await slot_model(self.body, "fast", str(cfg.get("action_judge_provider_id", "") or "").strip())
            if not pid:
                return plan
            out = await self.body.generate(pid, brain.judge_prompt(how, chat, replyer.plan_text(plan)), brain.JUDGE_SYSTEM,
                                           timeout=float(cfg.get("action_judge_timeout", 25) or 25))
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 发之前把关没答上来（照常回） {type(e).__name__}: {str(e)[:60]}")
            self._rec.note("judge", {"error": type(e).__name__})
            return plan
        verdict, why = brain.parse_judge(out)
        self._rec.note("judge", {"verdict": verdict, "why": why, "secs": round(time.time() - t0, 1),
                                 "raw": None if verdict else (out or "")[:200]})
        if verdict == "不回":
            self.log.info(f"kaju_style: 发之前把关说不回（{how}）：{why[:50]!r}")
            return {**plan, "回不回": "不回", "局面": f"{plan.get('局面', '')}（把关：{why}）"}
        return plan

    async def rewrite_snapshot(self, event: Turn, req: Request):
        """记下这一轮的上下文（按训练时的格式：称呼：话），回复回来时给重说层用。"""
        if not self._rewrite_on(event):
            return
        try:
            sender_title = self._titles(event)[0]
            title_of = lambda qq, name: (self._address_of(qq, name) if qq else  # noqa: E731
                                         ("身份不明" if event.get_group_id() else sender_title))
            # 多取几条再去掉系统文字和空行（rewrite.tidy_ctx），留最后 3 条，和训练时一样多
            ctx = rewrite.tidy_ctx([rewrite.label(m.get("role"), text_of(m.get("content")), title_of)
                                    for m in (req.contexts or [])[-8:]
                                    if isinstance(m, dict) and m.get("role") in ("user", "assistant")])[-3:]
            if event.get_group_id():
                lines = self._group_ctx(event, title_of)
                if lines is not None:
                    ctx = rewrite.tidy_ctx(lines)
            quote = next((m for p in (getattr(req, "extra_user_content_parts", None) or [])
                          if (m := rewrite.QUOTE.search(getattr(p, "text", "") or ""))), None)
            quoted = f"（引用{quote.group(1) or '身份不明'}：{quote.group(2).strip()[:80]}）" if quote else ""
            current = (event.message_str or "").replace("\n", " / ")[:160] + quoted
            ctx.append(f"{sender_title}：" + current)
            event.set_extra("_ks_rw_ctx", ctx)
            event.set_extra("_ks_rw_title", sender_title)
            if bool(self._sec("rewrite").get("long_ctx", False)):
                try:
                    long = self._long_ctx(event, title_of, sender_title, current)
                except Exception as e:  # noqa: BLE001  拿不到就用短的
                    long = None
                    self.log.info(f"kaju_style: 长前文没拿到（用短的） {type(e).__name__}: {e}")
                event.set_extra("_ks_rw_long", long)
            rcfg = self._sec("rewrite")
            if str(rcfg.get("replyer", "local")) == "api":
                # 回复器多看聊天（2026-11-18 兄长：“群聊改成跟人家一样，但是私聊可以相对少一点”）：
                # MaiBot 群聊参考最近 50 条（max_context_size）、私聊 75；这里群聊 50、私聊 20。本地写手照旧看 12 行（训练定死的）
                key, dflt = ("replyer_ctx_group", 50) if event.get_group_id() else ("replyer_ctx_private", 20)
                try:
                    n = int(rcfg.get(key, dflt) or 0)
                except (TypeError, ValueError):
                    n = dflt
                rc = None
                if n > 0:
                    try:
                        rc = self._long_ctx(event, title_of, sender_title, current, max_lines=n,
                                            max_chars=n * longctx.LINE_CHARS, me=replyer.ME_LABEL, rich=True)
                    except Exception as e:  # noqa: BLE001  拿不到就用写手那份
                        self.log.info(f"kaju_style: 回复器的前文没拿到（用写手那份） {type(e).__name__}: {e}")
                event.set_extra("_ks_rw_replyer", rc)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 重说层记上下文出错 {type(e).__name__}: {e}")

    def writer_only(self) -> bool:
        """只发写手写的话（2026-11-13 兄长：“我不希望写手会经过 DeepSeek”）：默认开（rewrite.writer_only）。
        回晚了、草稿带链接、出卡用不了、写手出错、核对没过……都不再退回发 DeepSeek 的草稿：
        核对几遍都没过就发写手最后那一遍，写手 / 卡根本没有就这次不说。"""
        return bool(self._sec("rewrite").get("writer_only", True))

    def _guard_fail_mode(self) -> str:
        """核对几遍都没过时（只发写手的话）："silent" = 这句不说（11-13 兄长定：写手编的“兄长大人好帅”核对拦了三遍，
        照发写手最后一遍就把它发出去了）；"send_writer" = 照发写手最后一遍；
        "busy"（默认，11-15 兄长：一直不说话会以为哪里坏了）= 先让核对模型只改被拦的那一处、再核对一次，
        还不行就照卡说一句“这会儿在忙，等下再好好回”。silent / busy 都先试改错（rewrite.guard_repair，默认开）。"""
        mode = str(self._sec("rewrite").get("guard_fail", "busy") or "busy")
        return mode if mode in ("silent", "send_writer", "busy") else "busy"

    def _mood_line(self) -> str:
        """给写手的心情那一行（决定 19，和训练同一个函数）；心情读不到就不加（写手照常写，训练里也有三成不带）。"""
        try:
            from kaju_core.heart.mood_line import mood_line
            h = parts.find("mood_snapshot")
            return mood_line(h.mood_snapshot()) if h is not None else ""
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 心情读不到（这次不带心情行） {type(e).__name__}: {e}")
            return ""

    def _mood_words(self, group: bool = False) -> str:
        """给回复器的心情底色（2026-11-18 兄长“照 anima 做”）：和 kaju_heart【此刻的心情】里“- 心情：”同一套词
        （heart.mood_words），按北京时间算困不困。读不到返回 ''（这一行就不加）。
        群聊不带“想黏人 / 想撒娇”那一维（11-19 凌晨群里“兄长大人又想起佳树了呢，佳树好开心~”：那是对一个人的，不是对一群人的）。"""
        try:
            from kaju_core.heart import heart
            h = parts.find("mood_snapshot")
            if h is None:
                return ""
            hour = dt.datetime.now(zoneinfo.ZoneInfo("Asia/Shanghai")).hour
            words = heart.mood_words(h.mood_snapshot()["mood"], hour)
            if group:
                words = [w for w in words if "黏人" not in w and "撒娇" not in w] or ["心情平常，挺平静的"]
            return "、".join(words)
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 心情底色读不到（这次不带） {type(e).__name__}: {e}")
            return ""

    def _warm_gemini(self) -> None:
        """出卡要用 Gemini：中转站空闲一阵后第一次要 30 多秒，消息一来先用一个字把它叫醒（DeepSeek 写草稿的这几秒正好用上）。"""
        if time.time() - self._gem_warm < 120:
            return
        self._gem_warm = time.time()

        async def warm():
            try:
                from kaju_core.senses import omni
                await omni.text("", "回一个字：好", timeout=60)
            except Exception:  # noqa: BLE001 - 叫不醒也没关系，真出卡时自己会换 key
                pass

        asyncio.create_task(warm())

    def _rw_model(self) -> str:
        return str(self._sec("rewrite").get("card_model", "kaju-writer-p4-8b-k"))

    async def _local_chat(self, system: str, user: str) -> str:
        import aiohttp

        cfg = self._sec("rewrite")
        # 8B 训练时关着思考（助手开头后有一段空的 <think></think>），不带 reasoning_effort 会写乱话（2026-11-11）。
        # 长短不卡（兄长：不要强行限制她的字数）：max_tokens 只是防卡死的兜底，远高于她正常会写的长度
        try:
            max_tokens = int(cfg.get("max_tokens", 1024) or 1024)
        except (TypeError, ValueError):
            max_tokens = 1024
        body = {"model": self._rw_model(), "temperature": 0.7, "top_p": 0.9, "max_tokens": max_tokens,
                "reasoning_effort": "none",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        url = str(cfg.get("base_url", "http://127.0.0.1:11435/v1")).rstrip("/") + "/chat/completions"
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("timeout", 10)))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, json=body, headers={"Authorization": "Bearer local"}) as r:
                r.raise_for_status()
                data = await r.json()
        return rewrite.clean_output(data["choices"][0]["message"]["content"])

    async def _extract_card(self, ctx: list[str], draft: str, kind: str, title: str, felt: bool = False) -> str:
        """第四版卡：Gemini（出卡那条链）把草稿整理成 场合/对象/局面/要说到的，再加心情行。拿不到就返回 ''；
        Gemini 的 key 全挂了抛 omni.GeminiDown。"""
        from kaju_core.senses import omni
        try:
            per_key = float(self._sec("rewrite").get("card_timeout_v4", 20) or 20)
        except (TypeError, ValueError):
            per_key = 20.0
        out, n = await omni.text(card.EXTRACT_V4, card.extract_prompt_v4(ctx, draft, kind, title, felt), timeout=per_key)
        g = card.parse_v4(out)
        if not g:
            self.log.info(f"kaju_style: Gemini 出的卡用不了（{out[:60]!r}）")
            return ""
        if n > 1:
            self.log.info(f"kaju_style: 出卡用的是第 {n} 个 Gemini key")
        return card.render_v4(kind, title, g, self._mood_line())

    async def _recheck_card(self, ctx: list[str], draft: str, kind: str, title: str, card_text: str,
                            new: str, why: str, felt: bool = False) -> str:
        """同一张卡写的话两次被核对拦下：把卡、写出来的话、核对的问题交回给出卡的，让它对着草稿看卡有没有错。
        卡有错 → 返回新卡；卡没错 / 看不懂 / Gemini 挂了 → 返回 ''（接着用原卡）。"""
        state = _PLAN.get()
        if state and state.get("brain"):  # 主模型当大脑出的卡：这一轮没法再问它一次，接着用原卡
            return ""
        from kaju_core.senses import omni
        cfg = self._sec("rewrite")
        try:
            per_key = float(cfg.get("card_timeout_v4", 20) or 20)
        except (TypeError, ValueError):
            per_key = 20.0
        try:
            out, _ = await omni.text(card.EXTRACT_V4,
                                     card.recheck_prompt_v4(ctx, draft, kind, title, card_text, new, why, felt),
                                     timeout=per_key)
        except Exception as e:  # noqa: BLE001  （GeminiDown 也在这：重抽不成就用原卡接着写）
            self.log.info(f"kaju_style: 带着问题重新出卡没成（用原卡） {type(e).__name__}: {e}")
            return ""
        verdict, g = card.parse_recheck_v4(out)
        if verdict == "keep":
            self.log.info("kaju_style: 重新看了卡，卡没错（用原卡再写）")
            return ""
        if verdict == "bad":
            self.log.info(f"kaju_style: 重新出的卡用不了（用原卡） {out[:60]!r}")
            return ""
        mood = next((x for x in card_text.splitlines() if x.startswith("心情：")), "")  # 心情行照旧
        return card.render_v4(kind, title, g, mood)

    async def _new_wording(self, ctx: list[str], draft: str, kind: str, title: str, felt: bool = False) -> tuple[str, str]:
        """(new text, card) — 先抽要点卡，再让本地写手照卡写。不能用时 new = ''。"""
        # felt 只在看完东西的回合才传（别的插件 / 测试换掉 _extract_card 时还是四个参数）
        card_text = await (self._extract_card(ctx, draft, kind, title, felt=True) if felt
                           else self._extract_card(ctx, draft, kind, title))
        if not card_text:
            return "", ""
        return await self._write_from_card(ctx, card_text, draft, title), card_text

    async def _write_from_card(self, ctx: list[str], card_text: str, draft: str, title: str) -> str:
        """本地写手照卡写一遍（每次采样都不一样，被核对拦下时可以拿同一张卡再写一次）。不像回复就返回 ''。
        第四版：提示和训练一字不差；写出来打转（卡死重复）也算没写好，交给"再写一次"。"""
        short_ctx = ctx
        ctx = _WRITER_CTX.get() or ctx  # 长前文（rewrite.long_ctx）：只换写手看的，出卡 / 核对照旧
        state = _PLAN.get()
        cfg = self._sec("rewrite")
        local_ok = self._local_writer_on()
        api = str(cfg.get("replyer", "local")) == "api"
        if api and ((state and state.get("brain")) or not local_ok):
            # 回复器（replyer.py，2026-11-18 兄长定照 MaiBot）：大脑的指导交给 API 大模型用她的口吻写；没写成就退回本地写手。
            # 本地写手关了（rewrite.local_writer = false，11-18 晚兄长：“我不想再用本地写手了”）：不是大脑那一轮的卡
            # （插件让她说话、草稿摘卡）也拆成指导交给回复器；回复器没写成就这次不说，不退回本地写手
            plan = state["brain"] if state and state.get("brain") else replyer.plan_from_card(card_text)
            if cfg.get("replyer_mood", True):  # 心情底色直接给回复器（11-18 量过：大脑写“情绪”时基本不看底色）
                tone = self._mood_words(group=(replyer.kind_of(card_text) or "私聊") == "群聊")
                plan = {**plan, "底色": tone} if tone else plan
            rctx = _REPLYER_CTX.get()  # 回复器自己那份（群聊 50 行 / 私聊 20 行）；没有就用写手那份、只看最后 10 行
            new, info = await replyer.reply(replyer.kind_of(card_text) or "私聊", title, list(rctx or ctx or []), plan,
                                            cfg, said=(short_ctx or [""])[-1] if short_ctx else "", log=self.log,
                                            ctx_lines=0 if rctx else 10, how=_HOW.get())
            info["底色"] = plan.get("底色", "")
            info["前文行数"] = len(rctx or (ctx or [])[-10:])
            self._rec.note("replyer", {**info, "text": new[:300]})
            if new and card.sane_v4(new, card_text, draft):
                self.log.info(f"kaju_style: 回复器写好（{info.get('model', '')[:24]}，{info.get('secs')}s）{new[:40]!r}")
                return new
            if not local_ok:
                self.log.info(f"kaju_style: 回复器没写成（{'；'.join(info.get('errors') or []) or '不像回复'}），本地写手关着")
                return ""
            self.log.info(f"kaju_style: 回复器没写成（{'；'.join(info.get('errors') or []) or '不像回复'}），换本地写手")
        if not local_ok:
            self.log.info("kaju_style: 本地写手关着、回复器也没开（rewrite.replyer 不是 api），这次写不了")
            return ""
        # 写手的系统提示要和它训练时一字不差：r6 及以前 v4，第 7 轮起 v5（去掉“不说你”）；rewrite.writer_system 和写手一起换
        system = card.SYSTEM_V5 if str(self._sec("rewrite").get("writer_system", "v4")) == "v5" else card.SYSTEM_V4
        new = card.fix_formal(await self._local_chat(system, card.write_prompt_v4(ctx, card_text)), draft, title)
        if card.loops(new):
            self.log.info(f"kaju_style: 写手这一遍打转了，不用 {new[:40]!r}")
        return new if card.sane_v4(new, card_text, draft) else ""

    async def _pick_emoji(self, event: Turn, text: str, plan: dict, ctx: list[str]) -> None:
        """表情包单独挑（emoji.py，rewrite.emoji = "separate"，2026-11-18）：她的话写好以后，“表情包”那一格
        （model_slots.json 的 emoji）看着这句和心情挑一类，放进 meme_manager 认的 found_emotions。meme_manager 的概率骰子没中就不挑；
        出任何错都只是这次不配图。"""
        cfg = self._sec("rewrite")
        block = event.get_extra("_ks_meme_block")
        if str(cfg.get("emoji", "brain")) != "separate" or not block:
            return
        cats = emoji.categories(block)
        if not cats:
            return
        want = str((plan or {}).get("表情包") or "").strip()
        if want in cats:  # 大脑点名要发（对方要了 / 她答应了，brain.MEME_ASK）：不掷骰、不再问模型，一定发（11-19）
            event.set_extra("found_emotions", [want])
            event.set_extra("meme_manager_legacy_probability_hit", True)
            self._rec.note("emoji", {"model": "brain", "secs": 0, "pick": want, "raw": "大脑点名"})
            self.log.info(f"kaju_style: 表情包照大脑点名发 {want}")
            return
        if want:
            self.log.info(f"kaju_style: 大脑点名的表情包分类 {want!r} 不在分类里，照常挑")
        if event.get_extra("meme_manager_legacy_probability_hit") is False:
            return  # 这一轮 meme_manager 掷骰没中：本来就不配图，也不用问模型
        try:
            system, user = emoji.prompt(cats, text, list(_WRITER_CTX.get() or ctx or []), plan.get("情绪", ""), emoji.own_note(block))
            pid = await slot_model(self.body, "emoji", str(cfg.get("emoji_provider_id", "") or "").strip())
            if not pid:
                return
            t0 = time.time()
            out = await self.body.generate(pid, user, system, timeout=float(cfg.get("emoji_timeout", 10) or 10))
            key = emoji.parse(out, cats)
            self._rec.note("emoji", {"model": pid, "secs": round(time.time() - t0, 1), "pick": key, "raw": (out or "")[:120]})
            if key:
                event.set_extra("found_emotions", [key])
                self.log.info(f"kaju_style: 表情包挑了 {key}（{pid}，{time.time() - t0:.1f}s）")
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 挑表情包没成（这次不配图） {type(e).__name__}: {e}")

    async def _gemini_down(self, event: Turn, resp: Answer, why: str) -> None:
        """出卡的 Gemini 全挂了（2026-11-13 兄长定，替掉决定 20 里“私聊由写手告诉”）：这一句谁那儿都不发
        （群里不说话、私聊和私信也不回），另由 DeepSeek 用她的 QQ 和抖音私信告诉兄长（见 notify_gemini_down）。"""
        where = "群里" if event.get_group_id() else "私聊"
        self.log.warning(f"kaju_style: Gemini 全挂了，{where}这次不说话（{why[:200]}）")
        self.notify_gemini_down(why)
        self._hush(event, resp)

    def notify_gemini_down(self, why: str = "") -> None:
        """后台：DeepSeek 写一两句，用她的 QQ 私聊和抖音私信告诉兄长 Gemini 的 key 全用不了。
        rewrite.gemini_down_notify_minutes（默认 30）分钟内只说一次；用哪个模型看 rewrite.gemini_down_provider_id（默认 deepseek）。
        报错原文不给 DeepSeek（里面可能有中转地址），只说几个 key 都没答上来。"""
        cfg = self._sec("rewrite")
        try:
            gap = float(cfg.get("gemini_down_notify_minutes", 30) or 0) * 60
        except (TypeError, ValueError):
            gap = 1800.0
        if time.time() - self._gd_told < gap:
            return
        self._gd_told = time.time()

        async def go():
            try:
                from kaju_core import people
                from kaju_core.senses import omni
                try:
                    n = len(omni.gemini_keys())
                except Exception:  # noqa: BLE001
                    n = 0
                pid = await self.body.model_id(str(cfg.get("gemini_down_provider_id", "deepseek") or "deepseek"))
                if not pid:
                    self.log.warning("kaju_style: Gemini 全挂了，可找不到 DeepSeek，没法告诉兄长")
                    return
                text = (await self.body.generate(pid, GEMINI_DOWN_PROMPT.format(what=down_summary(why, n)), GEMINI_DOWN_SYSTEM,
                                                 timeout=40)).strip()
                text = rewrite.split_tags(text)[0].strip()
                if not text or text.upper().startswith("[SKIP"):
                    self.log.warning("kaju_style: DeepSeek 没写出 Gemini 挂了的通知")
                    return
                told = []
                owner = people.owner()
                if owner:
                    try:
                        if await self.body.send(self.body.private_chat_id(owner), text):
                            told.append("QQ")
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_style: QQ 上没告诉成兄长 Gemini 挂了 {type(e).__name__}: {e}")
                dm = self.body.find("tell_owner_dm")
                if dm is not None:
                    try:
                        told += await dm.tell_owner_dm(text, ("douyin",))
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_style: 抖音上没告诉成兄长 Gemini 挂了 {type(e).__name__}: {e}")
                self.log.warning(f"kaju_style: 已告诉兄长 Gemini 全挂了（{'、'.join(told) or '哪边都没发出去'}）{text[:40]!r}")
                if not told:
                    self._gd_told = 0.0  # 一边都没发出去：下次再挂时再试
            except Exception as e:  # noqa: BLE001
                self._gd_told = 0.0
                self.log.warning(f"kaju_style: 告诉兄长 Gemini 挂了时出错 {type(e).__name__}: {e}")

        asyncio.create_task(go())

    def _hush(self, event: Turn, resp: Answer) -> None:
        """这一句不发。"""
        resp.completion_text = ""
        for name in ("clear_result", "stop_event"):
            fn = getattr(event, name, None)
            if fn is not None:
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

    def _tries(self, card_text: str) -> int:
        """照卡写最多写几遍：第一遍 + rewrite.retry（默认 1）。没抽出卡不重写。"""
        if not card_text:
            return 1
        try:
            return 1 + max(0, int(self._sec("rewrite").get("retry", 1) or 0))
        except (TypeError, ValueError):
            return 2

    async def _guard(self, said: str, draft: str, new: str, title: str = "", ctx=None) -> tuple[bool, str, bool]:
        """(bad?, why, opener ok?)"""
        cfg = self._sec("rewrite")
        # 核对是机械活：可以指向一个关了思考的提供方（2026-11-07 A/B：快一倍多，埋的错 25/25 照样抓到）
        pid = await self.body.model_id(str(cfg.get("guard_provider_id", "") or "").strip())
        if not pid:
            return True, "没有核对用的模型", True
        out = await self._ask_checker(pid, rewrite.guard_prompt(said, draft, new, title, ctx), rewrite.GUARD)
        return (*rewrite.guard_bad(out), rewrite.guard_opener_ok(out))

    async def _ask_checker(self, pid: str, prompt: str, system: str) -> str:
        """问核对用的模型（pid）：它慢 / 出错就把剩下的时间给 guard_backup_provider_id。核对和改错（_repair）共用。"""
        cfg = self._sec("rewrite")
        total = float(cfg.get("guard_timeout", 8))
        # 后备（2026-11-13）：核对先问 aigocode gemini-3.8-flash（抓“佳树吃过午饭了”这种编的事比 hardysapi 的 3-flash 准），
        # 它慢 / 出错就把剩下的时间给 guard_backup_provider_id（hardysapi）。后备没填 = 只问一个。
        backup = str(cfg.get("guard_backup_provider_id", "") or "").strip()
        backup = await self.body.model_id(backup) if backup else ""
        if backup and backup != pid:
            t0 = time.time()
            first = max(8.0, total * float(cfg.get("guard_first_share", 0.5) or 0.5))
            try:
                return await asyncio.wait_for(self.body.generate(pid, prompt, system, timeout=first), timeout=first)
            except Exception as e:  # noqa: BLE001
                left = total - (time.time() - t0)
                if left < 3:
                    raise
                self.log.info(f"kaju_style: 核对 {pid} 没答上来，换 {backup} {type(e).__name__}: {str(e)[:60]}")
                pid, total = backup, left
        return await self.body.generate(pid, prompt, system, timeout=total)

    async def _repair(self, said: str, draft: str, new: str, why: str, title: str = "") -> str:
        """核对几遍都没过：让核对用的模型只改核对说的那一处（“帮他”→“帮她”），别的字不动。改不了 / 改多了 → ''。
        2026-11-15 兄长：一直被拦也得回一句，不能一直不说话（03:46 写手四遍里后两遍只错了一个“她”字）。"""
        pid = await self.body.model_id(str(self._sec("rewrite").get("guard_provider_id", "") or "").strip())
        if not pid or not new.strip():
            return ""
        out = (await self._ask_checker(pid, rewrite.repair_prompt(said, draft, new, why, title), rewrite.REPAIR) or "").strip()
        out = rewrite.clean_output(out)
        if not out or "无法修改" in out or out.strip() == new.strip() or not rewrite.small_edit(new, out):
            self.log.info(f"kaju_style: 改错没改成 {out[:40]!r}")
            return ""
        return out

    async def _after_all_rejected(self, event: Turn, ctx: list[str], draft: str, flagged: tuple, why: str,
                                  title: str, kind: str, tries: int, mode: str):
        """核对 tries 遍都没过：先改错（只改那一处，再核对一次）；mode=busy 时还不行就说一句在忙。返回要发的那一遍或 None。"""
        new, _, attempt, t1 = flagged
        said = event.message_str or ""
        if self._sec("rewrite").get("guard_repair", True):
            try:
                fixed = await self._repair(said, draft, new, why, title)
                if fixed:
                    bad, what = (await self._guard(said, draft, fixed, title, ctx))[:2]
                    if not bad:
                        self.log.info(f"kaju_style: 核对 {tries} 遍都没过，改掉那一处（{why}）再核对过了 {fixed[:40]!r}")
                        return (fixed, [], attempt, t1)
                    self.log.info(f"kaju_style: 改过的还是没过（{what}） {fixed[:40]!r}")
            except Exception as e:  # noqa: BLE001
                self.log.info(f"kaju_style: 改错出错 {type(e).__name__}: {str(e)[:60]}")
        if mode == "busy" and kind == "群聊" and not event.get_extra("_kaju_called"):
            # 11-15 兄长：群里只有 @ 她、戳她才说在忙；提到名字、自己插话的，全被拦就照旧不说
            self.log.info("kaju_style: 群里没 @ 也没戳她（提到名字 / 自己插话），不说在忙")
        elif mode == "busy":
            try:
                busy = await self._busy_line(event, ctx, title, kind)
            except Exception as e:  # noqa: BLE001
                busy = ""
                self.log.info(f"kaju_style: 说在忙那句也没写成 {type(e).__name__}: {str(e)[:60]}")
            if busy:
                self.log.warning(f"kaju_style: 核对 {tries} 遍都没过、改错也没成，先说一句在忙 {busy[:40]!r}")
                event.set_extra("kaju_style_busy", True)
                return (busy, [], attempt, time.time())
        self.log.warning(f"kaju_style: 核对 {tries} 遍都没过，这次不说（rewrite.guard_fail={mode}）")
        return None

    def _doing_now(self) -> str:
        """日程里她这会儿在做的事（两小时内开始的那件）；没有 → ''。"""
        life = parts.find("doing_now")
        try:
            return str(life.doing_now() or "") if life is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    async def _busy_line(self, event: Turn, ctx: list[str], title: str, kind: str) -> str:
        """改错也没成：让写手照卡说一句“这会儿在忙，等下再好好回”（在忙什么取日程），不说固定的句子。写手不行 → ''。"""
        doing = self._doing_now()
        g = {"局面": f"{title}说了最后这句，佳树想好好回，可一时没整理好，轮到佳树回。",
             "要说到的": [f"佳树这会儿在忙（{doing}）" if doing else "佳树这会儿有点忙",
                         f"佳树等一下再好好回{title}刚才说的"]}
        new = await self._write_from_card(ctx, card.render_v4(kind, title, g, self._mood_line()), "", title)
        return (new or "").strip()

    async def polish(self, draft: str, ctx: list[str] | None = None, said: str = "", title: str = "兄长大人",
                     kind: str = "私聊", split: bool = True) -> str:
        """给插件主动发的话用（kaju_basics 刷到视频想跟兄长说；qzone_post 的说说 kind="说说"）：私聊开着写手就过一遍
        要点卡 + 写手 + 核对，再按聊天节奏分行（split=False 不分行）。
        ctx 是"兄长大人：…""佳树：…"这样的上下文行；said 是触发这句话的事（给核对看）。任何一步不行就用原稿。
        只发写手的话（writer_only，说说除外）：不用原稿——核对都没过发写手最后一遍，写手 / 卡没有就返回 ''（调用的地方这次就不说）。"""
        text = (draft or "").strip()
        cfg = self._sec("rewrite")
        strict = self.writer_only() and kind != "说说" and cfg.get("enable", False) and cfg.get("private", True)
        why = rewrite.skip_reason(text, int(cfg.get("max_chars", 400))) if text else "空"
        if strict and why and why != "空" and "[SKIP" not in text.upper():
            why = ""  # 带链接 / 太长 / 中文少：以前直接发原稿，现在照样交给写手
        if text and cfg.get("enable", False) and cfg.get("private", True) and not why:
            last = ""  # 写手写出来、但核对没过的最后一遍
            try:
                wtitle = "" if kind == "说说" else title
                new, card_text = await self._new_wording(list(ctx or []), text, kind, wtitle)
                tries = self._tries(card_text)
                for attempt in range(tries):  # 照卡写没过就拿同一张卡再写一次（同 _rewrite_reply）
                    if attempt:
                        new = await self._write_from_card(list(ctx or []), card_text, text, wtitle)
                    if not (new and (strict or new.strip() != text) and
                            (cfg.get("guard", True) or not rewrite.needs_title_guard(new, title, kind))):
                        continue
                    ok = True
                    if cfg.get("guard", True):
                        try:
                            res = await self._guard(said, text, new, title, list(ctx or []))
                        except Exception as e:  # noqa: BLE001
                            if not strict:
                                raise
                            res = (False, f"核对出错 {type(e).__name__}", True)  # 核对坏了：写手的话照发
                        ok = not res[0]
                        if ok and rewrite.added_opener(new, text) and len(res) > 2 and not res[2]:
                            new = rewrite.strip_opener(new)
                    if ok:
                        self.log.info(f"kaju_style: 主动的话重说{f'（第 {attempt + 1} 遍）' if attempt else ''} "
                                    f"{text[:30]!r} -> {new[:30]!r}")
                        text, last = new, ""
                        break
                    last = new
                else:
                    if strict:
                        send_last = self._guard_fail_mode() == "send_writer"
                        if last:
                            self.log.info(f"kaju_style: 主动的话核对 {tries} 遍都没过，"
                                          f"{'发写手最后一遍' if send_last else '这次不说'} {last[:30]!r}")
                        text = last if send_last else ""
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "GeminiDown":  # Gemini 全挂了不发草稿，交给调用的地方（kaju_basics 这次就不主动说）
                    self.notify_gemini_down(str(e))
                    raise
                if strict:
                    self.log.info(f"kaju_style: 主动的话写手没写成（这次不说） {type(e).__name__}: {e}")
                    text = last if self._guard_fail_mode() == "send_writer" else ""
                else:
                    self.log.info(f"kaju_style: 主动的话没重说成（用原稿） {type(e).__name__}: {e}")
        elif strict and text:
            text = ""  # 只剩 [SKIP]
        if text and split and self._sec("rhythm").get("enable", True):
            text = self._restyle(text)
        return text

    async def say_from_card(self, event: Turn, points: list[str], emotion: str = "平常",
                            attitude: str = "平常", reply_to: str = "", said: str = "") -> str:
        """插件要她先说一句（kaju_basics 看视频前"先去看"）：不用 DeepSeek 起草，直接把要点卡交给本地写手写，
        说法每次由写手按上下文定（不再从固定的几句里挑）。写手没开、出错、写出来不像话 → ''（就不说）。"""
        cfg = self._sec("rewrite")
        if not cfg.get("enable", False) or not points:
            return ""
        title = self._titles(event)[0]
        kind = "群聊" if event.get_group_id() else "私聊"
        ctx = [f"{title}：{said}"] if said else []
        # 局面由这里拼（插件知道发生了什么），要点照插件给的；emotion / attitude 是第一版卡的栏目，第四版卡不用（参数留着，调用的插件不用改）
        about = f"，接的是“{reply_to}”" if reply_to else ""
        g = {"局面": (f"{title}说了上面这句{about}，轮到佳树回。" if said else f"轮到佳树对{title}开口。"),
             "要说到的": list(points)}
        new = await self._write_from_card(ctx, card.render_v4(kind, title, g, self._mood_line()), "", title)
        if not new:
            return ""
        if self._sec("rhythm").get("enable", True):
            new = self._restyle(new)
        self.log.info(f"kaju_style: 照卡写了一句 {new[:30]!r}")
        return new.strip()

    async def rewrite_reply(self, event: Turn, resp: Answer):
        """外面这层只负责记录（records.py）：重说本身在 _rewrite_reply。"""
        rec = self._rec.begin("reply", event, resp)
        try:
            await self._rewrite_reply(event, resp)
        finally:
            self._rec.end(rec, getattr(resp, "completion_text", "") or "",
                          used=event.get_extra("kaju_style_rewritten") is not None)

    async def _rewrite_reply(self, event: Turn, resp: Answer):
        """主模型的回复（草稿或大脑的指导）交给写手照卡写，核对没问题才换上。
        只发写手的话（writer_only，默认，2026-11-13）：不发原稿——回晚了、草稿带链接也照样过写手；
        核对几遍都没过按 guard_fail 处理；卡 / 写手根本没有就这次不说。writer_only 关了才会退回发原稿。"""
        if getattr(resp, "tools_call_name", None) or event.get_extra("_ks_rw_done") or getattr(resp, "role", "") == "err":
            return  # 报错不是草稿（主模型全挂时由 hush_model_error 处理）
        strict = self.writer_only() and self._rewrite_on(event)
        ctx = event.get_extra("_ks_rw_ctx")
        if not ctx:
            if not strict:
                return
            # 这一轮没记上下文（rewrite_snapshot 没跑到 / 出错）：以前直接发原稿，现在只拿对方这句给写手
            title0 = event.get_extra("_ks_rw_title") or self._titles(event)[0]
            ctx = [f"{title0}：" + (event.message_str or "").replace("\n", " / ")[:160]]
            event.set_extra("_ks_rw_title", title0)
            self.log.info("kaju_style: 这一轮没记上下文，只拿对方这句给写手")
        event.set_extra("_ks_rw_ctx", None)  # 一轮只重说一次
        event.set_extra("_ks_rw_done", True)
        _WRITER_CTX.set(event.get_extra("_ks_rw_long") or None)  # 这一轮（这个 task）写手看长前文；没开 / 没拿到就是 None
        _REPLYER_CTX.set(event.get_extra("_ks_rw_replyer") or None)  # 回复器看的前文（群聊 50 行、私聊 20 行）
        _PLAN.set(None)  # 大脑的指导下面解析出来才放进去
        _HOW.set(event.get_extra("_ks_how") or "")
        cfg = self._sec("rewrite")
        # 已经回晚了（模型卡过、群里排着队）：重说 + 核对还要 3~4 秒，先把话发出去（只发写手的话时不跳过）
        try:
            late = 0.0 if strict else float(cfg.get("skip_when_late", 25) or 0)
            arrived = float(event.get_extra("_kaju_quote_t") or 0)  # kaju_basics 记的这条消息到达时间
        except (TypeError, ValueError):
            late, arrived = 0.0, 0.0
        if late > 0 and (event.get_extra("_kaju_felt") or event.get_extra("kaju_docs_read")):
            # 这一轮她是看完视频 / 听完歌 / 读完文件才回的：等的时间本来就花在看上，不算"回晚了"。
            # 2026-11-11 兄长定：看完的感想一定过写手，多等几秒也行（之前 28 次里有 16 次因为这条直接发了原稿）
            late = 0.0
        if late > 0 and arrived and time.time() - arrived > late:
            self.log.info(f"kaju_style: 重说层跳过（这条已经等了 {time.time() - arrived:.0f}s，先快点回）")
            return
        draft, tags = rewrite.split_tags(getattr(resp, "completion_text", "") or "")
        title = event.get_extra("_ks_rw_title") or ""
        kind = "群聊" if event.get_group_id() else "私聊"
        plan = None
        if event.get_extra("_ks_brain"):  # 主模型这一轮当的是大脑：回来的是 JSON 指导（brain.py）
            plan = brain.parse(draft)
            self._rec.note("brain", {"plan": plan, "raw": None if plan else draft[:500]})
            if plan is not None and kind == "群聊":  # 想的时候群里又来了：重想一遍（11-18 晚）
                plan = await self._replan(event, plan)
                more = event.get_extra("_ks_replan_ctx")
                if more:
                    ctx = list(ctx) + list(more)
                if plan is not None and plan.get("回不回") != "不回":  # 没人叫她的轮次：发之前单独把一下关
                    plan = await self._action_judge(event, plan, ctx)
            if plan is not None:  # follow_through 看“答应：…”有没有真做（11-19：答应“去查 Hoody”却没调工具）
                event.set_extra("_ks_plan", plan)
            if plan is None:
                self.log.info(f"kaju_style: 大脑的指导解析不了，当草稿照旧摘卡 {draft[:60]!r}")
            elif kind == "群聊" and plan.get("回不回") == "不回":
                if str(cfg.get("planner_skip", "log")) == "group":
                    self.log.info(f"kaju_style: 大脑说群里这句不用回，这次不说 {plan.get('局面', '')[:40]!r}")
                    event.set_extra("kaju_style_rewritten", {"draft": draft, "new": ""})  # 历史里别留下 JSON
                    self._hush(event, resp)
                    return
                self.log.info(f"kaju_style: 大脑说群里这句可以不回（只记，照样回） {plan.get('局面', '')[:40]!r}")
        if plan is None:
            why = rewrite.skip_reason(draft, int(cfg.get("max_chars", 400)))
            if strict and why and why != "空" and "[SKIP" not in draft.upper():
                self.log.info(f"kaju_style: 草稿{why}，照样交给写手（只发写手的话）")
                why = ""
            if why:
                self.log.info(f"kaju_style: 重说层跳过（{why}）")
                return
        t0 = time.time()
        try:
            if plan is not None:  # 大脑的指导直接排成卡；核对、改错拿“大脑定下的意思”当草稿比
                _PLAN.set({"brain": plan})
                draft = brain.reference(plan)
                card_text = brain.card_of(kind, title, plan, self._mood_line())
                new = await self._write_from_card(ctx, card_text, draft, title)
            elif event.get_extra("_kaju_felt"):  # 看完东西的回合（别的地方换掉 _new_wording 时还是四个参数，只在这时多传）
                new, card_text = await self._new_wording(ctx, draft, kind, title, felt=True)
            else:
                new, card_text = await self._new_wording(ctx, draft, kind, title)
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ == "GeminiDown":  # 第四版出卡的 Gemini 全挂了：这句不发，DeepSeek 告诉兄长
                await self._gemini_down(event, resp, str(e))
                return
            if strict:
                self.log.warning(f"kaju_style: 写手这边没回（这次不说） {type(e).__name__}: {e}")
                self._hush(event, resp)
                return
            self.log.warning(f"kaju_style: 重说层没回（发原稿） {type(e).__name__}: {e}")
            return
        if card_text:
            event.set_extra("kaju_style_card", card_text)
        # 照卡写：写出来不像回复、或者核对没过，就拿同一张卡再写一次（2026-11-08：线上 58 次里 14 次被拦，
        # 大半是写手这一遍编了/漏了，换一遍采样常常就对了）；核对本身出错（超时）不重写，重写也救不了
        tries = self._tries(card_text)
        # 发之前查套路（routine.py）：off 不查 / log 只记不拦（默认）/ on 撞了拿同一张卡再写一遍，两遍里挑撞得少的
        routine_mode = str(cfg.get("routine", "log") or "off")
        held = None  # 核对过了、但撞了套路的那一遍 (new, hits, attempt, t1)：再写的那遍不行就发它，不退回原稿
        done = None  # 最后要发的那一遍
        flagged = None  # 只发写手的话：核对没过、但总归是写手写的最后一遍
        flagged_why = ""  # 那一遍核对说的问题（改错用）
        fallback = "" if strict else "（发原稿）"
        rejects = 0  # 核对拦下几遍（核对出错不算）
        try:
            recard_after = int(cfg.get("recard_after", 2) or 0)  # 拦下这么多遍就带着问题重新出卡；0 = 不重出
        except (TypeError, ValueError):
            recard_after = 2
        felt = bool(event.get_extra("_kaju_felt"))
        for attempt in range(tries):
            again = attempt + 1 < tries
            if attempt:
                if late > 0 and arrived and time.time() - arrived > late:
                    self.log.info("kaju_style: 来不及再写一次了" + ("" if held else fallback))
                    break
                try:
                    new = await self._write_from_card(ctx, card_text, draft, title)
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_style: 再写一次没回{'' if held else fallback} {type(e).__name__}: {e}")
                    break
            if not new or (not strict and new.strip() == draft.strip()):
                why = "一样" if new else ("没抽出要点卡" if not card_text else "不像回复")
                self.log.info(f"kaju_style: 重说结果不用（{why}）{'，再写一次' if again else ''}")
                if again:
                    continue
                break
            if rewrite.needs_title_guard(new, title, kind) and not cfg.get("guard", True) and not strict:
                self.log.info(f"kaju_style: 兄长称呼需要核对但核对未启用（发原稿） {new[:40]!r}")
                break
            t1 = time.time()
            if cfg.get("guard", True):
                errored = False
                try:
                    res = await self._guard(event.message_str or "", draft, new, title, ctx)
                except Exception as e:  # noqa: BLE001
                    res, errored = (True, f"核对失败 {type(e).__name__}"), True
                bad, what = res[0], res[1]
                if bad and strict and errored:
                    self.log.info(f"kaju_style: {what}，写手这一遍照发 {new[:40]!r}")
                    bad = False
                if bad:
                    if strict:
                        flagged = (new, [], attempt, t1)
                        flagged_why = what
                    if again and not errored:
                        rejects += 1
                        self.log.info(f"kaju_style: 重说核对没过（{what}），再写一次 {new[:40]!r}")
                        if recard_after and rejects == recard_after:  # 同一张卡连着被拦：可能是卡错了，回去重出（只一次）
                            fresh = await self._recheck_card(ctx, draft, kind, title, card_text, new, what, felt)
                            if fresh and fresh != card_text:
                                self.log.info(f"kaju_style: 带着问题重新出了卡 {fresh.splitlines()[3][:60]!r}")
                                card_text = fresh
                                event.set_extra("kaju_style_card", card_text)
                        continue
                    self.log.info(f"kaju_style: 重说核对没过（{'' if held or strict else '发原稿：'}{what}） {new[:40]!r}")
                    break
                op = rewrite.added_opener(new, draft)
                if op and len(res) > 2 and not res[2]:
                    new = rewrite.strip_opener(new)
                    self.log.info(f"kaju_style: 开头「{op}」不合场合，去掉")
            hits = self._routine_hits(event, new, routine_mode) if routine_mode != "off" else []
            if hits:
                self.log.info(f"kaju_style: 撞了套路 {hits}"
                              f"{'，再写一次' if routine_mode == 'on' and again and held is None else ''} {new[:40]!r}")
            if hits and routine_mode == "on" and again and held is None:
                held = (new, hits, attempt, t1)
                continue
            if held is None or len(hits) < len(held[1]):
                done = (new, hits, attempt, t1)
            break
        done = done or held
        if not done and flagged:
            mode = self._guard_fail_mode()
            if mode == "send_writer":
                done = flagged
                self.log.info(f"kaju_style: 核对 {tries} 遍都没过，发写手最后一遍（只发写手的话）")
            else:  # 11-13 兄长：核对拦下的（编了“兄长大人好帅”）不能照发
                done = await self._after_all_rejected(event, ctx, draft, flagged, flagged_why, title, kind, tries, mode)
        if not done:
            if strict:
                self.log.warning("kaju_style: 写手这一轮一句也没写成（这次不说）")
                self._hush(event, resp)
            return
        new, _, attempt, t1 = done
        if plan is not None:
            await self._pick_emoji(event, new, plan, ctx)
        resp.completion_text = rewrite.with_tags(new, tags)
        event.set_extra("kaju_style_rewritten", {"draft": draft, "new": resp.completion_text})
        how = "照卡写" + (f"（第 {attempt + 1} 遍）" if attempt else "")
        self.log.info(f"kaju_style: {how} {t1 - t0:.1f}s + 核对 {time.time() - t1:.1f}s {draft[:30]!r} -> {new[:30]!r}")

    async def rewrite_history(self, event: Turn, run_context, response: Answer):
        """历史里存的是重说之前的那版（回复钩子之前就写好了）：换成真正发出去的。"""
        done = event.get_extra("kaju_style_rewritten")
        if not done:
            return
        try:
            msgs = run_context.messages
            if not msgs or msgs[-1].role != "assistant":
                return
            msg = msgs[-1]
            if isinstance(msg.content, str):
                msg.content = done["new"]
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if getattr(part, "type", None) == "text" and getattr(part, "text", None):
                        part.text = done["new"]
                        break
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 历史里没换成重说后的回复: {e!r}")

    # ------------------------------------------------------------ 收到回复后
    async def after_reply(self, event: Turn, resp: Answer):
        text = getattr(resp, "completion_text", "") or ""
        if self._is_late() and NAG_WORDS.search(text):
            self._record_nag(event)
        if getattr(resp, "tools_call_name", None) or not text.strip():
            return
        umo = event.unified_msg_origin
        reply = clean_reply(text)
        if reply and not reply.startswith("[SKIP"):
            self._replies[umo].append(reply)
            self._sent_of(umo).append(reply)

    # ------------------------------------------------------------ 聊天节奏
    def _max_lines(self) -> int:
        try:
            return int(self._sec("rhythm").get("max_lines", 4))
        except (TypeError, ValueError):
            return 4

    def _restyle(self, text: str, event: Turn | None = None) -> str:
        cfg = self._sec("rhythm")
        try:
            split_max = int(cfg.get("split_max_lines", 5))
            long_line = int(cfg.get("split_long", 0))
        except (TypeError, ValueError):
            split_max, long_line = 5, 0
        if event is not None and (event.get_extra("kaju_style_concrete") or event.get_extra("kaju_style_rewritten")):
            split_max = 0  # 聊作品时 / 重说层说的完整句子：不在逗号处拆
        return restyle(text, self._max_lines(), split_max, long_line)

    def _model_error_texts(self) -> list[str]:
        """主模型全挂时 AstrBot 自己发的那句：人设里的 custom_error_message（正本 kaju_data\\self\\persona\\persona.json）。"""
        try:
            with open(os.path.join(paths.self_dir("persona"), "persona.json"), encoding="utf-8") as f:
                msg = (json.load(f) or {}).get("custom_error_message") or ""
            return [msg.strip()] if msg.strip() else []
        except Exception:  # noqa: BLE001
            return []

    async def hush_model_error(self, event: Turn):
        """只发写手的话（2026-11-13）：主模型（Gemini）连后备都失败时，AstrBot 会直接发人设里的固定句子
        （“唔…佳树刚才走神了…”）或“LLM 响应错误: …”。这句不是写手写的 → 不发；当成 Gemini 全挂了，DeepSeek 告诉兄长。"""
        if not self.writer_only():
            return
        result = event.get_result()
        if not result or not result.chain or result.is_llm_result():
            return
        text = "".join(getattr(c, "text", "") or "" for c in result.chain if type(c).__name__ == "Plain").strip()
        if not text:
            return
        if not (MODEL_ERROR.match(text) or text in self._model_error_texts()):
            return
        self.log.warning(f"kaju_style: 主模型全挂了，AstrBot 要发的报错这次不发 {text[:60]!r}")
        self.notify_gemini_down("main")
        for name in ("clear_result", "stop_event"):
            fn = getattr(event, name, None)
            if fn is not None:
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

    async def restyle_outgoing(self, event: Turn):
        if not self._sec("rhythm").get("enable", True):
            return
        result = event.get_result()
        if not result or not result.chain or not result.is_llm_result():
            return
        for comp in result.chain:
            if type(comp).__name__ == "Plain" and comp.text:  # 文字段
                new = self._restyle(comp.text, event)
                if new != comp.text:
                    self.log.info(f"kaju_style: 节奏 {comp.text[:40]!r} -> {new[:40]!r}")
                    comp.text = new

    async def restyle_history(self, event: Turn, run_context, response: Answer):
        """把存进历史的那条回复也改掉，模型就不会从上下文里学回句号。"""
        if not self._sec("rhythm").get("enable", True):
            return
        try:
            msgs = run_context.messages
            if not msgs or msgs[-1].role != "assistant":
                return
            msg = msgs[-1]
            if isinstance(msg.content, str):
                msg.content = self._restyle(msg.content, event)
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if getattr(part, "type", None) == "text" and getattr(part, "text", None):
                        part.text = self._restyle(part.text, event)
        except Exception as e:  # 历史没改成不影响发送
            self.log.warning(f"kaju_style: 历史节奏改写失败: {e}")
