"""佳树的日记：分层记忆（借鉴 BaiShou-Next 的"日记 → 周记 → 月记"）。

Memorix 管"知道什么"（事实、人物关系，按语义检索），这里管"什么时候发生了什么"：
按时间顺序沉淀下来的回忆，不怕重复（反复出现说明重要），有时间感。

- 记录：所有收到的消息 + 她自己的回复，按天写进 log/日期.jsonl。
- 写日记：后台每 10 分钟看一次，前一天有聊天但还没日记 → 用她的口吻写当天日记
  （完整版 / 对外版 / 一句话 / 待办）。一周结束写周记，一个月结束写月记（从周记 + 日记来）。
  都存成 JSON（index.json）并另存一份 Markdown 方便人看（diary/ weekly/ monthly/）。
- 注入：把"最近的回忆"按层级拼进系统提示：较早的月记、没被月记覆盖的周记、
  最近几天的日记（最近两篇完整，其余一句话），外加还没兑现的约定。
  完整版只在主人私聊里给；群聊和其他人私聊只给对外版（不含私聊内容）。
"""

import asyncio
import datetime as dt
import json
import os
import re
import time

from .. import paths, people
from ..memory.rater import parse_json as _parse_json  # 和记忆那边同一份（11-18 整理合并）

WEEKDAYS = "一二三四五六日"
MEME_TAG = re.compile(r"&&[^&\n]{1,40}&&")
# 聊天记录多记几样（11-18 晚，照 MaiBot 回复器看的聊天：引用、@、图片内容都写出来）：
# 每条带编号 "i"；引用 "q" = {"u", "n", "x"}；@ 了她 "am" = true；群里的图的描述另存 log_caps/<日>.jsonl（{"i", "cap"}），
# recent() 读的时候并进 "cap"（图是先记、后描述的：kaju_basics 包住的描述函数描述完了调 note_caption）。
LOG_REF = "_kaju_log_ref"
PENDING_CAPS = "_kaju_pending_caps"  # 这条还没记进聊天记录时先描述好的图
_ACTIVE = None  # 现在这份 Diary（插件重载会换新的）


def note_caption(event, caption: str) -> None:
    """群里这条消息的图描述好了：记到聊天记录里这条后面（kaju_basics 调）。没记过这条就不管。"""
    if event is None or not caption:
        return
    d, ref = _ACTIVE, event.get_extra(LOG_REF)
    if d is not None and ref:
        d.add_caption(ref, caption)
        return
    # 11-19：AstrBot 自带的群聊上下文（优先级 maxsize-2）比 kaju_life 记这条（maxsize-5）先跑，图描述好时这条还没记，
    # 描述就丢了（log_caps 一直是空的）。先挂在消息上，log_incoming 记好这条再写进去。
    try:
        event.set_extra(PENDING_CAPS, (event.get_extra(PENDING_CAPS) or []) + [caption])
    except Exception:  # noqa: BLE001
        pass


def _marks(event) -> dict:
    """这条消息引用了谁（"q"）、有没有 @ 她（"am"）。AstrBot 的 message_str 里没有第一个 @她、也没有引用。"""
    out: dict = {}
    me = str(event.get_self_id() or "")
    try:
        comps = list(event.get_messages() or [])
    except Exception:  # noqa: BLE001
        return out
    for c in comps:
        kind = type(c).__name__
        if kind == "Reply":
            su = str(getattr(c, "sender_id", "") or "")
            mine = bool(me) and su == me
            x = str(getattr(c, "message_str", "") or "").strip()
            if not x and getattr(c, "chain", None):
                x = "[图片]" if any(type(z).__name__ == "Image" for z in c.chain) else ""
            out["q"] = {"u": "self" if mine else su, "n": "佳树" if mine else str(getattr(c, "sender_nickname", "") or ""),
                        "x": x[:80]}
        elif kind == "At" and me and str(getattr(c, "qq", "") or "") == me:
            out["am"] = True
    return out


def _cn_date(key: str) -> str:
    """'2026-10-29' -> '2026年10月29日'"""
    d = dt.date.fromisoformat(key)
    return f"{d.year}年{d.month}月{d.day}日"

PERSONA = (
    "你是温水佳树，初三女生，学生会副会长，正在备考石蕗高中，擅长做饭做点心，"
    "非常黏也非常操心哥哥（叫他\"兄长大人\"），性格开朗、爱操心、有点小醋意。"
    "你平时在手机上和兄长大人、群里的朋友们聊天。"
)

DIARY_SYSTEM = PERSONA + "现在是晚上，你在写今天的日记，写给自己看，以后回想用。只输出 JSON。"

