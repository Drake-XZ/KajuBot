"""记忆星海：把佳树记得的东西画成一片能转的 3D 星海（控制台「记忆星海」按钮用它，也能单独跑）。只用标准库。

每颗星都是一条真的记忆：
    兄长大人 / 佳树 / 群友说过的每一句话   kaju_life 的聊天记录 log\\日期.jsonl
    长期记忆（聊天总结、人物事实）          memorix 的 metadata.db（只读打开，不会改它）
    她心里想的（当时的感受和想法）          memorix 里 kaju_heart 写的、以【佳树心里】开头的那些
    星团的名字                              memorix 的记忆片段（episodes 表，模型起的标题）
    日记 / 周记 / 月记                      kaju_life 的 index.json
    此刻记着的事                            memory_weight 的 working_notes.json（工作记忆）
    关于自己（她是谁的细节，2026-11-07 起）  kaju_life 的 self_facts.json
    她知道的东西（知识本，2026-11-05 起）    kaju_learn 的 book.json（每张卡一颗星，越熟越大）
网页聊天（webchat，测试用的）一律不算。

画法：每个聊天（和兄长大人的私聊、每个群）是星系的一条旋臂，离中心越远越新；
     中心是她心里的东西：对人的了解、关于自己、她知道的、日记、此刻记着的事。
星和星之间的线：前后句、长期记忆和它总结的那几句、人物事实和它的出处、说到同一件事的话。

用法:
    python memsea.py build [--open] [--html 输出.html] [--data-dir core\\data] [--out 结果.json]
生成一个单文件网页（数据都在里面，离线能看）。默认写到 bot_setup\\memsea\\out\\memory-sea.html。
结果 {"ok": true, "path": ..., "counts": {...}, "warnings": [...]}；出错 {"ok": false, "error": ...}。
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SETUP = Path(__file__).resolve().parent.parent
DATA = Path(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data")
TEMPLATE = SETUP / "memsea" / "template.html"
OUT_HTML = SETUP / "memsea" / "out" / "memory-sea.html"

SELF_NAME = "佳树"
OWNER_TITLE = "兄长大人"
DEFAULT_OWNER = os.environ.get("KAJU_OWNER_QQ", "").strip()  # 兜底；兄长正式登记在 kaju_data\self\people\people.json
MEMORIX_SCOPE = "aiocqhttp"  # memorix 是 platform_global 模式，QQ 的记忆都在这一个 scope 里

CHAT_RE = re.compile(r"[pg]\d+")  # p<QQ> 私聊 / g<群号> 群聊；pastrbot 之类的网页聊天不要
ATTACH_RE = re.compile(r"\[File Attachment:[^\]]*\]?")
TOKEN_RE = re.compile(r"\[[^\[\]\n]{1,12}\]")  # [图片] [惊讶] [星星] 这类占位符和 QQ 小表情
AT_RE = re.compile(r"@([^\s@()（）]{1,24})[(（]\d{5,}[)）]")  # @来点作用吧(333333333) → @来点作用吧
CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]*|\d{3,}")

# 到处都有、连不出意思的字对
STOP_BIGRAMS = set("""
佳树 兄长 长大 大人 一下 这个 那个 什么 我们 你们 他们 就是 还是 不是 没有 可以 现在 今天 一个 知道 觉得
自己 真的 怎么 这样 这么 那么 然后 因为 所以 但是 如果 已经 还有 的话 时候 一点 有点 起来 出来 不过 一起
好的 好啊 嗯嗯 哈哈 呀兄 树也 树就 树会 树在 树的 人的 人在 人说 人要 的时 了吗 了吧 是不 不会 不能 会儿
""".split())

KIND_WEIGHT = {"owner": 1.6, "self": 1.0, "other": 0.8, "memory": 2.4, "heart": 2.4, "fact": 2.0, "diary": 3.0,
               "note": 2.2, "me": 1.8, "know": 1.6}
KNOW_LEVELS = ("听说过", "知道一些", "挺熟", "很懂")  # 和 kaju_learn 的 book.LEVELS 一致
INNER_MARK = "【佳树心里】"  # kaju_heart 写进 memorix 的心里话以它开头


# ---------------------------------------------------------------- 小工具
def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except Exception:  # noqa: BLE001
        return default


def load_tz(data_dir: Path):
    name = str(read_json(data_dir / "cmd_config.json", {}).get("timezone") or "Asia/Shanghai")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name), name
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=8)), "UTC+8"


def clean_text(text) -> str:
    text = ATTACH_RE.sub("", str(text or ""))
    text = TOKEN_RE.sub("", text)
    text = AT_RE.sub(r"@\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"pragma table_info({table})")}


def to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def tokens(text: str) -> Counter:
    c = Counter()
    for run in CJK_RE.findall(text):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in STOP_BIGRAMS:
                c[bg] += 1
    for w in WORD_RE.findall(text):
        c[w.lower()] += 1
    return c


# ---------------------------------------------------------------- 名字
class Names:
    """QQ 号 → 她嘴里的称呼。兄长大人本人固定叫「兄长大人」，别人先看称呼簿，再看昵称。"""

    def __init__(self, owner: str, pd: Path, registry: dict[str, str]):
        self.owner = owner
        self.addresses = read_json(pd / "astrbot_plugin_address_book" / "addresses.json", {})
        life = read_json(pd / "astrbot_plugin_kaju_life" / "names.json", {})
        self.people = dict(life.get("people") or {})
        self.groups = dict(life.get("groups") or {})
        self.registry = registry
        self.seen: dict[str, str] = {}  # 聊天记录里最近一次的昵称

    def nick(self, uid: str) -> str:
        uid = str(uid)
        a = self.addresses.get(uid) or {}
        return (self.seen.get(uid) or self.people.get(uid) or a.get("nickname")
                or self.registry.get(uid) or "")

    def person(self, uid: str) -> str:
        uid = str(uid)
        if uid == "self":
            return SELF_NAME
        if uid == self.owner:
            return OWNER_TITLE
        a = self.addresses.get(uid) or {}
        return a.get("address") or self.nick(uid) or uid

    def chat(self, key: str) -> str:
        if key.startswith("g"):
            name = self.groups.get(key[1:]) or key[1:]
            return name if name.endswith("群") else name + "群"
        uid = key[1:]
        return "私聊 · " + self.person(uid)


# ---------------------------------------------------------------- 读数据
def life_day(ts: float, tz, start_hour: int) -> str:
    d = datetime.fromtimestamp(ts, tz)
    if d.hour < start_hour:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def load_messages(pd: Path, tz, start_hour: int, names: Names) -> list[dict]:
    logdir = pd / "astrbot_plugin_kaju_life" / "log"
    out: list[dict] = []
    if not logdir.is_dir():
        return out
    for f in sorted(logdir.glob("*.jsonl")):
        try:
            base = datetime.strptime(f.stem, "%Y-%m-%d")
        except ValueError:
            continue
        same_min: Counter = Counter()
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
                hh, mm = (int(x) for x in str(d.get("t", "")).split(":")[:2])
            except Exception:  # noqa: BLE001
                continue
            chat = str(d.get("c", ""))
            if not CHAT_RE.fullmatch(chat):
                continue
            uid = str(d.get("u", ""))
            nick = str(d.get("n") or "")
            if nick and uid != "self":
                names.seen[uid] = nick
            text = clean_text(d.get("x"))
            if len(text) < 2:
                continue
            day = base + timedelta(days=1) if hh < start_hour else base  # 凌晨的话记在前一天的文件里
            ts = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).timestamp()
            same_min[ts] += 1
            ts += min(55, 2 * (same_min[ts] - 1))  # 同一分钟里的几句保持先后
            out.append({"chat": chat, "uid": uid, "t": ts, "x": text})
    out.sort(key=lambda m: m["t"])
    return out


def load_memorix(pd: Path, warn: list[str], now: float) -> dict:
    res = {"paragraphs": [], "episodes": [], "ep_of": {}, "entities": [], "registry": {}, "groups": set()}
    db = pd / "astrbot_plugin_memorix" / "scopes" / MEMORIX_SCOPE / "metadata" / "metadata.db"
    if not db.exists():
        warn.append("没找到长期记忆（memorix）的数据库，星海里只有聊天记录和日记")
        return res
    try:
        con = open_ro(db)
    except sqlite3.Error as exc:
        warn.append(f"长期记忆数据库打不开：{exc}")
        return res
    try:
        pc = columns(con, "paragraphs")
        where = ["1=1"]
        if "is_deleted" in pc:
            where.append("coalesce(is_deleted, 0) = 0")
        if "expires_at" in pc:
            where.append(f"(expires_at is null or expires_at > {now})")
        et = "event_time" if "event_time" in pc else "null"
        for r in con.execute(f"select hash, content, source, created_at, {et} as event_time "
                             f"from paragraphs where {' and '.join(where)} order by created_at"):
            res["paragraphs"].append(dict(r))
        if "episodes" in {r[0] for r in con.execute("select name from sqlite_master where type='table'")}:
            for r in con.execute("select episode_id, source, title, summary, event_time_start, event_time_end, "
                                 "participants_json, keywords_json from episodes"):
                res["episodes"].append(dict(r))
            for r in con.execute("select episode_id, paragraph_hash from episode_paragraphs"):
                res["ep_of"][r["paragraph_hash"]] = r["episode_id"]
        ec = columns(con, "entities")
        q = "select name from entities" + (" where coalesce(is_deleted, 0) = 0" if "is_deleted" in ec else "")
        res["entities"] = [str(r["name"]) for r in con.execute(q)]
        try:
            for r in con.execute("select user_id, person_name, nickname from person_registry"):
                if r["user_id"]:
                    res["registry"][str(r["user_id"])] = r["nickname"] or r["person_name"] or ""
        except sqlite3.Error:
            pass
        try:
            for r in con.execute("select session_id, metadata_json from transcript_sessions"):
                meta = json.loads(r["metadata_json"] or "{}")
                if meta.get("group_id"):
                    res["groups"].add(str(r["session_id"]))
        except (sqlite3.Error, ValueError):
            pass
    except sqlite3.Error as exc:
        warn.append(f"读长期记忆时出错：{exc}")
    finally:
        con.close()
    return res


def load_notes(pd: Path) -> list[dict]:
    notes = read_json(pd / "astrbot_plugin_memory_weight" / "working_notes.json", {})
    out = []
    for umo, v in (notes or {}).items():
        if "webchat" in umo or not isinstance(v, dict):
            continue
        parts = umo.split(":")
        if len(parts) < 3 or not parts[2].isdigit():
            continue
        chat = ("g" if "Group" in parts[1] else "p") + parts[2]
        text = str(v.get("note") or "").strip()
        if text:
            out.append({"chat": chat, "t": to_float(v.get("updated")) or time.time(), "x": text})
    return out


def load_self_facts(pd: Path) -> list[dict]:
    rows = read_json(pd / "astrbot_plugin_kaju_life" / "self_facts.json", [])
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and str(r.get("fact") or "").strip():
            out.append({"x": " ".join(str(r["fact"]).split()), "kind": " ".join(str(r.get("kind") or "").split())})
    return out


def know_level(card: dict) -> int:
    """照抄 kaju_learn book.familiarity / level（这里只用标准库，不导入插件）。"""
    f = (len(set(card.get("days", []))) + 0.5 * min(len(card.get("facts", [])), 8)
         + 0.3 * min(int(card.get("used", 0) or 0), 10) + (0.5 if card.get("view") else 0) + (0.5 if card.get("what") else 0))
    return 0 if f < 2 else 1 if f < 4 else 2 if f < 6.5 else 3


def load_knowledge(pd: Path) -> list[dict]:
    book = read_json(pd / "astrbot_plugin_kaju_learn" / "book.json", {})
    cards = ((book or {}).get("book") or {}).get("cards") or {}
    out = []
    for c in cards.values() if isinstance(cards, dict) else []:
        if not isinstance(c, dict) or c.get("removed") or not str(c.get("name") or "").strip():
            continue
        lines = [str(c.get("what") or "").strip()] + [str(f.get("x") or "").strip() for f in c.get("facts", [])[-6:]]
        lines = [x for x in lines if x]
        srcs = [s for s in c.get("srcs", []) if isinstance(s, dict) and CHAT_RE.fullmatch(str(s.get("chat") or ""))]
        out.append({"name": str(c["name"]).strip(), "kind": str(c.get("kind") or "").strip(), "x": "\n".join(lines) or str(c["name"]),
                    "t": to_float(c.get("t0")) or time.time(), "level": know_level(c),
                    "view": " ".join(str(c.get("view") or "").split()), "used": int(c.get("used", 0) or 0),
                    "srcs": [(str(s["chat"]), to_float(s.get("t"))) for s in srcs]})
    return out


def diary_time(kind: str, key: str, tz) -> float | None:
    try:
        if kind == "diary":
            d = datetime.strptime(key, "%Y-%m-%d").replace(hour=23, minute=30)
        elif kind == "weekly":
            d = datetime.strptime(key + "-7", "%G-W%V-%u").replace(hour=23, minute=40)
        else:
            first = datetime.strptime(key[:7], "%Y-%m")
            d = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            d = d.replace(hour=23, minute=50)
        return d.replace(tzinfo=tz).timestamp()
    except ValueError:
        return None


def load_diaries(pd: Path, tz) -> list[dict]:
    life = pd / "astrbot_plugin_kaju_life"
    idx = read_json(life / "index.json", {})
    out = []
    for kind, label in (("diary", "日记"), ("weekly", "周记"), ("monthly", "月记")):
        entries = dict(idx.get(kind) or {})
        folder = life / kind
        if folder.is_dir():  # index.json 里没有的，从 Markdown 补
            for md in folder.glob("*.md"):
                if md.stem not in entries:
                    body = md.read_text(encoding="utf-8", errors="replace")
                    body = re.sub(r"^# .*\n", "", body).split("\n## ")[0].strip()
                    entries[md.stem] = {"full": body}
        for key, e in sorted(entries.items()):
            text = str((e or {}).get("full") or "").strip()
            ts = diary_time(kind, key, tz)
            if text and ts:
                out.append({"key": key, "label": label, "t": ts, "x": text, "brief": str(e.get("brief") or "").strip()})
    return out


# ---------------------------------------------------------------- 分量（记忆轻重）
# 和 plugins\memory_weight\weigh.py 同一套：分量 0~3，没用过时的半衰期（天），每用上一次翻倍（最多 ×32）
GRAVITY_NAMES = {0: "琐碎闲聊", 1: "一般", 2: "要紧", 3: "郑重"}
DEFAULT_HALF_LIFE = {0: 4.0, 1: 15.0, 2: 90.0, 3: 365.0}


def retention(item: dict, now: float, table: dict) -> float:
    """0~1：现在还记得多清楚（遗忘曲线，从最后一次用上算起；没用过就从记下的时候算）。"""
    g = int(item.get("g") or 0)
    hl = table.get(g, DEFAULT_HALF_LIFE[1]) * min(2 ** max(0, int(item.get("uses") or 0)), 32)
    anchor = to_float(item.get("last_used")) or to_float(item.get("created")) or now
    return 2.0 ** (-max(0.0, now - anchor) / 86400.0 / max(0.01, hl))


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def apply_weights(points: list[dict], msg_pid: list[int], pd: Path, cfg: Path, now: float, warn: list[str]) -> int:
    """把记忆轻重插件的打分写到星上：g（分量 0~3）、ret（还记得多清楚）、uses（用上几次）、keep（铭记的内容）。
    返回打上分量的星数；插件没装 / 还没打过分就是 0，星图照旧。"""
    state = read_json(pd / "astrbot_plugin_memory_weight" / "state.json", None)
    if not isinstance(state, dict):
        return 0
    hl_cfg = read_json(cfg / "astrbot_plugin_memory_weight_config.json", {}).get("half_life_days") or {}
    table = dict(DEFAULT_HALF_LIFE)
    for g in table:
        try:
            table[g] = float(hl_cfg.get(f"g{g}", table[g]))
        except (TypeError, ValueError):
            pass
    n = 0
    by_hash = {p["hash"]: p for p in points if p.get("hash")}
    for h, item in (state.get("paras") or {}).items():
        p = by_hash.get(h)
        if p is None or not isinstance(item, dict) or item.get("g") is None:
            continue
        p["g"] = int(item["g"])
        p["ret"] = round(retention(item, now, table), 3)
        p["uses"] = int(item.get("uses") or 0)
        n += 1
    # 铭记在心：找那个人在那个聊天里、那个时间附近说的、最像引文的那句
    for ks in state.get("keepsakes") or []:
        if not isinstance(ks, dict) or ks.get("removed") or not ks.get("quote"):
            continue
        quote, created = str(ks["quote"]), to_float(ks.get("created")) or 0
        qb = _bigrams(quote)
        best, score = None, 0.0
        for i in msg_pid:
            p = points[i]
            if p.get("uid") != str(ks.get("qq")) or (ks.get("chat") and p.get("chat") != ks["chat"]):
                continue
            if abs(p["t"] - created) > 15 * 60:
                continue
            tb = _bigrams(p["text"])
            s = 1.0 if quote in p["text"] or (len(p["text"]) >= 6 and p["text"] in quote) else \
                len(qb & tb) / max(1, min(len(qb), len(tb)))
            s -= abs(p["t"] - created) / 1e5
            if s > score:
                best, score = p, s
        if best is None or score < 0.5:
            warn.append(f"铭记的话没在聊天记录里找到原句：「{quote[:20]}」")
            continue
        g = int(ks.get("g") or 2)
        if best.get("g") is None or g >= best["g"]:
            if best.get("g") is None:
                n += 1
            best["g"] = g
            best["ret"] = round(retention(ks, now, table), 3)
            best["uses"] = int(ks.get("uses") or 0)
            best["keep"] = {"memory": str(ks.get("memory") or ""), "said": int(ks.get("said") or 1),
                            "retired": bool(ks.get("retired"))}
    return n


# ---------------------------------------------------------------- 组装
def part_of_day(h: int) -> str:
    for end, name in ((5, "凌晨"), (8, "清晨"), (11, "上午"), (13, "中午"), (17, "下午"), (19, "傍晚"), (24, "晚上")):
        if h < end:
            return name
    return "晚上"


def build_scene(data_dir: Path = DATA, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    warn: list[str] = []
    tz, tz_name = load_tz(data_dir)
    pd = data_dir / "plugin_data"
    cfg = data_dir / "config"
    try:
        start_hour = int(read_json(cfg / "astrbot_plugin_kaju_life_config.json", {}).get("day_start_hour", 5))
    except (TypeError, ValueError):
        start_hour = 5
    owner = ""
    if data_dir == DATA:  # 兄长是谁以身份表为准（kaju_core.people）；拿数据副本测试时没有身份表，用老配置
        kaju = Path(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data")
        owner = str(read_json(kaju / "self" / "people" / "people.json", {}).get("owner") or "").strip()
    owner = owner or str(read_json(cfg / "astrbot_plugin_address_book_config.json", {}).get("owner_qq") or DEFAULT_OWNER).strip()

    mx = load_memorix(pd, warn, now)
    names = Names(owner, pd, mx["registry"])
    msgs = load_messages(pd, tz, start_hour, names)
    notes = load_notes(pd)
    diaries = load_diaries(pd, tz)
    self_facts = load_self_facts(pd)
    knowledge = load_knowledge(pd)
    if not msgs:
        warn.append("没找到聊天记录（kaju_life 的 log 文件夹）")

    def chat_of(chat_id: str) -> str:
        if f"g{chat_id}" in chat_set or chat_id in mx["groups"] or chat_id in names.groups:
            return "g" + chat_id
        return "p" + chat_id

    chat_set = {m["chat"] for m in msgs}

    clusters: list[dict] = []
    cindex: dict[str, int] = {}

    def cluster(cid: str, **kw) -> int:
        if cid not in cindex:
            cindex[cid] = len(clusters)
            clusters.append({"id": cid, **kw})
        return cindex[cid]

    # 记忆片段 → 星团（只要聊天总结那种；人物事实另放中心）
    episodes = {}
    for e in mx["episodes"]:
        src = str(e.get("source") or "")
        if not src.startswith("chat_summary:"):
            continue
        chat = chat_of(src.split(":", 1)[1])
        t0, t1 = to_float(e.get("event_time_start")), to_float(e.get("event_time_end"))
        if t0 is None or t1 is None:
            continue
        try:
            kws = [str(k) for k in json.loads(e.get("keywords_json") or "[]")]
        except ValueError:
            kws = []
        try:
            who = [str(k) for k in json.loads(e.get("participants_json") or "[]")]
        except ValueError:
            who = []
        episodes[e["episode_id"]] = {"chat": chat, "t0": t0, "t1": t1, "title": str(e.get("title") or "").strip(),
                                     "summary": str(e.get("summary") or "").strip(), "keywords": kws, "who": who}
    for eid, e in sorted(episodes.items(), key=lambda kv: kv[1]["t0"]):
        e["ci"] = cluster("e:" + eid[:16], label=e["title"] or "一段对话", kind="episode", chat=e["chat"],
                          summary=e["summary"], keywords=e["keywords"][:8], people=e["who"][:10])
        clusters[e["ci"]]["_t"] = (e["t0"], e["t1"])  # 只在组装时用，最后删掉

    def nearest(chat: str, t: float, within: float = 9e18) -> int | None:
        """同一个聊天里时间最近的星团。"""
        best, gap = None, within
        for i, c in enumerate(clusters):
            if c.get("chat") == chat and "_t" in c:
                g = 0.0 if c["_t"][0] <= t <= c["_t"][1] else min(abs(t - c["_t"][0]), abs(t - c["_t"][1]))
                if g < gap:
                    best, gap = i, g
        return best

    by_chat: dict[str, list[dict]] = defaultdict(list)
    for e in episodes.values():
        by_chat[e["chat"]].append(e)

    points: list[dict] = []

    def add_point(kind: str, ci: int, t: float, text: str, **kw) -> int:
        points.append({"id": len(points), "k": kind, "c": ci, "t": round(t, 1), "text": text, "w": KIND_WEIGHT[kind], **kw})
        return len(points) - 1

    # 聊天记录：落进时间对得上的记忆片段，落不进的按"一段闲聊"自己成团
    leftovers: dict[str, list[dict]] = defaultdict(list)
    for m in msgs:
        best = None
        for e in by_chat.get(m["chat"], []):
            if e["t0"] - 600 <= m["t"] <= e["t1"] + 600:
                if best is None or (e["t0"] <= m["t"] and (best["t0"] > m["t"] or e["t0"] > best["t0"])):
                    best = e
        if best:
            m["ci"] = best["ci"]
        else:
            leftovers[m["chat"]].append(m)
    for chat, ms in leftovers.items():
        sessions: list[list[dict]] = []
        for m in ms:
            if sessions and m["t"] - sessions[-1][-1]["t"] <= 45 * 60:
                sessions[-1].append(m)
            else:
                sessions.append([m])
        for s in sessions:
            if len(s) < 3:  # 零星几句：挂到同一个聊天里时间最近的星团（3 小时内）
                ci = nearest(chat, s[0]["t"], 3 * 3600)
                if ci is not None:
                    for m in s:
                        m["ci"] = ci
                    continue
            d0 = datetime.fromtimestamp(s[0]["t"], tz)
            ci = cluster(f"s:{chat}:{int(s[0]['t'])}", label=f"{d0.month}月{d0.day}日{part_of_day(d0.hour)}的闲聊",
                         kind="session", chat=chat, summary="", keywords=[], people=[])
            clusters[ci]["_t"] = (s[0]["t"], s[-1]["t"])
            for m in s:
                m["ci"] = ci

    msg_pid: list[int] = []
    for m in msgs:
        uid = m["uid"]
        kind = "self" if uid == "self" else ("owner" if uid == owner else "other")
        msg_pid.append(add_point(kind, m["ci"], m["t"], m["x"], who=names.person(uid),
                                 nick=names.nick(uid) if uid != "self" else "", chat=m["chat"], uid=uid))

    # 长期记忆
    fact_src: list[tuple[int, str, str, float | None]] = []
    for p in mx["paragraphs"]:
        src = str(p.get("source") or "")
        text = str(p.get("content") or "").strip()
        if not text:
            continue
        t = to_float(p.get("event_time")) or to_float(p.get("created_at")) or now
        if src.startswith("person_fact:"):
            parts = src.split(":")
            uid = parts[-1] if len(parts) >= 4 else ""
            chat = chat_of(parts[1]) if len(parts) >= 2 else ""
            who = names.person(uid) if uid else "某人"
            ci = cluster(f"about:{uid}", label=f"关于{who}", kind="core", chat=None, summary="", keywords=[], people=[who])
            pid = add_point("fact", ci, t, text, who=who, chat=chat, uid=uid, hash=p["hash"])
            fact_src.append((pid, chat, uid, to_float(p.get("event_time"))))
            continue
        chat = chat_of(src.split(":", 1)[1]) if src.startswith("chat_summary:") else ""
        eid = mx["ep_of"].get(p["hash"])
        ci = episodes[eid]["ci"] if eid in episodes else nearest(chat, t)
        if ci is None:
            ci = cluster("other-memory", label="其它记忆", kind="core", chat=None, summary="", keywords=[], people=[])
        if text.startswith(INNER_MARK):  # 她自己记下的感受和想法
            add_point("heart", ci, to_float(p.get("created_at")) or t, text[len(INNER_MARK):], who="她心里",
                      chat=chat, hash=p["hash"])
            continue
        add_point("memory", ci, to_float(p.get("created_at")) or t, text, who="长期记忆", chat=chat, hash=p["hash"])

    # 分量（记忆轻重插件打的分）：长期记忆按段落、铭记在心的话落到那句原话上
    weighed = apply_weights(points, msg_pid, pd, cfg, now, warn)

    # 日记、此刻记着
    for d in diaries:
        ci = cluster("diary", label="佳树的日记", kind="core", chat=None, summary="", keywords=[], people=[])
        add_point("diary", ci, d["t"], d["x"], who=f"{d['label']} · {d['key']}", brief=d["brief"], day=d["key"])
    for n in notes:
        ci = cluster("now", label="此刻记着", kind="core", chat=None, summary="她这会儿脑子里记着的事（工作记忆，一小时左右就会换掉）",
                     keywords=[], people=[])
        add_point("note", ci, n["t"], n["x"], who="此刻记着", chat=n["chat"])

    # 关于自己：没有"什么时候记下的"，放在时间轴最开头，拖时间轴时一直都在
    t_first = min((p["t"] for p in points), default=now)
    for f in self_facts:
        ci = cluster("me", label="关于自己", kind="core", chat=None,
                     summary="她是谁的细节（原作里提炼、兄长大人过目改过）。每轮按对方说的话想起最相关的几条。", keywords=[], people=[])
        add_point("me", ci, t_first, f["x"], who="关于自己" + (" · " + f["kind"] if f["kind"] else ""))

    # 她知道的（知识本）：第一次知道的时候出现，越熟越大
    know_src: list[tuple[int, list]] = []
    for k in sorted(knowledge, key=lambda k: k["t"]):
        ci = cluster("know", label="她知道的", kind="core", chat=None,
                     summary="聊天、视频、书、歌、搜索里学到的东西（知识本），越碰越熟。", keywords=[], people=[])
        brief = KNOW_LEVELS[k["level"]] + ("，用上过 %d 次" % k["used"] if k["used"] else "")
        if k["view"]:
            brief += "。她觉得：" + k["view"]
        pid = add_point("know", ci, k["t"], k["x"], who=k["name"] + (" · " + k["kind"] if k["kind"] else ""), brief=brief,
                        w=round(KIND_WEIGHT["know"] * (0.8 + 0.35 * k["level"]), 2))
        know_src.append((pid, k["srcs"]))

    for c in clusters:
        c.pop("_t", None)
    for p in points:
        p.pop("hash", None)

    edges = link_points(points, mx["entities"] + [k for e in episodes.values() for k in e["keywords"]]
                        + [k["name"] for k in knowledge], msg_pid, fact_src, tz, start_hour, know_src)

    # 旋臂：每个聊天一条，按消息多少排
    arm_count = Counter(p["chat"] for p in points if p["k"] in ("owner", "self", "other"))
    arms = [{"chat": c, "label": names.chat(c), "n": n} for c, n in arm_count.most_common()]
    for c in clusters:
        if c.get("chat") and c["chat"] not in arm_count:
            arms.append({"chat": c["chat"], "label": names.chat(c["chat"]), "n": 0})
            arm_count[c["chat"]] = 0
    for p in points:
        if p.get("chat"):
            p["where"] = names.chat(p["chat"])

    times = [p["t"] for p in points]
    days = []
    if times:
        d = datetime.fromtimestamp(min(times), tz).replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if datetime.fromtimestamp(min(times), tz).hour < start_hour:
            d -= timedelta(days=1)
        while d.timestamp() <= max(times):
            days.append({"t": d.timestamp(), "label": f"{d.month}月{d.day}日"})
            d = (d + timedelta(days=1, hours=2)).replace(hour=start_hour)  # 加 26 小时再对齐，夏令时也不会错位

    counts = Counter(p["k"] for p in points)
    return {
        "meta": {
            "generated": now, "tz": tz_name, "tz_offset_min": int((datetime.fromtimestamp(now, tz).utcoffset() or timedelta()).total_seconds() // 60),
            "self_name": SELF_NAME, "owner_title": OWNER_TITLE, "owner_nick": names.nick(owner),
            "day_start_hour": start_hour, "counts": dict(counts), "warnings": warn,
            "weighed": weighed, "gravity_names": GRAVITY_NAMES,
        },
        "arms": arms,
        "days": days,
        "clusters": clusters,
        "points": points,
        "edges": edges,
    }


def link_points(points, vocab_raw, msg_pid, fact_src, tz, start_hour, know_src=()) -> list[list]:
    """连线：[a, b, 强度 0~1, 类型]。类型 t=前后句  r=记忆和它总结的话  s=出处  w=说到同一件事。"""
    edges: dict[tuple[int, int], list] = {}

    def add(a, b, score, typ):
        if a == b:
            return
        key = (min(a, b), max(a, b))
        if key not in edges or edges[key][2] < score:
            edges[key] = [key[0], key[1], round(min(1.0, score), 3), typ]

    # 词表：memorix 抽出来的实体名 + 片段关键词（太短、纯数字、QQ 号的不要）
    vocab = sorted({v.strip() for v in vocab_raw if v and len(v.strip()) >= 2 and not v.strip().isdigit()
                    and not v.startswith("aiocqhttp:")}, key=len, reverse=True)
    tok = []
    df: Counter = Counter()
    for p in points:
        c = tokens(p["text"])
        low = p["text"].lower()
        kw = [v for v in vocab if v.lower() in low]
        for v in kw:
            c["#" + v.lower()] += 2
        tok.append(c)
        p["_kw"] = kw
        df.update(c.keys())
    n = max(1, len(points))
    vecs = []
    for c in tok:
        v = {k: (1 + math.log(x)) * math.log(1 + n / df[k]) for k, x in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({k: x / norm for k, x in v.items()})
    common = {SELF_NAME, OWNER_TITLE}
    for p in points:  # 详情里的关键词：只留不那么常见的
        kw = sorted((v for v in p.pop("_kw") if v not in common and df["#" + v.lower()] <= max(6, n // 5)),
                    key=lambda v: df["#" + v.lower()])
        if kw:
            p["kw"] = kw[:5]

    def sim(a, b):
        va, vb = vecs[a], vecs[b]
        if len(va) > len(vb):
            va, vb = vb, va
        return sum(x * vb.get(k, 0.0) for k, x in va.items())

    by_cluster: dict[int, list[int]] = defaultdict(list)
    for p in points:
        by_cluster[p["c"]].append(p["id"])

    # 前后句：同一个星团、同一个聊天里挨着的两句
    msg_set = set(msg_pid)
    for ids in by_cluster.values():
        ms = sorted((i for i in ids if i in msg_set), key=lambda i: points[i]["t"])
        for a, b in zip(ms, ms[1:]):
            if points[a]["chat"] == points[b]["chat"] and points[b]["t"] - points[a]["t"] < 3 * 3600:
                add(a, b, 0.35, "t")

    # 长期记忆 ↔ 它总结的那几句
    for ids in by_cluster.values():
        mems = [i for i in ids if points[i]["k"] in ("memory", "heart")]
        ms = [i for i in ids if i in msg_set]
        for m in mems:
            for s, i in sorted(((sim(m, i), i) for i in ms), reverse=True)[:3]:
                if s > 0.06:
                    add(m, i, 0.4 + s, "r")

    # 人物事实 ↔ 出处（那个人在那个时间附近说的、最像的一句）
    for pid, chat, uid, et in fact_src:
        cands = [i for i in msg_pid if points[i].get("uid") == uid and (not chat or points[i]["chat"] == chat)]
        near = [i for i in cands if et and abs(points[i]["t"] - et) <= 600]
        if near:  # 记下这条事实的那会儿他说的话：最像的，一样像就挑时间最近的
            best = max(near, key=lambda i: (round(sim(pid, i), 2), -abs(points[i]["t"] - et)))
        else:  # 那会儿的话没记进聊天记录：退一步找他说过的、明显像的一句
            best = max(cands, key=lambda i: sim(pid, i), default=None)
            if best is not None and sim(pid, best) < 0.12:
                best = None
        if best is not None:
            add(pid, best, 0.9, "s")

    # 她知道的 ↔ 学到它时那个聊天里、那会儿最像的一句（视频、书、搜索来的没有聊天，就不连）
    for pid, srcs in know_src:
        for chat, t in srcs[:3]:
            near = [i for i in msg_pid if points[i]["chat"] == chat and t and abs(points[i]["t"] - t) <= 900]
            best = max(near, key=lambda i: sim(pid, i), default=None)
            if best is not None and sim(pid, best) > 0.04:
                add(pid, best, 0.8, "s")

    # 日记 ↔ 那天最像的几句；此刻记着 ↔ 那个聊天最近的几句
    day_of = {i: life_day(points[i]["t"], tz, start_hour) for i in msg_pid}
    for p in points:
        if p["k"] == "diary" and p.get("day"):
            ms = [i for i in msg_pid if day_of[i] == p["day"]]
        elif p["k"] == "note":
            ms = [i for i in msg_pid if points[i]["chat"] == p.get("chat") and 0 <= p["t"] - points[i]["t"] <= 6 * 3600]
        else:
            continue
        for s, i in sorted(((sim(p["id"], i), i) for i in ms), reverse=True)[:4]:
            if s > 0.05:
                add(p["id"], i, 0.35 + s, "r")

    # 说到同一件事：跨星团、最像的两颗
    word_deg: Counter = Counter()
    cand = []
    for a in range(len(points)):
        if len(vecs[a]) < 2:
            continue
        for b in range(a + 1, len(points)):
            if points[a]["c"] == points[b]["c"] or len(vecs[b]) < 2:
                continue
            s = sim(a, b)
            if s >= 0.26:
                cand.append((s, a, b))
    for s, a, b in sorted(cand, reverse=True):
        if word_deg[a] >= 2 or word_deg[b] >= 2 or (min(a, b), max(a, b)) in edges:
            continue
        word_deg[a] += 1
        word_deg[b] += 1
        add(a, b, s, "w")

    return sorted(edges.values())


# ---------------------------------------------------------------- 输出
DATA_TAG = '<script id="sea-data" type="application/json">__SEA_DATA__</script>'


def render_html(scene: dict, template: Path = TEMPLATE) -> str:
    html = template.read_text(encoding="utf-8")
    # 数据放进 <script type="application/json">：把 < 全转义，聊天里写了 </script> 也不会提前结束标签
    data = json.dumps(scene, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    if html.count(DATA_TAG) != 1:
        raise RuntimeError(f"模板里要有且只有一个 {DATA_TAG}：{template}")
    return html.replace(DATA_TAG, DATA_TAG.replace("__SEA_DATA__", data))


def cmd_build(data_dir: Path, html_path: Path, open_after: bool) -> dict:
    scene = build_scene(data_dir)
    html = render_html(scene)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = html_path.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, html_path)
    if open_after:
        os.startfile(str(html_path))  # noqa: S606  用默认浏览器打开
    return {"ok": True, "path": str(html_path), "counts": scene["meta"]["counts"], "stars": len(scene["points"]),
            "lines": len(scene["edges"]), "clusters": len(scene["clusters"]), "warnings": scene["meta"]["warnings"]}


def main(argv: list[str]) -> int:
    out = None
    data_dir = DATA
    html_path = OUT_HTML
    open_after = False
    rest = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = Path(next(it))
        elif a == "--html":
            html_path = Path(next(it))
        elif a == "--data-dir":
            data_dir = Path(next(it))
        elif a == "--open":
            open_after = True
        else:
            rest.append(a)
    try:
        if rest[:1] != ["build"]:
            raise SystemExit(__doc__)
        res = cmd_build(data_dir, html_path, open_after)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if out:
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
