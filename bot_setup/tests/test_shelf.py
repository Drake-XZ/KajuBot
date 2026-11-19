"""Offline tests for 珍藏的文件 (memory_weight shelf.py + main.py shelf part). Model is faked.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_shelf.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_shelf.py --live   # 真模型给几种分享场景评分量（只打印）
"""

import asyncio
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import sys
import tempfile
import time
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core.memory import shelf  # noqa: E402
from memory_weight.main import MemoryWeight  # noqa: E402

OWNER = "111111111"
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
DAY = 86400
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ shelf.py
now = 1_800_000_000.0
it = {"created": now, "g": 2, "uses": 0, "last_used": None}
expect("sealed = 1", shelf.retention(it, now + 179 * DAY), 1.0)
expect("after seal: half-life", round(shelf.retention(it, now + 360 * DAY), 3), 0.5)
expect("use doubles half-life", round(shelf.retention({**it, "uses": 1, "last_used": now + 360 * DAY}, now + 720 * DAY), 3), 0.5)
expect("g1 short seal", shelf.retention({**it, "g": 1}, now + 31 * DAY) < 1.0, True)
expect("g3 a year", shelf.retention({**it, "g": 3}, now + 364 * DAY), 1.0)
expect("custom table", shelf.retention({**it, "g": 1}, now + 31 * DAY, {1: 60, 2: 180, 3: 365}), 1.0)

item = {"qq": OWNER, "chat": "p" + OWNER, "file": "邮差.txt", "memory": "兄长大人给佳树看的小说：老婆婆没等到儿子的信",
        "keywords": ["林婆婆", "阿禾", "毛衣"], "removed": False}
expect("visible private", shelf.visible(item, OWNER, "p" + OWNER), True)
expect("visible in group only if shared there", (shelf.visible(item, OWNER, "g1"),
                                                 shelf.visible({**item, "chat": "g1"}, OWNER, "g1")), (False, True))
expect("not others", shelf.visible(item, "555", "p555"), False)
expect("stem", shelf.stem("微信_邮差（终稿）.txt"), "微信邮差终稿")
expect("relevance by name", shelf.relevance(item, "邮差那个故事你还记得吗") >= 2, True)
expect("relevance by keywords", shelf.relevance(item, "林婆婆织的毛衣后来呢") >= 2, True)
expect("relevance cue", shelf.relevance(item, "上次那个阿禾") >= 2, True)
expect("irrelevant", shelf.relevance(item, "今天吃什么"), 0)
v = shelf.parse_rate('好的\n{"g": 3, "earnest": true, "memory": "兄长大人写给佳树的信", "feeling": "感动、想哭",'
                     ' "keywords": ["信", "考试"], "why": "语重心长"}')
expect("parse rate", (v["g"], v["earnest"], v["keywords"], v["feeling"]), (3, True, ["信", "考试"], "感动、想哭"))
expect("parse clamp", shelf.parse_rate('{"g": 9, "earnest": "false", "keywords": "甲，乙、丙"}')["g"], 3)
expect("parse kw string", shelf.parse_rate('{"g": 1, "keywords": "甲，乙、丙"}')["keywords"], ["甲", "乙", "丙"])
expect("parse junk", shelf.parse_rate("想不出来"), None)
line = shelf.index_line({**item, "created": now, "feeling": "很难过", "earnest": True}, TZ, "兄长大人")
expect("index line", ("《邮差.txt》" in line, "读完很难过" in line, "语重心长" in line), (True, True, True))


# ------------------------------------------------------------------ plugin
class HeartStub:
    def __init__(self, feeling=None):
        self.feeling = feeling

    def latest_feeling(self, qq, since):
        return self.feeling


