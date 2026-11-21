"""佳树的说话习惯：几条管"怎么说话"的小规则 + 写她的话（大脑的指导 → 回复器）。

- 聊天节奏（rhythm）：按句号等标点分行，去掉句尾句号，默认不在逗号处拆句；可配置拆分长句。
  发送前和存进历史前各处理一次。
- 被纠正提醒（rebuttal）：对方引用/接着她的话在纠正她时，提醒她先接住对方的意思、别沿用原来的说法。
  提醒放在所有提示的最后（离她作答最近）。
- 说具体、说连贯（concrete，1.6.0）：聊一部作品的时候（memory_weight 给了珍藏的内容、刚读了文件/看了视频、或者在问一部作品的看法），
  提醒"用具体的情节、人物、原话说看法，句和句接得上"，这一轮不在逗号处拆消息。
- 写她的话（rewrite 这一节配置）：主模型当大脑，只出 JSON 指导（brain.py）→ 回复器（replyer.py，API 大模型）用她的口吻写
  → 核对（编了事 / 丢了要紧信息 / 叫错人就再写）；只发回复器写的话（writer_only）。
  大脑没给出 JSON：同一份材料再问它一遍；还不行，私聊说一句在忙，群里不说。
  插件主动说的话（polish）先把草稿整理成同样格式的指导；插件给要点（say_from_card）直接拼成指导。
  2026-11-21 兄长：第四版要点卡（Gemini 从草稿摘卡）和本地写手整条删掉，来龙去脉见 git 历史。
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
from kaju_core.voice import asks, brain, concrete, emoji, longctx, replyer, rewrite, routine  # noqa: E402
from kaju_core.voice.respond import build_note as respond_note  # noqa: E402
from kaju_core.voice.rhythm import NOTE as RHYTHM_NOTE  # noqa: E402
from kaju_core.voice.rhythm import restyle  # noqa: E402
from kaju_core.voice.routine import clean_reply, text_of  # noqa: E402
from kaju_core.voice import records  # noqa: E402
from kaju_core.voice.rebuttal import build_note as rebuttal_note  # noqa: E402
from kaju_core.voice.rebuttal import is_rebuttal, quoted_own  # noqa: E402

# 回复器看的前文（rewrite_snapshot 里按 replyer_ctx_group / replyer_ctx_private 取；没有就用短的那份最后 10 行）。
# 用 ContextVar 不用 self：几个人同时说话时各轮互不串。
_REPLYER_CTX: contextvars.ContextVar = contextvars.ContextVar("kaju_replyer_ctx", default=None)
# 这一轮群聊怎么来的（brain.how_came："插话" / "接着聊" / ""），给回复器（11-18 晚）
_HOW: contextvars.ContextVar = contextvars.ContextVar("kaju_how", default="")

PLUGIN_NAME = "astrbot_plugin_kaju_style"


# ---- 深夜催睡
NAG_WORDS = re.compile(r"早点睡|早睡|快睡|去睡|睡觉|睡吧|该睡|熬夜|休息|晚安|别太晚|不早了")


USER_SLEEPY = re.compile(r"睡|困|晚安|熬夜|失眠|累")

# 主模型连后备全挂了时让 DeepSeek 写的通知（2026-11-13 兄长：“由 DeepSeek 用佳树的 QQ、抖音给我发消息告知”）。
# 这是给兄长的故障通知，不是她平时说话；平时的话只由回复器写。（11-21 起只剩主模型这一种：出卡的 Gemini 那条删了）
DOWN_SYSTEM = "你是温水佳树（《败犬女主太多了！》），兄长大人的妹妹，这会儿在给兄长大人发私聊消息。"
DOWN_PROMPT = ("你这边写回复用的模型刚才没答上来：主模型和它的几个后备都没答上来（多半是中转站太慢或在报错）。"
               "在它恢复之前，你在群里不说话、私聊也没法回。用一两句话照实告诉兄长大人这件事（别说成别的情况），"
               "请他看一下模型的 key 和中转站。只输出要发的话本身。")
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
        self._gd_told = 0.0  # 上次告诉兄长主模型全挂了的时间

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
    # ------------------------------------------------------------ 主模型当大脑（2026-11-17 兄长定；11-21 起只有这一种）
    async def brain_request(self, event: Turn, req: Request):
        """别的插件都加完材料之后：把人设里扮佳树说话的那一段换成大脑的要求（brain.swap_persona），这一轮记上 _ks_brain。
        这一轮不重说（rewrite 关着、插件自己发起的请求）就不换。"""
        if not self._rewrite_on(event):
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
            sp = brain.slim(sp)  # 跟大脑规则重复的“说到做到”几条去掉（11-20）
            req.system_prompt = brain.swap_persona(sp, bool(rcfg.get("brain_character", False)), meme=not separate,
                                                   meme_cats=meme_cats)
            try:  # 群里在聊 AI：这一轮最后提醒一句“说的不是她”（11-20，长规则老被盖过）；出错不影响换大脑
                parts = getattr(req, "extra_user_content_parts", None)
                for p in parts or []:  # Memorix 那段的固定规则和技术信息大脑用不上（11-20 精简）
                    if isinstance(getattr(p, "text", None), str):
                        p.text = brain.slim_memorix(p.text)
                if parts and event.get_group_id():
                    recent = [req.prompt or ""] + [str(getattr(p, "text", "") or "")[-1500:] for p in parts]
                    tp = next((type(p) for p in parts if isinstance(getattr(p, "text", None), str)), None)
                    if tp is not None and brain.ai_talk(recent):
                        parts.append(tp(text=brain.AI_TALK_NOTE))
            except Exception:  # noqa: BLE001
                pass
            event.set_extra("_ks_brain", True)
            event.set_extra("_ks_brain_req", req)  # 重想（_replan）、没给出 JSON 再问一遍（_rethink）都拿它
        except Exception as e:  # noqa: BLE001  换不成：主模型这一轮写的是草稿，回来时整理成指导（_plan_from_draft）
            self.log.warning(f"kaju_style: 换成大脑的提示没成（回来的草稿再整理成指导） {type(e).__name__}: {e}")

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
        """回复器看的前文：kaju_life 的聊天记录里这一句之前的最后几行（带时间、换天插日期，格式见 longctx.py），
        最后一行是对方这一句（current，含引用）。拿不到记录 → None（用短的）。"""
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
        重想了还把新来的几条接到回复器看的前文后面（不然它只看到这句为止）。"""
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
        extra = "".join(getattr(p, "text", "") or "" for p in (getattr(req, "extra_user_content_parts", None) or []))
        prompt = brain.replan_prompt((req.prompt or "") + extra, self._history_of(req), lines)
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
        cur = _REPLYER_CTX.get()
        if cur:
            _REPLYER_CTX.set(list(cur) + lines)
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
            rcfg = self._sec("rewrite")
            # 回复器多看聊天（2026-11-18 兄长：“群聊改成跟人家一样，但是私聊可以相对少一点”）：
            # MaiBot 群聊参考最近 50 条（max_context_size）、私聊 75；这里群聊 50、私聊 20
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
                except Exception as e:  # noqa: BLE001  拿不到就用短的那份
                    self.log.info(f"kaju_style: 回复器的前文没拿到（用短的） {type(e).__name__}: {e}")
            event.set_extra("_ks_rw_replyer", rc)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_style: 重说层记上下文出错 {type(e).__name__}: {e}")

    def writer_only(self) -> bool:
        """只发回复器写的话（2026-11-13 兄长：“我不希望写手会经过 DeepSeek”）：默认开（rewrite.writer_only）。
        回晚了、大脑没给出指导、回复器出错、核对没过……都不发主模型回的原话：
        核对几遍都没过按 guard_fail 处理，回复器根本没写成就这次不说。"""
        return bool(self._sec("rewrite").get("writer_only", True))

    def _guard_fail_mode(self) -> str:
        """核对几遍都没过时（只发写手的话）："silent" = 这句不说（11-13 兄长定：写手编的“兄长大人好帅”核对拦了三遍，
        照发写手最后一遍就把它发出去了）；"send_writer" = 照发写手最后一遍；
        "busy"（默认，11-15 兄长：一直不说话会以为哪里坏了）= 先让核对模型只改被拦的那一处、再核对一次，
        还不行就说一句“这会儿在忙，等下再好好回”。silent / busy 都先试改错（rewrite.guard_repair，默认开）。"""
        mode = str(self._sec("rewrite").get("guard_fail", "busy") or "busy")
        return mode if mode in ("silent", "send_writer", "busy") else "busy"

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

    def _history_of(self, req) -> list[tuple[str, str]]:
        """大脑那一轮请求里最近几轮对话，压成 (role, 文字)（重想、再问一遍时带上）。"""
        return [(str(m.get("role")), text_of(m.get("content"))) for m in (getattr(req, "contexts", None) or [])[-6:]
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")]

    async def _rethink(self, event: Turn, raw: str) -> dict | None:
        """大脑这一轮回的不是能用的 JSON（11-21 两次：兄长喊她“妈妈”，Claude 直接用她的口吻写了回复）：
        拿同一份材料再问一遍，最后叮嘱只输出 JSON（brain.RETHINK_NOTE）。走模型挑选和后备；这一遍没有工具。
        还不行 → None。原来这时把它写的话当草稿摘第四版要点卡，11-21 兄长：不要那种卡了，换成规划器的形式。"""
        req = event.get_extra("_ks_brain_req")
        if req is None:
            return None
        cfg = self._sec("rewrite")
        extra = "".join(getattr(p, "text", "") or "" for p in (getattr(req, "extra_user_content_parts", None) or []))
        prompt = brain.rethink_prompt((req.prompt or "") + extra, self._history_of(req), raw, bool(event.get_group_id()))
        t0 = time.time()
        try:
            pid = await self.body.model_id()
            out = await self.body.generate(pid, prompt, req.system_prompt or "",
                                           timeout=float(cfg.get("rethink_timeout", 45) or 45))
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 大脑再想一遍没答上来 {type(e).__name__}: {str(e)[:60]}")
            self._rec.note("rethink", {"error": type(e).__name__, "secs": round(time.time() - t0, 1)})
            return None
        plan = brain.parse(out)
        if plan is not None and not event.get_group_id() and not plan.get("局面"):
            plan = None  # 私聊一律回：只写了“不回”也不算
        self._rec.note("rethink", {"plan": plan, "raw": None if plan else (out or "")[:300],
                                   "secs": round(time.time() - t0, 1)})
        if plan is None:
            self.log.info(f"kaju_style: 大脑再想一遍还是没给出指导 {(out or '')[:60]!r}")
        else:
            self.log.info(f"kaju_style: 大脑再想了一遍（{time.time() - t0:.0f}s）{plan.get('回不回', '')} "
                          f"{plan.get('局面', '')[:40]!r}")
        return plan

    async def _plan_from_draft(self, ctx: list[str], draft: str, kind: str, title: str) -> dict | None:
        """插件主动让她说的话（刷到视频想分享、补上答应的事、说说）：草稿交给主模型整理成大脑那样的指导（brain.FROM_DRAFT），
        回复器再照指导写。整理不出来 → None（调用的地方这次就不说）。"""
        cfg = self._sec("rewrite")
        pid = await self.body.model_id()
        if not pid:
            return None
        t0 = time.time()
        out = await self.body.generate(pid, brain.from_draft_prompt(kind, title, ctx, draft), brain.FROM_DRAFT,
                                       timeout=float(cfg.get("rethink_timeout", 45) or 45))
        plan = brain.parse(out)
        self._rec.note("from_draft", {"plan": plan, "raw": None if plan else (out or "")[:300],
                                      "secs": round(time.time() - t0, 1)})
        if plan is None:
            self.log.info(f"kaju_style: 主动的话整理不出指导 {(out or '')[:60]!r}")
        return plan

    async def _write(self, ctx: list[str], plan: dict, kind: str, title: str, ref: str = "") -> str:
        """回复器照指导写一遍（每次都不一样，被核对拦下时可以拿同一份指导再写）。没写成 / 不像回复 → ''。
        ref：判繁体字时的参照（草稿 / 大脑定下的意思）。"""
        cfg = self._sec("rewrite")
        if cfg.get("replyer_mood", True):  # 心情底色直接给回复器（11-18 量过：大脑写“情绪”时基本不看底色）
            tone = self._mood_words(group=kind == "群聊")
            plan = {**plan, "底色": tone} if tone else plan
        rctx = _REPLYER_CTX.get()  # 回复器自己那份（群聊 50 行 / 私聊 20 行）；没有就用短的那份、只看最后 10 行
        new, info = await replyer.reply(kind or "私聊", title, list(rctx or ctx or []), plan, cfg,
                                        said=(ctx or [""])[-1] if ctx else "", log=self.log,
                                        ctx_lines=0 if rctx else 10, how=_HOW.get())
        info["底色"] = plan.get("底色", "")
        info["前文行数"] = len(rctx or (ctx or [])[-10:])
        self._rec.note("replyer", {**info, "text": new[:300]})
        if new and replyer.sane(new, (ref or "") + replyer.plan_text(plan)):
            self.log.info(f"kaju_style: 回复器写好（{info.get('model', '')[:24]}，{info.get('secs')}s）{new[:40]!r}")
            return new
        self.log.info(f"kaju_style: 回复器没写成（{'；'.join(info.get('errors') or []) or '不像回复'}）")
        return ""

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
            event.set_extra("_ks_meme_label", emoji.label(cats, want))  # kaju_life 记进聊天记录用（11-20）
            self._rec.note("emoji", {"model": "brain", "secs": 0, "pick": want, "raw": "大脑点名"})
            self.log.info(f"kaju_style: 表情包照大脑点名发 {want}")
            return
        if want:
            self.log.info(f"kaju_style: 大脑点名的表情包分类 {want!r} 不在分类里，照常挑")
        if event.get_extra("meme_manager_legacy_probability_hit") is False:
            return  # 这一轮 meme_manager 掷骰没中：本来就不配图，也不用问模型
        try:
            system, user = emoji.prompt(cats, text, list(_REPLYER_CTX.get() or ctx or []), plan.get("情绪", ""), emoji.own_note(block))
            pid = await slot_model(self.body, "emoji", str(cfg.get("emoji_provider_id", "") or "").strip())
            if not pid:
                return
            t0 = time.time()
            out = await self.body.generate(pid, user, system, timeout=float(cfg.get("emoji_timeout", 10) or 10))
            key = emoji.parse(out, cats)
            self._rec.note("emoji", {"model": pid, "secs": round(time.time() - t0, 1), "pick": key, "raw": (out or "")[:120]})
            if key:
                event.set_extra("found_emotions", [key])
                event.set_extra("_ks_meme_label", emoji.label(cats, key))
                self.log.info(f"kaju_style: 表情包挑了 {key}（{pid}，{time.time() - t0:.1f}s）")
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_style: 挑表情包没成（这次不配图） {type(e).__name__}: {e}")

    def notify_model_down(self) -> None:
        """后台：DeepSeek 写一两句，用她的 QQ 私聊和抖音私信告诉兄长主模型连后备都没答上来。
        rewrite.gemini_down_notify_minutes（默认 30）分钟内只说一次；用哪个模型看 rewrite.gemini_down_provider_id（默认 deepseek）。
        报错原文不给 DeepSeek（里面可能有中转地址）。"""
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
                pid = await self.body.model_id(str(cfg.get("gemini_down_provider_id", "deepseek") or "deepseek"))
                if not pid:
                    self.log.warning("kaju_style: 主模型全挂了，可找不到 DeepSeek，没法告诉兄长")
                    return
                text = (await self.body.generate(pid, DOWN_PROMPT, DOWN_SYSTEM, timeout=40)).strip()
                text = rewrite.split_tags(text)[0].strip()
                if not text or text.upper().startswith("[SKIP"):
                    self.log.warning("kaju_style: DeepSeek 没写出主模型挂了的通知")
                    return
                told = []
                owner = people.owner()
                if owner:
                    try:
                        if await self.body.send(self.body.private_chat_id(owner), text):
                            told.append("QQ")
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_style: QQ 上没告诉成兄长主模型挂了 {type(e).__name__}: {e}")
                dm = self.body.find("tell_owner_dm")
                if dm is not None:
                    try:
                        told += await dm.tell_owner_dm(text, ("douyin",))
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(f"kaju_style: 抖音上没告诉成兄长主模型挂了 {type(e).__name__}: {e}")
                self.log.warning(f"kaju_style: 已告诉兄长主模型全挂了（{'、'.join(told) or '哪边都没发出去'}）{text[:40]!r}")
                if not told:
                    self._gd_told = 0.0  # 一边都没发出去：下次再挂时再试
            except Exception as e:  # noqa: BLE001
                self._gd_told = 0.0
                self.log.warning(f"kaju_style: 告诉兄长主模型挂了时出错 {type(e).__name__}: {e}")

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

    def _tries(self) -> int:
        """照指导最多写几遍：第一遍 + rewrite.retry（默认 1）。"""
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
        """回不成正经的话（核对全拦、改错也没成；私聊里大脑两遍都没给出指导）：让回复器说一句“这会儿在忙，等下再好好回”
        （在忙什么取日程），不说固定的句子。回复器不行 → ''。"""
        doing = self._doing_now()
        plan = {"局面": f"{title}说了最后这句，她想好好回，可一时没整理好",
                "要表达的": [f"解释：这会儿在忙（{doing}）" if doing else "解释：这会儿有点忙",
                          f"答应：等一下再好好回{title or '对方'}刚才说的"]}
        new = await self._write(ctx, plan, kind, title)
        return (new or "").strip()

    async def polish(self, draft: str, ctx: list[str] | None = None, said: str = "", title: str = "兄长大人",
                     kind: str = "私聊", split: bool = True) -> str:
        """给插件主动发的话用（kaju_basics 刷到视频想跟兄长说；qzone_post 的说说 kind="说说"）：私聊开着就过一遍
        草稿整理成指导（_plan_from_draft）+ 回复器 + 核对，再按聊天节奏分行（split=False 不分行）。
        ctx 是"兄长大人：…""佳树：…"这样的上下文行；said 是触发这句话的事（给核对看）。任何一步不行就用原稿。
        只发回复器的话（writer_only，说说除外）：不用原稿——核对都没过按 guard_fail，整理不出指导 / 回复器没写成就返回 ''
        （调用的地方这次就不说）。"""
        text = (draft or "").strip()
        cfg = self._sec("rewrite")
        strict = self.writer_only() and kind != "说说" and cfg.get("enable", False) and cfg.get("private", True)
        why = rewrite.skip_reason(text, int(cfg.get("max_chars", 400))) if text else "空"
        if strict and why and why != "空" and "[SKIP" not in text.upper():
            why = ""  # 带链接 / 太长 / 中文少：以前直接发原稿，现在照样交给回复器
        if text and cfg.get("enable", False) and cfg.get("private", True) and not why:
            last = ""  # 回复器写出来、但核对没过的最后一遍
            try:
                wtitle = "" if kind == "说说" else title
                plan = await self._plan_from_draft(list(ctx or []), text, kind, wtitle)
                tries = self._tries() if plan else 0
                for attempt in range(tries):  # 照指导写没过就拿同一份指导再写一次（同 _rewrite_reply）
                    new = await self._write(list(ctx or []), plan, kind, wtitle, text)
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
                                          f"{'发最后一遍' if send_last else '这次不说'} {last[:30]!r}")
                        text = last if send_last else ""
            except Exception as e:  # noqa: BLE001
                if strict:
                    self.log.info(f"kaju_style: 主动的话没写成（这次不说） {type(e).__name__}: {e}")
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
        """插件要她先说一句（kaju_basics 看视频前"先去看"）：不用主模型起草，插件给的要点直接拼成指导交给回复器，
        说法每次由回复器按上下文定（不从固定的几句里挑）。回复器没写成、写出来不像话 → ''（就不说）。
        emotion / attitude 是第一版卡留下的参数，现在不用（留着，调用的插件不用改）。"""
        cfg = self._sec("rewrite")
        if not cfg.get("enable", False) or not points:
            return ""
        title = self._titles(event)[0]
        kind = "群聊" if event.get_group_id() else "私聊"
        ctx = [f"{title}：{said}"] if said else []
        about = f"，接的是“{reply_to}”" if reply_to else ""
        plan = {"局面": (f"{title}说了上面这句{about}，轮到她回" if said else f"轮到她对{title}开口"),
                "要表达的": list(points)}
        new = await self._write(ctx, plan, kind, title)
        if not new:
            return ""
        if self._sec("rhythm").get("enable", True):
            new = self._restyle(new)
        self.log.info(f"kaju_style: 照要点写了一句 {new[:30]!r}")
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
        """主模型这一轮当大脑：回来的 JSON 指导交给回复器写，核对没问题才换上。
        大脑没给出能用的指导 → 同一份材料再问它一遍（_rethink）；还不行，私聊说一句在忙、群里不说（11-21 兄长定）。
        只发回复器写的话（writer_only，默认，2026-11-13）：主模型回的东西本身从不发出去；核对几遍都没过按 guard_fail 处理。
        writer_only 关了，没指导时才照发主模型的原话。"""
        if getattr(resp, "tools_call_name", None) or event.get_extra("_ks_rw_done") or getattr(resp, "role", "") == "err":
            return  # 报错不是指导（主模型全挂时由 hush_model_error 处理）
        strict = self.writer_only() and self._rewrite_on(event)
        ctx = event.get_extra("_ks_rw_ctx")
        if not ctx:
            if not strict:
                return
            # 这一轮没记上下文（rewrite_snapshot 没跑到 / 出错）：只拿对方这句给回复器
            title0 = event.get_extra("_ks_rw_title") or self._titles(event)[0]
            ctx = [f"{title0}：" + (event.message_str or "").replace("\n", " / ")[:160]]
            event.set_extra("_ks_rw_title", title0)
            self.log.info("kaju_style: 这一轮没记上下文，只拿对方这句给回复器")
        event.set_extra("_ks_rw_ctx", None)  # 一轮只写一次
        event.set_extra("_ks_rw_done", True)
        _REPLYER_CTX.set(event.get_extra("_ks_rw_replyer") or None)  # 回复器看的前文（群聊 50 行、私聊 20 行）
        _HOW.set(event.get_extra("_ks_how") or "")
        cfg = self._sec("rewrite")
        # 已经回晚了（模型卡过、群里排着队）：写 + 核对还要 3~4 秒，先把话发出去（只发回复器的话时不跳过）
        try:
            late = 0.0 if strict else float(cfg.get("skip_when_late", 25) or 0)
            arrived = float(event.get_extra("_kaju_quote_t") or 0)  # kaju_basics 记的这条消息到达时间
        except (TypeError, ValueError):
            late, arrived = 0.0, 0.0
        if late > 0 and (event.get_extra("_kaju_felt") or event.get_extra("kaju_docs_read")):
            # 这一轮她是看完视频 / 听完歌 / 读完文件才回的：等的时间本来就花在看上，不算"回晚了"。
            late = 0.0
        if late > 0 and arrived and time.time() - arrived > late:
            self.log.info(f"kaju_style: 写的这层跳过（这条已经等了 {time.time() - arrived:.0f}s，先快点回）")
            return
        draft, tags = rewrite.split_tags(getattr(resp, "completion_text", "") or "")
        title = event.get_extra("_ks_rw_title") or ""
        kind = "群聊" if event.get_group_id() else "私聊"
        brain_turn = bool(event.get_extra("_ks_brain"))
        plan = None
        if brain_turn:  # 主模型这一轮当的是大脑：回来的应该是 JSON 指导（brain.py）
            plan = brain.parse(draft)
            if plan is not None and kind != "群聊" and not plan.get("局面"):
                plan = None  # 私聊一律回：只写了“不回”不算
            self._rec.note("brain", {"plan": plan, "raw": None if plan else draft[:500]})
            if plan is None:
                self.log.info(f"kaju_style: 大脑没给出指导，拿同一份材料再问一遍 {draft[:60]!r}")
                plan = await self._rethink(event, draft)
            elif kind == "群聊":  # 想的时候群里又来了：重想一遍（11-18 晚）
                plan = await self._replan(event, plan)
                more = event.get_extra("_ks_replan_ctx")
                if more:
                    ctx = list(ctx) + list(more)
            if plan is not None and kind == "群聊" and plan.get("回不回") != "不回":  # 没人叫她的轮次：发之前单独把一下关
                plan = await self._action_judge(event, plan, ctx)
        elif not draft.strip() or "[SKIP" in draft.upper():
            if strict:  # 这一轮没换成大脑、主模型自己说了不回
                self._hush(event, resp)
            return
        else:  # 这一轮没换成大脑（换提示时出错）：回来的是她的话的草稿，整理成指导
            try:
                plan = await self._plan_from_draft(ctx, draft, kind, title)
            except Exception as e:  # noqa: BLE001
                self.log.info(f"kaju_style: 草稿整理成指导没成 {type(e).__name__}: {str(e)[:60]}")
        if plan is None:
            if not strict:
                return  # writer_only 关着：照发主模型的原话
            busy = ""
            if kind != "群聊":  # 11-21 兄长：私聊说一句在忙（群里照旧不说）
                try:
                    busy = await self._busy_line(event, ctx, title, kind)
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_style: 说在忙那句也没写成 {type(e).__name__}: {str(e)[:60]}")
            if busy:
                self.log.warning(f"kaju_style: 大脑两遍都没给出指导，先说一句在忙 {busy[:40]!r}")
                event.set_extra("kaju_style_busy", True)
                resp.completion_text = busy
                event.set_extra("kaju_style_rewritten", {"draft": draft, "new": busy})
                return
            self.log.warning(f"kaju_style: 大脑两遍都没给出指导，{'群里' if kind == '群聊' else ''}这次不说")
            event.set_extra("kaju_style_rewritten", {"draft": draft, "new": ""})  # 历史里别留下它写的东西
            self._hush(event, resp)
            return
        event.set_extra("_ks_plan", plan)  # follow_through 看“答应：…”有没有真做（11-19：答应“去查 Hoody”却没调工具）
        if kind == "群聊" and plan.get("回不回") == "不回":
            if str(cfg.get("planner_skip", "log")) == "group":
                self.log.info(f"kaju_style: 大脑说群里这句不用回，这次不说 {plan.get('局面', '')[:40]!r}")
                event.set_extra("kaju_style_rewritten", {"draft": draft, "new": ""})  # 历史里别留下 JSON
                self._hush(event, resp)
                return
            self.log.info(f"kaju_style: 大脑说群里这句可以不回（只记，照样回） {plan.get('局面', '')[:40]!r}")
        draft = brain.reference(plan)  # 核对、改错拿“大脑定下的意思”当草稿比
        t0 = time.time()
        try:
            new = await self._write(ctx, plan, kind, title, draft)
        except Exception as e:  # noqa: BLE001
            if strict:
                self.log.warning(f"kaju_style: 回复器这边没回（这次不说） {type(e).__name__}: {e}")
                self._hush(event, resp)
                return
            self.log.warning(f"kaju_style: 回复器这边没回（发原话） {type(e).__name__}: {e}")
            return
        # 写出来不像回复、或者核对没过，就拿同一份指导再写一次（2026-11-08：线上 58 次里 14 次被拦，
        # 大半是这一遍编了/漏了，换一遍常常就对了）；核对本身出错（超时）不重写，重写也救不了
        tries = self._tries()
        # 发之前查套路（routine.py）：off 不查 / log 只记不拦（默认）/ on 撞了再写一遍，两遍里挑撞得少的
        routine_mode = str(cfg.get("routine", "log") or "off")
        held = None  # 核对过了、但撞了套路的那一遍 (new, hits, attempt, t1)：再写的那遍不行就发它
        done = None  # 最后要发的那一遍
        flagged = None  # 只发回复器的话：核对没过、但总归是回复器写的最后一遍
        flagged_why = ""  # 那一遍核对说的问题（改错用）
        fallback = "" if strict else "（发原话）"
        for attempt in range(tries):
            again = attempt + 1 < tries
            if attempt:
                if late > 0 and arrived and time.time() - arrived > late:
                    self.log.info("kaju_style: 来不及再写一次了" + ("" if held else fallback))
                    break
                try:
                    new = await self._write(ctx, plan, kind, title, draft)
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_style: 再写一次没回{'' if held else fallback} {type(e).__name__}: {e}")
                    break
            if not new or (not strict and new.strip() == draft.strip()):
                why = "一样" if new else "不像回复"
                self.log.info(f"kaju_style: 写的结果不用（{why}）{'，再写一次' if again else ''}")
                if again:
                    continue
                break
            if rewrite.needs_title_guard(new, title, kind) and not cfg.get("guard", True) and not strict:
                self.log.info(f"kaju_style: 兄长称呼需要核对但核对未启用（发原话） {new[:40]!r}")
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
                    self.log.info(f"kaju_style: {what}，这一遍照发 {new[:40]!r}")
                    bad = False
                if bad:
                    if strict:
                        flagged = (new, [], attempt, t1)
                        flagged_why = what
                    if again and not errored:
                        self.log.info(f"kaju_style: 核对没过（{what}），再写一次 {new[:40]!r}")
                        continue
                    self.log.info(f"kaju_style: 核对没过（{'' if held or strict else '发原话：'}{what}） {new[:40]!r}")
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
                self.log.info(f"kaju_style: 核对 {tries} 遍都没过，发最后一遍")
            else:  # 11-13 兄长：核对拦下的（编了“兄长大人好帅”）不能照发
                done = await self._after_all_rejected(event, ctx, draft, flagged, flagged_why, title, kind, tries, mode)
        if not done:
            if strict:
                self.log.warning("kaju_style: 回复器这一轮一句也没写成（这次不说）")
                self._hush(event, resp)
            return
        new, _, attempt, t1 = done
        await self._pick_emoji(event, new, plan, ctx)
        resp.completion_text = rewrite.with_tags(new, tags)
        event.set_extra("kaju_style_rewritten", {"draft": draft, "new": resp.completion_text})
        how = "照指导写" + (f"（第 {attempt + 1} 遍）" if attempt else "")
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
        """只发回复器的话（2026-11-13）：主模型连后备都失败时，AstrBot 会直接发人设里的固定句子
        （“唔…佳树刚才走神了…”）或“LLM 响应错误: …”。这句不是回复器写的 → 不发，DeepSeek 告诉兄长。"""
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
        self.notify_model_down()
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
