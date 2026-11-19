"""她懂的东西（纯计算，不碰 AstrBot，离线可测）。

一样东西一条：作品、角色、梗、歌、知识……每条记着它是什么、知道的几个点、她的看法、跟别的东西的关系、
拿不准的说法、在哪儿碰到过。再碰到同一样东西就往这条上补，不另开一条：碰到的日子越多、知道得越多、
用得越多就越熟（听说过 → 知道一些 → 挺熟 → 很懂）；很久没碰也没用就慢慢记不清。
"""

from __future__ import annotations

import hashlib
import json
import re

KINDS = ("作品", "角色", "人物", "梗", "游戏", "歌曲", "知识", "做法", "地方", "东西", "其他")
LEVELS = ("听说过", "知道一些", "挺熟", "很懂")
# 不算"学来的东西"：她自己、兄长大人（人设里的事），以及聊天里的人（另有人物记忆）
SELF_NAMES = {"佳树", "温水佳树", "小佳树", "兄长大人", "兄长", "哥哥", "温水和彦", "和彦", "温水君"}
# 知道的点、好奇、原来如此里出现这些就不要（她自己、兄长大人的事不是学来的；她就是温水佳树）
SELF_TOKENS = ("佳树", "兄长大人", "温水和彦", "温水君")
# 她自己口吻的句子里本来就会自称"佳树"；这些才说明是在讲她本人/兄长大人
WHO_SHE_IS = ("温水佳树", "兄长大人", "温水和彦", "温水君")
# 太普通的叫法，当名字、别名会让她天天误想起来（"妹妹"）
GENERIC = {"我", "你", "他", "她", "它", "妹妹", "哥哥", "姐姐", "弟弟", "女友", "前女友", "男友", "女主", "男主", "主角",
           "角色", "作者", "视频", "游戏", "动画", "小说", "歌", "歌曲", "电影", "梗", "作品", "老师", "同学", "妈妈", "爸爸",
           "母亲", "父亲", "朋友", "大家", "那个", "这个", "东西", "微调", "模型", "AI", "ai", "UP主", "up主"}
MAX_FACTS = 10
MAX_DOUBTS = 4
MAX_SRCS = 12
MAX_DAYS = 40
MAX_LINKS = 12


# ---------------------------------------------------------------- 名字
def clean(s, cap: int = 16) -> str:
    s = str(s or "").strip()
    m = re.search(r"《([^《》]+)》", s)
    if m and len(m.group(1).strip()) >= 2:  # "《妹妹人生》上（台版）" → 妹妹人生
        s = m.group(1)
    s = re.sub(r"(?:\s+|[（(])(?:上|下|中)[）)]?(?=\s*》|\s*$)", "", s)
    s = re.sub(r"\s*第[0-9一二三四五六七八九十百]{1,3}[册卷集话季部]\s*(?=》|$)", "", s)
    s = re.sub(r"\s+", " ", s).strip(" 「」\"'“”《》【】")
    return s[:cap]


def norm(s: str) -> str:
    """比较用：去掉书名号、空格、标点，英文小写。"""
    return re.sub(r"[\s\W_]+", "", clean(s, 40)).lower()


def is_self(name, extra: set[str] | None = None) -> bool:
    n = norm(name)
    return not n or n in {norm(x) for x in SELF_NAMES | (extra or set())}


def is_generic(name) -> bool:
    n = norm(name)
    return len(n) < 2 or n in {norm(x) for x in GENERIC}


def about_self(text, extra: set[str] | None = None) -> bool:
    """这句话说的是她自己、兄长大人，或者聊天里的某个人（"555说……"）。"""
    t = str(text or "")
    return any(x in t for x in SELF_TOKENS) or any(len(p) >= 2 and p in t for p in (extra or set()))


def names_of(card: dict) -> list[str]:
    return [card["name"], *card.get("aliases", [])]


def _ascii(s: str) -> bool:
    return all(ord(ch) < 128 for ch in s)


