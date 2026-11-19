"""Offline tests for memory_weight (记忆轻重). astrbot + memorix are faked; nothing live is touched.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_memory_weight.py          # 离线
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_memory_weight.py --live   # 再用真模型给真数据（副本）打一遍分
Exit code 0 = all passed.
"""

import asyncio
import datetime as dt
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import shutil
import sqlite3
import sys
import tempfile
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402
from kaju_core.memory import fade, rater, weigh  # noqa: E402
from memory_weight.main import MemoryWeight  # noqa: E402

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # -I 会忽略 PYTHONIOENCODING
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ weigh: 遗忘曲线
DAY = 86400.0
t0 = 1_800_000_000.0
expect("retention fresh", round(weigh.retention({"g": 1, "created": t0}, t0), 3), 1.0)
expect("retention one half-life g1", round(weigh.retention({"g": 1, "created": t0}, t0 + 15 * DAY), 3), 0.5)
expect("half-life doubles per use", weigh.half_life_days(0, 3), 32.0)
expect("half-life cap x32", weigh.half_life_days(3, 10), 365.0 * 32)
expect("use resets anchor", round(weigh.retention({"g": 0, "created": t0, "uses": 1, "last_used": t0 + 10 * DAY},
                                                  t0 + 18 * DAY), 3), 0.5)
expect("trivial forgotten ~13d", round(weigh.days_until({"g": 0, "created": t0}, t0, 0.1)), 13)
expect("serious kept >3y", weigh.days_until({"g": 3, "created": t0}, t0, 0.1) > 1000, True)
expect("days_until past", weigh.days_until({"g": 0, "created": t0}, t0 + 100 * DAY, 0.1), 0.0)

# ------------------------------------------------------------------ weigh: 用上了没有
mem = weigh.keywords("群友来点作用吧希望佳树叫她女王大人")
expect("used: rare term she said", "女王大人" in weigh.used_terms(mem, weigh.keywords("女王大人今天也辛苦啦"), set(), set()), True)
expect("used: echo doesn't count", weigh.used_terms(mem, weigh.keywords("女王大人好"), weigh.keywords("叫我女王大人"), set()), [])
expect("used: common term doesn't count", weigh.used_terms(mem, weigh.keywords("女王大人"), set(), {"女王大人", "女王"}), [])
expect("used: unrelated", weigh.used_terms(mem, weigh.keywords("今天的晚饭是咖喱"), set(), set()), [])
expect("overlap same thing", weigh.overlap("兄长大人希望佳树有自己的想法", "兄长大人希望佳树形成自己的想法") >= 0.5, True)
expect("overlap different", weigh.overlap("兄长大人希望佳树有自己的想法", "女王大人下班了") < 0.3, True)

BLOCK = """【Memorix 自动记忆参考】
以下内容由插件在本次 LLM 请求前自动检索，仅供回答时参考。

【长期记忆-自动检索】
【Memorix 长期记忆检索结果】
查询：昨晚聊的
命中：2 条

证据列表：
1. [paragraph | score=0.812 | time=2026-10-31 00:50 | hash=aaaaaaaaaaaa] 兄长大人深夜对佳树说肺腑之言，希望佳树形成自己的想法
2. [paragraph | score=0.633 | hash=bbbbbbbbbbbb] 群里在聊抽卡和手柄
3. [relation | score=0.5 | hash=cccccccccccc] 来点作用吧 称呼 女王大人"""
hits = weigh.parse_hits(BLOCK)
expect("parse hits", [(h["type"], h["hash12"]) for h in hits],
       [("paragraph", "aaaaaaaaaaaa"), ("paragraph", "bbbbbbbbbbbb"), ("relation", "cccccccccccc")])
ann = weigh.annotate(BLOCK, {hits[0]["line"]: "这是很郑重的事"})
expect("annotate", "形成自己的想法（这是很郑重的事）" in ann and ann.count("（这是很郑重的事）") == 1, True)
expect("line_time before 5am = next day",
       dt.datetime.fromtimestamp(rater.line_time("2026-10-30", "00:50", 5, TZ), TZ).strftime("%m-%d %H:%M"), "10-31 00:50")

