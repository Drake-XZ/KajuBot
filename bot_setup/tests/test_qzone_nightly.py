"""Offline tests for qzone_post 1.2.0 每晚的说说（选材 → 写 → 核对 → 过了才发）+ 对话里发说说的检查。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_qzone_nightly.py

假数据、假模型、假发布：不联网、不碰机器人的真实数据。
"""

import asyncio
import datetime as dt
import importlib
import json
import os
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
from astrbot.api.star import Context  # noqa: E402

ng = importlib.import_module("qzone_post.nightly")
qm = importlib.import_module("qzone_post.main")

OWNER, FRIEND, GID = "111111111", "111", "222222222"
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def ok(label, cond):
    expect(label, bool(cond), True)


# ------------------------------------------------------------------ 换天
day, since = ng.day_window(dt.datetime(2026, 11, 7, 22, 30, tzinfo=TZ), 5)
expect("day window", (day, dt.datetime.fromtimestamp(since, TZ).hour), ("2026-11-07", 5))
expect("day window before 5am", ng.day_window(dt.datetime(2026, 11, 8, 2, 0, tzinfo=TZ), 5)[0], "2026-11-07")

# ------------------------------------------------------------------ 假数据
NOW = dt.datetime(2026, 11, 7, 22, 30, tzinfo=TZ).timestamp()


def w(rel, data, jsonl=False):
    path = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if jsonl:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n")
        else:
            json.dump(data, f, ensure_ascii=False)


LOG = [
    {"t": "12:01", "c": f"p{OWNER}", "u": OWNER, "n": "晴川", "x": "佳树，我中午又吃了麦当劳，巨无霸有两块肉"},
    {"t": "12:02", "c": f"p{OWNER}", "u": "self", "n": "佳树", "x": "又是麦当劳！兄长大人要好好吃饭呀 &&生气&&"},
    {"t": "12:03", "c": f"p{OWNER}", "u": OWNER, "n": "晴川", "x": "[图片]"},
    {"t": "13:00", "c": f"g{GID}", "u": FRIEND, "n": "哆啦a梦学姐", "x": "我下周要去医院复查，有点怕"},
    {"t": "13:01", "c": f"g{GID}", "u": "self", "n": "佳树", "x": "学姐别怕，佳树陪着你"},
    {"t": "20:00", "c": f"p{OWNER}", "u": OWNER, "n": "晴川", "x": "/佳树日记"},
]
w("astrbot_plugin_kaju_life/log/2026-11-07.jsonl", LOG, jsonl=True)
w("astrbot_plugin_kaju_life/log/2026-11-06.jsonl", [
    {"t": "12:00", "c": f"p{OWNER}", "u": OWNER, "n": "x", "x": "昨天的事"}], jsonl=True)
w("astrbot_plugin_kaju_life/names.json", {"groups": {GID: "妖妖"}, "people": {OWNER: "晴川", FRIEND: "哆啦a梦学姐"}})
w("astrbot_plugin_address_book/addresses.json", {OWNER: {"address": "兄长大人"}, FRIEND: {"address": "多拉学姐"}})
w("astrbot_plugin_kaju_basics/browse.json", {"sessions": [
    {"t0": NOW - 3600 * 5, "by": "兄长大人", "topic": "", "items": [
        {"title": "带小傻龙出去玩", "up": "某UP", "why": "想看小傻龙", "emo": "开心", "voice": "也想和兄长大人去旅行"}]},
    {"t0": NOW - 86400 * 2, "by": "兄长大人", "items": [{"title": "前天的视频"}]},
]})
w("astrbot_plugin_kaju_heart/state.json", {"inner_log": [
    {"t": NOW - 3000, "chat": f"p{OWNER}", "group": "", "text": "【佳树心里】11月7日中午，和兄长大人私聊（他又吃麦当劳）：好想给他做顿家常饭。"},
    {"t": NOW - 2000, "chat": f"g{GID}", "group": GID, "text": "【佳树心里】11月7日下午，在妖妖里（学姐要去医院）：希望学姐没事。"},
]})

items = ng.collect(DATA, OWNER, "2026-11-07", since, tz=TZ)
texts = [it["text"] for it in items]
expect("collect kinds", [it["kind"] for it in items], ["私聊", "私聊", "B站", "心声"])
expect("collect ids", [it["id"] for it in items], [1, 2, 3, 4])
ok("collect owner line", texts[0].startswith("兄长大人：佳树，我中午又吃了麦当劳"))
expect("collect strips meme tag", texts[1], "佳树：又是麦当劳！兄长大人要好好吃饭呀")
ok("collect: no group chat, no group inner, no commands, no images, no old days",
   not any(("学姐" in t or "医院" in t or "/佳树" in t or "[图片]" in t or "前天" in t) for t in texts))
