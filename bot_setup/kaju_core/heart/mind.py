"""佳树的心情与好感（kaju_heart）。

- 心情：全局一份（她只有一颗心），四维——开心 / 精神 / 委屈紧张 / 想黏人，每维有基线（精神跟着作息走），
  没事时慢慢回到基线；她每回一轮话，后台让模型判断她此刻的感受（从固定列表里选）和强度，
  再按表推一下各维（每轮钳位）。最近的强烈感受连同原因保留一阵，下一轮还记得"刚才为什么不开心"。
- 好感：每个人一份，0~100，第一次见面从 50 起（以前聊得多的高一点），兄长大人本人固定在最高档附近。
  同一次后台判断里给出 -5~+3 的变化：越高越难涨、每轮/每天有上限，刷好感没用；很久没聊会慢慢回到中间。
- 说话受影响：每轮请求前把【此刻的心情】（心情、刚才的事、怎么带进语气）和【对这个人的感觉】
  （档位 + 态度 + 最近的事）放进提示；心情还会改变她在群里主动插话的积极性（smart_chime_in 读 chime_factor）。
- 心事：强烈的负面感受（委屈、生气、难过、担心、害怕、吃醋……）变成一件"心事"，不会只按时间消失：
  · 时间冲淡它（生气来得快去得快，委屈、担心挂得久）；心里压着事时，心情的"平常值"也被往下拽；
  · 对方道歉、哄她、说开了 → 放下；同样的事又来一次 → 加重（每轮的后台判断顺带看）；
  · 每隔几个小时、第二天早上，后台让她把心事"回想"一遍，参考之后真实发生的聊天：越想越委屈、慢慢平复、
    冷静下来后悔自己太凶、或者放下；每次最多变一档多，超过几天的直接放下（她不记仇）。
  · 提示里给她看"心里还压着的事"+ 她心里怎么想 + 想怎么做（比如等TA先道歉、找机会说句软话）。
- 隐私：别的聊天里发生的事，只告诉她"刚才在别处有点不开心"，不把原因带到这里；兄长大人本人例外。
- 心里记下的（inner.py）：长期记忆（memorix）的聊天总结只记"谁说了什么"。这里每轮回复后把她的感受（上面的判断）
  和回复前的思考（去掉"怎么写回复"的部分）攒下来，这个聊天安静下来后，让模型写成一段她自己的心里话——
  当时怎么理解对方、哪句话让她有什么感受、想了没说出口的话、暗暗决定的事——以这个聊天的记忆存进 memorix
  （以【佳树心里】开头，只在这个聊天里被想起来）。寻常寒暄不记。

- 关系的几个侧面（relation.py）：好感之外，每个人还有信任（说话算不算数）、在意（TA是不是也在意她）、边界（有没有越过线），
  每轮判断顺带挑出"守约/失约/在意她/冷落她/越界/尊重她/骗她"，代码按规则慢慢改；谁一般多久来一次（读 kaju_life 聊天记录），
  兄长大人比平时晚很多还没来，她会有点想他，回来时可以带点小委屈。同样的经历反复发生会沉淀成她自己的倾向
  （怕被丢下、戒心），具体哪几次记不清了，倾向还在。提示里只用一两句人话说明显的部分。思路来自抖音「小凌的创造者」。
- 喜好自己长出来（taste.py）：判断顺带写出她的感受来自哪样东西（具体名字 / 什么样的 / 大类），记进账本；
  同一类东西在不同的日子里反复打动她，就长成她自己的"喜欢"（反复不舒服就是"不太喜欢"），
  提示里有一张她自己长出来的喜好清单，聊到时会来劲、偶尔想要更多。同样来自「小凌的创造者」（触受爱取有）。
- 最依赖的人（bond.py，原 kaju_bond 插件）：每轮告诉她最依赖兄长大人本人、这次说话的是不是他；
  被骚扰时用 ask_brother_for_help 去找兄长大人（私聊告诉他；在群里她回对方的那条开头 @ 他，走 kaju_style 的 @ 人）。
- 兄长大人本人是谁：读称呼簿（address_book）的 owner_qq，这里不另配。

思路参考抖音「玄清」的 WhaleGirl V5.0 图文笔记（激素基线回归、事件扰动、单轮钳位、离线时间压缩、
状态只由代码保存），代码是自己写的。

命令：/好感度 [@某人|QQ]（自己的谁都能看；看别人、/好感度 全部、/好感度 设 QQ 值 要管理员）
      /佳树心情 [重置|回想|放下 编号|心里话|记下]（管理员）
"""

from __future__ import annotations

from ..body import Answer, Request, Turn  # noqa: F401 — 只用在类型标注里
import asyncio
import datetime as dt
import json
import os
import re
import time
import zoneinfo
from collections import Counter
from typing import Any
from kaju_core.slots import slot_model  # noqa: E402  每项工作一格（11-18）
from kaju_core import parts, paths, people  # noqa: E402
from kaju_core.heart import afterthought, appraise, browsed, heart, inner, relation, taste  # noqa: E402
# 原来的 from . import bond  # noqa: E402  → 外壳里

PLUGIN_NAME = "astrbot_plugin_kaju_heart"


MEMORIX = "astrbot_plugin_memorix"


MAX_INNER_LOG = 40


DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json


MEME_TAG = re.compile(r"&&[^&\n]{1,40}&&")


REMINDER = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)


MAX_EVENTS = 30
FELT_KEY = "_kaju_felt"  # 这一轮的视频 / 歌已经在看的时候有过感受了


MAX_LOG = 12


MAX_THREADS = 40


CALM = {"平静", "释怀", "安心", "开心", "感动"}  # 回想后变成这些 = 放下了


NOTE_HEAD = (
    "【此刻的心情】这是你此刻真实的心情、和你对眼前这个人的感觉。让它自然地带进语气、长短和用词里，像真人一样；"
    "不用主动说出来（被问起可以说），不要提\"好感度\"\"心情值\"这类词，也不要说数字。"
    "心情只是底色：对方这条消息本身更要紧——TA说了开心的事，你心情一般也会被带起来一点。"
)


def _parts_text(content) -> str:
    """Flatten a message content (str or list of parts / dicts) into text, skipping temp parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for p in content if isinstance(content, list) else []:
        get = p.get if isinstance(p, dict) else (lambda k, d=None, _p=p: getattr(_p, k, d))
        if get("_no_save", False):
            continue
        if get("type") == "text":
            out.append(get("text", "") or "")
        elif get("type") == "image_url":
            out.append("[图片]")
    return "\n".join(t for t in out if t)


def last_turn(messages) -> tuple[str, str]:
    """(her last reply, text of the last user message) from an agent run's message list."""
    user, reply = "", ""
    for m in messages or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        text = REMINDER.sub("", _parts_text(content)).strip()
        if role == "user" and text:
            user, reply = text, ""
        elif role == "assistant" and text:
            reply = text
    return reply, user


