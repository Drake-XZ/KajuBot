"""Offline tests for the custom plugins — no running AstrBot needed (astrbot is stubbed).

Run with AstrBot's venv python (it has aiohttp / tzdata):
    D:\\JiashuBot\\AstrBot-Data\\instances\\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\\venv\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_plugins.py
Exit code 0 = all passed.
"""

import asyncio
import datetime as dt
import importlib
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import random
import sys
import tempfile
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import Poke  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ every plugin imports
for name in sorted(os.listdir(PLUGINS)):
    if os.path.isfile(os.path.join(PLUGINS, name, "main.py")):
        try:
            importlib.import_module(f"{name}.main")
        except Exception as exc:  # noqa: BLE001
            expect(f"import {name}", repr(exc), "ok")

# ------------------------------------------------------------------ kaju_style
from kaju_core.voice.rhythm import restyle  # noqa: E402

for src, want in {
    "诶嘿嘿，佳树记下了。那以后就叫这位女王大人了哦～": "诶嘿嘿，佳树记下了\n那以后就叫这位女王大人了哦～",
    "是的！那佳树就放心了。女王大人玩的时候记得开灯哦。": "是的！那佳树就放心了\n女王大人玩的时候记得开灯哦",
    "被问到就说\"不、告、诉、你。\"好了。": "被问到就说\"不、告、诉、你。\"好了",
    "嗯。。。好吧。": "嗯。。。好吧",
    "（笑。）好的。": "（笑。）好的",
    "```py\nx = 1。\n```": "```py\nx = 1。\n```",
}.items():
    expect(f"restyle {src[:10]}", restyle(src), want)
expect("restyle max_lines", len(restyle("一。二。三。四。五。六。").split("\n")), 4)

# 2026-11-03 句长校准：超过 20 字的消息在逗号处拆开（两边 ≥6 字、引号/书名号里不拆、最多 5 条）
for src, want in {
    # 她 11-02 的真实回复
    "555学长说的龙娘是指哪个角色呀，佳树对不上号呢\n听着像是在比谁的二创更顺眼嘛":
        "555学长说的龙娘是指哪个角色呀\n佳树对不上号呢\n听着像是在比谁的二创更顺眼嘛",
    "兄长大人，佳树查过了哦": "兄长大人，佳树查过了哦",  # 短的不拆
    "兄长大人，佳树查过了哦，手台就是打歌用的那个控制器呢":  # 只有 4 字的"兄长大人"不单独成条
        "兄长大人，佳树查过了哦\n手台就是打歌用的那个控制器呢",
    "学姐说的“早上起来先喝水，然后再去跑步，最后吃早饭”佳树记下了":  # 引号里的逗号不拆
        "学姐说的“早上起来先喝水，然后再去跑步，最后吃早饭”佳树记下了",
    "佳树读完《春天来了，花也开了，鸟也叫了》这本书了呢": "佳树读完《春天来了，花也开了，鸟也叫了》这本书了呢",
    "没有句号也没有逗号的一句很长很长很长很长很长的话呀": "没有句号也没有逗号的一句很长很长很长很长很长的话呀",
    "&&happy&&": "&&happy&&",
}.items():
    expect(f"split_long {src[:12]}", restyle(src), want)
_many = "\n".join(["佳树今天去了一趟超市呀，买了好多好多好吃的东西呢"] * 4)
expect("split_long caps at 5 lines", len(restyle(_many).split("\n")), 5)
expect("split_long off", restyle("佳树今天去了一趟超市呀，买了好多好多好吃的东西呢", split_max=0),
       "佳树今天去了一趟超市呀，买了好多好多好吃的东西呢")
expect("split_long + 句号", restyle("佳树今天去了一趟超市呀，买了好多好多好吃的东西呢。兄长大人要吃吗？"),
       "佳树今天去了一趟超市呀\n买了好多好多好吃的东西呢\n兄长大人要吃吗？")


async def style_tests():
    sh_hour = dt.datetime.now(zoneinfo.ZoneInfo("Asia/Shanghai")).hour
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {
        "rhythm": {"prompt_note": False},
        "bedtime": {"late_start_hour": sh_hour, "late_end_hour": (sh_hour + 1) % 24, "nag_chance": 0.0}})
    ev = AstrMessageEvent(text="在干嘛")
    req = ProviderRequest("SYS")
    await st.remind(ev, req)
    # bedtime runs on the configured timezone (Asia/Shanghai), not the server clock
    expect("bedtime late (Shanghai clock)", st._is_late(), True)
    expect("bedtime note: no nag", "不要催对方睡觉" in req.system_prompt, True)
    await st.after_reply(ev, LLMResponse("早点睡哦"))
    req = ProviderRequest("SYS")
    await st.remind(AstrMessageEvent(text="好困"), req)
    expect("bedtime remembers nag", "已经叮嘱过" in req.system_prompt, True)
    st.config["bedtime"]["late_start_hour"] = (sh_hour + 1) % 24
    st.config["bedtime"]["late_end_hour"] = (sh_hour + 2) % 24
    expect("bedtime not late", st._is_late(), False)


asyncio.run(style_tests())

# ------------------------------------------------------------------ kaju_style: 被纠正
from astrbot.api.message_components import Reply  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402
from kaju_core.voice.rebuttal import is_rebuttal  # noqa: E402

# 2026-10-30 私聊里她真实的三次回复
REAL = ["诶——那是老师？\n佳树还当是个碗呢\n被蹭成那样，老师也真好脾气\n妃咲，佳树记住了",
        "被蹭成那样还笑得出来，老师也是没办法吧\n妃咲这招，佳树倒是有点想学",
        "诶——是亲呀？\n佳树完全看错了\n那被亲了还笑得出来，老师果然一点没恼\n这招佳树可学不来"]

expect("rebut: quoted + 怎么会", is_rebuttal("那说明妃咲很喜欢老师哦，老师怎么会生气呢", "被蹭成那样，老师也真好脾气", "x"), True)
expect("rebut: quoted + 不是", is_rebuttal("那不是在蹭老师哦佳树，那是妃咲在亲老师", "q", "x"), True)
expect("rebut: quoted, just chatting", is_rebuttal("好呀，那明天见", "q", "x"), False)
expect("rebut: no quote, 不是啦", is_rebuttal("不是啦，那是亲", None, "被蹭成那样"), True)
expect("rebut: no quote, 你看错了", is_rebuttal("你看错了吧", None, "x"), True)
expect("rebut: 你说的没错", is_rebuttal("你说的没错", None, "x"), False)
expect("rebut: 这个不错", is_rebuttal("这个不错哦", None, "x"), False)
expect("rebut: no quote, no reply yet", is_rebuttal("不是啦", None, ""), False)
expect("rebut: no quote, 怎么会…呢", is_rebuttal("那说明妃咲很喜欢老师哦，老师怎么会生气呢", None, "x"), True)
expect("rebut: no quote, 怎么会这样", is_rebuttal("怎么会这样", None, "x"), False)


async def rebuttal_tests():
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {
        "rhythm": {"prompt_note": True},
        "bedtime": {"enable": False}, "rebuttal": {"window_minutes": 120}})
    ctx = [{"role": "user", "content": "看这个"}, {"role": "assistant", "content": REAL[0]},
           {"role": "user", "content": "那说明妃咲很喜欢老师哦"}, {"role": "assistant", "content": REAL[1]}]

    async def ask(text, quote_sender="555555555"):
        msgs = [Reply(sender_id=quote_sender, sender_nickname="佳树")] if quote_sender else []
        ev = AstrMessageEvent(text=text, messages=msgs)
        req = ProviderRequest("SYS", contexts=ctx)
        req.extra_user_content_parts.append(
            TextPart("<Quoted Message>\n(佳树): 被蹭成那样还笑得出来，老师也是没办法吧\n</Quoted Message>"))
        for hook in (st.remind_rhythm, st.remind_rebuttal):  # 按优先级 -60 / -70
            await hook(ev, req)
        return req.system_prompt

    sp = await ask("那说明妃咲很喜欢老师哦，老师怎么会生气呢")
    expect("rebuttal note comes last", sp.rsplit("\n\n", 1)[-1].startswith("【对方在纠正你】"), True)
    expect("rebuttal note quotes her line", "老师也是没办法吧" in sp.rsplit("【对方在纠正你】", 1)[-1], True)
    sp = await ask("那不是在蹭老师哦佳树，那是妃咲在亲老师")
    expect("rebuttal counts times", "第 2 次" in sp, True)
    sp = await ask("那不是在蹭老师哦", quote_sender="123456")
    expect("quoting someone else: no note", "【对方在纠正你】" in sp, False)
    sp = await ask("那说明妃咲很喜欢老师哦，老师怎么会生气呢", quote_sender="bot")
    expect("webchat: quoting bot counts", "引用了你说的「被蹭成那样还笑得出来" in sp, True)
    sp = await ask("好呀，那明天见")
    expect("plain reply to quote: no note", "【对方在纠正你】" in sp, False)


asyncio.run(rebuttal_tests())

async def restyle_hook_tests():
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})
    long = "佳树今天去了一趟超市呀，买了好多好多好吃的东西呢"
    expect("restyle hook: keeps connected sentence", st._restyle(long), long)
    st3 = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"rhythm": {"split_long": 0}})
    expect("restyle hook: split_long 0", st3._restyle(long), long)


asyncio.run(restyle_hook_tests())

# 2026-11-03 聊作品说具体
from kaju_core.voice import concrete  # noqa: E402

expect("concrete: shelf offered", concrete.should_fire("而且节奏很快", True, False), True)
expect("concrete: read a file", concrete.should_fire("", False, True), True)
expect("concrete: asks about a book", concrete.should_fire("佳树觉得跟普通轻小说哪里不一样呢？", False, False), True)
expect("concrete: chit-chat", concrete.should_fire("今天好累", False, False), False)
_ev = AstrMessageEvent(messages=[])
_ev.message_str = "佳树觉得这个视频怎么样"
_ev.set_extra("kaju_docs_read", [{"name": "x"}])
expect("concrete: fires after watching the old way", importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})._concrete(_ev), True)
_ev = AstrMessageEvent(messages=[])
_ev.message_str = "佳树觉得这个视频怎么样"
_ev.set_extra("kaju_docs_read", [{"name": "x"}])
_ev.set_extra("_kaju_felt", True)
expect("concrete: off when she watched with feelings", importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})._concrete(_ev), False)
expect("concrete: 感觉 without a work", concrete.should_fire("感觉好冷", False, False), False)


async def concrete_hook_tests():
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})
    ev = AstrMessageEvent(text="而且节奏很快")
    ev.set_extra("memory_weight_shelf_offered", ["abc"])
    req = ProviderRequest("SYS", contexts=[])
    await st.remind_concrete(ev, req)
    expect("concrete hook: note", "【说具体、说连贯】" in req.system_prompt, True)
    long = "佳树今天去了一趟超市呀，买了好多好多好吃的东西呢"
    expect("concrete: no comma split", st._restyle(long, ev), long)
    plain_ev = AstrMessageEvent(text="今天好累")
    req = ProviderRequest("SYS", contexts=[])
    await st.remind_concrete(plain_ev, req)
    expect("concrete hook: chit-chat → no note", req.system_prompt, "SYS")
    expect("chit-chat keeps connected sentence", st._restyle(long, plain_ev), long)
    st2 = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"concrete": {"enable": False}})
    ev2 = AstrMessageEvent(text="而且节奏很快")
    ev2.set_extra("memory_weight_shelf_offered", ["abc"])
    req = ProviderRequest("SYS", contexts=[])
    await st2.remind_concrete(ev2, req)
    expect("concrete disabled", "【说具体" in req.system_prompt, False)


asyncio.run(concrete_hook_tests())

# 2026-11-04 重说层
from kaju_core.voice import rewrite  # noqa: E402

expect("rewrite: tags split", rewrite.split_tags("佳树看懂了\n&&shy&&"), ("佳树看懂了", ["&&shy&&"]))
expect("rewrite: tags back", rewrite.with_tags("看懂了呢", ["&&shy&&"]), "看懂了呢\n&&shy&&")
expect("rewrite: skip link", rewrite.skip_reason("佳树查到了 https://x.y", 400), "带代码/链接/SKIP")
expect("rewrite: skip SKIP", rewrite.skip_reason("[SKIP]", 400), "带代码/链接/SKIP")
expect("rewrite: skip long", bool(rewrite.skip_reason("佳" * 401, 400)), True)
expect("rewrite: ok", rewrite.skip_reason("兄长大人中午好呀", 400), "")
tof = lambda qq, name: {"111111111": "兄长大人", "777777777": "555学长"}.get(qq, "") if qq else "兄长大人"  # noqa: E731
expect("rewrite: label owner in group", rewrite.label("user", "[发言人：林一，QQ 111111111] 是不是还挺聪明的", tof), "兄长大人：是不是还挺聪明的")
expect("rewrite: label other in group", rewrite.label("user", "[发言人：555，QQ 777777777] 发点好看的图", tof), "555学长：发点好看的图")
expect("rewrite: label private", rewrite.label("user", "我煮了水饺<system_reminder>x</system_reminder>", tof), "兄长大人：我煮了水饺")
expect("rewrite: label her", rewrite.label("assistant", "好呀\n&&happy&&", tof), "佳树：好呀 / ")
expect("rewrite: guard ok", rewrite.guard_bad('{"bad": false, "what": ""}'), (False, ""))
expect("rewrite: guard bad", rewrite.guard_bad('{"bad": true, "what": "叫错人"}'), (True, "叫错人"))
expect("rewrite: guard unreadable", rewrite.guard_bad("嗯")[0], True)
expect("rewrite: clean output", rewrite.clean_output("佳树：好的兄长大人\n佳树：马上去"), "好的兄长大人\n马上去")
expect("rewrite: guard told who", "回给「555学长」" in rewrite.guard_prompt("x", "a", "b", "555学长"), True)
expect("rewrite: guard sees context", "佳树：开了好久会" in rewrite.guard_prompt("x", "a", "b", "兄长大人", ["佳树：开了好久会"]), True)
# 开头应答：改写新加的才问场合；不合适只去掉开头
expect("opener: added", rewrite.added_opener("好的兄长大人！佳树记下了", "佳树记下了"), "好的兄长大人！")
expect("opener: draft had it", rewrite.added_opener("好的兄长大人！佳树记下了", "好的呀 佳树记下了"), "")
expect("opener: 好的呀 is not one", rewrite.added_opener("好的呀，佳树记下了", "佳树记下了"), "")
expect("opener: group title", rewrite.added_opener("是的呢哆啦a梦学姐，佳树也刷到过", "佳树也刷到过"), "是的呢哆啦a梦学姐，")
expect("opener: rule only when added", "合不合场合" in rewrite.guard_prompt("咋了", "佳树在呢", "好的兄长大人！佳树在呢"), True)
expect("opener: no rule otherwise", "合不合场合" in rewrite.guard_prompt("咋了", "佳树在呢", "佳树在呢～"), False)
expect("opener: strip", rewrite.strip_opener("好的兄长大人！佳树刚想跟兄长大人说\n佳树还以为兄长大人嫌佳树烦了呢"),
       "佳树刚想跟兄长大人说\n佳树还以为兄长大人嫌佳树烦了呢")
expect("opener: strip own line", rewrite.strip_opener("真的嘛兄长大人！\n佳树好开心"), "佳树好开心")
expect("opener: keep if nothing left", rewrite.strip_opener("好的兄长大人！嗯"), "好的兄长大人！嗯")
expect("opener: guard says no", rewrite.guard_opener_ok('{"bad": false, "what": "", "opener": false}'), False)
expect("opener: guard silent → keep", rewrite.guard_opener_ok('{"bad": false, "what": ""}'), True)


async def rewrite_hook_tests():
    ks = importlib.import_module("kaju_style.main")
    # writer_only 关着：这几条查的是“写不成就发原稿”那种退路（writer_only 默认开，这里明写关）
    st = ks.KajuStyle(Context(), {"bedtime": {"enable": False}, "rewrite": {"enable": True, "retry": 0, "writer_only": False}})
    calls = []

    async def fake_plan(ctx, draft, kind, title):
        calls.append((ctx, draft))
        return {"局面": "兄长大人煮了水饺", "要表达的": ["反问：什么馅"]}

    async def fake_write(ctx, plan, kind, title, ref=""):
        return "好的兄长大人，水饺是什么馅的呀"

    async def guard_ok(said, draft, new, title="", ctx=None):
        return False, ""

    async def guard_no(said, draft, new, title="", ctx=None):
        return True, "加了草稿没有的事"

    st._plan_from_draft, st._write, st._guard = fake_plan, fake_write, guard_ok
    ev = AstrMessageEvent(text="我煮了水饺")
    req = ProviderRequest("SYS", contexts=[{"role": "user", "content": "在吗"}, {"role": "assistant", "content": "佳树在哦"}])
    await st.rewrite_snapshot(ev, req)
    expect("rewrite hook: ctx labeled", ev.get_extra("_ks_rw_ctx")[-2:], ["佳树：佳树在哦", "兄长大人：我煮了水饺"])
    r = LLMResponse("兄长大人吃水饺呀，那佳树就放心了呢，是什么馅的呀？\n&&happy&&")
    await st.rewrite_reply(ev, r)
    expect("rewrite hook: replaced + tag kept", r.completion_text, "好的兄长大人，水饺是什么馅的呀\n&&happy&&")
    expect("rewrite hook: draft without tag", calls[-1][1], "兄长大人吃水饺呀，那佳树就放心了呢，是什么馅的呀？")
    expect("rewrite hook: no comma split after rewrite", st._restyle("佳树今天去了一趟超市呀，买了好多好多好吃的东西呢", ev),
           "佳树今天去了一趟超市呀，买了好多好多好吃的东西呢")
    # 核对不过 → 原稿
    st._guard = guard_no
    ev2 = AstrMessageEvent(text="我煮了水饺")
    await st.rewrite_snapshot(ev2, ProviderRequest("SYS", contexts=[]))
    r2 = LLMResponse("那佳树就放心了呢")
    await st.rewrite_reply(ev2, r2)
    expect("rewrite hook: guard fails → draft", r2.completion_text, "那佳树就放心了呢")
    # 开头不合场合 → 只去掉开头
    async def guard_opener_no(said, draft, new, title="", ctx=None):
        return False, "", False
    st._guard = guard_opener_no
    ev4 = AstrMessageEvent(text="我煮了水饺")
    await st.rewrite_snapshot(ev4, ProviderRequest("SYS", contexts=[]))
    r4 = LLMResponse("兄长大人吃水饺呀，是什么馅的呀？")
    await st.rewrite_reply(ev4, r4)
    expect("rewrite hook: opener out of place → stripped", r4.completion_text, "水饺是什么馅的呀")
    # 整理指导的模型出错 → 原稿
    async def boom(*a, **k):
        raise ConnectionError("relay down")
    st._plan_from_draft, st._guard = boom, guard_ok
    ev3 = AstrMessageEvent(text="在吗")
    await st.rewrite_snapshot(ev3, ProviderRequest("SYS", contexts=[]))
    r3 = LLMResponse("佳树在哦")
    await st.rewrite_reply(ev3, r3)
    expect("rewrite hook: planner down → draft", r3.completion_text, "佳树在哦")
    # 已经回晚了（这条等了 40 秒）：不重说，先发出去
    st._plan_from_draft = fake_plan
    n = len(calls)
    ev5 = AstrMessageEvent(text="我煮了水饺")
    ev5.set_extra("_kaju_quote_t", __import__("time").time() - 40)
    await st.rewrite_snapshot(ev5, ProviderRequest("SYS", contexts=[]))
    r5 = LLMResponse("那佳树就放心了呢")
    await st.rewrite_reply(ev5, r5)
    expect("rewrite hook: late → skipped", (r5.completion_text, len(calls)), ("那佳树就放心了呢", n))
    ev6 = AstrMessageEvent(text="我煮了水饺")
    ev6.set_extra("_kaju_quote_t", __import__("time").time() - 5)
    await st.rewrite_snapshot(ev6, ProviderRequest("SYS", contexts=[]))
    r6 = LLMResponse("那佳树就放心了呢")
    await st.rewrite_reply(ev6, r6)
    expect("rewrite hook: on time → rewritten", r6.completion_text, "好的兄长大人，水饺是什么馅的呀")
    # 默认关
    st_off = ks.KajuStyle(Context(), {"bedtime": {"enable": False}})
    ev4 = AstrMessageEvent(text="在吗")
    await st_off.rewrite_snapshot(ev4, ProviderRequest("SYS", contexts=[]))
    expect("rewrite: off by default", ev4.get_extra("_ks_rw_ctx"), None)