def _grams(s: str) -> set[str]:
    s = re.sub(r"[\W_]", "", s or "").lower()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def carries(card: dict, reply: str, said: str, need: int = 3) -> bool:
    """她的回复里带出了这张卡上的内容（对方这句里没有的）：哪条事实 / 是什么 / 以前弄错过的说法，
    有 need 个以上的两字片段出现在回复里、而对方没说过（名字本身不算）。
    11-19：原来要求事实的前 6 个字原样出现，回复器都是换着说的，一个月 54 次给她看只算到 1 次“用上”。"""
    fresh = _grams(reply) - _grams(said)
    for name in names_of(card):
        fresh -= _grams(name)
    texts = [f.get("x", "") for f in card.get("facts", [])] + [card.get("what", "")] + [x.get("x", "") for x in card.get("fixed", [])]
    return any(len(_grams(t) & fresh) >= need for t in texts if t)


def mentioned(card: dict, text: str) -> str:
    """这段话里提到了这样东西的哪个叫法（没提到返回 ""）。英文名要整词、至少 3 个字母；中文名至少 2 个字。"""
    if not text:
        return ""
    low = text.lower()
    for name in sorted(names_of(card), key=len, reverse=True):
        n = clean(name, 40)
        if not n:
            continue
        if _ascii(n):
            if len(n) < 3:
                continue
            if re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", low):
                return n
        elif len(n) >= 2 and n.lower() in low:
            return n
    return ""


STOP_CH = set("的了是不在有我你他她它这那么什怎吗呢吧啊呀哦也都就还很太和与说个一要会能想去来看过着没好人")


def grams3(text: str) -> set[str]:
    """一句话里三个字的中文片段（带"的了是不……"这种常用字的不要），拿来跟条目的名字、说明对字面。"""
    out = set()
    for run_ in re.findall(r"[一-鿿]{3,}", text or ""):
        for i in range(len(run_) - 2):
            g = run_[i:i + 3]
            if not (set(g) & STOP_CH):
                out.add(g)
    return out


def word_hit(card: dict, grams: set[str]) -> str:
    """对方话里的三字片段出现在这条的名字、别名、说明里（"小傻龙是谁呀" → 说明里写着"小傻龙玩偶"的陈千语）。"""
    if not grams:
        return ""
    blob = " ".join([*names_of(card), card.get("what", "")])
    return next((g for g in sorted(grams) if g in blob), "")


from kaju_core.heart.taste import bigram_overlap  # noqa: E402  和喜好账本同一份（11-18 整理合并）


# ---------------------------------------------------------------- 本子
def new_book() -> dict:
    return {"cards": {}, "wonders": [], "digests": []}


def live(book: dict) -> list[dict]:
    return [c for c in book["cards"].values() if not c.get("removed")]


def find(book: dict, name: str) -> dict | None:
    """按名字或别名找（规范化后完全相同）。"""
    n = norm(name)
    if not n:
        return None
    for c in live(book):
        if any(norm(x) == n for x in names_of(c)):
            return c
    return None


def get(book: dict, cid) -> dict | None:
    c = book["cards"].get(str(cid or "").strip())
    while c is not None and c.get("removed") and c.get("merged_into"):
        c = book["cards"].get(c["merged_into"])
    return c if c is not None and not c.get("removed") else None


def _new_card(book: dict, name: str, kind: str, now: float) -> dict:
    base = f"{norm(name)}|{now}"
    cid = hashlib.sha1(base.encode()).hexdigest()[:8]
    while cid in book["cards"]:
        cid = hashlib.sha1((base + cid).encode()).hexdigest()[:8]
    card = {"id": cid, "name": clean(name, 16), "aliases": [], "kind": kind if kind in KINDS else "其他",
            "what": "", "facts": [], "view": "", "links": [], "doubts": [], "srcs": [], "days": [],
            "t0": now, "t1": now, "used": 0, "last_used": 0.0, "aha": ""}
    book["cards"][cid] = card
    return card


def add_alias(card: dict, alias) -> None:
    a = clean(alias, 16)
    if a and not is_generic(a) and not is_self(a) and norm(a) not in {norm(x) for x in names_of(card)}:
        card.setdefault("aliases", []).append(a)
        card["aliases"] = card["aliases"][-8:]


