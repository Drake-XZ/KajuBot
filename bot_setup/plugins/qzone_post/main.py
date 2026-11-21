"""QQ 空间说说：让佳树能在自己的 QQ 空间发说说，也看得到说说下面的点赞和评论。

- post_qzone 工具：管理员让她发时直接发；她自己觉得值得记录时也能主动发（有频率限制）。
- 通过 OneBot 的 get_cookies 拿 QQ 空间 cookie，再调用 QQ 空间的发表接口。
- 每次请求 LLM 前注入使用规则和最近发过的说说，避免重复、避免没发却说“发好了”。
- 互动（interact.*，1.1.0）：后台每几分钟看一眼最近的说说。
  · 有人新点了赞 → 交给 kaju_heart 加一点好感（照它的规则：越高越难涨、每天有上限），记成"刚才的事"；
    下次跟这个人聊天时提示里写一句"TA给你的说说点了赞"（只提一次）。
  · 有人评论 / 在楼里回她 → 当成"这个人发来的私聊"送进 AstrBot 的完整流程（turn.py），和私聊一样回
    （人设、记忆、心情、好感判断、日记都照常），回复截下来发到评论区（SnowLuma comment_qzone，回到那一楼）。
  · qzone_activity 工具：她自己翻看最近的点赞和评论。
- 每晚的说说（nightly.*，1.2.0）：插件自己到点（默认 22:30）走 选材 → 写 → 核对 → 过了才发，见 nightly.py。
  nightly.mode：off = 不管（旧的定时任务照旧）；draft = 只写好、核对、记下来，不发（管理员 /佳树说说 看、/佳树说说 发）；
  post = 核对过了就发。draft / post 时旧的 AstrBot 定时任务调 post_qzone 会被挡掉，不会发两条。
  对话里她自己想发（self_initiated）也先过一遍同样的硬伤检查 + 模型核对；管理员让发的只查硬伤。
"""

import asyncio
import datetime as dt
import json
import os
import time
import zoneinfo

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from kaju_core import paths, people

from . import interact, nightly, turn

PLUGIN_NAME = "astrbot_plugin_qzone_post"
MAX_LEN = 500
PUBLISH_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"
LIKES_URL = "https://user.qzone.qq.com/proxy/domain/users.qzone.qq.com/cgi-bin/likes/get_like_list_app"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_RECENT = 120

COMMENT_NOTE = (
    "\n\n【QQ空间评论】这一轮不是私聊：{name}在你的QQ空间说说下面给你留言了。你这次的回复会作为评论区里的回复"
    "公开发出去，谁都能看到。\n"
    "- 你的这条说说：「{post}」\n"
    "- 这一楼（从早到晚）：\n{thread}\n"
    "- 像平时跟TA聊天一样回TA最后这几句，语气、称呼照旧；只写一两句，合起来 60 字以内，会拼成一条评论。\n"
    "- 这是公开的地方：不提私聊里的私事、别人的事、QQ 号；不发表情包；这一轮不要调用工具（不发说说、不去私聊或群里发消息）。\n"
    "- 如果这几句其实不是在跟你说话、或者没什么好回的，就只回 [SKIP]。"
)


class NotLoggedIn(RuntimeError):
    """QQ 空间接口 code=-3000：这份 cookie 它不认了。"""


def _why(exc: BaseException) -> str:
    """日志里看得懂的原因：超时这类 str() 是空的；OneBot 的 ActionFailed 取 wording。"""
    result = getattr(exc, "result", None)
    wording = result.get("wording") if isinstance(result, dict) else None
    msg = str(wording or exc).strip()
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def _data(res):
    """aiocqhttp 的 call_action 一般直接给 data；HTTP 调用会带 status/retcode 外壳。"""
    if isinstance(res, dict) and "retcode" in res and "data" in res:
        return res["data"]
    return res