ok("collect browse line", "带小傻龙出去玩" in texts[2] and "也想和兄长大人去旅行" in texts[2])
ok("collect inner no prefix", texts[3].startswith("11月7日中午") and "【佳树心里】" not in texts[3])
mat = ng.render_material(items)
ok("render material", "【和兄长大人的私聊】\n[1] 12:01 兄长大人：" in mat and "\n【佳树心里记下的】\n[4]" in mat)

noon = dt.datetime(2026, 11, 7, 12, 1, 30, tzinfo=TZ).timestamp()
expect("collect until", [it["kind"] for it in ng.collect(DATA, OWNER, "2026-11-07", since, tz=TZ, until=noon)], ["私聊"])
expect("log ts after midnight", dt.datetime.fromtimestamp(ng._log_ts("00:30", since, TZ), TZ).day, 8)

w("astrbot_plugin_kaju_life/days.json", {"2026-11-10": {"mood": "还行", "events": [
    {"time": "23:30", "text": "还没到的事"}, {"time": "07:00", "text": "早起做便当"}, {"time": "01:00", "text": "过了半夜的事"}],
    "share": {"time": "16:40", "text": "买了布丁留给兄长大人"}}})
d10, s10 = ng.day_window(dt.datetime(2026, 11, 10, 22, 30, tzinfo=TZ), 5)
u10 = dt.datetime(2026, 11, 10, 22, 30, tzinfo=TZ).timestamp()
daily = ng.collect(DATA, OWNER, d10, s10, tz=TZ, until=u10)
expect("daily: only up to now, in time order", [(it["kind"], it["t"], it["text"]) for it in daily],
       [("日常", "07:00", "早起做便当"), ("日常", "16:40", "买了布丁留给兄长大人（想跟兄长大人说的事）")])
ok("daily: rendered head", "【佳树自己今天的日常】\n[1] 07:00 早起做便当" in ng.render_material(daily))
expect("daily: other day none", ng.collect(DATA, OWNER, "2026-11-11", s10 + 86400, tz=TZ, until=u10 + 86400), [])

long_items = ng.collect(DATA, OWNER, "2026-11-07", since, budget=10, tz=TZ)
ok("collect budget keeps browse + inner", [it["kind"] for it in long_items][-2:] == ["B站", "心声"])

# ------------------------------------------------------------------ 解析
plan = ng.parse_plan('好的：{"post": true, "reason": "r", "topics": ["麦当劳", "小傻龙"], "facts": ['
                     '{"say": "兄长大人中午吃了巨无霸", "src": [1]}, {"say": "没出处的事", "src": []},'
                     '{"say": "编号不存在", "src": [99]}], "feel": "想给兄长做饭", "avoid": []}', 4)
expect("plan facts filtered", [f["say"] for f in plan["facts"]], ["兄长大人中午吃了巨无霸"])
expect("plan post", plan["post"], True)
expect("plan without facts → no post", ng.parse_plan('{"post": true, "facts": []}', 4)["post"], False)
expect("plan garbage", ng.parse_plan("不知道", 4), None)
expect("check ok", ng.parse_check('{"ok": true, "problems": []}'), [])
expect("check problems", ng.parse_check('{"ok": false, "problems": [{"kind": "事实", "text": "没说过"}]}'), ["事实：没说过"])
expect("check not ok without reason", ng.parse_check('{"ok": false}'), ["核对没通过（没说原因）"])
expect("check garbage", ng.parse_check("嗯"), None)
expect("clean post", ng.clean_post("说说正文：“兄长大人今天好厉害！&&开心&&”"), "兄长大人今天好厉害！")

