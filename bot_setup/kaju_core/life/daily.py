"""佳树的一天：给她一份"自己的生活"，被问起今天过得怎样时有真实、前后一致的事可说。

每天第一次需要时，在后台让模型写一份"佳树今天"的小日程：六七件按时间排的小事 + 今天的心情 +
一件最想跟兄长大人说的事，参考前几天写过的内容保持连续、避免重复。

只有对方问起她自己（今天怎么样、在干嘛、吃了吗……）时，才把"到现在为止发生的事 + 接下来打算做的事"
放进提示；没问就只提醒一句别主动讲（2026-10-31：没人问她也自己说"今天算账目算到眼花""荧光笔打折多买了支蓝的"，
同一件事在私聊、空间、群里各说一遍）。她在某个聊天里讲过的事记下来（days.json 里的 told），
在那个聊天再被问起时标"说过了"，别再讲一遍。还没写好时这一次就不放。
"""

import asyncio
import datetime as dt
import json
import os
import re
import time


WEEKDAYS = "一二三四五六日"

GEN_SYSTEM = (
    "你在为一个角色写她今天的生活日程，用于让她聊天时有自己的事可说。"
    "角色：温水佳树，初三女生，学生会副会长，正在备考石蕗高中，擅长做饭做点心，"
    "非常黏也非常操心哥哥（她叫他\"兄长大人\"）。性格开朗、爱操心、有点小醋意。"
    "写的事要平凡、具体、像真实的初中生活（上课、社团/学生会、复习、做饭、买东西、和同学的小事、小烦恼），"
    "不要恋爱情节，不要夸张事件，不要提 AI。只输出 JSON。"
)

GEN_PROMPT = """今天是 {date}（星期{wd}），{season_note}
前几天的日程摘要（保持连贯，别重复同样的事）：
{history}

请写佳树今天的日程，输出 JSON：
{{"mood": "今天整体心情，一句话",
  "events": [{{"time": "07:10", "text": "一件小事，20字以内"}}, ...],
  "share": {{"time": "这件事发生的时间", "text": "今天最想跟兄长大人说的一件小事，一句话"}}}}
要求：events 6~8 件，时间从早到晚覆盖一整天（最晚到 23:00 左右），{day_note}
文字里不要用"我"，省略主语或用"佳树"。"""


def parse_plan(text: str) -> dict | None:
    """Parse the model's JSON schedule; None when it is unusable (fewer than 3 valid events)."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        plan = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    events = []
    for e in plan.get("events") or []:
        t, s = str(e.get("time", "")).strip(), str(e.get("text", "")).strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", t) and s:
            events.append({"time": t.zfill(5), "text": s[:40]})
    if len(events) < 3:
        return None
    events.sort(key=lambda e: e["time"])
    share = plan.get("share")
    if isinstance(share, dict):
        st = str(share.get("time", "")).strip()
        share = {"time": st.zfill(5) if re.fullmatch(r"\d{1,2}:\d{2}", st) else "18:00",
                 "text": str(share.get("text", "")).strip()[:60]}
    else:
        share = {"time": "18:00", "text": str(share or "").strip()[:60]}
    return {"mood": str(plan.get("mood", "")).strip()[:40], "events": events, "share": share}


# 对方在问佳树自己的事：今天/现在/最近怎么样、在干嘛、吃了吗、学校里的事、"你呢"
ASKS_ABOUT_HER = re.compile(
    r"今天(怎么样|如何|过得|干了|做了|干什么|做什么|干嘛|忙|累|有什么|有啥|发生|开心|顺利|还好)"
    r"|你今天.{0,8}([吗呢嘛][?？]?$|[?？])"
    r"|(在|正在)(干|做|忙)(嘛|啥|什么|吗)|干(嘛|啥)(呢|呀|去了)|做什么呢|忙(什么|啥)|在忙吗"
    r"|最近(怎么样|如何|过得|在忙|忙|还好|好吗)"
    r"|(学校|上课|放学|学生会|文化祭|考试|复习|作业|功课|社团|便当|晚饭|午饭|早饭).{0,8}(怎么样|如何|吗|没|呢|[?？])"
    r"|吃(饭)?(了|过)(饭)?(吗|没)|吃(的)?(什么|啥)"
    r"|^(那)?你呢[?？]*$|你那边(呢|怎么样)"
    r"|(有什么|有啥)(新鲜事|好玩的|开心的|有趣的)|说说你|聊聊你|讲讲你"
)

# 比较"她说过的话"和日程条目时不算数的词：人名称呼、太常见的字组
_STOP_BIGRAMS = {"佳树", "兄长", "长大", "大人", "今天", "一支", "一下", "一个", "的时", "时候"}


def asks_about_her(text: str) -> bool:
    """Whether this message asks about her own day / what she's doing."""
    return bool(ASKS_ABOUT_HER.search((text or "").strip()))


def _bigrams(text: str) -> set[str]:
    cjk = re.findall(r"[一-鿿]+", text or "")
    grams = {run[i:i + 2] for run in cjk for i in range(len(run) - 1)}
    return grams - _STOP_BIGRAMS


def mentions(item_text: str, reply: str) -> bool:
    """Whether her reply retells this schedule item (enough shared two-character pieces)."""
    item = _bigrams(item_text)
    if not item:
        return False
    shared = item & _bigrams(reply)
    return len(shared) >= max(3, int(len(item) * 0.4 + 0.5))


def told_in(plan: dict, umo: str) -> set[str]:
    """Keys of the items she already told in this chat today ("HH:MM" for events, "share")."""
    return set(((plan.get("told") or {}).get(umo)) or [])


