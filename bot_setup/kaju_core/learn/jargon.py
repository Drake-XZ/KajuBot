"""这个群的叫法和黑话（2026-11-19 兄长：“接着做”；照 MaiBot 的黑话学习；AGENT.md 第十节）。

每晚按群读前一天的群聊，挑出群里自己的叫法：外号（“哈鸡米”= Gemini、“大肥鱼”= DeepSeek）、缩写、谐音、圈内说法，
写成“叫法 → 意思”，每个群分开记。证据：有人解释过（L 编号，别人那行）→ 确定；没人解释、按上下文猜的 → 先记“猜的”，
在这个群里累计出现 confirm_uses 次以上才算确定。聊天时这句话里出现了这个群记着的叫法，就告诉大脑它的意思（猜的标“拿不准”）。

不收：粗话、性相关的词、骂人的话、群友的私事；大家都懂的普通词。文件随读随写（不在内存里久留），离线脚本和线上插件同时写也不会互相盖掉。
"""

from __future__ import annotations

import json
import os
import re

FILE = "jargon.json"
OFF = re.compile(r"几把|鸡巴|操|傻逼|sb|妈的|日你|色色|涩|性|裸|黄|约炮|骚|滚")
# 说不出到底指什么的（“可能指某个游戏”“某种设备”）：不记（11-19 首轮 17 个里一半是这种）
VAGUE = re.compile(r"某|^(可能|大概|似乎|疑似)?(是|指)?(一种|一个)|不明|不清楚|未知")

SYSTEM = "你在帮 QQ 群里的聊天角色“佳树”学这个群自己的叫法和黑话。只输出 JSON。"
PROMPT = """下面是一个 QQ 群一天的聊天（每行前面有编号，L 开头；“佳树”是她自己）。
挑出这个群自己的叫法：外号（比如把某个 AI 模型、游戏、人叫成别的名字）、缩写、谐音、群里自己的说法、圈子里的黑话。
已经记着的（意思一样就别重复写，意思有新的补充可以写同一个叫法）：
{known}

每条写：{{"叫法": "原样写", "别的写法": [...], "意思": "指的是什么（二十字以内）", "证据": "解释了它意思的那一行编号（别人说的 L 行），没人解释写空",
"猜的": true 或 false（没人解释、是按上下文猜的就 true）}}
不收：粗话、性相关的词、骂人的话、群友的私事（住哪、身体、感情）；大家都懂的普通词和正式名称本身（“Gemini”“GTA6”不算，“哈鸡米”“给他爱6”才算）；
产品的正式型号、版本号（“opus 5.5”“6.1 terra”这种）不算。说不出它到底指什么的（只能写“某个游戏”“某种设备”）就别写。
输出 {{"jargon": [...]}}，没有就 {{"jargon": []}}。最多 8 条。

{lines}"""

HEAD = "【这个群的叫法】下面是这句话里出现的、这个群自己的叫法（你以前从群聊里学到的）："


def load(folder: str) -> dict:
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        d = {}
    d.setdefault("groups", {})
    d.setdefault("reflected", [])
    return d


def save(folder: str, d: dict) -> None:
    d["reflected"] = d["reflected"][-60:]
    path = os.path.join(folder, FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def parse(out: str) -> list[dict]:
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return []
    return [x for x in (d.get("jargon") if isinstance(d, dict) else None) or [] if isinstance(x, dict)]


def names(e: dict) -> list[str]:
    return [e["term"], *e.get("aliases", [])]


def count_uses(term_names: list[str], texts: list[str]) -> int:
    low = [t.lower() for t in texts]
    return sum(1 for t in low if any(n.lower() in t for n in term_names if len(n) >= 2))


def known_block(d: dict, group: str) -> str:
    rows = d["groups"].get(group, [])
    return "\n".join(f"- {e['term']}：{e['meaning']}" for e in rows if e.get("status") != "removed") or "（还没有）"


def add(d: dict, group: str, items: list[dict], lines: dict[str, dict], texts: list[str], now: float, day: str,
        confirm_uses: int = 3) -> dict:
    """记进 d["groups"][group]。lines = {"L3": {"self": bool, "text": str}}（查证据）；texts = 这天这个群每行的话（数出现次数）。"""
    rows = d["groups"].setdefault(group, [])
    st = {"new": 0, "more": 0, "sure": 0, "dropped": 0}
    for it in items:
        term = " ".join(str(it.get("叫法") or "").split())[:16]
        meaning = " ".join(str(it.get("意思") or "").split())[:40]
        aliases = [" ".join(str(a).split())[:16] for a in (it.get("别的写法") or []) if str(a).strip()][:4]
        if len(term) < 2 or not meaning or OFF.search(term + meaning + "".join(aliases)) or VAGUE.search(meaning):
            st["dropped"] += 1
            continue
        ev = lines.get(str(it.get("证据") or "").strip().upper())
        explained = ev is not None and not ev.get("self")
        uses = count_uses([term, *aliases], texts)
        if uses == 0:
            st["dropped"] += 1  # 这天群里根本没出现：多半是模型编的
            continue
        e = next((x for x in rows if x.get("status") != "removed" and term.lower() in [n.lower() for n in names(x)]), None)
        if e is None:
            e = {"term": term, "aliases": aliases, "meaning": meaning, "sure": False, "uses": 0, "t0": now, "evidence": []}
            rows.append(e)
            st["new"] += 1
        else:
            st["more"] += 1
            e["aliases"] = list(dict.fromkeys(e.get("aliases", []) + aliases))[:6]
            if explained or not e.get("sure"):
                e["meaning"] = meaning
        e["uses"] = int(e.get("uses", 0)) + uses
        e["t"] = now
        if explained:
            e["evidence"] = (e.get("evidence", []) + [{"day": day, "line": str(ev.get("text", ""))[:100]}])[-3:]
        was = e.get("sure")
        e["sure"] = bool(was or explained or e["uses"] >= confirm_uses)
        e["status"] = "active"
        st["sure"] += int(e["sure"] and not was)
    d["groups"][group] = rows[-200:]
    return st


def lookup(d: dict, group: str, text: str, k: int = 4, guesses: bool = False) -> list[dict]:
    """这句话里出现了这个群记着的哪些叫法（长的先认，最多 k 个）；guesses = False 时只认确定了的。"""
    low = (text or "").lower()
    out = []
    rows = [x for x in d["groups"].get(group, []) if x.get("status") == "active" and (guesses or x.get("sure"))]
    for e in sorted(rows, key=lambda x: -len(x["term"])):
        if any(len(n) >= 2 and n.lower() in low for n in names(e)):
            out.append(e)
        if len(out) >= k:
            break
    return out


def note(rows: list[dict]) -> str:
    return HEAD + "\n" + "\n".join(f"- {e['term']}：{e['meaning']}" + ("" if e.get("sure") else "（猜的，拿不准）") for e in rows)


def report(d: dict, group: str = "") -> str:
    lines = []
    for g, rows in d["groups"].items():
        if group and g != group:
            continue
        act = [e for e in rows if e.get("status") == "active"]
        if not act:
            continue
        lines.append(f"群 {g}（{len(act)} 个）：")
        lines += [f"· {e['term']}{('（' + '、'.join(e['aliases']) + '）') if e.get('aliases') else ''}：{e['meaning']}"
                  f"〔{'确定' if e.get('sure') else '猜的'}，出现 {e.get('uses', 0)} 次〕" for e in act]
    return "\n".join(lines) or "还没学到哪个群的叫法。" + "\n删一个：/佳树学到的 删黑话 叫法"
