"""给记忆打"分量"的提示词 + 解析，以及读 kaju_life 聊天记录的小工具（纯函数，离线可测）。"""

from __future__ import annotations

import datetime as dt
import json
import re

SCALE = (
    "3 = 语重心长、真心话、郑重的叮嘱/嘱托/期望、认真的道歉或感谢、诉说心事或难过的事、严肃的批评或争执、"
    "气氛凝重的时刻，或者明确要佳树记住的话\n"
    "2 = 以后要一直照着做的约定、规矩、称呼；关于对方本人的要紧事（身体、学业、工作、感情、家人、烦恼、重要的决定）\n"
    "1 = 一般信息：对方的爱好、日常近况、聊过的话题\n"
    "0 = 寒暄、玩笑、斗图、一次性的小事（帮忙推荐/查个东西、随口问问、等某人上线）、和谁都无关的闲聊"
)

KEEP_SYSTEM = (
    "你在帮 QQ 聊天角色\"佳树\"（初三女生，叫最亲的人\"兄长大人\"）挑出哪些话值得她长久记在心里。"
    "判断要看整体气氛：同样的话，开玩笑时说分量就轻，认真谈心时说分量就重。只输出 JSON。"
)

KEEP_PROMPT = """下面是一段聊天记录（[时:分] 名字(QQ号): 内容；"佳树"是她自己说的；名字后面的括号是佳树对这个人的称呼）。【之前】只是上下文，只评【新消息】里别人说的话。
【之前】
{before}
【新消息】
{lines}

【她已经记着的铭记】（编号: 谁 - 记着的话）
{known}

按分量给【新消息】里别人说的话打分：
{scale}

只挑分量 2 和 3 的，输出 JSON：
{{"mood": "这段聊天整体的气氛，几个字", "level": 0到3（整段的分量）,
  "keep": [{{"i": 编号, "g": 2或3, "memory": "一句话写清楚谁对佳树说了什么、希望她怎样（第三人称，用佳树对这个人的称呼，40字以内）", "quote": "最关键的一句原话（可截取，40字以内）"}}]}}
一句都没有就输出 {{"mood": "…", "level": 0, "keep": []}}。好几句说的是同一件事就合成一条（i 写最关键那句的编号）。

另外看【她已经记着的铭记】（2026-11-18 作废线，照 dsh-soul）：
- 新的一条改掉了某条旧的（换了称呼、改了约定或规矩、说法变了），在那条 keep 里加 "replaces": "旧的编号"；
- 【新消息】让某条旧的不再成立、也没有新的要记（说以后不用了、取消了；或者那条记的是一时的事——要考试、这两天很累、心情不好——现在已经过去了），
  在最外层加 "retire": [{{"id": "旧的编号", "why": "为什么不再成立（20字以内）"}}]。
- 只看【新消息】里真的说到的；没说到的旧铭记不要动。没有就不写这两项。"""

PARA_SYSTEM = "你在帮 QQ 聊天角色\"佳树\"整理长期记忆，决定每条记录该记多久。只输出 JSON。"

PARA_PROMPT = """下面是佳树长期记忆里的几条记录，每条附上当时的部分原始聊天（如果找得到）。给每条记录打"分量"：
{scale}
一条记录里只要有一部分分量重，就按重的算。判断时看当时的气氛，不只看字面。
以"【佳树心里】"开头的是佳树自己记下的当时的感受和想法：心里起了大波澜（很感动、很难过、害怕、委屈得厉害）、
下了决心、想明白了一件关于自己或重要的人的事，算 2~3；有点小情绪、小心思算 1；没什么波澜算 0。

{items}

输出 JSON：{{"scores": [{{"id": 1, "g": 0}}, ...]}}"""


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def clamp_g(v, default: int = 1) -> int:
    try:
        return max(0, min(3, int(v)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- kaju_life 聊天记录
def line_time(day: str, hhmm: str, day_start_hour: int, tz) -> float:
    """kaju_life 的日志按"生活日"分文件（day_start_hour 点之前算前一天），t 只有时:分。"""
    d = dt.date.fromisoformat(day)
    h, m = (int(x) for x in (hhmm or "00:00").split(":")[:2])
    if h < day_start_hour:
        d += dt.timedelta(days=1)
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=tz).timestamp()


def read_log_lines(path: str, start: int = 0) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({})
    except FileNotFoundError:
        pass
    return out


def fmt_line(r: dict, idx: int | None = None, labels: dict | None = None) -> str:
    """labels: QQ → 佳树对这个人的称呼（兄长大人本人、称呼簿里的）。"""
    qq = str(r.get("u", ""))
    if qq == "self":
        who = "佳树"
    else:
        call = (labels or {}).get(qq, "")
        who = f"{r.get('n') or '某人'}({qq})" + (f"（{call}）" if call and call != r.get("n") else "")
    text = str(r.get("x", "")).replace("\n", " / ")[:200]
    head = f"{idx}. " if idx is not None else ""
    return f"{head}[{r.get('t', '')}] {who}: {text}"


CUE = re.compile(
    r"记住|记得|别忘|答应我|认真|说真的|真心|心里话|肺腑|希望你|你要|你可以|不要再|别再|以后|一定|"
    r"对不起|抱歉|谢谢你|难过|伤心|难受|害怕|担心|压力|累了|哭|生气|失望|骂|吵架|分手|生病|住院|去世|"
    r"重要|保证|承诺|约定|规矩|叫我|称呼"
)


def is_candidate(r: dict, min_chars: int) -> bool:
    if r.get("u") in (None, "", "self"):
        return False
    text = str(r.get("x", ""))
    if text.startswith("[") and text.endswith("]") and len(text) < 12:  # [图片] [表情]
        return False
    return len(text) >= min_chars or bool(CUE.search(text))


def chat_of_source(source: str) -> str:
    """memorix 段落来源 → 聊天里的人/群号：chat_summary:222222222 / conversation:111111111:… / person_fact:111111111:…"""
    parts = str(source or "").split(":")
    return parts[1] if len(parts) > 1 else ""
