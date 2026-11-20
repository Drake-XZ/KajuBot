"""表情包单独挑（2026-11-18 兄长：“填好表，然后做第二步”；AGENT.md 第十节）。

照 MaiBot 的 emoji 那一格：大脑（主模型）不再看那一大段表情包说明、也不在指导后面写 &&标记&&；
她的话写好以后，由“表情包”那一格的模型（kaju_data\\accounts\\model_slots.json 的 emoji）看着这句话和她的心情，决定配不配、配哪一类。
挑中了就把分类键放进 meme_manager 认的 event extra "found_emotions"，发送那一步照旧由 meme_manager 做（它自己的概率骰子照旧）。
开关 rewrite.emoji = "separate"（默认 "brain" = 照旧由大脑写标记），只在大脑模式下用。
"""

from __future__ import annotations

import json
import re

START = "<!-- meme_manager_prompt:start -->"
END = "<!-- meme_manager_prompt:end -->"
_BLOCK = re.compile(r"\n*" + re.escape(START) + r"[\s\S]*?" + re.escape(END))
_CAT = re.compile(r"^\s*([^\s\-][^\n]{0,30}?)\s+-\s+(.+?)\s*$")

SYSTEM = """你替温水佳树（初三女生，在 QQ 上和兄长大人、他的朋友们聊天）挑表情包：看她这一句话和她此刻的心情，决定这句要不要配一张表情包、配哪一类。
- 像真人在 QQ 上聊天：大多数句子不配；情绪很明显（开心、得意、委屈、害羞、生气、惊讶……），或者一张图比字更能表达时才配。
- 按她想表达的态度挑：是安慰对方还是说自己、是在开玩笑还是认真，别看到“难过”就机械选难过。
- 分类键只能从下面的列表里原样挑一个。
只输出 JSON：{"配": true, "分类": "分类键"}；不配时 {"配": false}。"""


def cut_block(system_prompt: str) -> tuple[str, str]:
    """(去掉表情包说明之后的系统提示, 那段说明)；没有就 (原样, "")。"""
    s = system_prompt or ""
    m = _BLOCK.search(s)
    if not m:
        return s, ""
    return s[:m.start()] + s[m.end():], m.group(0).strip()


def categories(block: str) -> dict[str, str]:
    """说明里“[可用分类：分类键 - 用途]”下面那些“键 - 用途”行。"""
    out: dict[str, str] = {}
    on = False
    for line in (block or "").splitlines():
        if line.startswith("[可用分类"):
            on = True
            continue
        if on and line.startswith("[") and not line.startswith("[可用分类"):
            break
        if on:
            m = _CAT.match(line)
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
    return out


def label(cats: dict[str, str], key: str) -> str:
    """记进聊天记录的说法：用途的头一小句（“得意、炫耀时”这种），没有就用分类键。"""
    use = re.split(r"[，。；;,.（(]", str(cats.get(key) or ""))[0].strip()
    return (use[:16] or key).strip()


def own_note(block: str) -> str:
    """“[亲手添加的表情]”那一段（几个分类都说得通时优先这些）。"""
    m = re.search(r"\[亲手添加的表情\]\n([\s\S]*?)(?:\n\n|\n\[)", block or "")
    return m.group(1).strip() if m else ""


def prompt(cats: dict[str, str], text: str, ctx: list[str], mood: str, own: str = "") -> tuple[str, str]:
    lst = "\n".join(f"{k} - {v}" for k, v in cats.items())
    system = SYSTEM + "\n\n可用分类（分类键 - 用途）：\n" + lst + (f"\n\n{own}" if own else "")
    chat = "\n".join((ctx or [])[-4:]) or "（没有前文）"
    user = f"最近的聊天：\n{chat}\n\n她这一句：\n{text}\n\n她此刻的心情：{mood or '平常'}\n\n只输出 JSON。"
    return system, user


def parse(out: str, cats: dict[str, str]) -> str:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return ""
    if not isinstance(v, dict) or not v.get("配"):
        return ""
    key = str(v.get("分类") or "").strip().strip("&")
    return key if key in cats else ""
