"""佳树私信：别人在B站（以后还有抖音）私信她，她像在 QQ 私聊一样回。

规矩（兄长定的，2026-11-08）：
- 只回和她互关的人。别人可以随便关注她；她要关注谁（回关），得先在 QQ 上问兄长，兄长同意了才关注。
  没互关的人发来的私信先存着（ledger.held），等兄长同意、关注上、互关了再接着回。兄长说不关注的人，以后不再问。
- 兄长以外的人，每人每天最多让她看 video_per_day 条视频；多的先不看，去 QQ 问兄长，同意了再看。
- 兄长本人的B站号（owner_bili_mid）不受这些限制，而且就是他的 QQ 私聊那段聊天（在哪边聊她都记得）。

怎么做：
- 后台每 poll_seconds 秒看一眼有没有未读私信（bilidm.py，借 kaju_basics 的B站小号登录）；
  有就读出新消息、标已读，按人交给 _chat：当成这个人发来的私聊送进完整流程（turn.py），
  她说的每一句（包括看视频前那句"先去看"）都发成B站私信；表情包传到B站图床发成图片私信（_patch_memes）。
- 每 fans_minutes 分钟看一眼粉丝列表：新关注她、还没互关的人 → 登记"要不要回关"。
- 要兄长批的事攒在 ledger.requests，通知用 QQ 私聊发给兄长（安静时段不发，攒着）。
  兄长回「/佳树私信 批准 n」「/佳树私信 拒绝 n」，或者在 QQ 私聊里直接跟她说，她调 answer_dm_request。
"""

from __future__ import annotations

from kaju_core.body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import logging
import datetime as dt
import importlib
import os
import sys
import time
import zoneinfo
from kaju_core import parts, paths, people
from kaju_platforms.bili import bilidm  # noqa: E402
from kaju_platforms.douyin import douyindm  # noqa: E402
from kaju_platforms.shared import ledger  # noqa: E402
from kaju_platforms.shared.ledger import Ledger  # noqa: E402
# 原来的 from . import turn  # noqa: E402  → 外壳里



PLUGIN_NAME = "astrbot_plugin_kaju_dm"


TOOL = "answer_dm_request"
TOOL_CLAIM = "claim_same_person"  # 私信里的人说自己是 QQ 上的谁 → 问兄长
TOOL_LINK = "link_same_person"  # 兄长在 QQ 私聊里说某个私信号就是 QQ 上的谁 → 直接记
SITES = {"抖音": "douyin", "douyin": "douyin", "b站": "bili", "bili": "bili", "哔哩哔哩": "bili", "bilibili": "bili"}


BILI_PREFIX = "bili_"


DOUYIN_PREFIX = "douyin_"


DM_NOTE = (
    "\n\n【{site}私信】这一轮不是 QQ：是{who}在{site}私信你，你的回复会发成{site}私信。"
    "像平时私聊一样回就好。"
)


OVER_NOTE = (
    "\n- TA今天已经让你看了 {limit} 条视频（兄长大人定的：别人每天最多 {limit} 条），"
    "这次发来的{n}条视频你还没看，已经去 QQ 问兄长大人了，他同意了你再看。别装作看过，也别编内容。"
)


APPROVED_NOTE = "\n- 这是TA之前发来、当时没看的视频；兄长大人刚同意了，你现在看完再跟TA聊。"


HELD_NOTE = "\n- 这些是你们互关之前TA发来的私信（当时还没互关，你没回）；现在互关了，接着回TA。"


OWNER_NOTE = (
    "\n\n【等兄长大人决定的事】B站/抖音私信那边有几件事在等兄长大人点头：\n{items}\n"
    "- 兄长大人这次的话如果是在回答其中某件（比如\"关注吧\"\"可以看\"\"不用理他\"），就调用 answer_dm_request"
    "（request_id 填编号，approve 填同意或不同意），做完按工具结果简单说一句；没提到的就别管，也不用主动念给他听。"
)


def _spawn(coro, log=None):
    """后台任务：出错要记日志（不然 create_task 里的错会被悄悄吞掉）。"""
    task = asyncio.get_event_loop().create_task(coro)

    def done(t):
        if not t.cancelled() and t.exception() is not None:
            e = t.exception()
            (log or logging.getLogger("kaju.dm")).warning(f"kaju_dm: 后台任务出错 {getattr(coro, '__name__', '')}: {type(e).__name__}: {e}")
    task.add_done_callback(done)
    return task


def _tz(body):
    try:
        return zoneinfo.ZoneInfo(str(body.settings().get("timezone") or "Asia/Shanghai"))
    except Exception:  # noqa: BLE001
        return zoneinfo.ZoneInfo("Asia/Shanghai")


