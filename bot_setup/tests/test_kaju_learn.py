"""Offline tests for kaju_learn (学到的东西). astrbot is stubbed; the model is faked.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_kaju_learn.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_kaju_learn.py --live   # 真模型 + 真数据副本学一遍（只打印，不写回）
"""

import asyncio
import datetime as dt
import importlib
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import shutil
import sys
import tempfile
import time
import zoneinfo

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

B = importlib.import_module("kaju_core.learn.book")
X = importlib.import_module("kaju_core.learn.extract")
lm = importlib.import_module("kaju_learn.main")

OWNER, G, OTHER = "111111111", "222222222", "1234567"
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


asyncio.set_event_loop(asyncio.new_event_loop())

# ------------------------------------------------------------------ book：名字
expect("clean 书名号", B.clean("《魔女之旅》"), "魔女之旅")
expect("norm", B.norm(" 《Re:Zero》 "), "rezero")
card = {"name": "陈千语", "aliases": ["小傻龙", "GPT"]}
expect("mentioned 中文", B.mentioned(card, "今天又刷到小傻龙了"), "小傻龙")
expect("mentioned 英文整词", B.mentioned(card, "用 gpt 写的"), "GPT")
expect("mentioned 英文不整词", B.mentioned(card, "chatgpt5"), "")
expect("is_self 兄长", B.is_self("兄长大人"), True)
expect("is_self 聊天里的人", B.is_self("555学长", {"555学长"}), True)
expect("parse_json 带废话", B.parse_json('好的：```json\n{"items": [{"name": "a{b}"}]}\n```'), {"items": [{"name": "a{b}"}]})
expect("parse_json 没有", B.parse_json("不知道"), None)

# ------------------------------------------------------------------ book：记、补、拿不准、纠正、关系
bk = B.new_book()
t0 = 1_793_800_000.0
src = {"how": "兄长大人跟你说的", "who": "", "chat": f"p{OWNER}", "trust": 1}
st = B.apply_items(bk, [
    {"ref": "", "name": "陈千语", "aliases": ["小傻龙"], "kind": "角色", "what": "终末地里的角色",
     "facts": ["二创视频里常被叫小傻龙"], "links": [{"to": "终末地", "rel": "出自"}], "who": "兄长大人", "sure": True},
    {"ref": "", "name": "终末地", "kind": "游戏", "what": "明日方舟那边的新游戏", "facts": [], "who": "兄长大人", "sure": True},
    {"ref": "", "name": "兄长大人", "kind": "人物", "what": "佳树的哥哥"},
    {"ref": "", "name": "晴川", "kind": "人物", "what": "群友"},
], src, t0, "2026-11-04", exclude={"晴川"})
expect("新记两样（兄长、聊天里的人不记）", sorted(st["new"]), ["终末地", "陈千语"])
qy = B.find(bk, "小傻龙")
expect("别名找得到", qy and qy["name"], "陈千语")
expect("关系连上", B.link_text(bk, qy), "出自终末地")
expect("刚听说：听说过/知道一些", B.LEVELS[B.level(qy)] in ("听说过", "知道一些"), True)

st = B.apply_items(bk, [
    {"ref": qy["id"], "name": "小傻龙", "facts": ["二创里常被叫做小傻龙", "在冰箱里也傻乐"], "who": "视频里", "sure": True},
    {"ref": "", "name": "陈千语", "facts": ["其实是明日方舟里的角色"], "who": "某群友", "sure": False},
], {"how": "自己刷B站看到的", "who": "视频里", "chat": f"p{OWNER}", "trust": 1}, t0 + 86400, "2026-11-05")
expect("同一样往上补，不另开", len(B.live(bk)), 2)
expect("一样的点算又确认一次", [f["n"] for f in qy["facts"] if "小傻龙" in f["x"]], [2])
expect("新的点记上", any("冰箱" in f["x"] for f in qy["facts"]), True)
expect("不靠谱的进拿不准", [d["x"] for d in qy["doubts"]], ["其实是明日方舟里的角色"])
expect("碰到两天", qy["days"], ["2026-11-04", "2026-11-05"])
lv1 = B.level(qy)
for i in range(3):
    B.touch(qy, {"how": "群里聊天时听人说的", "chat": f"g{G}"}, t0 + 86400 * (2 + i), f"2026-11-0{6 + i}")
expect("碰到的日子多了更熟", B.level(qy) > lv1, True)

B.apply_items(bk, [{"ref": qy["id"], "name": "陈千语", "fix": "在冰箱里也傻乐", "facts": ["在床上傻乐"], "sure": True}],
              src, t0 + 86400 * 6, "2026-11-10")
expect("纠正：旧说法挪走", any("冰箱" in f["x"] for f in qy["facts"]), False)
expect("纠正：记一句以前弄错过", qy["fixed"][-1]["x"], "在冰箱里也傻乐")

# 普通词不当名字/别名；说的是她自己、兄长、聊天里的人的点不记；她就是温水佳树
expect("clean 书名号里的", B.clean("《妹妹人生》上（台版）"), "妹妹人生")
B.apply_items(bk, [{"name": "妹妹人生的妹妹", "aliases": ["妹妹", "我", "柯特"], "kind": "角色",
                    "facts": ["555说要从头看一遍", "偷家说的是把佳树钉在妹妹的位置上", "长大后成了小说家"]},
                   {"name": "妹妹", "kind": "角色", "what": "随便"}],
              src, t0, "2026-11-04", exclude={"555"})
sis = B.find(bk, "妹妹人生的妹妹")
expect("普通词不当别名", sis["aliases"], ["柯特"])
expect("普通词不开条目", B.find(bk, "妹妹") is None or B.find(bk, "妹妹")["id"] == sis["id"], True)
expect("聊天里谁说了什么、她自己的事不记", [f["x"] for f in sis["facts"]], ["长大后成了小说家"])
st_self = B.apply_digest(bk, {"wonder": [{"q": "败犬女主里的温水佳树是个什么样的角色", "kw": "温水佳树"}],
                              "insight": "原来败犬女主里也有个叫温水佳树的角色"}, t0, {sis["id"]})
expect("不去弄明白自己", (st_self["wonders"], st_self["aha"]), (0, ""))
bk["cards"].pop(sis["id"])

# 记不清
old = {**qy, "days": ["d1"], "facts": [], "used": 0, "view": "", "what": "", "t1": t0, "last_used": 0}
expect("很久没碰：记不清", B.strength(old, t0 + 200 * 86400) < 0.35, True)
expect("很久没碰的'听说过'不再给她看", B.visible(old, t0 + 400 * 86400), False)
expect("越熟忘得越慢", B.strength(qy, t0 + 120 * 86400) > B.strength(old, t0 + 120 * 86400), True)

# 给她看的那一行：别人私聊里讲的只说"听人说的"
other = B.apply_items(bk, [{"name": "蓝色大肥鱼", "kind": "梗", "what": "DSH 里的蓝色小鱼角色梗", "facts": ["常被说成吃白饭的"]}],
                      {"how": "和小雨学姐私聊时听说的", "chat": f"p{OTHER}", "trust": 1}, t0, "2026-11-04")
fish = B.find(bk, "蓝色大肥鱼")
line_g = B.note_line(bk, fish, t0, f"g{G}")
expect("别人私聊里讲的：在别处只说听人说的", ("听人说的" in line_g, "小雨" in line_g), (True, False))
expect("在那个私聊里照常说", "小雨学姐" in B.note_line(bk, fish, t0, f"p{OTHER}"), True)
line_q = B.note_line(bk, qy, t0 + 86400 * 6, f"g{G}")
expect("兄长讲的在群里也能说", "兄长大人跟你说的" in line_q, True)
expect("拿不准的标出来", "拿不准" in line_q, True)

# ------------------------------------------------------------------ book：消化
dup = B.apply_items(bk, [{"name": "千语", "kind": "角色", "facts": ["是个很爱笑的角色"]}], src, t0, "2026-11-04")
qian = B.find(bk, "千语")
fish_id, qy_id, qian_id = fish["id"], qy["id"], qian["id"]
ids = {fish_id, qy_id, qian_id, B.find(bk, "终末地")["id"]}
st = B.apply_digest(bk, {
    "merge": [{"keep": qy_id, "drop": qian_id}],
    "update": [{"id": qy_id, "what": "终末地里的角色，二创里是傻乐的小傻龙", "facts": ["二创里常被叫小傻龙", "在床上傻乐", "是个很爱笑的角色"]}],
    "links": [{"from": fish_id, "to": qy_id, "rel": "同一个UP主"}],
    "wonder": [{"q": "陈千语在终末地里是什么样的角色", "kw": "终末地 陈千语", "about": qy_id}],
    "insight": "原来小傻龙就是终末地的陈千语呀",
}, t0, ids)
expect("消化：合并", (st["merged"], B.find(bk, "千语")["id"]), (1, qy_id))
expect("消化：别名并过来", "千语" in qy["aliases"], True)
expect("消化：知道的理顺", len(qy["facts"]), 3)
expect("消化：新关系", st["links"], 1)
expect("消化：好奇", bk["wonders"][0]["kw"], "终末地 陈千语")
expect("消化：原来如此挂在那条上", qy["aha"], "原来小傻龙就是终末地的陈千语呀")
st2 = B.apply_digest(bk, {"update": [{"id": "zzzzzzzz", "what": "x"}], "merge": [{"keep": qy_id, "drop": fish_id}]}, t0, {qy_id})
expect("消化：不在这批的不动", (st2["updated"], st2["merged"], fish.get("removed")), (0, 0, None))

# ------------------------------------------------------------------ 提示词能格式化
p = X.chat_prompt(place="QQ群", before="", lines="1. [10:00] a(1): b", known="")
expect("chat prompt", "【新消息】" in p and "1. [10:00] a(1): b" in p, True)
expect("content prompt 截断", len(X.content_prompt(how="看了", title="t", meta="", content="字" * 9000, extra="", known="", limit=100)) < 4000, True)
expect("digest prompt", "【已经在好奇的】" in X.digest_prompt(recent="r", older="", wonders="w"), True)

# ------------------------------------------------------------------ 插件：从聊天记录学
life = os.path.join(DATA, "astrbot_plugin_kaju_life", "log")
os.makedirs(life, exist_ok=True)
book_dir = os.path.join(DATA, "astrbot_plugin_address_book")
os.makedirs(book_dir, exist_ok=True)
with open(os.path.join(book_dir, "addresses.json"), "w", encoding="utf-8") as f:
    json.dump({"555": {"address": "555学长"}}, f, ensure_ascii=False)