DIARY_PROMPT = """日期：{date}（星期{wd}）
今天的聊天记录（[时间] 名字: 内容；"佳树（我）"是你自己说的话）：
{transcript}
{own_day}
请写今天的日记，输出 JSON：
{{"full": "完整日记", "public": "对外版", "brief": "一句话", "todo": [{{"text": "待办", "private": false}}]}}
要求：
- full：150~400字，开头不用写日期标题，用佳树自己的口吻（第一人称，也可以自称佳树），按时间顺序写今天跟谁聊了什么、发生了什么、自己的心情。
  记清楚具体的人（用称呼或昵称）、对方的近况和情绪、聊到的事、约好的事、自己答应过的事。
  心情用大白话直接写（开心、难过、舍不得、有点慌），不写手心发汗、喉咙发紧、心口一紧这类身体反应，
  不用"太满""留白""有分量"这类书评的词；聊天记录里自己说过这种话，写进日记时也换成大白话。
- 只写聊天记录里真的发生过的事，不要编造，看不出来的就不写；自己的日常安排可以轻轻带过，别喧宾夺主。
- 同一个话题或情绪今天反复出现，就如实写出来（反复出现说明它重要），不要因为重复就省略。
- public：60~200字，可以讲给别人听的版本，只写群里的事和自己的日常，私聊里的内容一律不写。
- brief：一句话概括今天，30字以内。
- todo：过几天还有意义的事——还没完成的约定、答应别人要做的事、在等结果的事（考试、面试、快递、到货……），最多5条，没有就空列表；只在私聊里出现的标 private: true。
  一次性的小关心不要记：某一顿饭吃没吃、某天睡没睡好、早点睡别熬夜——过了那天就没意义了；已经问过、对方没接话的，也不要记（别追着问）。
  今天之内后来已经办完、看完、问到、说开的事也不要记（看完整天的聊天再决定）。
  写具体日期，不要用"昨晚""今天""明天"这种说法（写"10月30日的面试结果"，不写"昨天的面试结果"）。"""

WEEKLY_SYSTEM = PERSONA + "你在翻这一周的日记，写一篇周记，把这一周沉淀下来。只输出 JSON。"

WEEKLY_PROMPT = """这一周：{start} 至 {end}（{label}）
这一周的日记：
{diaries}

请写周记，输出 JSON：
{{"full": "周记", "public": "对外版", "brief": "一两句话", "todo": [{{"text": "待办", "private": false}}]}}
要求：
- full：200~500字，开头不用写标题，佳树的口吻，可以分几小段：这周的关键词；身边的人和关系有什么变化（兄长大人、朋友们各自怎么样）；
  这周发生的重要的事；自己的心情和状态；最后一句话留给月记。
- 只根据日记写，不要编造；反复出现的人和事要写出来（反复说明重要）。
- public：80~200字，不含任何私聊内容。
- brief：一两句话，60字以内。
- todo：到这周末还没兑现的约定或要记得的事，最多5条；私聊里的标 private: true。"""

MONTHLY_SYSTEM = PERSONA + "你在翻这个月的周记和日记，写一篇月记。只输出 JSON。"

MONTHLY_PROMPT = """这个月：{label}（{start} 至 {end}）
这个月的周记：
{weeklies}

这个月每天的一句话：
{briefs}

请写月记，输出 JSON：
{{"full": "月记", "public": "对外版", "brief": "两三句话"}}
要求：
- full：200~500字，开头不用写标题，佳树的口吻：这个月的主题；和兄长大人、朋友们的关系有什么变化；重要的事；自己的状态；对下个月的期待。
- 只根据上面的内容写，不要编造。
- public：80~200字，不含任何私聊内容。
- brief：两三句话，80字以内。"""


# ---------------------------------------------------------------- helpers
# 一次性的小关心（某顿饭吃没吃、某晚睡没睡）：过了那天就没意义，记成待办会天天追问
_PERISHABLE = re.compile(
    r"那顿饭|吃没吃|吃了没|吃上没|吃上了没|有没有吃|吃过饭?了?没|饭.{0,4}吃[上了过]?没|"
    r"睡没睡|睡好没|有没有睡|睡得(?:好不好|怎么样)|熬夜|熬太晚|早点睡|别熬")

# 待办里相对的说法 → 具体日期（按记下那天算），隔几天再看也不会错位
_RELATIVE = [
    ("前天晚上", -2, "晚上"), ("前晚", -2, "晚上"), ("前天", -2, ""),
    ("昨天晚上", -1, "晚上"), ("昨晚", -1, "晚上"), ("昨夜", -1, "夜里"), ("昨天", -1, ""),
    ("今天晚上", 0, "晚上"), ("今晚", 0, "晚上"), ("今早", 0, "早上"), ("今天", 0, ""),
    ("明天晚上", 1, "晚上"), ("明晚", 1, "晚上"), ("明早", 1, "早上"), ("明天", 1, ""), ("后天", 2, ""),
]
_RELATIVE_RE = re.compile("|".join(re.escape(w) for w, _, _ in _RELATIVE))
_RELATIVE_MAP = {w: (off, part) for w, off, part in _RELATIVE}


