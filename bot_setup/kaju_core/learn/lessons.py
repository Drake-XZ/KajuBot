"""自己总结教训（2026-11-19 兄长：“会不会越聊越聪明” → “按这个做”；AGENT.md 第十节）。

每晚把她前一天说过的话（每句带前后几行聊天）和几样程序记录（说到做到插件记下的“答应了却没做”、知识本里被人纠正的说法）
交给模型复盘，找“这句之后有迹象说明她做得不好”的地方，写成“什么样的场合 → 下次怎么做”。
只管做事和聊天的本事（答没答对、做没做到、接没接住、场合对不对）；不管语气、用词、长短（那归回复器），也不学怎么表达亲近。

挡住乱学：证据必须是别人那行或程序记录（编号），不能是她自己那行；意思一样的并成一条；被人当面纠正 / 程序记录这种“强”证据
一次就生效，别的要碰到两次；同时生效的最多 max_active 条。用的时候挑和眼前最像的 2～3 条交给大脑（【以前的教训】）。
学会了：生效后给大脑看过 learned_after 次、这期间没再犯 → 退下（status = learned）；给看过还照样犯 → 标 revise，下次复盘时改写。
长期没碰到也没用上的（fade_days）淡掉。纯逻辑，离线可测；模型调用和存盘在 mind.py。
"""

from __future__ import annotations

import hashlib
import json
import re

from kaju_core.heart.taste import bigram_overlap

# 不归这里管的：语气、用词、长短（回复器的事），亲近的表达（不学）
OFF_TOPIC = re.compile(r"语气|口吻|用词|措辞|字数|长短|太长|太短|简短|啰嗦|撒娇|黏人|亲近|亲密|亲昵|暧昧|表白|恋爱|爱意|喜爱")

SYSTEM = "你在帮聊天角色“佳树”每晚复盘她前一天说过的话，找出值得记住的教训。只输出 JSON。"

PROMPT = """下面是她前一天说过的几句话，每句带着前后的聊天；每一行前面有编号（L 开头）。最后可能还有几条程序记录（R 开头）。
逐句看【之后】和程序记录，有没有迹象说明她那句做得不好：
- 有人纠正她、说她理解错了 / 认错人了 / 说的不对 / 没叫她
- 有人把同一件事又问了一遍、追问“你能不能…”“查了吗”（说明她上次没做到或没答到）
- 她答应了去做（查、看、发、记）却没有下文；程序记录里写着“答应了却没做”
- 她说的事实后来被人纠正；程序记录里写着“被纠正”
- 她插话以后有人明说她插错了、跑题了
只根据看得到的迹象判断，看不出来就别写；只是“可以说得更好”的不算。
只写做事和聊天的本事：答没答对、做没做到、接没接住、场合对不对。不写她的语气、用词、长短，不写怎么表达亲近。

已经记着的教训（编号 K 开头；新发现的和其中某条是同一个意思，就写 "同": "K编号"，别另写一条）：
{known}

每条写成：{{"场合": "什么样的时候（不带人名、能套到别的时候，二十字以内）", "教训": "下次怎么做（一句话，是做法不是台词，三十字以内）",
"证据": "说明问题的那一行的编号（别人说的 L 行，或 R 行；不能是她自己那行）", "强": true 或 false（有人当面纠正 / 程序记录写明了就是 true）,
"同": "K编号或空", "哪里": "群聊 / 私聊 / 都"}}
另外看看这些聊天里，别人或程序记录有没有让她弄清楚了一件关于她自己的“能力和经历”的事实（11-19 加）：
她能做什么、做不到什么、做过什么、有什么（账号、工具、能看能发的东西）。比如别人指出“你已经发过很多张表情包了”，
就说明“佳树能从表情包库里按分类发表情包”。只收能力和经历；不收性格、感情、关系、长相；她自己嘴上说的不算，要别人那行或程序记录证明。
每条写成：{{"事实": "佳树……（一句话，三十字以内）", "类": "能做 / 做不到 / 做过 / 有的", "证据": "L 或 R 编号"}}

输出 {{"lessons": [...], "关于自己": [...]}}，没有就写 []。教训最多 6 条，关于自己最多 3 条。

{eps}"""