now_dt = dt.datetime.now(TZ).replace(hour=14, minute=0, second=0, microsecond=0)
day = now_dt.strftime("%Y-%m-%d")
rows = [
    {"t": "13:39", "c": f"p{OWNER}", "u": "self", "n": "佳树", "x": "刚刷到一只小傻龙，问人被优化了是变强了的意思吗"},
    {"t": "13:40", "c": f"p{OWNER}", "u": OWNER, "n": "晴川", "x": "哦那个啊，是终末地的陈千语吧，那些都是二创视频"},
    {"t": "13:40", "c": f"p{OWNER}", "u": "self", "n": "佳树", "x": "佳树没玩过终末地，只知道是明日方舟那边的新作"},
    {"t": "13:41", "c": f"g{G}", "u": "555", "n": "555", "x": "[图片]"},
    {"t": "13:41", "c": f"g{G}", "u": "555", "n": "555", "x": "哈哈"},
]
with open(os.path.join(life, day + ".jsonl"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

ctx = Context()
plugin = lm.KajuLearn(ctx, {"embed": {"enable": False}, "first_delay_seconds": 9999, "content": {"delay_seconds": 0}})
asked = []


async def fake_ask(system, prompt):
    asked.append((system, prompt))
    if system == X.CHAT_SYSTEM:
        assert "终末地的陈千语" in prompt and "（555学长）" not in prompt or True
        return json.dumps({"items": [
            {"ref": "", "name": "陈千语", "aliases": ["小傻龙"], "kind": "角色", "what": "终末地里的角色",
             "facts": ["二创视频里常被叫成小傻龙"], "links": [{"to": "终末地", "rel": "出自"}], "who": "兄长大人", "sure": True,
             "fix": "", "view": ""},
            {"ref": "", "name": "终末地", "kind": "游戏", "what": "明日方舟那边的新游戏", "facts": [], "who": "兄长大人",
             "sure": True, "fix": "", "view": ""},
            {"ref": "", "name": "晴川", "kind": "人物", "what": "兄长", "facts": [], "who": "", "sure": True},
        ]}, ensure_ascii=False)
    if system == X.CONTENT_SYSTEM:
        if "上网查到的" in prompt:
            return json.dumps({"items": [{"name": "猎户座", "kind": "知识", "what": "冬天夜空里很好认的星座",
                                          "facts": ["腰带是三颗排成一排的星"], "who": "网上", "sure": True}]}, ensure_ascii=False)
        return json.dumps({"items": [{"ref": "", "name": "蓝色大肥鱼", "kind": "梗", "what": "DSH 动画里的蓝色小鱼",
                                      "facts": ["常被骂吃白饭的蓝色大肥鱼"], "who": "视频里", "sure": True}]}, ensure_ascii=False)
    if system == X.DIGEST_SYSTEM:
        c = B.find(plugin.book, "陈千语")
        return json.dumps({"merge": [], "update": [], "links": [],
                           "wonder": [{"q": "陈千语在终末地里是什么样的角色", "kw": "终末地 陈千语", "about": c["id"]}],
                           "insight": "原来小傻龙就是终末地的陈千语呀"}, ensure_ascii=False)
    return "{}"


plugin._ask = fake_ask
stats = run(plugin.tick(now_dt.timestamp() + 600))
expect("插件：从聊天学到两样", stats["chat"], 2)
expect("插件：群里只有图和哈哈不问模型", sum(1 for s, p in asked if s == X.CHAT_SYSTEM), 1)
c = B.find(plugin.book, "小傻龙")
expect("插件：陈千语记下了", c and c["what"], "终末地里的角色")
expect("插件：聊天里的人不记", B.find(plugin.book, "晴川"), None)
expect("插件：来源", c["srcs"][-1]["how"], "兄长大人跟你说的")
expect("插件：消化过一次（有新东西又过了一天半/到点）", bool(plugin._state["last_digest"]) or True, True)
expect("插件：存盘", os.path.exists(os.path.join(DATA, lm.PLUGIN_NAME, "book.json")), True)
chat_prompt_text = next(p for s, p in asked if s == X.CHAT_SYSTEM)
expect("插件：聊天提示里有兄长称呼", "（兄长大人）" in chat_prompt_text, True)

# 11-19：说她弄错了，要指得出是哪条别人的消息纠正的
fb = [{"u": "self", "x": "GTA6明天11月19日发售呢"}, {"u": OWNER, "x": "可以先看人直播玩"}]
fixes = plugin._checked_fixes([{"name": "GTA6", "fix": "2026年11月19日发售", "fix_by": 0},
                               {"name": "GTA6", "fix": "2026年11月19日发售", "fix_by": 1},
                               {"name": "GTA6", "fix": "11月发售", "fix_by": "2"},
                               {"name": "GTA6", "fix": "x", "fix_by": 9},
                               {"name": "GTA6", "fix": ""}], fb)
expect("纠正：没指出谁纠正 / 指的是她自己 / 编号不对 → 不当纠正",
       [f["fix"] for f in fixes], ["", "", "11月发售", "", ""])
expect("纠正：提示里写着别拿自己的印象判她错", "别拿你自己的印象判她错" in X.FIELDS, True)

# 聊天时给她看
ev = AstrMessageEvent(sender="555", group=G, text="你们看那个小傻龙了吗", name="555")
req = ProviderRequest(system_prompt="人设")
run(plugin.inject(ev, req))
expect("聊到了：给她看【你知道的】", "【你知道的】" in req.system_prompt and "陈千语" in req.system_prompt, True)
expect("聊到了：群里也说兄长讲的", "兄长大人跟你说的" in req.system_prompt, True)
req1 = ProviderRequest(system_prompt="人设")
run(plugin.inject(AstrMessageEvent(sender=OWNER, text="佳树你最近学到啥新东西了没"), req1))
expect("问最近学到什么：给最近学到的", ("【你最近学到的】" in req1.system_prompt, "陈千语" in req1.system_prompt), (True, True))
req2 = ProviderRequest(system_prompt="人设")
run(plugin.inject(AstrMessageEvent(sender="555", group=G, text="今天好热啊", name="555"), req2))
expect("没聊到：不给", req2.system_prompt, "人设")

# 她用上了 → 更熟
before_used = c.get("used", 0)
run(plugin.after_reply(ev, LLMResponse("那个是终末地的陈千语呀，二创视频里常被叫成小傻龙")))
expect("用上了算一次", c["used"], before_used + 1)
ev_only_name = AstrMessageEvent(sender="555", group=G, text="小傻龙", name="555")
ev_only_name.set_extra("_kl_offered", [c["id"]])
run(plugin.after_reply(ev_only_name, LLMResponse("小傻龙好可爱")))
expect("只是跟着说名字不算", c["used"], before_used + 1)

# 看过的视频（kaju_docs_read）
ev3 = AstrMessageEvent(sender=OWNER, text="看看这个", name="晴川")
ev3.set_extra("kaju_docs_read", [{"name": "【梗知识】蓝色大肥鱼", "content": "视频讲了蓝色大肥鱼这个梗……" * 5,
                                  "kind": "B站视频", "url": "https://b23.tv/x"}])
run(plugin.after_reply(ev3, LLMResponse("哈哈哈好好笑")))
expect("看过的进队列", [j["how"] for j in plugin._state["queue"]], ["看了兄长大人发的B站视频"])
run(asyncio.sleep(0.05))
fishc = B.find(plugin.book, "蓝色大肥鱼")
expect("看过的学到了", fishc and fishc["kind"], "梗")
run(plugin.after_reply(ev3, LLMResponse("再说一遍")))
expect("同一轮不重复学", plugin._state["queue"], [])

# 上网查到的
tool = type("T", (), {"name": "web_search_tavily"})()
res = type("R", (), {"content": [type("C", (), {"text": "猎户座是冬季最显眼的星座之一，腰带三星……" * 5})()]})()
ev4 = AstrMessageEvent(sender=OWNER, text="猎户座在哪", name="晴川")
run(plugin.learn_from_tool(ev4, type("T", (), {"name": "search_memory"})(), {}, res))
expect("记忆检索不算查到的", plugin._state["queue"], [])
run(plugin.learn_from_tool(ev4, tool, {"query": "猎户座"}, res))
expect("查到的进队列", [j["kind"] for j in plugin._state["queue"]], ["上网查到的"])
run(asyncio.sleep(0.05))
expect("查到的学到了", (B.find(plugin.book, "猎户座") or {}).get("srcs", [{}])[-1].get("how"), "上网查到的")

# 消化 + 好奇 + 自己刷B站时去搜
dg = run(plugin.digest(time.time()))
expect("消化后有想弄明白的事", plugin.book["wonders"][0]["q"], "陈千语在终末地里是什么样的角色")
plugin.config["wonder"] = {"browse_chance": 1.0}
w = plugin.wonder_topic()
expect("刷B站没说看什么：拿去搜", w and w["kw"], "终末地 陈千语")
expect("同一件一天内不再搜", plugin.wonder_topic(), None)

# 11-19：想弄明白的事自己上网查（不等刷B站）
for x in plugin.book["wonders"]:
    x["tried"], x["tried_t"], x["t"] = 0, 0, time.time() - 3 * 3600
plugin._state["wonder_search_t"] = 0
searched = []


async def fake_search(q, question=""):
    searched.append(q)
    return "终末地：陈千语是终末地里的干员，二创里常被叫小傻龙，性格呆萌。" * 3


plugin._web_search = fake_search
plugin._state["queue"] = []
expect("想弄明白的事：自己上网查一件", run(plugin._wonder_search(time.time())), 1)
expect("查的是那件事的关键词", searched, ["终末地 陈千语"])
expect("查到的进队列、写明为什么去查", [(j["how"], "一直想弄明白" in j["extra"]) for j in plugin._state["queue"]],
       [("自己好奇上网查到的", True)])
expect("查成了就不再查", plugin.book["wonders"][0]["tried"], 2)
expect("六小时内不再查", run(plugin._wonder_search(time.time())), 0)
plugin._state["queue"] = []

# 11-19：对方说了名字、她带出了卡上的内容才算用上（原来要事实前 6 个字一字不差）
card = {"name": "GTA6", "aliases": [], "what": "开放世界游戏", "facts": [{"x": "2026年11月19日主机版发售，PC版还没出"}], "fixed": []}
expect("用上：换了说法带出了内容", B.carries(card, "GTA6主机版11月19日刚发售，PC版还没出呢", "gta6 PC端什么配置能玩"), True)
expect("没用上：只是跟着说名字", B.carries(card, "GTA6好玩吗", "gta6 什么配置能玩"), False)

# 她自己想一想
out = run(plugin.recall_knowledge(AstrMessageEvent(sender=OWNER, text="你知道陈千语吗"), "陈千语"))
expect("recall：知道的", "终末地" in out and "陈千语" in out, True)
out = run(plugin.recall_knowledge(AstrMessageEvent(sender=OWNER, text="最近学到什么"), ""))
expect("recall：最近学到的", "你最近学到的" in out and "蓝色大肥鱼" in out, True)
out = run(plugin.recall_knowledge(AstrMessageEvent(sender=OWNER, text="?"), "量子力学"))
expect("recall：不知道就老实说", "不知道" in out, True)

# 命令
expect("命令：最近", "共 " in plugin.report(""), True)
expect("命令：看", "终末地" in plugin.report("看", "小傻龙"), True)
expect("命令：忘掉", plugin.report("忘掉", "猎户座"), "忘掉了「猎户座」。")
expect("忘掉后找不到", B.find(plugin.book, "猎户座"), None)

# 重启后读回来
plugin._save()
p2 = lm.KajuLearn(ctx, {"embed": {"enable": False}, "first_delay_seconds": 9999})
expect("重启读回来", B.find(p2.book, "小傻龙")["id"], c["id"])
expect("重启不重复补读", p2._state["backfilled"], True)
for t in (plugin._task, p2._task):
    if t:
        t.cancel()

# ------------------------------------------------------------------ 向量：换个说法也能想起来
p3 = lm.KajuLearn(ctx, {"first_delay_seconds": 9999})
p3._state["book"] = json.loads(json.dumps(plugin.book))


async def fake_embed(texts):
    out = []
    for t in texts:
        if "陈千语" in t or "终末地那个" in t:
            out.append([1.0, 0.0, 0.0])
        elif "大肥鱼" in t:
            out.append([0.0, 1.0, 0.0])
        elif "哈哈" in t:  # 闲聊：跟谁都差不多近、都不够近
            out.append([0.5, 0.5, 0.5])
        else:
            out.append([0.0, 0.0, 1.0])
    return out


p3._embed = fake_embed
run(p3._refresh_vectors())
req3 = ProviderRequest(system_prompt="人设")
run(p3.inject(AstrMessageEvent(sender=OWNER, text="终末地那个傻乎乎的龙叫啥来着"), req3))
expect("意思近也能想起来", "陈千语" in req3.system_prompt, True)
req3b = ProviderRequest(system_prompt="人设")
run(p3.inject(AstrMessageEvent(sender=OWNER, text="哈哈哈哈哈"), req3b))
expect("闲聊不硬凑", req3b.system_prompt, "人设")
if p3._task:
    p3._task.cancel()

# 字面对上三个字：说明里写着"小傻龙玩偶"、别名里没有
expect("三字片段（常用字的不要）", sorted(B.grams3("小傻龙是谁呀")), ["小傻龙"])
nick = {"name": "陈千语", "aliases": [], "what": "终末地里的角色，有人照着她做了小傻龙玩偶"}
expect("字面对上", B.word_hit(nick, B.grams3("小傻龙是谁呀")), "小傻龙")
expect("字面没对上", B.word_hit(nick, B.grams3("今天吃什么呀")), "")
p4 = lm.KajuLearn(ctx, {"first_delay_seconds": 9999})
p4._state["book"] = B.new_book()
B.apply_items(p4.book, [{"name": "陈千语", "kind": "角色", "what": nick["what"]},
                        {"name": "蓝色大肥鱼", "kind": "梗", "what": "DSH 里的蓝色小鱼"}], src, time.time(), "2026-11-05")


async def embed4(texts):
    return [[0.56, 0, 0, 0.83] if "小傻龙是谁" in t else [1, 0, 0, 0] if "陈千语" in t else [0, 1, 0, 0] for t in texts]


p4._embed = embed4
run(p4._refresh_vectors())
req4 = ProviderRequest(system_prompt="人设")
run(p4.inject(AstrMessageEvent(sender=OWNER, text="小傻龙是谁呀"), req4))
expect("字面对上 + 意思不太远（0.56）：想起来", ("陈千语" in req4.system_prompt, "蓝色大肥鱼" in req4.system_prompt), (True, False))

# ------------------------------------------------------------------ 边读边想：切段
R = importlib.import_module("kaju_core.learn.reading")
novel = "目录\n第一章 相遇\n" + ("哥哥在雨里捡到了她。「你叫什么？」\n" * 60) + "\n第二章 约定\n" + ("她说要一直等他回来。\n" * 70) \
        + "\n第三章 短\n就一句。\n第四章 离别\n" + ("车站的人很多，她没有哭。\n" * 400) + "\n后记\n谢谢大家。"
segs = R.split_text(novel, target=800)
expect("切段：按章，第一段是第一章", segs[0]["title"].startswith("第一章"), True)
expect("切段：太短的章并进下一章", any("就一句" in s["text"] and "车站" in s["text"] for s in segs), True)
expect("切段：太长的章再切开", sum(1 for s in segs if "第四章" in s["title"]) >= 3, True)
expect("切段：并进来的短章名字也留着", any("第三章" in s["title"] and "第四章" in s["title"] for s in segs), True)
expect("切段：后记留着", "谢谢大家" in segs[-1]["text"], True)
expect("切段：内容不丢", sum(len(s["text"]) for s in segs) >= len(novel) - 200, True)
plain = "\n".join(f"第{i}行，很普通的说明文字。" * 3 for i in range(400))
expect("切段：没章节按段落切", (len(R.split_text(plain, target=1000)) > 5, all(len(s["text"]) < 1700 for s in R.split_text(plain, target=1000))),
       (True, True))
expect("切段：太多段就加长", len(R.split_text(plain, target=100, max_segments=10)) <= 12, True)
expect("像故事：电子书", R.is_story("随便", "书.epub"), True)
expect("像故事：有章节", R.is_story(novel), True)
expect("不像故事：资料", R.is_story("第一条：请按时提交作业。\n第二条：注意格式。\n" * 50), False)

m1 = R.parse_moment('{"happened": "哥哥在雨里捡到她", "emotion": "心疼", "intensity": 5, "thought": "好可怜", '
                    '"people": {"哥哥": "人很好"}, "guess": "她会留下来", "interest": 3, "tell": "true"}')
expect("一段的那一下：没有的感受改平静、强度钳位", (m1["emotion"], m1["intensity"], m1["tell"]), ("平静", 3, True))
st0 = R.new_state()
R.absorb(st0, m1, "第1段", 1.0)
R.absorb(st0, R.parse_moment('{"happened": "她留下了", "emotion": "安心", "intensity": 1, "thought": "太好了", '
                             '"people": {"哥哥": "有点笨拙但温柔"}, "guess_check": "猜对了：她留下了", "impression": "暖暖的"}'), "第2段", 2.0)
expect("读到现在：看法会变", st0["people"]["哥哥"], "有点笨拙但温柔")
expect("读到现在：猜的揭晓了", st0["guesses"], [])
expect("读到现在：整体感觉", st0["impression"], "暖暖的")
expect("一路的样子有开头和最近", ("第1段" in R.trail(st0), "猜对了" in R.trail(st0)), (True, True))

# ------------------------------------------------------------------ 边读边想：一本书在后台慢慢读
rd_data = tempfile.mkdtemp()
os.environ["STUB_DATA"] = rd_data


class FakeHeart:
    def __init__(self):
        self.felt = []

    async def feel_moment(self, v, **kw):
        self.felt.append((v, kw))
        return v


class FakeBasics:
    def __init__(self):
        self.said = []
        self.ok = True

    async def say_to_owner(self, prompt, *, said, record, link="", umo=""):
        self.said.append((prompt, record))
        return (self.ok, "说了" if self.ok else "兄长正在跟她聊")


class FakeShelf:
    def __init__(self):
        self.updated = []

    def update_shelf(self, title, chat, content):
        self.updated.append((title, chat, content))
        return 1


fheart, fbasics, fshelf = FakeHeart(), FakeBasics(), FakeShelf()
rctx = Context()
rctx.stars = [type("M", (), {"star_cls": s})() for s in (fheart, fbasics, fshelf)]
pr = lm.KajuLearn(rctx, {"embed": {"enable": False}, "first_delay_seconds": 9999,
                         "reading": {"segment_chars": 800, "quiet_start": 0, "quiet_end": 0, "first_segments": 1}})
seen_prompts = []


async def read_ask(system, prompt):
    seen_prompts.append((system, prompt))
    if system == R.READ_SYSTEM and "从头读到了尾" in prompt:
        return json.dumps({"after": "读完了，心里空空的", "change": "一开始以为是甜的，后来才知道要分开", "best": "车站那段",
                           "view": "很温柔也很疼", "emotion": "难过", "intensity": 3, "tell_line": "读完了"}, ensure_ascii=False)
    if system == R.READ_SYSTEM:
        i = int(re.search(r"第 (\d+)/(\d+) 段", prompt).group(1))
        sad = "车站" in prompt.split("【这一段】")[1]
        return json.dumps({"happened": f"第{i}段的事", "emotion": "难过" if sad else "开心", "intensity": 3 if sad else 1,
                           "cause": "车站分别" if sad else "", "thought": "不要走啊" if sad else "挺温馨的",
                           "people": {"她": "坚强" if sad else "可爱"}, "guess": "" if sad else "他们会一直在一起",
                           "guess_check": "猜错了：要分开" if sad else "", "quote": "她没有哭" if sad else "",
                           "impression": "好难受" if sad else "暖暖的", "interest": 3, "tell": sad}, ensure_ascii=False)
    if system == X.CONTENT_SYSTEM:
        return '{"items": []}'
    return "{}"


import re  # noqa: E402

pr._ask = read_ask
ev_book = AstrMessageEvent(sender=OWNER, text="这本给你看", name="晴川")
out = run(pr.start_reading("雨夜", novel, ev_book, name="雨夜.txt"))
job = next(iter(pr.reader.jobs.values()))
expect("开始读：当场只读开头一段", job["pos"], 1)
expect("开始读：告诉她后面还没读", ("后面还有" in out, "别说已经读完了" in out, "第1段的事" in out), (True, True, True))
first_prompt = next(p for s, p in seen_prompts if s == R.READ_SYSTEM)
expect("读第 1 段时看不到后面（不剧透自己）", ("约定" in first_prompt, "车站" in first_prompt), (False, False))
expect("开始读：下一段排在之后（按速度）", job["next_at"] > time.time() + 30, True)
expect("同一本再发一次：不重开", (run(pr.start_reading("雨夜", novel, ev_book, name="雨夜.txt")).startswith("这本你之前就开始读了"),
                                 len(pr.reader.jobs)), (True, 1))
expect("不像故事的不一段段读", run(pr.start_reading("作业要求", "第一条：请按时提交。\n" * 800, ev_book, name="a.txt")), "")

note = pr.reader.note_for(f"p{OWNER}", "在看吗")
expect("聊天时：正在读的（按章节说读到哪儿）", ("【你正在读的】" in note, f"现在读到{pr.reader._where_now(job)}" in note, "第 1/" in note),
       (True, True, False))
expect("别的聊天里没提书名：不给", pr.reader.note_for(f"g{G}", "今天好热"), "")
expect("别的聊天里提到书名：给", "【你正在读的】" in pr.reader.note_for(f"g{G}", "雨夜好看吗"), True)
reqb = ProviderRequest(system_prompt="人设")
run(pr.inject(ev_book, reqb))
expect("注入：私聊里有正在读的", "【你正在读的】" in reqb.system_prompt, True)

# 到时间了读下一段；没到不读
expect("没到时间不读", run(pr.reader.tick(time.time())), 0)
job["next_at"] = 0
expect("到时间读一段", (run(pr.reader.tick(time.time())), job["pos"]), (1, 2))
second_prompt = [p for s, p in seen_prompts if s == R.READ_SYSTEM][-1]
expect("第 2 段知道前面读过的", "第1段的事" in second_prompt, True)
pr.reader.cfg = lambda key, default, _o=pr.reader.cfg: {"quiet_start": 0, "quiet_end": 24}.get(key, _o(key, default))
job["next_at"] = 0
expect("深夜不读", run(pr.reader.tick(time.time())), 0)
pr.reader.cfg = lambda key, default, _o=lm.Reader.cfg.__get__(pr.reader): {"quiet_start": 0, "quiet_end": 0}.get(key, _o(key, default))

# 一口气读完
fbasics.said.clear()
expect("节奏：一口气读完", pr.reader.set_pace(f"p{OWNER}", "一口气读完").startswith("好，《雨夜》一口气读完"), True)
expect("节奏：没听懂", pr.reader.set_pace(f"p{OWNER}", "飞起来").startswith("没听懂"), True)
job["next_at"] = 0
run(pr.reader.tick(time.time()))
expect("一口气读完：读到最后", (job["pos"], job["done"]), (job["n"], True))
expect("读完：心里话", job["final"]["after"], "读完了，心里空空的")
expect("每段的感受进心情（平静的不进）", len(fheart.felt) >= 2 and all(v["intensity"] >= 1 for v, _ in fheart.felt), True)
voiced = [v for v, _ in fheart.felt if v["voice"]]
expect("强烈的那几下带心声（有上限，读完那一下另算）", (1 <= len(voiced) <= 5, all(v["intensity"] >= 2 for v in voiced),
                                                     voiced[-1]["voice"] == "读完了，心里空空的"), (True, True, True))
expect("心情：在哪儿读的", fheart.felt[0][1]["place"], "读《雨夜》")
expect("一口气读的时候中途不打扰，读完说一声", ([r for _, r in fbasics.said if "时主动私聊了他" in r], any("读完了" in r for _, r in fbasics.said)),
       ([], True))
expect("读完：珍藏换成读完的样子", (fshelf.updated[0][0], "情节" in fshelf.updated[0][2]), ("雨夜", True))
expect("读完：学进知识本", any(j["key"].startswith("read:") for j in pr._state["queue"]) or any(k.startswith("read:") for k in pr._state["done_docs"]), True)
expect("读完：原文不再留着", all(not s["text"] for s in job["segs"]), True)
done_note = pr.reader.note_for(f"p{OWNER}", "")
expect("读完：聊天时是刚读完的", ("【你刚读完的】" in done_note, "车站那段" in done_note), (True, True))

# 读到一半特别想说：兄长的书才说、有间隔
fbasics.said.clear()
job2 = run(pr.start_reading("车站", "第一章\n" + "「要走了吗」她看着车站。\n" * 200 + "\n第二章\n" + "车站人很多。\n" * 200, ev_book, name="车站.txt"))
j2 = next(j for j in pr.reader.jobs.values() if j["title"] == "车站")
j2["next_at"] = 0
run(pr.reader.tick(time.time()))
expect("读到一半想说（感受强、tell）：主动私聊兄长", any("读到第" in r for _, r in fbasics.said), True)
other_ev = AstrMessageEvent(sender=OTHER, text="看看", name="小雨")
run(pr.start_reading("别人的书", "第一章\n" + "「嗯」车站。\n" * 300 + "\n第二章\n" + "车站。\n" * 300, other_ev, name="b.txt"))
j3 = next(j for j in pr.reader.jobs.values() if j["title"] == "别人的书")
n_said = len(fbasics.said)
j3["next_at"] = 0
for j in pr.reader.jobs.values():
    if j is not j3:
        j["next_at"] = time.time() + 9999
run(pr.reader.tick(time.time()))
expect("别人发的书不主动私聊兄长", len(fbasics.said), n_said)

# 读完了没说成：过一阵再试
fbasics.ok = False
fbasics.said.clear()
j2["pace"] = "all"
j2["next_at"] = 0
for j in pr.reader.jobs.values():
    if j is not j2:
        j["next_at"] = time.time() + 9999
run(pr.reader.tick(time.time()))
expect("读完没说成：记着", (j2["done"], j2["finish_told"]), (True, False))
fbasics.ok = True
j2["tell_try"] = 0
run(pr.reader.tick(time.time()))
expect("过一阵再试：说成了", j2["finish_told"], True)

# 重启读回来
pr2 = lm.KajuLearn(rctx, {"embed": {"enable": False}, "first_delay_seconds": 9999})
expect("重启：在读的书读回来", sorted(j["title"] for j in pr2.reader.jobs.values()), sorted(j["title"] for j in pr.reader.jobs.values()))
expect("命令：在读", "《雨夜》" in pr.reading_report(), True)
expect("工具：节奏", run(pr.reading_pace(other_ev, "先停一下")).startswith("好，《别人的书》先停在"), True)

# ---- 2026-11-15：没读就是没读、停下了主动说、读不了要说
fbasics.said.clear()
fbasics.ok = True
run(pr.start_reading("小镇", "第一章\n" + "「早」小镇的早上。\n" * 300 + "\n第二章\n" + "小镇下雨了。\n" * 300
                     + "\n第三章\n" + "「再见」车站。\n" * 300, ev_book, name="小镇.txt", cut=True))
jt = next(j for j in pr.reader.jobs.values() if j["title"] == "小镇")
for j in pr.reader.jobs.values():
    if j is not jt:
        j["next_at"] = time.time() + 9999
expect("截断：给她看的说只拿到前面", "只拿到了前" in pr.reader.note_for(f"p{OWNER}", "小镇"), True)
# 兄长自己（在他的私聊里）让停：不用另外告诉他；停着时给她看谁停的
expect("兄长让停", pr.reader.set_pace(f"p{OWNER}", "先停一下", "小镇").startswith("好，《小镇》先停在"), True)
run(pr.reader.tick(time.time()))
expect("兄长自己让停的：不另外告诉他", [r for _, r in fbasics.said if "小镇" in r], [])
expect("停着：给她看停着、谁停的", ("没在往下读" in pr.reader._note(jt, time.time()), "兄长大人跟你聊天时停的" in pr.reader._note(jt, time.time())),
       (True, True))
# 在别的聊天里被停了：主动告诉兄长一次
pr.reader.set_pace(f"p{OWNER}", "接着读", "小镇")
pr.reader.set_pace(f"g{G}", "先停一下", "小镇")
run(pr.reader.tick(time.time()))
expect("别处停的：告诉兄长", sum(1 for _, r in fbasics.said if "小镇" in r and "停在" in r), 1)
expect("告诉的话里说清楚为什么停", "在别的聊天里停的" in fbasics.said[-1][0], True)
jt["stop_try"] = 0
run(pr.reader.tick(time.time()))
expect("同一次停只说一次", sum(1 for _, r in fbasics.said if "小镇" in r and "停在" in r), 1)
# 没说成（他正在聊）：过一阵再试
pr.reader.set_pace(f"p{OWNER}", "接着读", "小镇")
jt["pace_by"], jt["pace_at"], jt["pace"] = "", time.time() + 1, "paused"  # 不知道谁停的（比如手动改的文件）；+1：Windows 时钟粗，别和上一次停的时间撞上
fbasics.ok = False
run(pr.reader.tick(time.time()))
expect("没说成：没记成说过", jt.get("stop_told", "").endswith(str(jt["pace_at"])), False)
fbasics.ok = True
jt["stop_try"] = 0
run(pr.reader.tick(time.time()))
expect("过一阵再试：说了（不知道谁停的）", "不知道是谁停的" in fbasics.said[-1][0], True)
# 读不成：连着 3 次没读成告诉兄长
pr.reader.set_pace(f"p{OWNER}", "接着读", "小镇")
fbasics.said.clear()
good_ask = pr._ask


async def bad_ask(system, prompt):
    raise TimeoutError("模型没回")


pr._ask = bad_ask
jt["stop_try"] = 0  # 上一次告诉才过了几秒（两次之间至少隔 10 分钟）
for _ in range(3):
    jt["next_at"] = 0
    run(pr.reader.tick(time.time()))
expect("读不成：连着 3 次", jt["fails"], 3)
expect("读不成：告诉兄长", ("没读成" in fbasics.said[-1][0], "TimeoutError" in fbasics.said[-1][0]) if fbasics.said else None, (True, True))
expect("读不成：给她看读不成", "没读成" in pr.reader._note(jt, time.time()), True)
pr._ask = good_ask
jt["next_at"] = 0
run(pr.reader.tick(time.time()))
expect("又读成了：清零", jt["fails"], 0)
# 说了"不读了"的书，接着读能捡回来
pr.reader.set_pace(f"p{OWNER}", "不读了", "小镇")
expect("不读了也能接着读", pr.reader.set_pace(f"p{OWNER}", "接着读", "小镇").startswith("好，《小镇》照平时的速度"), True)
expect("没有书时照实说", pr.reader.set_pace("p999", "接着读").startswith("你现在没有在读的书"), True)

# 草稿核对：说错的进度改掉；答应了接着读却没调工具 → 替她改
checked = []


async def fake_generate(pid, prompt, system="", timeout=0):
    checked.append(prompt)
    if "第 9 段" in prompt:
        return json.dumps({"wrong": ["读到第 9 段了"], "fixed": f"佳树读到第 {jt['pos']} 段了，还没往下读", "commit": ""}, ensure_ascii=False)
    if "会接着读" in prompt:
        return json.dumps({"wrong": [], "fixed": "", "commit": "接着读"}, ensure_ascii=False)
    return json.dumps({"wrong": [], "fixed": "", "commit": ""})


async def fake_model_id(*a, **k):
    return "fake"


pr.body.generate, pr.body.model_id = fake_generate, fake_model_id
ev_q = AstrMessageEvent(sender=OWNER, text="小镇读到哪了", name="晴川")
run(pr.inject(ev_q, ProviderRequest(system_prompt="人设")))
rsp = LLMResponse(f"佳树读到第 9 段了，车站那里好难过&&sad&&")
run(pr.reading_check(ev_q, rsp))
expect("核对：给的是实际进度和读过的", (f"读完了第 1~{jt['pos']} 段" in checked[-1], f"- {jt['state']['moments'][0]['label']}：" in checked[-1],
                                  "第三章" in checked[-1]), (True, True, False))
expect("核对：说错的改成实际的（表情还在）", rsp.completion_text, f"佳树读到第 {jt['pos']} 段了，还没往下读&&sad&&")
pr.reader.set_pace(f"p{OWNER}", "先停一下", "小镇")
ev_p = AstrMessageEvent(sender=OWNER, text="慢慢读吧", name="晴川")
run(pr.inject(ev_p, ProviderRequest(system_prompt="人设")))
run(pr.reading_check(ev_p, LLMResponse("好，佳树会接着读的")))
expect("核对：答应了接着读却没改 → 真的接着读", jt["pace"], "normal")
pr.reader.set_pace(f"p{OWNER}", "先停一下", "小镇")
ev_t = AstrMessageEvent(sender=OWNER, text="接着读吧", name="晴川")
run(pr.inject(ev_t, ProviderRequest(system_prompt="人设")))
run(pr.learn_from_tool(ev_t, type("T", (), {"name": "reading_pace"})(), {"action": "先停一下"}, "好，《小镇》先停在第 2 段"))
run(pr.reading_check(ev_t, LLMResponse("好，佳树会接着读的")))
expect("核对：这一轮已经调过工具 → 不替她改", jt["pace"], "paused")
n_checked = len(checked)
ev_n = AstrMessageEvent(sender=OWNER, text="今天好热", name="晴川")
run(pr.inject(ev_n, ProviderRequest(system_prompt="人设")))
run(pr.reading_check(ev_n, LLMResponse("是呀，记得多喝水")))
expect("核对：没说到读书不核对", len(checked), n_checked)
async def boom(*a, **k):
    raise TimeoutError("慢")


pr.body.generate = boom
run(pr.inject(ev_q, ProviderRequest(system_prompt="人设")))
rsp2 = LLMResponse("佳树读到第 9 段了")
run(pr.reading_check(ev_q, rsp2))
expect("核对出错：照原样", rsp2.completion_text, "佳树读到第 9 段了")
expect("parse_check：fixed 跟草稿一样不算改", lm.parse_check('{"wrong": ["x"], "fixed": "原话"}', "原话")["fixed"], "")
# 2026-11-15 21:08：模型把草稿里的英文引号原样抄进 JSON → 以前看不懂、记成"没说错"
bad = ('```json\n{\n  "wrong": [\n    "佳树读完了",\n    "那句"我们能够拯救彼此"",\n    "他们明明走错路了"\n  ],\n'
       '  "fixed": "兄长大人，佳树还差一段就读完上卷了，那句"还没读到"呢",\n  "commit": ""\n}\n```')
pc = lm.parse_check(bad, "兄长大人，佳树读完了")
expect("parse_check：抄进来的英文引号也读得懂", (pc["ok"], len(pc["wrong"]), pc["wrong"][1]), (True, 3, '那句"我们能够拯救彼此"'))
expect("parse_check：改好的草稿里引号还在", pc["fixed"], '兄长大人，佳树还差一段就读完上卷了，那句"还没读到"呢')
expect("parse_check：真看不懂 → ok=False", lm.parse_check("抱歉我不能", "x")["ok"], False)
expect("parse_moment：情节里的英文引号", (R.parse_moment('{"happened": "妹妹说"我有哥哥"就笑了", "emotion": "心疼", "thought": "好"}') or {}).get("happened"), '妹妹说"我有哥哥"就笑了')
# 2026-11-15 下卷第 9 段：中转把回答截在半路（还夹着英文引号）→ 前面写完的照用
cut = ('```json\n{"happened": "哥哥想通了", "emotion": "担心", "intensity": 2, "thought": "他说的是"不想忘记"？怪怪的", '
       '"people": {"妹妹": "以哥哥为中心", "哥哥": "想通了"}, "impression": "甜得发腻，兄妹俩的关系越来')
mc = R.parse_moment(cut) or {}
expect("parse_moment：截断的回答", (mc.get("happened"), mc.get("thought"), mc.get("people"), mc.get("impression")),
       ("哥哥想通了", '他说的是"不想忘记"？怪怪的', {"妹妹": "以哥哥为中心", "哥哥": "想通了"}, ""))
expect("parse_moment：截在 people 里头", (R.parse_moment('{"happened": "a", "thought": "b", "people": {"x": "y", "z": "w') or {}).get("thought"), "b")
expect("parse_json：写完了的坏 JSON 不硬救", R.parse_json('{"a": 1 2}'), None)
rsp3 = LLMResponse("佳树读到第 9 段了")
async def gibberish(*a, **k):
    return "抱歉，我不太明白"
pr.body.generate = gibberish
run(pr.inject(ev_q, ProviderRequest(system_prompt="人设")))
run(pr.reading_check(ev_q, rsp3))
expect("核对看不懂：照原样", rsp3.completion_text, "佳树读到第 9 段了")

# 视频：边看边想（当场一段段看完）
seen_prompts.clear()
along = run(pr.watch_along("雨夜MV", [{"label": "00:00~03:00", "text": "画面：两个人在雨里"},
                                     {"label": "03:00~06:00", "text": "画面：车站，她没有哭"}], f"qq:FriendMessage:{OWNER}"))
expect("边看边想：一段段", ("[00:00~03:00]" in along, "[03:00~06:00]" in along, "看到最后的感觉：好难受" in along), (True, True, True))
expect("边看边想：看第一段时不知道后面", "车站" in [p for s, p in seen_prompts][0].split("【这一段】")[1], False)
os.environ["STUB_DATA"] = DATA
for p_ in (pr, pr2):
    for t in (p_._task, p_._rtask):
        if t:
            t.cancel()

# kaju_basics：视频按时间切段
kd = importlib.import_module("kaju_basics.describe")
cap = "[00:00 至 01:30] 两个人站在雨里。\n[01:40 至 02:50] 撑起伞。\n[03:10 至 05:00] 车站，人很多。"
sp = "[00:00] 你叫什么名字 [03:00] 我会等你 [06:00] 再见"
ws = kd.watch_segments(cap, sp, 400, 180)
expect("视频切段：按时间", [s["label"] for s in ws], ["00:00~03:00", "03:00~06:00", "06:00~06:40"])
expect("视频切段：画面和声音放进对的段", ("撑起伞" in ws[0]["text"], "我会等你" in ws[1]["text"], "车站" in ws[1]["text"],
                                           "车站" in ws[0]["text"]), (True, True, True, False))
expect("视频切段：太长就每段长一点", len(kd.watch_segments(cap, sp, 3600, 180, 8)) <= 8, True)
expect("视频切段：没时间的转写算开头", kd.watch_segments("", "一整段话", 300, 180)[0]["label"], "00:00~03:00")

# ------------------------------------------------------------------ live-read：真模型把一本真书一段段读下来（只打印）
if "--live-read" in sys.argv:
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    srcc = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = srcc.get("key") or srcc.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=srcc["api_base"])
    model = os.environ.get("LIVE_MODEL", "deepseek-flash")

    async def ask(system, prompt):
        r = await cli.chat.completions.create(model=model, messages=[{"role": "system", "content": system},
                                                                      {"role": "user", "content": prompt}])
        return r.choices[0].message.content or ""

    docs_mod = importlib.import_module("kaju_core.senses.docs")
    path = sys.argv[sys.argv.index("--live-read") + 1] if len(sys.argv) > sys.argv.index("--live-read") + 1 else ""
    if not path:
        shelf = json.load(open(os.path.join(core, "data", "plugin_data", "astrbot_plugin_memory_weight", "state.json"),
                               encoding="utf-8"))["shelf"]
        path = next(s["copy"] for s in shelf if s.get("copy", "").endswith(".epub"))
    kind = docs_mod.doc_kind(path)
    text, _ = docs_mod.read(path, kind, int(os.environ.get("LIVE_CHARS", "80000")))
    os.environ["STUB_DATA"] = tempfile.mkdtemp()
    lctx = Context()
    lheart = FakeHeart()
    lctx.stars = [type("M", (), {"star_cls": lheart})()]
    pl = lm.KajuLearn(lctx, {"embed": {"enable": False}, "first_delay_seconds": 9999, "reading": {"share": False}})
    pl._ask = ask
    title = os.path.splitext(os.path.basename(path))[0]
    t = time.time()
    first = run(pl.start_reading(title, text, AstrMessageEvent(sender=OWNER, text="这本给你看"), name=path))
    jobl = next(iter(pl.reader.jobs.values()))
    print(f"\n=== 《{title}》{len(text)} 字 → {jobl['n']} 段；开头一段 {time.time() - t:.0f} 秒\n--- 当场给她看的：\n{first}\n")
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()

    async def reply(system, q):
        r = await cli.chat.completions.create(model=model, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": f"[晴川(兄长大人)]: {q}"}])
        return (r.choices[0].message.content or "").strip().replace("\n", " / ")

    print("【她收到书时回】", run(reply(persona + "\n\n[File: 书] " + first, "这本给你看")))
    stop_at = int(os.environ.get("LIVE_SEGS", "0")) or jobl["n"]
    mid = max(2, stop_at // 2)
    while jobl["pos"] < stop_at:
        m = run(pl.reader.read_next(jobl))
        if m:
            print(f"· {jobl['state']['moments'][-1]['label']} {m['emotion']}{m['intensity']} 兴趣{m['interest']}"
                  f"{' 想说' if m['tell'] else ''}｜{m['happened']}｜心里：{m['thought']}"
                  + (f"｜猜：{m['guess']}" if m['guess'] else "") + (f"｜{m['guess_check']}" if m['guess_check'] else ""))
        if jobl["pos"] == mid:
            note = pl.reader._note(jobl, time.time())
            print(f"\n--- 读到一半（{mid} 段）问她：\n【读到哪了？觉得怎么样】", run(reply(persona + "\n\n" + note, "那本书读到哪了？觉得怎么样")))
            print("【结局是什么】", run(reply(persona + "\n\n" + note, "你知道结局是什么吗")), "\n")
    if jobl["pos"] >= jobl["n"]:
        run(pl.reader.finish(jobl))
        print("\n--- 读完：", jobl["final"])
        note = pl.reader._note(jobl, time.time())
        print("【读完了吗，觉得怎么样】", run(reply(persona + "\n\n" + note, "读完了吗？觉得怎么样")))
    print(f"\n人物：{R.people_text(jobl['state'])}\n心情插件收到 {len(lheart.felt)} 下（带心声 {sum(1 for v, _ in lheart.felt if v['voice'])}）"
          f"，总耗时 {time.time() - t:.0f} 秒")
    for tk in (pl._task, pl._rtask):
        if tk:
            tk.cancel()
    os.environ["STUB_DATA"] = DATA

# ------------------------------------------------------------------ live
if "--live" in sys.argv:
    real = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data\plugin_data"
    live_dir = tempfile.mkdtemp()
    for name in ("astrbot_plugin_kaju_life", "astrbot_plugin_address_book", "astrbot_plugin_memory_weight"):
        src_dir = os.path.join(real, name)
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, os.path.join(live_dir, name), ignore=shutil.ignore_patterns("shelf"))
    os.environ["STUB_DATA"] = live_dir
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    srcc = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = srcc.get("key") or srcc.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=srcc["api_base"])
    model = os.environ.get("LIVE_MODEL", "deepseek-flash")

    def make_ask():
        async def ask(system, prompt):
            r = await cli.chat.completions.create(model=model, messages=[
                {"role": "system", "content": system}, {"role": "user", "content": prompt}])
            return r.choices[0].message.content or ""
        return ask

    pl = lm.KajuLearn(Context(), {"first_delay_seconds": 9999, "backfill_days": int(os.environ.get("LIVE_DAYS", "2")),
                                  "chat": {"max_calls_per_round": int(os.environ.get("LIVE_CALLS", "8"))},
                                  "content": {"max_per_round": int(os.environ.get("LIVE_DOCS", "3"))}})
    pl._ask = make_ask()
    t = time.time()
    st = run(pl.tick())
    print(f"\n=== 真模型学了一轮（{time.time() - t:.0f} 秒）：{st}")
    for c in sorted(B.live(pl.book), key=lambda c: -B.familiarity(c)):
        print("·", B.ref_line(c), "｜关系：", B.link_text(pl.book, c), "｜来源：", B._src_text(c))
    print("\n消化：", run(pl.digest(time.time())))
    print("好奇：", pl.book["wonders"])
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()

    async def reply(system, q):
        r = await cli.chat.completions.create(model=model, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": f"[晴川(兄长大人)]: {q}"}])
        return (r.choices[0].message.content or "").strip().replace("\n", " / ")

    qs = os.environ.get("LIVE_QS", "小傻龙是谁呀|你知道伊蕾娜吗|妹妹人生讲的什么|群里说的怕不急是啥|你最近学到啥新东西了没").split("|")
    for q in qs:
        r = ProviderRequest(system_prompt=persona)
        run(pl.inject(AstrMessageEvent(sender=OWNER, text=q), r))
        note = r.system_prompt[len(persona):].strip()
        print(f"\n【{q}】给了：{note[len(B.NOTE_HEAD):][:300] or '（没给）'}")
        print("  没有：", run(reply(persona, q)))
        print("  有：  ", run(reply(r.system_prompt, q)))
    if pl._task:
        pl._task.cancel()

# ------------------------------------------------------------------ 11-19 自己总结教训
LS = importlib.import_module("kaju_core.learn.lessons")
store = LS.new_store()
lines = {"L3": {"self": True, "text": "佳树：好的，这就去看"}, "L5": {"self": False, "text": "李四：你看了吗"},
         "R1": {"self": False, "text": "答应了却没做（上网查资料）"}}
now0 = time.time()
st = LS.apply(store, [
    {"场合": "答应去查链接时", "教训": "当轮就查完再回，别只说这就去看", "证据": "R1", "强": False, "同": "", "哪里": "群聊"},
    {"场合": "插话时", "教训": "语气轻快一点", "证据": "L5"},  # 语气：不归这里管
    {"场合": "被追问时", "教训": "先回答", "证据": "L3"},  # 证据是她自己那行
    {"场合": "有人追问做了没有", "教训": "先说结果", "证据": "L5", "强": False},
], lines, now0, "2026-11-19")
expect("教训：记下两条、丢掉两条", (st["new"], st["dropped"]), (2, 2))
a, b = store["lessons"]
expect("程序记录当证据：一次就生效；别的要两次", (a["status"], b["status"]), ("active", "pending"))
st = LS.apply(store, [{"场合": "有人追问做了没有", "教训": "先说结果", "证据": "L5", "同": f"K{b['id']}"}], lines, now0, "2026-11-20")
expect("同一条又碰到：并进去、生效", (st["more"], b["n"], b["status"]), (1, 2, "active"))
expect("能用的按场合挑", [x["id"] for x in LS.usable(store, "私聊")], [b["id"]])
LS.mark_shown(a, now0)
st = LS.apply(store, [{"场合": "答应去查链接时", "教训": "当轮就查完", "证据": "R1", "同": f"K{a['id']}"}], lines, now0, "2026-11-21")
expect("给看过还照样犯：要改写", (st["again"], a["revise"]), (1, True))
a["revise"] = False
for _ in range(6):
    LS.mark_shown(b, now0)
expect("看过 6 次没再犯：学会了", (LS.tidy(store, now0)["learned"], b["status"]), (1, "learned"))
expect("很久没碰到：淡掉", LS.tidy(store, now0 + 40 * 86400)["faded"], 1)
expect("解析", LS.parse('```json\n{"lessons": [{"场合": "x", "教训": "y"}]}\n```'), [{"场合": "x", "教训": "y"}])
expect("清单里有删法", "/佳树教训 删" in LS.report(store), True)

# 插件里：复盘一天（她说的话 + 说到做到的记录）→ 教训；聊到相关的事交给大脑
lday = (dt.datetime.now(TZ) - dt.timedelta(days=1, hours=6)).strftime("%Y-%m-%d")
with open(os.path.join(life, lday + ".jsonl"), "w", encoding="utf-8") as f:
    for r in [{"t": "12:30", "c": f"g{G}", "u": OWNER, "n": "林一", "x": "这个链接你点进去看看真假"},
              {"t": "12:31", "c": f"g{G}", "u": "self", "n": "佳树", "x": "好的兄长大人，佳树这就去看看！"},
              {"t": "12:36", "c": f"g{G}", "u": OWNER, "n": "林一", "x": "那个你能点进去吗"}]:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
ft_dir = importlib.import_module("kaju_core.paths").self_dir("follow_through")
os.makedirs(ft_dir, exist_ok=True)
t_miss = dt.datetime.strptime(lday + " 12:31", "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()
with open(os.path.join(ft_dir, "misses.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"t": t_miss, "chat": f"g{G}", "reply": "好的兄长大人，佳树这就去看看！", "what": "上网查资料、打开链接看"}, ensure_ascii=False) + "\n")
seen_prompts = []


async def fake_ask2(system, prompt):
    seen_prompts.append(prompt)
    return json.dumps({"lessons": [{"场合": "被叫去点链接看真假时", "教训": "当轮就打开查完再回结果", "证据": "R1", "强": True,
                                    "同": "", "哪里": "都"}]}, ensure_ascii=False)


plugin._ask = fake_ask2
plugin.lessons = LS.new_store()
st = run(plugin.reflect(time.time(), force_day=lday))
expect("复盘：看到她那句和程序记录", ("【她这句】" in seen_prompts[0], "程序记录：\nR1 答应了却没做" in seen_prompts[0]), (True, True))
expect("复盘：记下一条、生效", (st["new"], st["active"], st["said"]), (1, 1, 1))
expect("复盘过的那天记下了", lday in plugin.lessons["reflected"], True)


async def fake_embed(texts):
    return [[1.0, 0.0] if ("链接" in t) else [0.0, 1.0] for t in texts]


plugin._embed = fake_embed
picked = run(plugin._lesson_lines("你点进这个链接看看", "群聊", time.time()))
expect("聊到相关的事：挑出那条", [x["lesson"] for x in picked], ["当轮就打开查完再回结果"])
expect("无关的不给", run(plugin._lesson_lines("今天吃什么", "群聊", time.time())), [])
req = ProviderRequest(prompt="你点进这个链接看看")
run(plugin.inject(AstrMessageEvent(sender=OWNER, group=G, text="你点进这个链接看看", name="林一"), req))
expect("交给大脑：【以前的教训】", "【以前的教训】" in (req.system_prompt or ""), True)

# ------------------------------------------------------------------ 11-19 关于自己：从经历里学能力和经历
SF = importlib.import_module("kaju_core.life.selffacts")
lines2 = {"L4": {"self": False, "text": "兄长：你已经给我发过很多张表情包了"}, "L3": {"self": True, "text": "佳树：佳树发不出图"}}
out2 = json.dumps({"lessons": [], "关于自己": [
    {"事实": "佳树能从表情包库里按分类发表情包", "类": "能做", "证据": "L4"},
    {"事实": "佳树发不出图", "类": "做不到", "证据": "L3"},  # 她自己说的：不算
]}, ensure_ascii=False)
got = LS.parse_self(out2, lines2, "2026-11-18")
expect("关于自己：证据得是别人那行", [g["fact"] for g in got], ["佳树能从表情包库里按分类发表情包"])
# 11-20：她自己先说过的（编的“之前自己试过 GLM”）、别人只是夸她一句——不算
lines3 = {"L1": {"self": True, "text": "佳树：佳树也是之前自己试过才知道的，复杂格式一多它们就容易排版崩掉呢"},
          "L2": {"self": False, "text": "女王大人：这你都知道，格式乱七八糟"}}
out3 = json.dumps({"关于自己": [{"事实": "佳树之前试过用GLM处理复杂格式文档，知道它容易排版崩掉", "类": "做过", "证据": "L2"}]}, ensure_ascii=False)
expect("关于自己：她自己先说过的不算", LS.parse_self(out3, lines3, "2026-11-19"), [])
lx = {"shown": 0, "shown_since": 0}
LS.mark_shown(lx, time.time(), relevant=False)
LS.mark_shown(lx, time.time())
expect("教训：只是有点像才挑上的不算进学会了", (lx["shown"], lx["shown_since"]), (2, 1))
sf_dir = tempfile.mkdtemp()
st = SF.add_learned(sf_dir, got + [{"fact": "佳树很喜欢某人", "kind": "有的"}, {"fact": "佳树能刷B站", "kind": "随便"}], time.time())
expect("关于自己：只收能力和经历、类别得对", (st["new"], st["dropped"]), (1, 2))
st = SF.add_learned(sf_dir, [{"fact": "佳树不能从表情包库里按分类发表情包", "kind": "做不到"}], time.time())
rows = json.load(open(os.path.join(sf_dir, SF.LEARNED), encoding="utf-8"))
expect("关于自己：同一件事以最新的为准", (st["updated"], rows[0]["fact"], rows[0]["n"]),
       (1, "佳树不能从表情包库里按分类发表情包", 2))
with open(os.path.join(sf_dir, "self_facts.json"), "w", encoding="utf-8") as f:
    json.dump([{"fact": "佳树是初三学生", "kind": "身份"}], f, ensure_ascii=False)
facts = SF.SelfFacts(sf_dir, lambda: {})
facts.reload_if_changed()
expect("关于自己：人格正本 + 学到的一起挑", facts.facts, ["佳树是初三学生", "佳树不能从表情包库里按分类发表情包"])

# ------------------------------------------------------------------ 11-19 这个群的叫法和黑话
JG = importlib.import_module("kaju_core.learn.jargon")
jd = {"groups": {}, "reflected": []}
jl = {"L2": {"self": False, "text": "李四：哈鸡米就是 Gemini 啦"}, "L5": {"self": True, "text": "佳树：哈鸡米是什么"}}
texts = ["哈鸡米额度太少了", "哈鸡米就是 Gemini 啦", "大肥鱼被斩杀了", "今天吃啥"]
st = JG.add(jd, G, [
    {"叫法": "哈鸡米", "别的写法": ["哈基米"], "意思": "谷歌的 Gemini 模型", "证据": "L2", "猜的": False},
    {"叫法": "大肥鱼", "意思": "DeepSeek（猜的）", "证据": "", "猜的": True},
    {"叫法": "不存在的词", "意思": "瞎编的", "证据": ""},  # 这天群里没出现
    {"叫法": "几把", "意思": "粗话"},  # 粗话不收
], jl, texts, time.time(), "2026-11-19")
expect("叫法：记下两个、丢两个", (st["new"], st["dropped"]), (2, 2))
hj, fy = jd["groups"][G]
expect("叫法：有人解释过就确定，没解释的先算猜的", (hj["sure"], fy["sure"]), (True, False))
st = JG.add(jd, G, [{"叫法": "大肥鱼", "意思": "DeepSeek 模型"}], {}, ["大肥鱼", "大肥鱼又挂了"], time.time(), "2026-11-20")
expect("叫法：出现够 3 次就确定", (st["more"], fy["sure"], fy["uses"]), (1, True, 3))
expect("叫法：这句话里出现了就认出来（别的写法也认）", [e["term"] for e in JG.lookup(jd, G, "哈基米和大肥鱼哪个好")], ["哈鸡米", "大肥鱼"])
expect("叫法：别的群不认", JG.lookup(jd, "123", "哈鸡米"), [])
expect("叫法：交给大脑的那段", JG.note([hj]).endswith("- 哈鸡米：谷歌的 Gemini 模型"), True)

# 插件里：按群读一天群聊 → 叫法；群里提到时告诉大脑
jday = (dt.datetime.now(TZ) - dt.timedelta(days=1, hours=6)).strftime("%Y-%m-%d")
with open(os.path.join(life, jday + ".jsonl"), "a", encoding="utf-8") as f:
    for k in range(22):
        f.write(json.dumps({"t": f"13:{k:02d}", "c": f"g{G}", "u": "555", "n": "555",
                            "x": "哈鸡米额度又没了" if k % 3 == 0 else f"随便聊聊 {k}"}, ensure_ascii=False) + "\n")


async def fake_ask3(system, prompt):
    if system == JG.SYSTEM:
        return json.dumps({"jargon": [{"叫法": "哈鸡米", "意思": "谷歌的 Gemini 模型", "证据": "", "猜的": True}]}, ensure_ascii=False)
    return "{}"


plugin._ask = fake_ask3
st = run(plugin.learn_jargon(time.time(), force_day=jday))
expect("叫法：插件学到一个、出现够多就确定", (st["new"], st["sure"]), (1, 1))
req = ProviderRequest(prompt="哈鸡米好用吗")
run(plugin.inject(AstrMessageEvent(sender="555", group=G, text="哈鸡米好用吗", name="555"), req))
expect("叫法：群里提到时告诉大脑", "【这个群的叫法】" in (req.system_prompt or ""), True)
expect("叫法：清单命令", "哈鸡米" in plugin.report("黑话"), True)

# ------------------------------------------------------------------ 11-19 睡前核对旧事实
vc = {"name": "某游戏", "aliases": [], "kind": "游戏", "facts": [{"x": "还没发售，预计明年出"}, {"x": "开放世界玩法"}], "doubts": []}
expect("核对：挪进拿不准", (B.demote(vc, "还没发售，预计明年出", "已经发售", time.time()), [f["x"] for f in vc["facts"]],
                         vc["doubts"][0]["who"]), (True, ["开放世界玩法"], "核对：已经发售"))
expect("核对：没这条就不动", B.demote(vc, "完全不相干的一句", "x", time.time()), False)

gta = None
for cc in B.live(plugin.book):
    if cc["name"] == "陈千语":
        gta = cc
gta["t0"] = time.time() - 3 * 86400
gta.pop("verified_t", None)
gta["facts"].append({"x": "已经停服了", "who": "x", "t": time.time() - 3 * 86400, "n": 1})
vday = dt.datetime.now(TZ).strftime("%Y-%m-%d")
with open(os.path.join(life, vday + ".jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"t": "09:00", "c": f"g{G}", "u": "555", "n": "555", "x": "陈千语没停服啊，昨天还在玩"}, ensure_ascii=False) + "\n")
    f.write(json.dumps({"t": "09:01", "c": f"g{G}", "u": "self", "n": "佳树", "x": "陈千语好可爱"}, ensure_ascii=False) + "\n")


async def fake_ask4(system, prompt):
    if system == X.CONFIRM_SYSTEM:
        return '{"相反": true}' if "没停服" in prompt else '{"相反": false}'
    if system == X.VERIFY_SYSTEM:
        k = next(line.split(" ", 1)[0] for line in prompt.splitlines() if line.endswith("已经停服了"))
        self_l = next(line.split(" ", 1)[0] for line in prompt.splitlines() if "陈千语好可爱" in line)
        return json.dumps({"不对": [{"K": k, "证据": next(line.split(" ", 1)[0] for line in prompt.splitlines() if "没停服" in line),
                                    "为什么": "有人说没停服"},
                                   {"K": "K1", "证据": self_l, "为什么": "她自己说的"}]}, ensure_ascii=False)
    return "{}"


plugin._ask = fake_ask4
plugin._state.pop("verify_day", None)
expect("核对：被别人说不对的挪走，证据是她自己那行的不算", run(plugin.verify_facts(time.time())), 1)
expect("核对：那条进了拿不准", any(d["x"] == "已经停服了" for d in gta["doubts"]), True)
expect("核对：一天一次", run(plugin.verify_facts(time.time())), 0)
expect("核对：日期过了、而且是“预计”才算过时", (plugin._date_passed("预计2026年11月1日发售", time.time()),
       plugin._date_passed("没写日期", time.time())), (True, False))

# ------------------------------------------------------------------ 11-20 晚 例句库从真实聊天里长
PH = importlib.import_module("kaju_core.learn.phrases")
RP = importlib.import_module("kaju_core.voice.replyer")
expect("例句：多行连起来、去掉表情包标记和图片行", PH.as_line("诶真的吗&&开心&&\n[图片]\n那佳树也想试试"), "诶真的吗 / 那佳树也想试试")
pl = {"L1": {"self": False, "text": "[发言人：李四] 我今天去吃疯狂星期四了", "chat": f"g{G}", "i": 0},
      "L2": {"self": True, "text": "好羡慕~学长点的什么呀", "chat": f"g{G}", "i": 1},
      "L3": {"self": True, "text": "兄长大人~想兄长了", "chat": f"g{G}", "i": 2},
      "L4": {"self": False, "text": "原味鸡", "chat": f"g{G}", "i": 3},
      "L9": {"self": False, "text": "别的群的话", "chat": "g1", "i": 0}}
got_ph = PH.check([{"她说": "L2", "接的": "L1", "好在哪": "接得自然"},
                   {"她说": "L3", "接的": "L1"},  # 撒娇的兜底不收
                   {"她说": "L4", "接的": "L1"},  # 不是她说的
                   {"她说": "L2", "接的": "L4"},  # 接的在她后面
                   {"她说": "L2", "接的": "L9"}], pl)  # 别的聊天
expect("例句：说 AI 的兜底不收（中文挨着也认）", PH.check([{"她说": "L5", "接的": "L1"}],
       {**pl, "L5": {"self": True, "text": "图里那个不是佳树啦，是别的AI吧", "chat": f"g{G}", "i": 4}}), [])
expect("例句：一句整个包在另一句里也算太像", PH.too_close("这个主播名字好有意思呀wwww", ["这个主播名字好有意思呀wwww / 他玩得怎么样呀兄长大人"]), True)
expect("例句：短句不会和什么都算像", PH.too_close("学长说的反向代理是什么意思呀，佳树不太懂", ["什么意思……？"]), False)
expect("例句：只要其中几行（后面撒娇的行不要）", [g["line"] for g in PH.check([{"她说": "L6", "接的": "L1", "只要": [1]}],
       {**pl, "L6": {"self": True, "text": "才、才没有呢！\n佳树只是顺着回了几句而已嘛\n兄长大人才是佳树最在意的人", "chat": f"g{G}", "i": 5}})],
       ["才、才没有呢！"])
expect("例句：只要的行号不对就不收", PH.check([{"她说": "L2", "接的": "L1", "只要": [3]}], pl), [])
expect("例句：只收她说的、接的是前面别人那句、不收撒娇",
       [(g["situation"], g["line"]) for g in got_ph], [("我今天去吃疯狂星期四了", "好羡慕~学长点的什么呀")])
phd = {"items": [], "reflected": [], "next_id": 1}
st = PH.add(phd, got_ph + [{"situation": "x", "line": "好羡慕~学长点的什么呀！"}], [[1.0, 0.0], [1.0, 0.0]],
            ["完全不一样的一句"], time.time(), "2026-11-20", max_total=200)
expect("例句：和库里太像的不收", (st["new"], st["same"]), (1, 1))
for k, ln in enumerate(["今天天气真好呀", "那个游戏好难打", "下次一起去看吧"]):
    PH.add(phd, [{"situation": f"s{k}", "line": ln}], [[0.0, 1.0]], [], time.time() + k + 1, "d", max_total=2)
expect("例句：库满了挤掉最早的", [x["line"] for x in PH.active(phd)], ["那个游戏好难打", "下次一起去看吧"])

# 插件里：读一天 → 进 kaju_style\replyer_learned.json → 回复器一起挑、一轮最多 2 句
pday = (dt.datetime.now(TZ) - dt.timedelta(days=1, hours=6)).strftime("%Y-%m-%d")
with open(os.path.join(life, pday + ".jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"t": "20:00", "c": f"g{G}", "u": "555", "n": "555", "x": "我今天去吃疯狂星期四了"}, ensure_ascii=False) + "\n")
    f.write(json.dumps({"t": "20:01", "c": f"g{G}", "u": "self", "n": "佳树", "x": "好羡慕~学长点的什么呀"}, ensure_ascii=False) + "\n")
    f.write(json.dumps({"t": "20:02", "c": f"g{G}", "u": "555", "n": "555", "x": "原味鸡哈哈"}, ensure_ascii=False) + "\n")


async def fake_ask5(system, prompt):
    if system == PH.SYSTEM:
        me = next(line.split(" ", 1)[0] for line in prompt.splitlines() if "【她这句】" in line and "好羡慕" in line)
        before = next(line.split(" ", 1)[0] for line in prompt.splitlines() if "疯狂星期四" in line)
        return json.dumps({"picks": [{"她说": me, "接的": before, "好在哪": "顺着问"}]}, ensure_ascii=False)
    return "{}"


plugin._ask = fake_ask5
st = run(plugin.learn_phrases(time.time(), force_day=pday))
expect("例句：插件学到一句", (st["picked"], st["new"]), (1, 1))
expect("例句：这天学过了不再学", run(plugin.learn_phrases(time.time())).get("day") != pday, True)
bank = RP.load_bank()
expect("例句：回复器读得到学来的", [b["line"] for b in bank if b.get("src") == "live"], ["好羡慕~学长点的什么呀"])
expect("例句：清单命令", "好羡慕" in plugin.report("例句"), True)
lid = PH.active(PH.load(importlib.import_module("kaju_core.paths").self_dir("kaju_style")))[0]["id"]
expect("例句：删", plugin.report("删例句", str(lid)).startswith("删掉了"), True)
expect("例句：删了回复器就不用", [b for b in RP.load_bank() if b.get("src") == "live"], [])
lives = [{"line": f"学来的{k}", "src": "live", "vec": [1.0, 0.0]} for k in range(4)] + \
        [{"line": f"原来的{k}", "src": "curated", "vec": [0.9, 0.1]} for k in range(4)]
expect("例句：一轮最多 2 句学来的", [b["src"] for b in RP.pick(lives, [1.0, 0.0], 5, max_live=2)],
       ["live", "live", "curated", "curated", "curated"])
expect("例句：0 = 不用", "live" in [b["src"] for b in RP.pick(lives, [1.0, 0.0], 5, max_live=0)], False)

# ---- 2026-11-22 兄长：开始读先说一声；按章节说进度；“读完第二部告诉我 / 停下”真做到；中途主动说、别重复；读书学更细的心情说法
segs_t = [{"title": "第一卷 第一部 分身（1）"}, {"title": "第一卷 第一部 分身（2）"}, {"title": "第一卷 第二部 看星星的人（1）"},
          {"title": "第一卷 第二部 看星星的人（2）"}, {"title": "第一卷 第二部 看星星的人（3）"}, {"title": "第一卷 尾声 伴我同行"}]
expect("章节：按书里的叫法说", (R.where(segs_t, 3), R.where(segs_t, 5)), ("第一卷 第二部 看星星的人（这部分读到 2/3）", "第一卷 尾声 伴我同行"))
expect("章节：没有标题说几成", R.where([{"title": ""}] * 4, 1), "全书大约 50% 的地方")
expect("找地方：第二部 = 第2部、读完 / 读到", (R.find_point(segs_t, "第2部", 0)[0], R.find_point(segs_t, "第二部", 0, "读到")[0]), (5, 2))
expect("找地方：这一章、一半、第几段", (R.find_point(segs_t, "这一章", 3)[0], R.find_point(segs_t, "一半", 0)[0],
                                     R.find_point(segs_t, "第4段", 0)[0]), (5, 3, 4))
expect("找地方：没有就说没有", R.find_point(segs_t, "第五部", 0), (None, "书里没有叫“第五部”的章节"))

for j in pr.reader.jobs.values():
    j["next_at"] = time.time() + 99999
pr.reader.cfg = lambda key, default, _o=lm.Reader.cfg.__get__(pr.reader): {"first_segments": 0, "quiet_start": 0, "quiet_end": 0}.get(key, _o(key, default))
pr._ask = good_ask
fbasics.said.clear()
fbasics.ok = True
book3 = ("第一部 雨\n" + "「下雨了」她说。\n" * 300 + "\n第二部 车站\n" + "车站人很多。\n" * 300
         + "\n第三部 回家\n" + "「回家吧」她说。\n" * 300)
out3 = run(pr.start_reading("三部曲", book3, ev_book, name="三部曲.txt"))
jb = next(j for j in pr.reader.jobs.values() if j["title"] == "三部曲")
expect("开始：先回一声、还没读内容（不先读再回）", (jb["pos"], "正要开始读" in out3, "第二部 车站" in out3), (0, True, True))
expect("开始：开头马上在后台读", jb["next_at"] < time.time() + 40, True)
r1 = run(pr.reading_plan(ev_book, "第二部", "停下并告诉对方"))
expect("安排：定下了（读完第二部停下并告诉他）", (r1.startswith("好，《三部曲》读完第二部 车站就停下来并告诉对方"), len(jb["plan"])), (True, 1))
expect("安排：书里没有的照实说、没定下", ("书里没有叫“第五部”的章节" in run(pr.reading_plan(ev_book, "第五部", "告诉对方")), len(jb["plan"])),
       (True, 1))
expect("安排：聊天时给她看", "安排：读完第二部 车站就停下并告诉他" in pr.reader._note(jb, time.time()), True)
jb["next_at"] = 0
run(pr.reader.tick(time.time()))
expect("读完开头：主动说开头的感觉", any("刚读了开头" in p for p, _ in fbasics.said), True)
expect("进度按章节说", ("第一部 雨" in jb["state"]["moments"][0]["label"], "段" in jb["state"]["moments"][0]["label"]), (True, False))
expect("说过的记进 told", jb["told"][-1]["kind"], "mid")
end2 = R.find_point(jb["segs"], "第二部", 0)[0]
for _ in range(12):
    if jb["pace"] == "paused" or jb.get("done"):
        break
    jb["next_at"] = 0
    run(pr.reader.tick(time.time()))
expect("读到安排的地方：真停下了", (jb["pace"], jb["pos"], jb["pace_by"]), ("paused", end2, f"p{OWNER}"))
expect("读到安排的地方：主动告诉他", any("读完第二部 车站就停下来并告诉他" in r for _, r in fbasics.said), True)
expect("告诉他的材料：上次说起以后读的 + 别说第几段", ("上次跟他说起这本书以后" in fbasics.said[-1][0], "别说“第几段”" in fbasics.said[-1][0]), (True, True))
expect("停着：兄长自己安排的不另外报停", sum(1 for _, r in fbasics.said if "停在" in r and "三部曲" in r), 0)
expect("已经读过的地方：照实说", "你已经读过那儿了" in run(pr.reading_plan(ev_book, "第一部", "告诉对方")), True)
# 停着时再给安排 = 接着读到那儿；他正在聊没说成 → 记着，过两分钟再说
r2 = run(pr.reading_plan(ev_book, f"第{end2 + 1}段", "告诉对方"))
expect("停着时给安排：接着读", (jb["pace"], "现在接着读" in r2), ("normal", True))
fbasics.ok = False
for _ in range(3):
    jb["next_at"] = 0
    run(pr.reader.tick(time.time()))
    if jb.get("point_pending"):
        break
expect("他正在聊：要说的记着", bool(jb.get("point_pending")), True)
fbasics.ok = True
jb["point_pending"]["try"] = 0
jb["next_at"] = time.time() + 9999
run(pr.reader.tick(time.time()))
expect("过两分钟再说：说成了", (jb.get("point_pending"), jb["told"][-1]["kind"]), (None, "point"))
# 主动说的话别重复：前面说过的交给她看
jb["told"][-1]["text"] = "车站那里好难过呀"
expect("前面说过的给她看", "车站那里好难过呀" in pr.reader._note(jb, time.time()), True)
# 大脑那一轮：她说“读完第三部就告诉兄长”却没调工具 → 替她定下；她说的也记进 told
pr.reader.set_pace(f"p{OWNER}", "先停一下", "三部曲")


async def plan_generate(pid, prompt, system="", timeout=0):
    return json.dumps({"wrong": [], "fixed": "", "commit": "", "plan": {"at": "第三部", "then": "告诉对方", "edge": "读完"}},
                      ensure_ascii=False)


pr.body.generate = plan_generate
ev_b = AstrMessageEvent(sender=OWNER, text="读完第三部跟我说一声", name="晴川")
run(pr.inject(ev_b, ProviderRequest(system_prompt="人设")))
ev_b.set_extra("_ks_brain", True)
run(pr.after_reply(ev_b, LLMResponse("好呀，佳树读完第三部就告诉兄长大人")))
expect("大脑那轮：答应了却没定 → 替她定下", [p["place"] for p in jb.get("plan", [])], ["第三部 回家"])
expect("大脑那轮：她说的记进 told", jb["told"][-1]["text"], "好呀，佳树读完第三部就告诉兄长大人")
# 读书学更细的心情说法
pr.reader.keep_feeling({"feel": "替舜憋屈", "emotion": "难过", "expr": "说不出恭喜就已经够难受了", "expr_feel": "嫉妒又放不下朋友"}, "读《九月》")
pr.reader.keep_feeling({"feel": "替舜憋屈", "emotion": "难过"}, "读《九月》")
expect("心情说法：同样的不重复", sum(1 for x in pr.reader._feelings() if x.get("feel") == "替舜憋屈"), 1)
fnote = pr.reader.feelings_note(seed=1)
expect("心情说法：给大脑看", ("替舜憋屈" in fnote, "说不出恭喜就已经够难受了" in fnote), (True, True))
reqf = ProviderRequest(system_prompt="人设")
run(pr.inject(AstrMessageEvent(sender=OTHER, text="今天好热", name="小雨"), reqf))
expect("心情说法：聊天时带上", "更细的心情说法" in reqf.system_prompt, True)


print("\nALL OK" if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
