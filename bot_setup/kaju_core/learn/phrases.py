"""例句库从真实聊天里长（2026-11-20 晚兄长：“我现在想加这个了”；照 MaiBot 的“表达方式学习”；AGENT.md 第十节）。

每晚读前一天她说过的话（每句带前 10 行、后 8 行），交给模型挑“效果好”的：后面有人接着她这句聊下去（回她、笑、认同），
话本身像真人在 QQ 上随口说的、换个场合也能借鉴说法。挑中的记成 {situation（她接的那句，别人说的）, line（她说的）}，
写进 kaju_data\\self\\kaju_style\\replyer_learned.json，回复器（kaju_core\\voice\\replyer.py）和原来的例子库一起挑，
一轮最多放 rewrite.replyer_live_max 句。只当回复器的参考，不改她的话。

不收：亲昵、撒娇、恋爱暧昧；说自己是不是 AI；编她自己的经历；被纠正、对方没懂、她后来改口道歉的；复述对方的话；长篇说明。
跟库里已有的句子太像的不收（省得越学越单调）；库满了挤掉最早学的。
"""

from __future__ import annotations

import json
import os
import re

FILE = "replyer_learned.json"  # 在 kaju_data\self\kaju_style 下（回复器的例子都在那儿）
MEME = re.compile(r"&&[^&\n]{1,40}&&")
NOISE = re.compile(r"^\[(图片|表情|视频|语音|文件[^\]]*|动画表情|戳一戳)[^\]]*\]$")
# 模型漏掉时的兜底：亲昵撒娇的说法不进库（只管进不进参考库，不碰她说出去的话）
CLINGY = re.compile(r"抱抱|亲亲|么么|贴贴|想兄长|想你|最喜欢兄长|喜欢兄长|黏|撒娇|^兄长大人[~～]")
# 兄长不喜欢的说法不进参考库（11-14 笑用 wwww 不用哈哈哈；11-20 不道歉过头）
NOT_HER = re.compile(r"哈哈|不好意思|对不起|抱歉")
AI_TALK = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|机器人|模型|训练|算法|提示词", re.I)

SYSTEM = "你在帮 QQ 上的聊天角色“佳树”（初三女生）从她自己说过的话里挑说得好的，给以后写回复当参考。只输出 JSON。"
PROMPT = """下面是她昨天说过的几句话，每句带着前后的聊天（每行前面有编号，L 开头；“佳树”是她自己，【她这句】标着要看的那句）。
挑出“说得好、效果也好”的，以后在类似场合可以借鉴说法。要同时满足：
1. 效果好：后面有人接着她这句聊下去（回她、被逗笑、认同、顺着往下说）。没人理、被纠正、对方说没懂、她自己后来改口道歉的，不挑。
2. 话本身好：像真人在 QQ 上随口说的，口气自然、不啰嗦；接住了对方，不是复述对方的话、不是解说员式的总结、不是长篇说明。
3. 说法换个场合也能借鉴（不是只靠某件具体的事才成立的一句事实）。
特别留意有她自己味道的：口气和小反应很鲜活的（被打趣时结巴、嘴硬、害羞，比如“才、才没有呢！”；语气词、标点用得有意思的）。
这种比平平的、只是正确的回答（“确实很抽象呀”）更值得挑。被人打趣时嘴硬害羞不算恋爱暧昧。
不挑：亲昵、撒娇、讨好、恋爱暧昧的话（想兄长、要抱抱、“兄长大人~”这种）；说自己是不是 AI、机器人的，或从 AI、模型训练的角度说话的；
她编的自己的经历（说得像自己用过、试过、去过）；懂得超过初三学生的（技术、AI 模型这些说得头头是道，或像“某某模型确实容易这样”那样说得像很熟）；说错了事实的；
道歉、认错的话（“不好意思”“对不起”）；用“哈哈哈”笑的（她笑用“wwww”）。
宁缺毋滥，大多数天只有一两句、甚至一句都没有。
她一条消息常有好几行（用 “ / ” 隔开）。只有其中几行好、别的行不该挑（比如第一行接得好、后面几行在撒娇或啰嗦），就只挑好的那几行。

每条写：{{"她说": "她那句的 L 编号", "接的": "她这句在回的那一行的 L 编号（别人说的，在她这句前面）",
"只要": [只挑其中几行时写第几行，从 1 数；整条都好就不写], "好在哪": "十个字以内"}}
输出 {{"picks": [...]}}，没有就 {{"picks": []}}。

{eps}"""


def load(folder: str) -> dict:
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("items", [])
    d.setdefault("reflected", [])
    d.setdefault("next_id", 1 + max([int(x.get("id", 0)) for x in d["items"]] or [0]))
    return d