asyncio.run(rewrite_hook_tests())


# 先回应，别当解说员（2026-11-02 "女王大人这会儿是真上火了呀，额度被悄悄吃掉最气人啦"）
from kaju_core.voice import respond  # noqa: E402

for line in ["女王大人这会儿是真上火了呀，额度被悄悄吃掉最气人啦", "学姐这是要把一句话全打成错字才甘心呀",
             "这句听着像要下线了呀，学姐是去忙啦", "兄长大人这么一说佳树就明白了，这种时候要拿害羞的那一类",
             "哆啦a梦学姐这几句一句比一句抽象呀", "佳树看明白了，5小时那圈已经到91%，还得再等两分钟才刷新",
             "佳树看到啦，5小时那一圈都快转满了", "图里是说十二月起网页版和Codex要共用同一个额度"]:
    expect(f"respond: commentary {line[:10]}", respond.is_commentary(line), True)
for line in ["女王大人别气啦，偷偷扣额度最讨厌了", "兄长大人中午好～", "佳树查过了哦，手台就是手持电台",
             "好过分呀，四十分钟白排了", "兄长大人要不要先歇一会儿呀", "这不是佳树做的哦", "兄长大人是要煎的还是煮的呀",
             "佳树还以为学姐是困了要去睡呢，原来是额度快要见底了呀", "佳树看到兄长大人发的消息就开心"]:
    expect(f"respond: not commentary {line[:10]}", respond.is_commentary(line), False)
expect("respond: 服了 venting", respond.is_venting("服了"), True)
expect("respond: 烦死了 venting", respond.is_venting("今天组会被批评了，烦死了"), True)
expect("respond: about 佳树 not venting", respond.is_venting("希望佳树心里难受时可以好受一点"), False)
expect("respond: plain msg no note", respond.build_note("晚上吃什么呀", ["兄长大人晚上好～"]), "")
n = respond.build_note("服了", ["女王大人早呀"], "女王大人")
expect("respond: venting note", ("【先回应" in n, "自然地关心" in n, "尊重对方的请求" in n, "「" in n), (True, True, True, False))
n = respond.build_note("嗯嗯", ["学姐这是要把一句话全打成错字才甘心呀"], "哆啦a梦学姐")
expect("respond: quotes her commentary", ("【先回应" in n, "「学姐这是要把一句话全打成错字才甘心呀」" in n, "先哄" in n), (True, True, False))


async def respond_hook_tests():
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})
    req = ProviderRequest("SYS", contexts=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "兄长大人中午好～"}])
    await st.remind_respond(AstrMessageEvent(text="电脑又蓝屏了，服了"), req)
    expect("respond hook: venting note added", "自然地关心" in req.system_prompt, True)
    req = ProviderRequest("SYS", contexts=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "兄长大人中午好～"}])
    await st.remind_respond(AstrMessageEvent(text="晚上吃什么"), req)
    expect("respond hook: quiet otherwise", req.system_prompt, "SYS")


asyncio.run(respond_hook_tests())

# ------------------------------------------------------------------ kaju_basics 分享文字里哪些是对方自己说的话
_kbm = importlib.import_module("kaju_basics.main")
DY = ("0.76 复制打开抖音，看看【大孩纸啊啊啊的作品】户山香澄 弦卷心 popipa happy luc... "
      "https://v.douyin.com/YHa7Ee2y7-M/ :7pm 10/29 y@T.lc FUL:/ \n这个好洗脑")
expect("wait: own words of a douyin share", _kbm.own_words(DY), "这个好洗脑")
expect("wait: own words of a bili share", _kbm.own_words("【能看吗合集】 https://b23.tv/iOcLavf 佳树看看"), "佳树看看")

async def say_from_card_tests():
    """看视频前先说的那句：插件给的要点拼成指导，回复器写（2026-11-08 兄长：不要固定的几句；11-21 起没有卡、没有本地写手）。"""
    from kaju_core.voice import replyer as rp
    KS = importlib.import_module("kaju_style.main").KajuStyle
    st = KS(Context(), {"bedtime": {"enable": False}, "rewrite": {"enable": True}})
    st._mood_words = lambda **kw: ""
    seen, out_text = [], ["好嘞，佳树先去看看兄长大人说的洗脑歌～"]

    async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
        seen.append((list(ctx), dict(plan)))
        return out_text[0], {"model": "测试", "secs": 0.1, "examples": [], "errors": []}
    real, rp.reply = rp.reply, fake_reply
    try:
        ev = AstrMessageEvent(text="这个好洗脑")
        out = await st.say_from_card(ev, ["佳树先去看这个视频", "看完再说"], emotion="期待", attitude="答应",
                                     reply_to="这个好洗脑", said="[分享了一个视频] 这个好洗脑")
        ctx, plan = seen[0] if seen else ([], {})
        expect("say_from_card: replyer output", out, "好嘞，佳树先去看看兄长大人说的洗脑歌～")
        expect("say_from_card: plan + context", (plan.get("要表达的"), "接的是“这个好洗脑”" in plan.get("局面", ""),
                                                 any("：[分享了一个视频] 这个好洗脑" in c for c in ctx)),
               (["佳树先去看这个视频", "看完再说"], True, True))
        out_text[0] = "要表达的：佳树先去看"
        expect("say_from_card: leaked plan → nothing", await st.say_from_card(ev, ["佳树先去看这个视频"]), "")
        off = KS(Context(), {"bedtime": {"enable": False}, "rewrite": {"enable": False}})
        expect("say_from_card: rewrite off → nothing", await off.say_from_card(ev, ["佳树先去看这个视频"]), "")
    finally:
        rp.reply = real


asyncio.run(say_from_card_tests())

# ------------------------------------------------------------------ kaju_style 问之前先听懂
from kaju_core.voice import asks  # noqa: E402

REAL_REPLY = ("佳树也是这么想的，那种沉重不是靠剧情压出来的，是两个人要一起过日子这件事本来就很重\n"
              "什么意外都没发生，可读着就是不轻松\n兄长大人说很接近心里的想法，是哪种想法呀？佳树想听\n&&affection&&")
REAL_ASK = "兄长大人说很接近心里的想法，是哪种想法呀？佳树想听"
expect("asks: question lines", asks.question_lines(REAL_REPLY), [REAL_ASK])
expect("asks: parse keeps only real question lines",
       asks.parse('好的 {"drop":["' + REAL_ASK + '","什么意外都没发生，可读着就是不轻松","编的？"],"why":"x"}', REAL_REPLY),
       [REAL_ASK])
expect("asks: parse junk", (asks.parse("不是json", REAL_REPLY), asks.parse('{"drop":"x"}', REAL_REPLY)), ([], []))
expect("asks: drop line keeps the rest + meme",
       asks.drop_lines(REAL_REPLY, [REAL_ASK]).splitlines()[-2:], ["什么意外都没发生，可读着就是不轻松", "&&affection&&"])
expect("asks: never drop everything", asks.drop_lines("是哪种想法呀？\n&&happy&&", ["是哪种想法呀？"]), None)
ctx = [{"role": "user", "content": [{"type": "text", "text": "[发言人：晴川] 这本怎么样"},
                                    {"type": "text", "text": "<system_reminder>Current datetime: x</system_reminder>"}]},
       {"role": "assistant", "content": "这本不太一样，句子还平得很"}, {"role": "tool", "content": "{}"}]
lines = asks.context_lines(ctx, "我觉得这个跟我心里的想法很接近", quote="这本不太一样")
expect("asks: context lines", lines, ["对方：[发言人：晴川] 这本怎么样", "佳树：这本不太一样，句子还平得很",
                                      "对方（这一条，佳树正在回）：（他引用了：这本不太一样）我觉得这个跟我心里的想法很接近"])


async def asks_hook_tests():
    from astrbot.api.message_components import Plain
    st = importlib.import_module("kaju_style.main").KajuStyle(Context(), {"bedtime": {"enable": False}})
    seen = []

    async def fake_judge(prompt):
        seen.append(prompt)
        return '{"drop":["' + REAL_ASK + '"],"why":"他刚说过"}'
    st._judge = fake_judge
    ev = AstrMessageEvent(text="我觉得这个跟我心里的想法很接近，几乎没有剧情", messages=[
        Reply(sender_nickname="佳树", message_str="这本不太一样"), Plain("我觉得这个跟我心里的想法很接近，几乎没有剧情")])
    await st.asks_snapshot(ev, ProviderRequest("SYS", contexts=ctx))
    resp = LLMResponse(REAL_REPLY)
    await st.asks_check(ev, resp)
    expect("asks hook: line dropped before sending", REAL_ASK in resp.completion_text, False)
    expect("asks hook: judge saw quote + reply", "（他引用了：这本不太一样）" in seen[0] and REAL_ASK in seen[0], True)

    class Msg:
        def __init__(self, role, content): self.role, self.content = role, content

    class Run:
        messages = [Msg("user", "x"), Msg("assistant", REAL_REPLY)]
    await st.asks_history(ev, Run, resp)
    expect("asks hook: history cleaned too", REAL_ASK in Run.messages[-1].content, False)

    # 没问句：不问模型；群聊默认不管；出错照原样发
    ev2 = AstrMessageEvent(text="在吗")
    await st.asks_snapshot(ev2, ProviderRequest("SYS"))
    resp2 = LLMResponse("在呀～")
    n = len(seen)
    await st.asks_check(ev2, resp2)
    expect("asks hook: no question → no model call", (len(seen), resp2.completion_text), (n, "在呀～"))
    ev3 = AstrMessageEvent(text="在吗", group="222222222")
    await st.asks_snapshot(ev3, ProviderRequest("SYS"))
    expect("asks hook: groups off by default", ev3.get_extra("_ks_asks"), None)

    async def broken(prompt):
        raise asyncio.TimeoutError()
    st._judge = broken
    ev4 = AstrMessageEvent(text="x")
    await st.asks_snapshot(ev4, ProviderRequest("SYS"))
    resp4 = LLMResponse("真的吗？")
    await st.asks_check(ev4, resp4)
    expect("asks hook: judge error → send as is", resp4.completion_text, "真的吗？")


asyncio.run(asks_hook_tests())

# ------------------------------------------------------------------ working memory (memory_weight/working.py)
wm = importlib.import_module("kaju_core.memory.working")
from kaju_astr import AstrBody  # noqa: E402
expect("working memo now clock", len(wm.WorkingMemo(AstrBody(Context()), lambda: {}, tempfile.mkdtemp())._now_hhmm()), 5)
expect("working memo keeps corrections", "他的意思" in wm.NOTE_SYSTEM and "【现在】" in wm.NOTE_SYSTEM, True)


class FakeBook:
    """Stands in for the address_book star: the one place the owner QQ is configured."""
    owner = "999"

    def address_of(self, qq, name=None):
        return "兄长大人" if str(qq) == self.owner else "学长"


def book_context():
    ctx = Context()
    ctx.stars = [type("Meta", (), {"star_cls": FakeBook()})()]
    return ctx


mw_main = importlib.import_module("memory_weight.main")
mw_plugin = mw_main.MemoryWeight(book_context(), {"enable": False})
expect("memory_weight owner from address book", (mw_plugin._owners(), mw_plugin.labels().get("999")), ({"999"}, "兄长大人"))
expect("memory_weight owner default", mw_main.MemoryWeight(Context(), {"enable": False})._owners(), {"111111111"})
expect("memory_weight has working memo", type(mw_plugin.memo).__name__, "WorkingMemo")


# ------------------------------------------------------------------ kaju_basics
async def basics_tests():
    b = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {
        "guard": {"allowed_self_ids": ["555555555"]}, "wake": {"nicknames": ["佳树"], "poke": True},
        "image": {"max_wait": 1}, "stable_prefix": {"enable": True, "stable_hours": 4}})
    ev = AstrMessageEvent(self_id="999")
    await b.guard(ev)
    expect("guard blocks other account", ev.is_stopped(), True)
    ev = AstrMessageEvent()
    await b.guard(ev)
    expect("guard lets bot through", ev.is_stopped(), False)
    ev = AstrMessageEvent(self_id="webchat", platform="webchat")
    await b.guard(ev)
    expect("guard ignores WebUI chat", ev.is_stopped(), False)
    ev = AstrMessageEvent(group="1", text="佳树你看这个")
    await b.wake_on_nickname(ev)
    expect("nickname wake", (ev.is_at_or_wake_command, ev.is_wake), (True, True))
    ev = AstrMessageEvent(group="1", text="今天天气好")
    await b.wake_on_nickname(ev)
    expect("no nickname, no wake", ev.is_at_or_wake_command, False)
    ev = AstrMessageEvent(group="1", messages=[Poke(id="555555555")])
    await b.wake_on_poke(ev)
    expect("poke wake", (ev.is_at_or_wake_command, ev.message_str), (True, "（有人戳了戳你）"))
    # 群里被戳（2026-11-09）：戳一戳不带昵称 → 用TA在群里的名字；TA在她上次说话之后说的话一起给她
    from astrbot.api.message_components import Plain as _Plain
    DORA = "444444444"
    _now = __import__("time").time()
    b._pokes.note("qq:GroupMessage:222222222", DORA, "哆啦a梦", "所有东西都小规模验证", _now - 60)
    b._pokes.replied("qq:GroupMessage:222222222", _now - 30)  # 第一句之后她说过话：那句她已经回过了
    for text in ("说的就是你，你去看看autodl还有卡吗", "a100 40g"):
        await b.note_group_line(AstrMessageEvent(sender=DORA, group="222222222", name="哆啦a梦", text=text,
                                                 messages=[_Plain(text)]))
    await b.note_group_line(AstrMessageEvent(sender="555", group="222222222", name="555", text="别人的话",
                                             messages=[_Plain("别人的话")]))
    pk = AstrMessageEvent(sender=DORA, group="222222222", name=DORA, messages=[Poke(id="555555555")])
    pk.message_obj.sender = type("Sender", (), {"nickname": DORA})()
    await b.wake_on_poke(pk)
    expect("poke: name instead of QQ number", pk.message_obj.sender.nickname, "哆啦a梦")
    expect("poke: what TA just said", pk.message_str,
           "（有人戳了戳你。戳你之前，TA刚说了：「说的就是你，你去看看autodl还有卡吗」「a100 40g」）")
    pk2 = AstrMessageEvent(sender="666", group="222222222", name="666", messages=[Poke(id="555555555")])
    await b.wake_on_poke(pk2)
    expect("poke: nothing said → plain", pk2.message_str, "（有人戳了戳你）")
    expect("poke: marked as called", pk2.get_extra("_kaju_called"), "poke")
    # 群里 @ 她才算直接叫她（@ 别人、只提名字都不算）——核对一直不过时只有这样才说在忙
    from astrbot.api.message_components import At as _At
    at_her = AstrMessageEvent(sender=DORA, group="222222222", text="佳树在吗", messages=[_At(qq="555555555"), _Plain("在吗")])
    await b.note_called(at_her)
    at_other = AstrMessageEvent(sender=DORA, group="222222222", text="在吗", messages=[_At(qq="555"), _Plain("在吗")])
    await b.note_called(at_other)
    by_name = AstrMessageEvent(sender=DORA, group="222222222", text="佳树在吗", messages=[_Plain("佳树在吗")])
    await b.note_called(by_name)
    expect("called: @ her / @ other / name only",
           (at_her.get_extra("_kaju_called"), at_other.get_extra("_kaju_called"), by_name.get_extra("_kaju_called")),
           ("at", None, None))
    pk3 = AstrMessageEvent(sender=DORA, messages=[Poke(id="555555555")])  # 私聊被戳：不翻群里的话
    await b.wake_on_poke(pk3)
    expect("poke private: plain", pk3.message_str, "（有人戳了戳你）")
    req = ProviderRequest("SYS", prompt="[Image: 一只猫] 看")
    await b.add_image_note(AstrMessageEvent(), req)
    expect("image note", "【关于图片和视频】" in req.system_prompt, True)
    # stable prefix: plugin text appended after capture moves to the end of this turn
    ev, req = AstrMessageEvent(), ProviderRequest("人设")
    await b.capture_base(ev, req)
    req.system_prompt += "\n\n【今天】上课"
    await b.move_volatile(ev, req)
    expect("prefix keeps base", req.system_prompt, "人设")
    expect("prefix moved part is temp", (len(req.extra_user_content_parts), req.extra_user_content_parts[0]._no_save), (1, True))