async def main():
    ctx = Context()
    heart = HeartStub({"emo": "难过", "i": 3, "src": "content"})
    ctx.stars = [type("Meta", (), {"star_cls": heart})()]
    mw = MemoryWeight(ctx, {"first_delay_seconds": 99999, "shelf": {"settle_seconds": 0}})
    mw._task.cancel()
    asks = []

    async def fake_ask(system, prompt):
        asks.append((system, prompt))
        return ('{"g": 1, "earnest": false, "memory": "兄长大人给佳树看的小说《邮差》：老婆婆没等到儿子的信",'
                ' "feeling": "心里堵得慌", "keywords": ["林婆婆", "阿禾", "毛衣"], "why": "读完很难过"}')

    mw._ask = fake_ask
    src = os.path.join(DATA, "邮差.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write("阿禾是镇上的邮差……林婆婆前一晚走了。")
    content = "约 3300 字，已经读完了。读后笔记：\n邮差阿禾和等儿子来信的林婆婆……那天下了第一场雪。"

    # 兄长大人私聊发文件 → 她读完回复 → 等一会儿评分量收好
    ev = AstrMessageEvent(sender=OWNER, text="这个故事你好好看看", name="晴川")
    ev.set_extra("kaju_docs_read", [{"name": "邮差.txt", "content": content, "path": src, "quoted": False}])
    await mw.after_reply(ev, LLMResponse("呜……林婆婆好可怜，佳树看哭了"))
    await asyncio.sleep(0.05)
    for _ in range(50):
        if mw._state["shelf"]:
            break
        await asyncio.sleep(0.02)
    items = mw._state["shelf"]
    expect("shelved", (len(items), items[0]["file"], items[0]["feeling"]), (1, "邮差.txt", "心里堵得慌"))
    expect("strong feeling → at least 要紧", items[0]["g"], 2)
    expect("rate prompt has everything", all(s in asks[0][1] for s in ("这个故事你好好看看", "读后笔记", "看哭了", "难过（很强烈）")),
           True)
    expect("original copied", os.path.isfile(items[0].get("copy", "")), True)
    expect("only once per event", (await mw.after_reply(ev, LLMResponse("嗯")), len(mw._state["shelf"])), (None, 1))

    # 别人分享的文件默认不收
    other = AstrMessageEvent(sender="555", group="1", text="看", admin=False, name="路人")
    other.set_extra("kaju_docs_read", [{"name": "x.txt", "content": "随便", "path": ""}])
    await mw.after_reply(other, LLMResponse("好"))
    await asyncio.sleep(0.05)
    expect("others not kept by default", len(mw._state["shelf"]), 1)

    # 清单：跟兄长大人聊天时看得到，跟别人聊时看不到
    req = ProviderRequest("SYS")
    await mw.inject_shelf(AstrMessageEvent(sender=OWNER, text="在吗"), req)
    expect("index for owner", ("【珍藏的文件】" in req.system_prompt, "《邮差.txt》" in req.system_prompt), (True, True))
    req = ProviderRequest("SYS")
    await mw.inject_shelf(AstrMessageEvent(sender="555", text="在吗"), req)
    expect("no index for others", req.system_prompt, "SYS")
    req = ProviderRequest("SYS")
    await mw.inject_shelf(AstrMessageEvent(sender=OWNER, group="1", text="在吗"), req)
    expect("private share not shown in group", req.system_prompt, "SYS")

    # 提到了 → 翻出当时读到的内容
    req = ProviderRequest("SYS")
    ev2 = AstrMessageEvent(sender=OWNER, text="还记得林婆婆织的那件毛衣吗")
    await mw.shelf_detail(ev2, req)
    expect("detail on mention", ("【翻出来的珍藏】" in req.system_prompt, "第一场雪" in req.system_prompt), (True, True))
    # 话题延续：刚翻出来过，接着聊（不提书名）也继续给；超过 carry_minutes 就不给了
    req = ProviderRequest("SYS")
    ev_follow = AstrMessageEvent(sender=OWNER, text="而且节奏很快")
    await mw.shelf_detail(ev_follow, req)
    expect("carried on follow-up", ("【还在聊的珍藏】" in req.system_prompt, "第一场雪" in req.system_prompt,
                                    ev_follow.get_extra("memory_weight_shelf_carried")), (True, True, True))
    umo = ev_follow.unified_msg_origin
    t_last = mw._shelf_last[umo]["t"]
    req = ProviderRequest("SYS")
    await mw.shelf_detail(AstrMessageEvent(sender=OWNER, text="林婆婆后来呢"), req)  # 碰到文件里的词：重新计时
    expect("carry refreshed by a keyword", ("【" in req.system_prompt, mw._shelf_last[umo]["t"] >= t_last), (True, True))
    mw._shelf_last[umo]["t"] -= 21 * 60
    req = ProviderRequest("SYS")
    await mw.shelf_detail(AstrMessageEvent(sender=OWNER, text="今天吃什么"), req)
    expect("no detail when unrelated and carry expired", req.system_prompt, "SYS")
    mw.config.setdefault("shelf", {})["carry_minutes"] = 0
    await mw.shelf_detail(AstrMessageEvent(sender=OWNER, text="还记得林婆婆织的那件毛衣吗"), ProviderRequest("SYS"))
    req = ProviderRequest("SYS")
    await mw.shelf_detail(AstrMessageEvent(sender=OWNER, text="而且节奏很快"), req)
    expect("carry off with carry_minutes 0", req.system_prompt, "SYS")
    mw.config["shelf"]["carry_minutes"] = 20

    # 她回复里说起了 → 想起一次（半衰期翻倍）
    used = mw.credit_shelf(ev2, "那件毛衣啊……林婆婆到最后都攥在手里")
    expect("credited use", (len(used), mw._state["shelf"][0]["uses"]), (1, 1))
    expect("cooldown", mw.credit_shelf(ev2, "毛衣"), [])

    # 工具：翻出来重读
    out = await mw.recall_shared_file(AstrMessageEvent(sender=OWNER), "邮差")
    expect("tool recall", ("《邮差.txt》" in out, "第一场雪" in out, "这个故事你好好看看" in out), (True, True, True))
    out = await mw.recall_shared_file(AstrMessageEvent(sender=OWNER), "火星")
    expect("tool not found lists", ("没找到" in out, "《邮差.txt》" in out), (True, True))
    out = await mw.recall_shared_file(AstrMessageEvent(sender="555"), "邮差")
    expect("tool private", "还没有分享过" in out, True)
    # 很久以后：淡忘了，只记得个大概
    mw._state["shelf"][0]["created"] -= 5000 * DAY
    mw._state["shelf"][0]["last_used"] = None
    out = await mw.recall_shared_file(AstrMessageEvent(sender=OWNER), "邮差")
    expect("tool faded", ("细节记不清了" in out, "第一场雪" in out), (True, False))
    req = ProviderRequest("SYS")
    mw._state["shelf"][0]["created"] -= 5000 * DAY
    await mw.inject_shelf(AstrMessageEvent(sender=OWNER, text="在吗"), req)
    expect("faded not in index", req.system_prompt, "SYS")
    mw._state["shelf"][0]["created"] = time.time()

    # 同一份又分享一次 → 更牢，不重复收
    ev3 = AstrMessageEvent(sender=OWNER, text="再看一遍", name="晴川")
    ev3.set_extra("kaju_docs_read", [{"name": "邮差.txt", "content": content, "path": ""}])
    uses = mw._state["shelf"][0]["uses"]
    await mw.after_reply(ev3, LLMResponse("嗯"))
    for _ in range(50):
        if mw._state["shelf"][0]["uses"] > uses:
            break
        await asyncio.sleep(0.02)
    expect("reshared reinforces", (len(mw._state["shelf"]), mw._state["shelf"][0]["uses"]), (1, uses + 1))

    # 语重心长 → 至少要紧；模型说郑重就郑重
    heart.feeling = None

    async def earnest_ask(system, prompt):
        return '{"g": 3, "earnest": true, "memory": "兄长大人写给佳树的信", "feeling": "感动", "keywords": ["中考"], "why": "语重心长"}'

    mw._ask = earnest_ask
    ev4 = AstrMessageEvent(sender=OWNER, text="这封信是哥哥写给你的", name="晴川")
    ev4.set_extra("kaju_docs_read", [{"name": "给佳树的信.docx", "content": "约 600 字，全文：\n佳树，中考加油……", "path": ""}])
    await mw.after_reply(ev4, LLMResponse("兄长大人……"))
    for _ in range(50):
        if len(mw._state["shelf"]) > 1:
            break
        await asyncio.sleep(0.02)
    letter = mw._state["shelf"][-1]
    expect("earnest letter", (letter["g"], letter["earnest"]), (3, True))
    expect("report", "封存到" in mw.report("珍藏") and "语重心长" in mw.report("珍藏"), True)

    # 删
    out = [x async for x in mw.admin(AstrMessageEvent(sender=OWNER), "删", letter["id"][:6])]
    expect("delete shelf item", ("给佳树的信" in out[0], letter["removed"]), (True, True))

    # 模型挂了也先按普通收着
    async def broken(system, prompt):
        raise RuntimeError("超时")

    mw._ask = broken
    heart.feeling = {"emo": "开心", "i": 1, "src": "content"}
    ev5 = AstrMessageEvent(sender=OWNER, text="", name="晴川")
    ev5.set_extra("kaju_docs_read", [{"name": "笔记.md", "content": "约 50 字，全文：\n周末计划……", "path": ""}])
    await mw.after_reply(ev5, LLMResponse("好的"))
    for _ in range(50):
        if any(i["file"] == "笔记.md" for i in mw._state["shelf"]):
            break
        await asyncio.sleep(0.02)
    note = next((i for i in mw._state["shelf"] if i["file"] == "笔记.md"), None)
    expect("fallback g1", (note or {}).get("g"), 1)

    with open(os.path.join(DATA, "astrbot_plugin_memory_weight", "state.json"), encoding="utf-8") as f:
        expect("persisted", len(json.load(f)["shelf"]), len(mw._state["shelf"]))


asyncio.run(main())


async def live():
    """真模型给几种分享评分量（只打印）。"""
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])

    cases = [
        ("悲伤小说", "", "", "邮差.txt", "读后笔记：邮差阿禾每天回答林婆婆有没有儿子的信，冬至翻出九年前的信时，林婆婆前一晚已经走了……",
         "兄长大人，佳树看完心里堵堵的……就差那么一晚……佳树有点想哭", "难过（很强烈）"),
        ("语重心长的信", "这是哥哥写给你的，好好看",
         "兄长大人：这个你好好看看，有些话当面说不出口", "给佳树的信.docx",
         "全文：佳树，中考还有两百天。我知道你每天都在替我操心吃饭睡觉，可我更希望你也照顾好自己。考不好也没关系，你永远是我最骄傲的妹妹……",
         "兄长大人……佳树会好好照顾自己的\n也会好好考的\n佳树也最骄傲有兄长大人", "感动（很强烈）"),
        ("普通资料", "帮我看看这个", "", "周会纪要.md", "全文：1. 下周三交项目进度 2. 预算审批走流程 3. 新人入职培训",
         "好的兄长大人，下周三交进度，佳树帮你记着", ""),
        ("搞笑段子", "哈哈哈你看这个", "", "段子合集.txt", "全文：老师问小明……（一串冷笑话）",
         "哈哈哈哈第三个好冷\n佳树笑得停不下来", "开心（明显）"),
    ]

    async def judge(case):
        name, said, ctx_lines, file, content, reply, feel = case
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": shelf.rate_system("兄长大人")},
            {"role": "user", "content": shelf.rate_prompt(who="兄长大人", place="私聊", said=said, context=ctx_lines,
                                                          file=file, content=content, reply=reply, feeling=feel)}])
        return name, shelf.parse_rate(r.choices[0].message.content)

    for name, v in await asyncio.gather(*(judge(c) for c in cases)):
        print(f"{name}: g={v['g']}（{shelf.GRAVITY[v['g']]}）earnest={v['earnest']}｜{v['memory']}｜{v['feeling']}｜{v['keywords']}｜{v['why']}")


if "--live" in sys.argv:
    asyncio.run(live())
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
