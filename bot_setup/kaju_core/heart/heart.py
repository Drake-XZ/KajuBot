"""佳树的心情与好感：纯计算部分（不碰 AstrBot，离线测试直接调）。

几个想法来自抖音「玄清」的 WhaleGirl V5.0 图文笔记（代码是这里自己写的）：
- 心境像激素：每一维有基线，没事时按指数慢慢回到基线（稳态回归）；聊天里的事按"感受 + 强度"推一下（事件扰动）。
- 单轮变动钳位：一轮对话最多改这么多，一句话拧不动整个心情，也刷不满好感。
- 状态只由代码保存和计算（"生命卡唯一真值"）：回复她的模型只读不写，事件由另一次模型调用在后台判断。
- 离线时间补偿：很久没聊，按压缩后的时间淡化，不会一下清零。
"""

from __future__ import annotations

import math

# ------------------------------------------------------------------ 心情（全局，她只有一颗心）
DIMS = ("joy", "energy", "stress", "warm")
BASE = {"joy": 0.6, "energy": 0.6, "stress": 0.12, "warm": 0.5}
HALF_LIFE_H = {"joy": 3.0, "energy": 2.0, "stress": 4.0, "warm": 3.0}

# 感受 → (开心, 精神, 委屈/紧张, 想黏人) 的推动量（强度 2 =「明显」时）
EMOTIONS: dict[str, tuple[float, float, float, float]] = {
    "开心": (0.12, 0.05, -0.04, 0.03),
    "兴奋": (0.10, 0.15, 0.0, 0.0),
    "得意": (0.08, 0.06, -0.02, 0.0),
    "害羞": (0.05, 0.03, 0.02, 0.08),
    "感动": (0.10, 0.0, -0.05, 0.12),
    "安心": (0.06, 0.0, -0.10, 0.06),
    "好奇": (0.03, 0.06, 0.0, 0.0),
    "平静": (0.0, 0.0, -0.02, 0.0),
    "无聊": (-0.04, -0.06, 0.0, 0.0),
    "困": (0.0, -0.12, 0.0, 0.02),
    "担心": (-0.05, 0.0, 0.08, 0.04),
    "吃醋": (-0.05, 0.05, 0.08, 0.06),
    "委屈": (-0.10, -0.03, 0.12, 0.04),
    "失落": (-0.08, -0.05, 0.04, 0.0),
    "难过": (-0.14, -0.06, 0.08, 0.03),
    "生气": (-0.08, 0.06, 0.12, -0.06),
    "烦": (-0.06, 0.0, 0.08, -0.05),
    "害怕": (-0.08, 0.0, 0.15, 0.05),
    "后悔": (-0.05, -0.03, 0.06, 0.05),
    "释怀": (0.05, 0.0, -0.12, 0.02),
}
INTENSITY_SCALE = {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.6}

# ------------------------------------------------------------------ 心事（放不下的事）
# 强烈的负面感受会变成一件"心事"：它不是简单地按时间消失——
# 时间会冲淡它（不同感受快慢不同：气来得快去得快，委屈、担心挂得久），
# 但后台隔几个小时、第二天早上会让她"回想"一遍，结合之后真实发生的事决定：越想越气、慢慢平复、
# 转成后悔、还是放下；对方道歉/安慰、或者又来一次，也会当场改变它。
THREAD_EMOTIONS = {"委屈", "生气", "难过", "担心", "害怕", "吃醋", "失落", "后悔", "烦"}
THREAD_HALF_LIFE_H = {"生气": 10.0, "烦": 4.0, "吃醋": 8.0, "委屈": 30.0, "难过": 30.0, "失落": 20.0,
                      "害怕": 16.0, "担心": 72.0, "后悔": 36.0}
THREAD_MAX = 3.0
# 余韵：看过/读过的东西（故事、视频、文章）留下的情绪——不是谁的错，不回想、不等谁道歉，几个小时到半天自然淡掉
CONTENT_EMOTIONS = THREAD_EMOTIONS | {"感动"}
CONTENT_HALF_LIFE_H = {"难过": 10.0, "感动": 8.0, "害怕": 6.0, "担心": 10.0, "失落": 8.0, "生气": 4.0, "烦": 3.0,
                       "委屈": 6.0, "吃醋": 3.0, "后悔": 6.0}


def thread_charge(th: dict, now: float) -> float:
    """心事此刻的分量（0~3）：从上次更新起按这种感受的半衰期变淡；放下了的变淡得快三倍。"""
    if th.get("kind") == "content":
        hl = CONTENT_HALF_LIFE_H.get(th.get("emo", ""), 6.0)
    else:
        hl = THREAD_HALF_LIFE_H.get(th.get("emo", ""), 12.0)
    if th.get("status") != "open":
        hl /= 3
    dt_h = max(0.0, now - float(th.get("t", now))) / 3600
    return float(th.get("c", 0.0)) * 0.5 ** (dt_h / hl)