asyncio.run(basics_tests())


# ------------------------------------------------------------------ kaju_basics: 私聊连发合并
def burst_pure_tests():
    from astrbot.api.message_components import Image, Plain
    from kaju_basics import burst

    # 2026-11-01 真实的三条：引用纠正一句、一张图、补一句
    q = Reply(sender_id="555555555", sender_nickname="佳树", message_str="查过了，手台就是手持电台")
    parts = [burst.Part(0.0, "不是这个哦", [q, Plain("不是这个哦")]),
             burst.Part(5.0, "", [Image(url="http://x/taso.jpg")]),
             burst.Part(12.3, "是上面图这样的", [Plain("是上面图这样的")])]
    expect("burst text keeps order", burst.merged_text(parts), "不是这个哦\n[图片]\n是上面图这样的")
    expect("burst describe", burst.describe(parts), "文字、图、文字")
    two_quotes = parts + [burst.Part(13.0, "还有这个", [Reply(sender_nickname="佳树", message_str="原来是打歌台呀"),
                                                     Plain("还有这个")])]
    expect("burst second quote written inline", burst.merged_text(two_quotes).splitlines()[-1],
           "（引用佳树：「原来是打歌台呀」）还有这个")
    ev = AstrMessageEvent(text="是上面图这样的", messages=[Plain("是上面图这样的")])
    chain = ev.get_messages()
    burst.apply(ev, parts)
    expect("burst apply: chain merged in place", (chain is ev.get_messages(), len(chain), chain[0] is q), (True, 4, True))
    expect("burst apply: message_str", ev.message_str, "不是这个哦\n[图片]\n是上面图这样的")
    expect("burst: input_status notice", burst.is_input_status({"post_type": "notice", "sub_type": "input_status"}), True)
    expect("burst: poke is not typing", burst.is_input_status({"post_type": "notice", "sub_type": "poke"}), False)

    # 时钟可控：等多久
    now = [100.0]
    b = burst.Bursts(clock=lambda: now[0])
    e1, e2 = AstrMessageEvent(text="a"), AstrMessageEvent(text="b")
    p1 = b.add("u", e1, burst.Part(100.0, "a", [Plain("a")]), "111111111")
    expect("hold: quiet after last", b.hold_until("u", p1, 2.5, 4, 12), 102.5)
    b.typing("u", t=101.0, kind=1)
    expect("hold: typing extends", b.hold_until("u", p1, 2.5, 4, 12), 105.0)
    b.typing("u", t=111.0)
    expect("hold: capped by max_hold", b.hold_until("u", p1, 2.5, 4, 12), 112.0)
    now[0] = 101.5
    p2 = b.add("u", e2, burst.Part(101.5, "b", [Plain("b")]), "111111111")
    expect("add: older holding one yields", (p1.state, [x.text for x in p2.parts], e2.message_str),
           (burst.YIELDED, ["a", "b"], "a\nb"))
    expect("add: queue keeps only the new one", b._q["u"], [p2])
    # 回复：开始发 / 发完；对方在发完之前打的字
    b.reply_started("u", t=101.0)
    expect("unseen: reply still being sent", b.unseen_reply("u", 100.0), True)
    b.reply_sent("u", t=101.2)
    expect("unseen: sent after he started", b.unseen_reply("u", 100.0), True)
    expect("unseen: he wrote after seeing it", b.unseen_reply("u", 101.3), False)


burst_pure_tests()


async def burst_flow_tests():
    from astrbot.api.message_components import Image, Plain
    from kaju_basics import burst
    from kaju_basics.main import BURST_KEY

    b = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {
        "burst": {"quiet_seconds": 0.3, "typing_grace": 0.6, "max_hold": 3, "max_total": 30}})

    def msg(text="", comps=None, group="", platform="aiocqhttp"):
        ev = AstrMessageEvent(text=text, messages=list(comps or ([Plain(text)] if text else [])), group=group,
                              platform=platform)
        ev.is_at_or_wake_command = True  # 私聊 AstrBot 都当作叫她
        return ev

    async def arrive(ev, delay=0.0):
        await asyncio.sleep(delay)
        await b.note_private(ev)
        await b.hold_private(ev)
        return ev

    # 一句话 + 0.1 秒后一张图：前一条不回，图那条带着两条去回
    e1, e2 = msg("不是这个哦"), msg(comps=[Image(url="http://x/a.jpg")])
    await asyncio.gather(arrive(e1), arrive(e2, 0.1))
    expect("flow: first one stops", (e1.is_stopped(), e1.is_at_or_wake_command), (True, False))
    expect("flow: second carries both", (e2.is_stopped(), e2.message_str, len(e2.get_messages())),
           (False, "不是这个哦\n[图片]", 2))
    # 图那条要回之前（前一轮还在回），又来了一句还在等的：图那条交给它
    e3 = msg("是上面图这样的")
    hold3 = asyncio.create_task(arrive(e3))
    await asyncio.sleep(0.05)
    req2 = ProviderRequest("SYS")
    await b.burst_catch_up(e2, req2)
    expect("catch up: waiting one hands over", (e2.is_stopped(), e2.is_at_or_wake_command), (True, False))
    await hold3
    expect("catch up: newest has all three", (e3.is_stopped(), e3.message_str),
           (False, "不是这个哦\n[图片]\n是上面图这样的"))
    b._bursts.reply_started(e3.unified_msg_origin)  # 上一轮的回复是在他打这些字之后才发出去的
    b._bursts.reply_sent(e3.unified_msg_origin)
    req3 = ProviderRequest("SYS")
    await b.burst_catch_up(e3, req3)
    expect("catch up: answers, with notes", (e3.is_stopped(), "连着发的 3 条（按顺序：文字、图、文字）" in req3.system_prompt,
                                             "你上一条回复还没发到" in req3.system_prompt), (False, True, True))
    expect("catch up: only once per event", e3.get_extra(BURST_KEY), None)

    # 一条一条隔得开：各回各的，不加提醒
    e4 = await arrive(msg("在吗"))
    req4 = ProviderRequest("SYS")
    await b.burst_catch_up(e4, req4)
    expect("single message: no notes", (e4.is_stopped(), req4.system_prompt), (False, "SYS"))

    # "对方正在输入"：多等一会儿，等到下一条
    e5, e6 = msg("我跟你说"), msg("今天买了个打歌台")
    typing = msg()
    typing.message_obj.raw_message = {"post_type": "notice", "notice_type": "notify", "sub_type": "input_status",
                                      "event_type": 1}

    async def notice_then_message():
        await asyncio.sleep(0.25)
        await b.note_private(typing)
        await arrive(e6, 0.5)  # 比 quiet 0.3 晚，但在输入提示的 0.6 秒里
    await asyncio.gather(arrive(e5), notice_then_message())
    expect("typing: waits for the next one", (e5.is_stopped(), e6.message_str), (True, "我跟你说\n今天买了个打歌台"))
    expect("typing notice itself is not held", typing.get_extra(BURST_KEY), None)

    # 第一条等太久（max_total）就不再往后交，先回
    e7, e8 = msg("一"), msg("二")
    await arrive(e7)
    e7.get_extra(BURST_KEY).parts[0].t -= 60
    hold8 = asyncio.create_task(arrive(e8))
    await asyncio.sleep(0.05)
    await b.burst_catch_up(e7, ProviderRequest("SYS"))
    expect("max_total: old one answers now", e7.is_stopped(), False)
    await hold8

    # 2026-11-02 真实的竞态："而且节奏很快"正要回时，"也没多少剧情"43 毫秒前到了，
    # 可别的插件还在记它，还没排进来 → 以前看不见它，两条各回一遍。现在等它排进来再交过去
    e9, e10 = msg("而且节奏很快"), msg("也没多少剧情")
    await arrive(e9)
    await b.note_private(e10)  # 刚到

    async def slow_plugins_then_hold():
        await asyncio.sleep(0.3)  # 别的插件（记日志、记忆）慢慢记
        await b.hold_private(e10)
    hold10 = asyncio.create_task(slow_plugins_then_hold())
    await b.burst_catch_up(e9, ProviderRequest("SYS"))
    expect("race: arrived-but-not-queued one is waited for", (e9.is_stopped(), e9.is_at_or_wake_command),
           (True, False))
    await hold10
    expect("race: newer one answers both", (e10.is_stopped(), e10.message_str), (False, "而且节奏很快\n也没多少剧情"))
    await b.burst_catch_up(e10, ProviderRequest("SYS"))

    # 刚到的那条被别的插件拦下了（或是指令）：不白等
    e11, e12 = msg("在吗"), msg("/佳树心情")
    await arrive(e11)
    await b.note_private(e12)
    e13 = msg("还有一句")
    await b.note_private(e13)
    e13.stop_event()
    t0 = asyncio.get_running_loop().time()
    await b.burst_catch_up(e11, ProviderRequest("SYS"))
    expect("race: commands / stopped ones are not waited for",
           (e11.is_stopped(), asyncio.get_running_loop().time() - t0 < 0.5), (False, True))
    expect("race: arrivals cleaned when queued", any(ev is e10 for _, _, ev in b._bursts._arrived.get(e10.unified_msg_origin, [])), False)

    # 等不来（一直没排进来）：最多等 catch_up_wait，然后照常回
    b.config["burst"]["catch_up_wait"] = 0.4
    e14, e15 = msg("一"), msg("二")
    await arrive(e14)
    await b.note_private(e15)
    t0 = asyncio.get_running_loop().time()
    await b.burst_catch_up(e14, ProviderRequest("SYS"))
    expect("race: wait is capped", (e14.is_stopped(), 0.35 < asyncio.get_running_loop().time() - t0 < 1.0), (False, True))
    b._bursts.forget(e15.unified_msg_origin, e15)

    # 群聊、指令、网页聊天（默认不管）
    for label, ev in (("group", msg("在吗", group="222222222")), ("command", msg("/佳树心情")),
                      ("webchat", msg("在吗", platform="webchat"))):
        await arrive(ev)
        expect(f"burst skips {label}", ev.get_extra(BURST_KEY), None)

    # 出错不能让 AstrBot 把报错发给对方
    bad = msg("x")
    bad.get_messages = None
    await b.hold_private(bad)
    expect("burst error is swallowed", bad.is_stopped(), False)
    _ = burst  # noqa


asyncio.run(burst_flow_tests())


async def burst_late_tests():
    """2026-11-13：第一句已经在等模型（99 秒），第二句这时到了 → 草稿回来 / 写好要发时看见，这句不发，并到第二句那轮一起回。"""
    from astrbot.api.message_components import Plain
    from astrbot.api.provider import LLMResponse
    from kaju_basics.main import LATE_KEY

    b = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {
        "burst": {"quiet_seconds": 0.1, "typing_grace": 0.2, "max_hold": 1, "max_total": 30, "catch_up_wait": 0.3}})

    def msg(text):
        ev = AstrMessageEvent(text=text, messages=[Plain(text)])
        ev.is_at_or_wake_command = True
        return ev

    async def arrive(ev):
        await b.note_private(ev)
        await b.hold_private(ev)
        return ev

    # 草稿刚回来时第二句已经排着
    a = await arrive(msg("我这边是计算机相关的"))
    await b.burst_catch_up(a, ProviderRequest("SYS"))  # 开始请求模型
    expect("late: request kept the turn", isinstance(a.get_extra(LATE_KEY), object) and not a.is_stopped(), True)
    bb = await arrive(msg("佳树听过Dafny吗？"))  # 模型还没回，第二句到了
    resp = LLMResponse("计算机相关的话兄长大人一定很辛苦呢")
    await b.burst_late_on_draft(a, resp)
    expect("late: first is not sent", (a.is_stopped(), resp.completion_text), (True, ""))
    expect("late: second carries both", (bb.is_stopped(), bb.message_str),
           (False, "我这边是计算机相关的\n佳树听过Dafny吗？"))
    req = ProviderRequest("SYS")
    await b.burst_catch_up(bb, req)
    expect("late: merged turn told it's two in a row", "连着发的 2 条" in req.system_prompt, True)
    resp_b = LLMResponse("佳树听过！")
    await b.burst_late_on_draft(bb, resp_b)
    expect("late: nothing newer -> merged one is sent", (bb.is_stopped(), resp_b.completion_text), (False, "佳树听过！"))

    # 写好要发时才看见（写手、核对那段时间到的）
    c = await arrive(msg("今天好累"))
    await b.burst_catch_up(c, ProviderRequest("SYS"))
    resp_c = LLMResponse("兄长大人辛苦了")
    await b.burst_late_on_draft(c, resp_c)
    expect("late: nothing yet at draft time", c.is_stopped(), False)
    d = await arrive(msg("不过题都做完了"))
    await b.burst_late_before_send(c, resp_c)
    expect("late: caught right before sending", (c.is_stopped(), d.message_str), (True, "今天好累\n不过题都做完了"))
    await b.burst_catch_up(d, ProviderRequest("SYS"))

    # 一串从第一条起太久（late_max_total）就照发，不能一直不回
    e = await arrive(msg("一"))
    await b.burst_catch_up(e, ProviderRequest("SYS"))
    e.get_extra(LATE_KEY).parts[0].t -= 200
    f = await arrive(msg("二"))
    resp_e = LLMResponse("嗯嗯")
    await b.burst_late_on_draft(e, resp_e)
    expect("late: too long since first -> send", (e.is_stopped(), resp_e.completion_text, f.message_str),
           (False, "嗯嗯", "二"))
    await b.burst_catch_up(f, ProviderRequest("SYS"))

    # 关掉
    b.config["burst"]["late_merge"] = False
    g = await arrive(msg("三"))
    await b.burst_catch_up(g, ProviderRequest("SYS"))
    h = await arrive(msg("四"))
    await b.burst_late_on_draft(g, LLMResponse("好"))
    expect("late: off", (g.is_stopped(), h.message_str), (False, "四"))


asyncio.run(burst_late_tests())


# ------------------------------------------------------------------ kaju_basics: 离得远了就引用
async def quote_tests():
    from astrbot.api.message_components import At, Image, Plain
    from kaju_basics import quote

    now = [1000.0]
    s = quote.Seen(clock=lambda: now[0])
    s.message("u", 1000.0)
    expect("seen: nothing after", s.gap("u", 1000.0), 0)
    s.message("u", 1001.0)
    s.reply("u", start=1002.0, end=1005.0, bubbles=3)
    expect("seen: msg + 3 bubbles after", s.gap("u", 1000.0), 4)
    expect("seen: reply already going when it came → 1", s.gap("u", 1003.0), 1)
    expect("bubbles: segmented counts body only", quote.bubbles_of([Reply(), At(), Plain("a"), Plain("b")], True), 2)
    expect("bubbles: not segmented = 1", quote.bubbles_of([Plain("a"), Image(url="x")], False), 1)
    expect("should_quote", (quote.should_quote(1, False), quote.should_quote(1, True), quote.should_quote(2, True),
                            quote.should_quote(0, False)), (True, False, True, False))

    # 2026-11-02 真实的一段：A（长消息）→ 她在回 A 时他发 B"而且节奏很快" → A 的回复（3 句+表情）→ 他发 C → B 的回复 → C 的回复
    b = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {})
    b.context._config["platform_settings"] = {"segmented_reply": {"enable": True}}
    b._seen = quote.Seen(clock=lambda: now[0])

    class Result:
        def __init__(self, *comps, llm=True): self.chain, self._llm = list(comps), llm
        def is_llm_result(self): return self._llm

    def msg(text, mid, group=""):
        ev = AstrMessageEvent(text=text, messages=[Plain(text)], group=group)
        ev.message_obj.message_id = mid
        ev.is_at_or_wake_command = True
        return ev

    async def reply(ev, *lines, t_send=None):
        ev.set_result(Result(*[Plain(x) for x in lines]))
        await b.quote_far(ev)
        if t_send is not None:
            now[0] = t_send
        await b.quote_sent(ev)
        return ev.get_result().chain

    now[0] = 2000.0
    a = msg("我觉得这个跟我心里的想法很接近", 101)
    await b.quote_note(a)
    now[0] = 2018.0
    bb = msg("而且节奏很快", 102)
    await b.quote_note(bb)
    now[0] = 2021.0
    chain_a = await reply(a, "佳树也是这么想的", "什么意外都没发生", "是哪种想法呀？", t_send=2026.0)
    expect("quote: A is answered while B came in → quoted", type(chain_a[0]).__name__ == "Reply" and chain_a[0].id == 101,
           True)
    now[0] = 2029.0
    c = msg("也没多少剧情", 103)
    await b.quote_note(c)
    now[0] = 2044.0
    chain_b = await reply(bb, "兄长大人说得对", "时间是跳着走的", "快得让人有点舍不得", t_send=2050.0)
    expect("quote: B (behind A's reply + C) → quoted", (type(chain_b[0]).__name__, chain_b[0].id), ("Reply", 102))
    now[0] = 2065.0
    chain_c = await reply(c, "对呀", "会不会觉得闷呀？", t_send=2068.0)
    expect("quote: C (behind B's reply) → quoted", (type(chain_c[0]).__name__, chain_c[0].id), ("Reply", 103))
    # 平常：一问一答，紧挨着
    now[0] = 2100.0
    d = msg("在吗", 104)
    await b.quote_note(d)
    now[0] = 2105.0
    chain_d = await reply(d, "在呀～", t_send=2106.0)
    expect("quote: right after → no quote", type(chain_d[0]).__name__, "Plain")
    expect("quote: only first result of a turn", (await reply(d, "还有一句"))[0].__class__.__name__, "Plain")

    # 群：隔 1 条不引用，隔 2 条引用；她自己插话不引用；输入提示 / 她自己发的不算数
    g = msg("佳树你看这个", 201, group="222222222")
    await b.quote_note(g)
    other = AstrMessageEvent(text="哈哈", group="222222222")
    await b.quote_note(other)
    mine = AstrMessageEvent(text="我自己", group="222222222", sender="555555555")
    await b.quote_note(mine)
    typing = AstrMessageEvent()
    typing.message_obj.raw_message = {"post_type": "notice", "sub_type": "input_status"}
    await b.quote_note(typing)
    chain_g = await reply(g, "看到啦")
    expect("quote group: 1 between → no", type(chain_g[0]).__name__, "Plain")
    g2 = msg("佳树佳树", 202, group="222222222")
    await b.quote_note(g2)
    await b.quote_note(AstrMessageEvent(text="一", group="222222222"))
    await b.quote_note(AstrMessageEvent(text="二", group="222222222"))
    expect("quote group: 2 between → yes", type((await reply(g2, "在呢"))[0]).__name__, "Reply")
    g3 = msg("今天好热", 203, group="222222222")
    g3.is_at_or_wake_command = False
    g3.set_extra("_chime_in", True)
    await b.quote_note(g3)
    for x in "一二三":
        await b.quote_note(AstrMessageEvent(text=x, group="222222222"))
    expect("quote group: her own chime-in → no", type((await reply(g3, "是呀"))[0]).__name__, "Plain")
    g4 = msg("那你呢", 204, group="222222222")
    g4.is_at_or_wake_command = False
    g4.set_extra("_chime_in", "follow")
    await b.quote_note(g4)
    for x in "一二":
        await b.quote_note(AstrMessageEvent(text=x, group="222222222"))
    expect("quote group: follow-up to her → yes", type((await reply(g4, "佳树也想"))[0]).__name__, "Reply")
    # 网页聊天、非模型结果、关掉
    w = msg("在吗", 301)
    w._platform = "webchat"
    await b.quote_note(w)
    expect("quote: webchat untouched", w.get_extra("_kaju_quote_t"), None)
    b.config["quote"] = {"enable": False}
    e = msg("x", 401)
    await b.quote_note(e)
    expect("quote: disabled", e.get_extra("_kaju_quote_t"), None)


