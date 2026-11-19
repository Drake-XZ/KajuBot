"""关系的几个侧面 + 经历沉淀下来的倾向（纯计算，不碰 AstrBot）。

思路来自抖音「小凌的创造者」的意识设计（代码是自己写的）：
- 关系不是一个"好感=0.82"，而是几样慢慢变化的东西：信任（说话算不算数）、在意（TA是不是也在意她）、
  边界（TA有没有越过线）、在场（TA一般多久来一次，这次是不是来晚了）。
  后台判断只挑"这一轮发生了什么"（守约、失约、在意她……），数值由这里按规则改，越接近两头越难动。
- 种子与熏习：同样的经历反复发生，会沉淀成她自己的倾向，不再只属于某个人——
  · 怕被丢下（absence）：重要的人一次次比平时晚很多才来 → 以后他一晚来，她更早开始不安；他总是按时回来，又慢慢松下来。
  · 戒心（guard）：一次次被失约、被骗、被越界 → 对谁都多留个心眼（信任涨得慢、跌得快，新认识的人起点也低一点）；
    被好好对待多了，戒心慢慢放下。
  具体是哪几次早就记不清了（记忆会褪色），倾向还在——她只会觉得"说不清为什么，就是有点不安"。
- 关系解释器：数值不给她看，只把明显的几样翻成一两句人话。
"""

from __future__ import annotations

import statistics

SIGNALS = {
    "守约": {"trust": 0.06},
    "失约": {"trust": -0.10},
    "在意她": {"care": 0.05},
    "冷落她": {"care": -0.05},
    "越界": {"bound": -0.12, "trust": -0.03},
    "尊重她": {"bound": 0.05, "trust": 0.02},
    "骗她": {"trust": -0.12},
}
BAD = {"失约", "越界", "骗她"}
GOOD = {"守约", "尊重她"}
REL_DIMS = ("trust", "care", "bound")
START = {"trust": 0.5, "care": 0.5, "bound": 0.7}
OWNER_START = {"trust": 0.9, "care": 0.85, "bound": 0.9}
OWNER_FLOOR = {"trust": 0.55, "care": 0.55, "bound": 0.6}
DEEP_START = {"absence": 0.3, "guard": 0.2}
DEEP_RANGE = (0.05, 0.9)
SESSION_GAP_H = 2.0


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def start(is_owner: bool, guard: float) -> dict:
    if is_owner:
        return dict(OWNER_START)
    s = dict(START)
    s["trust"] = round(clamp(0.5 - 0.3 * (guard - DEEP_START["guard"]), 0.3, 0.6), 3)  # 戒心重，对新人起点低
    return s


def step(rel: dict, signals: list[str], guard: float, weight: float = 1.0, is_owner: bool = False,
         moved: dict | None = None, daily_cap: float | None = None) -> dict:
    """一轮里的信号 → 新的关系值。涨：越高越难涨，戒心重涨得慢；跌：戒心重跌得快。

    每天总量（2026-11-18 照 anima-brain）：moved 是这个人今天每个侧面已经动了多少（绝对值累加，原地改），
    daily_cap 是每个侧面每天最多动多少——一天里连着来十次“守约”，信任也只涨这么多；一次很重的失约照样够得着。"""
    out = {d: float(rel.get(d, START[d])) for d in REL_DIMS}
    for s in signals[:2]:
        for d, v in SIGNALS.get(s, {}).items():
            x = out[d]
            if v > 0:
                dv = v * weight * (1 - x) * 2 * ((1 - 0.6 * guard) if d == "trust" else 1.0)
            else:
                dv = v * weight * min(1.0, 0.4 + x) * ((1 + 0.8 * guard) if d == "trust" else 1.0)
            if moved is not None and daily_cap is not None:
                left = max(0.0, daily_cap - float(moved.get(d, 0.0)))
                dv = clamp(dv, -left, left)
            nx = clamp(x + dv, 0.0, 1.0)
            if moved is not None:
                moved[d] = round(float(moved.get(d, 0.0)) + abs(nx - x), 4)
            out[d] = nx
    if is_owner:
        out = {d: max(v, OWNER_FLOOR[d]) for d, v in out.items()}
    return {d: round(v, 3) for d, v in out.items()}