def set_charge(th: dict, charge: float, now: float) -> None:
    th["c"] = round(clamp(charge, 0.0, THREAD_MAX), 3)
    th["t"] = now


def thread_offsets(threads: list[dict], now: float, scale: float = 0.3, cap: float = 0.25) -> dict[str, float]:
    """压在心里的事把心情的"平常值"往下拽：委屈没解决时，就算没人惹她，心情也回不到平时那么好。"""
    off = {d: 0.0 for d in DIMS}
    for th in threads:
        if th.get("status") != "open":
            continue
        vec = EMOTIONS.get(th.get("emo", ""))
        if not vec:
            continue
        k = thread_charge(th, now) * scale
        for d, v in zip(DIMS, vec):
            off[d] += v * k
    return {d: clamp(v, -cap, cap) for d, v in off.items()}


def charge_words(c: float) -> str:
    if c >= 2.3:
        return "很强烈"
    if c >= 1.5:
        return "挺明显"
    if c >= 0.8:
        return "有一点"
    return "淡淡的"


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def is_night(hour: int) -> bool:
    return hour >= 23 or hour < 6


def baselines(hour: int, circadian: bool = True, offsets: dict[str, float] | None = None) -> dict[str, float]:
    """各维的基线。精神跟着作息走：深夜、清晨低一些；心里压着事时整体往下拽（offsets）。"""
    base = {d: v + (offsets or {}).get(d, 0.0) for d, v in BASE.items()}
    if circadian:
        if 0 <= hour < 6:
            base["energy"] -= 0.35
        elif hour < 8 or hour >= 22:
            base["energy"] -= 0.15
        if hour >= 23:
            base["energy"] -= 0.1
    return base


WEATHER = {"joy": 0.08, "energy": 0.06}  # 每天的“天气”幅度（照 anima-brain 的 daily weather）


def weather(day: str, amp: dict[str, float] | None = None) -> dict[str, float]:
    """这一天心情底色的小偏移：按日期定（同一天一直一样，每天不一样），开心 ±0.08、精神 ±0.06。
    像真人有的日子醒来就心情好一点、有的日子没来由地蔫一点；不是谁惹的，所以只挪平常值，不进“刚才的事”。"""
    import hashlib
    out = {}
    for d, a in (amp or WEATHER).items():
        h = int(hashlib.sha1(f"kaju-weather:{day}:{d}".encode()).hexdigest()[:8], 16)
        out[d] = round((h / 0xFFFFFFFF * 2 - 1) * float(a), 4)
    return out


def decay(mood: dict, now: float, base: dict[str, float], half_life_h: dict[str, float] | None = None) -> dict:
    """稳态回归：h(t+dt) = base + (h - base) · 2^(-dt / 半衰期)。"""
    hl = half_life_h or HALF_LIFE_H
    dt_h = max(0.0, now - float(mood.get("t", now))) / 3600
    out = {}
    for d in DIMS:
        cur = float(mood.get(d, base[d]))
        out[d] = base[d] + (cur - base[d]) * 0.5 ** (dt_h / max(0.1, float(hl.get(d, 3.0))))
    out["t"] = now
    return out


def push(mood: dict, emotion: str, intensity: int, weight: float = 1.0, turn_cap: float = 0.25) -> dict:
    """事件扰动：按感受和强度推一下各维；每维每轮最多动 turn_cap，越靠近两端越推不动。"""
    vec = EMOTIONS.get(emotion)
    scale = INTENSITY_SCALE.get(int(intensity), 0.0) * weight
    out = dict(mood)
    if not vec or scale <= 0:
        return out
    for d, v in zip(DIMS, vec):
        x = float(out[d])
        delta = clamp(v * scale, -turn_cap, turn_cap)
        delta *= min(1.0, (1 - x) * 2) if delta > 0 else min(1.0, x * 2)
        out[d] = clamp(x + delta, 0.0, 1.0)
    return out


def chime_factor(mood: dict, lo: float = 0.6, hi: float = 1.3) -> float:
    """群里主动插话的意愿倍数：开心、有精神时多说两句，委屈、没精神时少说。"""
    f = 1 + 0.6 * (mood["energy"] - 0.6) + 0.6 * (mood["joy"] - 0.6) - 0.8 * max(0.0, mood["stress"] - 0.3)
    return round(clamp(f, lo, hi), 3)


def mood_words(m: dict, hour: int) -> list[str]:
    words = []
    j, e, s, w = m["joy"], m["energy"], m["stress"], m["warm"]
    if j >= 0.8:
        words.append("特别开心")
    elif j >= 0.68:
        words.append("心情不错")
    elif j < 0.3:
        words.append("心情很低落")
    elif j < 0.45:
        words.append("有点低落")
    if e >= 0.78:
        words.append("精神满满")
    elif e < 0.25:
        words.append("困得不行" if is_night(hour) else "很累、没什么精神")
    elif e < 0.42:
        words.append("有点困了" if is_night(hour) or hour < 8 else "有点累")
    if s >= 0.55:
        words.append("心里很委屈、绷得紧紧的")
    elif s >= 0.35:
        words.append("心里有点不安、有点烦")
    if w >= 0.7:
        words.append("特别想撒娇黏人")
    elif w >= 0.6:
        words.append("有点想黏人")
    elif w <= 0.3:
        words.append("不太想黏人")
    return words or ["心情平常，挺平静的"]