asyncio.run(quote_tests())


# ------------------------------------------------------------------ kaju_basics: 看视频/动图/文件/语音
def make_clip(path, seconds=2, fps=10, tone=True):
    """用 PyAV 现做一段小视频：底色逐渐变红，tone=True 时带 440Hz 声音。"""
    import av
    import numpy as np
    from PIL import Image as PILImage

    c = av.open(path, "w")
    vs = c.add_stream("mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 160, 120, "yuv420p"
    aus = c.add_stream("aac", rate=16000, layout="mono")
    for i in range(seconds * fps):
        img = PILImage.new("RGB", (160, 120), (int(255 * i / (seconds * fps)), 40, 40))
        for p in vs.encode(av.VideoFrame.from_image(img)):
            c.mux(p)
    for p in vs.encode():
        c.mux(p)
    t = np.arange(seconds * 16000) / 16000
    pcm = ((np.sin(2 * np.pi * 440 * t) * 8000) if tone else np.zeros_like(t)).astype(np.int16)
    for k in range(0, len(pcm), 1024):
        fr = av.AudioFrame.from_ndarray(pcm[k:k + 1024].reshape(1, -1), format="s16", layout="mono")
        fr.sample_rate = 16000
        for p in aus.encode(fr):
            c.mux(p)
    for p in aus.encode():
        c.mux(p)
    c.close()


class FakeVision:
    def __init__(self): self.calls = []

    async def text_chat(self, prompt="", session_id="", image_urls=None, persist=False):
        self.calls.append((prompt, list(image_urls or [])))
        return LLMResponse("红色越来越深的画面")


class FakeSTT:
    def __init__(self): self.calls = 0

    async def get_text(self, audio_url=""):
        self.calls += 1
        return "佳树你好"


class FakeGcc:
    """内置群聊上下文的替身：记下每次记录时消息链里的文字。"""
    def __init__(self): self.lines, self.captions = [], []

    async def handle_message(self, event):
        from astrbot.api.message_components import Plain as P
        self.lines.append("".join(c.text for c in event.get_messages() if isinstance(c, P)))

    async def get_image_caption(self, image_url, provider_id, prompt):
        self.captions.append((image_url, prompt))
        return "图"


async def media_tests():
    from astrbot.api.message_components import File, Image, Plain, Record, Reply, Video
    from astrbot.core.agent.message import TextPart
    from kaju_core.senses import media
    from kaju_basics.main import VOICE_MARK, VOICE_NOTE

    expect("file_kind png", media.file_kind("微信图片_20261028175544.png"), "image")
    expect("file_kind mp4", media.file_kind("a.MP4"), "video")
    expect("file_kind zip", media.file_kind("a.zip"), None)
    expect("fmt_duration", (media.fmt_duration(6.2), media.fmt_duration(65), media.fmt_duration(None)), ("6秒", "1分05秒", "一段"))
    expect("fmt_ts", (media.fmt_ts(1.66, True), media.fmt_ts(75)), ("1.7s", "1:15"))

    tmp = tempfile.mkdtemp()
    clip, quiet = os.path.join(tmp, "clip.mp4"), os.path.join(tmp, "quiet.mp4")
    make_clip(clip)
    make_clip(quiet, tone=False)
    frames, dur, has_audio = media.grab_frames(clip, 9)
    expect("grab 9 frames in order", (len(frames), [t for t, _ in frames] == sorted(t for t, _ in frames)), (9, True))
    expect("grab duration/audio", (round(dur), has_audio), (2, True))
    expect("later frame is redder", frames[-1][1].getpixel((80, 60))[0] > frames[0][1].getpixel((80, 60))[0] + 100, True)
    expect("montage is jpeg", media.montage(frames)[:2], b"\xff\xd8")
    chunks, secs = media.extract_wav_chunks(clip, tmp)
    expect("audio extracted", (len(chunks), round(secs)), (1, 2))
    expect("silent audio skipped", media.extract_wav_chunks(quiet, tmp)[0], [])

    gcc, vision, stt = FakeGcc(), FakeVision(), FakeSTT()
    ctx = Context({"timezone": "Asia/Shanghai", "provider_ltm_settings": {"image_caption_provider_id": "ds", "group_icl_enable": True}})
    ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})()]
    ctx.providers, ctx.stt = {"ds": vision}, stt
    b = importlib.import_module("kaju_basics.main").KajuBasics(ctx, {"media": {"video_grid": 2, "group_video_preview": True}})

    # 群里发视频：记录里有描述+声音转写，记完消息链恢复原样；同一个视频第二次直接用缓存
    vid = Video(file="abc.mp4", path=clip)
    ev = AstrMessageEvent(group="1", messages=[Plain("看"), vid])
    await gcc.handle_message(ev)
    line = gcc.lines[-1]
    expect("group video described", ("[Video: 2秒的视频。红色越来越深的画面" in line, "「佳树你好」" in line), (True, True))
    expect("video prompt has duration", "2秒的视频按时间顺序截的4个画面" in vision.calls[0][0], True)
    expect("chain restored", len(ev.get_messages()), 2)
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[Video Attachment: name abc.mp4, path x]"))
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("direct video replaced", (len(texts), texts[0].startswith("[Video: 2秒的视频")), (1, True))
    expect("video cached", (len(vision.calls), stt.calls), (1, 1))
    await b.add_image_note(ev, req)
    expect("video triggers image note", "【关于图片和视频】" in req.system_prompt, True)

    # 引用的视频
    ev = AstrMessageEvent(messages=[Reply(chain=[Video(file="q.mp4", path=quiet)]), Plain("这是什么")])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[Video Attachment in quoted message: name q.mp4, path y]"))
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("quoted video replaced", (len(texts), texts[0].startswith("[Video in quoted message: 2秒的视频"), "「" in texts[0]),
           (1, True, False))

    # 下载不了的视频：给一句原因，不抛错
    ev = AstrMessageEvent(group="1", messages=[Video(file="gone.mp4")])
    await gcc.handle_message(ev)
    expect("broken video", "[Video: 视频下载不下来" in gcc.lines[-1], True)

    # 只有视频/语音的群消息：内置不记，这里补记
    n = len(gcc.lines)
    await b.record_media_only(AstrMessageEvent(group="1", messages=[Record(file="v.amr")]))
    expect("media-only recorded", (len(gcc.lines), "[Voice: 一条语音，没转成文字]" in gcc.lines[-1]), (n + 1, True))
    await b.record_media_only(AstrMessageEvent(group="1", messages=[Plain("hi"), Video(file="abc.mp4", path=clip)]))
    expect("text message left to builtin", len(gcc.lines), n + 1)

    # 语音转写成功：群聊记录和这一轮请求都标上"这是语音"
    raw = [{"type": "record", "data": {"file": "v.amr"}}]
    ev = AstrMessageEvent(group="1", text="家树今天去公园吗", messages=[Plain("家树今天去公园吗")], raw=raw)
    await gcc.handle_message(ev)
    expect("voice mark in history", gcc.lines[-1].endswith(VOICE_MARK), True)
    req = ProviderRequest("SYS", prompt=ev.message_str)
    await b.describe_media(ev, req)
    expect("voice note in request", [p.text for p in req.extra_user_content_parts], [VOICE_NOTE])
    # 没转成文字：别把音频塞给模型
    req = ProviderRequest("SYS")
    req.audio_urls = ["x.wav"]
    req.extra_user_content_parts.append(TextPart("[Audio Attachment: path x.wav]"))
    await b.describe_media(AstrMessageEvent(messages=[Record(file="v.amr")], raw=raw), req)
    expect("failed voice", (req.audio_urls, req.extra_user_content_parts[0].text.startswith("[Voice:")), ([], True))

    # 文件形式的图片/视频换成图片/视频（包括引用里的）；压缩包不动；商城表情补成图片
    png = os.path.join(tmp, "微信图片_1.png")
    open(png, "wb").write(b"\x89PNG fake")
    quoted = Reply(chain=[File(name="微信图片_1.png", file=png)])
    chain = [File(name="微信图片_1.png", file=png), File(name="clip.mp4", file=clip), File(name="a.zip", file=png), quoted]
    raw = [{"type": "mface", "data": {"url": "https://gxh.vip.qq.com/x.gif", "summary": "[开心]"}}]
    ev = AstrMessageEvent(group="1", messages=chain, raw=raw)
    await b.normalize_media(ev)
    kinds = [type(c).__name__ for c in ev.get_messages()]
    expect("files normalized", kinds, ["Image", "Video", "File", "Reply", "Image"])
    expect("quoted file normalized", type(quoted.chain[0]).__name__, "Image")
    expect("mface url", ev.get_messages()[-1].url, "https://gxh.vip.qq.com/x.gif")
    big = [{"type": "file", "data": {"name": "huge.png", "file_size": str(50 * 1024 * 1024)}}]
    ev = AstrMessageEvent(messages=[File(name="huge.png", file=png)], raw=big)
    await b.normalize_media(ev)
    expect("huge image file left alone", type(ev.get_messages()[0]).__name__, "File")

    # 群聊记录里的动图：拆帧后再描述，提示词里说明是动图；普通图原样
    from PIL import Image as PILImage
    gif, jpg = os.path.join(tmp, "a.gif"), os.path.join(tmp, "b.jpg")
    shots = [PILImage.new("RGB", (120, 90), (40 * i, 0, 255 - 40 * i)) for i in range(6)]
    shots[0].save(gif, save_all=True, append_images=shots[1:], duration=120, loop=0)
    shots[0].save(jpg)
    expect("gif caption", await gcc.get_image_caption(gif, "ds", "描述"), "图")
    expect("gif prompt", ("动图" in gcc.captions[-1][1], gcc.captions[-1][0] != gif and gcc.captions[-1][0].endswith(".jpg")),
           (True, True))
    expect("gif sheet cleaned up", os.path.exists(gcc.captions[-1][0]), False)
    await gcc.get_image_caption(jpg, "ds", "描述")
    b.config.setdefault("media", {})["gif_provider_id"] = "ds"   # 动图另外交给指定的模型（这里是 FakeVision）
    n_gcc, n_vis = len(gcc.captions), len(vision.calls)
    await gcc.get_image_caption(gif, "ds", "描述")
    expect("gif goes to gif_provider", (len(gcc.captions) - n_gcc, len(vision.calls) - n_vis, "动图" in vision.calls[-1][0]), (0, 1, True))
    await gcc.get_image_caption(jpg, "ds", "描述")
    expect("still image stays", len(gcc.captions) - n_gcc, 1)
    b.config["media"]["gif_provider_id"] = ""
    expect("still image prompt untouched", gcc.captions[-1], (jpg, "描述"))
    # 直接发给她的图：填了 gemini.json 就先交给 Gemini 看，描述写进这一轮、图不再给写回复的模型；没看成就原样留着
    import json as _json
    from kaju_core import paths as _paths
    from kaju_core.senses import omni as _omni
    turn_ev = AstrMessageEvent(text="这是什么呀", messages=[Image(file=jpg), Plain("这是什么呀")])
    req = ProviderRequest("SYS", prompt="这是什么呀", image_urls=[jpg])
    await b._turn_images(turn_ev, req)
    expect("turn image: no gemini key → untouched", (req.image_urls, req.extra_user_content_parts), ([jpg], []))
    gem_file = _paths.account("gemini.json")
    _json.dump({"api_key": "sk-g", "base_url": "http://relay"}, open(gem_file, "w"))
    _omni._gemini_cache = (0.0, {})
    real_look, asked = _omni.look, []

    async def gem_look(path, prompt, timeout=40, task="image"):
        asked.append((path, "这是什么呀" in prompt))
        return "一张蓝色的图"

    async def gem_blind(path, prompt, timeout=40, task="image"):
        raise RuntimeError("503")

    _omni.look = gem_look
    await b._turn_images(turn_ev, req)
    expect("turn image: gemini looks, model no longer gets the picture",
           (req.image_urls, [p.text for p in req.extra_user_content_parts], asked),
           ([], ["[Image in this message: 一张蓝色的图]"], [(jpg, True)]))
    _omni.look = gem_blind
    req = ProviderRequest("SYS", prompt="这是什么呀", image_urls=[jpg])
    await b._turn_images(turn_ev, req)
    expect("turn image: gemini fails → left for the reply model", (req.image_urls, req.extra_user_content_parts), ([jpg], []))
    _omni.look = real_look
    os.remove(gem_file)
    _omni._gemini_cache = (0.0, {})
    # 统一入口：同一套感官登记在 kaju_core 里，给本地文件就按类型分
    import kaju_core.senses as core_senses
    expect("senses registered", core_senses.get() is b._describer.senses, True)
    seen = await core_senses.get().perceive(gif, "chat1")
    expect("perceive gif", (seen.kind, seen.ok, "动图" in vision.calls[-1][0]), ("image", True, True))
    seen = await core_senses.get().perceive(clip, "chat1")
    expect("perceive video", (seen.kind, seen.ok, "2秒的视频" in str(seen)), ("video", True, True))
    seen = await core_senses.get().perceive(os.path.join(tmp, "none.mp4"), "chat1")
    expect("perceive missing video", (seen.kind, seen.ok), ("video", False))

    # 关掉总开关：什么都不加
    b._sec = lambda name: {"enable": False} if name == "media" else {}
    ev = AstrMessageEvent(group="1", messages=[Video(file="abc.mp4", path=clip)])
    expect("media off", await b._history_extras(ev), [])
    await b.terminate()
    expect("terminate unregisters senses", core_senses.get(), None)
    expect("terminate restores gcc", (gcc.handle_message.__qualname__, gcc.get_image_caption.__qualname__),
           ("FakeGcc.handle_message", "FakeGcc.get_image_caption"))


asyncio.run(media_tests())


# ------------------------------------------------------------------ kaju_basics: 群聊记录按到达顺序、小表情、视频不提前看
class OrderGcc:
    """照内置 group_chat_context 的做法：描述完才记；回复时只注入排在这条前面的记录。"""
    def __init__(self, delay=0.3, fail=False):
        from collections import defaultdict, deque
        self.raw_records, self._record_ids = defaultdict(deque), defaultdict(deque)
        self._locks, self.delay, self.fail = {}, delay, fail

    def _get_lock(self, umo):
        return self._locks.setdefault(umo, asyncio.Lock())

    async def get_image_caption(self, image_url, provider_id, prompt):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("caption provider down")
        return "额度面板 5-HOUR 91%"

    async def handle_message(self, event):
        import uuid
        from astrbot.api.message_components import Image as I, Plain as P
        parts = [f"[{event.get_sender_name()}]:"]
        for c in event.get_messages():
            if isinstance(c, P):
                parts.append(" " + c.text)
            elif isinstance(c, I):
                try:
                    parts.append(f" [Image: {await self.get_image_caption(c.url, 'ds', 'p')}]")
                except Exception:  # noqa: BLE001  内置的就是吞掉
                    pass
        umo = event.unified_msg_origin
        async with self._get_lock(umo):
            rid = uuid.uuid4().hex
            self.raw_records[umo].append("".join(parts))
            self._record_ids[umo].append(rid)
            event.set_extra("_group_context_record_id", rid)

    async def on_req_llm(self, event):
        umo, rid = event.unified_msg_origin, event.get_extra("_group_context_record_id")
        async with self._get_lock(umo):
            ids, recs = list(self._record_ids[umo]), list(self.raw_records[umo])
            i = ids.index(rid)
            self._record_ids[umo].clear(); self._record_ids[umo].extend(ids[i + 1:])
            self.raw_records[umo].clear(); self.raw_records[umo].extend(recs[i + 1:])
        return recs[:i]