def demote(card: dict, text: str, why: str, now: float) -> bool:
    """睡前核对（11-19）：这条“知道的”被后来的聊天说成不对 / 按日期已经过时 → 挪进“拿不准”（不删，别说得太肯定）。"""
    x = " ".join(str(text or "").split())
    for f in list(card.get("facts", [])):
        if bigram_overlap(f["x"], x) >= 0.6:
            card["facts"].remove(f)
            card["doubts"] = [d for d in card.get("doubts", []) if bigram_overlap(d["x"], f["x"]) < 0.6]
            card["doubts"].append({"x": f["x"], "who": ("核对：" + " ".join(str(why or "").split()))[:30], "t": now})
            card["doubts"] = card["doubts"][-MAX_DOUBTS:]
            return True
    return False


def add_fact(card: dict, text, src: dict, now: float, sure: bool = True, people: set[str] | None = None) -> str:
    """往这条上补一个知道的点：已经知道的算又确认了一次；不太确定的、跟已有的对不上的进"拿不准"。返回 new / again / doubt / ""。
    说的是她自己、兄长大人、聊天里某个人的（"555说要从头看"）不记。"""
    x = " ".join(str(text or "").split())[:60]
    if len(x) < 4 or about_self(x, people):
        return ""
    for f in card["facts"]:
        if bigram_overlap(f["x"], x) >= 0.6:
            f["n"] = int(f.get("n", 1)) + 1
            f["t"] = now
            if sure and not f.get("sure", True):
                f["sure"] = True
            return "again"
    if sure:  # 有人说得肯定了：以前拿不准的同一句不再算拿不准
        card["doubts"] = [d for d in card["doubts"] if bigram_overlap(d["x"], x) < 0.6]
    if not sure:
        for d in card["doubts"]:
            if bigram_overlap(d["x"], x) >= 0.6:
                return ""
        card["doubts"].append({"x": x, "who": src.get("who", ""), "t": now})
        card["doubts"] = card["doubts"][-MAX_DOUBTS:]
        return "doubt"
    card["facts"].append({"x": x, "who": src.get("who", ""), "how": src.get("how", ""), "t": now, "n": 1, "sure": True})
    if len(card["facts"]) > MAX_FACTS:  # 留确认次数多的、新的
        card["facts"].sort(key=lambda f: (int(f.get("n", 1)), float(f.get("t", 0))))
        card["facts"] = card["facts"][1:]
        card["facts"].sort(key=lambda f: float(f.get("t", 0)))
    return "new"


def fix(card: dict, old: str, now: float) -> int:
    """被纠正了：跟旧说法差不多的点挪走，记一句"以前以为……"。"""
    old = " ".join(str(old or "").split())[:60]
    if len(old) < 3:
        return 0
    keep, moved = [], 0
    for f in card["facts"]:
        if bigram_overlap(f["x"], old) >= 0.5:
            moved += 1
        else:
            keep.append(f)
    card["facts"] = keep
    if bigram_overlap(card.get("what", ""), old) >= 0.5:
        card["what"] = ""
        moved += 1
    card["doubts"] = [d for d in card["doubts"] if bigram_overlap(d["x"], old) < 0.5]
    card["fixed"] = ([*card.get("fixed", []), {"x": old, "t": now}])[-3:]
    return moved


def link(card: dict, to: dict | None, rel: str, to_name: str = "") -> bool:
    rel = clean(rel, 8)
    if not rel:
        return False
    if to is not None:
        if to["id"] == card["id"]:
            return False
        for ln in card["links"]:
            if ln.get("to") == to["id"]:
                ln["rel"] = rel
                return False
        card["links"].append({"to": to["id"], "rel": rel})
    else:
        name = clean(to_name, 16)
        if not name or norm(name) in {norm(x) for x in names_of(card)}:
            return False
        for ln in card["links"]:
            if not ln.get("to") and norm(ln.get("name", "")) == norm(name):
                ln["rel"] = rel
                return False
        card["links"].append({"name": name, "rel": rel})
    card["links"] = card["links"][-MAX_LINKS:]
    return True