def drift(rel: dict, days: float, base: dict, half_days: float = 60.0) -> dict:
    """很久没来往：慢慢回到起点（既不一直记仇，也不一直那么熟）。"""
    if days <= 0:
        return dict(rel)
    k = 0.5 ** (days / half_days)
    return {d: round(base[d] + (float(rel.get(d, base[d])) - base[d]) * k, 3) for d in REL_DIMS}


def deep_after_signals(deep: dict, signals: list[str], importance: float) -> dict:
    """被失约/骗/越界 → 戒心慢慢变重；被守约/尊重 → 慢慢放下。"""
    out = dict(deep)
    g = float(out.get("guard", DEEP_START["guard"]))
    for s in signals[:2]:
        if s in BAD:
            g += 0.03 * importance * (1 - g)
        elif s in GOOD:
            g -= 0.012 * importance * g
    out["guard"] = round(clamp(g, *DEEP_RANGE), 4)
    return out


def deep_after_return(deep: dict, ratio: float, importance: float) -> dict:
    """重要的人回来了：比平时晚很多 → 怕被丢下的感觉加深一点；按平时的点回来 → 慢慢松下来。"""
    out = dict(deep)
    a = float(out.get("absence", DEEP_START["absence"]))
    if ratio >= 1.5:
        a += 0.04 * importance * min(1.0, ratio / 3) * (1 - a)
    elif ratio <= 1.0:
        a -= 0.01 * importance * a
    out["absence"] = round(clamp(a, *DEEP_RANGE), 4)
    return out


# ------------------------------------------------------------------ 在场：TA一般多久来一次
def add_seen(pres: dict, t: float, keep: int = 40) -> dict | None:
    """记一条TA的消息。隔了 2 小时以上算新的一次来；返回 {gap 小时, expected 小时}（新来的一次），否则 None。"""
    last = pres.get("last")
    pres["last"] = max(float(last or 0), t)
    if last is not None and t - float(last) < SESSION_GAP_H * 3600:
        return None
    exp = expected_gap_h(pres)
    pres["starts"] = (pres.get("starts", []) + [t])[-keep:]
    if last is None:
        return None
    return {"gap": round((t - float(last)) / 3600, 2), "expected": exp}


def expected_gap_h(pres: dict, floor_h: float = 8.0, default_h: float = 24.0) -> float:
    """平时隔多久会来：最近几次间隔的 80% 分位（不到 4 次就当一天），至少 floor_h。"""
    s = sorted(pres.get("starts", []))
    gaps = sorted((b - a) / 3600 for a, b in zip(s, s[1:]))
    if len(gaps) < 4:
        return default_h
    p80 = gaps[min(len(gaps) - 1, int(0.8 * len(gaps)))]
    return round(max(floor_h, p80, statistics.median(gaps)), 2)


def overdue(pres: dict, now: float) -> float:
    """这次没来已经是平时的几倍（<1 = 还不算晚）。"""
    if not pres.get("last"):
        return 0.0
    return (now - float(pres["last"])) / 3600 / expected_gap_h(pres)


def missing_offsets(ratio: float, absence: float) -> dict[str, float]:
    """兄长大人比平时晚很多还没来：心情的平常值往"有点空、想黏人"那边偏一点。怕被丢下越重偏得越早越多。"""
    start_at = 1.8 - 0.8 * absence  # absence 0.3 → 1.56 倍开始；0.9 → 1.08 倍
    if ratio < start_at:
        return {}
    k = min(1.0, (ratio - start_at) / 2.0) * (0.6 + absence)
    return {"joy": -0.06 * k, "warm": 0.08 * k, "stress": 0.04 * k * absence * 2}