async def order_tests():
    from astrbot.api.message_components import Face, Image, Plain, Video
    from astrbot.core.agent.message import TextPart
    from kaju_basics import history

    # 纯逻辑：往前挪到比它晚到的记录前面
    ids, recs = ["a", "b", "c"], ["A", "B", "C"]
    expect("move img before text", (history.move_into_place(ids, recs, {"a": 1, "b": 3, "c": 2}, "c"), ids, recs),
           (1, ["a", "c", "b"], ["A", "C", "B"]))
    ids = ["a", "b"]
    expect("in order: no move", history.move_into_place(ids, ["A", "B"], {"a": 1, "b": 2}, "b"), 0)
    expect("unknown neighbour not crossed", history.move_into_place(["x", "b"], ["X", "B"], {"b": 1}, "b"), 0)
    expect("face names", (history.face_text(264), history.face_text("14"), history.face_text(99999), history.face_text(None)),
           ("[表情：捂脸]", "[表情：微笑]", "[QQ表情]", "[QQ表情]"))

    async def scene(keep_order, fail=False):
        gcc = OrderGcc(fail=fail)
        ctx = Context({"provider_ltm_settings": {"image_caption_provider_id": "ds", "group_icl_enable": True}})
        ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})()]
        b = importlib.import_module("kaju_basics.main").KajuBasics(ctx, {"image": {"keep_order": keep_order}})
        old = AstrMessageEvent(group="9", name="女王大人", messages=[Plain("glm flash真慢")])
        await gcc.handle_message(old)
        img = AstrMessageEvent(group="9", name="哆啦a梦", messages=[Image(url="http://x/91.jpg")])
        txt = AstrMessageEvent(group="9", name="哆啦a梦", messages=[Plain("我要消失了")])
        txt.created_at = img.created_at + 0.7
        t = asyncio.create_task(gcc.handle_message(img))  # 图先到，但要描述 0.3 秒
        await asyncio.sleep(0.01)
        await gcc.handle_message(txt)  # 话后到，瞬间记上
        req = ProviderRequest("SYS")
        await b.wait_for_captions(txt, req)  # 回复前等图描述完
        await t
        seen = await gcc.on_req_llm(txt)
        await b.terminate()
        return seen

    seen = await scene(True)
    expect("image before text is seen", (len(seen), "91%" in seen[-1], seen[0]), (2, True, "[女王大人]: glm flash真慢"))
    seen = await scene(False)
    expect("old behaviour: image missed (control)", any("91%" in s for s in seen), False)
    seen = await scene(True, fail=True)
    expect("failed caption still recorded", any("没看清" in s for s in seen), True)

    # 她插话回的这条自己带着图（"[图片] 已经什么也看不懂了"）：这条的记录被拿掉，图的描述要单独补进来
    async def own_scene(direct_image=False, group="9"):
        gcc = OrderGcc(delay=0.2)
        ctx = Context({"provider_ltm_settings": {"image_caption_provider_id": "ds", "group_icl_enable": True}})
        ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})()]
        b = importlib.import_module("kaju_basics.main").KajuBasics(ctx, {})
        ev = AstrMessageEvent(group=group, name="女王大人", text="已经什么也看不懂了",
                              messages=[Image(url="http://x/vivado.png"), Plain("已经什么也看不懂了")])
        t = asyncio.create_task(gcc.handle_message(ev))
        await asyncio.sleep(0.01)
        req = ProviderRequest("SYS", prompt=ev.message_str)
        if direct_image:
            req.image_urls = ["/tmp/vivado.png"]
        await b.wait_for_captions(ev, req)  # 等描述完，再补
        await t
        seen = await gcc.on_req_llm(ev)
        await b.add_image_note(ev, req)
        await b.terminate()
        return [p.text for p in req.extra_user_content_parts], seen, req.system_prompt

    parts, seen, sp = await own_scene()
    expect("own image caption added", parts, ["[Image in this message: 额度面板 5-HOUR 91%]"])
    expect("own record not in history", seen, [])
    expect("image + words note", ("【关于图片和视频】" in sp, "对方发了图还说了话" in sp), (True, True))
    parts, _, _ = await own_scene(direct_image=True)
    expect("image already sent directly: no duplicate", parts, [])

    # 小黄脸表情：换成文字，也补进 message_str
    ctx = Context({"provider_ltm_settings": {"image_caption_provider_id": "ds", "group_icl_enable": True}})
    ctx.stars = []
    b = importlib.import_module("kaju_basics.main").KajuBasics(ctx, {})
    ev = AstrMessageEvent(group="9", text="哈哈", messages=[Plain("哈哈"), Face(id=264)])
    await b.normalize_media(ev)
    expect("face to text", ([getattr(c, "text", None) for c in ev.get_messages()], ev.message_str),
           (["哈哈", "[表情：捂脸]"], "哈哈[表情：捂脸]"))
    b._sec = lambda name: {"face": False} if name == "media" else {}
    ev = AstrMessageEvent(group="9", messages=[Face(id=264)])
    await b.normalize_media(ev)
    expect("face off", type(ev.get_messages()[0]).__name__, "Face")
    await b.terminate()

    # 群里的视频默认不提前看；有人提到视频时补看最近那段
    tmp = tempfile.mkdtemp()
    clip = os.path.join(tmp, "clip.mp4")
    make_clip(clip)
    gcc, vision, stt = FakeGcc(), FakeVision(), FakeSTT()
    ctx = Context({"timezone": "Asia/Shanghai", "provider_ltm_settings": {"image_caption_provider_id": "ds", "group_icl_enable": True}})
    ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})()]
    ctx.providers, ctx.stt = {"ds": vision}, stt
    b = importlib.import_module("kaju_basics.main").KajuBasics(ctx, {"media": {"video_grid": 2}})
    vid = AstrMessageEvent(group="9", name="哆啦a梦", messages=[Video(file="abc.mp4", path=clip)])
    await gcc.handle_message(vid)
    expect("group video not watched", (history.UNSEEN_VIDEO_TEXT.strip() in gcc.lines[-1], len(vision.calls)), (True, 0))
    req = ProviderRequest("SYS")
    await b.describe_media(AstrMessageEvent(group="9", text="今天好冷"), req)
    expect("no mention: still unwatched", (req.extra_user_content_parts, len(vision.calls)), ([], 0))
    req = ProviderRequest("SYS")
    await b.describe_media(AstrMessageEvent(group="9", text="佳树你看学姐发的视频"), req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("mentioned: watched now", (len(texts), texts[0].startswith("[Video sent earlier by 哆啦a梦: 2秒的视频")), (1, True))
    req = ProviderRequest("SYS")
    await b.describe_media(AstrMessageEvent(group="9", text="那个视频还有吗"), req)
    expect("watched once only", req.extra_user_content_parts, [])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("x " + history.UNSEEN_VIDEO_TEXT))
    await b.add_image_note(AstrMessageEvent(group="9", text="hi"), req)
    expect("note says unwatched video", "还没点开看" in req.system_prompt, True)
    await b.terminate()


asyncio.run(order_tests())


# ------------------------------------------------------------------ kaju_basics: 请求时限
# 假的 DeepSeek：先发几行空行保活，hang=True 时永远不给结果（读超时管不住），否则 0.3s 后给正常回复
async def deadline_tests():
    import time

    import openai
    from aiohttp import web
    from openai.resources.chat.completions import AsyncCompletions

    from kaju_basics import deadline

    ok_body = (b'{"id":"x","object":"chat.completion","created":0,"model":"m","choices":[{"index":0,'
               b'"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}')

    async def handler(request):
        hang = (await request.json()).get("model") == "hang"
        resp = web.StreamResponse(headers={"Content-Type": "application/json"})
        await resp.prepare(request)
        try:
            for _ in range(10_000 if hang else 3):
                await resp.write(b"\n")
                await asyncio.sleep(0.1)
            await resp.write(ok_body)
            await resp.write_eof()
        except ConnectionError:  # 客户端放弃了
            pass
        return resp

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = openai.AsyncOpenAI(api_key="k", base_url=f"http://127.0.0.1:{port}/v1", timeout=0.5, max_retries=0)
    msgs = [{"role": "user", "content": "hi"}]
    deadline.uninstall()  # basics_tests 里的实例已经装过一次
    original = AsyncCompletions.create
    try:
        # 不装：读超时 0.5s，但空行一直来，请求 1.5s 后还挂着（就是这次她不回话的原因）
        task = asyncio.ensure_future(client.chat.completions.create(model="hang", messages=msgs))
        await asyncio.sleep(1.5)
        expect("keep-alive defeats read timeout", task.done(), False)
        task.cancel()

        limit = [1.0]
        logs = []
        expect("deadline installs", deadline.install(lambda: limit[0], logs.append), True)
        deadline.install(lambda: limit[0], logs.append)  # 热重载再装一次：仍只包一层
        expect("deadline wraps original once", AsyncCompletions.__dict__[deadline.ORIG_ATTR], original)
        t = time.monotonic()
        try:
            await client.chat.completions.create(model="hang", messages=msgs)
            got = "returned"
        except openai.APITimeoutError:
            got = "APITimeoutError"
        expect("deadline cuts hung request", (got, time.monotonic() - t < 2.5, len(logs)), ("APITimeoutError", True, 1))
        r = await client.chat.completions.create(model="m", messages=msgs)
        expect("deadline lets normal request through", r.choices[0].message.content, "ok")
        limit[0] = 0  # 关掉 = 不限
        task = asyncio.ensure_future(client.chat.completions.create(model="hang", messages=msgs))
        await asyncio.sleep(1.5)
        expect("deadline disabled", task.done(), False)
        task.cancel()
    finally:
        deadline.uninstall()
        expect("deadline uninstall restores", AsyncCompletions.create, original)
        await client.close()
        await runner.cleanup()

    # 流式请求不套时限
    class Fake:
        async def create(self, **kw):
            await asyncio.sleep(0.3)
            return "done"

    deadline.install(lambda: 0.1, lambda _m: None, cls=Fake, make_error=lambda _s: TimeoutError("cut"))
    expect("deadline skips stream", await Fake().create(stream=True), "done")
    try:
        await Fake().create()
        got = "returned"
    except TimeoutError as exc:
        got = str(exc)
    expect("deadline fake cut", got, "cut")
    deadline.uninstall(cls=Fake)

    # 再发一份（hedge）：第一份卡住 → 第二份先回；第一份只是慢 → 用第一份；都卡 → 超时；第一份很快报错 → 不再发
    class Hedge:
        plan: list = []
        calls = 0

        async def create(self, **kw):
            i = Hedge.calls
            Hedge.calls += 1
            how, secs = Hedge.plan[i]
            await asyncio.sleep(secs)
            if how == "err":
                raise ValueError(f"bad{i}")
            return f"r{i}"

    hlogs = []
    deadline.install(lambda: 1.0, hlogs.append, cls=Hedge, make_error=lambda _s: TimeoutError("cut"),
                     get_hedge=lambda: 0.2)

    async def run(plan):
        Hedge.plan, Hedge.calls = plan, 0
        hlogs.clear()
        t = time.monotonic()
        try:
            got = await Hedge().create()
        except Exception as exc:  # noqa: BLE001
            got = f"{type(exc).__name__}:{exc}"
        return got, time.monotonic() - t, Hedge.calls

    def near(res, want):  # Windows 计时粗：差 0.12s 以内算对
        return (res[0], res[2], abs(res[1] - want[1]) < 0.12) == (want[0], want[2], True) or res

    got = await run([("ok", 30), ("ok", 0.1)])
    expect("hedge: stalled first → second wins", near(got, ("r1", 0.3, 2)), True)
    expect("hedge: logged", any("再发一份" in m for m in hlogs) and any("后发的那份先回来了" in m for m in hlogs), True)
    expect("hedge: slow first still used", near(await run([("ok", 0.35), ("ok", 30)]), ("r0", 0.35, 2)), True)
    expect("hedge: fast answer → no second call", near(await run([("ok", 0.05)]), ("r0", 0.05, 1)), True)
    expect("hedge: both stall → timeout", near(await run([("ok", 30), ("ok", 30)]), ("TimeoutError:cut", 1.0, 2)), True)
    expect("hedge: quick error → raised, no second", near(await run([("err", 0.05)]), ("ValueError:bad0", 0.05, 1)), True)
    expect("hedge: first errors after hedge → wait for second", near(await run([("err", 0.3), ("ok", 0.3)]), ("r1", 0.5, 2)), True)
    expect("hedge: both error → first error", near(await run([("err", 0.3), ("err", 0.05)]), ("ValueError:bad0", 0.3, 2)), True)
    deadline.uninstall(cls=Hedge)


asyncio.run(deadline_tests())


# ------------------------------------------------------------------ kaju_life
async def life_tests():
    from kaju_core.life.daily import parse_plan, render_note

    plan = parse_plan('{"mood":"开心","events":[{"time":"7:10","text":"起床"},{"time":"12:00","text":"午饭"},'
                      '{"time":"18:00","text":"做饭"}],"share":{"time":"12:30","text":"考了满分"}}')
    expect("parse_plan zfill", plan["events"][0]["time"], "07:10")
    note = render_note(plan, dt.datetime(2026, 10, 30, 13, 0), 5)
    expect("render_note", ("午饭" in note, "接下来打算：18:00" in note, "考了满分" in note), (True, True, True))
    expect("render_note night = all done", "接下来" in render_note(plan, dt.datetime(2026, 10, 31, 2, 0), 5), False)

    life = importlib.import_module("kaju_life.main").KajuLife(Context(), {"day_start_hour": 5, "daily": {}, "diary": {}})
    life._loop_task.cancel()
    d = life.diary
    ev = AstrMessageEvent(sender="123", text="你好", name="路人")
    await d.log_incoming(ev)
    d.log_reply(ev, "你好呀&&happy&&")
    recs = d._read_log(life._day_key())
    expect("diary log", [(r["u"], r["x"]) for r in recs], [("123", "你好"), ("self", "你好呀")])
    ev.set_extra("found_emotions", ["proud"])  # 她跟着发了表情包（11-20）
    ev.set_extra("_ks_meme_label", "得意")
    d.log_reply(ev, "嘿嘿")
    ev.set_extra("meme_manager_legacy_probability_hit", False)  # 骰子没中 = 没发
    d.log_reply(ev, "嗯嗯")
    expect("diary logs her sticker", [r["x"] for r in d._read_log(life._day_key())][2:], ["嘿嘿", "[表情包：得意]", "嗯嗯"])
    from kaju_core.voice import emoji as _emoji
    expect("emoji label", (_emoji.label({"proud": "得意、炫耀时，被夸了"}, "proud"), _emoji.label({}, "shy")),
           ("得意、炫耀时", "shy"))
    today = dt.date.fromisoformat(life._day_key())
    y = (today - dt.timedelta(days=1)).isoformat()
    d._idx["diary"][y] = {"full": "私聊里兄长大人说要考试", "public": "群里很热闹", "brief": "普通的一天",
                          "todo": [{"text": "问考试结果", "private": True}]}
    life.daily.days[life._day_key()] = plan
    expect("diary own_day uses daily plan", "起床" in d._own_day(life._day_key()), True)
    expect("diary private note", "要考试" in d.build_memory_note(True), True)
    pub = d.build_memory_note(False)
    expect("diary public note", ("群里很热闹" in pub, "要考试" in pub, "问考试结果" in pub), (True, False, False))
    yd = today - dt.timedelta(days=1)
    expect("diary todo dated", f"- 问考试结果（{yd.year}年{yd.month}月{yd.day}日记）" in d.build_memory_note(True), True)
    # 两天的待办：新日记优先占 5 个名额，显示按从早到晚，各自带日期
    y2 = (today - dt.timedelta(days=2)).isoformat()
    d._idx["diary"][y2] = {"full": "前天", "public": "前天", "brief": "前天",
                           "todo": [{"text": f"旧事{i}", "private": True} for i in range(4)]}
    d._idx["diary"][y]["todo"] = [{"text": f"新事{i}", "private": True} for i in range(4)] + \
                                 [{"text": "旧事0", "private": True}]
    lines = [l for l in d.build_memory_note(True).splitlines() if l.startswith("- ")]
    expect("diary todo newest first", [l.split("（")[0] for l in lines],
           ["- 新事0", "- 新事1", "- 新事2", "- 新事3", "- 旧事0"])
    expect("diary todo dup keeps newest date", lines[-1].endswith(f"{yd.month}月{yd.day}日记）"), True)
    del d._idx["diary"][y2]
    # 一次性的小关心不当待办；"昨晚/明天"换成那天的具体日期
    dy = importlib.import_module("kaju_core.life.diary")
    expect("perishable meal/sleep", [dy.perishable(x) for x in (
        "惦记兄长大人昨晚那顿饭到底吃上了没有，明天问一句", "问兄长大人昨晚到底吃没吃饭，提醒他别熬太晚", "问他饭吃了没",
        "每晚十点半在空间写一条说说", "多给兄长大人做几顿饭", "等女王大人的椅子到货拍照片", "问面试结果")],
        [True, True, True, False, False, False, False])
    expect("absolute dates", dy.absolute_dates("昨晚那顿饭，明天问一句；今天的事；前天晚上；后天", "2026-10-31"),
           "10月30日晚上那顿饭，11月1日问一句；10月31日的事；10月29日晚上；11月2日")
    expect("absolute dates across month", dy.absolute_dates("明天考试", "2026-10-31"), "11月1日考试")
    d._idx["diary"][y]["todo"] = [{"text": "惦记兄长大人昨晚那顿饭到底吃上了没有，明天问一句", "private": True},
                                  {"text": "明天问他面试结果", "private": True}]
    note = d.build_memory_note(True)
    expect("stale meal check not shown", "那顿饭" in note, False)
    expect("relative todo dated", f"- {today.month}月{today.day}日问他面试结果（" in note, True)
    expect("note says old care is over", "都已经过去了" in note, True)

    async def fake_ask(system, prompt):
        expect("diary prompt forbids one-off checks", ("一次性的小关心不要记" in prompt, "写具体日期" in prompt), (True, True))
        return json.dumps({"full": "今天和路人打了招呼，说了你好，心情不错，还想着明天的事情要早点做完才好。", "public": "打招呼",
                           "brief": "打招呼", "todo": [{"text": "问他今晚那顿饭吃上没", "private": True},
                                                       {"text": "明天把会议记录整理好", "private": False}]},
                          ensure_ascii=False)

    d._ask = fake_ask
    entry = await d.write_diary(life._day_key())
    tm = today + dt.timedelta(days=1)
    expect("written todo filtered + dated", [t["text"] for t in (entry or {}).get("todo", [])],
           [f"{tm.month}月{tm.day}日把会议记录整理好"])
    d._idx["diary"].pop(life._day_key(), None)
    d._idx["diary"][y]["todo"] = [{"text": "问考试结果", "private": True}]
    expect("resolve 昨天", d.resolve_when("昨天"), ("diary", y))
    expect("resolve junk", d.resolve_when("13月"), None)


asyncio.run(life_tests())


# ------------------------------------------------------------------ kaju_heart: 最依赖的人 (bond.py, formerly kaju_bond)
heart_main = importlib.import_module("kaju_heart.main")
heart_plugin = heart_main.KajuHeart(book_context(), {"bond": {}})
expect("heart owner from address book", (heart_plugin.owner, "QQ 999" in heart_plugin.bond.note("999")), ("999", True))
expect("heart owner default", heart_main.KajuHeart(Context(), {}).owner, "111111111")