def touch(card: dict, src: dict, now: float, day: str) -> None:
    """又碰到了一次（在哪儿、谁讲的）。同一个地方一小时内算同一次。"""
    card["t1"] = max(float(card.get("t1", 0)), now)
    last = card["srcs"][-1] if card["srcs"] else None
    if not (last and last.get("how") == src.get("how") and last.get("chat") == src.get("chat")
            and now - float(last.get("t", 0)) < 3600):
        card["srcs"].append({k: src.get(k, "") for k in ("how", "who", "chat", "title")} | {"t": now})
        card["srcs"] = card["srcs"][-MAX_SRCS:]
    if day and day not in card["days"]:
        card["days"].append(day)
        card["days"] = card["days"][-MAX_DAYS:]


def apply_items(book: dict, items: list, src: dict, now: float, day: str,
                exclude: set[str] | None = None, max_items: int = 8) -> dict:
    """把模型挑出来的东西记进本子。src = {how, who, chat, title, trust}（trust 0 = 不太可靠，来的都当"拿不准"）。"""
    stats = {"new": [], "more": [], "doubt": 0, "fixed": 0}
    pending_links = []
    seen_here: dict[str, dict] = {}
    for it in (items or [])[:max_items]:
        if not isinstance(it, dict):
            continue
        name = clean(it.get("name"), 16)
        if not name or is_self(name, exclude) or is_generic(name):
            continue
        found = get(book, str(it.get("ref") or "")) if it.get("ref") else None
        if found is None:
            found = find(book, name) or next((find(book, a) for a in (it.get("aliases") or []) if find(book, a)), None)
        kind = str(it.get("kind") or "").strip()
        created = found is None
        card: dict = found if found is not None else _new_card(book, name, kind, now)
        if not created and norm(name) not in {norm(x) for x in names_of(card)}:
            add_alias(card, name)
        if card.get("kind") == "其他" and kind in KINDS:
            card["kind"] = kind
        for a in it.get("aliases") or []:
            if not is_self(a, exclude):
                add_alias(card, a)
        who = clean(it.get("who") or src.get("who", ""), 16)
        s = {**src, "who": who or src.get("who", "")}
        sure = bool(it.get("sure", True)) and int(src.get("trust", 1)) > 0
        if it.get("fix"):
            stats["fixed"] += fix(card, it["fix"], now)
        what = " ".join(str(it.get("what") or "").split())[:60]
        if about_self(what, exclude):
            what = ""
        if what and (not card["what"] or (it.get("fix") and sure)):
            card["what"] = what
        elif what and bigram_overlap(card["what"], what) < 0.5:
            add_fact(card, what, s, now, sure, exclude)
        got_any = created and bool(what)
        for f in (it.get("facts") or [])[:5]:
            r = add_fact(card, f, s, now, sure, exclude)
            got_any = got_any or r in ("new", "doubt")
            stats["doubt"] += r == "doubt"
        view = " ".join(str(it.get("view") or "").split())[:50]
        if view:
            card["view"] = view
        touch(card, s, now, day)
        for ln in it.get("links") or []:
            if isinstance(ln, dict):
                pending_links.append((card, str(ln.get("to") or ""), str(ln.get("rel") or "")))
        seen_here[norm(card["name"])] = card
        if created:
            stats["new"].append(card["name"])
        elif got_any:
            stats["more"].append(card["name"])
    for card, to_name, rel in pending_links:
        to = seen_here.get(norm(to_name)) or find(book, to_name)
        if to is None and is_self(to_name, exclude):
            continue
        link(card, to, rel, to_name)
    return stats


# ---------------------------------------------------------------- 熟悉、记不清
def familiarity(card: dict) -> float:
    return (len(set(card.get("days", [])))
            + 0.5 * min(len(card.get("facts", [])), 8)
            + 0.3 * min(int(card.get("used", 0)), 10)
            + (0.5 if card.get("view") else 0)
            + (0.5 if card.get("what") else 0))


def level(card: dict) -> int:
    f = familiarity(card)
    return 0 if f < 2 else 1 if f < 4 else 2 if f < 6.5 else 3