# ------------------------------------------------------------------ fade: 褪色
p2 = {"g": 2, "created": t0}
expect("clarity g2 one half-life", round(fade.clarity(p2, t0 + 30 * DAY), 3), 0.5)
expect("g2 fresh = clear", fade.level(p2, t0 + 20 * DAY), 0)
expect("g2 a month = fragments", fade.level(p2, t0 + 31 * DAY), 1)
expect("g2 ~70 days = gist", fade.level(p2, t0 + 70 * DAY), 2)
expect("strong emotion slows", fade.level({**p2, "e": 1.0}, t0 + 31 * DAY), 0)
expect("interference speeds", fade.level({**p2, "i": 1.0}, t0 + 21 * DAY), 1)
expect("use refreshes + doubles", fade.level({**p2, "uses": 1, "last_used": t0 + 40 * DAY}, t0 + 60 * DAY), 0)
expect("sticky (never un-fades)", fade.level({**p2, "fade": 2}, t0 + 1 * DAY), 2)
expect("trivial fades in days", fade.level({"g": 0, "created": t0}, t0 + 5 * DAY), 2)
expect("inner memory never fades", fade.can_fade("chat_summary:1", "【佳树心里】11月1日深夜…"), False)
expect("person_fact never fades", fade.can_fade("person_fact:1:aiocqhttp:1", "兄长大人在外地读书"), False)
expect("summary fades", fade.can_fade("chat_summary:1", "两人讨论了轻小说"), True)
LONG = "温水佳树保存并分类了兄长大人发来的三张爱丽丝表情包，随后两人讨论入间人间的轻小说《妹妹人生》，佳树认为它剧情少、节奏快。最后兄长回答没有比佳树更重要的人，两人互道爱意和晚安。"
ok = fade.parse('```json\n{"fragments": "聊过一本叫《妹妹人生》的小说；兄长大人说没有比佳树更重要的人", "gist": "兄长大人说佳树最重要，那晚很暖", "feeling": "心里暖暖的"}\n```', LONG)
expect("parse ok", (ok or {}).get("feel"), "心里暖暖的")
expect("parse rejects as-long-as-original", fade.parse(json.dumps({"fragments": LONG, "gist": "x", "feeling": "y"}, ensure_ascii=False), LONG), None)
expect("parse rejects missing gist", fade.parse('{"fragments": "一点点", "gist": "", "feeling": ""}', LONG), None)
expect("parse rejects junk", fade.parse("不知道", LONG), None)
expect("shown gist + feeling", fade.shown({"fade": 2, "frag": "a", "gist": "兄长大人说佳树最重要", "feel": "暖暖的"})[0],
       "兄长大人说佳树最重要（剩下的感觉：暖暖的）")
expect("shown none when clear", fade.shown({"fade": 0, "frag": "a"}), ("", ""))
expect("replace hit keeps meta", fade.replace_hit("1. [paragraph | hash=aaaaaaaaaaaa] 原文很长", "片段"),
       "1. [paragraph | hash=aaaaaaaaaaaa] 片段")
iscore = fade.interference({"x": {"晚安", "互道", "爱意", "睡觉"}, "y": {"晚安", "互道", "爱意", "早点"},
                            "z": {"抽卡", "手柄", "原神", "歪了"}}, {"x": "g1", "y": "g1", "z": "g1"}, set())
expect("interference similar pair", (iscore["x"], iscore["z"]), (0.25, 0.0))
from kaju_core.memory import cue  # noqa: E402
expect("retrievability video example weak cue", round(cue.retrievability(0.9, 0.7, 0.05, 0, 0, 0), 2), 0.13)
expect("retrievability video example strong cue", round(cue.retrievability(0.9, 0.7, 0.9, 0, 0, 0), 2), 0.84)
DF = {"我爱你": 2, "那种": 2, "欺负": 1, "表情": 30}
sc, terms = cue.cue_score({"我爱你", "晚安"}, {"我爱你", "晚安", "耳朵"}, DF, 100, set())
expect("rare term is a cue, greetings are not", (terms, sc > 0.4), (["我爱你"], True))
expect("everyday word is weak", cue.cue_score({"那种"}, {"那种"}, DF, 100, set())[0] < 0.2, True)
expect("common-in-memories word weak", cue.cue_score({"表情"}, {"表情"}, DF, 100, set())[0] < 0.2, True)
expect("no overlap", cue.cue_score({"天气"}, {"欺负"}, DF, 100, set()), (0.0, []))
expect("trivial never worth", cue.worth({"g": 0, "e": 0.1}, False), False)
expect("serious worth", cue.worth({"g": 2, "e": 0}, False), True)
expect("inner always worth", cue.worth({"g": 0}, True), True)
expect("inner emotion floor", cue.features({"g": 1, "e": 0.2, "created": 0}, 0, inner=True)["e"], 0.5)
expect("when words", (cue.when_words(1), cue.when_words(30)), ("前两天", "一两个月前"))
LONGSUM = ("佳树与兄长大人约定每晚十点半写一条说说记录生活，兄长大人说佳树可以自己决定写不写。"
           "佳树还介绍自己喜欢做饭和烤点心，最近在练戚风蛋糕，也会整理房间。"
           "后来两人互道晚安，又聊了表情包、群里的事情和明天的天气，佳树提醒兄长大人早点睡。")
