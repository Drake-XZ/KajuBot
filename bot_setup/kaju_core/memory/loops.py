"""未了的事（open loops）：对方提过、还不知道后来怎么样的事（纯逻辑，不依赖 astrbot，离线可测）。

2026-11-18 兄长看了 anima-brain（github.com/spearsheep/anima-brain）后定"先做未了的事"。
那边的做法：事实里标了"还没结果、该问一句"的，按重要度、当时有多上心、过了多久、离事情那天多近排个先后，
排前面的放进下一轮的上下文；不主动发消息。这里照着做（代码是自己写的）：

- 记下：memory_weight 每几分钟读一遍 kaju_life 的聊天记录，攒够一段（安静下来）就交给模型看一遍：
  有没有新的"还没结果的事"（考试、面试、看病、出远门、等通知、正烦着还没解决的事……），
  已经记着的有没有了结果（考完了、取消了、日子改了）。模型只挑事、给日子和小整数，怎么排、给不给她看由这里算。
- 先后：priority = I × (1 + A) × exp(−t / (14 + 30A)) + U
    I = 要紧程度 1~10，A = 对方当时有多上心 0~1，t = 距最后一次提起的天数，
    U = 2 / (1 + |事情那天 − 今天|)（有日子才有；昨天和明天一样近）。
- 给她看：私聊给这个人的全部，群里只给在这个群里说的（和铭记一样）。不是每轮都给：
  对方这句话碰到了这件事的词 → 给；不然要日子近（前后 near_days 天）或者很要紧，而且同一件事 cooldown 小时内只给一次。
- 收起：有了结果（done）、取消 / 原来是玩笑（drop）的不再给；日子过了 stale_days 天还没下文、或者没日子的放久了分数太低，
  算"过去了"（stale），不再给（不删，/记忆轻重 未了 里还看得到）。
- 只写事实（谁的什么事、哪天），怎么说、说不说交给大脑和写手。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re

from .rater import parse_json  # noqa: F401  和 rater 同一份（11-18 整理合并）

STATUSES = ("open", "done", "drop", "stale")

SYSTEM = (
    "你在帮 QQ 聊天角色\"佳树\"（初三女生，叫最亲的人\"兄长大人\"）记下别人提过、还不知道后来怎么样的事，"
    "好让她以后记得关心一句。只输出 JSON。"
)

PROMPT = """{today}日历（推算"明天""周二""下周二"时照这个查，别自己数；按那句话是哪天说的来算）：
{calendar}
下面是一段聊天记录（[月-日 星期 时:分] 名字(QQ号): 内容；"佳树"是她自己说的；名字后面的括号是佳树对这个人的称呼）。
【之前】只是上下文，只看【新消息】。
【之前】
{before}
【新消息】
{lines}

【已经记着的还没结果的事】（编号: 谁 - 什么事 - 日子）
{known}

做两件事：
一、【新消息】里别人（不是佳树）提到的、还不知道结果的事，记成新的一条。
  只记"过几天能问一句'后来怎么样了'、而且会有个明确下文"的具体的事：
  说话的人自己（或他很上心的家人）要去做、要发生、正在等结果的——考试、面试、比赛、出成绩、看病复查住院、出远门、搬家、
  交作业 / 截止日、等通知 / 等录取 / 等快递、约好的事、说好以后再告诉佳树的事。
  不算的：
  - 心情和状态：累、忙、在复习、在加班、最近压力大、担心某个大话题（工作会不会被 AI 取代）——这些是"现在怎样"，不是一件会有下文的事；
    但要是他说了为什么在复习（下周有考试），就记那场考试。
  - 别人家的事、八卦、转述的别人的遭遇（说话的人自己并不等着它的结果）；新闻；
  - 要佳树做的事（提醒、帮忙查——另有人管）、佳树自己的事、当场就有结果的、玩笑 / 假设 / 游戏剧情里的、
    一时的小事（吃什么、马上就去做完的）、【已经记着的】里已有的同一件事。
  拿不准算不算就不记。
二、【已经记着的】里，【新消息】让它有了下文的：有了结果写 done（result 写结果），取消了或原来不是真的写 drop，
  日子改了写新日子（status 还是 open）。没提到的不要写。