def strength(card: dict, now: float, half_days: float = 30.0) -> float:
    """记得多清楚：越熟忘得越慢（半衰期 30 / 60 / 90 / 120 天），用一次就从那时重新算。"""
    ref = max(float(card.get("t1", 0)), float(card.get("last_used", 0) or 0))
    half = half_days * (1 + level(card))
    return 2 ** (-max(0.0, now - ref) / 86400 / half)


def visible(card: dict, now: float, half_days: float = 30.0) -> bool:
    return not card.get("removed") and (strength(card, now, half_days) >= 0.1 or level(card) >= 2)


# ---------------------------------------------------------------- 给模型看的
def _src_text(card: dict, here: str = "") -> str:
    hows = []
    for s in card.get("srcs", []):
        how = s.get("how", "")
        if s.get("chat", "").startswith("p") and here and s.get("chat") != here and "兄长" not in how:
            how = "听人说的"  # 别人私聊里讲的：知识可以用，但不说是谁私下讲的
        if how and how not in hows:
            hows.append(how)
    return "、".join(hows[-3:])


def ref_line(card: dict) -> str:
    """给抽取/消化的模型看的旧条目（带 id）。"""
    bits = [f"[{card['id']}] {card['name']}"]
    if card.get("aliases"):
        bits.append("（又叫" + "、".join(card["aliases"][:4]) + "）")
    bits.append(f"〔{card['kind']}，{LEVELS[level(card)]}〕")
    if card.get("what"):
        bits.append("：" + card["what"])
    facts = [f["x"] for f in card.get("facts", [])][-5:]
    if facts:
        bits.append("｜知道的：" + "；".join(facts))
    if card.get("doubts"):
        bits.append("｜拿不准：" + "；".join(d["x"] for d in card["doubts"]))
    if card.get("view"):
        bits.append("｜看法：" + card["view"])
    return "".join(bits)


def link_text(book: dict, card: dict) -> str:
    out = []
    for ln in card.get("links", [])[:5]:
        to = get(book, ln.get("to")) if ln.get("to") else None
        name = to["name"] if to else ln.get("name", "")
        if name:
            out.append(f"{ln.get('rel', '')}{name}" if ln.get("rel", "").endswith(("于", "自", "是", "的")) else f"{ln.get('rel', '')}：{name}")
    return "；".join(out)


def note_line(book: dict, card: dict, now: float, here: str = "", half_days: float = 30.0) -> str:
    """聊天时给她看的一条。"""
    lv = LEVELS[level(card)]
    st = strength(card, now, half_days)
    head = f"- {card['name']}（{card['kind']}，{lv}"
    if card.get("aliases"):
        head += "；也叫" + "、".join(card["aliases"][:3])
    head += "）"
    if st < 0.35:
        return head + "：以前知道一点，现在记不太清了" + (f"，只记得{card['what']}" if card.get("what") else "")
    parts = [head + (f"：{card['what']}" if card.get("what") else "")]
    facts = sorted(card.get("facts", []), key=lambda f: (int(f.get("n", 1)), float(f.get("t", 0))), reverse=True)
    picked, size = [], 0
    for f in facts[: 2 + level(card)]:  # 越熟给得越多，但一条别太长
        if picked and size + len(f["x"]) > 150:
            break
        picked.append(f["x"])
        size += len(f["x"])
    facts = picked
    if facts:
        parts.append("知道的：" + "；".join(facts))
    lt = link_text(book, card)
    if lt:
        parts.append("跟别的关系：" + lt)
    if card.get("view"):
        parts.append("你的看法：" + card["view"])
    if card.get("doubts"):
        parts.append("拿不准（有人这么说，别说得太肯定）：" + "；".join(d["x"] for d in card["doubts"][-2:]))
    if card.get("fixed"):
        parts.append("以前弄错过：" + card["fixed"][-1]["x"])
    if card.get("aha"):
        parts.append("你想明白过：" + card["aha"])
    src = _src_text(card, here)
    parts = [p.rstrip("。") for p in parts]
    return "。".join(parts) + (f"。（{src}）" if src else "")