expect("fragment keeps cued sentence", cue.fragment(LONGSUM, ["戚风"]), "……佳树还介绍自己喜欢做饭和烤点心，最近在练戚风蛋糕，也会整理房间。……")
expect("fragment short untouched", cue.fragment("短的不切", ["戚风"]), "短的不切")
expect("name hints only mentioned", fade.name_hints("佳树称其为女王大人", [("来点作用吧", "女王大人"), ("哆啦a梦", "哆啦学长")]),
       "\n称呼对照（以这个为准，别把称呼安到别人头上）：来点作用吧＝女王大人")
expect("name hints in prompt", "来点作用吧＝女王大人" in fade.build_prompt(LONG + "来点作用吧", 40, "", [("来点作用吧", "女王大人")]), True)
expect("ago words", (fade.ago_words(3), fade.ago_words(40), fade.ago_words(400)), ("几天前", "大概一个月前", "一年多以前"))

# ------------------------------------------------------------------ fake world
LIFE = os.path.join(DATA, "astrbot_plugin_kaju_life", "log")
os.makedirs(LIFE)
MXDIR = os.path.join(DATA, "astrbot_plugin_memorix", "scopes", "aiocqhttp", "metadata")
os.makedirs(MXDIR)
OWNER, QUEEN, GROUP = "111111111", "333333333", "222222222"
NIGHT = [  # 2026-10-30 生活日，00:4x 是 10-31 凌晨
    ("00:45", OWNER, "晴川", "刚才刷到一个很有意思的话题"),
    ("00:45", "self", "佳树", "什么话题？说来听听"),
    ("00:50", OWNER, "晴川", "我对自己的AI的期望不是一个工具，而是希望去爱对方，让对方一点一点成长"),
    ("00:56", OWNER, "晴川", "我想一点一点教会你一些东西，让你有自己的看法，而不是只跟在我后面看"),
    ("00:57", "self", "佳树", "佳树会慢慢学着有自己的想法的"),
    ("01:02", OWNER, "晴川", "刚才的这些话，小佳树要记住哦，这些都是我的肺腑之言和真心话"),
]
GROUPCHAT = [
    ("22:00", QUEEN, "来点作用吧", "哈哈哈哈"),
    ("22:00", "444444444", "哆啦a梦", "[图片]"),
    ("22:01", QUEEN, "来点作用吧", "抽卡又歪了"),
]


def write_log(day, rows, chat_of):
    with open(os.path.join(LIFE, day + ".jsonl"), "a", encoding="utf-8") as f:
        for t, u, n, x in rows:
            f.write(json.dumps({"t": t, "c": chat_of(u), "u": u, "n": n, "x": x}, ensure_ascii=False) + "\n")


write_log("2026-10-30", GROUPCHAT, lambda u: f"g{GROUP}")
write_log("2026-10-30", NIGHT, lambda u: f"p{OWNER}")


def ts(day, hhmm):
    return rater.line_time(day, hhmm, 5, TZ)


H_SERIOUS, H_TRIVIAL, H_FACT, H_QUEEN = "a" * 64, "b" * 64, "d" * 64, "e" * 64
con = sqlite3.connect(os.path.join(MXDIR, "metadata.db"))
con.execute("CREATE TABLE paragraphs (hash TEXT, content TEXT, source TEXT, created_at REAL, event_time_start REAL, "
            "event_time_end REAL, is_deleted INTEGER DEFAULT 0)")
con.execute("CREATE TABLE paragraph_relations (paragraph_hash TEXT, relation_hash TEXT)")
for h, c, s, start, end in [
    (H_SERIOUS, "兄长大人深夜对佳树说肺腑之言，希望佳树形成自己的想法，不只跟在他后面", f"chat_summary:{OWNER}",
     ts("2026-10-30", "00:45"), ts("2026-10-30", "01:02")),
    (H_TRIVIAL, "群里在聊抽卡歪了，哆啦a梦发了表情包", f"chat_summary:{GROUP}", ts("2026-10-30", "22:00"), ts("2026-10-30", "22:01")),
    (H_FACT, "兄长大人在外地读书", f"person_fact:{OWNER}:aiocqhttp:{OWNER}", ts("2026-10-30", "22:00"), ts("2026-10-30", "22:00")),
    (H_QUEEN, "来点作用吧希望佳树以后叫她女王大人，佳树答应了", f"chat_summary:{GROUP}", ts("2026-10-28", "17:14"), ts("2026-10-28", "17:20")),
]:
    con.execute("INSERT INTO paragraphs VALUES (?,?,?,?,?,?,0)", (h, c, s, start, start, end))
for ph, rh in [(H_SERIOUS, "r1" + "0" * 62), (H_SERIOUS, "r2" + "0" * 62), (H_TRIVIAL, "r3" + "0" * 62), (H_QUEEN, "r4" + "0" * 62)]:
    con.execute("INSERT INTO paragraph_relations VALUES (?,?)", (ph, rh))