# ------------------------------------------------------------------ 硬伤
H = ng.check_hard
expect("hard clean", H("兄长大人又吃了麦当劳，佳树好想给兄长大人做一桌家常菜！"), [])
ok("hard qq number", any("QQ" in p for p in H("佳树的QQ是555555555哦")))
ok("hard link", any("链接" in p for p in H("看这个 https://b23.tv/x")))
ok("hard meta", any("素材" in p for p in H("今天的素材不多")))
ok("hard nickname", any("哆啦a梦学姐" in p for p in H("哆啦A梦学姐今天好可爱", names=["哆啦a梦学姐", "兄长大人"])))
expect("hard common title ok", H("兄长大人和学姐都在", names=["学姐", "兄长大人"]), [])
ok("hard group name", any("妖妖" in p for p in H("在妖妖群里聊天", groups=["妖妖"])))
ok("hard quote", any("原话" in p for p in H("兄长大人说：我中午又吃了麦当劳巨无霸有两块肉", others_lines=["佳树，我中午又吃了麦当劳，巨无霸有两块肉"])))
expect("hard paraphrase ok", H("兄长大人中午又去吃麦当劳了", others_lines=["佳树，我中午又吃了麦当劳，巨无霸有两块肉"]), [])
ok("hard copies example", any("撞句" in p for p in H("佳树一定要做满满一大桌菜给兄长大人吃！", old_posts=ng.EXAMPLES)))
ok("hard too long", any("超过" in p for p in H("佳" * 501)))
ok("write system has examples + rules", "小傻龙" in ng.write_system() and "真名" in ng.write_system())
ok("write prompt has feedback", "上一稿" in ng.write_prompt({"facts": [{"say": "a"}], "feel": "b"}, ["事实：x"], "旧稿"))


# ------------------------------------------------------------------ 整个流程（假模型）
class FakeLLM:
    def __init__(self):
        self.plan = {"post": True, "reason": "兄长大人又吃麦当劳", "topics": ["麦当劳", "小傻龙"],
                     "facts": [{"say": "兄长大人中午又吃了麦当劳", "src": [1]},
                               {"say": "佳树刷到带小傻龙出去玩的视频", "src": [3]}],
                     "feel": "佳树想给兄长做家常饭，也想和兄长旅行", "avoid": []}
        self.drafts = ["兄长大人中午又去吃麦当劳了，佳树好想给兄长大人做顿家常饭。下午还看了小傻龙出去玩的视频，佳树也想和兄长大人一起去旅行！"]
        self.checks = ['{"ok": true, "problems": []}']
        self.calls = []

    async def __call__(self, chat_provider_id=None, prompt="", system_prompt=""):
        if system_prompt == ng.PLAN_SYSTEM:
            kind, out = "plan", json.dumps(self.plan, ensure_ascii=False)
        elif system_prompt == ng.CHECK_SYSTEM:
            kind, out = "check", self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]
        else:
            kind, out = "write", self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]
        self.calls.append((kind, prompt))
        return type("Resp", (), {"completion_text": out})()


class Prov:
    provider_config = {"id": "deepseek"}


def make_plugin(cfg=None):
    ctx = Context()
    ctx.providers = {"deepseek": Prov()}
    llm = FakeLLM()
    ctx.llm_generate = llm
    ctx.get_platform = lambda name: None
    p = qm.QzonePost(ctx, cfg or {})
    published = []

    async def publish(content, self_initiated, by, topics=None, source="", bot=None):
        published.append({"content": content, "topics": topics, "source": source})
        p._posts.append({"time": int(time.time()), "content": content, "self_initiated": self_initiated,
                         "topics": topics or [], "by": by})
        return True, "TID1"

    p._publish = publish
    return p, llm, published