class FakeBot:
    def __init__(self, owner_in_group=True):
        self.calls, self.owner_in_group = [], owner_in_group

    async def call_action(self, action, **kw):
        self.calls.append((action, kw))
        if action == "get_group_member_info":
            return {"join_time": 1, "nickname": "兄"} if self.owner_in_group else {"join_time": 0, "nickname": ""}
        if action == "get_group_info":
            return {"group_name": "妖妖"}
        return {}


async def bond_tests():
    mod = importlib.import_module("kaju_platforms.qq.bond")
    real_sleep = asyncio.sleep

    class _FastAsyncio:
        @staticmethod
        async def sleep(*_):
            await real_sleep(0)

    mod.asyncio = _FastAsyncio
    cfg = {"cooldown_minutes": 10, "hourly_limit": 2}
    from kaju_astr import AstrBody  # Bond 只认 body：发 QQ 消息走 body.qq_call（这里用消息自带的 FakeBot）
    b = mod.Bond(AstrBody(Context()), lambda: cfg, lambda: "111111111", lambda qq: "兄长大人")
    b.ask_brother_for_help = b.ask

    expect("bond owner note", ("【最依赖的人】" in b.note("111111111"), "就是兄长大人本人" in b.note("111111111")), (True, True))
    expect("bond other note (称呼规则已说，不再重复)", ("【最依赖的人】" in b.note("555"), "不是兄长大人本人" in b.note("555")), (True, False))
    expect("bond no fixed line", "佳树要去告诉兄长大人" in b.note("555"), False)
    cfg["enable"] = False
    expect("bond off", b.note("111111111"), "")
    cfg["enable"] = True

    ev = AstrMessageEvent(sender="111111111", group="222222222")
    ev.bot = FakeBot()
    out = await b.ask_brother_for_help(ev, "逗佳树", "兄长大人")
    expect("bond owner refused", (out.startswith("没找"), ev.bot.calls), (True, []))

    # group harassment: PM owner now (her line + detail), @ owner after her reply is sent
    ev = AstrMessageEvent(sender="555", group="222222222", admin=False, name="路人甲", text="告诉我你住哪 快说")
    ev.bot = FakeBot()
    out = await b.ask_brother_for_help(ev, "一直逼问佳树住哪", "兄长大人！有人欺负佳树")
    pms = [kw["message"][0]["data"]["text"] for a, kw in ev.bot.calls if a == "send_private_msg"]
    expect("bond pm", (len(pms), pms[0], "「妖妖」群里" in pms[1], "QQ 555" in pms[1], "住哪 快说" in pms[1]),
           (2, "兄长大人！有人欺负佳树", True, True, True))
    expect("bond result", out.startswith("已经去找兄长大人了"), True)
    expect("bond no @ before reply", any(a == "send_group_msg" for a, _ in ev.bot.calls), False)
    await b.at_brother(ev)
    at = [kw for a, kw in ev.bot.calls if a == "send_group_msg"]
    expect("bond @ after reply", (len(at), at[0]["group_id"], at[0]["message"][0]),
           (1, 222222222, {"type": "at", "data": {"qq": "111111111"}}))
    await b.at_brother(ev)
    expect("bond @ only once", len([1 for a, _ in ev.bot.calls if a == "send_group_msg"]), 1)

    # same person again within cooldown → no new notification
    ev2 = AstrMessageEvent(sender="555", group="222222222", admin=False, text="快说")
    ev2.bot = FakeBot()
    out = await b.ask_brother_for_help(ev2, "又来", "兄长大人")
    expect("bond cooldown", ("已经找过" in out, [a for a, _ in ev2.bot.calls if a.startswith("send")]), (True, []))

    # owner not in that group → PM only, no @
    ev3 = AstrMessageEvent(sender="666", group="123", admin=False, text="滚")
    ev3.bot = FakeBot(owner_in_group=False)
    await b.ask_brother_for_help(ev3, "骂佳树", "兄长大人……")
    await b.at_brother(ev3)
    expect("bond owner absent", ([a for a, _ in ev3.bot.calls if a.startswith("send")].count("send_private_msg") >= 1,
                                 any(a == "send_group_msg" for a, _ in ev3.bot.calls)), (True, False))

    # hourly limit (2) reached
    ev4 = AstrMessageEvent(sender="777", admin=False, text="hi")
    ev4.bot = FakeBot()
    out = await b.ask_brother_for_help(ev4, "纠缠", "兄长大人")
    expect("bond hourly limit", ("好几次" in out, ev4.bot.calls), (True, []))


asyncio.run(bond_tests())

ft = importlib.import_module("follow_through.main")
expect("follow_through knows bond tool", "ask_brother_for_help" in ft.CAPABILITY_LABELS, True)
expect("follow_through strips meme tags", ft.FollowThrough._clean("查到啦\n&&happy&&"), "查到啦")


# ------------------------------------------------------------------ 2026-10-31 群聊：她的今天 / 重复发 / 抢答
def today_tests():
    from kaju_core.life.daily import asks_about_her, mark_told, render_note, told_in

    for text in ("今天怎么样", "佳树在干嘛呢", "你今天干了啥？", "吃饭了吗", "吃了没", "学生会忙吗", "你呢",
                 "最近怎么样", "放学了没", "在忙吗"):
        expect(f"asks about her: {text}", asks_about_her(text), True)
    for text in ("好无聊来跟佳树聊天", "电人的话需要多少的电压能把人电晕", "还会发空间啊", "帮她记忆",
                 "今天天气好热", "我今天好累", "晚安", "你今天真可爱", "必须告诉我"):
        expect(f"not asking about her: {text}", asks_about_her(text), False)

    # 2026-10-30 的真实日程和她那天在群里的回复
    plan = {"mood": "有点犯困", "events": [
        {"time": "15:40", "text": "学生会整理文化祭账目，算到眼睛发花"},
        {"time": "17:20", "text": "放学绕去文具店，买蓝黑两色荧光笔"},
        {"time": "19:30", "text": "晚饭煮味噌汤，盐放多了，自己先尝出来"}],
        "share": {"time": "17:20", "text": "文具店荧光笔打折，佳树多买了一支蓝的，想着兄长大人划重点用得上。"}}
    now = dt.datetime(2026, 10, 30, 22, 58)
    quiet = render_note(plan, now, 5, asked=False)
    expect("not asked: no schedule details", ("荧光笔" in quiet, "账目" in quiet, "不要主动讲" in quiet), (False, False, True))
    full = render_note(plan, now, 5, asked=True)
    expect("asked: schedule + share", ("账目" in full, "荧光笔打折" in full), (True, True))

    g = "qq:GroupMessage:222222222"
    reply = "兄长大人终于想起佳树啦\n佳树今天算文化祭账目算到眼睛发花，正好想歇一歇\n对了，文具店荧光笔打折，佳树多买了支蓝的，留给你划重点"
    expect("mark_told finds both", sorted(mark_told(plan, g, reply)), ["15:40", "share"])
    expect("mark_told: unrelated reply", mark_told(plan, g, "诶——这问题佳树不答哦，电到人会出大事的"), [])
    expect("mark_told: 味噌汤 not told", "19:30" in told_in(plan, g), False)
    again = render_note(plan, now, 5, asked=True, told=told_in(plan, g))
    expect("asked again here: told marked, share hidden",
           ("账目，算到眼睛发花（在这里已经说过了）" in again, "荧光笔打折" in again), (True, False))
    other = render_note(plan, now, 5, asked=True, told=told_in(plan, "qq:FriendMessage:1"))
    expect("other chat: not marked", ("（在这里已经说过了）" in other, "荧光笔打折" in other), (False, True))


today_tests()


async def outgoing_tests():
    from astrbot.api.message_components import Plain
    from astrbot.core.agent.tool import ToolSet

    from kaju_basics.outgoing import drop_repeated, strip_meme_tags

    b = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {})

    class Tool:
        def __init__(self, name): self.name = name

    # send_message_to_user: 平常聊天去掉，定时任务那一轮保留
    req = ProviderRequest("SYS")
    req.func_tool = ToolSet([Tool("web_search"), Tool("send_message_to_user"), Tool("post_qzone")])
    await b.hide_chat_tools(AstrMessageEvent(group="222222222"), req)
    expect("chat turn: send_message_to_user hidden", req.func_tool.names(), ["web_search", "post_qzone"])
    req.func_tool = ToolSet([Tool("send_message_to_user")])
    await b.hide_chat_tools(AstrMessageEvent(platform="cron"), req)
    expect("cron turn keeps send_message_to_user", req.func_tool.names(), ["send_message_to_user"])
    # memorix 的管理工具（通配符）：平常聊天不给，search_memory / memory_stats 照留
    req.func_tool = ToolSet([Tool("search_memory"), Tool("memory_delete_admin"), Tool("memory_fuzzy_modify_admin"),
                             Tool("memory_stats")])
    await b.hide_chat_tools(AstrMessageEvent(), req)
    expect("chat turn: memory_*_admin hidden", req.func_tool.names(), ["search_memory", "memory_stats"])

    # 定时任务里直接发的消息去掉表情标签
    args = {"messages": [{"type": "plain", "text": "到点啦\n&&happy&&"}, {"type": "plain", "text": "&&confused&&"}]}
    await b.clean_tool_message(AstrMessageEvent(platform="cron"), Tool("send_message_to_user"), args)
    expect("tool message tags stripped", args["messages"], [{"type": "plain", "text": "到点啦"}])

    expect("strip tags", strip_meme_tags("女王大人怎么突然问这个呀&&confused&&"), "女王大人怎么突然问这个呀")
    expect("strip tags keeps plain text", strip_meme_tags("A&B"), "A&B")

    # 2026-10-31 那一轮：正文先发一次、工具又发一次、最后的回复又是同一段
    class Result:
        def __init__(self, *comps): self.chain = list(comps)

    ev = AstrMessageEvent(group="222222222")
    first = "诶——这问题佳树不答哦，电到人会出大事的，太危险了\n女王大人怎么突然问这个呀"
    ev.set_result(Result(Plain(first)))
    await b.drop_repeats(ev)
    expect("first send untouched", ev.get_result().chain[0].text, first)
    ev.set_result(Result(Plain(first + "\n&&confused&&")))
    await b.drop_repeats(ev)
    expect("same text again (+ meme) not sent", ev.get_result().chain, [])
    ev.set_result(Result(Plain("诶，这问题佳树不答哦！电到人会出大事的～太危险了\n要说安全，碰电的事别去试&&shy&&")))
    await b.drop_repeats(ev)
    expect("only the new line is kept", ev.get_result().chain[0].text, "要说安全，碰电的事别去试&&shy&&")
    expect("drop_repeated: nothing said yet", drop_repeated("你好\n今天呢", set()), ("你好\n今天呢", 0))

    ev = AstrMessageEvent()
    ev.set_result(Result(Plain("好呀&&unknowntag&&")))
    await b.strip_leftover_tags(ev)
    expect("leftover tag stripped", ev.get_result().chain[0].text, "好呀")


asyncio.run(outgoing_tests())


# ------------------------------------------------------------------ 2026-10-31 私聊：发表情包她先描述一遍
async def media_reaction_tests():
    from astrbot.api.message_components import Image, Plain, Reply, Video

    kb = importlib.import_module("kaju_basics.main")
    b = kb.KajuBasics(Context(), {})

    async def note(messages, text, image_urls=None):
        ev = AstrMessageEvent(text=text, messages=messages)
        req = ProviderRequest("SYS", image_urls=image_urls or [])
        await b.add_image_note(ev, req)
        return req.system_prompt

    duck = Image(url="http://x/duck.gif")
    sp = await note([duck], "", image_urls=["x"])
    expect("sticker only: react, don't describe",
           ("别复述" in sp or "不要先把画面" in sp, "只发了图" in sp, "可以具体说说" in sp), (True, True, False))
    sp = await note([Plain("哈哈哈哈"), duck], "哈哈哈哈", image_urls=["x"])
    expect("image + words", ("还说了话" in sp, "只发了图" in sp), (True, False))
    for q in ("这是什么", "图里写的什么", "这是谁", "什么梗", "啥？", "图上是什么呀"):
        sp = await note([Plain(q), duck], q, image_urls=["x"])
        expect(f"asked about the image: {q}", "可以具体说说" in sp, True)
    # 叫她看（看懂、给反应）≠ 问里面是什么（2026-11-02 "看他发的图" → 她把面板读数念了一遍）
    for q in ("你看得懂吗", "能看清吗", "你看看这个", "看这张图"):
        sp = await note([Plain(q), duck], q, image_urls=["x"])
        expect(f"asked to look: {q}", ("不是要你讲解" in sp, "可以具体说说" in sp), (True, False))
    sp = await note([Reply(chain=[Plain("这句听着像要下线了呀")]), Plain("看他发的图")], "看他发的图", image_urls=["x"])
    expect("look at an image from the chat history", ("不是要你讲解" in sp, "【关于图片和视频】" in sp), (True, True))
    sp = await note([Plain("你看看上面那个视频")], "你看看上面那个视频", image_urls=["x"])
    expect("look at a video from history", "叫你看视频" in sp, True)
    sp = await note([Plain("看他发的图片上写的什么")], "看他发的图片上写的什么", image_urls=["x"])
    expect("look + asks content → no look note", "不是要你讲解" in sp, False)
    sp = await note([Reply(chain=[Video(file="v.mp4")]), Plain("笑死")], "笑死", image_urls=["x"])
    expect("quoted video + words: react", ("对方发了视频还说了话" in sp, "可以具体说说" in sp), (True, False))
    sp = await note([Reply(chain=[Video(file="v.mp4")]), Plain("视频里说的啥")], "视频里说的啥", image_urls=["x"])
    expect("quoted video asked", "对方在问视频里的内容" in sp, True)
    sp = await note([Plain("晚安")], "晚安")
    expect("no media, no note", sp, "SYS")
    sp = await note([Plain("你觉得呢")], "你觉得呢", image_urls=["x"])  # 群聊记录里别人的图
    expect("someone else's image: general note only", ("【关于图片和视频】" in sp, "【这条消息】" in sp), (True, False))


asyncio.run(media_reaction_tests())


# ------------------------------------------------------------------ 2026-10-31 没人让她存表情包，她说"存下来了"
async def false_save_tests():
    from astrbot.core.agent.tool import ToolSet

    ft = importlib.import_module("follow_through.main")
    meme = next(a for a in ft.ACTIONS if a.key == "meme")
    # 测试里她真说过的谎称
    for text in ("佳树把它存下来了，以后想用\"OK\"就发它", "这张鸭鸭好可爱，佳树存下来了",
                 "那只小鸭子佳树先存下来当证据", "已经存到表情包里了", "存好啦", "收藏好了", "佳树收藏啦"):
        expect(f"claim: {text}", ft.claims(meme.claim, text), True)
    # 真实聊天里她说过的、不是谎称的话
    for text in ("诶嘿嘿，是给佳树做的吗？兄长大人太厉害了！佳树要全部收藏起来。",
                 "第四张啦！佳树虽然看不清，但心里已经收下了哦。",
                 "佳树做不到呢，聊天里没法直接把图存进表情库。",
                 "收下了哦！这张笑得眼睛都眯起来，佳树建议放进\"开心\"那一类。",
                 "佳树没把它存下来了", "这个表情包好可爱"):
        expect(f"not a claim: {text}", ft.claims(meme.claim, text), False)

    reply = "诶嘿嘿，这只小鸭子举手的姿势好认真\n\n佳树把它存下来了，以后想用\"OK\"就发它\n\n&&stickers&&"
    expect("retract drops the claim line", ft.retract_claims(reply, meme.claim),
           "诶嘿嘿，这只小鸭子举手的姿势好认真\n\n&&stickers&&")
    expect("retract falls back to clauses", ft.retract_claims("收到，佳树存下来了", meme.claim), "收到")
    expect("retract: nothing left", ft.retract_claims("存好啦\n&&happy&&", meme.claim), None)
    expect("retract: no claim, unchanged", ft.retract_claims("好，那说定了", meme.claim), "好，那说定了")

    class Tool:
        def __init__(self, name): self.name = name

    p = ft.FollowThrough(Context(), {"enable_follow_up": False})

    async def run(user_text, reply, extras=None, calls=None):
        ev = AstrMessageEvent(text=user_text)
        ev.set_extra("_ft_req", {"system_prompt": "", "contexts": [], "prompt": "", "user_text": user_text,
                                 "func_tool": ToolSet([Tool("save_meme")])})
        ev.set_extra("_ft_calls", calls or [])
        for k, v in (extras or {}).items():
            ev.set_extra(k, v)
        resp = LLMResponse(reply)
        await p.check(ev, resp)
        return ev, resp.completion_text

    claim_reply = "收到啦\n这张鸭鸭好可爱，佳树存下来了"
    ev, out = await run("", claim_reply)
    expect("unasked claim removed before sending", (out, ev.get_extra(ft.RETRACT_KEY)), ("收到啦", "meme"))
    _, out = await run("把这个存成表情包", claim_reply)
    expect("asked: left for the save/follow-up path", out, claim_reply)
    _, out = await run("", claim_reply, extras={ft.MEME_SAVER_RESULT: {"saved": True}})
    expect("meme_saver saved it this turn: keep", out, claim_reply)
    _, out = await run("", claim_reply, calls=[{"name": "save_meme", "ok": True, "result": "ok"}])
    expect("save_meme really called: keep", out, claim_reply)

    # 存进历史的那份也删掉
    class Part:
        type, text = "text", "收到啦\n这张鸭鸭好可爱，佳树存下来了"

    class Msg:
        role, content = "assistant", [Part()]

    class Run:
        messages = [Msg()]

    ev, _ = await run("", claim_reply)
    await p.retract_history(ev, Run, None)
    expect("history copy cleaned", Run.messages[-1].content[0].text, "收到啦")


asyncio.run(false_save_tests())