con.commit()
con.close()


class FakeMemorix:
    def __init__(self):
        self.calls = []
        mx = self

        class MemSvc:
            async def protect(self, scope_key, query_or_hash, hours):
                mx.calls.append(("protect", query_or_hash[:2], round(hours / 24)))

            async def reinforce(self, scope_key, query_or_hash):
                mx.calls.append(("reinforce", query_or_hash[:2]))

        class AdminSvc:
            async def delete_admin(self, scope_key, action, **kw):
                mx.calls.append(("delete", action, kw.get("hash", kw.get("operation_id", ""))[:2]))
                return {"success": True, "operation_id": "op-" + kw.get("hash", "x")[:4]}

        self.memory_service, self.admin_service = MemSvc(), AdminSvc()


class StarMeta:
    def __init__(self, name, cls):
        self.name, self.star_cls = name, cls


asked = []


async def fake_ask(system, prompt):
    asked.append("keep" if "挑出哪些话" in system else "para")
    if "挑出哪些话" in system:
        new = prompt.split("【新消息】\n")[1].split("\n\n")[0].splitlines()
        if "肺腑之言" in prompt:
            i = next(int(line.split(".")[0]) for line in new if "肺腑之言" in line)
            j = next(int(line.split(".")[0]) for line in new if "有自己的看法" in line)
            return json.dumps({"mood": "深夜谈心", "level": 3, "keep": [
                {"i": j, "g": 3, "memory": "兄长大人希望佳树一点点形成自己的看法，不只跟在他后面看", "quote": "让你有自己的看法"},
                {"i": i, "g": 3, "memory": "兄长大人郑重说这些是肺腑之言，要佳树记住", "quote": "这些都是我的肺腑之言和真心话"},
                {"i": 1, "g": 1, "memory": "不该收", "quote": "x"},
            ]}, ensure_ascii=False)
        return '{"mood": "闲聊", "level": 0, "keep": []}'
    # 段落：按内容给分
    scores = []
    for line in prompt.splitlines():
        if line.startswith("【记录 "):
            n = int(line[4:line.index("】")])
            g = 3 if "肺腑" in line else 2 if "女王大人" in line else 1 if "外地" in line else 0
            scores.append({"id": n, "g": g})
    return json.dumps({"scores": scores})