async def flow_tests():
    # draft 模式：写好、核对过，不发
    p, llm, pub = make_plugin()
    expect("default mode draft", p._nmode(), "draft")
    run = await p.run_nightly(publish=False, now=NOW)
    expect("draft: status", (run["status"], run["material"], pub), ("draft", 4, []))
    expect("draft: steps", [k for k, _ in llm.calls], ["plan", "write", "check"])
    write_prompt = llm.calls[1][1]
    ok("draft: writer never sees raw chat", "巨无霸有两块肉" not in write_prompt and "兄长大人中午又吃了麦当劳" in write_prompt)
    ok("draft: checker sees material", "巨无霸有两块肉" in llm.calls[2][1])
    expect("draft: saved", p._load(p._npath, {})["runs"][-1]["status"], "draft")

    # 管理员 /佳树说说 发（"发"只认两天内的草稿：NOW 是固定的 11-07，测试那天早过了两天 → 当它是刚写的）
    p._nstate["runs"][-1]["t"] = int(time.time())
    ev = AstrMessageEvent(sender=OWNER, text="/佳树说说 发")
    out = [x async for x in p.nightly_cmd(ev, "发")]
    ok("cmd publish", out[-1].startswith("发好了") and pub[-1]["source"] == "nightly-approved")
    expect("cmd publish marks posted", p._nstate["runs"][-1]["status"], "posted")
    out = [x async for x in p.nightly_cmd(ev, "发")]
    expect("cmd publish twice", out[-1], "没有两天内核对过、还没发的草稿。")
    out = [x async for x in p.nightly_cmd(AstrMessageEvent(sender=FRIEND, admin=False), "发")]
    expect("cmd not admin", out, [])
    out = [x async for x in p.nightly_cmd(ev, "")]
    ok("cmd list", "draft 模式" in out[0] and "发了" in out[0])
    ok("recent topics after nightly post", p._recent_topics(3)[0].endswith("麦当劳、小傻龙"))

    # post 模式：过了就发，记下话题
    p, llm, pub = make_plugin({"nightly": {"mode": "post"}})
    run = await p.run_nightly(publish=True, now=NOW)
    expect("post: published", (run["status"], run["tid"], pub[0]["topics"], pub[0]["source"]),
           ("posted", "TID1", ["麦当劳", "小傻龙"], "nightly"))

    # 第一稿没过核对 → 带着问题重写一次 → 过了
    p, llm, pub = make_plugin()
    llm.checks = ['{"ok": false, "problems": [{"kind": "事实", "text": "素材里兄长没说想旅行"}]}', '{"ok": true}']
    llm.drafts = ["兄长大人说想和佳树去旅行！", "兄长大人中午又去吃麦当劳了，佳树好想给兄长大人做顿家常饭。"]
    run = await p.run_nightly(publish=True, now=NOW)
    expect("retry: posted second draft", (run["status"], len(run["attempts"]), pub[0]["content"]),
           ("posted", 2, "兄长大人中午又去吃麦当劳了，佳树好想给兄长大人做顿家常饭。"))
    ok("retry: feedback in rewrite prompt", "素材里兄长没说想旅行" in llm.calls[3][1] and "上一稿" in llm.calls[3][1])

    # 两稿都没过 → 不发
    p, llm, pub = make_plugin()
    llm.checks = ['{"ok": false, "problems": [{"kind": "隐私", "text": "写了学姐的事"}]}']
    run = await p.run_nightly(publish=True, now=NOW)
    expect("blocked: not posted", (run["status"], pub, len(run["attempts"])), ("blocked", [], 2))
    ok("blocked: reason", "学姐" in run["reason"])
    out = [x async for x in p.nightly_cmd(AstrMessageEvent(sender=OWNER), "")]
    ok("blocked: cmd shows", "没过检查" in out[0] and "第一稿的问题" in out[0])

    # 硬伤（照搬原话）不用模型核对，直接重写
    p, llm, pub = make_plugin()
    llm.drafts = ["兄长大人说佳树我中午又吃了麦当劳巨无霸有两块肉", "兄长大人中午又去吃麦当劳了，佳树想给他做饭。"]
    run = await p.run_nightly(publish=True, now=NOW)
    expect("hard: steps", [k for k, _ in llm.calls], ["plan", "write", "write", "check"])
    expect("hard: posted clean one", run["status"], "posted")

    # 核对的回答看不懂 → 不发
    p, llm, pub = make_plugin()
    llm.checks = ["嗯嗯没问题"]
    run = await p.run_nightly(publish=True, now=NOW)
    expect("check garbage: blocked", (run["status"], pub), ("blocked", []))

    # 选材说不发
    p, llm, pub = make_plugin()
    llm.plan = {"post": False, "reason": "今天只说了晚安", "facts": []}
    run = await p.run_nightly(publish=True, now=NOW)
    expect("plan no: skip", (run["status"], run["reason"], [k for k, _ in llm.calls]), ("skip", "今天只说了晚安", ["plan"]))

    # 没有素材
    p, llm, pub = make_plugin()
    run = await p.run_nightly(publish=True, now=dt.datetime(2026, 11, 9, 22, 30, tzinfo=TZ).timestamp())
    expect("no material: skip without model", (run["status"], llm.calls), ("skip", []))

    # 今天已经主动发够了
    p, llm, pub = make_plugin({"auto_daily_limit": 1})
    p._posts.append({"time": int(time.time()) - 60, "content": "x", "self_initiated": True})
    run = await p.run_nightly(publish=True, now=time.time())
    expect("limit: skip", (run["status"], llm.calls), ("skip", []))

    # 模型出错
    p, llm, pub = make_plugin()

    async def boom(**k):
        raise TimeoutError("慢")
    p.context.llm_generate = boom
    run = await p.run_nightly(publish=True, now=NOW)
    expect("error: recorded", (run["status"], pub), ("error", []))

    # 到点判断
    p, llm, pub = make_plugin()
    at = dt.datetime(2026, 11, 7, 22, 30, tzinfo=TZ).timestamp()
    expect("due: before", p._due(at - 60), False)
    expect("due: at", p._due(at + 10), True)
    expect("due: too late", p._due(at + 91 * 60), False)
    p._nstate["last_day"] = "2026-11-07"
    expect("due: done today", p._due(at + 10), False)
    p2, _, _ = make_plugin({"nightly": {"mode": "off"}})
    expect("due: off", p2._due(at + 10), False)

    # 交给说话习惯插件写（writer=local）：写出来有硬伤就用 DeepSeek 原稿
    p, llm, pub = make_plugin({"nightly": {"writer": "local"}})

    class Style:
        def __init__(self, out): self.out, self.calls = out, []
        async def _plan_from_draft(self, *a): pass
        async def polish(self, draft, ctx, said, kind="", split=True):
            self.calls.append((draft, kind, split))
            return self.out
    st = Style("兄长大人中午吃了麦当劳呢，佳树想给兄长大人做好吃的！")
    p.context.stars = [type("Meta", (), {"star_cls": st})()]
    run = await p.run_nightly(publish=False, now=NOW)
    expect("local: used", (run["text"], st.calls[0][1:]), ("兄长大人中午吃了麦当劳呢，佳树想给兄长大人做好吃的！", ("说说", False)))
    st.out = "佳树的QQ是555555555"
    p._nstate["runs"].clear()
    run = await p.run_nightly(publish=False, now=NOW)
    ok("local: bad output falls back to draft", run["text"].startswith("兄长大人中午又去吃麦当劳了"))