REVISE_SYSTEM = "你在帮聊天角色“佳树”改写一条她自己总结的教训：她照着这条做了还是犯了同样的错，说明这条写得不对或不够具体。只输出 JSON。"
REVISE_PROMPT = """原来的教训：场合「{situation}」→「{lesson}」
这几次犯错的证据：
{evidence}
改写成更准的一条（同样只管做事和聊天的本事，不写语气、用词、长短，不写怎么表达亲近）：
{{"场合": "二十字以内", "教训": "三十字以内，是做法不是台词"}}"""

HEAD = ("【以前的教训】下面是你以前自己复盘出来的教训（做事的办法，不是要说的话）。跟眼前这件事有关就照着想、照着做；"
        "无关就不用管，也别提起它。")


def new_store() -> dict:
    return {"lessons": [], "reflected": [], "next": 1}


def lesson_text(x: dict) -> str:
    return f"{x.get('situation', '')}：{x.get('lesson', '')}"


def vec_key(x: dict) -> str:
    return hashlib.sha1(lesson_text(x).encode()).hexdigest()[:10]


def known_block(store: dict) -> str:
    rows = [x for x in store["lessons"] if x["status"] in ("pending", "active")]
    return "\n".join(f"K{x['id']}. {lesson_text(x)}" for x in rows) or "（还没有）"


def parse(out: str) -> list[dict]:
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("lessons") if isinstance(data, dict) else None
    return [x for x in items or [] if isinstance(x, dict)]


def parse_self(out: str, lines: dict[str, dict], day: str) -> list[dict]:
    """复盘回来的“关于自己”：证据要是别人那行或程序记录。→ [{"fact", "kind", "day", "line"}]（selffacts.add_learned 吃这个）。"""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return []
    rows = data.get("关于自己") if isinstance(data, dict) else None
    out_rows = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        line = lines.get(str(it.get("证据") or "").strip().upper())
        if line is None or line.get("self"):
            continue
        out_rows.append({"fact": str(it.get("事实") or ""), "kind": str(it.get("类") or "").strip(),
                         "day": day, "line": str(line.get("text", ""))})
    return out_rows


def apply(store: dict, items: list[dict], lines: dict[str, dict], now: float, day: str) -> dict:
    """把复盘出来的教训记进去。lines = {"L12": {"self": bool, "text": str}, "R1": {...}}：用来查证据是不是别人的 / 程序记录。
    返回 {"new": n, "more": n, "active": n, "again": n, "dropped": n}。"""
    st = {"new": 0, "more": 0, "active": 0, "again": 0, "dropped": 0}
    by_id = {f"K{x['id']}": x for x in store["lessons"]}
    for it in items:
        situation = " ".join(str(it.get("场合") or "").split())[:40]
        lesson = " ".join(str(it.get("教训") or "").split())[:60]
        ev = str(it.get("证据") or "").strip().upper()
        line = lines.get(ev)
        if not situation or not lesson or line is None or line.get("self"):
            st["dropped"] += 1  # 没证据、证据是她自己那行
            continue
        if OFF_TOPIC.search(situation + lesson):
            st["dropped"] += 1  # 语气 / 用词 / 长短 / 亲近：不归这里管
            continue
        strong = bool(it.get("强")) or ev.startswith("R")
        where = str(it.get("哪里") or "都").strip()
        where = where if where in ("群聊", "私聊", "都") else "都"
        evidence = {"day": day, "line": str(line.get("text", ""))[:120], "t": now}
        same = by_id.get(str(it.get("同") or "").strip().upper())
        if same is None:
            same = next((x for x in store["lessons"] if x["status"] in ("pending", "active")
                         and bigram_overlap(lesson_text(x), f"{situation}：{lesson}") >= 0.55), None)
        if same is not None:
            same["n"] += 1
            same["last_seen"] = now
            same["evidence"] = (same.get("evidence", []) + [evidence])[-5:]
            same["strong"] = same.get("strong") or strong
            if same["status"] == "active" and same.get("shown_since", 0) > 0:
                same["revise"] = True  # 给大脑看过还照样犯
                same["shown_since"] = 0
                st["again"] += 1
            st["more"] += 1
            x = same
        else:
            x = {"id": store["next"], "situation": situation, "lesson": lesson, "where": where, "n": 1, "strong": strong,
                 "status": "pending", "t0": now, "last_seen": now, "evidence": [evidence], "shown": 0, "shown_since": 0,
                 "last_shown": 0.0, "revise": False}
            store["next"] += 1
            store["lessons"].append(x)
            by_id[f"K{x['id']}"] = x
            st["new"] += 1
        if x["status"] == "pending" and (x["strong"] or x["n"] >= 2):
            x["status"] = "active"
            x["active_t"] = now
            st["active"] += 1
    return st