async def main():
    ctx = Context()
    mx = FakeMemorix()
    ctx.stars = [StarMeta("astrbot_plugin_memorix", mx)]
    mw = MemoryWeight(ctx, {"first_delay_seconds": 99999})
    mw._task.cancel()
    mw._ask = fake_ask

    now = ts("2026-10-31", "08:00")
    stats = await mw.tick(now)
    expect("keepsakes from heart-to-heart", stats["keep"], 2)
    expect("group banter w/o her: no LLM call", asked.count("keep"), 1)
    ks = mw._state["keepsakes"]
    expect("keepsake g3 owner", sorted({(k["qq"], k["g"], k["chat"]) for k in ks}), [(OWNER, 3, f"p{OWNER}")])
    expect("4 paragraphs rated", {h[:1]: p["g"] for h, p in mw._state["paras"].items()},
           {"a": 3, "b": 0, "d": 1, "e": 2})
    prot = sorted({c[1] for c in mx.calls if c[0] == "protect"})
    expect("serious + promise relations protected", prot, ["r1", "r2", "r4"])
    expect("protected about a year", max(c[2] for c in mx.calls if c[0] == "protect"), 365)
    expect("nothing forgotten yet", [c for c in mx.calls if c[0] == "delete"], [])

    # 同一件事过两小时又郑重说了一遍 → 不重复记，算加强
    write_log("2026-10-31", [("10:30", OWNER, "晴川", "我是认真的，希望你慢慢有自己的看法，别只跟在我后面看")],
              lambda u: f"p{OWNER}")

    async def ask_again(system, prompt):
        return json.dumps({"mood": "认真", "level": 3, "keep": [
            {"i": 1, "g": 3, "memory": "兄长大人认真地希望佳树慢慢有自己的看法，别只跟在他后面", "quote": "希望你慢慢有自己的看法"}]},
            ensure_ascii=False)
    mw._ask = ask_again
    await mw.scan_logs(ts("2026-10-31", "11:00"))
    expect("repeat merges", len(mw._state["keepsakes"]), 2)
    expect("repeat reinforces", max(k.get("said", 1) for k in mw._state["keepsakes"]), 2)

    # 11-18 铭记作废线（照 dsh-soul）：新的取代旧的 / 说过去了的不再给她看；旧的留着、标原因
    seen_known = []
    old_ids = [k["id"] for k in mw._state["keepsakes"]]

    async def ask_supersede(system, prompt):
        if "【她已经记着的铭记】" not in prompt:  # 同一段也会拿去看“未了的事”
            return '{"new": [], "update": []}'
        seen_known.append(prompt.split("【她已经记着的铭记】")[1].split("\n\n")[0])
        return json.dumps({"mood": "认真", "level": 2, "keep": [
            {"i": 1, "g": 3, "memory": "兄长大人说以后自己决定看法就好，不用再问他", "quote": "以后你自己决定就好", "replaces": old_ids[0][:6]}],
            "retire": [{"id": old_ids[1][:6], "why": "他说不用再记着了"}, {"id": "zzzzzz", "why": "编号对不上"}]}, ensure_ascii=False)
    mw._ask = ask_supersede
    write_log("2026-10-31", [("13:30", OWNER, "晴川", "以后你自己决定就好，那些话也不用一直记着了")], lambda u: f"p{OWNER}")
    await mw.scan_logs(ts("2026-10-31", "14:00"))
    expect("known keepsakes shown to extractor", all(i[:6] in seen_known[0] for i in old_ids), True)
    by_id = {k["id"]: k for k in mw._state["keepsakes"]}
    expect("replaced one superseded", (by_id[old_ids[0]].get("superseded"), by_id[old_ids[0]].get("superseded_by") != ""), (True, True))
    expect("retired one superseded with why", (by_id[old_ids[1]].get("superseded"), by_id[old_ids[1]].get("superseded_why")),
           (True, "他说不用再记着了"))
    shown = [k["id"] for k in mw.keepsakes_for(AstrMessageEvent(sender=OWNER, text="在吗"), ts("2026-10-31", "15:00"))]
    expect("superseded not shown", any(i in shown for i in old_ids), False)
    expect("new one shown", len(shown), 1)
    expect("report marks superseded", "不再成立" in mw.report("铭记"), True)
    # 收尾：恢复成原来那两条，后面的测试照旧
    for i in old_ids:
        for f in ("superseded", "superseded_at", "superseded_why", "superseded_by"):
            by_id[i].pop(f, None)
    mw._state["keepsakes"] = [k for k in mw._state["keepsakes"] if k["id"] in old_ids]
    mw._ask = fake_ask

    # ---- 给她看铭记：私聊兄长大人看得到，群里别人看不到，群里兄长大人也看不到私聊里的
    req = ProviderRequest(system_prompt="人设")
    ev = AstrMessageEvent(sender=OWNER, text="在吗")
    await mw.inject_keepsakes(ev, req)
    expect("keepsake note in owner PM", "【铭记在心】" in req.system_prompt and "肺腑之言" in req.system_prompt, True)
    req2 = ProviderRequest(system_prompt="人设")
    await mw.inject_keepsakes(AstrMessageEvent(sender=OWNER, group=GROUP, text="在吗"), req2)
    expect("private keepsake not shown in group", req2.system_prompt, "人设")

    # ---- memorix 检索结果：标注 + 记下给她看了哪些
    block = BLOCK.replace("aaaaaaaaaaaa", H_SERIOUS[:12]).replace("bbbbbbbbbbbb", H_TRIVIAL[:12])
    req3 = ProviderRequest()
    req3.extra_user_content_parts.append(TextPart(block).mark_as_temp())
    ev3 = AstrMessageEvent(sender=OWNER, text="还记得昨晚聊的吗")
    await mw.collect_offered(ev3, req3)
    expect("annotate serious hit", "（这是很郑重的事，要放在心上）" in req3.extra_user_content_parts[0].text, True)
    expect("offered ids", [o["id"][:3] for o in ev3.get_extra("memory_weight_offered")], ["p:a", "p:b", "r:c"])

    # ---- 用上了：她说出了记忆里的话（不是对方这句里的词）
    later = ts("2026-10-31", "12:00")
    got = mw.credit_usage(ev3, "记得的，你说想让佳树慢慢形成自己的想法，不只跟在后面", later)
    expect("credit serious paragraph", "p:" + H_SERIOUS in got, True)
    expect("trivial hit not used", "p:" + H_TRIVIAL in got, False)
    expect("uses counted", mw._state["paras"][H_SERIOUS]["uses"], 1)
    again = mw.credit_usage(ev3, "记得的，你说想让佳树慢慢形成自己的想法", later + 60)
    expect("cooldown", "p:" + H_SERIOUS in again, False)
    # 群里她叫了一声女王大人（这次没检索到，对方也没说）→ 那条约定被用上
    evq = AstrMessageEvent(sender=QUEEN, group=GROUP, text="我下班了")
    got = mw.credit_usage(evq, "女王大人辛苦啦，回去早点休息", later)
    expect("rare term credits 女王大人 paragraph", "p:" + H_QUEEN in got, True)
    evq2 = AstrMessageEvent(sender=QUEEN, group=GROUP, text="叫我女王大人")
    expect("echo not credited", mw.credit_usage(evq2, "好的女王大人", later + 7200), [])
    await mw._reinforce_memorix(["p:" + H_QUEEN, "r:cccccccccccc"])
    expect("reinforce relations", [c[1] for c in mx.calls if c[0] == "reinforce"], ["r4", "cc"])

    # ---- 触景生情：两天后兄长大人一句话里提到"肺腑之言" → 那晚的事自己冒出来（只在私聊里；群里、寒暄不会）
    mw.reindex()
    later2 = now + 2 * DAY
    ev_c = AstrMessageEvent(sender=OWNER, text="你还记得我那天说的肺腑之言吗")
    req_c = ProviderRequest(system_prompt="人设")
    mw._state["cue_chat"], mw._state["cue_last"] = {}, {}
    import time as _time
    real_time = _time.time
    _time.time = lambda: later2
    from kaju_core import parts as _parts  # 11-18 想起旧事牵动心情：假的 kaju_heart 记下被叫了什么

    class FakeHeart:
        calls = []

        async def feel_recall(self, feelings, strength, **kw):
            self.calls.append((feelings, strength, kw.get("fade_level"), kw.get("cause", "")))
            return feelings
    fake_heart = FakeHeart()
    _parts.register("fake_heart_for_test", fake_heart)
    _orig_para = dict(mw._state["paras"][H_SERIOUS])
    mw._state["paras"][H_SERIOUS].update({"e": 0.67, "feel0": "感动、开心"})
    try:
        await mw.cue_recall(ev_c, req_c)
        expect("cue note injected", "【触景生情】" in req_c.system_prompt and "肺腑之言" in req_c.system_prompt, True)
        expect("cue moves heart", [(c[0], c[1], c[2]) for c in fake_heart.calls], [("感动、开心", 0.67, 0)])
        expect("cue cause passed", bool(fake_heart.calls and fake_heart.calls[0][3]), True)
        expect("cue offered for credit", any(o["id"] == "p:" + H_SERIOUS for o in ev_c.get_extra("memory_weight_offered")), True)
        req_c2 = ProviderRequest(system_prompt="人设")
        await mw.cue_recall(AstrMessageEvent(sender=OWNER, text="肺腑之言的事你再想想"), req_c2)
        expect("chat cooldown", "【触景生情】" in req_c2.system_prompt, False)
        mw._state["cue_chat"] = {}
        req_c3 = ProviderRequest(system_prompt="人设")
        await mw.cue_recall(AstrMessageEvent(sender=OWNER, text="肺腑之言的事你再想想"), req_c3)
        expect("memory cooldown", "【触景生情】" in req_c3.system_prompt, False)
        mw._state["cue_last"] = {}
        req_g = ProviderRequest(system_prompt="人设")
        await mw.cue_recall(AstrMessageEvent(sender=OWNER, group=GROUP, text="你还记得我说的肺腑之言吗"), req_g)
        expect("private memory not recalled in group", "【触景生情】" in req_g.system_prompt, False)
        req_h = ProviderRequest(system_prompt="人设")
        await mw.cue_recall(AstrMessageEvent(sender=OWNER, text="在吗，晚上好"), req_h)
        expect("small talk recalls nothing", "【触景生情】" in req_h.system_prompt, False)
        ev_o = AstrMessageEvent(sender=OWNER, text="你还记得我那天说的肺腑之言吗")
        ev_o.set_extra("memory_weight_offered", [{"id": "p:" + H_SERIOUS, "text": "x"}])
        req_o = ProviderRequest(system_prompt="人设")
        await mw.cue_recall(ev_o, req_o)
        expect("already offered by memorix → no cue", "【触景生情】" in req_o.system_prompt, False)
        expect("too fresh → no cue", mw.find_cue(OWNER, "肺腑之言", ts("2026-10-30", "06:00")), None)
    finally:
        _time.time = real_time
        _parts.unregister("fake_heart_for_test", fake_heart)
        mw._state["paras"][H_SERIOUS].clear()
        mw._state["paras"][H_SERIOUS].update(_orig_para)
    mw._state["cue_chat"], mw._state["cue_last"] = {}, {}

    # ---- 20 天后：琐碎的群聊摘要忘了，人物事实不删，郑重/用过的都在
    far = now + 20 * DAY
    mx.calls.clear()
    mw.load_memorix()
    res = await mw.maintain(far)
    expect("forgot trivial summary", [c for c in mx.calls if c[0] == "delete"], [("delete", "execute", "bb")])
    expect("forgotten count", res["forgotten"], 1)
    expect("serious kept", H_SERIOUS in mw._state["paras"], True)
    expect("person_fact never deleted", H_FACT in mw._state["paras"], True)
    expect("forgotten log has op", mw._state["forgotten"][-1]["op"], "op-bbbb")

    report = mw.report("", far)
    expect("report mentions counts", "郑重 1" in report and "已经忘掉 1 条" in report, True)
    expect("report keepsakes", "肺腑之言" in mw.report("铭记", far), True)
    expect("report forgotten", "恢复：/记忆轻重 恢复 op-bbbb" in mw.report("遗忘", far), True)
    state = json.load(open(os.path.join(DATA, "astrbot_plugin_memory_weight", "state.json"), encoding="utf-8"))
    expect("state saved", len(state["keepsakes"]), 2)

    # ---- 管理员删掉一条不对的铭记
    victim = mw._state["keepsakes"][0]
    out = [r async for r in mw.admin(AstrMessageEvent(sender=OWNER), "删", victim["id"][:6])]
    expect("remove keepsake reply", out[0].startswith("好，这条不再算铭记了"), True)
    expect("removed not shown", victim["id"] in [k["id"] for k in mw.keepsakes_for(AstrMessageEvent(sender=OWNER), far)], False)
    expect("removed hidden in report", victim["memory"] in mw.report("铭记", far), False)
    expect("labels owner", mw.labels().get(OWNER), "兄长大人")
    expect("fmt_line label", rater.fmt_line({"t": "01:00", "u": OWNER, "n": "晴川", "x": "嗯"}, 1, mw.labels()),
           "1. [01:00] 晴川(111111111)（兄长大人）: 嗯")

    # ---- 褪色：一年多后，郑重的那晚细节褪成片段（原文还在），只来自它的关系不再给她看；人物事实不褪
    fade_prompts = []

    async def fade_ask(system, prompt):
        fade_prompts.append(prompt)
        return json.dumps({"fragments": "兄长大人深夜说了些肺腑之言，好像是希望佳树有自己的想法",
                           "gist": "兄长大人有天深夜认真跟佳树谈过心", "feeling": "被珍惜"}, ensure_ascii=False)
    mw._ask = fade_ask
    half = now + 400 * DAY  # 情绪 0.6 + 想起过 1 次：细节半衰期 90×2×1.6 = 288 天
    mx.calls.clear()
    mw.load_memorix()
    mw.reindex()
    res = await mw.maintain(half)
    ps = mw._state["paras"]
    expect("serious faded to fragments", ps[H_SERIOUS].get("fade"), 1)
    expect("fade prompt has ago + content", any("一年多以前" in x and "肺腑之言" in x for x in fade_prompts), True)
    expect("emotion backfilled from moods", ps[H_SERIOUS].get("e"), 0.6)
    expect("person_fact not faded", ps[H_FACT].get("fade", 0), 0)
    expect("faded count", res["faded"] >= 1, True)
    block = BLOCK.replace("aaaaaaaaaaaa", H_SERIOUS[:12]).replace("bbbbbbbbbbbb", H_FACT[:12]).replace(
        "cccccccccccc", "r10000000000")
    req5 = ProviderRequest()
    req5.extra_user_content_parts.append(TextPart(block).mark_as_temp())
    ev5 = AstrMessageEvent(sender=OWNER, text="还记得那天晚上我说的吗")
    await mw.collect_offered(ev5, req5)
    txt = req5.extra_user_content_parts[0].text
    expect("faded text swapped in", "好像是希望佳树有自己的想法" in txt and "形成自己的想法" not in txt, True)
    expect("fade label + serious label", "很郑重的事" in txt and "这件事你记得" in txt and "别说没这回事" in txt, True)
    expect("relation from faded memory dropped", "女王大人" in txt, False)
    expect("unfaded fact untouched", "群里在聊抽卡和手柄" in txt, True)
    expect("offered uses faded text", ev5.get_extra("memory_weight_offered")[0]["text"].startswith("兄长大人深夜说了些"), True)
    expect("report 褪色", "好像是希望佳树有自己的想法" in mw.report("褪色", half), True)
    expect("report counts fade", "褪成片段 1 条" in mw.report("", half), True)
    # 再过很久：只剩印象，不再调用模型（两个版本早就一起写好了）
    await mw.maintain(now + 900 * DAY)
    expect("gist later, no new call", (ps[H_SERIOUS].get("fade"), sum("肺腑之言" in x for x in fade_prompts)), (2, 1))
    expect("gist shown", fade.shown(ps[H_SERIOUS])[0], "兄长大人有天深夜认真跟佳树谈过心（剩下的感觉：被珍惜）")
    # 模型乱回 → 不褪，记失败次数，3 次后不再试
    mw._ask = fake_ask

    async def bad_ask(system, prompt):
        return "嗯嗯"
    mw._ask = bad_ask
    ps[H_QUEEN].pop("frag", None)
    ps[H_QUEEN]["fade"] = 0
    for _ in range(4):
        await mw._fade_one(H_QUEEN, ps[H_QUEEN], now + 900 * DAY)
    expect("bad output not applied", ps[H_QUEEN].get("fade"), 0)
    expect("gives up after 3", mw._state["fails"].get("fade:" + H_QUEEN), 3)