@register(PLUGIN_NAME, "dsh", "让机器人在自己的 QQ 空间发说说，看到点赞和评论（点赞加好感、评论像私聊一样回；每晚选材写说说、核对过才发）", "1.2.1")
class QzonePost(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        folder = paths.self_dir(PLUGIN_NAME)
        os.makedirs(folder, exist_ok=True)
        self._path = os.path.join(folder, "posts.json")
        self._ipath = os.path.join(folder, "interact.json")
        self._lock = asyncio.Lock()
        self._ilock = asyncio.Lock()
        try:
            with open(self._path, encoding="utf-8") as f:
                self._posts: list[dict] = json.load(f)
        except FileNotFoundError:
            self._posts = []
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: failed to read post log: {exc}")
            self._posts = []
        self._istate = self._load_istate()
        self._npath = os.path.join(folder, "nightly.json")
        self._nstate = self._load(self._npath, {})
        self._nstate.setdefault("last_day", "")
        self._nstate.setdefault("runs", [])
        self._nlock = asyncio.Lock()
        # 按 AstrBot 配置的时区（北京时间）显示时间、算"今天"；服务器本机是当地时间（不是北京时间）
        try:
            self._tz = zoneinfo.ZoneInfo(self.context.get_config().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))
        self._ck: tuple[str, str, int, float] | None = None  # 留着用的 QQ 空间 cookie（cookies, uin, g_tk, 拿到的时间）
        self._ifails = 0  # 看说说互动连着出错几次（出错就隔久一点再看）
        self._task: asyncio.Task | None = None
        self._ntask: asyncio.Task | None = None
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._interact_loop())
            self._ntask = loop.create_task(self._nightly_loop())
        except RuntimeError:  # 离线测试直接构造，没有事件循环
            pass

    def _fmt(self, ts: float, fmt: str) -> str:
        return dt.datetime.fromtimestamp(ts, self._tz).strftime(fmt)

    @staticmethod
    def _load(path: str, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: 读不了 {path}: {exc}")
            return default

    @staticmethod
    def _dump(path: str, data) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def _ncfg(self, key: str, default):
        v = (self.config.get("nightly") or {}).get(key, default)
        if v is None or v == "":
            return default
        try:
            return type(default)(v)
        except (TypeError, ValueError):
            return default

    def _nmode(self) -> str:
        m = str(self._ncfg("mode", "draft")).strip().lower()
        return m if m in ("off", "draft", "post") else "draft"

    def _icfg(self, key: str, default):
        v = (self.config.get("interact") or {}).get(key, default)
        if v is None or v == "":
            return default
        try:
            return type(default)(v)
        except (TypeError, ValueError):
            return default

    # ---------- interaction state ----------
    def _load_istate(self) -> dict:
        try:
            with open(self._ipath, encoding="utf-8") as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: failed to read interact state: {exc}")
            st = {}
        st.setdefault("init", False)   # 第一次看：已有的赞和评论只记下，不算新的
        st.setdefault("likes", {})     # tid → [uin]
        st.setdefault("seen", {})      # 评论 key → 处理时间
        st.setdefault("tries", {})     # 评论 key → 回复失败次数
        st.setdefault("recent", [])    # 最近的互动 {t, kind like|comment|reply, uin, name, tid, post, text, noticed}
        return st

    def _save_istate(self) -> None:
        st = self._istate
        cutoff = time.time() - 60 * 86400
        st["seen"] = {k: v for k, v in st["seen"].items() if v >= cutoff}
        st["recent"] = st["recent"][-MAX_RECENT:]
        tmp = self._ipath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._ipath)

    # ---------- QQ helpers ----------
    def _bot(self, event: AstrMessageEvent | None = None):
        bot = getattr(event, "bot", None) if event is not None else None
        platform = self.context.get_platform("aiocqhttp")
        if bot is None and platform is not None:
            bot = platform.get_client()
        return platform, bot

    async def _cookies(self, bot, fresh: bool = False) -> tuple[str, str, int]:
        """QQ 空间 cookie。SnowLuma 每次 get_cookies 都重新走一遍 QQ 登录跳转（5~10 秒），
        每 5 分钟拿一次会被 QQ 空间限流、偶尔拿回"没登录"的 cookie（-3000）。
        所以拿到的先留着用（cookie_hours），接口说没登录时再 fresh=True 重拿；重拿失败就先用旧的。"""
        ttl = self._icfg("cookie_hours", 6.0) * 3600
        if not fresh and self._ck and time.time() - self._ck[3] < ttl:
            return self._ck[:3]
        try:
            res = _data(await bot.call_action("get_cookies", domain="user.qzone.qq.com"))
            cookies = str(res.get("cookies", "") if isinstance(res, dict) else "")
            kv = dict(p.split("=", 1) for p in cookies.split("; ") if "=" in p)
            skey = kv.get("p_skey") or kv.get("skey")
            uin = (kv.get("uin") or kv.get("p_uin") or "").lstrip("o").lstrip("0")
            if not skey or not uin:
                raise RuntimeError("cookie missing p_skey/uin")
        except Exception as exc:  # noqa: BLE001
            if self._ck:
                logger.info(f"qzone_post: 重拿 cookie 没成（{_why(exc)}），先用旧的")
                return self._ck[:3]
            raise
        h = 5381
        for c in skey:
            h += (h << 5) + ord(c)
        self._ck = (cookies, uin, h & 0x7FFFFFFF, time.time())
        return self._ck[:3]

    # ---------- prompt ----------
    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        if event.get_platform_name() != "aiocqhttp":
            return
        qz = event.get_extra(turn.QZ_KEY)
        if qz:  # QQ 空间评论那一轮：只讲评论区的规矩
            req.system_prompt = (req.system_prompt or "") + COMMENT_NOTE.format(
                name=qz.get("name", "TA"), post=qz.get("post", "")[:200],
                thread="\n".join("  " + x for x in qz.get("thread") or []))
            return
        auto_on = bool(self.config.get("auto_post_enabled", True))
        lines = [
            "",
            "【QQ空间说说】",
            "- 你有自己的 QQ 空间，可以用 post_qzone 工具发说说。只有工具返回“发布成功”才算真的发出去了；"
            "没调用工具、或工具返回失败时，绝对不要说“已经发好了”。",
            "- 管理员（兄长大人）让你发说说时：按TA的意思写好内容，调用 post_qzone（self_initiated=false），发完再开心地告诉TA。"
            "其他人让你发，不能用 self_initiated=false，可以婉拒，或者你自己也真心觉得值得记录才发。",
        ]
        if auto_on:
            lines.append(
                "- 你也可以主动记录：遇到自己真心觉得值得纪念的事（第一次做到什么、被兄长大人夸、约定、节日、特别开心或难过的时刻），"
                "可以顺手发一条，self_initiated=true。普通闲聊不要发，一天最多一两条，宁缺毋滥。主动发完后在回复里轻轻提一句就好。"
            )
        lines.append(
            "- 说说是公开的，用佳树的第一人称自然地写，长短按内容决定，可以一起写相关的事和自己的感受、愿望；"
            "不要写 QQ 号、真名、群名，不要贴别人的聊天原话或隐私。"
        )
        lines.append("- 想知道说说下面谁点了赞、谁留了言，用 qzone_activity 看。评论区的留言你会自己回，不用在这里再回一遍。")
        recent = self._recent_topics(3)
        if recent:
            lines.append("- 你最近发过的说说写过这些（别重复，也别照着以前的格式写）：")
            lines += [f"  - {x}" for x in recent]
        # 这个人最近给她的说说点了赞：提一次
        sender = str(event.get_sender_id() or "")
        hours = self._icfg("like_notice_hours", 48.0)
        likes = [x for x in self._istate["recent"] if x.get("kind") == "like" and x.get("uin") == sender
                 and not x.get("noticed") and time.time() - x["t"] < hours * 3600]
        if likes:
            posts = "、".join(f"「{x['post']}」" for x in likes[-3:])
            lines.append(f"- 对方最近给你的说说点了赞：{posts}。你看到了、心里挺开心；想提可以自然地提一句，不用特意道谢。")
            for x in likes:
                x["noticed"] = True
            try:
                self._save_istate()
            except Exception:  # noqa: BLE001
                pass
        req.system_prompt = (req.system_prompt or "") + "\n".join(lines)

    @filter.on_agent_done()
    async def mark_done(self, event: AstrMessageEvent, run_context, response):
        """评论那一轮：记下她回完了（出错就不发到评论区）。"""
        if event.get_extra(turn.QZ_KEY) and not event.get_extra(turn.DONE_KEY):
            event.set_extra(turn.DONE_KEY, {"t": time.time(), "err": getattr(response, "role", "") == "err"})

    # ---------- tools ----------
    @filter.llm_tool(name="post_qzone")
    async def post_qzone(self, event: AstrMessageEvent, content: str, self_initiated: bool):
        """在你自己的 QQ 空间发一条说说（公开可见）。

        Args:
            content(string): 说说正文，用你自己的第一人称口吻，500 字以内
            self_initiated(boolean): 是你自己想记录的填 true；是管理员要求你发的填 false
        """
        content = str(content or "").strip()
        if event.get_extra(turn.QZ_KEY):
            return "没发：现在是在回评论区的留言，这一轮不发说说。直接回留言就好。"
        if not content:
            return "没发：内容是空的。"
        if len(content) > MAX_LEN:
            return f"没发：内容超过 {MAX_LEN} 字了，精简一下再发。"

        sender_id = str(event.get_sender_id() or "")
        if not self_initiated and not event.is_admin():
            return "没发：只有管理员能直接要求你发说说。可以用佳树的口吻婉拒，或者如果你自己真心想记录，再用 self_initiated=true。"
        if type(event).__name__ == "CronMessageEvent" and self._nmode() != "off":
            logger.info("qzone_post: 旧的定时任务想发说说，挡掉了（每晚的说说现在走 nightly）")
            return "没发：每晚的说说现在由佳树自己的流程写，这次不用发。不用回复任何人。"

        now = time.time()
        if self_initiated:
            if not self.config.get("auto_post_enabled", True):
                return "没发：主动发说说的功能被关掉了。就当没这回事，正常聊天。"
            why = self._auto_limit(now)
            if why:
                return f"没发：{why}。不用提这件事，正常聊天。"

        probs = self._hard_problems(content)
        if not probs and self_initiated:
            probs = await self._chat_check(event, content)
        if probs:
            logger.info(f"qzone_post: 没过检查，没发 {content[:40]!r}：{'；'.join(probs)}")
            tail = "改掉这些再发，或者就不发了。" if self_initiated else "如实告诉兄长大人哪里不合适，问他要不要改。"
            return "没发：发布前检查没通过——" + "；".join(probs) + "。" + tail

        ok, info = await self._publish(content, bool(self_initiated), sender_id, bot=self._bot(event)[1])
        if not ok:
            return f"没发成功：{info}。如实告诉对方没发出去，可以过会儿再试。"
        return "发布成功，已经发到你的 QQ 空间了。现在用佳树的口吻自然地回应一下。"

    def _auto_limit(self, now: float) -> str:
        """主动发的频率限制（对话里主动发、每晚的说说一起算）；没超返回 ''。"""
        limit = int(self.config.get("auto_daily_limit", 2))
        gap_h = float(self.config.get("auto_min_interval_hours", 4))
        auto = [p for p in self._posts if p.get("self_initiated")]
        today = self._fmt(now, "%Y-%m-%d")
        if sum(1 for p in auto if self._fmt(p["time"], "%Y-%m-%d") == today) >= limit:
            return "今天主动发的说说已经够多了"
        if auto and now - auto[-1]["time"] < gap_h * 3600:
            return "离上一条主动发的说说太近了"
        return ""

    async def _publish(self, content: str, self_initiated: bool, by: str, topics=None, source: str = "",
                       bot=None) -> tuple[bool, str]:
        """真的发到 QQ 空间并记下来。(成功?, tid 或出错原因)。"""
        if bot is None:
            bot = self._bot()[1]
        if bot is None:
            return False, "现在连不上 QQ"
        now = time.time()
        try:
            cookies, uin, g_tk = await self._cookies(bot, fresh=True)  # 一天才一两条，发之前拿新的稳一点
            form = {
                "syn_tweet_verson": "1",
                "paramstr": "1",
                "who": "1",
                "con": content,
                "feedversion": "1",
                "ver": "1",
                "ugc_right": "1",
                "to_sign": "0",
                "hostuin": uin,
                "code_version": "1",
                "format": "json",
                "qzreferrer": f"https://user.qzone.qq.com/{uin}",
            }
            headers = {
                "Cookie": cookies,
                "Referer": f"https://user.qzone.qq.com/{uin}",
                "Origin": "https://user.qzone.qq.com",
                "User-Agent": UA,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    PUBLISH_URL,
                    params={"g_tk": str(g_tk)},
                    data=form,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    text = await resp.text()
            body = text[text.find("{") : text.rfind("}") + 1]
            data = json.loads(body) if body else {}
            if data.get("code") != 0 or not data.get("tid"):
                raise RuntimeError(f"code={data.get('code')} msg={data.get('message') or text[:120]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: publish failed: {exc}")
            return False, "QQ 空间那边出错了"

        rec = {"time": int(now), "content": content, "tid": data.get("tid"),
               "self_initiated": bool(self_initiated), "by": by}
        if topics:
            rec["topics"] = list(topics)
        if source:
            rec["source"] = source
        async with self._lock:
            self._posts.append(rec)
            self._posts = self._posts[-200:]
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._posts, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        # 新说说：点赞名单从空开始算，之后点的赞都是新的
        self._istate["likes"].setdefault(str(data.get("tid")), [])
        logger.info(f"qzone_post: posted tid={data.get('tid')} self_initiated={self_initiated} by={by} {source}")
        return True, str(data.get("tid"))

    @filter.llm_tool(name="qzone_activity")
    async def qzone_activity(self, event: AstrMessageEvent, days: int = 3):
        """看看你自己 QQ 空间的说说最近有谁点了赞、谁留了言、你回了什么。

        Args:
            days(number): 看最近几天，默认 3
        """
        try:
            days = max(1, min(int(days or 3), 14))
        except (TypeError, ValueError):
            days = 3
        cutoff = time.time() - days * 86400
        rows = [x for x in self._istate["recent"] if x["t"] >= cutoff]
        if not rows:
            return f"最近 {days} 天说说下面没有新的点赞和留言。"
        out = []
        for x in rows[-30:]:
            when = self._fmt(x["t"], "%m-%d %H:%M")
            if x["kind"] == "like":
                out.append(f"{when} {x['name']} 赞了「{x['post']}」")
            else:
                line = f"{when} {x['name']} 在「{x['post']}」下说：{x.get('text', '')}"
                if x.get("her"):
                    line += f" → 你回：{x['her']}"
                out.append(line)
        return "\n".join(out) + "\n（这些是公开的；跟人说起时别报 QQ 号。）"

    # ---------- background: likes & comments ----------
    async def _interact_loop(self) -> None:
        await asyncio.sleep(self._icfg("start_delay_seconds", 90.0))
        while True:
            poll = max(1.0, self._icfg("poll_minutes", 5.0))
            wait = poll
            if self._icfg("enable", True):
                try:
                    async with self._ilock:
                        await self.check_interactions()
                    self._ifails = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # QQ 空间限流 / 没登录 / 连不上：多半过一阵就好，隔久一点再看（5→10→20→40→60 分钟），别一直刷
                    self._ifails += 1
                    wait = min(poll * 2 ** self._ifails, max(poll, self._icfg("max_backoff_minutes", 60.0)))
                    logger.warning(f"qzone_post: 看说说互动出错（连着第 {self._ifails} 次）{_why(exc)}，"
                                   f"{wait:.0f} 分钟后再看")
            await asyncio.sleep(wait * 60)

    async def _likers(self, cookies: str, uin: str, g_tk: int, tid: str) -> list[dict]:
        params = {"uin": uin, "unikey": f"http://user.qzone.qq.com/{uin}/mood/{tid}", "begin_uin": 0,
                  "query_count": 60, "if_first_page": 1, "g_tk": g_tk}
        headers = {"Cookie": cookies, "Referer": f"https://user.qzone.qq.com/{uin}", "User-Agent": UA}
        # QQ 空间慢的时候第一下要 16 秒多，原来 15 秒就放弃了
        async with aiohttp.ClientSession() as session:
            async with session.get(LIKES_URL, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=self._icfg("like_timeout_seconds", 30.0))) as resp:
                raw = await resp.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:  # 出错时 QQ 空间回的是 GBK
            text = raw.decode("gb18030", errors="replace")
        body = text[text.find("{"): text.rfind("}") + 1]
        if not body:
            raise RuntimeError(f"like list 回的不是 JSON：{text[:80]!r}")
        data = json.loads(body)
        if data.get("code") == -3000:
            raise NotLoggedIn(f"like list code=-3000 {data.get('message')}")
        if data.get("code") != 0:
            raise RuntimeError(f"like list code={data.get('code')} {data.get('message')}")
        return (data.get("data") or {}).get("like_uin_info") or []

    async def _read_likes(self, bot, ck: dict, tid: str):
        """读一条说说的点赞名单；读不到返回 None。ck 是这一轮共用的 {cookie, refreshed, stop, errors}。
        cookie 不认了（-3000）就重拿一次再试；重拿的也不认，这一轮剩下的说说都不读了（读也是白读，还招限流）。"""
        if ck["stop"]:
            return None
        for attempt in range(2):
            try:
                cookies, uin, g_tk = ck["cookie"]
                return await self._likers(cookies, uin, g_tk, tid)
            except NotLoggedIn as exc:
                if ck["refreshed"] or attempt:
                    ck["errors"].append(f"{tid}: {_why(exc)}")
                    ck["stop"] = True
                    self._ck = None
                    return None
                ck["refreshed"] = True
                try:
                    ck["cookie"] = await self._cookies(bot, fresh=True)
                except Exception as exc2:  # noqa: BLE001
                    ck["errors"].append(f"{tid}: 重拿 cookie 失败 {_why(exc2)}")
                    ck["stop"] = True
                    return None
            except Exception as exc:  # noqa: BLE001
                ck["errors"].append(f"{tid}: {_why(exc)}")
                return None
        return None

    def _heart(self):
        for meta in self.context.get_all_stars() or []:
            star = getattr(meta, "star_cls", None)
            if star is not None and hasattr(star, "feel_outside"):
                return star
        return None

    async def check_interactions(self) -> dict:
        """看一遍最近的说说：新的赞 → 好感；新的评论 → 回。返回这次的统计（日志/测试用）。"""
        platform, bot = self._bot()
        if bot is None:
            return {"skip": "no bot"}
        st = self._istate
        cookie = await self._cookies(bot)
        self_uin = cookie[1]
        ck = {"cookie": cookie, "refreshed": False, "stop": False, "errors": []}
        now = time.time()
        res = _data(await bot.call_action("get_qzone_msg_list", target_uin=int(self_uin), pos=0,
                                          num=self._icfg("scan_posts", 10)))
        posts = [p for p in (res or {}).get("msglist") or []
                 if now - int(p.get("time") or 0) < self._icfg("scan_days", 14.0) * 86400]
        first = not st["init"]
        stats = {"likes": 0, "comments": 0, "replied": 0}
        new_likes: dict[str, list] = {}
        pending: list[tuple[dict, dict]] = []
        for p in posts:
            tid = str(p.get("tid") or "")
            content = str(p.get("content") or "")
            likers = await self._read_likes(bot, ck, tid)
            if likers is not None:
                prev = st["likes"].get(tid)
                fresh = interact.new_likers(prev, likers, self_uin)
                st["likes"][tid] = sorted(set(prev or []) | {x["uin"] for x in fresh})
                # 第一次看：已有的赞只记下。之后：已经在看的说说上新来的赞都算；刚进来的说说只有一天内发的才算
                counts = not first and (prev is not None or now - int(p.get("time") or 0) < 86400)
                if counts:
                    for x in fresh:
                        new_likes.setdefault(x["uin"], []).append((x["nick"], content))
            if int(p.get("comment_num") or 0) <= 0:
                continue
            detail = _data(await bot.call_action("get_qzone_msg_detail", tid=tid, pos=0, num=50))
            max_age = self._icfg("max_age_hours", 24.0) * 3600
            items, skip = interact.scan(detail or {}, self_uin, st["seen"], now, 0 if first else max_age)
            for k in skip:
                st["seen"][k] = now
            for it in items:
                pending.append((it, {"post": content, "tid": tid}))
        st["init"] = True
        if ck["errors"]:  # 一轮只报一行，别一条说说一行
            skipped = "，剩下的这轮先不读" if ck["stop"] else ""
            logger.warning(f"qzone_post: 读点赞失败 {len(ck['errors'])}/{len(posts)} 条{skipped}；"
                           f"例如 {ck['errors'][0]}")

        # 点赞：一个人这次赞了几条，合成一次加好感
        heart = self._heart()
        per_like = self._icfg("like_affection", 1.0)
        umo_base = f"{platform.meta().id}:FriendMessage:" if platform is not None else ""
        for uin, got in new_likes.items():
            nick = got[-1][0]
            briefs = "、".join(f"「{interact.brief(c, 16)}」" for _, c in got[:3])
            for _, c in got:
                st["recent"].append({"t": now, "kind": "like", "uin": uin, "name": nick, "post": interact.brief(c, 24)})
            stats["likes"] += len(got)
            logger.info(f"qzone_post: {nick}({uin}) 赞了 {briefs}")
            if heart is not None and per_like > 0:
                try:
                    await heart.feel_outside(
                        uin, nick, affection=min(3.0, per_like * len(got)), emotion="开心",
                        intensity=1, cause=f"{nick}给你的说说{briefs}点了赞", reason="给说说点赞",
                        umo=umo_base + uin)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"qzone_post: 点赞加好感失败 {exc}")
        self._save_istate()

        # 评论：一条条走她的聊天流程回
        budget = self._icfg("max_replies_per_poll", 3)
        for it, ctx in pending:
            stats["comments"] += len(it["texts"])
            if not self._icfg("reply_comments", True) or budget <= 0:
                if not self._icfg("reply_comments", True):
                    for k in it["keys"]:
                        st["seen"][k] = now
                continue
            budget -= 1
            ok = await self._answer(platform, bot, self_uin, it, ctx)
            stats["replied"] += 1 if ok else 0
            self._save_istate()
        return stats

    async def _answer(self, platform, bot, self_uin: str, it: dict, ctx: dict) -> bool:
        """一条评论（同一人同一楼的几句）：送进她的聊天流程，把回复发到评论区。"""
        st = self._istate
        now = time.time()
        text = interact.message_text(it, ctx["post"])
        extra = {"name": it["name"], "post": ctx["post"], "thread": it["thread"], "tid": it["tid"]}
        for k in it["keys"]:
            st["recent"].append({"t": now, "kind": "reply" if it["is_reply"] else "comment", "uin": it["uin"],
                                 "name": it["name"], "post": interact.brief(ctx["post"]), "text": " / ".join(it["texts"])})
        rec = st["recent"][-1]
        logger.info(f"qzone_post: {it['name']}({it['uin']}) 在说说 {it['tid']} 下：{' / '.join(it['texts'])[:80]}")
        try:
            ev = turn.make_event(platform, bot, self_uin, it["uin"], it["name"], text, extra)
            status, parts = await turn.run(platform, ev, self._icfg("reply_timeout_seconds", 240.0))
        except Exception as exc:  # noqa: BLE001
            status, parts = "error", []
            logger.warning(f"qzone_post: 评论这一轮没跑起来 {type(exc).__name__}: {exc}")
        reply = interact.join_reply(parts) if status == "ok" else ""
        sent = False
        if reply:
            params = {"tid": it["tid"], "content": reply, "comment_id": it["comment_id"],
                      "comment_uin": int(it["comment_uin"])}
            if it.get("reply_to"):
                params.update(reply_uin=int(it["reply_to"]["uin"]), reply_name=it["reply_to"]["name"])
            try:
                await bot.call_action("comment_qzone", **params)
                sent = True
                rec["her"] = reply
                logger.info(f"qzone_post: 回了评论：{reply}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"qzone_post: 回评论失败 {type(exc).__name__}: {exc}")
        elif status == "ok":
            logger.info("qzone_post: 她觉得这条不用回（[SKIP] 或没说话）")
        else:
            logger.warning(f"qzone_post: 评论这一轮结果 {status}，这次不回")
        done = sent or status == "ok"
        for k in it["keys"]:
            if done:
                st["seen"][k] = now
                st["tries"].pop(k, None)
            else:  # 出错了下次再试，最多 2 次
                st["tries"][k] = int(st["tries"].get(k, 0)) + 1
                if st["tries"][k] >= 2:
                    st["seen"][k] = now
                    st["tries"].pop(k, None)
        return sent

    # ---------- checks shared by the tool and the nightly post ----------
    def _recent_topics(self, n: int) -> list[str]:
        """最近 n 条说说的话题（每晚流程记下的 topics；以前的说说只给开头几个字），不给原文，免得照抄格式。"""
        out = []
        for p in reversed(self._posts[-n:]):
            day = self._fmt(p["time"], "%m-%d")
            what = "、".join(p["topics"]) if p.get("topics") else interact.brief(p.get("content", ""), 14)
            out.append(f"{day}：{what}")
        return out

    def _owner(self) -> str:
        if people.owner():  # 身份表（kaju_core.people）
            return people.owner()
        for meta in self.context.get_all_stars() or []:
            star = getattr(meta, "star_cls", None)
            if star is not None and hasattr(star, "address_of"):
                owner = str(getattr(star, "owner", "") or "").strip()
                if owner:
                    return owner
        admins = [str(a) for a in (self.context.get_config().get("admins_id") or []) if str(a).isdigit()]
        return admins[0] if admins else ""

    def _known_names(self) -> tuple[list[str], list[str]]:
        """(别人的昵称和称呼, 群名)：从 kaju_life 记下的名字和称呼簿里来，公开的说说里都不该出现。"""
        names_js = self._load(os.path.join(paths.self_dir("kaju_life"), "names.json"), {})
        addr = self._load(os.path.join(paths.self_dir("address_book"), "addresses.json"), {})
        names = set((names_js.get("people") or {}).values())
        owner = self._owner()
        for qq, v in addr.items():
            if qq != owner and isinstance(v, dict) and v.get("address"):
                names.add(str(v["address"]))
        groups = [str(g) for g in (names_js.get("groups") or {}).values()]
        return sorted(n for n in names if n), groups

    def _hard_problems(self, content: str, others_lines=()) -> list[str]:
        names, groups = self._known_names()
        olds = [p.get("content", "") for p in self._posts[-30:]] + nightly.EXAMPLES
        return nightly.check_hard(content, others_lines=others_lines, names=names, groups=groups, old_posts=olds)

    async def _ask(self, system: str, prompt: str, timeout: float) -> str:
        prov = await self.context.get_using_provider_async()
        if prov is None:
            raise RuntimeError("没有可用的模型")
        pid = (getattr(prov, "provider_config", None) or {}).get("id") or prov.meta().id
        resp = await asyncio.wait_for(
            self.context.llm_generate(chat_provider_id=pid, prompt=prompt, system_prompt=system), timeout=timeout)
        return getattr(resp, "completion_text", "") or ""

    def _today(self, now: float | None = None) -> tuple[str, float]:
        when = dt.datetime.fromtimestamp(now or time.time(), self._tz)
        return nightly.day_window(when, self._ncfg("day_start_hour", 5))

    async def _chat_check(self, event: AstrMessageEvent, content: str) -> list[str]:
        """对话里她自己想发：拿这个聊天今天的记录当素材，让模型核对事实和隐私。核对不成就当没通过。"""
        day, _ = self._today()
        gid, sid = str(event.get_group_id() or ""), str(event.get_sender_id() or "")
        chat = f"g{gid}" if gid else f"p{sid}"
        path = os.path.join(paths.self_dir("kaju_life"), "log", day + ".jsonl")
        recs = [r for r in nightly._read_jsonl(path) if r.get("c") == chat][-40:]
        owner = self._owner()
        items = []
        for r in recs:
            who = "佳树" if r.get("u") == "self" else ("兄长大人" if str(r.get("u")) == owner else (r.get("n") or "别人"))
            items.append({"id": len(items) + 1, "kind": "群聊" if gid else "私聊", "t": r.get("t", ""),
                          "text": f"{who}：{r.get('x', '')}"})
        others = [r.get("x", "") for r in recs if r.get("u") != "self"]
        probs = self._hard_problems(content, others)
        if probs:
            return probs
        try:
            out = await self._ask(nightly.CHECK_SYSTEM, nightly.check_prompt(nightly.render_material(items), content),
                                  self._ncfg("timeout_seconds", 60.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: 发布前核对没跑成 {type(exc).__name__}: {exc}")
            return ["发布前核对没跑成"]
        res = nightly.parse_check(out)
        return ["发布前核对没跑成"] if res is None else res

    # ---------- nightly post ----------
    def _save_nstate(self) -> None:
        self._nstate["runs"] = self._nstate["runs"][-30:]
        try:
            self._dump(self._npath, self._nstate)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qzone_post: 写 nightly.json 失败 {exc}")

    def _due(self, now: float) -> bool:
        if self._nmode() == "off":
            return False
        day, _ = self._today(now)
        if self._nstate.get("last_day") == day:
            return False
        try:
            hh, mm = (int(x) for x in str(self._ncfg("at", "22:30")).split(":"))
        except ValueError:
            hh, mm = 22, 30
        local = dt.datetime.fromtimestamp(now, self._tz)
        at = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        late = (local - at).total_seconds()
        return 0 <= late <= self._ncfg("catch_up_minutes", 90.0) * 60

    async def _nightly_loop(self) -> None:
        await asyncio.sleep(self._ncfg("start_delay_seconds", 120.0))
        while True:
            try:
                if self._due(time.time()):
                    self._nstate["last_day"] = self._today()[0]  # 先记下，出错也不在同一天反复跑
                    self._save_nstate()
                    await self.run_nightly(publish=self._nmode() == "post")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"qzone_post: 每晚的说说出错 {type(exc).__name__}: {exc}")
            await asyncio.sleep(60)

    async def _local_writer(self, draft: str) -> str:
        """writer=local：交给 kaju_style（草稿整理成指导 → 回复器写 → 核对）。拿不到就用原稿。"""
        for meta in self.context.get_all_stars() or []:
            star = getattr(meta, "star_cls", None)
            if star is not None and hasattr(star, "polish") and hasattr(star, "_plan_from_draft"):
                try:
                    return (await star.polish(draft, [], "", kind="说说", split=False)).strip() or draft
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"qzone_post: 说话习惯插件没写成（用原稿） {type(exc).__name__}: {exc}")
        return draft

    async def run_nightly(self, publish: bool, now: float | None = None) -> dict:
        """走一遍 选材 → 写 → 核对；publish=True 且都过了才真的发。返回这次的记录（也存进 nightly.json）。"""
        async with self._nlock:
            now = now or time.time()
            day, since = self._today(now)
            run = {"day": day, "t": int(now), "publish": publish, "status": "skip", "reason": "", "attempts": []}
            try:
                await self._nightly_steps(run, day, since, now, publish)
            except Exception as exc:  # noqa: BLE001
                run.update(status="error", reason=f"{type(exc).__name__}: {exc}")
            self._nstate["runs"].append(run)
            self._save_nstate()
            logger.info(f"qzone_post: 每晚的说说 {day} → {run['status']}：{run.get('text') or run['reason']}")
            return run

    async def _nightly_steps(self, run: dict, day: str, since: float, now: float, publish: bool) -> None:
        timeout = self._ncfg("timeout_seconds", 60.0)
        if self.config.get("auto_post_enabled", True) is False:
            run["reason"] = "主动发说说的功能关着"
            return
        why = self._auto_limit(now)
        if why:
            run["reason"] = why
            return
        owner = self._owner()
        items = nightly.collect(paths.self_dir, owner, day, since, self._ncfg("budget", 9000), self._tz, until=now)
        run["material"] = len(items)
        if not items:
            run["reason"] = "今天没有素材（没和兄长大人私聊、没刷B站、也没有日程）"
            return
        material = nightly.render_material(items)
        d = dt.date.fromisoformat(day)
        plan = nightly.parse_plan(await self._ask(
            nightly.PLAN_SYSTEM, nightly.plan_prompt(material, self._recent_topics(self._ncfg("recent_topics", 5)),
                                                     f"{d.month}月{d.day}日"), timeout), len(items))
        if plan is None:
            run.update(status="error", reason="选材结果看不懂")
            return
        run["plan"] = plan
        if not plan["post"]:
            run["reason"] = plan["reason"] or "今天没有值得写的"
            return
        others = [it["text"].split("：", 1)[1] for it in items if it["kind"] == "私聊" and it["text"].startswith("兄长大人：")]
        feedback, text = None, ""
        for _ in range(2):
            draft = nightly.clean_post(await self._ask(nightly.write_system(), nightly.write_prompt(plan, feedback, text), timeout))
            text = draft
            if draft and self._ncfg("writer", "deepseek") == "local":
                local = nightly.clean_post(await self._local_writer(draft))
                if local and local != draft and not self._hard_problems(local, others):
                    text = local
            probs = self._hard_problems(text, others)
            if not probs:
                res = nightly.parse_check(await self._ask(nightly.CHECK_SYSTEM, nightly.check_prompt(material, text), timeout))
                probs = ["发布前核对没跑成"] if res is None else res
            run["attempts"].append({"text": text, "problems": probs})
            if not probs:
                break
            feedback = probs
        run["text"] = text
        if run["attempts"][-1]["problems"]:
            run.update(status="blocked", reason="；".join(run["attempts"][-1]["problems"]))
            return
        if not publish:
            run["status"] = "draft"
            return
        ok, info = await self._publish(text, True, "nightly", topics=plan["topics"], source="nightly")
        if ok:
            run.update(status="posted", tid=info)
        else:
            run.update(status="error", reason=info)

    @filter.command("佳树说说")
    async def nightly_cmd(self, event: AstrMessageEvent, action: str = ""):
        """管理员：/佳树说说（最近几晚的记录）｜试写（现在走一遍，只写不发）｜发（把最近一条核对过的草稿发出去）"""
        if not event.is_admin():
            return
        action = (action or "").strip()
        if action == "试写":
            yield event.plain_result("佳树想想今天写什么……（只写不发）")
            run = await self.run_nightly(publish=False)
            yield event.plain_result(self._render_run(run))
            return
        if action == "发":
            run = next((r for r in reversed(self._nstate["runs"]) if r.get("status") == "draft"), None)
            if run is None or time.time() - run["t"] > 2 * 86400:
                yield event.plain_result("没有两天内核对过、还没发的草稿。")
                return
            ok, info = await self._publish(run["text"], True, str(event.get_sender_id() or ""),
                                           topics=(run.get("plan") or {}).get("topics"), source="nightly-approved",
                                           bot=self._bot(event)[1])
            if ok:
                run.update(status="posted", tid=info)
                self._save_nstate()
            yield event.plain_result(f"发好了：{run['text']}" if ok else f"没发成功：{info}")
            return
        runs = self._nstate["runs"][-5:]
        if not runs:
            yield event.plain_result(f"还没有每晚说说的记录。现在是 {self._nmode()} 模式，{self._ncfg('at', '22:30')} 写。")
            return
        head = f"每晚的说说：{self._nmode()} 模式，{self._ncfg('at', '22:30')} 写。最近几次："
        yield event.plain_result(head + "\n\n" + "\n\n".join(self._render_run(r) for r in reversed(runs)))

    def _render_run(self, r: dict) -> str:
        status = {"skip": "没写", "blocked": "没过检查，没发", "draft": "写好了，没发（/佳树说说 发）",
                  "posted": "发了", "error": "出错"}.get(str(r.get("status")), r.get("status"))
        lines = [f"{r['day']} {self._fmt(r['t'], '%H:%M')} {status}"]
        if r.get("text"):
            lines.append(f"正文：{r['text']}")
        if r.get("reason"):
            lines.append(f"原因：{r['reason']}")
        tries = r.get("attempts") or []
        if len(tries) > 1:
            lines.append(f"第一稿：{tries[0]['text']}\n第一稿的问题：{'；'.join(tries[0]['problems'])}")
        return "\n".join(lines)

    async def terminate(self):
        for t in (self._task, self._ntask):
            if t is not None:
                t.cancel()