def perishable(text: str) -> bool:
    return bool(_PERISHABLE.search(text or ""))


def absolute_dates(text: str, key: str) -> str:
    """'昨晚那顿饭，明天问一句'（10-31 记）→ '10月30日晚上那顿饭，11月1日问一句'。"""
    base = dt.date.fromisoformat(key)

    def rep(m):
        off, part = _RELATIVE_MAP[m.group(0)]
        d = base + dt.timedelta(days=off)
        return f"{d.month}月{d.day}日{part}"

    return _RELATIVE_RE.sub(rep, text or "")


def _clean_entry(data: dict | None, brief_max: int) -> dict | None:
    if not data:
        return None
    full = str(data.get("full", "")).strip()
    if len(full) < 30:
        return None
    todo = []
    for t in data.get("todo") or []:
        if isinstance(t, dict) and str(t.get("text", "")).strip():
            todo.append({"text": str(t["text"]).strip()[:80], "private": bool(t.get("private", False))})
        elif isinstance(t, str) and t.strip():
            todo.append({"text": t.strip()[:80], "private": True})
    return {
        "full": full[:1500],
        "public": str(data.get("public", "")).strip()[:800],
        "brief": str(data.get("brief", "")).strip()[:brief_max],
        "todo": todo[:5],
        "written": int(time.time()),
    }