def mark_told(plan: dict, umo: str, reply: str) -> list[str]:
    """Record which of today's items her reply in `umo` talked about. Returns the newly told keys."""
    told = told_in(plan, umo)
    new = []
    for e in plan.get("events") or []:
        if e["time"] not in told and mentions(e["text"], reply):
            new.append(e["time"])
    share = plan.get("share") or {}
    if "share" not in told and share.get("text") and mentions(share["text"], reply):
        new.append("share")
    if new:
        plan.setdefault("told", {})[umo] = sorted(told | set(new))
    return new


NOT_ASKED_NOTE = (
    "\n\n【佳树的今天】这次对方没问起你自己的生活：专心回应对方说的，"
    "不要主动讲你今天做了什么、去了哪、买了什么，也别用\"对了\"把话题拐到自己身上。"
)


def render_note(plan: dict, now: dt.datetime, day_start_hour: int = 5,
                asked: bool = True, told: set[str] | frozenset = frozenset()) -> str:
    """Build the prompt note about her day.

    Args:
        plan: Today's plan (events / mood / share).
        now: Current time in the bot's timezone.
        day_start_hour: Hours before this still count as the previous day.
        asked: Whether the message asks about her day. If not, only a short "don't volunteer it" note.
        told: Items already told in this chat ("HH:MM" / "share"), marked so she doesn't retell them.
    """
    if not asked:
        return NOT_ASKED_NOTE
    hm = now.strftime("%H:%M")
    if now.hour < day_start_hour:  # 凌晨还算前一天，事情都已经发生了
        hm = "99:99"
    done = [e for e in plan["events"] if e["time"] <= hm]
    upcoming = [e for e in plan["events"] if e["time"] > hm][:1]
    lines = [f"- {e['time']} {e['text']}" + ("（在这里已经说过了）" if e["time"] in told else "")
             for e in done[-5:]]
    if upcoming:
        lines.append(f"- 接下来打算：{upcoming[0]['time']} {upcoming[0]['text']}")
    if not lines:
        return ""
    note = ("\n\n【佳树的今天】对方问起了你自己的事，这是你今天的生活。挑一两件和对方问的相关的说，"
            "别一次全说；标着\"已经说过了\"的别再讲一遍，除非对方追问：\n" + "\n".join(lines))
    if plan.get("mood"):
        note += f"\n心情：{plan['mood']}"
    share = plan.get("share") or {}
    if share.get("text") and share.get("time", "99:99") <= hm and "share" not in told:
        note += f"\n今天印象最深的一件小事：{share['text']}"
    return note


class Daily:
    """Generates and stores her daily schedule (days.json keeps the last 7 days)."""

    def __init__(self, body, cfg, folder: str):
        """
        Args:
            body: kaju_core.body.Body（模型、日志）。
            cfg: Callable returning the "daily" config section.
            folder: Plugin data folder.
        """
        self.body = body
        self.log = body.log
        self.cfg = cfg
        self._path = os.path.join(folder, "days.json")
        try:
            with open(self._path, encoding="utf-8") as f:
                self.days: dict = json.load(f)
        except FileNotFoundError:
            self.days = {}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_life: 读不了 days.json: {exc}")
            self.days = {}
        self._task: asyncio.Task | None = None
        self._last_fail = 0.0

    def _save(self) -> None:
        keep = sorted(self.days)[-7:]
        self.days = {k: self.days[k] for k in keep}
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self.days, f, ensure_ascii=False, indent=1)

    def note_reply(self, key: str, umo: str, reply: str) -> None:
        """Remember which of today's items she just told in this chat."""
        plan = self.days.get(key)
        if not plan or not reply:
            return
        new = mark_told(plan, umo, reply)
        if new:
            try:
                self._save()
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_life: 存不了 days.json: {exc}")
            self.log.info(f"kaju_life: {umo} 讲过了今天的 {new}")

    async def generate(self, umo: str, key: str, now: dt.datetime) -> dict | None:
        history = "\n".join(
            f"{k}：心情 {v.get('mood', '')}；" + "；".join(e["text"] for e in v.get("events", [])[:6])
            for k, v in sorted(self.days.items())[-3:] if k != key
        ) or "（没有）"
        weekend = now.weekday() >= 5
        prompt = GEN_PROMPT.format(
            date=now.strftime("%Y年%m月%d日"), wd=WEEKDAYS[now.weekday()],
            season_note=(f"现在是{now.month}月，离高中入学考试还有几个月，复习越来越紧。" if now.month >= 9
                         else f"现在是{now.month}月，高中入学考试就快到了。" if now.month <= 2
                         else f"现在是{now.month}月。"),
            history=history,
            day_note="今天周末不上学，可以有补习、做饭、出门买东西、在家复习之类。" if weekend
            else "今天上学，白天大多在学校（上课、课间、午饭、放学后学生会），晚上在家。",
        )
        text = await self.body.think(prompt, GEN_SYSTEM, who=umo, timeout=float(self.cfg().get("timeout_seconds", 90)))
        plan = parse_plan(text)
        if plan:
            self.days[key] = plan
            self._save()
            self.log.info(f"kaju_life: 写好了 {key} 的日程: {plan}")
        else:
            self.log.warning(f"kaju_life: 日程解析失败: {text[:200]!r}")
        return plan

    def kick(self, umo: str, key: str, now: dt.datetime) -> None:
        """Start a background generation unless one is running or one failed in the last 10 minutes."""
        if self._task and not self._task.done():
            return
        if time.time() - self._last_fail < 600:
            return

        async def run():
            try:
                if not await self.generate(umo, key, now):
                    self._last_fail = time.time()
            except Exception as exc:  # noqa: BLE001
                self._last_fail = time.time()
                self.log.warning(f"kaju_life: 生成日程失败: {exc}")

        self._task = asyncio.create_task(run())