async def tool_tests():
    w("astrbot_plugin_kaju_life/log/" + ng.day_window(dt.datetime.now(TZ), 5)[0] + ".jsonl", LOG, jsonl=True)

    # 旧的定时任务被挡掉
    p, llm, pub = make_plugin()
    CronMessageEvent = type("CronMessageEvent", (AstrMessageEvent,), {})
    out = await p.post_qzone(CronMessageEvent(sender="cron", admin=False), "今天天气很好", True)
    ok("cron blocked", out.startswith("没发：每晚的说说现在由佳树自己的流程写") and pub == [])
    p2, _, pub2 = make_plugin({"nightly": {"mode": "off"}})
    out = await p2.post_qzone(CronMessageEvent(sender="cron", admin=False), "兄长大人今天好厉害", True)
    ok("cron allowed when off", out.startswith("发布成功") and len(pub2) == 1)

    # 管理员让发：只查硬伤
    p, llm, pub = make_plugin()
    out = await p.post_qzone(AstrMessageEvent(sender=OWNER), "佳树的QQ号是555555555", False)
    ok("admin: hard check blocks", out.startswith("没发：发布前检查没通过") and "兄长大人" in out and pub == [])
    out = await p.post_qzone(AstrMessageEvent(sender=OWNER), "兄长大人让佳树发一条：今天好开心！", False)
    expect("admin: ok, no model check", (out.startswith("发布成功"), llm.calls), (True, []))

    # 自己想发：硬伤 + 模型核对（素材是这个聊天今天的记录）
    p, llm, pub = make_plugin()
    llm.checks = ['{"ok": false, "problems": [{"kind": "隐私", "text": "写了学姐去医院"}]}']
    out = await p.post_qzone(AstrMessageEvent(sender=FRIEND, group=GID, admin=False), "学姐下周要去复查", True)
    ok("self: model check blocks", "学姐去医院" in out and pub == [])
    ok("self: check saw group chat", "我下周要去医院复查" in llm.calls[0][1] and "哆啦a梦学姐：" in llm.calls[0][1])
    llm.checks = ['{"ok": true}']
    out = await p.post_qzone(AstrMessageEvent(sender=OWNER), "兄长大人又吃麦当劳了，佳树要监督他好好吃饭！", True)
    ok("self: passes", out.startswith("发布成功") and len(pub) == 1)

    # 提示里最近的说说只给话题 / 开头几个字
    p, _, _ = make_plugin()
    p._posts = [{"time": int(NOW), "content": "很长很长的一条以前写的说说内容在这里结束", "self_initiated": True},
                {"time": int(NOW), "content": "x", "topics": ["麦当劳"], "self_initiated": True}]
    tops = p._recent_topics(3)
    expect("recent topics", [t.split("：", 1)[1] for t in tops], ["麦当劳", "很长很长的一条以前写的说说内…"])


asyncio.run(flow_tests())
asyncio.run(tool_tests())
print("FAILURES:", len(failures)) if failures else print("all qzone nightly tests passed")
sys.exit(1 if failures else 0)