async def chime_tests():
    from astrbot.api.message_components import At, Plain

    sci = importlib.import_module("smart_chime_in.main")
    G = "222222222"
    BRO, QUEEN, BOT = "111111111", "333333333", "555555555"

    class Conv:
        async def get_curr_conversation_id(self, umo): return "cid"
        async def get_conversation(self, umo, cid): return object()

    class Ev(AstrMessageEvent):
        session_id = G

        def request_llm(self, **kw):
            return ("LLM", self.message_str)

    def msg(sender, name, text, at=None, wake=False):
        comps = ([At(qq=at)] if at else []) + [Plain(text)]
        e = Ev(sender=sender, group=G, text=text, name=name, messages=comps)
        e.is_at_or_wake_command = wake
        return e

    async def run(plugin, e):
        return [x async for x in plugin.maybe_chime_in(e)]

    def plugin():
        p = sci.SmartChimeIn(Context(), {"quiet_seconds": 0.05, "follow_quiet_seconds": 0.05, "base_chance": 0.0,
                                         "question_bonus": 0.0, "topic_bonus": 0.0, "lively_bonus": 0.0,
                                         "wake_quiet_seconds": 0.15, "wake_max_wait": 1.0})
        p.context.conversation_manager = Conv()
        return p

    # 她 01:58 回过兄长大人、01:59 回过女王大人；02:00 女王大人 "，，，" 接着 @兄长大人 "还会发空间啊"
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    t0 = __import__("time").time()
    st.partners = {BRO: t0 - 100, QUEEN: t0 - 30}
    out = await asyncio.gather(run(p, msg(QUEEN, "来点作用吧", "，，，")),
                               run(p, msg(QUEEN, "来点作用吧", "还会发空间啊", at=BRO)))
    expect("queen turns to brother: no follow", out, [[], []])
    # 兄长大人回答女王大人："会的" / "帮她记忆"
    expect("brother answering queen: no follow", await run(p, msg(BRO, "林一", "会的")), [])
    expect("brother answering queen 2: no follow", await run(p, msg(BRO, "林一", "帮她记忆")), [])
    # 对照：女王大人没 @ 别人、接着她刚才的话
    expect("queen continues with her: follow", await run(p, msg(QUEEN, "来点作用吧", "为什么不能说")),
           [("LLM", "为什么不能说")])

    # 被叫到后等对方说完；她回复时已经看到的话不再单独接着聊
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    wake = msg(QUEEN, "来点作用吧", "佳树我问你个事", wake=True)

    async def more():
        await asyncio.sleep(0.1)
        return await run(p, msg(QUEEN, "来点作用吧", "电人要多少电压"))

    import time as _time
    start = _time.time()
    follow_task = asyncio.create_task(more())
    await run(p, wake)
    expect("wake waits for the second line", _time.time() - start >= 0.25, True)
    await p.show_late_messages(wake, ProviderRequest("SYS"))  # 她开始回复：之前的消息都看到了
    expect("second line not answered separately", await follow_task, [])

    # 同一个人连着叫她两次：只回第二次
    p = plugin()
    w1, w2 = msg(QUEEN, "来点作用吧", "@佳树 在吗", wake=True), msg(QUEEN, "来点作用吧", "@佳树 问你", wake=True)

    async def second():
        await asyncio.sleep(0.05)
        await run(p, w2)

    await asyncio.gather(run(p, w1), second())
    expect("older wake dropped", (w1.is_stopped(), w1.is_at_or_wake_command, w2.is_stopped()), (True, False, False))

    # 叫她之后新来的群消息补进这一轮
    class Lock:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class GCC:
        raw_records = {f"qq:GroupMessage:{G}": __import__("collections").deque(["[林一/02:00:31]:  会的"])}
        _record_ids = {f"qq:GroupMessage:{G}": __import__("collections").deque(["r2"])}
        def _get_lock(self, umo): return Lock()

    class Meta:
        class star_cls:
            group_chat_context = GCC()

    p = plugin()
    p.context.get_all_stars = lambda: [Meta]
    ev = msg(QUEEN, "来点作用吧", "@佳树 在吗", wake=True)
    ev.set_extra("_group_context_record_id", "r1")  # 已被内置上下文用掉
    req = ProviderRequest("SYS")
    await p.show_late_messages(ev, req)
    expect("late messages shown", ("会的" in req.extra_user_content_parts[0].text,
                                   len(Meta.star_cls.group_chat_context.raw_records[ev.unified_msg_origin])), (True, 0))

    # ---- 回之前再看一眼（2026-11-01）
    # 同一个人连着叫两次、第二次在第一次等完之后（第一次在排队）：第一次交给第二次一起回
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    w1 = msg(BRO, "林一", "佳树你看这个", wake=True)
    await run(p, w1)  # 等完了，在排队
    w2 = msg(BRO, "林一", "是上面图这样的", wake=True)
    hold2 = asyncio.create_task(run(p, w2))
    await asyncio.sleep(0.05)
    await p.wake_catch_up(w1, ProviderRequest("SYS"))
    expect("catch up: queued wake hands over", (w1.is_stopped(), w1.is_at_or_wake_command), (True, False))
    await hold2
    req = ProviderRequest("SYS")
    await p.wake_catch_up(w2, req)
    expect("catch up: newer one answers with merged note",
           (w2.is_stopped(), "前面还叫过你（「佳树你看这个」" in req.system_prompt), (False, True))
    await p.show_late_messages(w2, ProviderRequest("SYS"))  # 她开始回了
    expect("catch up: bookkeeping cleared", (st.wake_info, st.wake_pending), ({}, {}))

    # 被 hold 顶掉的那次，说过的话也记到后面那次上
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    w1, w2 = msg(QUEEN, "来点作用吧", "@佳树 在吗", wake=True), msg(QUEEN, "来点作用吧", "@佳树 问你", wake=True)

    async def second_wake():
        await asyncio.sleep(0.05)
        await run(p, w2)

    await asyncio.gather(run(p, w1), second_wake())
    req = ProviderRequest("SYS")
    await p.wake_catch_up(w2, req)
    expect("hold drop: earlier text carried", "「@佳树 在吗」" in req.system_prompt, True)

    # 别人也在排队等她：这次只回眼前这个人
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    wq, wb = msg(QUEEN, "来点作用吧", "佳树早", wake=True), msg(BRO, "林一", "佳树吃了吗", wake=True)
    await asyncio.gather(run(p, wq), run(p, wb))
    req = ProviderRequest("SYS")
    await p.wake_catch_up(wq, req)
    expect("others queued: note", ("林一 也叫了你" in req.system_prompt, wq.is_stopped()), (True, False))
    req = ProviderRequest("SYS")
    await p.wake_catch_up(wb, req)
    expect("last in queue: no others note", "也叫了你" in req.system_prompt, False)

    # TA 是在她上一条（回给 TA 的）发出去之前打的字
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    w = msg(BRO, "林一", "不是这个哦", wake=True)
    await run(p, w)
    st.reply_end = (_time.time(), BRO)
    req = ProviderRequest("SYS")
    await p.wake_catch_up(w, req)
    expect("unseen reply: note", "TA 多半还没看到" in req.system_prompt, True)
    w = msg(QUEEN, "来点作用吧", "佳树在吗", wake=True)
    await run(p, w)
    st.reply_end = (_time.time(), BRO)  # 回的是别人：不算
    req = ProviderRequest("SYS")
    await p.wake_catch_up(w, req)
    expect("unseen reply to someone else: no note", req.system_prompt, "SYS")
    # 接着聊也一样
    ev = msg(BRO, "林一", "是上面图这样的")
    ev.set_extra("_chime_in", "follow")
    ev.set_extra("_chime_follow", {"sender": BRO, "name": "林一", "text": "是上面图这样的",
                                   "t": _time.time() - 1, "t0": _time.time() - 5})
    req = ProviderRequest("SYS")
    await p.frame_request(ev, req)
    expect("follow: unseen note", ("可能在接着跟你聊" in req.system_prompt, "TA 多半还没看到" in req.system_prompt),
           (True, True))

    # ---- 排队的"接着聊"（2026-11-03 20:14 群里聊得热、模型卡了一分钟：她一条条回一分多钟前的话）
    DORA, FIVE = "444444444", "777777777"
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.partners = {DORA: _time.time() - 20, FIVE: _time.time() - 20}
    f1 = msg(DORA, "哆啦a梦", "0.8B都行")
    expect("busy: dora follow queued", await run(p, f1), [("LLM", "0.8B都行")])
    await asyncio.sleep(0.01)
    f2 = msg(FIVE, "555", "买中转站可能要")
    expect("busy: 555 follow queued", await run(p, f2), [("LLM", "买中转站可能要")])
    await p.follow_catch_up(f1, ProviderRequest("SYS"))
    expect("busy: older follow steps aside", (f1.is_stopped(), f1.is_at_or_wake_command), (True, False))
    req = ProviderRequest("SYS")
    await p.follow_catch_up(f2, req)
    expect("busy: newest answers, told about dora", (f2.is_stopped(), "哆啦a梦 也在接着跟你说话" in req.system_prompt),
           (False, True))
    expect("busy: queue empty", st.follows, {})

    # 等太久、群里早聊过去了：不回
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.partners = {DORA: _time.time() - 20}
    f3 = msg(DORA, "哆啦a梦", "16G内存")
    await run(p, f3)
    info = next(iter(st.follows.values()))
    info["t"] -= 60
    for i in range(6):
        st.recent.append({"sender": FIVE, "text": f"别的话{i}", "at_other": False, "t": _time.time()})
    f3.set_extra("_chime_prev_spoke", 123.0)
    await p.follow_catch_up(f3, ProviderRequest("SYS"))
    expect("stale follow dropped", (f3.is_stopped(), st.last_spoke), (True, 123.0))
    # 不算太久（只过了几条）：照常回
    f4 = msg(DORA, "哆啦a梦", "量太少了")
    st.partners[DORA] = _time.time()
    await run(p, f4)
    await p.follow_catch_up(f4, ProviderRequest("SYS"))
    expect("fresh follow answered", f4.is_stopped(), False)

    # 接着聊排队时，有人直接叫她：接着聊让给叫她那次，叫她那次知道还有人在接着说
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.partners = {DORA: _time.time() - 20}
    f5 = msg(DORA, "哆啦a梦", "你纯聊天花token多吗")
    await run(p, f5)
    w = msg(BRO, "林一", "佳树你看看这个", wake=True)
    await run(p, w)
    await p.follow_catch_up(f5, ProviderRequest("SYS"))
    expect("follow steps aside for a wake", f5.is_stopped(), True)
    req = ProviderRequest("SYS")
    await p.wake_catch_up(w, req)
    expect("wake told about follow", (w.is_stopped(), "哆啦a梦 也在接着跟你说话" in req.system_prompt), (False, True))
    # 关掉合并：照旧各回各的
    p = plugin()
    p.config["follow_merge"] = False
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.partners = {DORA: _time.time() - 20, FIVE: _time.time() - 20}
    a, b = msg(DORA, "哆啦a梦", "一"), msg(FIVE, "555", "二")
    await run(p, a)
    await asyncio.sleep(0.01)
    await run(p, b)
    await p.follow_catch_up(a, ProviderRequest("SYS"))
    expect("follow_merge off", a.is_stopped(), False)

    # ---- 2026-11-05：没叫她时群友话里的"你"不是她
    from astrbot.api.event import MessageChain
    from astrbot.api.message_components import Plain as _P

    async def sent(p, ev, reply_text):
        ev.set_result(MessageChain([_P(reply_text)]))
        await p.mark_reply_start(ev)
        await p.mark_spoke(ev)

    # 她插了一句（没问什么）：女王大人不算在跟她聊，接下来"有网页吧"不当成接着聊
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    c = msg(QUEEN, "来点作用吧", "更了啊")
    c.set_extra("_chime_in", True)
    await sent(p, c, "女王大人动作还挺快呀\n可别拖成通宵啦～")
    expect("chime-in: speaker not a partner", QUEEN in st.partners, False)
    expect("chime-in: next line not a follow", await run(p, msg(QUEEN, "来点作用吧", "有网页吧")), [])
    # 她插话时问了 TA（问句不带问号）：TA 接下来的话可能是在回她
    c = msg(DORA, "哆啦a梦", "咒术回战 看不腻呢怎么")
    c.set_extra("_chime_in", True)
    await sent(p, c, "学姐追到哪一集啦")
    expect("chime-in with a question: partner", DORA in st.partners, True)
    # 叫她 / 接着聊 照旧
    w = msg(BRO, "林一", "佳树看看", wake=True)
    await sent(p, w, "好的兄长大人")
    expect("wake reply: partner", BRO in st.partners, True)

    # 插话提醒：写明"你"不是她；发言人最近跟谁互相 @ 过，就点出来
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    await run(p, msg(QUEEN, "来点作用吧", "有何意见", at=DORA))
    ev = msg(DORA, "哆啦a梦", "你更新了吗")
    ev.set_extra("_chime_in", True)
    req = ProviderRequest("SYS")
    await p.frame_request(ev, req)
    expect("chime note: 你 is someone else", "这里的「你」是发言人在叫群里的别人" in req.system_prompt, True)
    expect("chime note: who 你 means", "哆啦a梦 刚才在跟 来点作用吧 说话" in req.system_prompt, True)
    ev = msg(FIVE, "555", "你变了")
    ev.set_extra("_chime_in", True)
    req = ProviderRequest("SYS")
    await p.frame_request(ev, req)
    expect("chime note: no hint without @", ("「你」是发言人" in req.system_prompt, "刚才在跟" in req.system_prompt),
           (True, False))
    expect("chime note: no leftover braces", "{" in req.system_prompt, False)
    ev = msg(BRO, "林一", "基本聊天感觉都还稍微有点问题呢")
    ev.set_extra("_chime_in", "follow")
    ev.set_extra("_chime_follow", {"sender": BRO, "name": "林一", "text": ev.message_str, "t": _time.time()})
    req = ProviderRequest("SYS")
    await p.frame_request(ev, req)
    expect("follow note: 你 is no evidence", "话里有「你」不算证据" in req.system_prompt, True)


asyncio.run(chime_tests())


async def chime_merge_tests():
    """2026-11-07 妖妖群：555 发红包（她插话那轮在生成）→ 又说"给佳树爆米"叫她 → 两条回复；
    "0.11" 和还在等描述的表情包 → 又是两条。"""
    import collections
    import time as _time
    from astrbot.api.message_components import Image, Plain

    sci = importlib.import_module("smart_chime_in.main")
    G, FIVE, BRO = "222222222", "777777777", "111111111"
    UMO = f"qq:GroupMessage:{G}"

    class Conv:
        async def get_curr_conversation_id(self, umo): return "cid"
        async def get_conversation(self, umo, cid): return object()

    class Ev(AstrMessageEvent):
        session_id = G

        def request_llm(self, **kw):
            return ("LLM", kw.get("prompt"))

    def msg(sender, name, text="", wake=False, image=False):
        comps = ([Plain(text)] if text else []) + ([Image()] if image else [])
        e = Ev(sender=sender, group=G, text=text, name=name, messages=comps)
        e.is_at_or_wake_command = wake
        return e

    class Lock:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    def plugin(**over):
        cfg = {"quiet_seconds": 0.05, "follow_quiet_seconds": 0.05, "base_chance": 0.0, "question_bonus": 0.0,
               "topic_bonus": 0.0, "lively_bonus": 0.0, "wake_quiet_seconds": 0.1, "wake_max_wait": 1.0}
        cfg.update(over)
        p = sci.SmartChimeIn(Context(), cfg)
        p.context.conversation_manager = Conv()
        gcc = type("GCC", (), {})()
        gcc.raw_records = {UMO: collections.deque()}
        gcc._record_ids = {UMO: collections.deque()}
        gcc._get_lock = lambda umo: Lock()
        meta = type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})
        p.context.get_all_stars = lambda: [meta]
        return p, gcc

    async def run(p, e):
        return [x async for x in p.maybe_chime_in(e)]

    # 插话那轮写好了，555 在红包之后又叫了她：这轮不发，群聊记录放回去，叫她那次知道红包还没回
    p, gcc = plugin()
    red = msg(FIVE, "555", "[QQ红包]请使用新版手机QQ查收红包。")
    red.created_at = _time.time() - 5
    red.set_extra("_chime_in", True)
    red.set_extra("_chime_prev_spoke", 11.0)
    red.set_extra("_group_context_record_id", "rc")
    gcc.raw_records[UMO].extend(["[女王]: 骗骗你的呀", "[555]: [QQ红包]", "[555]: 给佳树爆米"])
    gcc._record_ids[UMO].extend(["r0", "rc", "rw"])
    await p.snapshot_records(red, ProviderRequest("SYS"))
    gcc.raw_records[UMO] = collections.deque(["[555]: 给佳树爆米"])  # 内置上下文给了她 rc 之前的，留下后面的
    gcc._record_ids[UMO] = collections.deque(["rw"])
    wake = msg(FIVE, "555", "给佳树爆米", wake=True)
    await run(p, wake)
    resp = LLMResponse("呜哇，555学长真的给佳树发红包了")
    await p.yield_to_newer_wake(red, resp)
    expect("yield: chime-in reply dropped", (resp.completion_text, red.is_stopped()), ("", True))
    expect("yield: records back in order", list(gcc._record_ids[UMO]), ["r0", "rc", "rw"])
    expect("yield: cooldown restored", p._groups[UMO].last_spoke, 11.0)
    req = ProviderRequest("SYS")
    await p.wake_catch_up(wake, req)
    expect("yield: wake told red packet not answered",
           ("叫你之前还发了 「[QQ红包]请使用新版手机QQ查收红包。」" in req.system_prompt, wake.is_stopped()), (True, False))

    # 不让的：叫她的是别人 / 叫她在这条之前 / 这轮已经等了很久 / 关掉
    for label, sender, before, age, over in [("other sender", BRO, False, 5, {}), ("wake came first", FIVE, True, 5, {}),
                                             ("too old", FIVE, False, 100, {}), ("off", FIVE, False, 5, {"yield_to_wake": False})]:
        p, gcc = plugin(**over)
        w = msg(sender, "x", "佳树", wake=True)
        if before:
            await run(p, w)
        c = msg(FIVE, "555", "红包")
        c.created_at = _time.time() - (0 if before else age)
        c.set_extra("_chime_in", True)
        if not before:
            await run(p, w)
        resp = LLMResponse("收下啦")
        await p.yield_to_newer_wake(c, resp)
        expect(f"no yield: {label}", (resp.completion_text, c.is_stopped()), ("收下啦", False))

    # 接着聊等一等还在路上的表情包，到了一起回一次
    p, _ = plugin()
    st = p._groups[UMO]
    st.partners = {FIVE: _time.time() - 20}
    sticker = msg(FIVE, "555", image=True)
    await p.note_arrival(sticker)  # 到了，前面的插件还在描述它
    money = msg(FIVE, "555", "0.11")
    await p.note_arrival(money)
    money_task = asyncio.create_task(run(p, money))
    await asyncio.sleep(0.4)
    expect("coming: money waits", money_task.done(), False)
    out = await run(p, sticker)
    expect("coming: one reply for both", (await money_task, out[0][0], "0.11 / [图片]" in str(st.follows and
           next(iter(st.follows.values()))["text"])), ([], "LLM", True))
    # 对照：不等
    p, _ = plugin(follow_wait_coming=0.0)
    p._groups[UMO].partners = {FIVE: _time.time() - 20}
    sticker = msg(FIVE, "555", image=True)
    await p.note_arrival(sticker)
    money = msg(FIVE, "555", "0.11")
    await p.note_arrival(money)
    expect("coming off: money answered alone", await run(p, money), [("LLM", "0.11")])
    # 在路上的消息被别的插件拦下了：不再等
    p, _ = plugin()
    p._groups[UMO].partners = {FIVE: _time.time() - 20}
    lost = msg(FIVE, "555", "/help")
    await p.note_arrival(lost)
    lost.stop_event()
    t = _time.time()
    expect("coming stopped: no wait", (await run(p, msg(FIVE, "555", "0.11")), _time.time() - t < 0.4), ([("LLM", "0.11")], True))