def tidy(store: dict, now: float, learned_after: int = 6, fade_days: float = 30, max_active: int = 30) -> dict:
    """学会了的退下、长期没碰到的淡掉、生效的太多就留碰到多的新的。"""
    st = {"learned": 0, "faded": 0, "capped": 0}
    for x in store["lessons"]:
        if x["status"] == "active" and x.get("shown_since", 0) >= learned_after and not x.get("revise"):
            x["status"], x["done_t"] = "learned", now
            st["learned"] += 1
        elif x["status"] in ("pending", "active") and now - max(x["last_seen"], x.get("last_shown") or 0) > fade_days * 86400:
            x["status"], x["done_t"] = "faded", now
            st["faded"] += 1
    active = sorted((x for x in store["lessons"] if x["status"] == "active"), key=lambda x: (-x["n"], -x["last_seen"]))
    for x in active[max_active:]:
        x["status"], x["done_t"] = "faded", now
        st["capped"] += 1
    store["lessons"] = [x for x in store["lessons"]
                        if x["status"] in ("pending", "active") or now - x.get("done_t", now) < 90 * 86400][-300:]
    return st


def usable(store: dict, kind: str) -> list[dict]:
    """这一轮能用的：生效的、场合对得上（群聊 / 私聊 / 都）。"""
    return [x for x in store["lessons"] if x["status"] == "active" and x.get("where", "都") in ("都", kind)]


def mark_shown(x: dict, now: float) -> None:
    x["shown"] = x.get("shown", 0) + 1
    x["shown_since"] = x.get("shown_since", 0) + 1
    x["last_shown"] = now


def note(rows: list[dict]) -> str:
    return HEAD + "\n" + "\n".join(f"- {lesson_text(x)}" for x in rows)


def report(store: dict) -> str:
    act = [x for x in store["lessons"] if x["status"] == "active"]
    pend = [x for x in store["lessons"] if x["status"] == "pending"]
    learned = [x for x in store["lessons"] if x["status"] == "learned"]
    lines = [f"生效 {len(act)} 条、待确认 {len(pend)} 条（再碰到一次就生效）、学会了 {len(learned)} 条"]
    for title, rows in (("生效的", act), ("待确认的", pend)):
        if rows:
            lines.append(title + "：")
        for x in rows:
            ev = (x.get("evidence") or [{}])[-1]
            lines.append(f"#{x['id']} {lesson_text(x)}（{x.get('where', '都')}，碰到 {x['n']} 次，给大脑看过 {x.get('shown', 0)} 次"
                         + ("，要改写" if x.get("revise") else "") + f"）\n    证据 {ev.get('day', '')}：{ev.get('line', '')[:60]}")
    if learned:
        lines.append("学会了的：" + "；".join(f"#{x['id']} {x['lesson']}" for x in learned[-5:]))
    lines.append("删一条：/佳树教训 删 编号")
    return "\n".join(lines)