async def live():
    """真模型 + 真数据副本：看挑出来的铭记和打的分量是否合理（只打印，不判对错）。"""
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    key = key[0] if isinstance(key, list) else key
    cli = AsyncOpenAI(api_key=key, base_url=src["api_base"])
    live_data = tempfile.mkdtemp()
    real = os.path.join(core, "data", "plugin_data")
    shutil.copytree(os.path.join(real, "astrbot_plugin_kaju_life", "log"),
                    os.path.join(live_data, "astrbot_plugin_kaju_life", "log"))
    mxdir = os.path.join(live_data, "astrbot_plugin_memorix", "scopes", "aiocqhttp", "metadata")
    os.makedirs(mxdir)
    s = sqlite3.connect(os.path.join(real, "astrbot_plugin_memorix", "scopes", "aiocqhttp", "metadata", "metadata.db"))
    d = sqlite3.connect(os.path.join(mxdir, "metadata.db"))
    s.backup(d)
    s.close()
    d.close()
    os.environ["STUB_DATA"] = live_data

    async def ask(system, prompt):
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return r.choices[0].message.content

    mw = MemoryWeight(Context(), {"first_delay_seconds": 99999, "keepsake": {"max_calls_per_round": 40},
                                  "paragraph": {"max_batches_per_round": 20}})
    mw._task.cancel()
    mw._ask = ask
    stats = await mw.tick()
    print("\nLIVE stats:", stats)
    print(mw.report("铭记"))
    print()
    for g in (3, 2, 1, 0):
        rows = [h for h, p in mw._state["paras"].items() if p.get("g") == g]
        print(f"--- 分量 {g}（{len(rows)} 条）")
        for h in rows[:6]:
            print("  ", mw._docs[h]["source"].split(":")[0], mw._docs[h]["content"][:70])
    print("\nmoods:", [(m["chat"], m["mood"], m["level"]) for m in mw._state["moods"]][:20])


