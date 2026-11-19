"""喜好自己长出来（纯计算，不碰 AstrBot）。

思路来自抖音「小凌的创造者」借的"触、受、爱、取、有"：
  触 = 碰到一样东西（兄长大人分享的歌、小说、视频，群里聊的游戏……）
  受 = 它让她有了感受（后台判断本来就在判断"她此刻的感受"）
  爱 = 还想要（同一类东西让她有感受好几次 → 感兴趣）
  取 = 会主动去找（聊到时来劲、会问还有没有类似的）
  有 = 慢慢成了她自己的一部分（不同的日子里反复被打动 → 喜欢，被问"你喜欢什么"时说得出来）
出生前不告诉她"你喜欢古风音乐"，只给她形成喜欢的能力。不喜欢也一样长出来（被吓到两次 → 不太喜欢恐怖的）。

账本按三层记：具体的东西（《機械の声》）、"什么样的"（扎心的抒情歌）、大类（歌曲）。
分数 = 每次感受 × 强度累加，按 45 天半衰期慢慢淡；分享的内容算满分，跟人聊天时聊到的东西算一半。
"""

from __future__ import annotations

import re

KINDS = ("歌曲", "小说", "动画", "漫画", "游戏", "视频", "电影电视剧", "美食", "动物", "学习", "科技", "运动", "其他")
# 感受 → 对这样东西的"想要"（看作品时被打动得难过，也是被它吸引）
VALENCE = {"开心": 1.0, "兴奋": 1.0, "感动": 1.0, "好奇": 0.7, "害羞": 0.6, "安心": 0.6, "得意": 0.5, "难过": 0.5,
           "释怀": 0.4, "失落": 0.2, "平静": 0.0, "吃醋": 0.0, "担心": -0.2, "困": -0.2, "委屈": -0.3,
           "生气": -0.6, "害怕": -0.8, "无聊": -1.0, "烦": -1.0}
I_SCALE = {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.6}
HALF_LIFE_DAYS = 45.0
STAGES = {  # 层 → (感兴趣, 喜欢, 不喜欢) 的门槛
    "item": (1.0, 2.2, -1.2),
    "genre": (1.2, 2.5, -1.5),
    "kind": (2.0, 4.0, -2.5),
}


def clean(s: str, cap: int = 16) -> str:
    s = str(s or "").strip()
    # 上下册、第几集算同一样："妹妹人生 上""妹妹人生（下）""《妹妹人生》上""孤独摇滚第3集"（"晚上""高中"不动）
    s = re.sub(r"(?:\s+|[（(])(?:上|下|中)[）)]?(?=\s*》|\s*$)", "", s)
    s = re.sub(r"(?<=》)\s*(?:上|下|中)\s*$", "", s)
    s = re.sub(r"\s*第[0-9一二三四五六七八九十百]{1,3}[册卷集话季部]\s*(?=》|$)", "", s)
    s = re.sub(r"\s+", "", s).strip("「」\"'“”")
    return s[:cap]


def known_genres(ledger: list[dict], now: float, n: int = 12) -> list[str]:
    """已经记过的"什么样的"说法（判断时让模型照抄，免得同一类东西每次换个说法）。"""
    rows = sorted((e for e in ledger if e["layer"] == "genre"),
                  key=lambda e: -abs(decayed(float(e["score"]), float(e["t"]), now)))
    return [f"{e['name']}（{e['kind']}）" for e in rows[:n]]