NOTE_HEAD = (
    "【你知道的】下面是你自己一点一点学来的（看过的视频和书、听别人讲的、上网查过的），不是谁给你的资料。"
    "聊到了就用自己的话自然带出来，像本来就知道一样；知道多少说多少：「听说过」「知道一些」的只说个大概，可以说\"好像是……\"；"
    "下面没写到的别编，「拿不准」的别说得太肯定；对方正在聊的不是这个就别提。别一口气全倒出来，"
    "也别说\"知识\"\"笔记\"\"记录\"这种词。"
)


def recall_text(book: dict, cards: list[dict], now: float, here: str = "") -> str:
    """工具 recall_knowledge 的结果：比聊天提示更全一点。"""
    out = []
    for c in cards:
        out.append(note_line(book, c, now, here))
        more = [f["x"] for f in c.get("facts", [])]
        if len(more) > 2 + level(c):
            out.append("  其他知道的：" + "；".join(more[2 + level(c):]))
    return "\n".join(out)


# ---------------------------------------------------------------- 解析模型的回答
def parse_json(text: str) -> dict | None:
    """回答里第一个完整的 JSON 对象（前后有别的字、代码块标记都行）。"""
    s = text or ""
    dec = json.JSONDecoder()
    i = s.find("{")
    while i != -1:
        try:
            data, _ = dec.raw_decode(s, i)
        except json.JSONDecodeError:
            i = s.find("{", i + 1)
            continue
        if isinstance(data, dict):
            return data
        i = s.find("{", i + 1)
    return None


