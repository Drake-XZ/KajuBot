"""佳树的生活：她自己的每日日程 + 日记/周记/月记（原 kaju_daily / kaju_diary 合并）。

- 日程（daily.py）：每天第一次需要时后台写一份"佳树今天"的小日程，聊天时把到现在为止的事放进提示。
- 日记（diary.py）：记录聊天，后台每天写日记、每周写周记、每月写月记，把最近的回忆放进提示；
  写日记时会参考她当天的日程。
- 都按 AstrBot 配置的时区（北京时间）过日子，day_start_hour 点算新的一天。
- 工具：read_diary / search_diary。管理员命令：/佳树日程 [重写]、/佳树日记 [日期|上周|10月|补写 日期]。
- 关于自己（selffacts.py，1.1.0）：人设卡换成两句身份后，每轮按对方刚说的话从"关于自己"清单里想起最相关的几条。
"""

from __future__ import annotations

from ..body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import datetime as dt
import os
import re
import sys
import zoneinfo
from kaju_core import parts, paths  # noqa: E402
from kaju_core.life.daily import Daily, asks_about_her, render_note, told_in  # noqa: E402
from kaju_core.life.diary import Diary  # noqa: E402
from kaju_core.life.selffacts import SelfFacts  # noqa: E402

PLUGIN_NAME = "astrbot_plugin_kaju_life"