def speech_hints(m: dict, aff: float, hour: int) -> list[str]:
    hints = []
    if m["joy"] >= 0.68:
        hints.append("语气轻快些，感叹号和～可以多一点，更愿意多聊几句、分享自己的事")
    elif m["joy"] < 0.45:
        hints.append("话少一点、句子短一点，感叹号少用；但不迁怒对方，对方关心你、逗你开心时你会好受一些")
    if m["energy"] < 0.42:
        hints.append("回得短、懒洋洋的，可以带点" + ("困意" if is_night(hour) or hour < 8 else "累") + "，但别每句都说")
    elif m["energy"] >= 0.78 and m["joy"] >= 0.6:
        hints.append("一兴奋就停不下来：一句接一句、感叹号连发")
    if m["stress"] >= 0.35:
        hints.append("有点敏感、容易别扭；被安慰、被哄会很快软下来，然后自己给台阶")
    if m["warm"] >= 0.6 and aff >= 60:
        hints.append("对TA更想撒娇")
    return hints[:3]


# ------------------------------------------------------------------ 好感（每个人一份）
LEVELS = ((90, "很亲近"), (75, "喜欢"), (60, "熟悉"), (40, "普通"), (20, "有点疏远"), (0, "戒备"))
ATTITUDE = {
    "很亲近": "很亲近、很信任TA：会撒娇、分享心事和小秘密，主动关心TA；TA不开心你会很在意",
    "喜欢": "喜欢TA：说话亲昵自然，会开玩笑、撒点娇、主动找话题",
    "熟悉": "已经比较熟了：自然随意，会开玩笑，偶尔关心TA",
    "普通": "普通朋友：友好有礼貌，正常聊天，不特别亲昵",
    "有点疏远": "有点疏远：客气、话少一点，不撒娇，不主动延伸话题",
    "戒备": "对TA有戒心：礼貌但保持距离，回答简短，不开亲昵的玩笑；TA真心道歉或示好，你可以慢慢软化",
}


def level(a: float) -> str:
    for lo, name in LEVELS:
        if a >= lo:
            return name
    return LEVELS[-1][1]


def seed_affection(msg_count: int, start: float = 50.0, max_bonus: float = 15.0) -> float:
    """第一次算好感时：以前聊得多的人从高一点的地方开始（聊过 35 句 ≈ +12）。"""
    if msg_count <= 0:
        return start
    return round(start + min(max_bonus, 4 * math.log2(1 + msg_count / 5)), 1)


def compress_days(days: float) -> float:
    """离线时间补偿：7 天内照算，7~30 天按一半，30 天以上按 0.15，最多算 90 天。"""
    d = max(0.0, days)
    if d <= 7:
        e = d
    elif d <= 30:
        e = 7 + (d - 7) * 0.5
    else:
        e = 7 + 23 * 0.5 + (d - 30) * 0.15
    return min(e, 90.0)


def drift(a: float, days: float, neutral: float = 50.0, up_half_days: float = 90.0, down_half_days: float = 10.0) -> float:
    """很久没聊：好感慢慢回到中间。高的淡得很慢；低的（生过气）消得快一些——她不记仇。"""
    if days <= 0:
        return a
    hl = up_half_days if a > neutral else down_half_days
    return neutral + (a - neutral) * 0.5 ** (compress_days(days) / max(0.1, hl))


def affection_step(a: float, delta: float, gained_today: float, *, daily_cap: float = 6.0, up_cap: float = 3.0,
                   down_cap: float = 6.0, floor: float = 0.0, repeats: int = 0, repeat_k: float = 0.6) -> float:
    """一轮对话后的好感变化量（已经钳位）。

    涨：越高越难涨（50 分时 1 倍，75 分时 0.5 倍，最少 0.25 倍），每轮最多 up_cap，每人每天最多 daily_cap；
    同一天里这个人已经让她好感涨过 repeats 次，这次再除以 (1 + repeat_k·repeats)——好话说第三遍没第一遍那么打动人（照 anima-brain）；
    跌：每轮最多 down_cap。不会低于 floor、高于 100。
    """
    if delta > 0:
        d = delta * clamp((100 - a) / 50, 0.25, 1.0) / (1 + repeat_k * max(0, int(repeats)))
        d = min(d, up_cap, max(0.0, daily_cap - gained_today))
    else:
        d = max(delta, -down_cap)
    return clamp(a + d, floor, 100.0) - a