# ---------------------------------------------------------------- 消化（睡前理一理）
def apply_digest(book: dict, data: dict, now: float, ids: set[str]) -> dict:
    """ids：这次给模型看的条目，只改这些。"""
    stats = {"merged": 0, "updated": 0, "links": 0, "wonders": 0, "aha": ""}
    for m in data.get("merge") or []:
        if not isinstance(m, dict):
            continue
        keep, drop = get(book, m.get("keep")), get(book, m.get("drop"))
        if not keep or not drop or keep["id"] == drop["id"] or keep["id"] not in ids or drop["id"] not in ids:
            continue
        for a in names_of(drop):
            add_alias(keep, a)
        for f in drop["facts"]:
            add_fact(keep, f["x"], f, float(f.get("t", now)), f.get("sure", True))
        keep["doubts"] = (keep["doubts"] + drop["doubts"])[-MAX_DOUBTS:]
        keep["srcs"] = sorted(keep["srcs"] + drop["srcs"], key=lambda s: s.get("t", 0))[-MAX_SRCS:]
        keep["days"] = sorted(set(keep["days"]) | set(drop["days"]))[-MAX_DAYS:]
        keep["links"] = (keep["links"] + [ln for ln in drop["links"] if ln.get("to") != keep["id"]])[-MAX_LINKS:]
        keep["used"] = int(keep.get("used", 0)) + int(drop.get("used", 0))
        keep["t0"], keep["t1"] = min(keep["t0"], drop["t0"]), max(keep["t1"], drop["t1"])
        if not keep.get("what"):
            keep["what"] = drop.get("what", "")
        if not keep.get("view"):
            keep["view"] = drop.get("view", "")
        drop["removed"], drop["merged_into"] = True, keep["id"]
        for c in live(book):
            for ln in c["links"]:
                if ln.get("to") == drop["id"]:
                    ln["to"] = keep["id"]
            c["links"] = [ln for ln in c["links"] if ln.get("to") != c["id"]]
        stats["merged"] += 1
    for u in data.get("update") or []:
        if not isinstance(u, dict):
            continue
        c = get(book, u.get("id"))
        if not c or c["id"] not in ids:
            continue
        changed = False
        for a in u.get("aliases") or []:
            if isinstance(a, str) and not is_self(a) and norm(a) not in {norm(x) for x in names_of(c)}:
                add_alias(c, a)
                changed = True
        what = " ".join(str(u.get("what") or "").split())[:60]
        if what and what != c.get("what"):
            c["what"], changed = what, True
        facts = [" ".join(str(x).split())[:60] for x in (u.get("facts") or [])
                 if len(str(x).strip()) >= 4 and not about_self(x)]
        if facts:
            old = c["facts"]
            new = []
            for x in facts[:MAX_FACTS]:
                prev = max(old, key=lambda f: bigram_overlap(f["x"], x), default=None)
                if prev is not None and bigram_overlap(prev["x"], x) >= 0.4:
                    new.append({**prev, "x": x})
                else:
                    new.append({"x": x, "who": "", "how": "自己理的", "t": now, "n": 1, "sure": True})
            c["facts"], changed = new, True
        if "doubts" in u and isinstance(u.get("doubts"), list):
            c["doubts"] = [{"x": " ".join(str(x).split())[:60], "who": "", "t": now}
                           for x in u["doubts"] if str(x).strip()][-MAX_DOUBTS:]
            changed = True
        view = " ".join(str(u.get("view") or "").split())[:50]
        if view and view != c.get("view"):
            c["view"], changed = view, True
        stats["updated"] += changed
    for ln in data.get("links") or []:
        if not isinstance(ln, dict):
            continue
        a, b = get(book, ln.get("from")), get(book, ln.get("to"))
        if a and b and a["id"] in ids and b["id"] in ids:
            stats["links"] += link(a, b, str(ln.get("rel") or ""))
    wonders = book.setdefault("wonders", [])
    for w in (data.get("wonder") or [])[:3]:
        if not isinstance(w, dict):
            continue
        q = " ".join(str(w.get("q") or "").split())[:40]
        kw = clean(w.get("kw") or "", 16)
        if not q or any(bigram_overlap(x["q"], q) >= 0.6 for x in wonders):
            continue
        if any(x in q + " " + kw for x in WHO_SHE_IS) or is_self(kw):  # 她就是温水佳树，不去"弄明白"自己
            continue
        about = get(book, str(w.get("about") or ""))
        wonders.append({"q": q, "kw": kw, "about": about["id"] if about else "", "t": now, "tried": 0})
        stats["wonders"] += 1
    book["wonders"] = [w for w in wonders if now - float(w.get("t", now)) < 14 * 86400][-6:]
    aha = " ".join(str(data.get("insight") or "").split())[:60]
    if any(x in aha for x in WHO_SHE_IS):  # "原来败犬女主里也有个叫温水佳树的角色"——她就是
        aha = ""
    if aha:
        about, best = None, 10 ** 6
        for c in (get(book, i) for i in sorted(ids)):  # 挂在这句里最先提到的那样东西上
            if not c or not mentioned(c, aha):
                continue
            pos = min((aha.lower().find(clean(n, 40).lower()) for n in names_of(c)
                       if clean(n, 40) and clean(n, 40).lower() in aha.lower()), default=-1)
            if pos != -1 and pos < best:
                about, best = c, pos
        if about is not None:
            about["aha"] = aha
        stats["aha"] = aha
    return stats


def neighbors(book: dict, cards: list[dict], limit: int = 12) -> list[dict]:
    """跟这些条目有关的旧条目：有关系连着的、名字/内容提到彼此的。"""
    ids = {c["id"] for c in cards}
    out: list[dict] = []
    for c in cards:
        for ln in c.get("links", []):
            to = get(book, ln.get("to")) if ln.get("to") else find(book, ln.get("name", ""))
            if to and to["id"] not in ids:
                ids.add(to["id"])
                out.append(to)
    blob = " ".join(ref_line(c) for c in cards)
    for c in live(book):
        if c["id"] in ids:
            continue
        if mentioned(c, blob) or any(mentioned(x, ref_line(c)) for x in cards):
            ids.add(c["id"])
            out.append(c)
    return out[:limit]


def relevant(book: dict, text: str, limit: int = 8) -> list[dict]:
    """抽取前给模型看的旧条目：这段话里提到名字的。"""
    hits = [c for c in live(book) if mentioned(c, text)]
    hits.sort(key=lambda c: -familiarity(c))
    return hits[:limit]