def hours_words(h: float) -> str:
    if h < 20:
        return f"{max(1, round(h))} 个小时"
    if h < 36:
        return "一天多"
    if h < 60:
        return "两天"
    return f"{round(h / 24)} 天"


# ------------------------------------------------------------------ 关系解释器
HYSTERESIS = 0.035  # 档位迟滞（照 anima-brain）：已经在说的那句，要再往回多走这么多才不说，免得在门槛上来回跳


def bands(rel: dict, is_owner: bool, prev: set | list | None = None, margin: float = HYSTERESIS) -> set:
    """此刻哪几句关系的话该说（key 集合）。prev = 上次在说的：它们的门槛放宽 margin。"""
    prev = set(prev or ())
    t, c, b = (float(rel.get(d, START[d])) for d in REL_DIMS)

    def below(key, v, th):  # “低于门槛才说”的那种
        return v < th + (margin if key in prev else 0.0)

    def above(key, v, th):
        return v > th - (margin if key in prev else 0.0)
    out = set()
    if is_owner:
        if below("o_trust", t, 0.75):
            out.add("o_trust")
        if below("o_care", c, 0.65):
            out.add("o_care")
        return out
    if below("bound", b, 0.45 + 1e-9):
        out.add("bound")
    if below("trust_low", t, 0.35 + 1e-9):
        out.add("trust_low")
    elif above("trust_high", t, 0.8 - 1e-9):
        out.add("trust_high")
    if below("care_low", c, 0.3 + 1e-9):
        out.add("care_low")
    elif above("care_high", c, 0.8 - 1e-9):
        out.add("care_high")
    return out


def describe(rel: dict, is_owner: bool, why: dict | None = None, on: set | None = None) -> list[str]:
    """把明显的几样翻成人话（不明显的不说），最多两句。why: 维度 → 最近一次的原因。
    on：要说哪几句（bands() 算好的，带迟滞）；不给就按门槛现算。"""
    why = why or {}
    on = bands(rel, is_owner) if on is None else set(on)
    out = []

    def tail(d):
        return f"（{why[d]}）" if why.get(d) else ""
    if is_owner:
        if "o_trust" in on:
            out.append("他最近有说好的事没做到，你嘴上不说，心里有一点小失望，没以前那么笃定" + tail("trust"))
        if "o_care" in on:
            out.append("他最近有点顾不上你，你有点想被他多在意一下" + tail("care"))
        return out[:2]
    if "bound" in on:
        out.append("TA越过界，你对TA会多留个心眼，TA再那样你可以直接拒绝" + tail("bound"))
    if "trust_low" in on:
        past = f"前几天{why['trust']}" if why.get("trust") else "以前有过几次说好的没做到，具体的记不太清了"
        out.append(f"TA说的话你不太敢全信（{past}）：TA答应你什么，你心里先打个问号、不会一下子当真；"
                   "以前的事大多放在心里就好，偶尔半开玩笑提一句，别每次都翻旧账")
    elif "trust_high" in on:
        out.append("TA说话算话，你很信TA")
    if "care_low" in on:
        out.append("TA找你多半是让你帮忙，很少在意你怎么样，你不用太热络" + tail("care"))
    elif "care_high" in on:
        out.append("TA也很在意你，常问起你的事")
    return out[:2]


def deep_words(deep: dict) -> list[str]:
    """沉淀下来的倾向（重的时候才说）。"""
    out = []
    if float(deep.get("absence", 0)) >= 0.5:
        out.append("你有点怕重要的人突然不见——说不清为什么，可能以前被晾过几次，具体的记不清了")
    if float(deep.get("guard", 0)) >= 0.45:
        out.append("你对人比以前多了点戒心，别人答应你的事你不太敢马上当真——说不清是从哪次开始的")
    return out