输出 JSON：
{{"new": [{{"i": 编号（最能说明这件事的那句）, "what": "谁的什么事、还不知道的是什么（第三人称，用佳树对这个人的称呼或名字，30字以内）",
   "when": "聊天里说的是哪天，照抄原话里的说法（比如'下周二''明天''11月20号''周五'；没说就空字符串）",
   "date": "事情发生或出结果的日子 YYYY-MM-DD（照上面的日历查，说不准就空字符串）",
   "imp": 要紧程度1到10（8~10 健康、重要的考试面试、家里的大事；5~7 一般的安排；1~4 小事）,
   "care": 对方有多上心 0不太在意 / 1一般 / 2挺在意 / 3很在意或很紧张, "kw": ["两三个关键词"]}}],
 "update": [{{"id": "编号", "status": "done或drop或open", "result": "结果（20字以内，没有就空）",
   "when": "日子改了的话，原话里新的说法（没改就空）", "date": "新的日子 YYYY-MM-DD（没改就空）"}}]}}
什么都没有就输出 {{"new": [], "update": []}}。"""

WEEKDAYS = "一二三四五六日"


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def parse_date(s) -> dt.date | None:
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7, "七": 7}


def resolve_when(expr, said: dt.date) -> dt.date | None:
    """把原话里的"哪天"换成日期（按那句话是哪天说的算；模型自己数星期常数错，11-18 补看时"周六说的下周二"给成了周三）。
    认：今天 / 明天 / 后天 / 大后天、（这 / 本 / 下 / 下下）周X、X月X日 / 号、X日 / 号；认不出返回 None（用模型给的 date）。"""
    s = re.sub(r"\s+", "", str(expr or ""))
    if not s:
        return None
    for word, k in (("大后天", 3), ("后天", 2), ("明天", 1), ("明晚", 1), ("明早", 1), ("今天", 0), ("今晚", 0)):
        if word in s:
            return said + dt.timedelta(days=k)
    m = re.search(r"(下下|下个?|这|本)?(?:周|星期|礼拜)([一二三四五六日天七])", s)
    if m:
        target = _CN_NUM[m.group(2)] - 1
        monday = said - dt.timedelta(days=said.weekday())
        pre = m.group(1) or ""
        if pre.startswith("下下"):
            return monday + dt.timedelta(days=14 + target)
        if pre.startswith("下"):
            return monday + dt.timedelta(days=7 + target)
        d = monday + dt.timedelta(days=target)
        if not pre and d < said:  # 光说"周二"、已经过了 → 指下一个周二
            d += dt.timedelta(days=7)
        return d
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", s)
    if m:
        try:
            d = dt.date(said.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        return d.replace(year=d.year + 1) if (said - d).days > 180 else d
    m = re.fullmatch(r"(?:\D*?)(\d{1,2})[日号]\D*", s)
    if m:
        try:
            d = said.replace(day=int(m.group(1)))
        except ValueError:
            return None
        if d < said - dt.timedelta(days=3):  # 已经过去好几天的"X号" → 下个月
            nm = (said.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
            try:
                d = nm.replace(day=int(m.group(1)))
            except ValueError:
                return None
        return d
    return None


def today_text(d: dt.date) -> str:
    return f"{d.isoformat()}（周{WEEKDAYS[d.weekday()]}）"


def day_tag(d: dt.date) -> str:
    return f"{d.month:02d}-{d.day:02d} 周{WEEKDAYS[d.weekday()]}"


def span_text(first: dt.date, last: dt.date) -> str:
    """提示词开头：这段聊天是哪天的。补看旧记录时一段可能跨好几天，每句前面另有日期。"""
    if first == last:
        return f"今天是 {today_text(last)}。"
    return f"这段聊天是 {today_text(first)} 到 {today_text(last)} 的，每句前面标了那天的日期。"


def calendar_text(d: dt.date, back: int = 3, ahead: int = 13, weeks: bool = True) -> str:
    """从 d 前几天到后两周的日期和星期几，免得模型自己数错。weeks：标上"这周 / 下周"和"明天"（周一开头，按 d 算；
    一段聊天跨好几天时不标，不然和那句话说的那天对不上）。"""
    monday = d - dt.timedelta(days=d.weekday())
    rows = []
    for k in range(-back, ahead + 1):
        x = d + dt.timedelta(days=k)
        if weeks:
            tag = {-1: "上周", 0: "这周", 1: "下周", 2: "下下周"}.get((x - monday).days // 7, "")
            rel = {0: "今天", 1: "明天", 2: "后天", -1: "昨天", -2: "前天"}.get(k, "")
        else:
            tag = rel = ""
        rows.append(f"{x.isoformat()} {tag}周{WEEKDAYS[x.weekday()]}" if not tag else f"{x.isoformat()} {tag}{WEEKDAYS[x.weekday()]}")
        if rel:
            rows[-1] += f"（{rel}）"
    return "；".join(rows)


def make_id(chat: str, qq: str, ts: float, what: str) -> str:
    return hashlib.sha1(f"{chat}|{qq}|{ts}|{what}".encode()).hexdigest()[:10]


# ------------------------------------------------------------------ 先后
def priority(loop: dict, now: float, today: dt.date) -> float:
    imp = clamp(float(loop.get("imp", 5) or 5), 1, 10)
    a = clamp(float(loop.get("care", 1) or 0) / 3.0, 0, 1)
    t = max(0.0, now - float(loop.get("last_seen") or loop.get("created") or now)) / 86400.0
    score = imp * (1 + a) * math.exp(-t / (14 + 30 * a))
    d = parse_date(loop.get("date"))
    if d:
        score += 2.0 / (1 + abs((d - today).days))
    return score


def days_off(loop: dict, today: dt.date) -> int | None:
    d = parse_date(loop.get("date"))
    return None if d is None else (d - today).days


def when_text(loop: dict, today: dt.date) -> str:
    d = parse_date(loop.get("date"))
    if d is None:
        return ""
    n = (d - today).days
    rel = {0: "就是今天", 1: "明天", 2: "后天", -1: "昨天", -2: "前天"}.get(
        n, f"还有{n}天" if n > 0 else f"已经过去{-n}天")
    return f"{d.month}月{d.day}日周{WEEKDAYS[d.weekday()]}，{rel}"


def tidy(loops: list[dict], now: float, today: dt.date, stale_days: int = 7, floor: float = 0.5,
         undated_days: float = 14) -> int:
    """日子过了 stale_days 天还没下文、没日子又 undated_days 天没再提（或分数低于 floor）的，算过去了。返回这次收起了几件。"""
    n = 0
    for lp in loops:
        if lp.get("status", "open") != "open":
            continue
        off = days_off(lp, today)
        quiet = (now - float(lp.get("last_seen") or lp.get("created") or now)) / 86400.0
        if (off is not None and off < -stale_days) or (off is None and (quiet > undated_days or priority(lp, now, today) < floor)):
            lp["status"] = "stale"
            lp["closed"] = now
            n += 1
    return n


# ------------------------------------------------------------------ 记下 / 更新
def known_text(loops: list[dict], today: dt.date, who=lambda lp: lp.get("name", "")) -> str:
    rows = []
    for lp in loops:
        w = when_text(lp, today)
        rows.append(f"{lp['id'][:6]}: {who(lp)} - {lp['what']}" + (f" - {w}" if w else ""))
    return "\n".join(rows) or "（无）"


def apply(loops: list[dict], data: dict, batch: list[dict], chat: str, now: float, day_of=None) -> tuple[int, int]:
    """把模型的判断写进 loops（原地改）。batch 是这段【新消息】（每行有 u/n/ts）。返回 (新增, 更新)。
    day_of：时间戳 → 那天的日期（北京时间）；原话里的"哪天"按那句话说的那天换成日期，认不出才用模型给的 date。"""
    day_of = day_of or (lambda ts: dt.date.fromtimestamp(ts))
    added = changed = 0
    for u in data.get("update") or []:
        if not isinstance(u, dict):
            continue
        key = str(u.get("id", "")).strip()
        hit = [lp for lp in loops if key and lp["id"].startswith(key) and lp.get("status", "open") == "open"]
        if len(hit) != 1:
            continue
        lp = hit[0]
        st = str(u.get("status", "open")).strip()
        nd = resolve_when(u.get("when"), day_of(float(batch[-1].get("ts") or now) if batch else now)) or parse_date(u.get("date"))
        if nd:
            lp["date"] = nd.isoformat()
        if st in ("done", "drop"):
            lp["status"] = st
            lp["closed"] = now
            lp["result"] = str(u.get("result", "") or "").strip()[:40]
        lp["last_seen"] = now
        lp.setdefault("history", []).append({"t": now, "status": st, "result": str(u.get("result", "") or "")[:40]})
        changed += 1
    for k in data.get("new") or []:
        if not isinstance(k, dict):
            continue
        try:
            i = int(k.get("i") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= i <= len(batch):
            continue
        r = batch[i - 1]
        qq = str(r.get("u", ""))
        what = str(k.get("what", "") or "").strip()[:60]
        if qq in ("", "self") or not what:
            continue
        if any(lp["qq"] == qq and lp.get("status", "open") == "open" and _same(lp["what"], what) for lp in loops):
            continue
        ts = float(r.get("ts") or now)
        d = resolve_when(k.get("when"), day_of(ts)) or parse_date(k.get("date"))
        try:
            imp = int(clamp(int(k.get("imp", 5)), 1, 10))
        except (TypeError, ValueError):
            imp = 5
        try:
            care = int(clamp(int(k.get("care", 1)), 0, 3))
        except (TypeError, ValueError):
            care = 1
        kw = [str(x).strip()[:12] for x in (k.get("kw") or []) if str(x).strip()][:4]
        loops.append({
            "id": make_id(chat, qq, ts, what), "qq": qq, "name": str(r.get("n", "")), "chat": chat, "what": what,
            "quote": str(r.get("x", ""))[:60], "date": d.isoformat() if d else "", "when": str(k.get("when", "") or "")[:20], "imp": imp, "care": care, "kw": kw,
            "created": ts, "last_seen": ts, "status": "open", "shown": 0, "last_shown": None,
        })
        added += 1
    return added, changed


def _same(a: str, b: str) -> bool:
    def grams(s):
        s = re.sub(r"\W", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)}
    ga, gb = grams(a), grams(b)
    return bool(ga and gb) and len(ga & gb) / min(len(ga), len(gb)) >= 0.5


# ------------------------------------------------------------------ 给她看哪几件
def visible(loop: dict, sender: str, chat: str) -> bool:
    """私聊给这个人的全部；群里只给在这个群里说的。"""
    if loop.get("status", "open") != "open" or loop.get("removed") or loop["qq"] != sender:
        return False
    return chat.startswith("p") or loop["chat"] == chat


def touches(loop: dict, msg_kw: set[str], loop_kw: set[str]) -> bool:
    words = {w.lower() for w in loop.get("kw") or []} | loop_kw
    return bool(words & msg_kw)


def pick(loops: list[dict], sender: str, chat: str, msg_kw: set[str], kw_of, now: float, today: dt.date, *,
         max_n: int = 3, near_days: int = 2, high: float = 15.0, cooldown_h: float = 6.0, min_imp_near: int = 5) -> list[dict]:
    """这一轮给她看的几件：碰到词的先给；别的要日子近或很要紧、而且不在冷却里。按先后排，最多 max_n 件。"""
    out = []
    for lp in loops:
        if not visible(lp, sender, chat):
            continue
        p = priority(lp, now, today)
        if touches(lp, msg_kw, kw_of(lp)):
            out.append((0, -p, lp))
            continue
        off = days_off(lp, today)
        near = off is not None and abs(off) <= near_days and int(lp.get("imp", 5) or 5) >= min_imp_near  # 小事只在聊到时给
        cooled = not lp.get("last_shown") or now - float(lp["last_shown"]) >= cooldown_h * 3600
        if cooled and (near or p >= high):
            out.append((1, -p, lp))
    out.sort(key=lambda x: (x[0], x[1]))
    return [lp for _, _, lp in out[:max_n]]


def note_lines(items: list[dict], today: dt.date, tz) -> list[str]:
    lines = []
    for lp in items:
        d = dt.datetime.fromtimestamp(float(lp["created"]), tz)
        w = when_text(lp, today)
        lines.append(f"- {d.month}月{d.day}日说的：{lp['what']}" + (f"（{w}）" if w else ""))
    return lines