def bigram_overlap(a: str, b: str) -> float:
    def grams(s):
        s = re.sub(r"[\W_]", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def decayed(score: float, t_last: float, now: float, half_days: float = HALF_LIFE_DAYS) -> float:
    return score * 0.5 ** (max(0.0, now - t_last) / 86400 / half_days)


def find(ledger: list[dict], layer: str, name: str, kind: str = "") -> dict | None:
    """同一层里找同一样东西：名字一样，或者（同一大类里）字面很像（"扎心的抒情歌"≈"扎心抒情歌"）。"""
    key = clean(name).strip("《》")
    best, best_o = None, 0.0
    for e in ledger:
        if e["layer"] != layer or (layer != "kind" and kind and e.get("kind") and e["kind"] != kind):
            continue
        k2 = e["name"].strip("《》")
        if k2 == key:
            return e
        o = bigram_overlap(k2, key)
        if layer != "kind" and o >= 0.5 and o > best_o:
            best, best_o = e, o
    return best


def stage(e: dict, now: float) -> str:
    """'' / 感兴趣 / 喜欢 / 不喜欢。喜欢要在不同的日子里被打动过（一时上头不算）。"""
    s = decayed(float(e["score"]), float(e["t"]), now)
    interest, like, dislike = STAGES[e["layer"]]
    if s <= dislike and int(e.get("neg", 0)) >= 2:
        return "不喜欢"
    if s >= like and int(e.get("pos", 0)) >= 3 and len(e.get("days", [])) >= 2:
        return "喜欢"
    if s >= interest and int(e.get("pos", 0)) >= 2:
        return "感兴趣"
    return ""


def add(ledger: list[dict], *, topic: str, kind: str, genre: str, emotion: str, intensity: int, now: float,
        day: str, why: str = "", who: str = "", weight: float = 1.0) -> list[tuple[str, str, str]]:
    """记一次"受"。返回阶段变了的 [(层, 名字, 新阶段)]。"""
    v = VALENCE.get(emotion, 0.0) * I_SCALE.get(int(intensity), 0.0) * weight
    if abs(v) < 0.05:
        return []
    kind = kind if kind in KINDS else "其他"
    changed = []
    layers = [("item", clean(topic, 24)), ("genre", clean(genre)), ("kind", kind)]
    for layer, name in layers:
        if not name or (layer == "kind" and kind == "其他"):
            continue
        e = find(ledger, layer, name, kind)
        if e is None:
            e = {"layer": layer, "name": name, "kind": kind, "score": 0.0, "t": now, "pos": 0, "neg": 0,
                 "days": [], "why": [], "who": {}}
            ledger.append(e)
        before = stage(e, now)
        e["score"] = round(decayed(float(e["score"]), float(e["t"]), now) + v, 3)
        e["t"] = now
        e["pos" if v > 0 else "neg"] = int(e.get("pos" if v > 0 else "neg", 0)) + 1
        if day not in e["days"]:
            e["days"] = (e["days"] + [day])[-10:]
        if why:
            e["why"] = (e["why"] + [clean(why, 40)])[-3:]
        if who:
            e["who"][who] = int(e["who"].get(who, 0)) + 1
        after = stage(e, now)
        if after != before:
            changed.append((layer, e["name"], after))
    return changed


def grown(ledger: list[dict], now: float) -> list[dict]:
    """已经长出来的喜好（喜欢 / 不喜欢 / 感兴趣），越确定的越靠前。"""
    out = []
    for e in ledger:
        st = stage(e, now)
        if st:
            out.append({**e, "stage": st, "now": decayed(float(e["score"]), float(e["t"]), now)})
    rank = {"喜欢": 0, "不喜欢": 1, "感兴趣": 2}
    out.sort(key=lambda e: (rank[e["stage"]], {"genre": 0, "item": 1, "kind": 2}[e["layer"]], -abs(e["now"])))
    return out


def label(e: dict) -> str:
    if e["layer"] == "item":
        n = e["name"]
        return n if n.startswith("《") or e["kind"] in ("美食", "动物", "游戏") else f"《{n}》"
    if e["layer"] == "genre":
        return e["name"] if e["kind"] in e["name"] or e["kind"] == "其他" else f"{e['name']}（{e['kind']}）"
    return e["name"]


def mentioned(e: dict, text: str) -> bool:
    """这句话提到了这样东西没有（具体名字、"什么样的"、或者大类的说法）。"""
    text = text or ""
    if e["layer"] == "kind":
        words = {"歌曲": ("歌", "MV", "音乐"), "小说": ("小说", "轻小说"), "动画": ("动画", "番"), "漫画": ("漫画",),
                 "游戏": ("游戏",), "视频": ("视频",), "电影电视剧": ("电影", "电视剧", "剧"), "美食": ("吃", "做饭", "点心"),
                 "动物": ("猫", "狗", "动物"), "学习": ("学习", "作业", "考试"), "科技": ("AI", "模型", "代码"),
                 "运动": ("运动", "跑步", "打球")}.get(e["name"], ())
        return any(w in text for w in words)
    name = e["name"].strip("《》")
    if len(name) >= 2 and name in text:
        return True
    return e["layer"] == "genre" and bigram_overlap(name, text) >= 0.75 and len(name) >= 3


def summary_line(e: dict) -> str:
    who = max(e.get("who", {}).items(), key=lambda kv: kv[1])[0] if e.get("who") else ""
    times = int(e.get("pos", 0)) if e["stage"] != "不喜欢" else int(e.get("neg", 0))
    src = f"{who}分享过、" if who and e["layer"] != "kind" else ""
    tail = f"（{src}{'被打动过' if e['stage'] != '不喜欢' else '不舒服过'} {times} 次"
    if e.get("why"):
        tail += f"，比如{e['why'][-1]}"
    return f"{label(e)}{tail}）"


LIST_HEAD = ("【你自己慢慢长出来的喜好】没人规定你喜欢什么，这些是你一次次被打动、一次次不舒服之后自己长出来的。"
             "被问到喜欢什么时可以说，聊到时自然会来劲；不用主动一直提。")