def save(folder: str, d: dict) -> None:
    d["reflected"] = d["reflected"][-60:]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def active(d: dict) -> list[dict]:
    return [x for x in d["items"] if x.get("status", "active") == "active"]


def as_line(text: str) -> str:
    """她一条（可能好几行）→ 例子库里的一行：去掉表情包标记和纯图片行，多行用 “ / ” 连。"""
    parts = [MEME.sub("", p).strip() for p in str(text or "").split("\n")]
    return " / ".join(p for p in parts if p and not NOISE.match(p))


def situation_of(text: str) -> str:
    return re.sub(r"^\[发言人：[^\]]*\]\s*", "", str(text or "")).replace("\n", " / ").strip()[:120]


def parse(out: str) -> list[dict]:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return []
    return [x for x in (d.get("picks") if isinstance(d, dict) else None) or [] if isinstance(x, dict)]


def check(picks: list[dict], lines: dict[str, dict]) -> list[dict]:
    """模型挑的 → 能用的 {situation, line, why, key}；编号对不上、不是她说的、接的不是别人前面那句、太短太长、亲昵/AI 话的不要。
    lines: {L编号: {"self", "text"（原文）, "chat", "i"（当天行序）}}"""
    out, seen = [], set()
    for p in picks:
        me, prev = lines.get(str(p.get("她说", "")).strip()), lines.get(str(p.get("接的", "")).strip())
        if not me or not prev or not me["self"] or prev["self"] or prev["chat"] != me["chat"] or prev["i"] >= me["i"]:
            continue
        line, sit = as_line(me["text"]), situation_of(prev["text"])
        only = p.get("只要")
        if isinstance(only, (int, str)):
            only = [only]
        if isinstance(only, list) and only:  # 只要其中几行（11-20 晚：“才、才没有呢！”后面跟着一行撒娇，整条就被筛掉了）
            parts = line.split(" / ")
            try:
                keep = sorted({int(k) for k in only})
            except (TypeError, ValueError):
                continue
            if not keep or keep[0] < 1 or keep[-1] > len(parts):
                continue
            line = " / ".join(parts[k - 1] for k in keep)
        if not (4 <= len(line) <= 90) or len(sit) < 2 or NOISE.match(sit) or line in seen:
            continue
        if CLINGY.search(line) or AI_TALK.search(line) or NOT_HER.search(line):
            continue
        seen.add(line)
        out.append({"situation": sit, "line": line, "why": str(p.get("好在哪", ""))[:20], "chat": me["chat"]})
    return out


def _grams(s: str) -> set[str]:
    s = re.sub(r"[\W_]", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def overlap(a: str, b: str) -> float:
    """两句共有的两字片段占长的那句的多少（taste.bigram_overlap 除以短的那句，短句“什么意思？”会和什么都算像）。"""
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / max(len(ga), len(gb)) if ga and gb else 0.0


def too_close(line: str, others: list[str], limit: float = 0.6) -> bool:
    """太像：两字片段重合够多，或者一句整个包在另一句里（只挑其中一行时会和整条的旧句子重）。"""
    return any(overlap(line, o) >= limit or (len(line) >= 6 and len(o) >= 6 and (line in o or o in line)) for o in others)


def add(d: dict, items: list[dict], vecs: list, base_lines: list[str], now: float, day: str, max_total: int = 200) -> dict:
    st = {"new": 0, "same": 0}
    have = [x["line"] for x in active(d)] + list(base_lines)
    for it, v in zip(items, vecs):
        if not v or too_close(it["line"], have):
            st["same"] += 1
            continue
        d["items"].append({"id": d["next_id"], "situation": it["situation"], "line": it["line"], "src": "live",
                           "vec": v, "why": it.get("why", ""), "chat": it.get("chat", ""), "day": day, "t": now,
                           "status": "active"})
        d["next_id"] += 1
        have.append(it["line"])
        st["new"] += 1
    act = sorted(active(d), key=lambda x: x.get("t", 0))
    for x in act[:max(0, len(act) - max_total)]:
        x["status"] = "pushed"  # 库满了挤掉最早学的
    return st


def report(d: dict, n: int = 30) -> str:
    act = active(d)
    if not act:
        return "还没从聊天里学到例句。"
    rows = sorted(act, key=lambda x: -x.get("t", 0))[:n]
    return (f"从聊天里学到的例句 {len(act)} 句（最近 {len(rows)} 句；删：/佳树学到的 删例句 编号）：\n"
            + "\n".join(f"#{x['id']} {x.get('day', '')} 当对方说“{x['situation'][:40]}”，她说“{x['line'][:60]}”"
                        + (f"（{x['why']}）" if x.get("why") else "") for x in rows))
