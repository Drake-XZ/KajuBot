"""Offline tests for tools/memsea.py（记忆星海）— builds from a fake data folder in a temp dir, never touches the real data.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_memsea.py
Exit code 0 = all passed. Also does a read-only smoke run on the real data if it is there.
"""

import json
import re
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import memsea  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


SH = ZoneInfo("Asia/Shanghai")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=SH).timestamp()


def write(path: Path, data, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")


# ---------------------------------------------------------------- 假数据
root = Path(tempfile.mkdtemp()) / "data"
pd = root / "plugin_data"
write(root / "cmd_config.json", {"timezone": "Asia/Shanghai"})
write(root / "config" / "astrbot_plugin_kaju_life_config.json", {"day_start_hour": 5}, bom=True)
write(root / "config" / "astrbot_plugin_address_book_config.json", {"owner_qq": "111"}, bom=True)
life = pd / "astrbot_plugin_kaju_life"
log = [
    {"t": "13:30", "c": "p111", "u": "111", "n": "", "x": "我在外地读书，最近在玩pjsk"},
    {"t": "13:30", "c": "p111", "u": "self", "n": "佳树", "x": "兄长大人在外地读书呀，佳树记住了"},
    {"t": "13:31", "c": "p111", "u": "111", "n": "晴川", "x": "[图片]"},
    {"t": "13:31", "c": "p111", "u": "111", "n": "晴川", "x": "[File Attachment: name a.png, path C:\\x\\a.png]"},
    {"t": "13:32", "c": "p111", "u": "111", "n": "晴川", "x": "[惊讶]今天吃晚饭了吗"},
    {"t": "13:33", "c": "pastrbot", "u": "astrbot", "n": "astrbot", "x": "网页测试的话，不该出现"},
    {"t": "20:00", "c": "g999", "u": "222", "n": "来点", "x": "@佳树(555555555) 晚上好呀 </script><b>x</b>"},
    {"t": "20:01", "c": "g999", "u": "self", "n": "佳树", "x": "女王大人晚上好"},
    {"t": "20:02", "c": "g999", "u": "333", "n": "路人", "x": "我也在玩pjsk"},
    {"t": "01:30", "c": "p111", "u": "111", "n": "晴川", "x": "晚安佳树，我先睡了"},
]
write(life / "log" / "2026-10-28.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in log) + "\n")
write(life / "names.json", {"groups": {"999": "妖妖"}, "people": {"111": "晴川", "222": "来点", "333": "路人"}})
write(life / "index.json", {"diary": {"2026-10-28": {"full": "今天兄长大人说他在外地读书，还在玩pjsk。", "brief": "记住了兄长大人的学校"}},
                            "weekly": {}, "monthly": {}, "skip": {}})
write(pd / "astrbot_plugin_address_book" / "addresses.json", {"222": {"address": "女王大人", "nickname": "来点"}})
write(pd / "astrbot_plugin_memory_weight" / "working_notes.json", {
    "qq_555555555:FriendMessage:111": {"note": "话题：兄长大人要睡了", "updated": ts("2026-10-29 01:31")},
    "webchat:FriendMessage:webchat!astrbot!abc": {"note": "网页测试的笔记", "updated": ts("2026-10-29 01:31")},
})

db = pd / "astrbot_plugin_memorix" / "scopes" / "aiocqhttp" / "metadata" / "metadata.db"
db.parent.mkdir(parents=True)
con = sqlite3.connect(db)
con.executescript("""
create table paragraphs (hash text primary key, content text, created_at real, source text, event_time real,
                         is_deleted integer default 0, expires_at real);
create table episodes (episode_id text primary key, source text, title text, summary text, event_time_start real,
                       event_time_end real, participants_json text, keywords_json text);
create table episode_paragraphs (episode_id text, paragraph_hash text, position integer);
create table entities (hash text, name text, is_deleted integer default 0);
create table person_registry (user_id text, person_name text, nickname text);
create table transcript_sessions (session_id text, metadata_json text);
""")
con.executemany("insert into paragraphs values (?,?,?,?,?,?,?)", [
    ("h1", "兄长大人自我介绍：在外地读书，玩pjsk", ts("2026-10-28 13:40"), "chat_summary:111", None, 0, None),
    ("h2", "晴川在外地读书", ts("2026-10-28 13:30"), "person_fact:111:aiocqhttp:111", ts("2026-10-28 13:30"), 0, None),
    ("h3", "这条删掉了", ts("2026-10-28 13:30"), "person_fact:111:aiocqhttp:111", None, 1, None),
    ("h4", "群里大家在聊pjsk", ts("2026-10-28 20:05"), "chat_summary:999", None, 0, None),
])
con.execute("insert into episodes values (?,?,?,?,?,?,?,?)",
            ("ep1", "chat_summary:111", "自我介绍", "兄长大人说了学校和游戏", ts("2026-10-28 13:30"), ts("2026-10-28 13:35"),
             '["兄长大人"]', '["外地", "pjsk"]'))
con.execute("insert into episode_paragraphs values ('ep1', 'h1', 0)")
con.executemany("insert into entities (hash, name) values (?, ?)", [("e1", "外地"), ("e2", "pjsk"), ("e3", "aiocqhttp:111"), ("e4", "555")])
con.execute("insert into transcript_sessions values ('999', '{\"group_id\": \"999\"}')")
con.commit()
con.close()

# ---------------------------------------------------------------- 组装
scene = memsea.build_scene(root, now=ts("2026-10-29 02:00"))
P, C, E = scene["points"], scene["clusters"], scene["edges"]
texts = [p["text"] for p in P]
kinds = {}
for p in P:
    kinds[p["k"]] = kinds.get(p["k"], 0) + 1

expect("counts", kinds, {"owner": 3, "self": 2, "other": 2, "memory": 2, "fact": 1, "diary": 1, "note": 1})
expect("no warnings", scene["meta"]["warnings"], [])
expect("webchat log line dropped", any("网页测试" in t for t in texts), False)
expect("placeholder-only lines dropped", any(t.startswith("[") for t in texts), False)
expect("qq face stripped", "今天吃晚饭了吗" in texts, True)
expect("@name(qq) cleaned", any(t.startswith("@佳树 晚上好呀") for t in texts), True)
expect("deleted paragraph dropped", "这条删掉了" in texts, False)

late = next(p for p in P if p["text"] == "晚安佳树，我先睡了")
expect("01:30 belongs to the next calendar day", datetime.fromtimestamp(late["t"], SH).strftime("%m-%d %H:%M"), "10-29 01:30")
same = [p["t"] for p in P if p["k"] in ("owner", "self") and datetime.fromtimestamp(p["t"], SH).strftime("%H:%M") == "13:30"]
expect("same-minute lines keep their order", same == sorted(same) and len(set(same)) == 2, True)

owner_line = next(p for p in P if p["text"].startswith("我在外地"))
queen = next(p for p in P if p["text"].startswith("@佳树"))
expect("owner called 兄长大人", owner_line["who"], "兄长大人")
expect("owner nickname kept", owner_line["nick"], "晴川")
expect("address book name used", queen["who"], "女王大人")
expect("group chat name", queen["where"], "妖妖群")
expect("private chat name", owner_line["where"], "私聊 · 兄长大人")

ep = next(i for i, c in enumerate(C) if c["label"] == "自我介绍")
expect("episode keywords kept", C[ep]["keywords"], ["外地", "pjsk"])
expect("message lands in its episode", owner_line["c"], ep)
expect("summary paragraph lands in its episode", next(p for p in P if p["k"] == "memory" and "自我介绍" in p["text"])["c"], ep)
expect("group lines form their own session", C[queen["c"]]["kind"], "session")
expect("group memory joins nearest group cluster", next(p for p in P if p["text"] == "群里大家在聊pjsk")["c"], queen["c"])
expect("arms: one per chat, busiest first", [a["chat"] for a in scene["arms"]], ["p111", "g999"])
expect("core clusters", sorted(c["label"] for c in C if c["kind"] == "core"), ["佳树的日记", "关于兄长大人", "此刻记着"])
expect("days list starts at life-day start", [d["label"] for d in scene["days"]], ["10月28日"])

pairs = {(min(a, b), max(a, b)) for a, b, _, _ in E}
expect("edges reference real points", all(0 <= a < len(P) and 0 <= b < len(P) and a != b for a, b, _, _ in E), True)
expect("no duplicate edges", len(pairs), len(E))
fact = next(p for p in P if p["k"] == "fact")
src = [e for e in E if e[3] == "s" and fact["id"] in e[:2]]
expect("fact linked to the line it came from", [P[e[0] if e[1] == fact["id"] else e[1]]["text"] for e in src], ["我在外地读书，最近在玩pjsk"])
mem = next(p for p in P if p["k"] == "memory" and "自我介绍" in p["text"])
expect("memory linked to what it summarised", any(e[3] == "r" and mem["id"] in e[:2] for e in E), True)
diary = next(p for p in P if p["k"] == "diary")
expect("diary linked to that day's lines", any(e[3] == "r" and diary["id"] in e[:2] for e in E), True)
expect("diary brief kept", diary["brief"], "记住了兄长大人的学校")
expect("keywords skip QQ-id and numeric entities", all(not k.startswith("aiocqhttp") and k != "555" for p in P for k in p.get("kw", [])), True)
expect("pjsk keyword found", "pjsk" in owner_line.get("kw", []), True)

expect("no weights without memory_weight", (scene["meta"]["weighed"], any("g" in p for p in P)), (0, False))

# ---------------------------------------------------------------- 分量（记忆轻重）
write(pd / "astrbot_plugin_memory_weight" / "state.json", {
    "paras": {
        "h1": {"g": 3, "uses": 0, "last_used": None, "created": ts("2026-10-28 13:40")},
        "h2": {"g": 0, "uses": 0, "last_used": None, "created": ts("2026-10-18 13:30")},  # 琐碎、10 天前 → 忘了大半
        "gone": {"g": 2, "created": ts("2026-10-28 13:40")},
    },
    "keepsakes": [
        {"id": "k1", "qq": "111", "chat": "p111", "memory": "兄长大人在外地读书", "quote": "我在外地读书", "g": 2,
         "created": ts("2026-10-28 13:30"), "said": 2, "uses": 1, "last_used": ts("2026-10-28 20:00"), "retired": False},
        {"id": "k2", "qq": "111", "chat": "p111", "memory": "没有这句", "quote": "完全不存在的一句话啊", "g": 3,
         "created": ts("2026-10-28 13:30")},
        {"id": "k3", "qq": "111", "chat": "p111", "memory": "删掉的", "quote": "晚安佳树", "g": 3,
         "created": ts("2026-10-29 01:30"), "removed": True},
    ],
})
write(root / "config" / "astrbot_plugin_memory_weight_config.json", {"half_life_days": {"g0": 4, "g1": 15, "g2": 90, "g3": 365}}, bom=True)
w = memsea.build_scene(root, now=ts("2026-10-29 02:00"))
WP = {p["text"]: p for p in w["points"]}
expect("weighed count", w["meta"]["weighed"], 3)
expect("memory gets its gravity", WP["兄长大人自我介绍：在外地读书，玩pjsk"]["g"], 3)
expect("trivial old fact fades", WP["晴川在外地读书"]["ret"] < 0.25, True)
kept = WP["我在外地读书，最近在玩pjsk"]
expect("keepsake lands on the exact line", (kept["g"], kept["keep"]["memory"], kept["keep"]["said"]), (2, "兄长大人在外地读书", 2))
expect("used keepsake still fresh", kept["ret"] > 0.99, True)
expect("removed keepsake ignored", "g" in WP["晚安佳树，我先睡了"], False)
expect("unmatched keepsake warns", sum("没在聊天记录里找到原句" in x for x in w["meta"]["warnings"]), 1)
expect("unrated lines untouched", "g" in WP["今天吃晚饭了吗"], False)
expect("hash not leaked into page data", any("hash" in p for p in w["points"]), False)
(pd / "astrbot_plugin_memory_weight" / "state.json").unlink()

# ---------------------------------------------------------------- 网页
html = memsea.render_html(scene)
m = re.search(r'<script id="sea-data" type="application/json">(.*?)</script>', html, re.S)
expect("data tag present", bool(m), True)
expect("chat text cannot close the script tag", "</script><b>" in html, False)
expect("embedded data round-trips", json.loads(m.group(1))["points"][queen["id"]]["text"], queen["text"])
expect("placeholder gone", "__SEA_DATA__" in html, False)

out = root.parent / "out" / "sea.html"
res = memsea.cmd_build(root, out, open_after=False)
expect("build ok", res["ok"], True)
expect("build wrote file", out.exists(), True)
expect("build stars", res["stars"], len(P))

empty = root.parent / "empty"
(empty / "plugin_data").mkdir(parents=True)
e_scene = memsea.build_scene(empty)
expect("empty data still builds", (len(e_scene["points"]), len(e_scene["edges"])), (0, 0))
expect("empty data warns", len(e_scene["meta"]["warnings"]), 2)

bad = root.parent / "bad-out.json"
rc = memsea.main(["build", "--data-dir", str(root), "--html", str(root.parent / "x" / "y.html"), "--out", str(bad)])
expect("cli exit code", rc, 0)
expect("cli result json", json.loads(bad.read_text(encoding="utf-8"))["ok"], True)

# ---------------------------------------------------------------- 关于自己 + 知识本（2026-11-07 加）
extra = root.parent / "extra"
epd = extra / "plugin_data"
write(extra / "cmd_config.json", {"timezone": "Asia/Shanghai"})
write(epd / "astrbot_plugin_kaju_life" / "log" / "2026-10-29.jsonl",
      json.dumps({"t": "13:00", "c": "p111", "u": "111", "n": "", "x": "Blue Archive 的角色头上都有光环"}, ensure_ascii=False) + "\n")
write(epd / "astrbot_plugin_kaju_life" / "self_facts.json",
      [{"fact": "佳树是妹妹，比哥哥小两岁。", "kind": "家人"}, {"fact": "  ", "kind": "空的不要"}, {"fact": "佳树读初三。"}])
write(epd / "astrbot_plugin_kaju_learn" / "book.json", {"book": {"cards": {
    "a1": {"id": "a1", "name": "Blue Archive", "kind": "游戏", "what": "角色头上顶着光环的手机游戏",
           "facts": [{"x": "角色头上都有光环"}], "view": "画风挺可爱", "days": ["2026-10-29"], "used": 2,
           "srcs": [{"chat": "p111", "t": ts("2026-10-29 13:00")}], "t0": ts("2026-10-29 13:00")},
    "a2": {"id": "a2", "name": "删掉的", "kind": "", "what": "x", "facts": [], "removed": True, "t0": ts("2026-10-29 13:00")},
}}})
xs = memsea.build_scene(extra)
XP = xs["points"]
me = [p for p in XP if p["k"] == "me"]
kn = [p for p in XP if p["k"] == "know"]
expect("self facts: blanks dropped", [p["text"] for p in me], ["佳树是妹妹，比哥哥小两岁。", "佳树读初三。"])
expect("self facts: kind in who", me[0]["who"], "关于自己 · 家人")
expect("self facts: at timeline start", me[0]["t"], min(p["t"] for p in XP))
expect("knowledge: removed cards skipped", [p["who"] for p in kn], ["Blue Archive · 游戏"])
expect("knowledge: text = what + facts", kn[0]["text"], "角色头上顶着光环的手机游戏\n角色头上都有光环")
expect("knowledge: brief", kn[0]["brief"], "知道一些，用上过 2 次。她觉得：画风挺可爱")
msg = next(p["id"] for p in XP if p["k"] in ("owner", "other"))
expect("knowledge: linked to where she learned it",
       any(e[3] == "s" and {e[0], e[1]} == {kn[0]["id"], msg} for e in xs["edges"]), True)
expect("new kinds sit in the centre", {xs["clusters"][p["c"]]["kind"] for p in me + kn}, {"core"})

# ---------------------------------------------------------------- 真数据（只读）
if (memsea.DATA / "plugin_data").is_dir():
    real = memsea.build_scene()
    expect("real: has stars", len(real["points"]) > 0, True)
    expect("real: no webchat", any("webchat" in str(p.get("chat", "")) or p.get("chat") == "pastrbot" for p in real["points"]), False)
    expect("real: every point has a cluster", all(0 <= p["c"] < len(real["clusters"]) for p in real["points"]), True)
    print(f"real data: {len(real['points'])} stars, {len(real['edges'])} lines, {len(real['clusters'])} clusters")

print("ALL PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
