"""人物印象（2026-11-19 兄长：“做人物印象”；AGENT.md 第十节）。

memorix 的人物画像只是“最近几条关系”的流水账（李四那份 6 条：问是否 24h 运行、测了 Plus……），可信度全是 1.00，
玩笑、起哄的话也照记。这里每晚给最近常说话的人各综合一份印象：是谁、最近在忙的、喜好、说话习惯、平时找她聊什么；
玩笑 / 反话 / 只说过一次的写进“拿不准”或不写。聊天时把 memorix 那段【人物画像-内部参考】里有印象的人换成印象。

只写这个人本身（身份、在做的事、喜好、习惯、常聊的话题），不写感情和关系的亲疏（好感另有 kaju_heart），
不写健康、住址、联系方式这类私事。纯逻辑，模型调用和存盘在 mind.py。
"""

from __future__ import annotations

import json
import re

FIELDS = ("是谁", "最近在忙", "喜好", "说话习惯", "常找她聊", "拿不准")
# 不写进印象的：感情、亲疏（kaju_heart 管），私事
OFF = re.compile(r"爱|恋|暧昧|表白|亲密|亲昵|撒娇|黏|依恋|好感|喜欢佳树|想佳树|吃醋|住址|地址|电话|手机号|身份证|病|医院|药")

SYSTEM = "你在帮聊天角色“佳树”整理她对身边一个人的印象：从这个人说过的话和记下的事里，综合出稳定、靠得住的几条。只输出 JSON。"

PROMPT = """这个人：{who}
【TA 最近说过的话】（日期 时间 内容；可能有玩笑、反话、起哄）
{lines}

【记下的关于 TA 的事】（自动抽的，可能把玩笑当了真）
{facts}

【上次的印象】（没有就是第一次写）
{old}

综合成一份印象，每项 0～3 条短话（每条二十字以内），写这个人本身：
- 是谁：身份、在做什么（学生 / 工作 / 在哪读书这类大概的，不写住址联系方式）
- 最近在忙：最近一两周反复在做、在聊的事
- 喜好：TA 明显喜欢 / 讨厌的东西（游戏、作品、吃的、话题）
- 说话习惯：TA 说话的样子（爱开玩笑、爱发表情、说话很冲、常用的叫法）
- 常找她聊：TA 平时找佳树聊或让她做的是哪类事
- 拿不准：听起来像玩笑、反话、只说过一次、前后对不上的说法
规矩：
- 只写反复出现或说得很明白的；玩笑、起哄、反话（“学习不好不给饭吃”“入党”这种）不当真，放“拿不准”或不写。
- 上次的印象里和这次材料对不上的就改掉；没有新材料说明它错了的照留。
- 不写感情和关系亲疏（谁喜欢谁、对她好不好），不写健康、住址、联系方式这些私事。
- 不编：材料里没有的项就写 []。
输出：{{"是谁": [...], "最近在忙": [...], "喜好": [...], "说话习惯": [...], "常找她聊": [...], "拿不准": [...]}}"""

HEAD = "【身边人的印象】下面是你对这几个人的大致印象（睡前整理的，可能有点过时；跟眼前对话冲突时以对话为准，别逐字说出来）："
PROFILE_HEAD = "【人物画像-内部参考】"


def parse(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    clean = {}
    for k in FIELDS:
        items = d.get(k) or []
        if isinstance(items, str):
            items = [items]
        clean[k] = [" ".join(str(x).split())[:30] for x in items if str(x).strip() and not OFF.search(str(x))][:3]
    return clean if any(clean[k] for k in FIELDS if k != "拿不准") else None


def text(name: str, imp: dict) -> str:
    parts = [f"{k}：{'；'.join(imp[k])}" for k in FIELDS if imp.get(k)]
    return f"- {name}：" + "。".join(parts)


def old_text(imp: dict | None) -> str:
    if not imp:
        return "（没有）"
    return "\n".join(f"{k}：{'；'.join(imp.get(k) or []) or '无'}" for k in FIELDS)


_BLOCK = re.compile(r"【人物画像-内部参考】.*?使用时把它当作对当前人物的背景理解；若与当前对话冲突，以当前对话为准。", re.S)
_PERSON = re.compile(r"^- .*?（person_id: [^:：]+[:：]([^，,）)]+)", re.M)


def swap_profiles(blob: str, impressions: dict, names: dict) -> tuple[str, list[str]]:
    """memorix 那段【人物画像-内部参考】里，有印象的人换成印象；都没有就原样。返回 (新文字, 换了的 QQ)。
    impressions = {qq: {"imp": {...}}}，names = {qq: 显示名}。"""
    m = _BLOCK.search(blob or "")
    if not m:
        return blob, []
    block = m.group(0)
    ids = _PERSON.findall(block)
    have = [q for q in ids if q in impressions]
    if not have:
        return blob, []
    rest = []
    for chunk in re.split(r"\n(?=- .*?（person_id: )", block):
        mm = _PERSON.search(chunk)
        if mm and mm.group(1) not in impressions:
            rest.append(chunk.strip())
    new = HEAD + "\n" + "\n".join(text(names.get(q, q), impressions[q]["imp"]) for q in have)
    if rest:
        new += "\n\n" + PROFILE_HEAD + "\n" + "\n\n".join(rest)
    return blob[:m.start()] + new + blob[m.end():], have