class LifeMind:
    """KajuLife 的逻辑（AstrBot 外壳在 plugins\\kaju_life\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        folder = paths.self_dir(PLUGIN_NAME)
        os.makedirs(folder, exist_ok=True)
        # 服务器本机是当地时间（不是北京时间）；按 AstrBot 配置的时区过日子，和她在消息里看到的时间一致
        try:
            self._tz = zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            self._tz = dt.timezone(dt.timedelta(hours=8))
        self.daily = Daily(self.body, lambda: self._sec("daily"), folder)
        self.diary = Diary(self.body, lambda: self._sec("diary"), folder,
                           now=self._now, day_key=self._day_key,
                           own_plan=lambda day: self.daily.days.get(day))
        self.selffacts = SelfFacts(folder, lambda: self._sec("self_facts"))
        self._loop_task = asyncio.create_task(self.diary.loop())

    def _sec(self, name: str) -> dict:
        sec = self.config.get(name)
        return sec if isinstance(sec, dict) else {}

    def _now(self) -> dt.datetime:
        return dt.datetime.now(self._tz)

    def _start_hour(self) -> int:
        return int(self.config.get("day_start_hour", 5))

    def _day_key(self, now: dt.datetime | None = None) -> str:
        now = now or self._now()
        return (now - dt.timedelta(hours=self._start_hour())).strftime("%Y-%m-%d")

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)
        if self._loop_task:
            self._loop_task.cancel()

    # ------------------------------------------------------------ 记录聊天（日记的素材）
    async def log_incoming(self, event: Turn):
        if self._sec("diary").get("enable", True):
            await self.diary.log_incoming(event)

    async def log_reply(self, event: Turn, resp: Answer):
        text = getattr(resp, "completion_text", "") or ""
        if self._sec("diary").get("enable", True):
            self.diary.log_reply(event, text)
        if self._sec("daily").get("enable", True) and text:
            self.daily.note_reply(self._day_key(), event.unified_msg_origin, text)

    def log_own(self, chat: str, text: str) -> None:
        """别的插件替她主动发出去的话（刷完 B 站私聊兄长……）也记进聊天记录，日记、心里话才看得到。chat：p<QQ> / g<群号>。"""
        text = re.sub(r"&&[^&\n]{1,40}&&", "", text or "").strip()
        if text and chat and self._sec("diary").get("enable", True):
            self.diary._append_log({"c": chat, "u": "self", "n": "佳树", "x": text[:300]})

    # ------------------------------------------------------------ 放进提示
    async def inject_self_facts(self, event: Turn, req: Request):
        if not self._sec("self_facts").get("enable", True):
            return
        try:
            note, picked, secs = await self.selffacts.note_for(event.message_str or "")
        except Exception as exc:  # noqa: BLE001
            self.log.info(f"kaju_life: 这轮没想起关于自己的事（{type(exc).__name__}: {exc}）")
            return
        if note:
            req.system_prompt = (req.system_prompt or "") + note
            self.log.info(f"kaju_life: 想起关于自己 {len(picked)} 条（{secs:.2f}s）：{picked[0][:24]}…")

    async def inject_diary(self, event: Turn, req: Request):
        if not self._sec("diary").get("enable", True):
            return
        note = self.diary.build_memory_note(self.diary.can_see_private(event))
        if note:
            req.system_prompt = (req.system_prompt or "") + note

    def doing_now(self, within_minutes: int = 120) -> str:
        """日程里她这会儿在做的事：今天已经开始、离现在不超过 within_minutes 分钟的最后一件；没有 → ''。
        （2026-11-15：核对一直不过时她说一句“在忙”，忙什么从这里取。）"""
        now = self._now()
        plan = self.daily.days.get(self._day_key(now)) or {}
        if now.hour < self._start_hour():
            return ""
        hm, best = now.strftime("%H:%M"), None
        for e in plan.get("events") or []:
            if str(e.get("time", "")) <= hm:
                best = e
        if not best:
            return ""
        try:
            h, m = map(int, str(best["time"]).split(":"))
            if (now.hour * 60 + now.minute) - (h * 60 + m) > within_minutes:
                return ""
        except (ValueError, KeyError):
            return ""
        return str(best.get("text") or "").strip()

    async def inject_daily(self, event: Turn, req: Request):
        if not self._sec("daily").get("enable", True):
            return
        now = self._now()
        key = self._day_key(now)
        plan = self.daily.days.get(key)
        if not plan:
            self.daily.kick(event.unified_msg_origin, key, now)
            return
        asked = asks_about_her(event.get_message_str() or "")
        note = render_note(plan, now, self._start_hour(), asked=asked,
                           told=told_in(plan, event.unified_msg_origin))
        if note:
            req.system_prompt = (req.system_prompt or "") + note

    # ------------------------------------------------------------ 工具
    async def read_diary(self, event: Turn, when: str = ""):
        """翻看你自己以前写的日记、周记或月记，回想某天/某周/某月发生了什么。被问到"那天/上周/上个月发生了什么、你还记得吗"时先翻一下再回答。

        Args:
            when(string): 想看哪天，例如 昨天、前天、2026-10-29、10月29日、上周、这周、上个月、10月；留空看最近一篇
        """
        return self.diary.read(event, when)

    async def search_diary(self, event: Turn, keywords: str):
        """在你自己写过的日记、周记、月记里按关键词找某件事、某个人是哪天的事。想不起来某件事什么时候发生、细节是什么时用。

        Args:
            keywords(string): 关键词，可以用空格隔开好几个，例如 "音游 兄长大人" 或 "女王大人 加班"
        """
        return self.diary.search(event, keywords)

    # ------------------------------------------------------------ 管理员命令
    async def show_daily(self, event: Turn, action: str = ""):
        if not event.is_admin():
            return
        now = self._now()
        key = self._day_key(now)
        if action.strip() == "重写":
            yield event.plain_result("好，佳树重新想想今天……")
            try:
                plan = await self.daily.generate(event.unified_msg_origin, key, now)
            except Exception as exc:  # noqa: BLE001
                yield event.plain_result(f"重写失败：{exc}")
                return
        else:
            plan = self.daily.days.get(key)
        if not plan:
            self.daily.kick(event.unified_msg_origin, key, now)
            yield event.plain_result("今天的日程还没写好，稍等一会儿再看。")
            return
        lines = [f"{e['time']} {e['text']}" for e in plan["events"]]
        yield event.plain_result(
            f"佳树的今天（{key}）\n" + "\n".join(lines)
            + f"\n心情：{plan.get('mood', '')}\n想说的事：{(plan.get('share') or {}).get('text', '')}"
        )

    async def show_diary(self, event: Turn, action: str = "", arg: str = ""):
        if not event.is_admin():
            return
        action = action.strip()
        if action in ("补写", "重写"):
            r = self.diary.resolve_when(arg or "昨天")
            if not r:
                yield event.plain_result("日期没看懂，用 2026-10-29 这种格式。")
                return
            kind, key = r
            yield event.plain_result(f"好，佳树重新写 {key}……")
            fn = {"diary": self.diary.write_diary, "week": self.diary.write_weekly,
                  "month": self.diary.write_monthly}[kind]
            try:
                async with self.diary.busy:
                    e = await fn(key)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_life: 补写 {key} 失败: {exc}")
                yield event.plain_result(f"没写成：{exc}")
                return
            yield event.plain_result(e["full"] if e else "没写成（那段时间没有记录，或者模型没按格式回）。")
            return
        if action in ("", "列表"):
            yield event.plain_result(self.diary.listing())
            return
        yield event.plain_result(self.diary.read(event, action))