asyncio.run(chime_merge_tests())


async def chime_waiting_tests():
    """2026-11-13 妖妖群：她插完一句，兄长大人问“怎么突然回了zsy一句”，三秒后 555 说“这勾八佳树”叫醒她，
    她只回了 555。叫她那次要把兄长大人那句也给她看。"""
    import time as _time
    from astrbot.api.message_components import At, Plain

    sci = importlib.import_module("smart_chime_in.main")
    G, FIVE, BRO, DORA, QUEEN = "222222222", "777777777", "111111111", "444444444", "333333333"
    UMO = f"qq:GroupMessage:{G}"

    def msg(sender, name, text, wake=False, comps=None):
        e = AstrMessageEvent(sender=sender, group=G, text=text, name=name, messages=comps or [Plain(text)])
        e.is_at_or_wake_command = wake
        return e

    def plugin(**over):
        cfg = {"quiet_seconds": 0.02, "follow_quiet_seconds": 0.02, "base_chance": 0.0, "question_bonus": 0.0,
               "topic_bonus": 0.0, "lively_bonus": 0.0, "wake_quiet_seconds": 0.02, "wake_max_wait": 0.2}
        cfg.update(over)
        return sci.SmartChimeIn(Context(), cfg)

    async def run(p, e):
        return [x async for x in p.maybe_chime_in(e)]

    async def scene(p, before):
        """她刚发完一句（插话，回给 555）→ before 里的消息 → 555 叫她 → 叫她那次的系统提示。"""
        st = p._groups[UMO]
        st.reply_end = (_time.time(), FIVE)
        await asyncio.sleep(0.01)
        for e in before:
            await run(p, e)
        w = msg(FIVE, "555", "这勾八佳树", wake=True)
        await run(p, w)
        req = ProviderRequest("SYS")
        await p.wake_catch_up(w, req)
        return req.system_prompt

    sp = await scene(plugin(), [msg(BRO, "林一", "怎么突然回了zsy一句")])
    expect("waiting: brother's question shown when 555 wakes her",
           ("【你上一条之后群里还有】" in sp, "林一（「怎么突然回了zsy一句」）" in sp), (True, True))
    # 不是她上一条之后的第一条、也没和她聊过、也没 @ 她：不算
    sp = await scene(plugin(), [msg(DORA, "哆啦a梦", "原神牛逼"), msg(QUEEN, "来点作用吧", "哈哈")])
    expect("waiting: first message counts, later chatter does not",
           ("哆啦a梦（「原神牛逼」）" in sp, "来点作用吧" in sp), (True, False))
    # @ 了别人的不算；@ 了她的算
    sp = await scene(plugin(), [msg(DORA, "哆啦a梦", "你看这个", comps=[At(qq=QUEEN), Plain("你看这个")]),
                                msg(QUEEN, "来点作用吧", "佳树呢", comps=[At(qq="555555555"), Plain("佳树呢")])])
    expect("waiting: @other skipped, @her kept", ("哆啦a梦" in sp, "来点作用吧（「佳树呢」）" in sp), (False, True))
    # 叫她的人自己的话不重复；关掉开关就没有
    sp = await scene(plugin(), [msg(FIVE, "555", "前面那句")])
    expect("waiting: waker's own lines not repeated", "【你上一条之后群里还有】" in sp, False)
    sp = await scene(plugin(wake_waiting_note=False), [msg(BRO, "林一", "怎么突然回了zsy一句")])
    expect("waiting: off switch", "【你上一条之后群里还有】" in sp, False)
    # 她回之前哆啦a梦刚在说（最后 3 条里有 TA）：之后接着说、没叫她 → 不算（2026-11-18 “讲话”那次）；叫了她就算
    p = plugin()
    await run(p, msg(DORA, "哆啦a梦", "量化我听不懂"))
    await run(p, msg(DORA, "哆啦a梦", "讲话"))
    sp = await scene(p, [msg(DORA, "哆啦a梦", "和他说听不懂了")])
    expect("waiting: someone continuing their own talk is skipped", "哆啦a梦（「和他说听不懂了」）" in sp, False)
    p = plugin()
    await run(p, msg(DORA, "哆啦a梦", "讲话"))
    sp = await scene(p, [msg(DORA, "哆啦a梦", "佳树呢", comps=[At(qq="555555555"), Plain("佳树呢")])])
    expect("waiting: same person but @her is kept", "哆啦a梦（「佳树呢」）" in sp, True)


asyncio.run(chime_waiting_tests())


async def long_post_and_stale_tests():
    """2026-11-13：555 贴几千字更新日志 @全体成员 她插了话；三天前和 555 争“食指”的对话还在群聊上下文里。"""
    import datetime as _dt
    from astrbot.api.message_components import At, Plain

    sci = importlib.import_module("smart_chime_in.main")
    G, FIVE = "222222222", "777777777"

    class Conv:
        async def get_curr_conversation_id(self, umo): return "cid"
        async def get_conversation(self, umo, cid): return object()

    class Ev(AstrMessageEvent):
        session_id = G

        def request_llm(self, **kw):
            return ("LLM", kw.get("prompt"))

    def chime(text, comps=None, **over):
        cfg = {"quiet_seconds": 0.02, "base_chance": 1.0, "max_chance": 1.0}
        cfg.update(over)
        p = sci.SmartChimeIn(Context(), cfg)
        p.context.conversation_manager = Conv()
        e = Ev(sender=FIVE, group=G, text=text, name="555", messages=comps or [Plain(text)])
        e.is_at_or_wake_command = False
        return p, e

    async def run(p, e):
        return [x async for x in p.maybe_chime_in(e)]

    p, e = chime("这个新角色太bt了吧")
    expect("long post: normal line still chimes in", len(await run(p, e)), 1)
    p, e = chime("海斗0.10.0更新日志：" + "修复了一个问题；" * 60)
    expect("long post: wall of text skipped", await run(p, e), [])
    p, e = chime("海克斯本体和拓展包均已更新", comps=[At(qq="all"), Plain("海克斯本体和拓展包均已更新")])
    expect("long post: @全体成员 skipped", await run(p, e), [])
    p, e = chime("海斗0.10.0更新日志：" + "修复了一个问题；" * 60, long_post_chars=0)
    expect("long post: off switch", len(await run(p, e)), 1)

    stale = importlib.import_module("kaju_basics.stale")
    now = _dt.datetime(2026, 11, 13, 14, 2)

    def u(when, text="x"):
        return {"role": "user", "content": [{"type": "text", "text": text},
                                            {"type": "text", "text": f"<system_reminder>Current datetime: {when} (CST)</system_reminder>"}]}

    old = [u("2026-11-10 21:48", "你再看看是食指还是中指"), {"role": "assistant", "content": "佳树看了好几遍了，都是食指呢"},
           u("2026-11-10 21:50"), {"role": "assistant", "content": "确实是食指嘛"}]
    new = [u("2026-11-13 13:50", "海斗更新日志"), {"role": "assistant", "content": "这个看起来像网页端ai实验室呢"}]
    kept, n = stale.trim(old + new, now, 6)
    expect("stale: three-day-old 食指 turns dropped", (kept, n), (new, 4))
    expect("stale: all old -> nothing left", stale.trim(old, now, 6), ([], 4))
    plain = [{"role": "user", "content": "没打时间"}, {"role": "assistant", "content": "嗯"}]
    expect("stale: no stamps -> untouched", stale.trim(plain, now, 6), (plain, 0))
    expect("stale: off (0 hours)", stale.trim(old + new, now, 0), (old + new, 0))

    kb = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {})
    fresh = [u(_dt.datetime.now().strftime("%Y-%m-%d %H:%M")), {"role": "assistant", "content": "刚说的"}]
    req = ProviderRequest("SYS")
    req.contexts = old + fresh
    await kb.drop_stale_history(AstrMessageEvent(group=G, text="这勾八佳树"), req)
    expect("stale hook: group trims", len(req.contexts) <= 2, True)
    req = ProviderRequest("SYS")
    req.contexts = old + fresh
    await kb.drop_stale_history(AstrMessageEvent(text="在吗"), req)
    expect("stale hook: private untouched", len(req.contexts), 6)


asyncio.run(long_post_and_stale_tests())


# 本地模型服务没开就拉起来（kaju_basics ollama.py，2026-11-02）
async def ollama_tests():
    from kaju_basics import ollama

    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    expect("ollama: open port is up", await ollama.is_up("127.0.0.1", port), True)
    server.close()
    await server.wait_closed()
    expect("ollama: closed port is down", await ollama.is_up("127.0.0.1", port, 1.0), False)
    ok, said = await ollama.start(r"D:\no\such\runtime.ps1")
    expect("ollama: missing script", (ok, "找不到" in said), (False, True))
    if os.path.isfile(r"D:\JiashuBot\local_vision\runtime.ps1"):  # 真脚本：已经在跑时 Start 什么都不做，报 running
        ok, said = await ollama.start(r"D:\JiashuBot\local_vision\runtime.ps1")
        expect("ollama: real Start is idempotent", (ok, '"running"' in said), (True, True))


asyncio.run(ollama_tests())


# ------------------------------------------------------------------ prewarm: kaju_basics loads bge-m3
def prewarm_server():
    import http.server
    import threading

    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            hits.append((self.path, json.loads(body or b"{}")))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1], hits


warm_port, warm_hits = prewarm_server()
warm_kb = importlib.import_module("kaju_basics.main").KajuBasics(Context(), {"ollama": {"port": warm_port}})


async def prewarm_tests():
    async def settle():
        await asyncio.sleep(0.5)

    await warm_kb.prewarm_local(AstrMessageEvent(group="1", text="随便聊聊"))
    await settle()
    expect("prewarm: group chatter without calling her does nothing", warm_hits, [])
    await warm_kb.prewarm_local(AstrMessageEvent(text="在吗"))
    await settle()
    expect("prewarm: private message loads bge-m3", warm_hits, [("/api/embed", {"model": "bge-m3", "input": []})])
    await warm_kb.prewarm_local(AstrMessageEvent(text="还在吗"))
    await settle()
    expect("prewarm: at most once a minute", len(warm_hits), 1)
    warm_kb._prewarmed = 0.0
    called = AstrMessageEvent(group="1", text="佳树你看")
    called.is_at_or_wake_command = True
    await warm_kb.prewarm_local(called)
    await settle()
    expect("prewarm: someone calling her in a group", len(warm_hits), 2)
    warm_kb._prewarmed = 0.0
    warm_kb.config["ollama"]["prewarm_embed"] = ""
    await warm_kb.prewarm_local(AstrMessageEvent(text="在吗"))
    await settle()
    expect("prewarm: off when not configured", len(warm_hits), 2)
    expect("prewarm: kaju_style has no writer warm-up", hasattr(importlib.import_module("kaju_style.main").KajuStyle,
                                                                "rewrite_prewarm"), False)


asyncio.run(prewarm_tests())


# ------------------------------------------------------------------ smart_chime_in：冷却完再看一眼（2026-11-09）
async def cooldown_recheck_tests():
    import time as _time
    from astrbot.api.message_components import Plain

    sci = importlib.import_module("smart_chime_in.main")
    G = "222222222"

    class Conv:
        async def get_curr_conversation_id(self, umo): return "cid"
        async def get_conversation(self, umo, cid): return object()

    class Ev(AstrMessageEvent):
        session_id = G

        def request_llm(self, **kw):
            return ("LLM", self.message_str)

    def msg(sender, text):
        return Ev(sender=sender, group=G, text=text, name="哆啦a梦", messages=[Plain(text)])

    def plugin(**kw):
        cfg = {"quiet_seconds": 0.05, "follow_quiet_seconds": 0.05, "base_chance": 1.0, "question_bonus": 0.0,
               "topic_bonus": 0.0, "lively_bonus": 0.0, "cooldown_seconds": 1.0, "follow_enable": False}
        cfg.update(kw)
        p = sci.SmartChimeIn(Context(), cfg)
        p.context.conversation_manager = Conv()
        p._score = lambda window, n: (1.0, "test")
        return p

    async def run(p, e):
        return [x async for x in p.maybe_chime_in(e)]

    # 冷却中来的话：冷却完、没新消息、她没再说话 → 再照常决定（这里一定说）
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.last_spoke = _time.time() - 0.5
    t0 = _time.time()
    expect("cooldown recheck: decides after cooldown", await run(p, msg("444444444", "说的就是你，去看看卡")),
           [("LLM", "说的就是你，去看看卡")])
    expect("cooldown recheck: waited", _time.time() - t0 >= 0.45, True)
    # 冷却期间又来了新消息 → 这条不再看（交给新的那条）
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.last_spoke = _time.time() - 0.3
    first = asyncio.ensure_future(run(p, msg("444444444", "第一句")))
    await asyncio.sleep(0.3)
    second = await run(p, msg("444444444", "第二句"))
    expect("cooldown recheck: newer message takes over", (await first, second), ([], [("LLM", "第二句")]))
    # 冷却期间她被叫到说了话 → 不再看
    p = plugin()
    st = p._groups[f"qq:GroupMessage:{G}"]
    st.last_spoke = _time.time() - 0.3
    first = asyncio.ensure_future(run(p, msg("444444444", "第一句")))
    await asyncio.sleep(0.2)
    st.last_spoke = _time.time()
    expect("cooldown recheck: she spoke meanwhile", await first, [])
    # 关掉 / 冷却剩得太多 → 和以前一样直接不插话
    p = plugin(cooldown_recheck=False)
    p._groups[f"qq:GroupMessage:{G}"].last_spoke = _time.time()
    expect("cooldown recheck off", await run(p, msg("444444444", "x")), [])
    p = plugin(cooldown_seconds=100.0, cooldown_recheck_max=5.0)
    p._groups[f"qq:GroupMessage:{G}"].last_spoke = _time.time()
    t0 = _time.time()
    expect("cooldown too long: no wait", (await run(p, msg("444444444", "x")), _time.time() - t0 < 1), ([], True))


asyncio.run(cooldown_recheck_tests())


# ------------------------------------------------------------------ 2026-11-19 答应去查，补做超时后什么都没发
async def follow_up_router_tests():
    from types import SimpleNamespace

    ft = importlib.import_module("follow_through.main")
    search = next(a for a in ft.ACTIONS if a.key == "search")
    for text in ("好的李四学长，佳树这就一起看！", "好的兄长大人，佳树这就去看Hoody那个！",
                 "佳树这就去查查主机版的配置要求！", "答应：去帮他查看 hoody.com"):
        expect(f"promise: {text}", bool(search.promise.search(text)), True)

    class Router:
        def __init__(self, pids): self.pids = pids
        def on(self): return True
        def order(self, want): return [{"pid": p} for p in self.pids]

    ctx = Context()
    ctx.stars = [SimpleNamespace(star_cls=SimpleNamespace(_router=Router(["slow", "fast", "c", "d"])))]
    tried = []

    async def get_pid(umo): return "default"

    async def agent(**kw):
        tried.append(kw["chat_provider_id"])
        if kw["chat_provider_id"] == "slow":
            await asyncio.sleep(5)
        return SimpleNamespace(completion_text="查到了：PS5 Pro 约等于 RTX 5060 Ti")

    ctx.get_current_chat_provider_id = get_pid
    ctx.tool_loop_agent = agent
    p = ft.FollowThrough(ctx, {"attempt_seconds": 0.2, "timeout_seconds": 30})
    expect("router order read", p._router_order(), ["slow", "fast", "c", "d"])
    ev = AstrMessageEvent(text="x")
    snap = {"contexts": [], "prompt": "", "system_prompt": ""}
    out = await p._run_agent(ev, snap, "这就去查", "补做", None)
    expect("slow provider skipped, next answers", (out, tried), ("查到了：PS5 Pro 约等于 RTX 5060 Ti", ["slow", "fast"]))

    # 没有挑模型：用默认模型；全超时 → TimeoutError
    ctx.stars = []
    tried.clear()

    async def stuck(**kw):
        tried.append(kw["chat_provider_id"])
        await asyncio.sleep(5)

    ctx.tool_loop_agent = stuck
    try:
        await p._run_agent(ev, snap, "这就去查", "补做", None)
        got = "no error"
    except asyncio.TimeoutError:
        got = "timeout"
    expect("no router: default provider, timeout raised", (got, tried), ("timeout", ["default"]))


asyncio.run(follow_up_router_tests())

# ------------------------------------------------------------------ 2026-11-19 只引用 + @、没写字 → "<attachment>"
def quote_only_tests():
    from astrbot.api.message_components import At, Reply

    ab = importlib.import_module("address_book.main")
    ev = AstrMessageEvent(text="", group="222222222")
    ev.get_self_id = lambda: "555555555"
    ev.get_messages = lambda: [Reply(sender_id="444444444", sender_nickname="哆啦a梦", message_str="什么配置能玩"),
                               At(qq="555555555")]
    expect("quote + @ me, no words", ab.quote_only_text(ev), "（这条没写字，只引用了哆啦a梦的“什么配置能玩”，还 @ 了佳树）")
    ev.get_messages = lambda: [Reply(sender_id="555555555", sender_nickname="佳树", message_str="")]
    expect("quote of her own, empty text", ab.quote_only_text(ev), "（这条没写字，只引用了佳树自己的那条）")
    ev.get_messages = lambda: [At(qq="555555555")]
    expect("no quote: nothing", ab.quote_only_text(ev), "")


quote_only_tests()

print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