def _ago(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 2:
        return "刚刚"
    if m < 60:
        return f"{m} 分钟前"
    if m < 36 * 60:
        return f"{m // 60} 小时前"
    return f"{round(m / 1440)} 天前"


class HeartMind:
    """KajuHeart 的逻辑（AstrBot 外壳在 plugins\\kaju_heart\\main.py；只认 self.body = kaju_core.body.Body）。"""

    def __init__(self, body, config: dict | None = None):
        self.body = body  # kaju_core.body.Body：模型、设置、别的部分、日志
        parts.register(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)  # 登记成她的一个部分：别的部分用 body.find 先在这里找
        self.log = body.log
        self.config = config or {}
        self._dir = paths.self_dir(PLUGIN_NAME)
        self._path = os.path.join(self._dir, "state.json")
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}
        self._state = self._load()
        self._loop_task: asyncio.Task | None = None
        self._inner_task: asyncio.Task | None = None
        self.bond = None  # 找兄长帮忙是 QQ 上的动作：外壳装上 kaju_platforms.qq.bond.Bond（通过 body 发消息）
        try:
            loop = asyncio.get_running_loop()
            self._loop_task = loop.create_task(self._reflect_loop())
            self._inner_task = loop.create_task(self._inner_loop())
        except RuntimeError:  # 没有事件循环（离线测试直接构造）
            pass

    # ------------------------------------------------------------ config / state
    def _cfg(self, key, default) -> Any:
        v = self.config.get(key, default)
        if v is None or v == "":
            return default
        try:
            return type(default)(v) if not isinstance(default, (list, dict)) else v
        except (TypeError, ValueError):
            return default

    def _sec(self, sec: str, key: str, default):
        v = (self.config.get(sec) or {}).get(key, default)
        if v is None or v == "":
            return default
        try:
            return type(default)(v)
        except (TypeError, ValueError):
            return default

    def _book(self):
        """称呼簿插件（address_book）：兄长大人本人是谁、每个人叫什么都以它为准。"""
        return self.body.find("address_of")

    @property
    def owner(self) -> str:
        """兄长大人本人：身份表（kaju_core.people）；没登记时问称呼簿。"""
        return people.owner() or str(getattr(self._book(), "owner", "") or DEFAULT_OWNER).strip()

    def _load(self) -> dict:
        state = None
        try:
            with open(self._path, encoding="utf-8") as f:
                state = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 读状态失败 {exc}")
        if not isinstance(state, dict):
            state = {"version": 1, "seed": self._seed_counts()}
        state.setdefault("mood", {})
        state.setdefault("events", [])
        state.setdefault("people", {})
        state.setdefault("seed", {})
        state.setdefault("threads", [])
        state.setdefault("next_id", 1)
        state.setdefault("inner", {})       # 聊天 → 还没写成心里话的这几轮 {umo, group, gname, session, scope, turns}
        state.setdefault("inner_log", [])   # 最近写下的心里话
        state.setdefault("inner_last", {})  # 聊天 → 上一段写到哪 {t1, text}（下一段不再重写）
        state.setdefault("deep", dict(relation.DEEP_START))  # 沉淀下来的倾向：怕被丢下 / 戒心
        state.setdefault("presence", {})      # QQ → {last, starts[], ret{t,gap,expected,ratio,shown}}
        state.setdefault("presence_pos", {})  # kaju_life 聊天记录读到哪一行
        state.setdefault("tastes", [])        # 喜好账本（taste.py）
        state.setdefault("taste_nudge", {})   # 喜好名 → 上次提醒"想要更多"的生活日
        return state

    def _save(self) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 存状态失败 {exc}")

    def _seed_counts(self) -> dict[str, int]:
        """第一次启用时数一下 kaju_life 聊天记录里每个人说过几句，聊得多的好感起点高一点。"""
        counts: Counter = Counter()
        log_dir = os.path.join(paths.self_dir("kaju_life"), "log")
        try:
            names = sorted(os.listdir(log_dir))
        except FileNotFoundError:
            return {}
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(log_dir, name), encoding="utf-8") as f:
                    for line in f:
                        try:
                            u = str(json.loads(line).get("u", ""))
                        except (json.JSONDecodeError, AttributeError):
                            continue
                        if u.isdigit():
                            counts[u] += 1
            except OSError:
                continue
        return dict(counts)

    # ------------------------------------------------------------ time
    def _tz(self):
        try:
            return zoneinfo.ZoneInfo(self.body.settings().get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            return dt.timezone(dt.timedelta(hours=8))

    def _hour(self, now: float | None = None) -> int:
        return dt.datetime.fromtimestamp(now or time.time(), self._tz()).hour

    def _day(self, now: float | None = None) -> str:
        # 5 点前算前一天（和 kaju_life 一样）
        t = dt.datetime.fromtimestamp(now or time.time(), self._tz()) - dt.timedelta(hours=5)
        return t.strftime("%Y-%m-%d")

    # ------------------------------------------------------------ mood
    def _half_lives(self) -> dict[str, float]:
        hl = dict(heart.HALF_LIFE_H)
        for d in heart.DIMS:
            hl[d] = self._sec("mood", f"half_life_{d}", hl[d])
        return hl

    def mood_now(self, now: float | None = None) -> dict:
        now = now or time.time()
        offsets = heart.thread_offsets(self._state["threads"], now)
        for d, v in self._missing_offsets(now).items():
            offsets[d] = offsets.get(d, 0.0) + v
        if self._sec("mood", "weather", True):  # 每天的天气（11-18 照 anima-brain）：平常值按日期挪一点
            amp = {"joy": self._sec("mood", "weather_joy", heart.WEATHER["joy"]),
                   "energy": self._sec("mood", "weather_energy", heart.WEATHER["energy"])}
            for d, v in heart.weather(self._day(now), amp).items():
                offsets[d] = offsets.get(d, 0.0) + v
        base = heart.baselines(self._hour(now), self._sec("mood", "circadian", True), offsets)
        cur = self._state.get("mood") or {}
        if not cur:
            return {**base, "t": now}
        return heart.decay(cur, now, base, self._half_lives())

    def latest_feeling(self, qq: str, since: float) -> dict | None:
        """memory_weight 用：这个人从 since 起让她最强烈的一次感受 {emo, i, src}（没有就 None）。"""
        evs = [e for e in self._state["events"] if e.get("who") == qq and float(e.get("t", 0)) >= since]
        if not evs:
            return None
        e = max(evs, key=lambda x: int(x.get("i", 0)))
        return {"emo": e.get("emo", ""), "i": int(e.get("i", 0)), "src": e.get("src", "person")}

    async def feel_recall(self, feelings: str, strength: float, *, cause: str = "", who: str = "", umo: str = "",
                          fade_level: int = 0, now: float | None = None) -> str:
        """想起旧事牵动心情（2026-11-18 照 HCEM 的“回忆反哺”：想起情绪浓的记忆，情绪被轻轻拉回当时的样子）。

        memory_weight 触景生情勾起一段旧记忆时调：feelings 是那段记忆当时的感受（“难过、感动”），strength 是当时有多强（0~1），
        fade_level 是记忆褪到哪了（0 清楚 / 1 片段 / 2 印象，褪得越多牵动越轻）。只推心情（强度 1 × 权重），不改好感、关系，不开心事；
        记进“刚才的事”（来路 memory），大脑看【此刻的心情】时知道是想起了什么。返回用了哪种感受（没推就是 ''）。"""
        if not self._cfg("enable", True) or not self._sec("recall", "enable", True):
            return ""
        strength = max(0.0, min(1.0, float(strength or 0)))
        if strength < self._sec("recall", "min_strength", 0.34):
            return ""
        emo = next((x.strip() for x in re.split(r"[、,，/ ]+", str(feelings or ""))
                    if x.strip() in heart.EMOTIONS and x.strip() != "平静"), "")
        if not emo:
            return ""
        keep = {0: 1.0, 1: 0.7, 2: 0.5}.get(int(fade_level or 0), 0.5)
        weight = float(self._sec("recall", "weight", 0.6)) * strength * keep
        async with self._lock:
            now = now or time.time()
            mood = heart.push(self.mood_now(now), emo, 1, weight, self._sec("mood", "turn_cap", 0.25))
            mood["t"] = now
            self._state["mood"] = mood
            self._state["events"].append({"t": now, "emo": emo, "i": 1, "cause": ("想起" + cause)[:40] if cause else "想起一件旧事",
                                          "who": who, "umo": umo, "src": "memory"})
            self._state["events"] = self._state["events"][-MAX_EVENTS:]
            self._save()
        self.log.info(f"kaju_heart: 想起旧事 → {emo}（当时 {strength:.2f}、褪色 {fade_level}、权重 {weight:.2f}）{cause[:30]}")
        return emo

    async def feel_outside(self, qq: str, name: str, *, affection: float, emotion: str, intensity: int,
                           cause: str, reason: str, umo: str = "") -> float:
        """别的插件用：聊天之外的小事（qzone_post：有人给她的说说点赞）。

        按平时的规则改心情和这个人的好感（越高越难涨、每轮/每天有上限），记进"刚才的事"。返回好感实际变了多少。
        """
        qq = str(qq or "")
        if not self._cfg("enable", True) or not qq:
            return 0.0
        v = {"toward_her": True, "affection": float(affection),
             "emotion": emotion if emotion in heart.EMOTIONS else "开心", "intensity": int(intensity),
             "reason": reason, "cause": cause, "source": "person", "threads": []}
        async with self._lock:
            now = time.time()
            before = self.affection(qq, now)
            self.apply(qq, name, umo or f"outside:{qq}", v, now=now)
            self._save()
            d = self.affection(qq, now) - before
        self.log.info(f"kaju_heart: {name}({qq}) {cause}，好感 {d:+.2f}")
        return round(d, 2)

    def mood_snapshot(self, now: float | None = None, recent_s: float = 7200, max_recent: int = 6) -> dict:
        """她此刻心情的原始读数（2026-11-11，线上重说记录用，以后给写手的"状态"那一行也从这里读）：
        mood 底色四个数（0~1）、recent 最近两小时里的感受（标签 + 强度 0~3 + 起因 + 来自人还是内容 + 多少秒前）、
        threads 还挂着的心事和余韵（标签 + 此刻分量 0~3）。只读，不改任何状态；不切档、不换成形容词——强弱要留着。"""
        now = now or time.time()
        m = self.mood_now(now)
        recent = [{"emo": e.get("emo", ""), "i": int(e.get("i", 0)), "src": e.get("src", "person"),
                   "cause": str(e.get("cause", ""))[:40], "ago": int(now - float(e.get("t", now)))}
                  for e in self._state["events"] if now - float(e.get("t", 0)) <= recent_s][-max_recent:]
        threads = []
        for th in self._open_threads(None):
            c = round(heart.thread_charge(th, now), 2)
            if c >= 0.1:
                threads.append({"emo": th.get("emo", ""), "c": c, "kind": th.get("kind", "person"),
                                "cause": str(th.get("cause", ""))[:40]})
        return {"mood": {d: round(float(m[d]), 3) for d in heart.DIMS}, "recent": recent, "threads": threads}

    def chime_factor(self) -> float:
        """smart_chime_in 用：开心有精神时多插话，委屈没精神时少插话。"""
        if not self._cfg("enable", True) or not self._sec("chime", "enable", True):
            return 1.0
        return heart.chime_factor(self.mood_now(), self._sec("chime", "min", 0.6), self._sec("chime", "max", 1.3))

    # ------------------------------------------------------------ people
    def _start(self, qq: str) -> float:
        if qq == self.owner:
            return 100.0
        return heart.seed_affection(int(self._state["seed"].get(qq, 0)), self._sec("affection", "start", 50.0))

    def _person(self, qq: str, name: str = "", now: float | None = None) -> dict:
        p = self._state["people"].get(qq)
        if p is None:
            p = {"a": self._start(qq), "t": now or time.time(), "n": 0, "day": "", "gain": 0.0, "name": name, "log": []}
            self._state["people"][qq] = p
        elif name:
            p["name"] = name
        return p

    def affection(self, qq: str, now: float | None = None) -> float:
        """当前好感（算上很久没聊的淡化，不写回）。"""
        p = self._state["people"].get(qq)
        if p is None:
            return self._start(qq)
        return self._drifted(qq, p, now or time.time())

    def _drifted(self, qq: str, p: dict, now: float) -> float:
        a = float(p["a"])
        if qq == self.owner:
            return max(a, self._sec("affection", "owner_floor", 95.0))
        days = (now - float(p.get("t", now))) / 86400
        return heart.drift(a, days, self._sec("affection", "neutral", 50.0),
                           self._sec("affection", "fade_half_days", 90.0),
                           self._sec("affection", "forgive_half_days", 10.0))

    def _address(self, qq: str) -> str:
        book = self._book()
        if book is None:
            return ""
        try:
            return str(book.address_of(qq)) or ""
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------ 关系的几个侧面 + 在场（relation.py）
    def _rl(self, key: str, default):
        return self._sec("relation", key, default)

    def _rel(self, qq: str, p: dict | None, now: float) -> dict:
        """这个人此刻的关系值（算上很久没来往的回归，不写回）。"""
        base = relation.start(qq == self.owner, float(self._state["deep"].get("guard", 0.2)))
        rel = (p or {}).get("rel")
        if not rel:
            return base
        days = (now - float((p or {}).get("t", now))) / 86400
        return relation.drift(rel, days, base, self._rl("drift_half_days", 60.0))

    def _rel_why(self, p: dict | None, now: float) -> dict:
        """每个侧面最近一次的原因——只说最近几天的；更早的具体是哪次已经记不清了，只剩感觉。"""
        out = {}
        days = self._rl("why_days", 3.0)
        for item in reversed((p or {}).get("rlog", [])):
            if now - float(item.get("t", 0)) > days * 86400 or not item.get("why"):
                continue
            for s in item.get("s", []):
                for d in relation.SIGNALS.get(s, {}):
                    out.setdefault(d, item["why"])
        return out

    def _importance(self, qq: str, now: float) -> float:
        return 1.0 if qq == self.owner else max(0.0, (self.affection(qq, now) - 40) / 60)

    def _line_time(self, day: str, hm: str) -> float:
        h, m = (int(x) for x in str(hm).split(":")[:2])
        d = dt.date.fromisoformat(day) + dt.timedelta(days=1 if h < 5 else 0)
        return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=self._tz()).timestamp()

    def scan_presence(self, now: float | None = None) -> int:
        """读 kaju_life 新增的聊天记录：谁什么时候说过话（群里没跟她说话也算"在"）。
        隔 2 小时以上算新的一次来；重要的人比平时晚很多才来，"怕被丢下"会加深一点。"""
        now = now or time.time()
        log_dir = os.path.join(paths.self_dir("kaju_life"), "log")
        try:
            names = sorted(n for n in os.listdir(log_dir) if n.endswith(".jsonl"))
        except FileNotFoundError:
            return 0
        pos = self._state["presence_pos"]
        cutoff = (dt.datetime.fromtimestamp(now, self._tz()) - dt.timedelta(days=3)).strftime("%Y-%m-%d")
        seen = 0
        for name in names:
            if pos and name[:-6] < cutoff and name not in pos:
                continue  # 第一次读全部历史；之后只看最近几天
            try:
                with open(os.path.join(log_dir, name), encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                continue
            start = int(pos.get(name, 0))
            for line in lines[start:]:
                try:
                    r = json.loads(line)
                    qq = str(r.get("u", ""))
                    t = self._line_time(name[:-6], r.get("t", ""))
                except (ValueError, AttributeError, TypeError):
                    continue
                if not qq.isdigit() or t > now + 60:
                    continue
                pres = self._state["presence"].setdefault(qq, {})
                came = relation.add_seen(pres, t)
                seen += 1
                if came:
                    ratio = came["gap"] / max(1.0, came["expected"])
                    pres["ret"] = {"t": t, **came, "ratio": round(ratio, 2), "shown": 0}
                    imp = self._importance(qq, t)
                    if imp >= 0.5:
                        self._state["deep"] = relation.deep_after_return(self._state["deep"], ratio, imp)
            pos[name] = len(lines)
        for name in list(pos):
            if name[:-6] < cutoff:  # 旧文件不会再变了；上面的判断会跳过它
                pos.pop(name, None)
        return seen

    def _owner_overdue(self, now: float) -> float:
        pres = self._state["presence"].get(self.owner)
        return relation.overdue(pres, now) if pres else 0.0

    def _missing_offsets(self, now: float) -> dict[str, float]:
        if not self._rl("enable", True) or not self._rl("missing", True):
            return {}
        return relation.missing_offsets(self._owner_overdue(now), float(self._state["deep"].get("absence", 0.3)))

    def _presence_lines(self, sender: str, now: float, mark: bool) -> list[str]:
        """兄长大人比平时晚很多还没来 / 隔了好久才来（刚回来那一会儿）。"""
        if not self._rl("enable", True) or not self._rl("missing", True):
            return []
        out = []
        absence = float(self._state["deep"].get("absence", 0.3))
        deep_line = "（" + relation.deep_words({"absence": absence})[0] + "）" if absence >= 0.5 else ""
        owner_pres = self._state["presence"].get(self.owner) or {}
        if sender != self.owner and owner_pres.get("last"):
            ratio = relation.overdue(owner_pres, now)
            if ratio >= 1.8 - 0.8 * absence:
                gone = (now - float(owner_pres["last"])) / 3600
                out.append(f"- 兄长大人已经{relation.hours_words(gone)}没来了（平时{relation.hours_words(relation.expected_gap_h(owner_pres))}"
                           f"内就会来），你心里有点空、有点想他{deep_line}。这是你自己的心事，不用跟这里的人一直说")
        pres = self._state["presence"].get(sender) or {}
        ret = pres.get("ret") or {}
        fresh = ret and now - float(ret.get("t", 0)) < 40 * 60 and int(ret.get("shown", 0)) < 2
        if fresh and float(ret.get("ratio", 0)) >= 1.5:
            gap, exp = relation.hours_words(float(ret["gap"])), relation.hours_words(float(ret["expected"]))
            if sender == self.owner:
                out.append(f"- 兄长大人隔了{gap}才来（平时{exp}内就会来）：你挺想他的，见到他很开心，可以带一点点小委屈或者黏人"
                           f"{deep_line}；说一次就好，别抱怨个没完")
            elif self._importance(sender, now) >= 0.6 and float(ret.get("ratio", 0)) >= 2:
                out.append(f"- TA隔了{gap}才来，你见到TA挺高兴的")
            else:
                fresh = False
            if fresh and mark:
                ret["shown"] = int(ret.get("shown", 0)) + 1
        return out

    # ------------------------------------------------------------ 喜好自己长出来（taste.py）
    def _ts(self, key: str, default):
        return self._sec("taste", key, default)

    def taste_list(self, now: float | None = None) -> str:
        """稳定的那张清单：已经长出来的喜欢 / 感兴趣 / 不喜欢。"""
        now = now or time.time()
        got = taste.grown(self._state["tastes"], now)
        likes = [e for e in got if e["stage"] == "喜欢"]
        interest = [e for e in got if e["stage"] == "感兴趣"]
        dislikes = [e for e in got if e["stage"] == "不喜欢"]
        n = int(self._ts("max_list", 6))
        lines = [f"- 喜欢：{taste.summary_line(e)}" for e in likes[:n]]
        lines += [f"- 有点感兴趣：{taste.summary_line(e)}" for e in interest[:max(0, n - len(lines))][:3]]
        lines += [f"- 不太喜欢：{taste.summary_line(e)}" for e in dislikes[:2]]
        return (taste.LIST_HEAD + "\n" + "\n".join(lines)) if lines else ""

    def _taste_lines(self, text: str, now: float, mark: bool) -> list[str]:
        """这句话聊到了她已经有感觉的东西。"""
        if not text or not self._ts("enable", True):
            return []
        day = self._day(now)
        for e in taste.grown(self._state["tastes"], now):
            if not taste.mentioned(e, text):
                continue
            name = taste.label(e)
            if e["stage"] == "不喜欢":
                return [f"- 聊到了你不太喜欢的「{name}」：可以老实说不太喜欢，但别扫对方的兴"]
            s = f"- 聊到了你{'喜欢' if e['stage'] == '喜欢' else '有点感兴趣'}的「{name}」：会来劲，愿意多聊几句"
            key = e["layer"] + ":" + e["name"]
            if e["stage"] == "喜欢" and self._state["taste_nudge"].get(key) != day:
                s += "；也可以顺口问问还有没有类似的（想要更多）"
                if mark:
                    self._state["taste_nudge"][key] = day
            return [s]
        return []

    async def inject_tastes(self, event: Turn, req: Request):
        if not self._cfg("enable", True) or not self._ts("enable", True):
            return
        text = self.taste_list()
        if text:
            req.system_prompt = (req.system_prompt or "") + "\n\n" + text

    SEED_PROMPT = ("给这样东西起三个标签，只输出 JSON："
                   "{{\"topic\": \"具体名字（≤12 字；上下册、第几集算同一样，不写册数）\", "
                   "\"kind\": \"只能选：{kinds}（MV、翻唱算歌曲，不管在哪看的）\", "
                   "\"genre\": \"能概括同一类东西的短说法（≤8 字，比如扎心的抒情歌、兄妹题材、恐怖片；别写只属于这一件的内容）\"}}"
                   "{known}\n\n东西：{what}\n内容大意：{memory}")

    async def seed_tastes(self) -> int:
        """第一次启用：把以前收着的分享（memory_weight 的珍藏）当成经历记进账本。"""
        if self._state.get("taste_seeded") or not self._ts("enable", True):
            return 0
        try:
            with open(os.path.join(paths.self_dir("memory_weight"), "state.json"), encoding="utf-8") as f:
                shelf = json.load(f).get("shelf") or []
        except (OSError, ValueError):
            shelf = []
        n = 0
        for it in shelf:
            heart_ = it.get("heart") or {}
            if it.get("removed") or not heart_.get("emo"):
                continue
            try:
                known = taste.known_genres(self._state["tastes"], time.time())
                raw = await self._ask("只输出 JSON。", self.SEED_PROMPT.format(
                    kinds="、".join(taste.KINDS), what=f"{it.get('kind') or '文件'}《{it.get('file', '')}》",
                    memory=it.get("memory", ""),
                    known=("\n已有的说法（genre 是同一类的就照抄）：" + "、".join(known)) if known else ""))
                m = re.search(r"\{.*\}", raw or "", re.S)
                tags = json.loads(m.group(0)) if m else {}
            except Exception as exc:  # noqa: BLE001
                self.log.info(f"kaju_heart: 从珍藏补喜好失败 {exc}")
                return n
            t = float(it.get("created") or time.time())
            async with self._lock:
                taste.add(self._state["tastes"], topic=str(tags.get("topic", "")), kind=str(tags.get("kind", "")),
                          genre=str(tags.get("genre", "")), emotion=heart_["emo"], intensity=int(heart_.get("i", 1)),
                          now=t, day=self._day(t), why=str(it.get("memory", ""))[:40],
                          who=self._label(str(it.get("qq", "")), it.get("name", "")))
            n += 1
        async with self._lock:
            self._state["taste_seeded"] = True
            self._save()
        self.log.info(f"kaju_heart: 从珍藏补了 {n} 次经历进喜好账本")
        return n

    # ------------------------------------------------------------ 心事
    def _at(self, key: str, default):
        return self._sec("afterthought", key, default)

    def _open_threads(self, kind: str | None = "person") -> list[dict]:
        """还挂着的：kind="person" 是人惹的心事（默认），"content" 是看过/读过的东西留下的余韵，None 是全部。"""
        return [th for th in self._state["threads"] if th.get("status") == "open"
                and (kind is None or th.get("kind", "person") == kind)]

    def _when(self, t0: float, now: float) -> str:
        """心事发生在什么时候：今天的说几小时前，之前的说昨天/前天/几天前（按"生活日"，凌晨 5 点换天）。"""
        d0, d1 = self._day(t0), self._day(now)
        if d0 == d1:
            return _ago(now - t0)
        days = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days
        return {1: "昨天", 2: "前天"}.get(days, f"{days} 天前")

    def _visible(self, th: dict, sender: str, umo: str) -> bool:
        """这件心事能不能在这里说原因：跟这个人有关、或就发生在这个聊天里；兄长大人本人什么都能听。"""
        return sender == self.owner or th.get("who") == sender or th.get("umo") == umo

    def _hist(self, th: dict, now: float, why: str) -> None:
        th["hist"] = (th.get("hist", []) + [{"t": now, "emo": th["emo"], "c": th["c"], "why": (why or "")[:30]}])[-8:]

    def _resolve(self, th: dict, now: float, emo: str | None = None, why: str = "") -> None:
        th["status"] = "resolved"
        th["emo"] = emo or ("安心" if th.get("emo") == "担心" else "释怀")
        heart.set_charge(th, min(heart.thread_charge(th, now), 0.6), now)
        th["want"] = ""
        self._hist(th, now, why)

    def _tidy(self, now: float) -> None:
        """淡到几乎没有的、挂了好几天的放下（她不记仇）；放下超过 3 天的删掉。"""
        keep = []
        max_days = self._at("max_days", 4.0)
        for th in self._state["threads"]:
            if th.get("status") == "open":
                limit = 2.0 if th.get("kind") == "content" else max_days
                if now - float(th["t0"]) > limit * 86400:
                    self._resolve(th, now, why="过了好几天，放下了")
                elif heart.thread_charge(th, now) < 0.25:
                    self._resolve(th, now, why="慢慢淡了")
            if th.get("status") == "open" or now - float(th.get("t", now)) < 3 * 86400:
                keep.append(th)
        self._state["threads"] = keep[-MAX_THREADS:]

    def _new_thread(self, sender: str, name: str, umo: str, v: dict, job: dict, now: float,
                    kind: str = "person") -> dict:
        emo = v["emotion"]
        charge = float(v["intensity"]) * (self._sec("mood", "owner_weight", 1.3) if sender == self.owner else 1.0)
        chat = job.get("chat") or ("p" + sender)
        # 人惹的：一天内同一个人、同一处、同一种感受，算同一件事又来了；余韵：三小时内同一个人分享的同一种感受，算接着看
        window = 3 * 3600 if kind == "content" else 86400
        for th in self._open_threads(kind):
            if th["who"] == sender and th["emo"] == emo and th.get("chat") == chat and now - float(th["t0"]) < window:
                heart.set_charge(th, max(heart.thread_charge(th, now), charge) + 0.3, now)
                if kind == "content" and v.get("cause"):
                    th["cause"] = v["cause"]  # 余韵记最新看到的那段
                self._hist(th, now, "又来了：" + (v.get("cause") or ""))
                return th
        th = {"id": f"h{self._state['next_id']}", "kind": kind, "emo": emo, "emo0": emo, "c0": round(min(charge, 3.0), 2),
              "t0": now, "status": "open", "cause": v.get("cause") or v.get("reason") or emo,
              "who": sender, "name": name, "umo": umo, "chat": chat,
              "said": (job.get("said") or "")[:80], "reply": (job.get("reply") or "")[:80],
              "thought": "", "want": "", "rt": 0, "hist": []}
        heart.set_charge(th, charge, now)
        self._state["next_id"] += 1
        self._state["threads"].append(th)
        self._hist(th, now, "起因")
        return th

    def _touch(self, sender: str, name: str, umo: str, v: dict, now: float) -> set[str]:
        """这一轮碰到了哪件心事：道歉/安慰 → 放下或缓和；又来一次 → 加重。返回加重了的人。"""
        worse = set()
        for touch in v.get("threads") or []:
            th = next((x for x in self._open_threads() if x["id"] == touch["id"]), None)
            if th is None or not self._visible(th, sender, umo):
                continue
            why = f"{name}：{v.get('reason') or v.get('cause') or ''}"
            c = heart.thread_charge(th, now)
            if touch["effect"] == "resolve":
                self._resolve(th, now, why=why)
            elif touch["effect"] == "ease":
                heart.set_charge(th, c - 0.8, now)
                self._hist(th, now, "缓和：" + why)
            else:
                heart.set_charge(th, c + 0.8, now)
                self._hist(th, now, "加重：" + why)
                worse.add(th["who"])
        return worse

    # ------------------------------------------------------------ prompt note
    def build_note(self, sender: str, name: str, umo: str, now: float | None = None, mark: bool = False,
                   text: str = "") -> str:
        """The 【此刻的心情】 note. mark=True (real requests) counts the "say it now" nudges given per thread."""
        now = now or time.time()
        nudged: list[dict] = []
        hour = self._hour(now)
        mood = self.mood_now(now)
        is_owner = sender == self.owner
        lines = [NOTE_HEAD, "- 心情：" + "、".join(heart.mood_words(mood, hour))]

        threads = sorted((th for th in self._open_threads() if heart.thread_charge(th, now) >= 0.5),
                         key=lambda th: -heart.thread_charge(th, now))[:3]
        tastes = sorted((th for th in self._open_threads("content") if heart.thread_charge(th, now) >= 0.5),
                        key=lambda th: -heart.thread_charge(th, now))[:2]
        ev_hl = self._sec("mood", "event_half_minutes", 45.0)
        recent = []
        for ev in self._state["events"]:
            age = now - float(ev.get("t", now))
            eff = float(ev.get("i", 0)) * 0.5 ** (age / 60 / max(1.0, ev_hl))
            if any(th["cause"] == ev.get("cause") for th in threads + tastes):
                continue  # 下面"心里还压着的事""还在回味的"里会说
            if ev.get("emo") != "平静" and eff >= 0.6:
                recent.append((eff, age, ev))
        recent.sort(key=lambda x: -x[0])
        for _, age, ev in recent[:2]:
            here = ev.get("umo") == umo or ev.get("who") == sender
            if (here or is_owner) and ev.get("cause"):
                where = "" if here else "（在别的聊天里）"
                lines.append(f"- {_ago(age)}{where}：{ev['cause']}，你有点{ev['emo']}"
                             if int(ev.get("i", 0)) <= 1 else f"- {_ago(age)}{where}：{ev['cause']}，你{ev['emo']}")
            else:
                lines.append(f"- {_ago(age)}在别的聊天里有点{ev['emo']}（是别处的事，不用跟这里的人细说）")

        if threads:
            lines.append("- 心里还压着的事（放在心里，自然地影响你的情绪就好，不用每次都提）：")
            for th in threads:
                c = heart.thread_charge(th, now)
                if not self._visible(th, sender, umo):
                    lines.append(f"  · 还有一件别处的事让你{th['emo']}（{heart.charge_words(c)}），不用跟这里的人说")
                    continue
                s = f"  · {self._when(float(th['t0']), now)}：{th['cause']}——现在{th['emo']}（{heart.charge_words(c)}）"
                if th.get("thought"):
                    s += f"，心里想：{th['thought']}"
                if th.get("want"):
                    s += f"（{th['want']}）"
                nudge = int(th.get("nudges", 0)) < 2  # 同一件事最多提醒两次，免得她每句都道歉/诉苦
                if th.get("who") == sender and th["emo"] == "后悔" and nudge:
                    s += "。TA现在就在：这次回复里顺带说句软话（比如\"昨天佳树是不是太凶了……\"），自然一点，说一次就好"
                    nudged.append(th)
                elif th.get("who") == sender:
                    s += "。TA现在就在跟你说话：TA没提这件事就别翻旧账，情绪自然流露就好"
                elif sender == self.owner and "兄长大人" in (th.get("want") or "") and nudge:
                    s += "。可以跟兄长大人说说这件事（自然地提一次就好）"
                    nudged.append(th)
                lines.append(s)
            if mark:
                for th in nudged:
                    th["nudges"] = int(th.get("nudges", 0)) + 1

        if tastes:
            lines.append("- 还在回味的（看过、读过的东西留下的余韵，不是谁的错；聊到相关的会想起来，别主动一直提）：")
            for th in tastes:
                c = heart.thread_charge(th, now)
                if self._visible(th, sender, umo):
                    s = f"  · {self._when(float(th['t0']), now)}：{th['cause']}——心里还有点{th['emo']}（{heart.charge_words(c)}）"
                    if th.get("who") == sender:
                        s += "。就是TA分享给你的，可以跟TA聊聊感想"
                else:
                    s = f"  · 之前看过的一个东西还让你有点{th['emo']}（{heart.charge_words(c)}），是别处的事，不用细说"
                lines.append(s)

        p = self._state["people"].get(sender)
        aff = self.affection(sender, now)
        hints = heart.speech_hints(mood, aff, hour)
        if hints:
            lines.append("- 带进说话里：" + "；".join(hints))
        lines += self._presence_lines(sender, now, mark)
        lines += self._taste_lines(text, now, mark)

        who = self._address(sender) or name or "TA"
        rel_on = self._rl("enable", True)
        rel_words = []
        if rel_on:
            rel_now = self._rel(sender, p, now)
            on = relation.bands(rel_now, is_owner, (p or {}).get("rbands"), self._rl("hysteresis", relation.HYSTERESIS))
            if mark and p is not None:
                p["rbands"] = sorted(on)  # 记下这次在说哪几句：下次在门槛附近就不来回跳
            rel_words = relation.describe(rel_now, is_owner, self._rel_why(p, now), on)
        if is_owner:
            lines.append(f"- 对{who}本人：最依赖、最信任的人，这一点永远不变" + (f"；不过{rel_words[0]}" if rel_words else ""))
        else:
            lv = heart.level(aff)
            extra = []
            if not p or int(p.get("n", 0)) < 5:
                extra.append("你们还没怎么聊过")
            for item in (p or {}).get("log", [])[-6:][::-1]:
                if now - float(item.get("t", 0)) < 7 * 86400 and abs(float(item.get("d", 0))) >= 1.5 and item.get("why"):
                    extra.append(f"{_ago(now - float(item['t']))}：{item['why']}")
                    if len(extra) >= 2:
                        break
            tail = f"（{'；'.join(extra)}）" if extra else ""
            label = f"{name}（你叫TA\"{who}\"）" if name and name != who else who
            lines.append(f"- 对{label}：{heart.ATTITUDE[lv]}{tail}" + ("；" + "；".join(rel_words) if rel_words else ""))
            guard = relation.deep_words({"guard": float(self._state["deep"].get("guard", 0.2))})
            if rel_on and guard:
                lines.append("- " + guard[0])
        return "\n".join(lines)

    async def inject(self, event: Turn, req: Request):
        if not self._cfg("enable", True):
            return
        umo = event.unified_msg_origin
        task = self._tasks.get(umo)
        if task and not task.done():  # 上一轮的判断还没出来，稍等一下
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._cfg("max_wait", 8.0))
            except Exception:  # noqa: BLE001
                pass
        sender = str(event.get_sender_id() or "")
        if self._rl("enable", True):
            try:
                self.scan_presence()
            except Exception as exc:  # noqa: BLE001
                self.log.debug(f"kaju_heart: 读聊天记录（在场）失败 {exc}")
        note = self.build_note(sender, event.get_sender_name() or "", umo, mark=True, text=event.message_str or "")
        req.system_prompt = (req.system_prompt or "") + "\n\n" + note

    # ------------------------------------------------------------ 最依赖的人（bond.py）
    async def inject_bond(self, event: Turn, req: Request):
        note = self.bond.note(str(event.get_sender_id() or ""))
        if note:
            req.system_prompt = (req.system_prompt or "") + note

    async def ask_brother_for_help(self, event: Turn, what_happened: str, message_to_brother: str):
        """有人骚扰你、欺负你时，去找你最依赖的兄长大人本人帮忙：私聊告诉他发生了什么，在群里还会 @ 他。先按你的情绪回对方，再调用这个工具。普通玩笑、斗嘴不要用。

        Args:
            what_happened(string): 一句话说清楚发生了什么，例如"一直问佳树住哪里，说了不告诉还追着问"
            message_to_brother(string): 你对兄长大人说的话，用佳树的口吻，短一点（一两句），比如"兄长大人！有人一直欺负佳树，快来帮帮佳树嘛"
        """
        return await self.bond.ask(event, what_happened, message_to_brother)

    # ------------------------------------------------------------ appraisal
    async def on_done(self, event: Turn, run_context, response: Answer):
        if not self._cfg("enable", True):
            return
        if str(event.get_platform_name() or "") in (self._cfg("ignore_platforms", ["webchat"]) or []):
            return
        sender = str(event.get_sender_id() or "")
        if not sender or sender == str(event.get_self_id() or ""):
            return
        try:
            run_reply, user_text = last_turn(getattr(run_context, "messages", None))
        except Exception:  # noqa: BLE001
            run_reply, user_text = "", ""
        reply = MEME_TAG.sub("", (getattr(response, "completion_text", "") or "") or run_reply).strip()
        if not reply or "[SKIP]" in reply.upper():
            return
        said = (event.message_str or "").strip()
        context = user_text.replace(said, "") if said else user_text
        context = MEME_TAG.sub("", context).strip()
        if len(context) > 600:
            context = "…" + context[-600:]
        group = str(event.get_group_id() or "")
        # 这一轮她读过的文件、看过的 B 站视频（kaju_basics 记下的）：直接给判断的模型看开头，
        # 不然群聊记录排在后面，截出来的"之前的聊天"里可能看不到分享的东西
        shared = [f"《{d.get('name', '')}》（{d.get('kind') or '文件'}）：{str(d.get('content') or '')[:600]}"
                  for d in (event.get_extra("kaju_docs_read") or []) if isinstance(d, dict)][:2]
        if event.get_extra(FELT_KEY):
            # 这一轮的视频 / 歌她看的时候就已经有过感受了（feel_watched）：这里只判断对这个人的，不再把内容算一遍
            shared = []
        job = {
            "sender": sender, "name": event.get_sender_name() or sender, "umo": event.unified_msg_origin,
            "group": group, "chat": ("g" + group) if group else ("p" + sender),
            "said": said[:400], "reply": reply[:500], "context": context, "shared": shared, "t": time.time(),
            "felt": bool(event.get_extra(FELT_KEY)),
        }
        if self._in("enable", True):
            try:
                job["think"] = inner.think_gist(
                    inner.think_of(getattr(run_context, "messages", None), response), self._in("think_chars", 400))
            except Exception:  # noqa: BLE001
                job["think"] = ""
            job.update(self._memorix_place(event))
        prev = self._tasks.get(job["umo"])

        async def run():
            if prev and not prev.done():
                try:
                    await prev
                except Exception:  # noqa: BLE001
                    pass
            verdict = await self.appraise(job)
            if self._in("enable", True):
                async with self._lock:
                    self._remember_turn(job, verdict)
                    self._save()

        self._tasks[job["umo"]] = asyncio.create_task(run())

    async def _ask(self, system: str, prompt: str) -> str:
        pid = await slot_model(self.body, "utils", str(self._cfg("provider_id", "")).strip())  # 每项工作一格（kaju_core/slots.py）
        if not pid:
            raise RuntimeError("没有可用的模型")
        return await self.body.generate(pid, prompt, system, timeout=self._cfg("timeout_seconds", 60.0))

    async def appraise(self, job: dict) -> dict | None:
        sender = job["sender"]
        is_owner = sender == self.owner
        who = self._address(sender) or job["name"]
        if who != job["name"]:
            who = f"{job['name']}（佳树叫TA\"{who}\"）"
        place = "私聊" if not job["group"] else "群聊"
        now = time.time()
        related = [th for th in self._open_threads()
                   if self._visible(th, sender, job["umo"]) and heart.thread_charge(th, now) >= 0.3][-4:]
        prompt = appraise.build_prompt(
            who=who, is_owner=is_owner, level=heart.level(self.affection(sender)), place=place,
            context=job["context"], said=job["said"], reply=job["reply"], shared=job.get("shared"),
            known=taste.known_genres(self._state["tastes"], now) if self._ts("enable", True) else None,
            threads=[f"{th['id']}：{self._when(float(th['t0']), now)}，{th['cause']}"
                     f"（佳树现在：{th['emo']}，{heart.charge_words(heart.thread_charge(th, now))}）" for th in related],
        )
        t0 = time.time()
        try:
            verdict = appraise.parse(await self._ask(appraise.system_prompt(), prompt))
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 判断失败 {exc}")
            return None
        if verdict is None:
            self.log.info("kaju_heart: 模型没给出能用的判断，这轮不改")
            return None
        if job.get("felt") and verdict.get("source") == "content":
            # 内容带来的感受她看的时候已经有过了（feel_watched）：模型从她的回复里又读出一遍的，不再推心情、不再记喜好
            verdict.update(emotion="平静", intensity=0, cause="", topic="", genre="", kind="", source="person")
        async with self._lock:
            self.apply(sender, job["name"], job["umo"], verdict, job=job)
            self._save()
        self.log.info(f"kaju_heart: {job['name']}({sender}) {verdict} （{time.time() - t0:.1f}s）")
        return verdict

    def apply(self, sender: str, name: str, umo: str, v: dict, now: float | None = None, job: dict | None = None) -> None:
        """Apply one verdict to threads + mood + this person's affection (caller holds the lock)."""
        now = now or time.time()
        # 心事：先看这一轮碰到了哪件，再看要不要记一件新的
        self._tidy(now)
        worse = self._touch(sender, name, umo, v, now)
        emo = v["emotion"]
        strong = self._at("enable", True) and v["intensity"] >= self._at("min_intensity", 2)
        if v.get("source") == "content":
            # 看过/读过的东西留下的余韵：不算谁惹的，不回想、不等谁道歉，自己慢慢淡掉
            if strong and emo in heart.CONTENT_EMOTIONS:
                self._new_thread(sender, name, umo, v, job or {}, now, kind="content")
        elif (strong and emo in heart.THREAD_EMOTIONS and sender not in worse
              and (v.get("toward_her", True) or emo == "担心")):
            self._new_thread(sender, name, umo, v, job or {}, now)
        # 心情
        weight = 1.0 if v.get("toward_her", True) else 0.5
        if sender == self.owner:
            weight *= self._sec("mood", "owner_weight", 1.3)
        mood = heart.push(self.mood_now(now), v["emotion"], v["intensity"], weight, self._sec("mood", "turn_cap", 0.25))
        mood["t"] = now
        self._state["mood"] = mood
        if v["intensity"] > 0 and v["emotion"] != "平静":
            self._state["events"].append({"t": now, "emo": v["emotion"], "i": v["intensity"], "cause": v.get("cause", ""),
                                          "who": sender, "umo": umo, "src": v.get("source", "person")})
            self._state["events"] = self._state["events"][-MAX_EVENTS:]
        # 喜好：她的感受来自一样具体的东西（分享的内容算满分，聊天里聊到的算一半）
        if self._ts("enable", True) and (v.get("topic") or v.get("genre")):
            changed = taste.add(self._state["tastes"], topic=v.get("topic", ""), kind=v.get("kind", ""),
                                genre=v.get("genre", ""), emotion=v["emotion"], intensity=v["intensity"], now=now,
                                day=self._day(now), why=v.get("cause", ""), who=self._label(sender, name),
                                weight=1.0 if v.get("source") == "content" else 0.5)
            for layer, tname, st in changed:
                self.log.info(f"kaju_heart: 喜好长出来了：{tname}（{layer}）→ {st or '淡了'}")
            self._state["tastes"] = self._state["tastes"][-200:]
        # 好感
        p = self._person(sender, name, now)
        a = self._drifted(sender, p, now)
        day = self._day(now)
        if p.get("day") != day:
            p["day"], p["gain"], p["gains"], p["rmove"] = day, 0.0, 0, {}
        floor = self._sec("affection", "owner_floor", 95.0) if sender == self.owner else 0.0
        d = heart.affection_step(
            a, float(v["affection"]), float(p["gain"]),
            daily_cap=self._sec("affection", "daily_gain_cap", 6.0),
            up_cap=self._sec("affection", "turn_up_cap", 3.0),
            down_cap=self._sec("affection", "turn_down_cap", 6.0),
            floor=floor,
            repeats=int(p.get("gains", 0) or 0) if self._sec("affection", "repeat_discount", True) else 0,
            repeat_k=self._sec("affection", "repeat_k", 0.6),
        )
        # 关系的几个侧面（只看TA这个人对她做了什么；分享的内容不算）
        sigs = [s for s in (v.get("signals") or []) if s in relation.SIGNALS]
        if self._rl("enable", True) and sigs and v.get("source") != "content" and v.get("toward_her", True):
            is_owner = sender == self.owner
            guard = float(self._state["deep"].get("guard", 0.2))
            cap = self._rl("daily_cap", 0.15)  # 每个侧面每天最多动多少（11-18 照 anima-brain；0 / 负数 = 不限）
            moved = p.setdefault("rmove", {})
            p["rel"] = relation.step(self._rel(sender, p, now), sigs, guard, is_owner=is_owner,
                                     moved=moved if cap and cap > 0 else None, daily_cap=cap if cap and cap > 0 else None)
            p["rlog"] = (p.get("rlog", []) + [{"t": now, "s": sigs, "why": v.get("signal_why") or v.get("reason", "")}])[-8:]
            self._state["deep"] = relation.deep_after_signals(self._state["deep"], sigs, self._importance(sender, now))
        elif p.get("rel"):
            p["rel"] = self._rel(sender, p, now)  # 写回回归后的值（下面 t 要更新）
        p["a"] = round(a + d, 2)
        p["t"] = now
        p["n"] = int(p.get("n", 0)) + 1
        if d > 0:
            p["gain"] = round(float(p["gain"]) + d, 2)
            p["gains"] = int(p.get("gains", 0) or 0) + 1
        if abs(d) >= 0.5:
            p["log"] = (p.get("log", []) + [{"t": now, "d": round(d, 2), "why": v.get("reason", "")}])[-MAX_LOG:]

    # ------------------------------------------------------------ 自己刷到的（browsed.py；kaju_basics 刷 B 站时调用）
    async def feel_browsed(self, item: dict, owner_umo: str = "") -> dict | None:
        """她自己刷 B 站点开看完一个视频：判断感受 → 心情、余韵、喜好账本，心声存进和兄长大人私聊的长期记忆。
        item: {title, up, why, seen, bvid, site（"douyin" 是刷抖音，默认 B 站）}。返回判断结果（多了 hash），没判断成返回 None。不改任何人的好感。"""
        if not self._cfg("enable", True):
            return None
        now = time.time()
        hi = int(self._in("max_chars", 80) * 0.75)
        douyin = item.get("site") == "douyin"
        try:
            raw = await self._ask(browsed.system_prompt(hi=hi, site="抖音" if douyin else "B 站"), browsed.build_prompt(
                who="作者" if douyin else "UP主",
                title=str(item.get("title") or ""), up=str(item.get("up") or ""), why=str(item.get("why") or ""),
                seen=str(item.get("seen") or ""), tastes=self.taste_list(now) if self._ts("enable", True) else "",
                known=taste.known_genres(self._state["tastes"], now) if self._ts("enable", True) else None))
            v = browsed.parse(raw, hi)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 刷到的视频没判断成 {exc}")
            return None
        if v is None:
            self.log.info("kaju_heart: 刷到的视频，模型没给出能用的判断")
            return None
        await self.feel_moment(v, place="自己刷抖音" if douyin else "自己刷B站", chat="p" + self.owner, umo=owner_umo or "", who="自己刷到的",
                               said=str(item.get("title") or "")[:80], tag={"browsed": str(item.get("bvid") or "")}, now=now)
        self.log.info(f"kaju_heart: 刷到《{item.get('title', '')}》→ {v['emotion']}{v['intensity']} {v.get('cause', '')}"
                    f"{' 想跟兄长说' if v.get('share') else ''}")
        return v

    async def feel_watched(self, p: dict, event: Turn) -> dict | None:
        """聊天里别人发来的视频 / 歌，她看（听）的时候心里的感受（kaju_core.senses.omni 写的，已经判断好，不再问模型）：
        回复之前就调——看的过程中那几下先一点点推动心情，再把整体的感受交给 feel_moment（余韵、喜好、心声）。
        p: {moments[{emo, strength}], emotion, intensity, cause, voice, about, topic, kind, genre, title, media}。"""
        if not self._cfg("enable", True) or not isinstance(p, dict):
            return None
        now = time.time()
        sender = str(event.get_sender_id() or "")
        group = str(event.get_group_id() or "")
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        what = "歌" if p.get("media") == "audio" else "视频"
        who = self._address(sender) or str(event.get_sender_name() or "") or "别人"
        place = f"在群里看{who}发的{what}" if group else f"看{who}发来的{what}"
        async with self._lock:
            mood = self.mood_now(now)
            cap = self._sec("mood", "turn_cap", 0.25)
            for m in (p.get("moments") or [])[:6]:
                if isinstance(m, dict) and m.get("emo") in heart.EMOTIONS:
                    mood = heart.push(mood, m["emo"], max(0, min(3, int(m.get("strength") or 0))), 0.4, cap)
            mood["t"] = now
            self._state["mood"] = mood
        v = {k: p.get(k) or "" for k in ("emotion", "cause", "voice", "about", "topic", "kind", "genre")}
        v["kind"] = v["kind"] if v["kind"] in taste.KINDS else ""
        v["intensity"] = p.get("intensity") or 0
        try:
            event.set_extra(FELT_KEY, True)
        except Exception:  # noqa: BLE001
            pass
        out = await self.feel_moment(v, place=place, chat=("g" + group) if group else ("p" + sender), umo=umo,
                                     who=who, said=str(p.get("title") or "")[:80], now=now)
        self.log.info(f"kaju_heart: {place}{('《' + str(p.get('title')) + '》') if p.get('title') else ''}"
                      f" → {out['emotion']}{out['intensity']} {out.get('cause', '')}")
        return out

    async def feel_moment(self, v: dict, *, place: str, chat: str, umo: str = "", who: str = "", said: str = "",
                          tag: dict | None = None, now: float | None = None) -> dict:
        """看的、读的东西里心里有了一下（已经判断好了，不再问模型）：进心情、明显的进余韵、喜好账本记一笔，
        有心声就写成【佳树心里】存进那个聊天的长期记忆。不改任何人的好感、不算关系信号。
        v: {emotion, intensity, cause, voice, about, topic, kind, genre}。kaju_learn 一段段读书时每段调一次。"""
        now = now or time.time()
        if v.get("emotion") not in heart.EMOTIONS:
            v["emotion"] = "平静"
        v["intensity"] = max(0, min(3, int(v.get("intensity") or 0)))
        v.setdefault("hash", "")
        if not self._cfg("enable", True):
            return v
        async with self._lock:
            self._tidy(now)
            if (self._at("enable", True) and v["intensity"] >= self._at("min_intensity", 2)
                    and v["emotion"] in heart.CONTENT_EMOTIONS):
                self._new_thread("", place, umo, v, {"chat": chat, "said": said or str(v.get("cause", ""))[:80]},
                                 now, kind="content")
            mood = heart.push(self.mood_now(now), v["emotion"], v["intensity"], 1.0,
                              self._sec("mood", "turn_cap", 0.25))
            mood["t"] = now
            self._state["mood"] = mood
            if v["intensity"] > 0 and v["emotion"] != "平静":
                self._state["events"].append({"t": now, "emo": v["emotion"], "i": v["intensity"],
                                              "cause": v.get("cause", ""), "who": "", "umo": umo, "src": "content"})
                self._state["events"] = self._state["events"][-MAX_EVENTS:]
            if self._ts("enable", True) and (v.get("topic") or v.get("genre")):
                for layer, tname, st in taste.add(
                        self._state["tastes"], topic=v.get("topic", ""), kind=v.get("kind", ""),
                        genre=v.get("genre", ""), emotion=v["emotion"], intensity=v["intensity"], now=now,
                        day=self._day(now), why=v.get("cause", ""), who=who or "自己看的"):
                    self.log.info(f"kaju_heart: 喜好长出来了：{tname}（{layer}）→ {st or '淡了'}")
                self._state["tastes"] = self._state["tastes"][-200:]
            self._save()
        if v.get("voice") and self._in("enable", True):
            # 心声跟那个聊天的记忆放在一起（自己刷B站算和兄长大人的私聊）：聊起来时想得起来
            last = next((e for e in reversed(self._state["inner_log"]) if e.get("chat") == chat), {})
            group = chat[1:] if chat.startswith("g") else ""
            entry = {"t": now, "chat": chat, "t0": now, "t1": now, "n": 1,
                     "text": inner.compose(inner.when_words(now, self._tz()), place, v["voice"], v.get("about", "")),
                     "emos": [v["emotion"]] if v["emotion"] != "平静" else [], "umo": umo or last.get("umo", ""),
                     "group": group, "session": last.get("session") or chat[1:], "scope": last.get("scope", ""),
                     "people": [], "names": [], **(tag or {})}
            entry["hash"] = await self._ingest(entry) if self._in("store_memorix", True) else ""
            if not entry["hash"] and self._in("store_memorix", True):
                entry["tries"] = 1
            async with self._lock:
                self._state["inner_log"] = (self._state["inner_log"] + [entry])[-MAX_INNER_LOG:]
                self._save()
            v["hash"] = entry["hash"]
            self.log.info(f"kaju_heart: 心里记下（{place}，memorix {entry['hash'][:8] or '没存上'}）{entry['text']}")
        return v

    # ------------------------------------------------------------ 心里记下的（inner.py）
    def _in(self, key: str, default):
        return self._sec("inner", key, default)

    def _memorix(self):
        for s in self.body.stars() or []:
            if getattr(s, "name", "") == MEMORIX and getattr(s, "star_cls", None) is not None:
                return s.star_cls
        return None

    def _memorix_place(self, event: Turn) -> dict:
        """这一轮属于 memorix 的哪个会话、哪个记忆范围（和 memorix 自己的聊天总结放在一起）。"""
        umo = str(event.unified_msg_origin or "")
        session = str(getattr(getattr(event, "message_obj", None), "session_id", "") or "") or umo.split(":")[-1]
        scope = ""
        mx = self._memorix()
        if mx is not None and hasattr(mx, "_resolve_scope"):
            try:
                scope = str(mx._resolve_scope(event) or "")
            except Exception:  # noqa: BLE001
                scope = ""
        grp = getattr(getattr(event, "message_obj", None), "group", None)
        return {"session": session, "scope": scope or str(self._in("scope_key", "aiocqhttp")),
                "gname": str(getattr(grp, "group_name", "") or "")}

    def _label(self, qq: str, name: str = "") -> str:
        """写心里话时怎么叫这个人：兄长大人本人叫"兄长大人"，别人用特别设过的称呼（女王大人……），否则用昵称。"""
        if qq == self.owner:
            return "兄长大人"
        addr = self._address(qq)
        if addr and addr != "兄长大人":
            return addr
        return name or (self._state["people"].get(qq) or {}).get("name") or qq

    def _group_name(self, gid: str, fallback: str = "") -> str:
        if fallback:
            return fallback
        try:
            with open(os.path.join(paths.self_dir("kaju_life"), "names.json"), encoding="utf-8") as f:
                name = str((json.load(f).get("groups") or {}).get(gid) or "")
            return "" if name == gid else name
        except (OSError, ValueError, AttributeError):
            return ""

    def _remember_turn(self, job: dict, v: dict | None) -> None:
        """攒下这一轮：她的感受（判断结果）+ 回复前在想什么（caller holds the lock）。"""
        chat = job["chat"]
        seg = self._state["inner"].get(chat)
        if seg is None:
            seg = self._state["inner"][chat] = {"umo": job["umo"], "group": job["group"], "turns": []}
        seg.update({k: job[k] for k in ("session", "scope", "gname") if job.get(k)})
        t = float(job.get("t") or time.time())
        turn = {"t": t, "hm": dt.datetime.fromtimestamp(t, self._tz()).strftime("%H:%M"),
                "who": job["sender"], "name": job["name"], "said": job["said"][:200], "reply": job["reply"][:300],
                "think": job.get("think", "")}
        if v:
            turn.update({"emo": v.get("emotion", ""), "i": int(v.get("intensity") or 0), "cause": v.get("cause", ""),
                         "src": v.get("source", "person")})
        seg["turns"].append(turn)
        seg["turns"] = seg["turns"][-60:]  # 后台一直没写成（比如模型坏了）也不会无限长

    async def _inner_loop(self) -> None:
        await asyncio.sleep(self._in("first_delay_seconds", 120.0))
        while True:
            try:
                if self._rl("enable", True):
                    async with self._lock:
                        self.scan_presence()  # 没人找她时也知道谁来过、兄长大人多久没来了
                        self._save()
                await self.write_inner()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_heart: 记心里话出错 {exc}")
            await asyncio.sleep(max(60.0, self._in("interval_minutes", 5.0) * 60))

    async def write_inner(self, force: bool = False, now: float | None = None) -> list[dict]:
        """安静下来的聊天（或攒够一批的）：把她这几轮的感受和想法写成一段心里话，存进 memorix。"""
        if not self._cfg("enable", True) or not self._in("enable", True):
            return []
        now = now or time.time()
        settle = self._in("settle_minutes", 10.0) * 60
        max_turns = max(2, self._in("max_turns", 12))
        await self._retry_pending()
        async with self._lock:
            jobs = [(chat, {**seg, "turns": list(seg["turns"][:max_turns])})
                    for chat, seg in self._state["inner"].items()
                    if seg.get("turns") and (force or inner.due(seg, now, settle, max_turns))][:4]
        written = []
        for chat, seg in jobs:
            n = len(seg["turns"])
            try:
                entry = await self._write_one(chat, seg, now)
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_heart: 写心里话失败（{chat}）: {exc}")
                async with self._lock:
                    cur = self._state["inner"].get(chat)
                    if cur is not None:
                        cur["fails"] = int(cur.get("fails", 0)) + 1
                        if cur["fails"] >= 3:  # 连着失败 3 次：这几轮不记了
                            del cur["turns"][:n]
                            cur["fails"] = 0
                            if not cur["turns"]:
                                self._state["inner"].pop(chat, None)
                    self._save()
                continue
            async with self._lock:
                cur = self._state["inner"].get(chat)
                if cur is not None:
                    del cur["turns"][:n]
                    cur.pop("fails", None)
                    if not cur["turns"]:
                        self._state["inner"].pop(chat, None)
                # 这几轮看过了（记下或者不值得记）：下一段只把它们当背景
                last = self._state["inner_last"].get(chat) or {}
                self._state["inner_last"][chat] = {"t1": float(seg["turns"][-1]["t"]),
                                                   "text": entry["text"] if entry else last.get("text", "")}
                if entry:
                    self._state["inner_log"] = (self._state["inner_log"] + [entry])[-MAX_INNER_LOG:]
                    written.append(entry)
                self._save()
        for e in written:
            self.log.info(f"kaju_heart: 心里记下（{e['chat']}，{e['n']} 轮，memorix {e.get('hash', '')[:8] or '没存上'}）{e['text']}")
        return written

    async def _write_one(self, chat: str, seg: dict, now: float) -> dict | None:
        turns = seg["turns"]
        if not inner.worth(turns):
            self.log.info(f"kaju_heart: {chat} 这 {len(turns)} 轮是寻常寒暄，不记心里话")
            return None
        tz = self._tz()
        t0, t1 = float(turns[0]["t"]), float(turns[-1]["t"])
        labels = {str(t["who"]): self._label(str(t["who"]), t.get("name", "")) for t in turns}
        log_dir = os.path.join(paths.self_dir("kaju_life"), "log")
        people = set(labels) | {"self"}
        start = t0 - self._in("context_minutes", 10.0) * 60
        # 上一段已经写过的：只作背景，免得同一件事记两遍
        last = (self._state.get("inner_last") or {}).get(chat) or {}
        last_t1 = float(last.get("t1") or 0)
        before: list[str] = []
        if last_t1 > start:
            before = afterthought.log_lines(log_dir, tz, {chat}, start, last_t1, people=people, names=labels,
                                            limit=8, per_line=80)
            start = last_t1 + 1
        prev = str(last.get("text") or "") if last_t1 and t0 - last_t1 < 3 * 3600 else ""
        lines = afterthought.log_lines(
            log_dir, tz, {chat}, start, t1 + 90,
            people=people, names=labels, limit=self._in("context_lines", 30), per_line=120)
        group = str(seg.get("group") or "")
        first = str(turns[0]["who"])
        when = inner.when_words(t0, tz)
        place = inner.place_words(group, self._group_name(group, seg.get("gname", "")) if group else "",
                                  labels.get(first, "对方"))
        hi = int(self._in("max_chars", 80))
        if len(turns) >= 8:
            hi = int(hi * 1.3)
        raw = await self._ask(inner.system_prompt(hi=hi),
                              inner.build_prompt(when=when, place=place, lines=lines, turns=turns, names=labels,
                                                 before=before, prev=prev))
        r = inner.parse(raw, hi)
        if r is None:
            raise ValueError("模型没按 JSON 回")
        if r["skip"]:
            self.log.info(f"kaju_heart: {chat} 这 {len(turns)} 轮她心里没什么波澜，不记")
            return None
        text = inner.compose(when, place, r["memory"], r.get("about", ""))
        entry = {"t": now, "chat": chat, "t0": t0, "t1": t1, "n": len(turns), "text": text,
                 "emos": [t["emo"] for t in turns if t.get("emo") and t["emo"] != "平静"][:8],
                 "umo": seg.get("umo", ""), "group": group, "session": seg.get("session", ""),
                 "scope": seg.get("scope", ""), "people": sorted(labels), "names": sorted(set(labels.values()))}
        entry["hash"] = await self._ingest(entry) if self._in("store_memorix", True) else ""
        if not entry["hash"] and self._in("store_memorix", True):
            entry["tries"] = 1
        return entry

    async def _ingest(self, e: dict) -> str:
        """存进 memorix：来源 chat_summary:<会话>，跟这个聊天的总结放在一起（只在这个聊天里被检索到）。"""
        mx = self._memorix()
        svc = getattr(mx, "ingest_service", None) if mx is not None else None
        if svc is None:
            self.log.info("kaju_heart: memorix 没加载，心里话先留在这里，下次再存")
            return ""
        group = e.get("group", "")
        session = e.get("session") or group or e["chat"][1:]
        try:
            res = await svc.ingest_summary(
                scope_key=e.get("scope") or str(self._in("scope_key", "aiocqhttp")),
                external_id=f"kaju_inner:{e['chat']}:{int(e['t0'])}",
                chat_id=session, text=e["text"], participants=["佳树", *e.get("names", [])],
                time_start=e["t0"], time_end=e["t1"], tags=["佳树的心里话", *e.get("emos", [])[:4]],
                metadata={"kind": "inner_voice", "writer": PLUGIN_NAME, "unified_msg_origin": e.get("umo", ""),
                          "group_id": group, "people_qq": e.get("people", [])},
                respect_filter=True, user_id="" if group else e["chat"][1:], group_id=group,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 心里话存进 memorix 失败: {exc}")
            return ""
        ids = (res or {}).get("stored_ids") or []
        if not ids:
            self.log.info(f"kaju_heart: memorix 没收这段心里话（{(res or {}).get('detail') or (res or {}).get('reason') or res}）")
            return "-"  # 这个聊天被 memorix 过滤掉了：不再重试
        return str(ids[0])

    async def _retry_pending(self) -> None:
        todo = [e for e in self._state["inner_log"] if not e.get("hash") and 0 < int(e.get("tries", 0)) < 4]
        for e in todo:
            h = await self._ingest(e)
            async with self._lock:
                e["tries"] = int(e.get("tries", 0)) + 1
                if h:
                    e["hash"] = h
                    e.pop("tries", None)
                self._save()

    # ------------------------------------------------------------ commands
    def _describe(self, qq: str, show_number: bool) -> str:
        p = self._state["people"].get(qq)
        name = (p or {}).get("name") or self._address(qq) or qq
        a = self.affection(qq)
        if qq == self.owner:
            head = f"佳树对{name}：最依赖的人，永远排第一"
        else:
            head = f"佳树对{name}的感觉：{heart.level(a)}"
        if show_number:
            head += f"（{a:.0f}/100）"
        lines = [head]
        now = time.time()
        rel = self._rel(qq, p, now)
        words = relation.describe(rel, qq == self.owner, self._rel_why(p, now),
                                  relation.bands(rel, qq == self.owner, (p or {}).get("rbands"), self._rl("hysteresis", relation.HYSTERESIS)))
        if words:
            lines.append("· " + "；".join(words))
        if show_number:
            lines.append(f"· 信任 {rel['trust']:.2f} / 在意 {rel['care']:.2f} / 边界 {rel['bound']:.2f}")
        pres = self._state["presence"].get(qq) or {}
        if pres.get("last"):
            lines.append(f"· 平时隔 {relation.hours_words(relation.expected_gap_h(pres))}内会来，"
                         f"上次 {_ago(now - float(pres['last']))}")
        for item in (p or {}).get("log", [])[-3:][::-1]:
            if item.get("why"):
                arrow = "↑" if item["d"] > 0 else "↓"
                lines.append(f"· {_ago(now - item['t'])}：{item['why']} {arrow}")
        for item in (p or {}).get("rlog", [])[-3:][::-1]:
            lines.append(f"· {_ago(now - item['t'])}：{'、'.join(item.get('s', []))}——{item.get('why', '')}")
        return "\n".join(lines)

    async def cmd_affection(self, event: Turn, action: str = "", arg: str = "", value: str = ""):
        """看佳树对你（或别人）的感觉"""
        sender = str(event.get_sender_id() or "")
        admin = event.is_admin()
        action = action.strip()
        self_id = str(event.get_self_id() or "")
        target = next((str(c.qq) for c in event.get_messages() if type(c).__name__ == "At" and str(c.qq) != self_id), "")  # @ 了谁
        if action == "全部":
            if not admin:
                return
            rows = sorted(self._state["people"].items(), key=lambda kv: -self.affection(kv[0]))
            out = [f"{p.get('name') or qq}({qq})：{heart.level(self.affection(qq))} {self.affection(qq):.1f}"
                   f"，聊过 {p.get('n', 0)} 轮" for qq, p in rows[:40]]
            yield event.plain_result("\n".join(out) or "还没有记录")
            return
        if action == "设":
            if not admin:
                return
            # /好感度 设 @某人 80  或  /好感度 设 QQ号 80
            qq, raw = (target, arg) if target else (arg.strip(), value)
            try:
                val = float(raw)
            except ValueError:
                qq, val = "", 0.0
            if not qq.isdigit():
                yield event.plain_result("用法：/好感度 设 QQ号 数值(0~100)")
                return
            async with self._lock:
                p = self._person(qq)
                p["a"], p["t"] = heart.clamp(val, 0.0, 100.0), time.time()
                self._save()
            yield event.plain_result(self._describe(qq, True))
            return
        if not target and action.isdigit():
            target = action
        if target and target != sender and not admin:
            yield event.plain_result("别人的佳树可不告诉你～")
            return
        yield event.plain_result(self._describe(target or sender, admin or self._cfg("show_number", True)))

    async def cmd_mood(self, event: Turn, action: str = "", arg: str = ""):
        """查看佳树此刻的心情和心事（重置｜回想｜放下 编号｜心里话｜记下｜喜好｜忘掉喜好 名字）"""
        action = action.strip()
        if action == "喜好":
            now = time.time()
            rows = sorted(self._state["tastes"], key=lambda e: -abs(taste.decayed(float(e["score"]), float(e["t"]), now)))
            out = [f"· [{e['layer']}] {taste.label(e)}：{taste.stage(e, now) or '还没成形'} "
                   f"{taste.decayed(float(e['score']), float(e['t']), now):+.2f}（好{e.get('pos', 0)} 坏{e.get('neg', 0)}，"
                   f"{len(e.get('days', []))} 天）" for e in rows[:20]]
            yield event.plain_result("喜好账本（/佳树心情 忘掉喜好 名字）\n" + ("\n".join(out) or "还没有"))
            return
        if action == "忘掉喜好":
            async with self._lock:
                before = len(self._state["tastes"])
                self._state["tastes"] = [e for e in self._state["tastes"] if e["name"].strip("《》") != arg.strip().strip("《》")]
                self._save()
            yield event.plain_result("好，忘掉了" if len(self._state["tastes"]) < before else "没找到这个名字")
            return
        if action == "记下":
            out = await self.write_inner(force=True)
            yield event.plain_result("记下了：\n" + "\n".join(e["text"] for e in out) if out
                                     else "现在没有要记的（或者都是寻常寒暄）")
            return
        if action == "心里话":
            now = time.time()
            lines = []
            for e in self._state["inner_log"][-6:][::-1]:
                where = "没存上" if not e.get("hash") else ("memorix 没收" if e["hash"] == "-" else "")
                lines.append(f"· {_ago(now - e['t'])}（{e['chat']}，{e['n']} 轮{('，' + where) if where else ''}）{e['text']}")
            waiting = {c: len(s.get("turns") or []) for c, s in self._state["inner"].items() if s.get("turns")}
            if waiting:
                lines.append("还没写的：" + "、".join(f"{c} {n} 轮" for c, n in waiting.items()))
            yield event.plain_result("\n".join(lines) or "还没记下过心里话")
            return
        if action == "重置":
            async with self._lock:
                self._state["mood"], self._state["events"], self._state["threads"] = {}, [], []
                self._save()
            yield event.plain_result("心情已经回到平常的样子了，心事也都放下了")
            return
        if action == "放下":
            async with self._lock:
                th = next((x for x in self._open_threads(None) if x["id"] == arg.strip()), None)
                if th is not None:
                    self._resolve(th, time.time(), why="管理员让她放下")
                    self._save()
            yield event.plain_result(f"好，{arg.strip()} 放下了" if th else "用法：/佳树心情 放下 编号（编号在 /佳树心情 里看）")
            return
        if action == "回想":
            out = await self.reflect(force=True)
            yield event.plain_result("回想完了：\n" + "\n".join(out) if out else "现在心里没有压着的事")
            return
        now = time.time()
        m = self.mood_now(now)
        nums = " ".join(f"{k}={m[k]:.2f}" for k in heart.DIMS)
        deep = self._state["deep"]
        owner_pres = self._state["presence"].get(self.owner) or {}
        lines = ["佳树此刻：" + "、".join(heart.mood_words(m, self._hour(now))), nums,
                 f"群聊插话倍数 ×{self.chime_factor():.2f}",
                 f"沉淀下来的：怕被丢下 {float(deep.get('absence', 0)):.2f}，戒心 {float(deep.get('guard', 0)):.2f}"
                 + (f"；兄长大人上次 {_ago(now - float(owner_pres['last']))}，是平时的 {self._owner_overdue(now):.1f} 倍"
                    if owner_pres.get("last") else "")]
        for ev in self._state["events"][-5:][::-1]:
            lines.append(f"· {_ago(now - ev['t'])} {ev['emo']}{ev['i']}：{ev.get('cause', '')}")
        threads = [th for th in self._state["threads"] if th.get("status") == "open" or now - th.get("t", 0) < 86400]
        if threads:
            lines.append("心事：")
        for th in threads[-8:]:
            state = ("还在回味" if th.get("kind") == "content" else "还挂着") if th["status"] == "open" else "已放下"
            s = (f"· {th['id']} {state} {th['emo']} {heart.thread_charge(th, now):.1f}"
                 f"（{self._when(float(th['t0']), now)}，{th.get('name') or th['who']}）：{th['cause']}")
            if th.get("thought"):
                s += f"\n   心里想：{th['thought']}" + (f"（{th['want']}）" if th.get("want") else "")
            lines.append(s)
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------ 回想
    async def _reflect_loop(self) -> None:
        await asyncio.sleep(self._at("first_delay_seconds", 90.0))
        try:
            await self.seed_tastes()
        except Exception as exc:  # noqa: BLE001
            self.log.info(f"kaju_heart: 补喜好出错 {exc}")
        while True:
            try:
                await self.reflect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"kaju_heart: 回想出错 {exc}")
            await asyncio.sleep(max(60.0, self._at("interval_minutes", 20.0) * 60))

    def _due(self, th: dict, now: float) -> bool:
        """该回想了：离上次（或事发）过了 reflect_hours，或者睡了一觉（换了一天，且至少隔半小时）。"""
        last = float(th.get("rt") or th["t0"])
        if now - last >= self._at("reflect_hours", 4.0) * 3600:
            return True
        return self._day(last) != self._day(now) and now - last >= 1800

    async def reflect(self, force: bool = False, now: float | None = None) -> list[str]:
        """把心里压着的事重新想一遍：结合之后真实发生的聊天，决定越想越气、平复、后悔还是放下。"""
        if not self._cfg("enable", True) or not self._at("enable", True):
            return []
        now = now or time.time()
        async with self._lock:
            self._tidy(now)
            due = [th for th in self._open_threads() if force or self._due(th, now)][:6]
        if not due:
            return []
        log_dir = os.path.join(paths.self_dir("kaju_life"), "log")
        names = {qq: p.get("name", "") for qq, p in self._state["people"].items()}
        items = []
        for th in due:
            after = afterthought.log_lines(
                log_dir, self._tz(), {th.get("chat", ""), "p" + th["who"]}, float(th["t0"]) + 60, now,
                people={th["who"], "self"}, names=names,
            )
            items.append({
                "id": th["id"], "cause": th["cause"], "said": th.get("said", ""), "reply": th.get("reply", ""),
                "first_emo": th.get("emo0", th["emo"]), "first_charge": float(th.get("c0", th["c"])),
                "emo": th["emo"], "charge": heart.thread_charge(th, now), "age_s": now - float(th["t0"]),
                "slept": self._day(float(th.get("rt") or th["t0"])) != self._day(now),
                "thought": th.get("thought", ""), "want": th.get("want", ""), "after": "\n".join(after),
            })
        now_text = dt.datetime.fromtimestamp(now, self._tz()).strftime("%m月%d日 %H:%M")
        try:
            results = {r["id"]: r for r in afterthought.parse(
                await self._ask(afterthought.system_prompt(), afterthought.build_prompt(now_text, items)))}
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"kaju_heart: 回想失败 {exc}")
            return []
        out = []
        async with self._lock:
            step = self._at("max_step", 1.2)
            for th in due:
                th["rt"] = now
                r = results.get(th["id"])
                if r is None or th.get("status") != "open":
                    continue
                cur = heart.thread_charge(th, now)
                new = heart.clamp(r["charge"], cur - step, cur + step)  # 单次回想最多变一档多
                emo = r["emotion"] or th["emo"]
                if emo != th["emo"] or r["want"] != th.get("want"):
                    th["nudges"] = 0  # 想法变了（比如刚转成后悔），重新可以提醒
                th["thought"], th["want"] = r["thought"], r["want"]
                if r["resolved"] or emo in CALM or emo not in heart.THREAD_EMOTIONS or new < 0.25:
                    heart.set_charge(th, new, now)
                    self._resolve(th, now, emo if emo in CALM else None, why=r["thought"])
                else:
                    if new - cur >= 0.5:  # 越想越……：心情也跟着沉一下
                        self._state["mood"] = {**heart.push(self.mood_now(now), emo, 1), "t": now}
                    th["emo"] = emo
                    heart.set_charge(th, new, now)
                    self._hist(th, now, r["thought"])
                out.append(f"{th['id']} {th['cause'][:18]}：{cur:.1f}→{heart.thread_charge(th, now):.1f} "
                           f"{th['emo']}（{'还挂着' if th['status'] == 'open' else '放下了'}）{r['thought']}")
            self._save()
        for line in out:
            self.log.info(f"kaju_heart 回想: {line}")
        return out

    async def terminate(self):
        parts.unregister(PLUGIN_NAME.removeprefix("astrbot_plugin_"), self)
        if self._loop_task is not None:
            self._loop_task.cancel()
        if self._inner_task is not None:
            self._inner_task.cancel()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