class DmMind:
    """KajuDm 的逻辑（AstrBot 外壳在 plugins\\kaju_dm\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        root = paths.self_dir(PLUGIN_NAME)
        self._ledger = Ledger(os.path.join(root, "state.json"))
        self._ledger.data.setdefault("started", time.time())
        self._ledger.data.setdefault("dev_id", "")
        self._locks: dict[str, asyncio.Lock] = {}
        # 连发合并（2026-11-13）：同一个人正在回的时候又来的私信先放这里，并进正在回的这一轮（inject）或者下一轮一起回
        self._inbox: dict[str, list[dict]] = {}
        self._busy: set[str] = set()
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._sem = asyncio.Semaphore(2)
        self._http = None
        self._self_id = ""
        self._patched = None  # (platform, 原来的 send_by_session)
        self._fans_at = 0.0
        self._dy = douyindm.Chat(self._dy_keeper)  # 抖音私信页（借 kaju_basics 的常驻浏览器）
        self._dy_me = ""  # 她抖音小号的 uid
        self._dy_fans_at = 0.0
        self._tasks = []
        try:
            self._ledger.save()
            self._tasks.append(_spawn(self._bili_loop(), self.log))
            self._tasks.append(_spawn(self._douyin_loop(), self.log))
            self._patch_memes()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_dm: 没起来 {type(e).__name__}: {e}")

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)
        for t in self._tasks:
            t.cancel()
        self._unpatch()
        self._unpatch_memes()
        await self._dy.close()
        if self._http is not None:
            await self._http.close()

    # ------------------------------------------------------------ 配置
    def _sec(self, name: str) -> dict:
        v = self.config.get(name)
        return v if isinstance(v, dict) else {}

    def _num(self, sec: str, k: str, default: float) -> float:
        try:
            return float(self._sec(sec).get(k, default))
        except (TypeError, ValueError):
            return default

    def _limit(self) -> int:
        try:
            return int(self.config.get("video_per_day", 3))
        except (TypeError, ValueError):
            return 3

    def _owner_mid(self, site: str = "bili") -> str:
        """兄长本人在B站（UID）/ 抖音（sec_uid）的号：身份表（kaju_core.people）；没登记时用老配置。"""
        mine = people.registry().account(people.owner(), site) if people.owner() else ""
        return mine or str(self.config.get("owner_bili_mid" if site == "bili" else "owner_douyin_uid") or "").strip()

    def _who(self, site: str, uid: str) -> str:
        """私信来的这个号是谁（会话和"发言人"都用它）：兄长本人 → 他的 QQ；身份表里认过的 → 那个人；
        都不是 → bili_<UID> / douyin_<数字 uid>（自己一段）。"""
        if uid == self._owner_mid(site):
            return self._owner_qq()
        own = f"{BILI_PREFIX}{uid}" if site == "bili" else f"{DOUYIN_PREFIX}{self._dy_num(uid)}"
        return people.registry().key(site, uid, fallback=own)

    def _on(self) -> bool:
        return bool(self.config.get("enable", True)) and bool(self._sec("bili").get("enable", True))

    def _dy_on(self) -> bool:
        return bool(self.config.get("enable", True)) and bool(self._sec("douyin").get("enable", True))

    def _dy_keeper(self):
        """kaju_basics 的抖音常驻浏览器：小号登录着、常驻开着才给。"""
        basics = self._basics()
        try:
            if basics is None or not basics._dy_logged():
                return None
            return getattr(self._kb_mod("douyin"), "KEEPER", None)
        except Exception:  # noqa: BLE001
            return None

    def _dy_num(self, uid: str) -> str:
        """抖音的人在 kaju_dm 里用 sec_uid 认；会话名用数字 uid（短一点）。"""
        return str(self._ledger.person("douyin", uid).get("uid") or uid)

    def _dy_sec(self, num: str) -> str:
        for k, p in self._ledger.data["people"].items():
            if k.startswith("douyin:") and str(p.get("uid") or "") == num:
                return k.split(":", 1)[1]
        return num

    async def _douyin_loop(self) -> None:
        await asyncio.sleep(45)
        while True:
            try:
                if self._dy_on() and self._dy_keeper() is not None:
                    self._patch()
                    self._patch_memes()
                    await self._douyin_tick()
                    await self._notify_owner()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_dm: 抖音私信轮询出错 {type(e).__name__}: {e}")
                await self._dy.close()
            await asyncio.sleep(max(8.0, self._num("douyin", "poll_seconds", 20)))

    async def _douyin_tick(self) -> None:
        """有未读的会话点开读；正开着的那个会话每轮也看一眼（开着的会话来新消息不显示未读）。"""
        started_ms = (float(self._ledger.data.get("started") or 0) - 600) * 1000
        work: dict[str, tuple] = {}
        async with self._dy.lock:
            if not self._dy_me:
                self._dy_me = await self._dy.me()
                if not self._dy_me:
                    return
            convs = {c["sec"]: c for c in await self._dy.conversations() if c.get("type") == 1}

            def take(msgs: list[dict]) -> None:
                for sec in {m["sec"] for m in msgs if m.get("sender") != self._dy_me and m.get("sec")}:
                    last = self._ledger.seq("douyin", sec)
                    seen = self._ledger.seen("douyin", sec)
                    mine = [m for m in msgs if m.get("sec") == sec]
                    new = [m for m in mine if m["t"] > last and m["t"] >= started_ms and m.get("sender") != self._dy_me
                           and not (m.get("id") and m["id"] in seen)]
                    self._ledger.set_seq("douyin", sec, max([m["t"] for m in mine] + [last]))
                    self._ledger.add_seen("douyin", sec, [m.get("id") for m in mine])
                    items = [x for x in (douyindm.to_item(m) for m in new) if x]
                    if items:
                        c = convs.get(sec) or {}
                        old = work.get(sec)
                        work[sec] = (sec, c.get("uid") or new[0].get("sender", ""), c.get("name") or "",
                                     (old[3] if old else []) + items)

            take(await self._dy.messages())
            for sec, c in convs.items():
                if c.get("badge", 0) > 0 and await self._dy.open(sec):
                    take(await self._dy.messages())
            self._ledger.save()
        for args in work.values():
            self.log.info(f"kaju_dm: 抖音私信 {args[2] or args[1]} 发来 {len(args[3])} 条")
            _spawn(self._from_douyin(*args), self.log)
        if time.time() - self._dy_fans_at > self._num("douyin", "fans_minutes", 15) * 60:
            self._dy_fans_at = time.time()
            await self._check_dy_fans()

    async def _check_dy_fans(self) -> None:
        """新关注她、还没互关的人 → 登记问兄长；存着私信的人现在互关了 → 接着回。"""
        try:
            fans = await self._dy.fans()
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_dm: 看抖音粉丝没成 {type(e).__name__}: {e}")
            fans = []
        known = self._ledger.data["known_fans"]
        for f in fans:
            sec = f["sec"]
            known.setdefault("douyin:" + sec, time.time())
            self._ledger.set_person("douyin", sec, name=f["name"], uid=f["uid"])
            if sec == self._owner_mid("douyin") or f["follow_status"] >= 1:
                continue
            if not self._ledger.refused_follow("douyin", sec):
                self._ledger.ask("follow", "douyin", sec, f["name"])
        for k in [k for k, v in self._ledger.data["held"].items() if k.startswith("douyin:") and v]:
            sec = k.split(":", 1)[1]
            if douyindm.mutual(await self._dy.profile(sec)):
                _spawn(self._release_held("douyin", sec), self.log)
        self._ledger.save()

    async def _queue(self, key: str, items: list[dict], run) -> None:
        """同一个人的私信排成一队：正在回TA时又来的几条先攒着（inject 能并进正在回的这一轮），
        这一轮回完还剩的就一起当下一轮回（不再一条一轮、各回一遍）。run(batch) 回一批。"""
        self._inbox.setdefault(key, []).extend(items)
        if key in self._busy:
            self.log.info(f"kaju_dm: {key[:24]} 正在回，又来 {len(items)} 条，先攒着一起回")
            return
        self._busy.add(key)
        try:
            while self._inbox.get(key):
                batch = self._inbox.pop(key)
                await run(batch)
        finally:
            self._busy.discard(key)

    async def _from_douyin(self, sec: str, num: str, name: str, items: list[dict]) -> None:
        await self._queue("douyin:" + sec, items, lambda batch: self._from_douyin_now(sec, num, name, batch))

    async def _from_douyin_now(self, sec: str, num: str, name: str, items: list[dict]) -> None:
        async with self._lock("douyin:" + sec):
            prof = await self._dy.profile(sec)
            self.log.info(f"kaju_dm: 抖音 {name or num} 的关系 {prof.get('follow_status')}/{prof.get('follower_status')}")
            name = prof.get("nickname") or name
            self._ledger.set_person("douyin", sec, name=name, sex=prof.get("sex"), uid=prof.get("uid") or num,
                                    t=time.time())
            self._ledger.save()
            if sec != self._owner_mid("douyin"):
                if not prof:
                    self._ledger.hold("douyin", sec, items)
                    self._ledger.save()
                    self.log.info(f"kaju_dm: 抖音 {name} 的关系没问出来，私信先存着")
                    return
                if not douyindm.mutual(prof):
                    self._ledger.hold("douyin", sec, items)
                    if prof.get("follow_status", 0) == 0 and not self._ledger.refused_follow("douyin", sec):
                        text, _ = bilidm.joined(items)
                        self._ledger.ask("follow", "douyin", sec, name, text=text)
                    self._ledger.save()
                    self.log.info(f"kaju_dm: 抖音 {name} 没互关（{prof.get('follow_status')}），私信先存着")
                    return
            await self._chat("douyin", sec, name, items)

    # ------------------------------------------------------------ 借别的插件
    def _star(self, attr: str):
        return self.body.find(attr)

    def _basics(self):
        """kaju_basics：B站小号登录（_login）和它的 bililogin / bili / douyin 模块。"""
        return self._star("_login")

    PLATFORM_MODS = {"bili": "kaju_platforms.bili.bili", "bililogin": "kaju_platforms.bili.bililogin",
                     "douyin": "kaju_platforms.douyin.douyin"}

    def _kb_mod(self, name: str):
        """B站 / 抖音的模块（kaju_platforms 里，和 kaju_basics 用的是同一个：抖音常驻浏览器 douyin.KEEPER 也在上面）。"""
        full = self.PLATFORM_MODS[name]
        return sys.modules.get(full) or importlib.import_module(full)

    def _owner_qq(self) -> str:
        if people.owner():  # 身份表（kaju_core.people）
            return people.owner()
        book = self._star("address_of")
        owner = str(getattr(book, "owner", "") or "").strip() if book else ""
        if owner:
            return owner
        admins = [str(a) for a in (self.body.settings().get("admins_id") or []) if str(a).isdigit()]
        return admins[0] if admins else ""

    def _qq(self):
        return self.body.qq()

    async def _self_qq(self, bot) -> str:
        if self._self_id:
            return self._self_id
        try:
            res = await bot.call_action("get_login_info")
            data = res.get("data", res) if isinstance(res, dict) else {}
            self._self_id = str((data or {}).get("user_id") or "")
        except Exception:  # noqa: BLE001
            pass
        if not self._self_id:
            basics = self._basics()
            allowed = ((getattr(basics, "config", None) or {}).get("guard") or {}).get("allowed_self_ids") or []
            self._self_id = str(allowed[0]) if allowed else ""
        return self._self_id

    def _client(self):
        basics = self._basics()
        store = getattr(basics, "_login", None)
        if store is None or not store.logged_in:
            return None
        if self._http is None or self._http.closed:
            import aiohttp
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        cl = bilidm.Client(self._http, store, self._kb_mod("bililogin"), self._ledger.data.get("dev_id") or "")
        if not self._ledger.data.get("dev_id"):
            self._ledger.data["dev_id"] = cl.dev_id
        return cl

    def _day(self, ts: float | None = None) -> str:
        return ledger.day_of(ts or time.time(), _tz(self.body))

    # ------------------------------------------------------------ 轮询
    async def _bili_loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                if self._on():
                    self._patch()
                    self._patch_memes()
                    await self._bili_tick()
                    await self._notify_owner()
            except asyncio.CancelledError:
                raise
            except bilidm.BiliError as e:
                if str(e.code) == "-509":  # 请求过于频繁：多歇一分钟
                    self.log.info("kaju_dm: B站说请求太频繁，歇一分钟再看")
                    await asyncio.sleep(60)
                else:
                    self.log.warning(f"kaju_dm: B站私信轮询出错 {e}")
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_dm: B站私信轮询出错 {type(e).__name__}: {e}")
            await asyncio.sleep(max(5.0, self._num("bili", "poll_seconds", 15)))

    async def _bili_tick(self) -> None:
        cl = self._client()
        if cl is None:
            return
        if time.time() - self._fans_at > self._num("bili", "fans_minutes", 10) * 60:
            self._fans_at = time.time()
            await self._check_fans(cl)
        if await cl.unread() <= 0:
            return
        started = float(self._ledger.data.get("started") or 0)
        for st in (1, 2):
            for sess in await cl.sessions(st):
                if int(sess.get("unread_count") or 0) <= 0:
                    continue
                talker = str(sess.get("talker_id") or "")
                begin = max(self._ledger.seq("bili", talker), int(sess.get("ack_seqno") or 0))
                msgs = await cl.messages(talker, st, begin)
                if not msgs:
                    continue
                top = max(int(m.get("msg_seqno") or 0) for m in msgs)
                items = []
                for m in msgs:
                    if str(m.get("sender_uid")) != talker:  # 她自己发的（别的设备）也会在里面
                        continue
                    it = bilidm.parse(m)
                    if it and it["t"] >= started - 600:  # 开这个功能之前的旧私信不翻出来回
                        items.append(it)
                self._ledger.set_seq("bili", talker, top)
                self._ledger.save()
                try:
                    await cl.ack(talker, st, top)
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_dm: 标已读没成 {talker}: {e}")
                if items:
                    _spawn(self._from_bili(talker, items), self.log)

    async def _check_fans(self, cl) -> None:
        """新关注她的人：还没互关 → 登记问兄长要不要回关；已经互关、有存着的私信 → 接着回。兄长本人直接回关。"""
        try:
            fans = await cl.fans()
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_dm: 看粉丝没成 {type(e).__name__}: {e}")
            return
        known = self._ledger.data["known_fans"]
        for f in fans:
            mid = f["mid"]
            known.setdefault(mid, time.time())
            if f["name"]:
                self._ledger.set_person("bili", mid, name=f["name"])
            if f["attribute"] == bilidm.MUTUAL:
                if self._ledger.data["held"].get(ledger.key("bili", mid)):
                    _spawn(self._release_held("bili", mid), self.log)
                continue
            if f["attribute"] == bilidm.BLOCKED:
                continue
            if mid == self._owner_mid("bili"):
                try:
                    await self._follow(cl, mid, why="兄长本人")
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_dm: 回关兄长没成 {type(e).__name__}: {e}")
                    continue
                r = self._ledger.find("follow", "bili", mid)
                if r:  # 填 owner_bili_mid 之前问过兄长"要不要回关他自己"：不用等了
                    self._ledger.answer(r["id"], True)
                    r["status"] = ledger.DONE
                continue
            if f["attribute"] == 0 and not self._ledger.refused_follow("bili", mid):
                self._ledger.ask("follow", "bili", mid, f["name"])
        self._ledger.save()

    async def _follow(self, cl, mid: str, why: str = "") -> int:
        await cl.follow(mid)
        attr = await cl.relation(mid)
        self.log.info(f"kaju_dm: B站关注了 {mid}（{why}），现在关系 {attr}")
        return attr

    # ------------------------------------------------------------ 一个人发来的私信
    def _lock(self, k: str) -> asyncio.Lock:
        return self._locks.setdefault(k, asyncio.Lock())

    async def _person(self, cl, uid: str) -> dict:
        p = self._ledger.person("bili", uid)
        if not p.get("sex") or time.time() - float(p.get("t") or 0) > 7 * 86400:
            try:
                c = await cl.card(uid)
                self._ledger.set_person("bili", uid, name=c["name"], sex=c["sex"], t=time.time())
                self._ledger.save()
            except Exception as e:  # noqa: BLE001
                self.log.info(f"kaju_dm: 查B站资料没成 {uid}: {e}")
            p = self._ledger.person("bili", uid)
        return p

    async def _from_bili(self, uid: str, items: list[dict]) -> None:
        await self._queue("bili:" + uid, items, lambda batch: self._from_bili_now(uid, batch))

    async def _from_bili_now(self, uid: str, items: list[dict]) -> None:
        async with self._lock("bili:" + uid):
            cl = self._client()
            if cl is None:
                return
            p = await self._person(cl, uid)
            name = p.get("name") or ""
            if uid != self._owner_mid("bili"):
                attr = await cl.relation(uid)
                if attr == bilidm.BLOCKED:
                    return
                if attr != bilidm.MUTUAL:
                    self._ledger.hold("bili", uid, items)
                    if attr == 0 and not self._ledger.refused_follow("bili", uid):
                        text, _ = bilidm.joined(items)
                        self._ledger.ask("follow", "bili", uid, name, text=text)
                    self._ledger.save()
                    self.log.info(f"kaju_dm: {name}({uid}) 没互关（{attr}），私信先存着")
                    return
            await self._chat("bili", uid, name, items)

    async def _release_held(self, site: str, uid: str) -> None:
        async with self._lock(f"{site}:{uid}"):
            items = self._ledger.take_held(site, uid)
            self._ledger.save()
            if items:
                name = self._ledger.person(site, uid).get("name") or ""
                await self._chat(site, uid, name, items, note=HELD_NOTE)

    def _video_links(self, text: str) -> list[str]:
        out = []
        for mod in ("bili", "douyin"):
            try:
                out += self._kb_mod(mod).find_links(text, 10)
            except Exception:  # noqa: BLE001
                pass
        return list(dict.fromkeys(out))

    async def _chat(self, site: str, uid: str, name: str, items: list[dict], *, note: str = "",
                    count_videos: bool = True) -> str:
        """送进完整流程，等她回完。→ ok / err / timeout / skip"""
        text, images = bilidm.joined(items)
        owner = uid == self._owner_mid(site) or self._who(site, uid) == self._owner_qq()  # 身份表里认到兄长的号也算
        extra = {"site": site, "uid": uid, "name": name, "owner": owner, "note": note}
        links = self._video_links(text)
        if not owner and links and count_videos:
            day = self._day()
            ok, over = self._ledger.split_videos(site, uid, day, links, self._limit())
            self._ledger.use_videos(site, uid, day, len(ok))
            if over:
                titles = {(it.get("share") or {}).get("url"): (it.get("share") or {}).get("title") for it in items}
                for u in over:
                    self._ledger.ask("video", site, uid, name, url=u, title=titles.get(u) or "", text=text)
                text = ledger.strip_links(text, over) or "（发来一个视频）"
                extra["over"] = len(over)
            self._ledger.save()
        if not text and not images:
            return "skip"
        platform, bot = self._qq()
        if platform is None:  # 私信借 AstrBot 的 aiocqhttp 适配器进完整流程（兄长的私信和他的 QQ 私聊是同一段）
            self.log.warning("kaju_dm: AstrBot 里没有 aiocqhttp 适配器，这条私信先不回")
            return "skip"
        if bot is None:  # QQ 本身没连上不要紧：这一轮不用 QQ
            bot = self.turn.NoQQ()
        session = sender = self._who(site, uid)
        if not owner and session.startswith((BILI_PREFIX, DOUYIN_PREFIX)):  # 认到 QQ 号上的人，称呼簿里已经有 TA
            self._tell_address_book(sender, name, self._ledger.person(site, uid).get("sex") or "")

        async def on_line(line: str) -> None:
            await self._send(site, uid, line)

        async def on_image(img) -> None:
            await self._send_image(site, uid, img)

        async with self._sem:
            ev = self.turn.make_event(platform, bot, await self._self_qq(bot), session, sender, name, text, images,
                                 extra, on_line, on_image)
            status = await self.turn.run(platform, ev, timeout=self._num("bili", "reply_timeout", 360),
                                    settle=self._num("bili", "settle_seconds", 6))
        self.log.info(f"kaju_dm: {ledger.SITE_NAMES.get(site, site)}私信 {name}({uid}) → {status}，说了 {len(ev.sent)} 句")
        return status

    def _tell_address_book(self, sid: str, name: str, sex: str) -> None:
        """称呼簿：B站的人用B站昵称，性别用B站资料（QQ 那套查不到）。"""
        book = self._star("address_of")
        people = getattr(book, "_people", None)
        if not isinstance(people, dict):
            return
        p = people.setdefault(sid, {})
        changed = False
        if name and p.get("name") != name:
            p["name"], changed = name, True
        if sex in ("male", "female") and p.get("sex") != sex:
            p["sex"], changed = sex, True
        if changed:
            p["t"] = time.time()
            book._people_dirty = True

    async def tell_owner_dm(self, text: str, sites=("douyin",)) -> list[str]:
        """给兄长本人的私信号发一段话（kaju_style 告诉他 Gemini 全挂了时用）。→ 发出去了的平台名。"""
        told = []
        for site in sites:
            uid = self._owner_mid(site)
            if not uid:
                continue
            if site == "douyin" and (not self._dy_on() or self._dy_keeper() is None):
                continue
            if site == "bili" and (not self._on() or self._client() is None):
                continue
            try:
                await self._send(site, uid, text)
                told.append(ledger.SITE_NAMES.get(site, site))
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_dm: 给兄长的{ledger.SITE_NAMES.get(site, site)}私信没发出去 {type(e).__name__}: {e}")
        return told

    async def _send(self, site: str, uid: str, text: str) -> None:
        """一句话发成私信（同一个人按顺序、隔一会儿发）。"""
        if site == "douyin":
            limit = int(self._num("douyin", "max_chars", 480))
            async with self._send_locks.setdefault(f"{site}:{uid}", asyncio.Lock()):
                for chunk in [text[i:i + limit] for i in range(0, len(text), limit)] or [text]:
                    async with self._dy.lock:
                        if not self._dy_me:
                            self._dy_me = await self._dy.me()
                        ok = await self._dy.send(uid, chunk, self._dy_me)
                    if not ok:
                        self.log.warning(f"kaju_dm: 抖音私信回读没看到这句（可能没发出去）→ {uid[:12]}…: {chunk[:20]}")
                        raise RuntimeError("抖音私信没发出去")
                    await asyncio.sleep(max(0.5, self._num("douyin", "line_gap", 1.5)))
            return
        cl = self._client()
        if cl is None:
            raise RuntimeError("B站没登录")
        limit = int(self._num("bili", "max_chars", 480))
        chunks = [text[i:i + limit] for i in range(0, len(text), limit)] or [text]
        async with self._send_locks.setdefault(f"{site}:{uid}", asyncio.Lock()):
            for chunk in chunks:
                try:
                    await cl.send_text(uid, chunk)
                except Exception as e:  # noqa: BLE001
                    self.log.warning(f"kaju_dm: B站私信没发出去 → {uid}: {type(e).__name__}: {e}")
                    raise
                await asyncio.sleep(max(0.3, self._num("bili", "line_gap", 1.2)))

    @staticmethod
    async def _image_bytes(img) -> bytes:
        """AstrBot 的 Image 组件 → 图片内容（本地文件 / base64 / 网址都行）。"""
        import base64

        f = str(getattr(img, "file", "") or getattr(img, "url", "") or getattr(img, "path", "") or "")
        if f.startswith("base64://"):
            return base64.b64decode(f[len("base64://"):])
        if f.startswith("file:///"):
            f = f[len("file:///"):]
        if f and os.path.isfile(f):
            with open(f, "rb") as fh:
                return fh.read()
        conv = getattr(img, "convert_to_file_path", None)
        if callable(conv):
            path = await conv()
            with open(path, "rb") as fh:
                return fh.read()
        raise ValueError("读不到这张图")

    async def _send_image(self, site: str, uid: str, img) -> None:
        """一张图（表情包）发成私信。B站：先传到B站图床再发；抖音：交给私信页的上传框。太大的不发。"""
        if site == "douyin":
            # 2026-11-08 实测：网页端上传的图片（gif、png 都试了）在她这边显示已发、已读，兄长手机上一张都看不到
            # ——抖音把网页端发图拦了，只给发送方看。所以默认不上传图，改发抖音表情库里的表情（打字联想，对方收得到）。
            if self._sec("douyin").get("send_images", False):
                await self._send_douyin_image(uid, img)
            elif self._sec("douyin").get("stickers", True):
                await self._send_douyin_sticker(uid, img)
            return
        cl = self._client()
        if cl is None:
            raise RuntimeError("B站没登录")
        try:
            data = await self._image_bytes(img)
            if len(data) > self._num("bili", "max_image_mb", 8) * 1024 * 1024:
                self.log.info(f"kaju_dm: 图太大（{len(data) // 1024}KB），不发")
                return
            async with self._send_locks.setdefault(f"{site}:{uid}", asyncio.Lock()):
                up = await cl.upload_image(data)
                await cl.send_image(uid, up)
                await asyncio.sleep(max(0.3, self._num("bili", "line_gap", 1.2)))
            self.log.info(f"kaju_dm: 给 {uid} 发了一张图（{up['width']}x{up['height']}）")
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_dm: 图片私信没发出去 → {uid}: {type(e).__name__}: {e}")
            raise

    @staticmethod
    def _meme_category(img) -> str:
        """表情包是哪一类：meme_manager 的图在 packs/<包>/memes/<分类>/<文件> 里。"""
        f = str(getattr(img, "file", "") or getattr(img, "path", "") or "")
        if f.startswith("file:///"):
            f = f[len("file:///"):]
        parts = f.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[-3] == "memes":
            return parts[-2]
        return ""

    async def _send_douyin_sticker(self, sec: str, img) -> None:
        """她想发某一类表情包：在抖音里打这一类的意思（开心、难过……），点弹出来的第一个~第三个表情。"""
        import random

        category = self._meme_category(img)
        word = douyindm.sticker_word(category, dt.datetime.now(_tz(self.body)).hour)
        async with self._send_locks.setdefault(f"douyin:{sec}", asyncio.Lock()):
            async with self._dy.lock:
                if not self._dy_me:
                    self._dy_me = await self._dy.me()
                ok = await self._dy.send_sticker(sec, word, self._dy_me, pick=random.randrange(3))
            await asyncio.sleep(max(0.5, self._num("douyin", "line_gap", 1.5)))
        if ok:
            self.log.info(f"kaju_dm: 抖音私信发了一个表情（{category or '?'} → 搜「{word}」）")
        else:
            self.log.warning(f"kaju_dm: 抖音表情没发出去（{category or '?'} → 搜「{word}」，没弹出建议或回读没看到）")

    async def _send_douyin_image(self, sec: str, img) -> None:
        """抖音只收 jpg/png/gif：别的格式（webp……）先转成 png，写个临时文件交给上传框，发完删掉。"""
        import tempfile

        data = await self._image_bytes(img)
        if len(data) > self._num("douyin", "max_image_mb", 8) * 1024 * 1024:
            self.log.info(f"kaju_dm: 图太大（{len(data) // 1024}KB），不发")
            return
        mime = bilidm.image_mime(data)
        ext = {"image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg"}.get(mime)
        if mime == "image/jpeg" and data[:2] != b"\xff\xd8":  # 认不出来的格式：转 png
            ext = None
        if ext is None:
            import io

            from PIL import Image as PILImage

            buf = io.BytesIO()
            PILImage.open(io.BytesIO(data)).save(buf, "PNG")
            data, ext = buf.getvalue(), ".png"
        fd, path = tempfile.mkstemp(prefix="kaju_dm_", suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            async with self._send_locks.setdefault(f"douyin:{sec}", asyncio.Lock()):
                async with self._dy.lock:
                    if not self._dy_me:
                        self._dy_me = await self._dy.me()
                    ok = await self._dy.send_image(sec, path, self._dy_me)
                await asyncio.sleep(max(0.5, self._num("douyin", "line_gap", 1.5)))
            if ok:
                self.log.info(f"kaju_dm: 抖音私信发了一张图（{ext}，{len(data) // 1024}KB）")
            else:
                self.log.warning("kaju_dm: 抖音图片私信回读没看到（可能没发出去）")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _patch_memes(self) -> None:
        """表情包插件（meme_manager）发图不走这一轮的回复，而是按会话直接发（context.send_message）：
        兄长从B站私信她时会话就是他的 QQ 私聊，图会发到 QQ（2026-11-08 实际发生过）。
        私信那一轮的表情包改成发B站图片私信，绝不发到 QQ。"""
        star = self._star("_send_meme_image")
        if star is None or getattr(star._send_meme_image, "_kaju_dm", False):
            return
        orig = star._send_meme_image

        async def send_meme(event, image):
            dm = event.get_extra(self.turn.DM_KEY) if event is not None else None
            if not dm:
                return await orig(event, image)
            try:
                await self._send_image(dm.get("site", "bili"), dm["uid"], image)
            except Exception:  # noqa: BLE001 — 发不出就算了
                pass

        send_meme._kaju_dm = True
        send_meme._orig = orig
        star._send_meme_image = send_meme

    def _unpatch_memes(self) -> None:
        star = self._star("_send_meme_image")
        fn = getattr(star, "_send_meme_image", None) if star else None
        if fn is not None and getattr(fn, "_kaju_dm", False):
            try:
                del star._send_meme_image  # 去掉实例上的这层，回到类上的原方法
            except AttributeError:
                star._send_meme_image = fn._orig

    # ------------------------------------------------------------ 别的插件往 bili_<uid> 主动发消息
    def _patch(self) -> None:
        """定时提醒、说到做到的补做……会用 context.send_message 往这个会话发：bili_ 开头的转成B站私信。"""
        if self._patched is not None:
            return
        platform, _ = self._qq()
        if platform is None:
            return
        orig = platform.send_by_session

        async def send_by_session(session, message_chain):
            sid = str(getattr(session, "session_id", "") or "")
            if sid.startswith(DOUYIN_PREFIX):
                sec = self._dy_sec(sid[len(DOUYIN_PREFIX):])
                for line in self.turn.plain_lines(message_chain):
                    await self._send("douyin", sec, line)
                for img in self.turn.chain_images(message_chain):
                    try:
                        await self._send_image("douyin", sec, img)
                    except Exception:  # noqa: BLE001
                        pass
                return
            if sid.startswith(BILI_PREFIX):
                uid = sid[len(BILI_PREFIX):]
                for line in self.turn.plain_lines(message_chain):
                    await self._send("bili", uid, line)
                for img in self.turn.chain_images(message_chain):
                    try:
                        await self._send_image("bili", uid, img)
                    except Exception:  # noqa: BLE001
                        pass
                return
            return await orig(session, message_chain)

        platform.send_by_session = send_by_session
        self._patched = (platform, orig)

    def _unpatch(self) -> None:
        if self._patched is not None:
            platform, orig = self._patched
            try:
                platform.send_by_session = orig
            except Exception:  # noqa: BLE001
                pass
            self._patched = None

    # ------------------------------------------------------------ 兄长批
    def _quiet(self) -> bool:
        raw = str(self.config.get("quiet_hours", "0-7") or "")
        try:
            a, b = (int(x) for x in raw.split("-"))
        except ValueError:
            return False
        h = dt.datetime.now(_tz(self.body)).hour
        return (a <= h < b) if a <= b else (h >= a or h < b)

    async def _notify_owner(self) -> None:
        if not self.config.get("notify_owner", True) or self._quiet():
            return
        new = [r for r in self._ledger.pending() if not r.get("told")]
        if not new:
            return
        _, bot = self._qq()
        owner = self._owner_qq()
        if bot is None or not owner:
            return
        lines = ["【佳树私信】有事等兄长大人决定："] + [ledger.describe(r) for r in new]
        lines.append("回「/佳树私信 批准 编号」或「/佳树私信 拒绝 编号」，也可以直接跟佳树说。")
        try:
            await bot.call_action("send_private_msg", user_id=int(owner),
                                  message=[{"type": "text", "data": {"text": "\n".join(lines)}}])
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_dm: 告诉兄长没发出去 {type(e).__name__}: {e}")
            return
        for r in new:
            r["told"] = True
        self._ledger.save()

    async def _apply(self, r: dict, yes: bool) -> str:
        """兄长答复了一件事：记下来，然后去做（关注 / 看视频）。→ 给兄长看的结果。"""
        if r is None:
            return "没有这个编号。"
        if r["status"] != ledger.PENDING:
            return f"#{r['id']} 已经答复过了（{ {'yes': '同意', 'no': '不同意', 'done': '做完了'}.get(r['status'], r['status']) }）。"
        self._ledger.answer(r["id"], yes)
        self._ledger.save()
        who = r.get("name") or r["uid"]
        if r["kind"] == "same":
            r["status"] = ledger.DONE if yes else ledger.NO
            self._ledger.save()
            if not yes:
                return f"好，{who}不算是那个人，佳树还当TA是新认识的。"
            qq = str(r.get("qq") or "")
            if not qq:
                return (f"佳树不知道{who}是 QQ 上的哪一位：直接告诉佳树（比如\"{who}就是某某\"），"
                        f"或者用 /佳树认人 认 {ledger.SITE_NAMES.get(r['site'], r['site'])} 号 QQ号。")
            return self._link(r["site"], r["uid"], who, qq)
        if not yes:
            if r["kind"] == "follow":
                self._ledger.take_held(r["site"], r["uid"])
                self._ledger.save()
                return f"好，不关注{who}，TA的私信也不回。"
            return f"好，{who}的那条视频不看。"
        if r["kind"] == "follow" and r["site"] == "douyin":
            if self._dy_keeper() is None:
                r["status"] = ledger.PENDING
                r.pop("answered_at", None)
                self._ledger.save()
                return "抖音小号没登录着，做不了（先 /佳树抖音登录）。"
            try:
                async with self._dy.lock:
                    ok = await self._dy.follow(r["uid"])
                prof = await self._dy.profile(r["uid"])
            except Exception as e:  # noqa: BLE001
                ok, prof = False, {}
                self.log.info(f"kaju_dm: 抖音关注出错 {type(e).__name__}: {e}")
            r["status"] = ledger.DONE
            self._ledger.save()
            if not ok:
                return (f"佳树在网页上点了关注{who}，但抖音没认（网页端的关注会被悄悄撤销）。"
                        f"麻烦用小号的手机抖音 App 关注一下「{who}」；互关以后TA的私信佳树会接着回。")
            if douyindm.mutual(prof):
                if self._ledger.data["held"].get(ledger.key("douyin", r["uid"])):
                    _spawn(self._release_held("douyin", r["uid"]), self.log)
                    return f"关注了{who}，现在互关了；TA之前的私信佳树接着回。"
                return f"关注了{who}，现在互关了。"
            return f"关注了{who}，不过TA现在没关注佳树，还不算互关；TA关注回来以后私信才会回。"
        cl = self._client()
        if cl is None and r["kind"] == "follow":
            return "B站小号没登录着，做不了（先 /佳树B站登录）。"
        if r["kind"] == "follow":
            try:
                attr = await self._follow(cl, r["uid"], why=f"兄长批准 #{r['id']}")
            except Exception as e:  # noqa: BLE001
                r["status"] = ledger.PENDING  # 没关注上：还算没答复，可以再批一次
                r.pop("answered_at", None)
                self._ledger.save()
                return f"关注{who}没成功：{e}"
            r["status"] = ledger.DONE
            self._ledger.save()
            if attr == bilidm.MUTUAL:
                if self._ledger.data["held"].get(ledger.key(r["site"], r["uid"])):
                    _spawn(self._release_held(r["site"], r["uid"]), self.log)
                    return f"关注了{who}，现在互关了；TA之前的私信佳树接着回。"
                return f"关注了{who}，现在互关了。"
            return f"关注了{who}，不过TA现在没关注佳树，还不算互关；TA关注回来以后私信才会回。"
        # video
        item = {"text": "", "images": [], "share": {"title": r.get("title") or "", "url": r["url"]}}
        r["status"] = ledger.DONE
        self._ledger.save()

        async def go():
            async with self._lock(f"{r['site']}:{r['uid']}"):
                await self._chat(r["site"], r["uid"], r.get("name") or "", [item], note=APPROVED_NOTE,
                                 count_videos=False)

        _spawn(go(), self.log)
        return f"好，佳树现在去看{who}发的那条视频，看完在私信里跟TA聊。"

    async def cmd_dm(self, event: Turn, action: str = "", arg: str = ""):
        """B站私信：/佳树私信（待批的事和今天的情况）｜批准 n｜拒绝 n｜关注 B站UID"""
        action, arg = action.strip(), arg.strip()
        if action in ("批准", "同意", "拒绝", "不同意"):
            yield event.plain_result(await self._apply(self._ledger.get(arg), action in ("批准", "同意")))
            return
        if action == "关注" and arg.isdigit():
            cl = self._client()
            if cl is None:
                yield event.plain_result("B站小号没登录着。")
                return
            try:
                attr = await self._follow(cl, arg, why="兄长直接让关注")
            except Exception as e:  # noqa: BLE001
                yield event.plain_result(f"关注没成功：{e}")
                return
            r = self._ledger.find("follow", "bili", arg)
            if r:
                self._ledger.answer(r["id"], True)
                r["status"] = ledger.DONE
            self._ledger.save()
            if attr == bilidm.MUTUAL and self._ledger.data["held"].get(ledger.key("bili", arg)):
                _spawn(self._release_held("bili", arg), self.log)
            yield event.plain_result(f"关注了 {arg}，关系：{ {6: '互关', 2: '她关注了TA（TA没关注她）'}.get(attr, attr) }")
            return
        pend = self._ledger.pending()
        day = self._day()
        used = self._ledger.data["videos"].get(day) or {}
        cl_ok = self._client() is not None
        lines = [f"B站私信：{'开着' if self._on() else '关着'}，小号{'登录着' if cl_ok else '没登录'}；"
                 f"兄长的B站UID：{self._owner_mid('bili') or '（身份表里还没登记：botctl people link）'}；"
                 f"别人每天最多 {self._limit()} 条视频。"]
        lines.append("待批：" + ("\n" + "\n".join(ledger.describe(r) for r in pend) if pend else "没有"))
        if used:
            lines.append("今天看的视频：" + "，".join(
                f"{self._ledger.data['people'].get(k, {}).get('name') or k} {n} 条" for k, n in used.items()))
        held = {k: len(v) for k, v in self._ledger.data["held"].items() if v}
        if held:
            lines.append("没互关先存着的私信：" + "，".join(
                f"{self._ledger.data['people'].get(k, {}).get('name') or k} {n} 条" for k, n in held.items()))
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------ 认人（谁是谁，kaju_core.people）
    def _link(self, site: str, uid: str, who: str, qq: str) -> str:
        """把私信号认到 QQ 上那个人：以后TA在这边私信，和在 QQ 跟她聊是同一份（心情、称呼、记忆、聊天记录）。"""
        try:
            people.registry().link(qq, site, uid)
        except ValueError as e:
            return f"没认上：{e}"
        book = self._star("address_of")
        addr = book.address_of(qq) if book is not None else qq
        self.log.info(f"kaju_dm: 认人 {ledger.SITE_NAMES.get(site, site)} {who}({uid}) → QQ {qq}（{addr}）")
        return (f"记下了：{ledger.SITE_NAMES.get(site, site)}的{who}就是{addr}（QQ {qq}）。"
                f"以后TA在{ledger.SITE_NAMES.get(site, site)}私信佳树，和在 QQ 上是同一个人、同一段记忆。")

    def _find_qq(self, text: str) -> list[tuple[str, str]]:
        book = self._star("find_person")
        try:
            return book.find_person(text) if book is not None else []
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_dm: 称呼簿找人出错 {type(e).__name__}: {e}")
            return []

    def _find_dm_account(self, site: str, name: str) -> list[tuple[str, str]]:
        """私信那边叫这个名字的号 → [(号, 名字)]：完全对上的优先，没有再找包含的；名字空 = 最近私信过的那个。"""
        rows = [(k.split(":", 1)[1], str(p.get("name") or ""), float(p.get("t") or 0))
                for k, p in self._ledger.data["people"].items() if k.startswith(site + ":")]
        name = (name or "").strip()
        if not name:
            rows.sort(key=lambda x: x[2], reverse=True)
            return [(u, n) for u, n, _ in rows[:1]]
        exact = [(u, n) for u, n, _ in rows if n == name or u == name or self._dy_num(u) == name]
        return exact or [(u, n) for u, n, _ in rows if name in n or (n and n in name)][:5]

    async def claim_same_person(self, event: Turn, who: str) -> str:
        dm = event.get_extra(self.turn.DM_KEY) or {}
        if not dm or dm.get("owner"):
            return "不用：这不是别人在B站/抖音私信佳树。"
        site, uid, name = dm.get("site"), str(dm.get("uid") or ""), dm.get("name") or "对方"
        if people.registry().is_linked(site, uid):
            return f"{name}已经认过了，就是佳树认识的那个人。"
        hits = self._find_qq(who)
        guess = "、".join(f"{a}（QQ {q}）" for q, a in hits)
        r, new = self._ledger.ask("same", site, uid, name, text=str(who)[:30], title=guess)
        r["qq"] = hits[0][0] if len(hits) == 1 else ""
        self._ledger.save()
        if new:
            _spawn(self._notify_owner(), self.log)
        return (f"已经去 QQ 问兄长大人：{name}说自己是「{who}」"
                + (f"，看着像{guess}" if guess else "，QQ 上没找到叫这个的人")
                + "。兄长大人确认之前，佳树这边还认不准是不是同一个人。")

    async def link_same_person(self, event: Turn, site: str, account_name: str, who: str) -> str:
        if event.get_group_id() or str(event.get_sender_id() or "") != self._owner_qq() or event.get_extra(self.turn.DM_KEY):
            return "没记：只有兄长大人本人在 QQ 私聊里说了才算。"
        key = SITES.get(str(site or "").strip().lower())
        if not key:
            return "没记：平台只认抖音或B站。"
        accs = self._find_dm_account(key, account_name)
        if len(accs) != 1:
            names = "、".join(n or u for u, n in accs)
            return (f"没记：{ledger.SITE_NAMES[key]}私信过佳树的人里" + (f"有好几个对得上（{names}），问兄长大人是哪一个。"
                    if accs else f"没有叫「{account_name}」的。"))
        hits = self._find_qq(who)
        if len(hits) != 1:
            names = "、".join(f"{a}（QQ {q}）" for q, a in hits)
            return (f"没记：QQ 上" + (f"有好几个对得上（{names}），问兄长大人是哪一位。" if hits
                    else f"没找到「{who}」，问兄长大人TA的 QQ 号或群名片。"))
        uid, name = accs[0]
        said = self._link(key, uid, name or uid, hits[0][0])
        r = self._ledger.find("same", key, uid)
        if r:
            r["status"] = ledger.DONE
            self._ledger.save()
        return said

    # ------------------------------------------------------------ 提示 / 工具
    async def inject(self, event: Turn, req: Request):
        dm = event.get_extra(self.turn.DM_KEY)
        if dm:
            self._merge_late(event, req, dm)
            site = ledger.SITE_NAMES.get(dm.get("site"), "B站")
            who = "兄长大人本人" if dm.get("owner") else (dm.get("name") or "对方")
            note = DM_NOTE.format(site=site, who=who) + (dm.get("note") or "")
            if dm.get("over"):
                note += OVER_NOTE.format(limit=self._limit(), n=dm["over"])
            req.system_prompt = (req.system_prompt or "") + note
            hide = [TOOL, TOOL_LINK]
            if dm.get("owner") or people.registry().is_linked(dm.get("site"), str(dm.get("uid") or "")):
                hide.append(TOOL_CLAIM)
            self._hide_tool(req, *hide)
            return
        pend = self._ledger.pending()
        is_owner = (event.get_platform_name() == "aiocqhttp" and not event.get_group_id()
                    and str(event.get_sender_id() or "") == self._owner_qq())
        if not is_owner:
            self._hide_tool(req, TOOL, TOOL_CLAIM, TOOL_LINK)
            return
        if not pend:
            self._hide_tool(req, TOOL, TOOL_CLAIM)
            return
        self._hide_tool(req, TOOL_CLAIM)
        items = "\n".join("  " + ledger.describe(r) for r in pend[-8:])
        req.system_prompt = (req.system_prompt or "") + OWNER_NOTE.format(items=items)

    def _merge_late(self, event: Turn, req: Request, dm: dict) -> None:
        """她还没开口回（看视频、排队等模型）时TA又发来的私信：并进这一轮一起回（像 QQ 私聊的连发合并）。
        别人发来的新视频链接不并（要照每天的额度算，留给下一轮）。"""
        key = f"{dm.get('site')}:{dm.get('uid')}"
        late = self._inbox.get(key) or []
        if not late:
            return
        text, images = bilidm.joined(late)
        if not dm.get("owner") and self._video_links(text):
            return
        self._inbox.pop(key, None)
        if text:
            req.prompt = ((req.prompt or "").rstrip() + "\n" + text).strip()
            try:
                event.message_str = ((event.message_str or "").rstrip() + "\n" + text).strip()
            except Exception:  # noqa: BLE001
                pass
        if images:
            try:
                req.image_urls = list(req.image_urls or []) + list(images)
            except Exception:  # noqa: BLE001
                pass
        self.log.info(f"kaju_dm: 回之前TA又发了 {len(late)} 条，并进这一轮一起回：{text[:40]!r}")

    @staticmethod
    def _hide_tool(req: Request, *names: str) -> None:
        tools = getattr(req, "func_tool", None)
        try:
            have = set(tools.names()) if tools else set()
            for n in names or (TOOL,):
                if n in have:
                    tools.remove_tool(n)
        except Exception:  # noqa: BLE001
            pass

    async def mark_done(self, event: Turn, run_context, response):
        if event.get_extra(self.turn.DM_KEY) and not event.get_extra(self.turn.DONE_KEY):
            event.set_extra(self.turn.DONE_KEY, {"t": time.time(), "err": getattr(response, "role", "") == "err"})

    async def answer_dm_request(self, event: Turn, request_id: str, approve: bool):
        """兄长大人回答了B站/抖音私信那边等他决定的事（要不要关注某人、某人多发的视频要不要看）时调用。只有兄长大人本人说了才算。

        Args:
            request_id(string): 那件事的编号（#后面的数字）
            approve(boolean): 兄长大人同意填 true，不同意填 false
        """
        if event.get_group_id() or str(event.get_sender_id() or "") != self._owner_qq() or event.get_extra(self.turn.DM_KEY):
            return "没做：只有兄长大人本人在 QQ 私聊里说了才算。"
        if isinstance(approve, str):
            approve = approve.strip().lower() in ("true", "1", "yes", "同意", "是")
        return await self._apply(self._ledger.get(request_id), bool(approve))