def week_key(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_range(key: str) -> tuple[dt.date, dt.date]:
    y, w = key.split("-W")
    start = dt.date.fromisocalendar(int(y), int(w), 1)
    return start, start + dt.timedelta(days=6)


def month_range(key: str) -> tuple[dt.date, dt.date]:
    y, m = map(int, key.split("-"))
    start = dt.date(y, m, 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return start, nxt - dt.timedelta(days=1)


def thin_lines(lines: list[str], keep: list[bool], budget: int) -> list[str]:
    """Drop unimportant lines evenly until the text fits the budget."""
    total = sum(len(s) + 1 for s in lines)
    if total <= budget:
        return lines
    droppable = [i for i, k in enumerate(keep) if not k]
    need = total - budget
    drop: set[int] = set()
    if droppable:
        avg = max(1, sum(len(lines[i]) + 1 for i in droppable) // len(droppable))
        n = min(len(droppable), need // avg + 1)
        step = len(droppable) / n
        drop = {droppable[int(j * step)] for j in range(n)}
    out, skipped = [], 0
    for i, s in enumerate(lines):
        if i in drop:
            skipped += 1
            continue
        if skipped:
            out.append(f"（省略 {skipped} 条）")
            skipped = 0
        out.append(s)
    if skipped:
        out.append(f"（省略 {skipped} 条）")
    text = "\n".join(out)
    return text[-budget:].split("\n") if len(text) > budget else out


class Diary:
    """Chat log, diary / weekly / monthly writing, prompt note and diary lookups."""

    def __init__(self, body, cfg, folder: str, now, day_key, own_plan):
        """
        Args:
            body: kaju_core.body.Body（模型、设置、群名、日志）。
            cfg: Callable returning the "diary" config section.
            folder: Plugin data folder (log/ diary/ weekly/ monthly/ index.json names.json live here).
            now: Callable returning the current time in the bot's timezone.
            day_key: Callable (datetime | None) -> "YYYY-MM-DD" of the bot day it belongs to.
            own_plan: Callable (day) -> her own daily schedule dict for that day, or None.
        """
        self.body = body
        self.log = body.log
        self.cfg = cfg
        self.now = now
        self.day_key = day_key
        self.own_plan = own_plan
        self._dir = folder
        for sub in ("log", "log_caps", "diary", "weekly", "monthly"):
            os.makedirs(os.path.join(self._dir, sub), exist_ok=True)
        self._idx_path = os.path.join(self._dir, "index.json")
        self._names_path = os.path.join(self._dir, "names.json")
        self._idx = self._load(self._idx_path, {})
        for k in ("diary", "weekly", "monthly", "skip"):
            self._idx.setdefault(k, {})
        self._names = self._load(self._names_path, {"groups": {}, "people": {}})
        self.busy = asyncio.Lock()
        global _ACTIVE
        _ACTIVE = self

    # ------------------------------------------------------------ storage
    def _load(self, path: str, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_life: 读不了 {path}: {exc}")
            return default

    @staticmethod
    def _dump(path: str, data) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def _append_log(self, rec: dict) -> str:
        """记一条；返回它记在哪一天的文件里（"YYYY-MM-DD"）。"""
        now = self.now()
        rec = {"t": now.strftime("%H:%M"), **rec}
        day = self.day_key(now)
        path = os.path.join(self._dir, "log", day + ".jsonl")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_life: 写聊天记录失败: {exc}")
        return day

    def add_caption(self, ref, caption: str) -> None:
        day, i = ref
        try:
            with open(os.path.join(self._dir, "log_caps", f"{day}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"i": i, "cap": str(caption).strip()[:300]}, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_life: 记图片描述失败: {exc}")

    def _read_caps(self, day: str) -> dict:
        out: dict = {}
        try:
            with open(os.path.join(self._dir, "log_caps", day + ".jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("i") and r.get("cap"):
                        out.setdefault(r["i"], []).append(r["cap"])
        except FileNotFoundError:
            pass
        return out

    def _read_log(self, day: str) -> list[dict]:
        path = os.path.join(self._dir, "log", day + ".jsonl")
        out = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except FileNotFoundError:
            pass
        return out

    def _log_days(self) -> list[str]:
        return sorted(f[:-6] for f in os.listdir(os.path.join(self._dir, "log")) if f.endswith(".jsonl"))

    def recent(self, chat: str, n: int) -> list[dict]:
        """这个聊天（"g群号" / "pQQ"）最近 n 条记录，按到达顺序（今天的不够就往前一天补）。
        kaju_style 重说层用：群里别人之间说的话也给抽卡 / 写手 / 核对看（2026-11-09）。"""
        out: list[dict] = []
        try:
            days = self._log_days()[-2:]
        except OSError:
            return []
        for day in reversed(days):  # 每条带上日期 "d"（11-17 写手看长前文要按天插日期行；别的用法不看它）
            caps = self._read_caps(day)
            out = [dict(r, d=day, **({"cap": caps[r["i"]]} if r.get("i") in caps else {}))
                   for r in self._read_log(day) if r.get("c") == chat] + out
            if len(out) >= n:
                break
        return out[-n:] if n > 0 else []

    def _write_md(self, kind: str, key: str, title: str, entry: dict) -> None:
        lines = [f"# {title}", "", entry["full"], "", "## 对外版", "", entry.get("public", ""), "",
                 "## 一句话", "", entry.get("brief", "")]
        if entry.get("todo"):
            lines += ["", "## 还记着的事", ""]
            lines += [f"- {t['text']}" + ("（私聊）" if t.get("private") else "") for t in entry["todo"]]
        try:
            with open(os.path.join(self._dir, kind, key + ".md"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_life: 写 Markdown 失败: {exc}")

    # ------------------------------------------------------------ people / groups
    def _owner_ids(self) -> set[str]:
        """谁是兄长大人（日记里这么叫、能看私聊的日记）：配置 owner_ids 写了就用它；没写看身份表（kaju_core.people）；
        身份表也没登记才用 AstrBot 管理员（以前就是这样，管理员 999999999 不是兄长，2026-11-09 改掉）。"""
        ids = {s.strip() for s in str(self.cfg().get("owner_ids", "")).replace("，", ",").split(",") if s.strip()}
        if ids:
            return ids
        if people.owner():
            return {people.owner()}
        return {str(a) for a in self.body.settings().get("admins_id", []) if str(a).isdigit()}

    def _person_label(self, qq: str, name: str) -> str:
        path = os.path.join(paths.self_dir("address_book"), "addresses.json")
        addr = (self._load(path, {}).get(qq) or {}).get("address")
        if qq in self._owner_ids():
            return f"兄长大人（{name}）" if name and name != "兄长大人" else "兄长大人"
        if addr:
            return f"{name}（你叫TA{addr}）"
        return name or f"QQ{qq}"

    def _chat_label(self, chat: str) -> str:
        if chat.startswith("g"):
            gid = chat[1:]
            name = self._names["groups"].get(gid)
            return f"群聊「{name}」" if name else f"群聊（{gid}）"
        qq = chat[1:]
        name = self._names["people"].get(qq, "")
        return f"私聊·{self._person_label(qq, name)}"

    async def _remember_group_name(self, event, gid: str) -> None:
        if gid in self._names["groups"]:
            return
        name = await self.body.group_name(event, gid)
        self._names["groups"][gid] = name or gid
        self._dump(self._names_path, self._names)

    # ------------------------------------------------------------ logging
    async def log_incoming(self, event) -> None:
        sid = str(event.get_sender_id() or "")
        if not sid or sid == str(event.get_self_id() or ""):
            return
        text = (event.message_str or "").strip()
        if not text:
            kinds = {type(c).__name__ for c in event.get_messages()}
            files = [getattr(c, "name", "") or "文件" for c in event.get_messages() if type(c).__name__ == "File"]
            text = ("[图片]" if "Image" in kinds else "[表情]" if "Face" in kinds else "[视频]" if "Video" in kinds
                    else "".join(f"[文件《{n}》]" for n in files))
        if not text or text.startswith("/"):
            return
        gid = str(event.get_group_id() or "")
        name = str(event.get_sender_name() or "")
        if name and self._names["people"].get(sid) != name:
            self._names["people"][sid] = name
            self._dump(self._names_path, self._names)
        if gid:
            await self._remember_group_name(event, gid)
        rec = {"c": f"g{gid}" if gid else f"p{sid}", "u": sid, "n": name, "x": text[:300], "i": os.urandom(5).hex()}
        rec.update(_marks(event))
        day = self._append_log(rec)
        try:
            event.set_extra(LOG_REF, (day, rec["i"]))
            for cap in event.get_extra(PENDING_CAPS) or []:
                self.add_caption((day, rec["i"]), cap)
            event.set_extra(PENDING_CAPS, None)
        except Exception:  # noqa: BLE001
            pass

    def log_reply(self, event, text: str) -> None:
        text = (text or "").strip()
        if not text or "[SKIP]" in text.upper():
            return
        text = MEME_TAG.sub("", text).strip()
        if not text:
            return
        gid = str(event.get_group_id() or "")
        sid = str(event.get_sender_id() or "")
        self._append_log({"c": f"g{gid}" if gid else f"p{sid}", "u": "self", "n": "佳树", "x": text[:300]})

    # ------------------------------------------------------------ generation
    async def _ask(self, system: str, prompt: str) -> str:
        return await self.body.think(prompt, system, timeout=float(self.cfg().get("timeout_seconds", 180)))

    def _transcript(self, recs: list[dict], budget: int) -> str:
        chats: dict[str, list[dict]] = {}
        for r in recs:
            chats.setdefault(r.get("c", "?"), []).append(r)
        # 私聊放前面，群聊按她说话多少排
        order = sorted(chats, key=lambda c: (not c.startswith("p"), -sum(r.get("u") == "self" for r in chats[c])))
        blocks = []
        share = max(1500, budget // max(1, len(order)))
        for c in order:
            rs = chats[c]
            lines, keep = [], []
            for i, r in enumerate(rs):
                who = "佳树（我）" if r.get("u") == "self" else self._person_label(str(r.get("u", "")), r.get("n", ""))
                lines.append(f"[{r.get('t', '')}] {who}: {r.get('x', '')}")
                near_me = r.get("u") == "self" or any(x.get("u") == "self" for x in rs[i + 1:i + 3])
                keep.append(near_me or c.startswith("p"))
            lines = thin_lines(lines, keep, share)
            blocks.append(f"【{self._chat_label(c)}】\n" + "\n".join(lines))
        return "\n\n".join(blocks)

    def _own_day(self, day: str) -> str:
        plan = self.own_plan(day)
        if not plan:
            return ""
        evs = "；".join(f"{e['time']} {e['text']}" for e in plan.get("events", []))
        return f"\n你自己今天的安排（可以轻轻带过）：{evs}。心情：{plan.get('mood', '')}\n"

    async def write_diary(self, day: str) -> dict | None:
        recs = self._read_log(day)
        if not recs:
            return None
        d = dt.date.fromisoformat(day)
        prompt = DIARY_PROMPT.format(
            date=f"{d.year}年{d.month}月{d.day}日", wd=WEEKDAYS[d.weekday()],
            transcript=self._transcript(recs, int(self.cfg().get("transcript_budget", 16000))),
            own_day=self._own_day(day),
        )
        entry = _clean_entry(_parse_json(await self._ask(DIARY_SYSTEM, prompt)), 40)
        if not entry:
            self.log.warning(f"kaju_life: {day} 的日记没写成（解析失败）")
            return None
        dropped = [t["text"] for t in entry["todo"] if perishable(t["text"])]
        if dropped:
            self.log.info(f"kaju_life: {day} 的待办里去掉一次性的小关心：{'；'.join(dropped)}")
        entry["todo"] = [{**t, "text": absolute_dates(t["text"], day)} for t in entry["todo"] if not perishable(t["text"])]
        self._idx["diary"][day] = entry
        self._idx["skip"].pop(day, None)
        self._dump(self._idx_path, self._idx)
        self._write_md("diary", day, f"{d.month}月{d.day}日 星期{WEEKDAYS[d.weekday()]}", entry)
        self.log.info(f"kaju_life: 写好了 {day} 的日记：{entry['brief']}")
        return entry

    async def write_weekly(self, wk: str) -> dict | None:
        start, end = week_range(wk)
        days = [k for k in sorted(self._idx["diary"]) if start.isoformat() <= k <= end.isoformat()]
        if not days:
            return None
        diaries = "\n\n".join(f"【{k}】\n{self._idx['diary'][k]['full']}" for k in days)
        label = f"{end.month}月第{(end.day - 1) // 7 + 1}周"
        prompt = WEEKLY_PROMPT.format(start=start.isoformat(), end=end.isoformat(), label=label, diaries=diaries[-20000:])
        entry = _clean_entry(_parse_json(await self._ask(WEEKLY_SYSTEM, prompt)), 80)
        if not entry:
            self.log.warning(f"kaju_life: {wk} 的周记没写成")
            return None
        entry["label"] = label
        self._idx["weekly"][wk] = entry
        self._dump(self._idx_path, self._idx)
        self._write_md("weekly", wk, f"周记 {start} ~ {end}", entry)
        self.log.info(f"kaju_life: 写好了 {wk} 的周记：{entry['brief']}")
        return entry

    async def write_monthly(self, mk: str) -> dict | None:
        start, end = month_range(mk)
        days = [k for k in sorted(self._idx["diary"]) if start.isoformat() <= k <= end.isoformat()]
        if not days:
            return None
        weeks = [w for w in sorted(self._idx["weekly"])
                 if week_range(w)[1] >= start and week_range(w)[0] <= end]
        weeklies = "\n\n".join(f"【{w}】\n{self._idx['weekly'][w]['full']}" for w in weeks) or "（没有）"
        briefs = "\n".join(f"{k}：{self._idx['diary'][k]['brief']}" for k in days)
        label = f"{start.year}年{start.month}月"
        prompt = MONTHLY_PROMPT.format(label=label, start=start, end=end, weeklies=weeklies[-16000:], briefs=briefs)
        entry = _clean_entry(_parse_json(await self._ask(MONTHLY_SYSTEM, prompt)), 100)
        if not entry:
            self.log.warning(f"kaju_life: {mk} 的月记没写成")
            return None
        entry["label"] = label
        self._idx["monthly"][mk] = entry
        self._dump(self._idx_path, self._idx)
        self._write_md("monthly", mk, f"{label} 月记", entry)
        self.log.info(f"kaju_life: 写好了 {mk} 的月记：{entry['brief']}")
        return entry

    async def catch_up(self) -> None:
        """Write whatever diary / weekly / monthly is due. Runs one item at a time."""
        async with self.busy:
            today = self.day_key()
            min_lines = int(self.cfg().get("min_lines", 4))
            for day in self._log_days():
                if day >= today or day in self._idx["diary"] or day in self._idx["skip"]:
                    continue
                recs = self._read_log(day)
                if len(recs) < min_lines or not any(r.get("u") == "self" for r in recs):
                    self._idx["skip"][day] = len(recs)
                    self._dump(self._idx_path, self._idx)
                    continue
                await self.write_diary(day)
            today_d = dt.date.fromisoformat(today)
            weeks = sorted({week_key(dt.date.fromisoformat(k)) for k in self._idx["diary"]})
            for wk in weeks:
                if wk not in self._idx["weekly"] and week_range(wk)[1] < today_d:
                    await self.write_weekly(wk)
            months = sorted({k[:7] for k in self._idx["diary"]})
            for mk in months:
                if mk not in self._idx["monthly"] and month_range(mk)[1] < today_d:
                    await self.write_monthly(mk)

    async def loop(self) -> None:
        await asyncio.sleep(90)
        fails = 0
        while True:
            if self.cfg().get("enable", True):
                try:
                    await self.catch_up()
                    fails = 0
                except Exception as exc:  # noqa: BLE001
                    fails += 1
                    self.log.warning(f"kaju_life: 写日记出错（第{fails}次）: {exc}")
            await asyncio.sleep(600 * min(fails + 1, 6))

    # ------------------------------------------------------------ injection
    def can_see_private(self, event) -> bool:
        return not event.get_group_id() and str(event.get_sender_id() or "") in self._owner_ids()

    def build_memory_note(self, private: bool, now: dt.datetime | None = None) -> str:
        today = self.day_key(now)
        today_d = dt.date.fromisoformat(today)
        items: list[tuple[str, str]] = []  # (label, text)，从早到晚

        # 分层：最近一周的日记总是在（刚写完月记那天也不会把昨天"折叠"掉，借鉴白守季报级联的处理），
        # 更早的用周记，再早的用月记；层与层之间稍有重叠没关系（"拥抱冗余"）。
        recent = int(self.cfg().get("recent_days", 7))
        first_day = (today_d - dt.timedelta(days=recent)).isoformat()
        days = [k for k in sorted(self._idx["diary"]) if first_day <= k < today]
        edge = dt.date.fromisoformat(days[0]) if days else today_d
        weeks = [w for w in sorted(self._idx["weekly"]) if week_range(w)[0] < edge][-2:]
        if weeks:
            edge = week_range(weeks[0])[0]
        months = [m for m in sorted(self._idx["monthly"]) if month_range(m)[0] < edge][-2:]

        for m in months:
            e = self._idx["monthly"][m]
            items.append((f"{e.get('label', m)}（月记）", e.get("brief", "")))
        for w in weeks:
            e = self._idx["weekly"][w]
            s, t = week_range(w)
            items.append((f"{s.month}/{s.day}~{t.month}/{t.day}（周记）", e.get("brief", "")))
        n_full = int(self.cfg().get("full_days", 2))
        for i, k in enumerate(days):
            e = self._idx["diary"][k]
            d = dt.date.fromisoformat(k)
            ago = (today_d - d).days
            tag = {1: "昨天", 2: "前天"}.get(ago, f"星期{WEEKDAYS[d.weekday()]}")
            if i < len(days) - n_full:
                text = e.get("brief", "")
            elif private:
                text = e.get("full", "")
            else:  # brief 本身不写私聊细节，兜底用
                text = e.get("public", "") or e.get("brief", "")
            items.append((f"{d.month}月{d.day}日（{tag}）", text))

        items = [(lab, txt) for lab, txt in items if txt]
        if not items:
            return ""

        # 待办标上是哪天记的，里面的"昨晚/明天"换成具体日期（以前的日记里还有这种说法，隔天再看会错位）；
        # 一次性的小关心（某顿饭吃没吃……）不再拿出来，免得天天追问。新日记的待办优先占名额，显示时仍按从早到晚。
        todos: list[tuple[str, str]] = []  # (日期, 内容)
        for k in reversed(days[-2:]):
            for t in self._idx["diary"][k].get("todo", []):
                text = absolute_dates(t["text"], k)
                if (private or not t.get("private")) and not perishable(text) and all(text != x for _, x in todos):
                    todos.append((k, text))
        todos = sorted(todos[:5], key=lambda kt: kt[0])

        head = ("\n\n【佳树的日记】这是你自己写的日记，记着最近发生的事（越往下越近）。"
                "聊天时自然地记得这些事：别人的事合适的时候可以接着关心；你自己前几天做了什么，"
                "被问起或正好聊到时再说，别主动讲；别背日记、别一次全说。"
                "日记里那几天的小关心（某顿饭吃没吃、某晚睡没睡好）都已经过去了，不用再追问。"
                "日记里的\"昨晚\"\"明天\"是按写日记那天说的，不是按今天。"
                "想看某天完整的日记就用 read_diary 工具。")
        if not private:
            head += "（这里只有可以公开的部分，私聊里的事不要在这里提。）"
        budget = int(self.cfg().get("max_inject_chars", 1500))

        def render(its):
            body = "\n".join(f"· {lab}：{txt}" for lab, txt in its)
            if todos:
                body += ("\n还记着要做/要关心的事（括号里是记下的日期）：\n"
                         + "\n".join(f"- {t}（{_cn_date(k)}记）" for k, t in todos))
            return head + "\n" + body

        note = render(items)
        while len(note) > budget and len(items) > 1:
            items.pop(0)
            note = render(items)
        return note[: budget + 200]

    # ------------------------------------------------------------ lookups (tools / admin command)
    def resolve_when(self, when: str) -> tuple[str, str] | None:
        """Turn a user phrase (昨天 / 2026-10-29 / 上周 / 10月 …) into (kind, key)."""
        w = (when or "").strip()
        try:
            today = dt.date.fromisoformat(self.day_key())
            rel = {"今天": 0, "昨天": 1, "昨日": 1, "前天": 2, "大前天": 3}
            if not w or w in ("最近", "最新"):
                return ("diary", max(self._idx["diary"])) if self._idx["diary"] else None
            if w in rel:
                return "diary", (today - dt.timedelta(days=rel[w])).isoformat()
            if w in ("这周", "本周", "这星期"):
                return "week", week_key(today)
            if w in ("上周", "上星期", "上个星期"):
                return "week", week_key(today - dt.timedelta(days=7))
            if w in ("这个月", "本月"):
                return "month", today.strftime("%Y-%m")
            if w in ("上个月", "上月"):
                return "month", (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
            if re.fullmatch(r"\d{4}-W\d{2}", w):
                return "week", w
            m = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", w)
            if m:
                return "diary", dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
            m = re.fullmatch(r"(\d{1,2})[-/.月](\d{1,2})[日号]?", w)
            if m:
                d = dt.date(today.year, int(m[1]), int(m[2]))
                if d > today:
                    d = d.replace(year=today.year - 1)
                return "diary", d.isoformat()
            m = re.fullmatch(r"(?:(\d{4})[-年])?(\d{1,2})月?(?:份)?", w)
            if m and 1 <= int(m[2]) <= 12:
                y = int(m[1]) if m[1] else today.year
                if not m[1] and int(m[2]) > today.month:
                    y -= 1
                return "month", f"{y}-{int(m[2]):02d}"
        except ValueError:
            return None
        return None

    def _render_entry(self, kind: str, key: str, entry: dict, private: bool) -> str:
        text = entry.get("full", "") if private else (entry.get("public", "") or entry.get("brief", ""))
        out = f"{kind} {key}：\n{text}"
        todos = [t["text"] for t in entry.get("todo", []) if private or not t.get("private")]
        if todos:
            out += "\n当时还记着的事：" + "；".join(todos)
        return out

    def read(self, event, when: str) -> str:
        private = self.can_see_private(event)
        r = self.resolve_when(when)
        if not r:
            return f"没看懂「{when}」是哪天，换个说法，比如 2026-10-29、昨天、上周、10月。"
        kind, key = r
        if kind == "diary":
            e = self._idx["diary"].get(key)
            if e:
                return self._render_entry("日记", key, e, private)
            if key >= self.day_key():
                return "今天的日记还没写（晚上过了才写），今天的事直接看聊天记录就好。"
            near = [k for k in sorted(self._idx["diary"]) if abs((dt.date.fromisoformat(k) - dt.date.fromisoformat(key)).days) <= 3]
            return f"{key} 没有日记（那天可能没怎么聊天）。" + (f"附近有：{'、'.join(near)}" if near else "")
        if kind == "week":
            e = self._idx["weekly"].get(key)
            if e:
                return self._render_entry("周记", key, e, private)
            s, t = week_range(key)
            days = [k for k in sorted(self._idx["diary"]) if s.isoformat() <= k <= t.isoformat()]
            if not days:
                return f"{s}~{t} 这周没有日记。"
            return "这周的周记还没写，这几天的日记：\n" + "\n\n".join(
                self._render_entry("日记", k, self._idx["diary"][k], private) for k in days[-4:])
        e = self._idx["monthly"].get(key)
        if e:
            return self._render_entry("月记", key, e, private)
        s, t = month_range(key)
        weeks = [w for w in sorted(self._idx["weekly"]) if week_range(w)[1] >= s and week_range(w)[0] <= t]
        days = [k for k in sorted(self._idx["diary"]) if s.isoformat() <= k <= t.isoformat()]
        if not weeks and not days:
            return f"{key} 没有日记。"
        parts = [self._render_entry("周记", w, self._idx["weekly"][w], private) for w in weeks]
        covered = {k for w in weeks for k in self._idx["diary"] if week_range(w)[0].isoformat() <= k <= week_range(w)[1].isoformat()}
        parts += [f"日记 {k}：{self._idx['diary'][k]['brief']}" for k in days if k not in covered]
        return f"{key} 的月记还没写，这个月的记录：\n" + "\n\n".join(parts)

    def search(self, event, keywords: str) -> str:
        private = self.can_see_private(event)
        words = [w for w in re.split(r"[\s,，、]+", keywords or "") if w]
        if not words:
            return "给个关键词。"
        hits = []
        for kind, label in (("diary", "日记"), ("weekly", "周记"), ("monthly", "月记")):
            for key, e in self._idx[kind].items():
                text = e.get("full", "") if private else (e.get("public", "") + " " + e.get("brief", ""))
                text += " " + " ".join(t["text"] for t in e.get("todo", []) if private or not t.get("private"))
                score = sum(text.count(w) for w in words)
                if score:
                    pos = min((text.find(w) for w in words if w in text), default=0)
                    snip = text[max(0, pos - 40): pos + 100].replace("\n", " ")
                    hits.append((score, key, f"{label} {key}：…{snip}…"))
        if not hits:
            return f"日记里没找到「{keywords}」。可能没写进日记，也可以换个词再找，或者用记忆工具查。"
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)  # 命中多的在前，同分新的在前
        return "\n".join(h[2] for h in hits[:6]) + "\n（要看全文用 read_diary 加日期）"

    def listing(self) -> str:
        ds = sorted(self._idx["diary"])[-10:]
        lines = [f"{k}：{self._idx['diary'][k]['brief']}" for k in ds]
        lines += [f"{w}（周记）：{self._idx['weekly'][w]['brief']}" for w in sorted(self._idx["weekly"])[-3:]]
        lines += [f"{m}（月记）：{self._idx['monthly'][m]['brief']}" for m in sorted(self._idx["monthly"])[-2:]]
        return ("佳树的日记\n" + ("\n".join(lines) or "还没有日记。")
                + "\n\n/佳树日记 日期｜上周｜10月 看全文；/佳树日记 补写 日期 重新写")