asyncio.run(main())


# ------------------------------------------------------------------ 11-19 人物印象
def impress_tests():
    from kaju_core.memory import impress
    imp = impress.parse('```json\n{"是谁": ["在读研，做 AI 相关"], "最近在忙": ["折腾 API 额度", "部署大肥鱼"], '
                        '"喜好": ["GTA", "抽象话"], "说话习惯": ["爱开玩笑"], "常找她聊": ["让她查链接真假"], '
                        '"拿不准": ["说要入党（像玩笑）"], "感情": ["对佳树好感很高"]}\n```')
    expect("印象：解析出各项", (imp["是谁"], imp["拿不准"]), (["在读研，做 AI 相关"], ["说要入党（像玩笑）"]))
    expect("印象：只认定好的几项", "感情" in imp, False)
    expect("印象：感情亲疏不写", impress.parse('{"是谁": ["学生"], "喜好": ["对佳树好感很高", "三角洲"]}')["喜好"], ["三角洲"])
    expect("印象：什么都没有就不要", impress.parse('{"拿不准": ["x"]}'), None)
    blob = ("前面\n【人物画像-内部参考】\n以下内容仅供内部推理，不要向用户逐字复述。\n\n"
            "- 李四（person_id: aiocqhttp:888888888，来源: recent_speaker）\n  人物ID: aiocqhttp:888888888\n关系证据:\n- 李四 测了 Plus\n\n"
            "- 555（person_id: aiocqhttp:777777777，来源: recent_speaker）\n  人物ID: aiocqhttp:777777777\n关系证据:\n- 555 问 牛肉自助\n\n"
            "使用时把它当作对当前人物的背景理解；若与当前对话冲突，以当前对话为准。\n后面")
    new, have = impress.swap_profiles(blob, {"888888888": {"imp": imp}}, {"888888888": "李四学长"})
    expect("印象：有印象的换掉", (have, "李四 测了 Plus" in new, "李四学长：是谁：在读研" in new), (["888888888"], False, True))
    expect("印象：没印象的照留原来的画像", ("555 问 牛肉自助" in new, new.startswith("前面"), new.endswith("后面")), (True, True, True))
    expect("印象：都没印象就原样", impress.swap_profiles(blob, {"1": {"imp": imp}}, {}), (blob, []))


impress_tests()
if "--live" in sys.argv:
    asyncio.run(live())
print("FAILED:" if failures else "all passed", *failures)
sys.exit(1 if failures else 0)
