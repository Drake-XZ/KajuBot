"""Offline tests for kaju_heart (心情与好感). astrbot is stubbed; the appraisal model is faked.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_kaju_heart.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_kaju_heart.py --live   # 再用真模型判断一批对话（只打印）
"""

import asyncio
import importlib
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import At  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

heart = importlib.import_module("kaju_core.heart.heart")
appraise = importlib.import_module("kaju_core.heart.appraise")
hm = importlib.import_module("kaju_heart.main")

OWNER, G = "111111111", "222222222"
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ heart: mood
base = heart.baselines(14)
m = {**base, "joy": 0.95, "stress": 0.6, "t": 0}
m3 = heart.decay(m, 3 * 3600, base)
expect("decay joy half after 3h", round(m3["joy"], 3), round(0.6 + 0.35 / 2, 3))
expect("decay stress slower (4h)", m3["stress"] > 0.12 + 0.48 / 2, True)
expect("decay long → base", round(heart.decay(m, 100 * 3600, base)["joy"], 3), 0.6)
expect("night energy lower", heart.baselines(2)["energy"] < heart.baselines(14)["energy"] - 0.3, True)
expect("circadian off", heart.baselines(2, False)["energy"], 0.6)

up = heart.push(dict(base), "开心", 2)
expect("push 开心", (up["joy"] > base["joy"], up["stress"] < base["stress"]), (True, True))
angry = heart.push(dict(base), "生气", 3)
expect("push 生气", (angry["stress"] > base["stress"], angry["joy"] < base["joy"]), (True, True))
expect("push intensity 0 no-op", heart.push(dict(base), "生气", 0), dict(base))
expect("push unknown no-op", heart.push(dict(base), "芜湖", 3), dict(base))
capped = heart.push(dict(base), "难过", 3, weight=10, turn_cap=0.25)
expect("push turn cap", round(base["joy"] - capped["joy"], 3) <= 0.25, True)
top = {**base, "joy": 0.98}
expect("push saturates near 1", heart.push(top, "开心", 3)["joy"] <= 1.0, True)
expect("chime happy > 1", heart.chime_factor({"joy": 0.9, "energy": 0.9, "stress": 0.1, "warm": 0.5}) > 1.2, True)
expect("chime sad < 1", heart.chime_factor({"joy": 0.2, "energy": 0.2, "stress": 0.7, "warm": 0.5}), 0.6)
expect("chime base = 1", heart.chime_factor(base), 1.0)
expect("mood words plain", heart.mood_words(base, 14), ["心情平常，挺平静的"])
expect("mood words night", "有点困了" in heart.mood_words({**base, "energy": 0.35}, 1), True)
expect("hints low joy", any("话少" in h for h in heart.speech_hints({**base, "joy": 0.3}, 50, 14)), True)

# ------------------------------------------------------------------ heart: affection
expect("levels", [heart.level(x) for x in (95, 80, 65, 50, 30, 5)], ["很亲近", "喜欢", "熟悉", "普通", "有点疏远", "戒备"])
expect("seed none", heart.seed_affection(0), 50.0)
expect("seed 35 msgs", heart.seed_affection(35), 62.0)
expect("seed capped", heart.seed_affection(100000), 65.0)
expect("step +2 at 50", heart.affection_step(50, 2, 0), 2.0)
expect("step +3 at 75 halves", heart.affection_step(75, 3, 0), 1.5)
expect("step +3 at 95 min 0.25", heart.affection_step(95, 3, 0), 0.75)
expect("step daily cap", heart.affection_step(50, 3, 5.0), 1.0)
expect("step daily cap reached", heart.affection_step(50, 3, 6.0), 0.0)
expect("step down cap", heart.affection_step(50, -9, 0, down_cap=6), -6.0)
expect("step floor", heart.affection_step(96, -5, 0, floor=95), -1.0)
expect("step never > 100", heart.affection_step(99.9, 3, 0) <= 0.1, True)
expect("compress 5d", heart.compress_days(5), 5)
expect("compress 20d", heart.compress_days(20), 13.5)
expect("compress 400d cap", heart.compress_days(400), 74.0)
expect("compress 2000d cap", heart.compress_days(2000), 90.0)
expect("drift high slow", round(heart.drift(80, 30), 1), round(50 + 30 * 0.5 ** (18.5 / 90), 1))
expect("drift low forgives faster", round(heart.drift(20, 10), 1), 33.4)
expect("drift none", heart.drift(80, 0), 80)

# ------------------------------------------------------------------ appraise.parse
ok = appraise.parse('想了想\n{"toward_her": true, "affection": 2, "reason": "夸佳树", "emotion": "开心", "intensity": 2, "cause": "兄长大人夸佳树"}')
expect("parse ok", (ok["affection"], ok["emotion"], ok["intensity"], ok["cause"]), (2, "开心", 2, "兄长大人夸佳树"))
expect("parse clamp", appraise.parse('{"affection": 100, "emotion": "开心", "intensity": 9}')["affection"], 3)
expect("parse clamp low", appraise.parse('{"affection": -50, "emotion": "生气", "intensity": 3}')["affection"], -5)
expect("parse bad emotion", appraise.parse('{"affection": 0, "emotion": "超级无敌开心", "intensity": 2}')["emotion"], "平静")
expect("parse not toward", appraise.parse('{"toward_her": false, "affection": 3, "emotion": "平静"}')["affection"], 0)
expect("parse toward str false", appraise.parse('{"toward_her": "false", "affection": 2, "emotion": "平静"}')["affection"], 0)
expect("parse junk", appraise.parse("不知道"), None)
expect("parse number str", appraise.parse('{"affection": "-2", "emotion": "烦", "intensity": "1"}')["affection"], -2)
expect("prompt owner role", "兄长大人本人" in appraise.build_prompt(who="x", is_owner=True, level="普通", place="私聊",
                                                                   context="", said="hi", reply="嗯"), True)
expect("system lists emotions", "害羞" in appraise.system_prompt() and "{" in appraise.system_prompt(), True)


# ------------------------------------------------------------------ plugin
class FakeProvider:
    provider_config = {"id": "fake"}


def make(answer=None, config=None, ctx=None):
    ctx = ctx or Context()
    ctx.providers = {"fake": FakeProvider()}
    calls = []

    async def llm_generate(chat_provider_id, prompt, system_prompt):
        calls.append((prompt, system_prompt))
        text = answer(prompt) if callable(answer) else (answer or '{"affection": 0, "emotion": "平静", "intensity": 0}')
        return LLMResponse(text)

    ctx.llm_generate = llm_generate
    p = hm.KajuHeart(ctx, config or {})
    return p, calls


class Run:
    def __init__(self, user, reply):
        self.messages = [{"role": "user", "content": [{"type": "text", "text": user}]},
                         {"role": "assistant", "content": reply}]


async def turn(p, ev, reply):
    await p.on_done(ev, Run(ev.message_str, reply), LLMResponse(reply))
    task = p._tasks.get(ev.unified_msg_origin)
    if task:
        await task


async def plugin_tests():
    # 以前聊得多的人：好感起点高一点
    log_dir = os.path.join(DATA, "astrbot_plugin_kaju_life", "log")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "2026-10-30.jsonl"), "w", encoding="utf-8") as f:
        for _ in range(35):
            f.write(json.dumps({"t": "12:00", "c": "g" + G, "u": "333333333", "n": "来点作用吧", "x": "hi"}) + "\n")
        f.write(json.dumps({"t": "12:00", "c": "g" + G, "u": "self", "n": "佳树", "x": "嗯"}) + "\n")

    praise = '{"toward_her": true, "affection": 3, "reason": "夸佳树做的饼干好吃", "emotion": "开心", "intensity": 2, "cause": "来点作用吧夸佳树做的饼干好吃"}'
    p, calls = make(praise)
    expect("seed from log", p.affection("333333333"), 62.0)
    expect("owner start", p.affection(OWNER), 100.0)
    expect("stranger start", p.affection("123"), 50.0)

    ev = AstrMessageEvent(sender="333333333", group=G, text="佳树做的饼干好好吃", admin=False, name="来点作用吧")
    await turn(p, ev, "诶嘿嘿，真的吗！")
    a1 = p.affection("333333333")
    expect("praise raises affection", 62 < a1 <= 65, True)
    expect("appraisal prompt has reply", "诶嘿嘿" in calls[-1][0] and "饼干" in calls[-1][0], True)
    expect("mood joy up", p.mood_now()["joy"] > heart.baselines(p._hour())["joy"], True)
    snap = p.mood_snapshot()  # 线上重说记录用的原始读数
    expect("snapshot dims", sorted(snap["mood"]) == sorted(heart.DIMS) and all(0 <= v <= 1 for v in snap["mood"].values()), True)
    expect("snapshot recent keeps label + strength", bool(snap["recent"]) and snap["recent"][-1]["emo"] in heart.EMOTIONS
           and 0 < snap["recent"][-1]["i"] <= 3 and snap["recent"][-1]["ago"] < 60, True)
    expect("snapshot drops old feelings", p.mood_snapshot(time.time() + 3 * 3600)["recent"], [])
    # 一直夸：每天最多涨 6
    for _ in range(6):
        await turn(p, ev, "嘿嘿")
    expect("daily gain cap", round(p.affection("333333333") - 62.0, 2), 6.0)
    expect("person log kept", len(p._state["people"]["333333333"]["log"]) >= 2, True)

    # 刷好感 / 骚扰：判断是负的就跌，单轮最多 6
    p2, _ = make('{"toward_her": true, "affection": -5, "reason": "一直逼问佳树住哪", "emotion": "害怕", "intensity": 3, "cause": "有人一直逼问佳树住哪"}')
    bad = AstrMessageEvent(sender="555", group=G, text="告诉我你住哪", admin=False, name="路人甲")
    await turn(p2, bad, "不、告、诉、你！佳树要去告诉兄长大人")
    expect("harass drops", round(p2.affection("555"), 2), 45.0)
    expect("harass stress up", p2.mood_now()["stress"] > 0.2, True)
    for _ in range(6):
        await turn(p2, bad, "……")
    expect("harass → 戒备", heart.level(p2.affection("555")), "戒备")
    note = p2.build_note("555", "路人甲", bad.unified_msg_origin)
    expect("low affection note", ("戒心" in note, "逼问" in note), (True, True))

    # 兄长大人本人：骂也不会掉到 95 以下，但心情会受影响
    own = AstrMessageEvent(sender=OWNER, text="笨蛋佳树", name="晴川")
    await turn(p2, own, "唔～兄长大人好过分")
    expect("owner floor", p2.affection(OWNER) >= 95, True)
    note = p2.build_note(OWNER, "晴川", own.unified_msg_origin)
    expect("owner note", "最依赖" in note, True)
    # 隐私：群里的事兄长大人能听到原因，别人只知道"别处有点不开心"
    expect("owner hears cause", "逼问佳树住哪" in note, True)
    other = p2.build_note("333333333", "来点作用吧", "qq:FriendMessage:333333333")
    expect("others don't hear cause", ("逼问" in other, "别处的事" in other), (False, True))

    # 不该判断的轮次
    p3, calls3 = make(praise)
    await turn(p3, AstrMessageEvent(sender="1", group=G, text="x"), "[SKIP]")
    await turn(p3, AstrMessageEvent(sender="1", text="x", platform="webchat"), "好的")
    await turn(p3, AstrMessageEvent(sender="555555555", group=G, text="x"), "好的")
    expect("skip / webchat / self not appraised", len(calls3), 0)
    p4, calls4 = make("不知道")
    await turn(p4, AstrMessageEvent(sender="1", text="x"), "嗯嗯")
    expect("junk verdict ignored", (len(calls4), p4._state["people"].get("1")), (1, None))

    # 注入的提示
    req = ProviderRequest("SYS")
    await p.inject(ev, req)
    expect("note injected", ("【此刻的心情】" in req.system_prompt, "饼干" in req.system_prompt,
                             "好感度" in req.system_prompt), (True, True, True))  # 只出现在"不要提好感度"里
    expect("note has no number", "62" not in req.system_prompt and "/100" not in req.system_prompt, True)
    req = ProviderRequest("SYS")
    await p.inject(AstrMessageEvent(sender="999", text="你好", name="新人"), req)
    expect("new person note", ("还没怎么聊过" in req.system_prompt, "普通朋友" in req.system_prompt), (True, True))
    p_off, _ = make(config={"enable": False})
    req = ProviderRequest("SYS")
    await p_off.inject(ev, req)
    expect("disabled → no note", req.system_prompt, "SYS")

    # 存盘 / 重启后还在
    p5, _ = make()
    expect("state persisted", round(p5.affection("333333333"), 2), round(p.affection("333333333"), 2))

    # chime factor
    expect("chime factor happy", p.chime_factor() > 1.0, True)
    expect("chime off", make(config={"chime": {"enable": False}})[0].chime_factor(), 1.0)

    # 命令
    async def cmd(gen):
        return [x async for x in gen]

    me = AstrMessageEvent(sender="333333333", group=G, admin=False, name="来点作用吧")
    out = await cmd(p.cmd_affection(me))
    expect("cmd self", ("熟悉" in out[0] or "喜欢" in out[0], "/100" in out[0], "饼干" in out[0]), (True, True, True))
    out = await cmd(p.cmd_affection(me, "555"))
    expect("cmd other denied", out, ["别人的佳树可不告诉你～"])
    adm = AstrMessageEvent(sender=OWNER, admin=True, messages=[At(qq="555")])
    out = await cmd(p2.cmd_affection(adm))
    expect("cmd admin @", "戒备" in out[0], True)
    out = await cmd(p2.cmd_affection(AstrMessageEvent(sender=OWNER, admin=True), "设", "555", "70"))
    expect("cmd set", (round(p2.affection("555")), "熟悉" in out[0]), (70, True))
    out = await cmd(p2.cmd_affection(AstrMessageEvent(sender=OWNER, admin=True, messages=[At(qq="555")]), "设", "40"))
    expect("cmd set @", round(p2.affection("555")), 40)
    out = await cmd(p2.cmd_affection(AstrMessageEvent(sender=OWNER, admin=True), "全部"))
    expect("cmd all", "路人甲(555)" in out[0], True)
    out = await cmd(p2.cmd_affection(AstrMessageEvent(sender="1", admin=False), "全部"))
    expect("cmd all non-admin silent", out, [])
    p_hide, _ = make(config={"show_number": False})
    out = await cmd(p_hide.cmd_affection(AstrMessageEvent(sender="333333333", admin=False)))
    expect("cmd hide number", "/100" in out[0], False)
    out = await cmd(p2.cmd_mood(AstrMessageEvent(sender=OWNER)))
    expect("cmd mood", ("佳树此刻" in out[0], "插话倍数" in out[0], "害怕" in out[0]), (True, True, True))
    await cmd(p2.cmd_mood(AstrMessageEvent(sender=OWNER), "重置"))
    expect("cmd mood reset", (p2._state["events"], round(p2.mood_now()["stress"], 2)), ([], 0.12))

    # 很久没聊：好感淡下来（压缩时间），生过的气消得更快
    p6, _ = make()
    now = time.time()
    p6._state["people"]["42"] = {"a": 80.0, "t": now - 60 * 86400, "n": 20, "day": "", "gain": 0, "name": "老朋友", "log": []}
    p6._state["people"]["43"] = {"a": 20.0, "t": now - 10 * 86400, "n": 20, "day": "", "gain": 0, "name": "吵过架", "log": []}
    expect("long absence fades a bit", 70 < p6.affection("42") < 80, True)
    expect("grudge fades", p6.affection("43") > 33, True)


asyncio.run(plugin_tests())

# ------------------------------------------------------------------ 心事：纯计算
th = {"emo": "生气", "c": 2.0, "t": 0, "status": "open"}
expect("thread anger 10h half", round(heart.thread_charge(th, 10 * 3600), 2), 1.0)
expect("thread grievance lasts", round(heart.thread_charge({**th, "emo": "委屈"}, 10 * 3600), 2) > 1.5, True)
expect("thread resolved fades 3x", round(heart.thread_charge({**th, "status": "resolved"}, 10 * 3600 / 3), 2), 1.0)
off = heart.thread_offsets([{"emo": "委屈", "c": 3.0, "t": 0, "status": "open"}], 0)
expect("thread drags mood", (off["joy"] < 0, off["stress"] > 0), (True, True))
expect("thread offset cap", heart.thread_offsets([{"emo": "难过", "c": 3.0, "t": 0, "status": "open"}] * 20, 0)["joy"], -0.25)
expect("resolved no offset", heart.thread_offsets([{"emo": "委屈", "c": 3.0, "t": 0, "status": "resolved"}], 0)["joy"], 0.0)
expect("charge words", [heart.charge_words(x) for x in (2.5, 1.6, 1.0, 0.3)], ["很强烈", "挺明显", "有一点", "淡淡的"])

af = importlib.import_module("kaju_core.heart.afterthought")
got = af.parse('好的\n[{"id": "h1", "emotion": "后悔", "charge": 1.5, "status": "open", "thought": "昨天太凶了", "want": "说句软话"},'
               ' {"id": "h2", "emotion": "释怀", "charge": 9, "status": "resolved"}, {"emotion": "生气"}, {"id": "h3"}]')
expect("af parse", [(r["id"], r["emotion"], r["charge"], r["resolved"]) for r in got],
       [("h1", "后悔", 1.5, False), ("h2", "释怀", 3.0, True)])
expect("af parse junk", af.parse("想不起来"), [])

import zoneinfo  # noqa: E402

SH = zoneinfo.ZoneInfo("Asia/Shanghai")
ldir = tempfile.mkdtemp()
with open(os.path.join(ldir, "2026-10-30.jsonl"), "w", encoding="utf-8") as f:
    for row in [{"t": "22:00", "c": "g1", "u": "9", "n": "坏人", "x": "早"},          # 事发前
                {"t": "23:30", "c": "g1", "u": "9", "n": "坏人", "x": "哈哈哈"},
                {"t": "23:31", "c": "g1", "u": "7", "n": "路人", "x": "无关的话"},     # 群里别人、没提佳树 → 不要
                {"t": "23:32", "c": "g1", "u": "7", "n": "路人", "x": "佳树别理他"},   # 提到佳树 → 要
                {"t": "01:10", "c": "p9", "u": "9", "n": "坏人", "x": "对不起嘛"},     # 凌晨 = 10-31 01:10
                {"t": "02:00", "c": "g2", "u": "9", "n": "坏人", "x": "别的群"}]:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
since = dt_since = __import__("datetime").datetime(2026, 10, 30, 23, 0, tzinfo=SH).timestamp()
lines = af.log_lines(ldir, SH, {"g1", "p9"}, since, since + 86400, people={"9", "self"})
expect("af log lines", [ln.split("] ", 1)[1] for ln in lines], ["坏人：哈哈哈", "路人：佳树别理他", "坏人：对不起嘛"])
expect("af log after midnight", "10-31 01:10 私聊" in lines[-1], True)


async def thread_tests():
    grievance = ('{"toward_her": true, "affection": -2, "reason": "笑佳树笨", "emotion": "委屈", "intensity": 2,'
                 ' "cause": "来点作用吧笑佳树笨", "threads": []}')
    state = {"answer": grievance, "reflect": "[]"}
    p, calls = make(lambda prompt: state["reflect"] if "【心事" in prompt else state["answer"])
    ev = AstrMessageEvent(sender="333333333", group=G, text="佳树好笨啊哈哈哈", admin=False, name="来点作用吧")
    await turn(p, ev, "唔……佳树才不笨")
    ths = p._open_threads()
    expect("thread created", (len(ths), ths[0]["emo"], ths[0]["cause"], ths[0]["chat"], ths[0]["said"]),
           (1, "委屈", "来点作用吧笑佳树笨", "g" + G, "佳树好笨啊哈哈哈"))
    tid = ths[0]["id"]
    note = p.build_note("333333333", "来点作用吧", ev.unified_msg_origin)
    expect("note thread for that person", ("心里还压着的事" in note, "笑佳树笨" in note, "TA现在就在" in note), (True, True, True))
    expect("event not duplicated", "笑佳树笨，你" in note, False)
    stranger = p.build_note("1", "路人", "qq:FriendMessage:1")
    expect("note thread hidden from others", ("笑佳树笨" in stranger, "别处的事" in stranger), (False, True))
    expect("note thread visible to owner", "笑佳树笨" in p.build_note(OWNER, "晴川", "qq:FriendMessage:" + OWNER), True)

    # 同一个人一天内又来一次 → 同一件心事加重，不新开
    c1 = heart.thread_charge(ths[0], time.time())
    await turn(p, ev, "哼")
    expect("thread merged & heavier", (len(p._open_threads()), heart.thread_charge(p._open_threads()[0], time.time()) > c1),
           (1, True))
    # 判断时把相关心事给模型看
    await turn(p, ev, "嗯")
    expect("appraiser sees thread", f"{tid}：" in calls[-1][0] and "笑佳树笨" in calls[-1][0], True)
    other_ev = AstrMessageEvent(sender="888888888", group="123", text="你好", admin=False, name="李四")
    state["answer"] = '{"affection": 1, "emotion": "开心", "intensity": 1, "threads": [{"id": "%s", "effect": "resolve"}]}' % tid
    await turn(p, other_ev, "你好呀")
    expect("unrelated person can't see/resolve", (f"{tid}：" in calls[-1][0], len(p._open_threads())), (False, 1))

    # 心事压着：过了很久，心情也回不到平常那么好
    later = time.time() + 6 * 3600
    expect("open thread lowers mood", p.mood_now(later)["joy"] < heart.baselines(p._hour(later))["joy"], True)
    ths = p.mood_snapshot()["threads"]
    expect("snapshot has open thread with charge", len(ths) == 1 and 0 < ths[0]["c"] <= 3 and ths[0]["emo"] in heart.EMOTIONS, True)

    # 加重：同样的事又来一次（threads worsen），不重复新开
    c2 = heart.thread_charge(p._open_threads()[0], time.time())
    state["answer"] = ('{"affection": -1, "emotion": "委屈", "intensity": 2, "cause": "又被笑了",'
                       ' "threads": [{"id": "%s", "effect": "worsen"}]}' % tid)
    await turn(p, ev, "……")
    expect("worsen", (len(p._open_threads()), round(heart.thread_charge(p._open_threads()[0], time.time()), 1)),
           (1, round(min(3.0, c2 + 0.8), 1)))

    # 回想：还没到时间不想；过 4 小时 / 第二天早上该想了
    th0 = p._open_threads()[0]
    expect("not due right away", p._due(th0, time.time()), False)
    expect("due after 4h", p._due(th0, time.time() + 4.1 * 3600), True)
    # 越想越委屈：分量最多 +1.2，想法和打算记下来，提示里能看到
    log_dir = os.path.join(DATA, "astrbot_plugin_kaju_life", "log")
    today = (__import__("datetime").datetime.now(SH) - __import__("datetime").timedelta(hours=5)).strftime("%Y-%m-%d")
    hhmm = (__import__("datetime").datetime.now(SH) + __import__("datetime").timedelta(minutes=2)).strftime("%H:%M")
    with open(os.path.join(log_dir, today + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": hhmm, "c": "g" + G, "u": "333333333", "n": "来点作用吧", "x": "今天天气真好哈哈"},
                           ensure_ascii=False) + "\n")
    th0["t0"] -= 3600  # 事情是一小时前开始的（这样上面那句算"之后"）
    state["reflect"] = ('[{"id": "%s", "emotion": "委屈", "charge": 3, "status": "open",'
                        ' "thought": "TA一句道歉都没有还在聊天气", "want": "等TA先道歉"}]' % tid)
    cur = heart.thread_charge(th0, time.time() + 300)
    out = await p.reflect(force=True, now=time.time() + 300)
    expect("reflect prompt has later chat", "今天天气真好" in calls[-1][0] and "笑佳树笨" in calls[-1][0], True)
    expect("reflect worse clamped", round(heart.thread_charge(th0, time.time() + 300), 1), round(min(3.0, cur + 1.2), 1))
    expect("reflect out", len(out), 1)
    note = p.build_note("333333333", "来点作用吧", ev.unified_msg_origin, now=time.time() + 300)
    expect("note shows thought", ("一句道歉都没有" in note, "等TA先道歉" in note), (True, True))

    # 冷静下来后悔了 → 提示她找机会说句软话
    state["reflect"] = ('[{"id": "%s", "emotion": "后悔", "charge": 1.2, "status": "open",'
                        ' "thought": "其实TA只是开玩笑", "want": "找机会跟TA说句软话"}]' % tid)
    await p.reflect(force=True, now=time.time() + 600)
    note = p.build_note("333333333", "来点作用吧", ev.unified_msg_origin, now=time.time() + 600)
    expect("regret note", ("后悔" in note, "说句软话" in note), (True, True))
    for _ in range(2):  # 真请求里提醒过两次，就不再催她道歉
        p.build_note("333333333", "来点作用吧", ev.unified_msg_origin, mark=True)
    note = p.build_note("333333333", "来点作用吧", ev.unified_msg_origin, mark=True)
    expect("regret nudge at most twice", ("后悔" in note, "这次回复里顺带说句软话" in note), (True, False))
    # 对方道歉 → 放下
    state["answer"] = ('{"affection": 2, "reason": "来道歉了", "emotion": "感动", "intensity": 2,'
                       ' "threads": [{"id": "%s", "effect": "resolve"}]}' % tid)
    await turn(p, AstrMessageEvent(sender="333333333", group=G, text="对不起嘛佳树", admin=False, name="来点作用吧"), "嗯！")
    expect("resolved by apology", (p._open_threads(), p._state["threads"][0]["emo"]), ([], "释怀"))
    expect("resolved not in note", "心里还压着" in p.build_note("333333333", "来点作用吧", ev.unified_msg_origin), False)

    # 回想后放下 / 挂太久自动放下
    state["answer"] = ('{"affection": -3, "emotion": "生气", "intensity": 3, "cause": "李四骂佳树", "threads": []}')
    await turn(p, other_ev, "你才是！")
    hid = p._open_threads()[0]["id"]
    state["reflect"] = '[{"id": "%s", "emotion": "释怀", "charge": 0.2, "status": "resolved", "thought": "算了"}]' % hid
    await p.reflect(force=True)
    expect("reflect → let go", p._open_threads(), [])
    state["answer"] = ('{"affection": 0, "emotion": "担心", "intensity": 2, "toward_her": false,'
                       ' "cause": "兄长大人的项目被骂了"}')
    own = AstrMessageEvent(sender=OWNER, text="项目被骂了", name="晴川")
    await turn(p, own, "兄长大人……")
    expect("worry thread (not toward her)", [t["emo"] for t in p._open_threads()], ["担心"])
    p._tidy(time.time() + 5 * 86400)
    expect("old thread let go", p._open_threads(), [])

    # 命令
    async def cmd(gen):
        return [x async for x in gen]

    await turn(p, other_ev, "你才是！")
    out = await cmd(p.cmd_mood(AstrMessageEvent(sender=OWNER)))
    expect("cmd mood lists threads", ("心事" in out[0], "还挂着" in out[0]), (True, True))
    hid = p._open_threads()[0]["id"]
    out = await cmd(p.cmd_mood(AstrMessageEvent(sender=OWNER), "放下", hid))
    expect("cmd let go", (p._open_threads(), "放下了" in out[0]), ([], True))
    out = await cmd(p.cmd_mood(AstrMessageEvent(sender=OWNER), "回想"))
    expect("cmd reflect nothing", out, ["现在心里没有压着的事"])
    p_off, _ = make(lambda _prompt: grievance, {"afterthought": {"enable": False}})
    await turn(p_off, ev, "唔")
    expect("afterthought off", p_off._open_threads(), [])
    if p._loop_task:
        p._loop_task.cancel()


asyncio.run(thread_tests())


# ------------------------------------------------------------------ 余韵：看过/读过的东西留下的情绪
async def content_tests():
    expect("parse source", (appraise.parse('{"emotion": "难过", "source": "content"}')["source"],
                            appraise.parse('{"emotion": "难过"}')["source"]), ("content", "person"))
    sad = ('{"toward_her": true, "affection": 1, "reason": "愿意跟佳树分享", "emotion": "难过", "intensity": 2,'
           ' "source": "content", "cause": "兄长大人发的小说里林婆婆没等到儿子"}')
    p, calls = make(lambda prompt: '[]' if "【心事" in prompt else sad)
    ev = AstrMessageEvent(sender=OWNER, text="给你看个故事", name="晴川")
    await turn(p, ev, "呜……林婆婆好可怜")
    tastes, grudges = p._open_threads("content"), p._open_threads()
    expect("aftertaste created, no grudge", ([t["emo"] for t in tastes], grudges), (["难过"], []))
    expect("sharing doesn't cost affection", p.affection(OWNER) >= 95, True)
    note = p.build_note(OWNER, "晴川", ev.unified_msg_origin)
    expect("aftertaste note", ("还在回味的" in note, "林婆婆没等到儿子" in note, "可以跟TA聊聊感想" in note,
                               "心里还压着的事" in note), (True, True, True, False))
    other = p.build_note("1", "路人", "qq:FriendMessage:1")
    expect("aftertaste private elsewhere", ("林婆婆" in other, "之前看过的一个东西" in other), (False, True))
    # 余韵比人惹的心事淡得快（难过 10 小时 vs 30 小时）
    th = tastes[0]
    expect("aftertaste fades faster", heart.thread_charge(th, time.time() + 10 * 3600) < heart.thread_charge(
        {**th, "kind": "person"}, time.time() + 10 * 3600) * 0.7, True)
    # 不给每轮判断看、不回想
    await turn(p, ev, "嗯")
    expect("appraiser doesn't see aftertaste", "【佳树心里压着的事】" in calls[-1], False)
    expect("not reflected", await p.reflect(force=True), [])
    # 接着看同一个人分享的、同一种感受：算接着看，不新开
    await turn(p, ev, "呜呜")
    expect("aftertaste merged", len(p._open_threads("content")), 1)
    p._tidy(time.time() + 2.5 * 86400)
    expect("aftertaste gone after 2 days", p._open_threads("content"), [])
    # 感动也能留下余韵（暖暖的）
    p2, _ = make('{"affection": 1, "emotion": "感动", "intensity": 3, "source": "content", "cause": "信里写着谢谢佳树"}')
    p2._state["threads"] = []  # 同一个测试存档目录里还留着上面的余韵
    await turn(p2, ev, "兄长大人……")
    expect("touching aftertaste", [t["emo"] for t in p2._open_threads("content")], ["感动"])
    expect("touching lifts mood", p2.mood_now(time.time() + 3600)["warm"] > heart.baselines(p2._hour())["warm"], True)
    for x in (p, p2):
        if x._loop_task:
            x._loop_task.cancel()


asyncio.run(content_tests())


# ------------------------------------------------------------------ smart_chime_in reads the mood factor
async def chime_tests():
    sci = importlib.import_module("smart_chime_in.main")
    p = sci.SmartChimeIn(Context(), {"base_chance": 0.4, "max_chance": 0.9})
    window = [{"sender": "1", "text": "今天去哪里玩比较好呢", "at_other": False, "t": 0}]
    base_p, why = p._score(window, 1)

    class Meta:
        class star_cls:
            @staticmethod
            def chime_factor():
                return 1.25

    p.context.get_all_stars = lambda: [Meta]
    happy_p, why2 = p._score(window, 1)
    expect("chime mood scales", (round(happy_p / base_p, 2), "mood×1.25" in why2, "mood" in why), (1.25, True, False))


asyncio.run(chime_tests())


# ------------------------------------------------------------------ 心里记下的（inner.py）
inner = importlib.import_module("kaju_core.heart.inner")

THINK = ('User: "嗯我明白了，是我曲解了佳树的意思" — he thinks he misunderstood her. 佳树 should reassure: 不是曲解啦, '
         '佳树说得含糊. 撒娇 tone, short.\n\nPersonal touch: 被追问三遍，其实佳树心里挺高兴的。\n'
         'Meme: recent replies — last had &&shy&&. Use &&affection&&.\n\nDraft:\n"不是兄长大人曲解，是佳树自己没说明白呀"\n'
         'Keep short.')
expect("gist keeps understanding", ("he thinks he misunderstood her" in inner.think_gist(THINK),
                                    "其实佳树心里挺高兴的" in inner.think_gist(THINK)), (True, True))
expect("gist drops meme/draft/format", any(w in inner.think_gist(THINK) for w in ("Meme", "&&", "Draft", "没说明白呀", "short")),
       False)
expect("gist cap", len(inner.think_gist("他在难过。" * 200, 100)) <= 101, True)
expect("gist empty", inner.think_gist(""), "")
msgs = [{"role": "user", "content": "old"},
        {"role": "assistant", "content": [{"type": "think", "think": "旧的思考"}, {"type": "text", "text": "x"}]},
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": [{"type": "think", "think": "先想想要不要查资料"}]},
        {"role": "tool", "content": "..."},
        {"role": "assistant", "content": [{"type": "think", "think": "他好像有点难过"}, {"type": "text", "text": "y"}]}]
expect("think_of this turn only", inner.think_of(msgs), "先想想要不要查资料\n他好像有点难过")
expect("think_of + reasoning_content", inner.think_of([], type("R", (), {"reasoning_content": "嗯…他在逗我"})()), "嗯…他在逗我")
expect("think_of no dup", inner.think_of(msgs, type("R", (), {"reasoning_content": "他好像有点难过"})()).count("难过"), 1)
expect("worth: one plain turn", inner.worth([{"emo": "平静", "i": 0}]), False)
expect("worth: a little feeling", inner.worth([{"emo": "开心", "i": 1}]), True)
expect("worth: several turns", inner.worth([{"emo": "平静", "i": 0}] * 3), True)
expect("due settle", (inner.due({"turns": [{"t": 0}]}, 599, 600, 12), inner.due({"turns": [{"t": 0}]}, 600, 600, 12)),
       (False, True))
expect("due max turns", inner.due({"turns": [{"t": 100}] * 12}, 101, 600, 12), True)
TZ = __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
ts = __import__("datetime").datetime(2026, 11, 1, 0, 28, tzinfo=TZ).timestamp()
expect("when: after midnight = last night", inner.when_words(ts, TZ), "10月31日深夜")
expect("when: afternoon", inner.when_words(ts + 14 * 3600, TZ), "11月1日下午")
expect("place", (inner.place_words("", "", "兄长大人"), inner.place_words("1", "妖妖", "x"), inner.place_words("1", "", "x")),
       ("和兄长大人私聊", "在妖妖里", "在群里"))
expect("parse skip", inner.parse('{"skip": true}'), {"skip": True})
expect("parse memory (old key)", inner.parse('好的 {"skip": false, "memory": "他追问了三遍，我心里偷偷高兴。"}'),
       {"skip": False, "memory": "他追问了三遍，我心里偷偷高兴。", "about": ""})
expect("parse voice + about", inner.parse('{"skip": false, "about": "（他说爱我，道了晚安）", "voice": "真想记住今晚。"}'),
       {"skip": False, "memory": "真想记住今晚。", "about": "他说爱我，道了晚安"})
expect("compose with about", inner.compose("10月31日深夜", "和兄长大人私聊", "真想记住今晚。", "他说爱我，道了晚安"),
       "【佳树心里】10月31日深夜，和兄长大人私聊（他说爱我，道了晚安）：真想记住今晚。")
expect("parse strips mark", inner.parse('{"memory": "【佳树心里】：我有点害羞。"}')["memory"], "我有点害羞。")
expect("parse drops leaked words", inner.parse('{"memory": "我很开心。按照人设我要撒娇。"}')["memory"], "我很开心。")
expect("parse garbage", (inner.parse("不知道"), inner.parse('{"skip": false}')), (None, None))
expect("parse caps length", len(inner.parse('{"memory": "' + "我想他了。" * 100 + '"}', 100)["memory"]) <= 150, True)
expect("compose", inner.compose("10月31日深夜", "和兄长大人私聊", "我很开心。"), "【佳树心里】10月31日深夜，和兄长大人私聊：我很开心。")
prompt = inner.build_prompt(when="10月31日深夜", place="和兄长大人私聊", lines=["  [10-31 23:32 私聊] 兄长大人：嗯"],
                            turns=[{"hm": "23:32", "who": OWNER, "name": "晴川", "said": "嗯我明白了", "reply": "不是你曲解",
                                    "emo": "开心", "i": 2, "cause": "他认真在听", "think": "he thinks he misunderstood"}],
                            names={OWNER: "兄长大人"})
expect("prompt parts", all(x in prompt for x in ("【这段聊天】", "兄长大人：嗯我明白了", "开心（明显）——他认真在听",
                                                  "回话前心里在想（草稿）：he thinks")), True)
expect("system: heart-only style", ("最多 120 字" in inner.system_prompt(hi=120), "真想记住今晚" in inner.system_prompt(),
                                     "不复述谁说了什么" in inner.system_prompt(), '"voice"' in inner.system_prompt()),
       (True, True, True, True))


class FakeIngest:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    async def ingest_summary(self, **kw):
        self.calls.append(kw)
        return {"stored_ids": ["abcdef1234567890"] if self.ok else [], "detail": "chat_filtered"}


class FakeMemorix:
    def __init__(self, ok=True):
        self.ingest_service = FakeIngest(ok)

    def _resolve_scope(self, event):
        return "aiocqhttp"


def memorix_star(mx):
    return type("Meta", (), {"name": "astrbot_plugin_memorix", "star_cls": mx})()


class ThinkRun:
    def __init__(self, user, reply, think):
        self.messages = [{"role": "user", "content": [{"type": "text", "text": user}]},
                         {"role": "assistant", "content": [{"type": "think", "think": think}, {"type": "text", "text": reply}]}]


async def think_turn(p, ev, reply, think):
    await p.on_done(ev, ThinkRun(ev.message_str, reply, think), LLMResponse(reply))
    task = p._tasks.get(ev.unified_msg_origin)
    if task:
        await task


def life_log(lines):
    import datetime as _dt
    now = _dt.datetime.now(TZ)
    day = (now - _dt.timedelta(hours=5)).strftime("%Y-%m-%d")
    path = os.path.join(DATA, "astrbot_plugin_kaju_life", "log", day + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for u, n, c, x in lines:
            f.write(json.dumps({"t": now.strftime("%H:%M"), "c": c, "u": u, "n": n, "x": x}, ensure_ascii=False) + "\n")


async def inner_tests():
    happy = ('{"toward_her": true, "affection": 2, "reason": "认真听佳树说话", "emotion": "开心", "intensity": 2,'
             ' "cause": "兄长大人追问三遍，说明真在听佳树说话"}')
    plain = '{"toward_her": true, "affection": 0, "emotion": "平静", "intensity": 0, "cause": ""}'
    memory = '{"skip": false, "about": "他追问了我三遍", "voice": "被追问了三遍，我心里偷偷高兴——他是真的在听我说话。"}'
    state = {"appraisal": happy, "inner": memory}

    def answer(prompt):
        return state["inner"] if "【她每次回话时】" in prompt else state["appraisal"]

    mx = FakeMemorix()
    ctx = Context()
    ctx.stars = [memorix_star(mx)]
    p, calls = make(answer, ctx=ctx)
    p._state["inner"], p._state["inner_log"] = {}, []
    life_log([(OWNER, "晴川", "p" + OWNER, "嗯我明白了，是我曲解了佳树的意思"),
              ("self", "佳树", "p" + OWNER, "不是兄长大人曲解，是佳树自己没说明白")])
    ev = AstrMessageEvent(sender=OWNER, text="嗯我明白了，是我曲解了佳树的意思", name="晴川")
    await think_turn(p, ev, "不是兄长大人曲解，是佳树自己没说明白", THINK)
    ev2 = AstrMessageEvent(sender=OWNER, text="佳树的话我一定会听的", name="晴川")
    await think_turn(p, ev2, "那佳树以后说得直白点", "He promises to listen. 佳树 feels warm.")
    seg = p._state["inner"].get("p" + OWNER)
    expect("turns buffered", len(seg["turns"]) if seg else 0, 2)
    expect("turn has feeling + think", (seg["turns"][0]["emo"], seg["turns"][0]["i"], "misunderstood" in seg["turns"][0]["think"],
                                        "Meme" in seg["turns"][0]["think"]), ("开心", 2, True, False))
    expect("memorix place", (seg["session"], seg["scope"]), (OWNER, "aiocqhttp"))
    expect("not yet: still chatting", await p.write_inner(now=time.time() + 60), [])
    n_calls = len(calls)
    out = await p.write_inner(now=time.time() + 11 * 60)
    expect("written once", len(out), 1)
    e = out[0] if out else {}
    expect("one writer call", len(calls) - n_calls, 1)
    wp = calls[-1][0]
    expect("writer sees log, feeling, think", ("【这段聊天】" in wp, "兄长大人：嗯我明白了" in wp, "追问三遍" in wp,
                                               "he thinks he misunderstood her" in wp, "&&" in wp), (True, True, True, True, False))
    expect("text marked + where + about", (e.get("text", "").startswith("【佳树心里】"),
                                          "和兄长大人私聊（他追问了我三遍）：" in e.get("text", ""),
                                          "偷偷高兴" in e.get("text", "")), (True, True, True))
    kw = mx.ingest_service.calls[-1] if mx.ingest_service.calls else {}
    expect("stored as this chat's memory", (kw.get("chat_id"), kw.get("scope_key"), kw.get("group_id"), kw.get("user_id"),
                                           kw.get("text") == e.get("text"), kw.get("metadata", {}).get("kind")),
           (OWNER, "aiocqhttp", "", OWNER, True, "inner_voice"))
    expect("time range + tags", (kw.get("time_start") <= kw.get("time_end"), "佳树的心里话" in kw.get("tags", []), "开心" in kw.get("tags", [])),
           (True, True, True))
    expect("hash kept, buffer cleared", (e.get("hash"), "p" + OWNER in p._state["inner"]), ("abcdef1234567890", False))
    expect("log kept", p._state["inner_log"][-1]["text"], e.get("text"))

    # 一句平平的寒暄：不记，也不问模型
    state["appraisal"] = plain
    await think_turn(p, AstrMessageEvent(sender=OWNER, text="在吗", name="晴川"), "在呀", "Just a greeting.")
    n_calls = len(calls)
    expect("plain greeting not written", await p.write_inner(now=time.time() + 11 * 60), [])
    expect("no writer call for greeting", (len(calls) - n_calls, "p" + OWNER in p._state["inner"]), (0, False))

    # 模型说没什么波澜：不记
    state["appraisal"], state["inner"] = happy, '{"skip": true}'
    for _ in range(3):
        await think_turn(p, AstrMessageEvent(sender=OWNER, text="哈哈", name="晴川"), "嘿嘿", "")
    expect("model skip", (await p.write_inner(now=time.time() + 11 * 60), "p" + OWNER in p._state["inner"]), ([], False))
    wp = calls[-1][0]
    # （测试里所有话都在同一分钟，聊天记录只精确到分钟，所以全算"之前的"）
    expect("next segment sees last memory as already written",
           ("【上一段已经记下的心声】" in wp, "偷偷高兴" in wp, "【之前的聊天】" in wp, "【这段聊天】" in wp),
           (True, True, True, False))
    expect("already-written lines only as background",
           "是我曲解了佳树的意思" in wp.split("【之前的聊天】")[1].split("【她每次回话时】")[0], True)

    # 群里：存成这个群的记忆，地点写群名；只带当事人和她自己的话
    state["inner"] = '{"memory": "女王大人问电晕人要多少电压，我有点怕，坚决没说。"}'
    with open(os.path.join(DATA, "astrbot_plugin_kaju_life", "names.json"), "w", encoding="utf-8") as f:
        json.dump({"groups": {G: "妖妖"}, "people": {}}, f, ensure_ascii=False)
    life_log([("888888888", "danb", "g" + G, "电晕人需要多少电压"), ("999", "路人", "g" + G, "今天吃啥"),
              ("self", "佳树", "g" + G, "这个佳树不说")])
    gev = AstrMessageEvent(sender="888888888", group=G, text="电晕人需要多少电压", admin=False, name="danb")
    state["appraisal"] = '{"toward_her": true, "affection": -1, "emotion": "害怕", "intensity": 2, "cause": "danb问危险的事"}'
    await think_turn(p, gev, "这个佳树不说", "Dangerous question.")
    out = await p.write_inner(now=time.time() + 11 * 60)
    wp = calls[-1][0]
    kw = mx.ingest_service.calls[-1]
    expect("group memory", (kw["chat_id"], kw["group_id"], kw["user_id"], "在妖妖里：" in (out[0]["text"] if out else "")),
           (G, G, "", True))
    expect("group context only people involved", ("电晕人" in wp, "今天吃啥" in wp), (True, False))

    # memorix 没加载：先留着，下一轮再存
    ctx.stars = []
    state["appraisal"], state["inner"] = happy, memory
    await think_turn(p, ev, "嗯嗯", "")
    out = await p.write_inner(now=time.time() + 11 * 60)
    expect("kept without memorix", (len(out), out[0]["hash"] if out else None, out[0].get("tries") if out else None), (1, "", 1))
    ctx.stars = [memorix_star(mx)]
    before = len(mx.ingest_service.calls)
    await p.write_inner(now=time.time() + 11 * 60)
    expect("retried into memorix", (len(mx.ingest_service.calls) - before, p._state["inner_log"][-1]["hash"]),
           (1, "abcdef1234567890"))
    # memorix 过滤了这个聊天：标"-"，不再重试
    mx2 = FakeMemorix(ok=False)
    ctx.stars = [memorix_star(mx2)]
    await think_turn(p, ev, "嗯嗯", "")
    out = await p.write_inner(now=time.time() + 11 * 60)
    expect("filtered chat not retried", (out[0]["hash"] if out else None, out[0].get("tries") if out else None), ("-", None))
    ctx.stars = [memorix_star(mx)]

    # 模型连着坏 3 次：这几轮不记了
    state["inner"] = "不知道"
    await think_turn(p, ev, "嗯嗯", "")
    for _ in range(3):
        await p.write_inner(now=time.time() + 11 * 60)
    expect("dropped after 3 failures", "p" + OWNER in p._state["inner"], False)

    # 聊个不停：攒够 max_turns 就先写一段，剩下的留着
    state["inner"] = memory
    p.config = {"inner": {"max_turns": 3}}
    for _ in range(4):
        await think_turn(p, ev, "嗯嗯", "")
    out = await p.write_inner(now=time.time() + 30)
    expect("long chat chunked", (len(out), out[0]["n"] if out else 0, len(p._state["inner"]["p" + OWNER]["turns"])), (1, 3, 1))
    p.config = {}

    # 网页聊天、关掉时不攒
    p._state["inner"] = {}
    await think_turn(p, AstrMessageEvent(sender="astrbot", text="测试", platform="webchat"), "嗯", "")
    expect("webchat ignored", p._state["inner"], {})
    p.config = {"inner": {"enable": False}}
    await think_turn(p, ev, "嗯", "")
    expect("disabled", (p._state["inner"], await p.write_inner(force=True)), ({}, []))
    p.config = {}

    # 命令
    await think_turn(p, ev, "嗯嗯", "")
    cmd = AstrMessageEvent(sender=OWNER, text="/佳树心情 心里话", name="晴川")
    shown = [x async for x in p.cmd_mood(cmd, "心里话")][0]
    expect("cmd shows memories + waiting", ("【佳树心里】" in shown, "还没写的：p" + OWNER in shown), (True, True))
    forced = [x async for x in p.cmd_mood(cmd, "记下")][0]
    expect("cmd force write", (forced.startswith("记下了"), "p" + OWNER in p._state["inner"]), (True, False))
    for task in (p._loop_task, p._inner_task):
        if task:
            task.cancel()


asyncio.run(inner_tests())


# ------------------------------------------------------------------ 关系的几个侧面 + 在场 + 沉淀（relation.py）
rel_mod = importlib.import_module("kaju_core.heart.relation")
R = rel_mod
r0 = R.start(False, 0.2)
expect("rel start", r0, {"trust": 0.5, "care": 0.5, "bound": 0.7})
expect("guarded start lower trust", R.start(False, 0.7)["trust"] < 0.4, True)
expect("owner start", R.start(True, 0.9)["trust"], 0.9)
up1 = R.step(r0, ["守约"], 0.2)
expect("守约 raises trust", 0.5 < up1["trust"] < 0.58, True)
dn1 = R.step(r0, ["失约"], 0.2)
expect("失约 drops more than 守约 raises", 0.5 - dn1["trust"] > up1["trust"] - 0.5, True)
expect("guard slows gains", R.step(r0, ["守约"], 0.8)["trust"] < up1["trust"], True)
expect("guard speeds losses", R.step(r0, ["失约"], 0.8)["trust"] < dn1["trust"], True)
expect("max 2 signals", R.step(r0, ["失约", "骗她", "失约"], 0.2) == R.step(r0, ["失约", "骗她"], 0.2), True)
expect("owner floor", R.step({"trust": 0.56, "care": 0.9, "bound": 0.9}, ["骗她", "失约"], 0.2, is_owner=True)["trust"], 0.55)
expect("越界 hits bound", R.step(r0, ["越界"], 0.2)["bound"] < 0.62, True)
expect("drift back halfway", R.drift({"trust": 0.1, "care": 0.5, "bound": 0.7}, 60, r0)["trust"], 0.3)
g1 = R.deep_after_signals({"guard": 0.2, "absence": 0.3}, ["骗她"], 1.0)
expect("betrayal grows guard", g1["guard"] > 0.2, True)
expect("kindness eases guard", R.deep_after_signals(g1, ["守约"], 1.0)["guard"] < g1["guard"], True)
expect("late return grows absence", R.deep_after_return({"absence": 0.3}, 3.0, 1.0)["absence"] > 0.3, True)
expect("on-time return eases absence", R.deep_after_return({"absence": 0.3}, 0.5, 1.0)["absence"] < 0.3, True)
expect("deep range", R.deep_after_return({"absence": 0.9}, 9, 1)["absence"] <= 0.9, True)
pres = {}
for k in range(6):
    R.add_seen(pres, 1_800_000_000 + k * 6 * 3600)
    R.add_seen(pres, 1_800_000_000 + k * 6 * 3600 + 600)  # 同一次来里的第二句
expect("sessions counted once", len(pres["starts"]), 6)
expect("expected gap floor 8h", R.expected_gap_h(pres), 8.0)
came = R.add_seen(pres, pres["last"] + 30 * 3600)
expect("return after 30h", (came["gap"], came["expected"]), (30.0, 8.0))
expect("overdue ratio", round(R.overdue(pres, pres["last"] + 16 * 3600), 1), 2.0)
expect("no missing when on time", R.missing_offsets(1.0, 0.3), {})
mo = R.missing_offsets(3.0, 0.3)
expect("missing: joy down warm up", (mo["joy"] < 0, mo["warm"] > 0), (True, True))
expect("absence makes it start earlier", R.missing_offsets(1.3, 0.8) != {} and R.missing_offsets(1.3, 0.3) == {}, True)
expect("describe low trust", any("不太敢全信" in s for s in R.describe({"trust": 0.3, "care": 0.5, "bound": 0.7}, False,
                                                                   {"trust": "说好讲题又没来"})), True)
expect("describe neutral says nothing", R.describe(r0, False), [])
expect("describe owner only negatives", (R.describe(R.OWNER_START, True), bool(R.describe({"trust": 0.6, "care": 0.9, "bound": 0.9}, True))),
       ([], True))

# 11-18 照 anima-brain：每天总量、档位迟滞
moved = {}
cur = dict(r0)
for _ in range(10):
    cur = R.step(cur, ["守约"], 0.2, moved=moved, daily_cap=0.15)
expect("daily cap: 10 守约 in a day ≤ 0.15", round(cur["trust"] - r0["trust"], 3) <= 0.15 and moved["trust"] <= 0.1501, True)
expect("daily cap: uncapped goes further", R.step(R.step(R.step(dict(r0), ["守约"], 0.2), ["守约"], 0.2), ["守约"], 0.2)["trust"] >
       R.step(R.step(R.step(dict(r0), ["守约"], 0.2, moved={}, daily_cap=0.05), ["守约"], 0.2, moved={"trust": 0.05}, daily_cap=0.05),
              ["守约"], 0.2, moved={"trust": 0.05}, daily_cap=0.05)["trust"], True)
one_bad = R.step(dict(r0), ["骗她"], 0.2, moved={}, daily_cap=0.15)
expect("daily cap: one heavy betrayal still lands", round(r0["trust"] - one_bad["trust"], 3) == round(r0["trust"] - R.step(dict(r0), ["骗她"], 0.2)["trust"], 3), True)
expect("daily cap: spent budget blocks both ways", R.step(dict(r0), ["失约"], 0.2, moved={"trust": 0.15}, daily_cap=0.15)["trust"], 0.5)
expect("bands: low trust on", R.bands({"trust": 0.34, "care": 0.5, "bound": 0.7}, False), {"trust_low"})
expect("bands: just above threshold, not shown before → off", R.bands({"trust": 0.37, "care": 0.5, "bound": 0.7}, False), set())
expect("bands: just above threshold, shown before → stays on",
       R.bands({"trust": 0.37, "care": 0.5, "bound": 0.7}, False, {"trust_low"}), {"trust_low"})
expect("bands: well above → off even if shown", R.bands({"trust": 0.4, "care": 0.5, "bound": 0.7}, False, {"trust_low"}), set())
expect("bands: owner care hysteresis", (R.bands({"trust": 0.9, "care": 0.67, "bound": 0.9}, True),
                                        R.bands({"trust": 0.9, "care": 0.67, "bound": 0.9}, True, ["o_care"])), (set(), {"o_care"}))
expect("describe uses bands", any("不太敢全信" in s for s in R.describe({"trust": 0.37, "care": 0.5, "bound": 0.7}, False, None, {"trust_low"})), True)

# 每天的天气、重复的好话打折
w1, w1b, w2 = heart.weather("2026-11-18"), heart.weather("2026-11-18"), heart.weather("2026-11-19")
expect("weather same all day", w1, w1b)
expect("weather differs by day", w1 != w2, True)
expect("weather bounded", abs(w1["joy"]) <= 0.08 and abs(w1["energy"]) <= 0.06, True)
spread = [heart.weather(f"2026-12-{d:02d}")["joy"] for d in range(1, 31)]
expect("weather goes both ways", min(spread) < -0.02 and max(spread) > 0.02, True)
first = heart.affection_step(50, 2, 0)
expect("repeat discount: 2nd gain smaller", heart.affection_step(50, 2, 0, repeats=1) < first, True)
expect("repeat discount: /(1+0.6n)", round(heart.affection_step(50, 2, 0, repeats=2), 3), round(first / 2.2, 3))
expect("repeat discount: losses untouched", heart.affection_step(50, -2, 0, repeats=5), -2)
expect("deep words only when heavy", (R.deep_words(R.DEEP_START), len(R.deep_words({"absence": 0.6, "guard": 0.5}))), ([], 2))
sp = appraise.parse('{"affection": -1, "emotion": "失落", "intensity": 2, "signals": ["失约", "瞎编的", "失约"], "signal_why": "说好晚上讲题又没来"}')
expect("parse signals", (sp["signals"], sp["signal_why"]), (["失约"], "说好晚上讲题又没来"))
expect("parse signal str", appraise.parse('{"affection": 1, "emotion": "开心", "signals": "守约"}')["signals"], ["守约"])
expect("parse no signals", appraise.parse('{"affection": 1, "emotion": "开心"}')["signals"], [])
expect("parse not toward → no signals", appraise.parse('{"toward_her": false, "emotion": "平静", "signals": ["越界"]}')["signals"], [])
expect("system lists signals", "守约" in appraise.system_prompt() and "signal_why" in appraise.system_prompt(), True)


def write_life(base_dir, rows, now):
    """rows: (几小时前, QQ, 昵称, 聊天)；按"5 点换天"写进 kaju_life 的日志文件。"""
    import datetime as _dt
    log_dir = os.path.join(base_dir, "astrbot_plugin_kaju_life", "log")
    os.makedirs(log_dir, exist_ok=True)
    for hours_ago, u, n, c in rows:
        t = _dt.datetime.fromtimestamp(now - hours_ago * 3600, TZ)
        day = (t - _dt.timedelta(hours=5)).strftime("%Y-%m-%d")
        with open(os.path.join(log_dir, day + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": t.strftime("%H:%M"), "c": c, "u": u, "n": n, "x": "嗯"}, ensure_ascii=False) + "\n")


async def relation_tests():
    old = os.environ["STUB_DATA"]
    os.environ["STUB_DATA"] = tempfile.mkdtemp()
    try:
        now = time.time()
        # 兄长大人平时每 6 小时左右来一次，这次已经 30 小时没来
        write_life(os.environ["STUB_DATA"], [(30 + 6 * k, OWNER, "晴川", "p" + OWNER) for k in range(8, -1, -1)], now)
        broke = ('{"toward_her": true, "affection": -1, "reason": "又没来讲题", "emotion": "失落", "intensity": 1,'
                 ' "cause": "说好讲题又没来", "signals": ["失约"], "signal_why": "说好晚上讲题又没来"}')
        p, _ = make(broke, config={"relation": {"daily_cap": 0}})  # 这里测一次次失约怎么累积：每天总量另测
        p.scan_presence(now)
        expect("presence seeded from log", len(p._state["presence"][OWNER]["starts"]), 9)
        expect("owner overdue", p._owner_overdue(now) > 3, True)
        friend = AstrMessageEvent(sender="444444444", group=G, text="佳树在吗", admin=False, name="哆啦a梦")
        note = p.build_note("444444444", "哆啦a梦", friend.unified_msg_origin)
        expect("missing owner line in others' chat", "兄长大人已经一天多没来了" in note and "有点想他" in note, True)
        p_off, _ = make(broke, config={"relation": {"missing": False}})
        p_off.scan_presence(now)
        expect("missing lowers joy baseline", p.mood_now(now)["joy"] < p_off.mood_now(now)["joy"], True)
        expect("missing off: no line", "没来了" in p_off.build_note("444444444", "哆啦a梦", friend.unified_msg_origin), False)
        # 他回来了
        a0 = float(p._state["deep"]["absence"])
        write_life(os.environ["STUB_DATA"], [(0, OWNER, "晴川", "p" + OWNER)], now)
        p.scan_presence(now + 30)
        expect("return recorded", round(p._state["presence"][OWNER]["ret"]["gap"]), 30)
        expect("late return deepens absence", float(p._state["deep"]["absence"]) > a0, True)
        own = AstrMessageEvent(sender=OWNER, text="佳树我回来啦", name="晴川")
        n1 = p.build_note(OWNER, "晴川", own.unified_msg_origin, now + 60, mark=True)
        expect("return note for owner", "隔了一天多才来" in n1 and "小委屈" in n1, True)
        p.build_note(OWNER, "晴川", own.unified_msg_origin, now + 90, mark=True)
        expect("return note at most twice", "隔了" in p.build_note(OWNER, "晴川", own.unified_msg_origin, now + 120, mark=True), False)
        expect("no more missing once back", "没来了" in p.build_note("444444444", "哆啦a梦", friend.unified_msg_origin, now + 120), False)

        # 哆啦a梦一次次失约：信任掉下去，提示里说出来；戒心变重一点（TA不算重要的人，加得少）
        g0 = float(p._state["deep"]["guard"])
        for _ in range(4):
            await turn(p, friend, "唔……又这样")
        rel = p._state["people"]["444444444"]["rel"]
        expect("broken promises drop trust", rel["trust"] < 0.35, True)
        note2 = p.build_note("444444444", "哆啦a梦", friend.unified_msg_origin)
        expect("relation words in note", "不太敢全信" in note2 and "说好晚上讲题又没来" in note2, True)
        expect("guard grows a bit", float(p._state["deep"]["guard"]) > g0, True)
        expect("rlog kept", len(p._state["people"]["444444444"]["rlog"]), 4)
        expect("/好感度 shows relation", "信任 " in p._describe("444444444", True) and "失约" in p._describe("444444444", True), True)
        # 兄长大人失约：信任有底线，好感不受影响；提示里是"小失望"
        for _ in range(4):
            await turn(p, own, "兄长大人又忘了……")
        expect("owner trust floor", p._state["people"][OWNER]["rel"]["trust"], 0.55)
        expect("owner affection floor kept", p.affection(OWNER) >= 95, True)
        expect("owner note small disappointment", "小失望" in p.build_note(OWNER, "晴川", own.unified_msg_origin), True)
        expect("owner betrayals grow guard more", float(p._state["deep"]["guard"]) > 0.25, True)
        # 分享内容带来的感受不算关系信号
        p3, _ = make('{"toward_her": true, "affection": 0, "emotion": "难过", "intensity": 2, "source": "content",'
                     ' "cause": "小说里的人骗了女主", "signals": ["骗她"]}')
        reader = AstrMessageEvent(sender="999", group=G, text="这个故事好难过", admin=False, name="读者")
        await turn(p3, reader, "呜……好难过")
        expect("content source ignores signals", p3._state["people"]["999"].get("rel"), None)
        # 戒心重时，对别人的提示里说一句
        p._state["deep"]["guard"] = 0.5
        expect("guard words when heavy", "戒心" in p.build_note("444444444", "哆啦a梦", friend.unified_msg_origin), True)
        lines = [r async for r in p.cmd_mood(AstrMessageEvent(sender=OWNER, admin=True), "")]
        expect("/佳树心情 shows deep", "怕被丢下" in lines[0].text if hasattr(lines[0], "text") else "怕被丢下" in str(lines[0]), True)
    finally:
        os.environ["STUB_DATA"] = old


asyncio.run(relation_tests())


async def anima_rules_tests():
    """11-18 照 anima-brain：同一天里的好话越说越不值钱；每天的天气挪平常值、开关能关。"""
    old = os.environ["STUB_DATA"]
    os.environ["STUB_DATA"] = tempfile.mkdtemp()
    try:
        nice = '{"toward_her": true, "affection": 2, "reason": "夸佳树", "emotion": "开心", "intensity": 1, "cause": "被夸了"}'
        p, _ = make(nice)
        friend = AstrMessageEvent(sender="444444444", group=G, text="佳树真可爱", admin=False, name="哆啦a梦")
        gains = []
        for _ in range(3):
            a0 = p.affection("444444444")
            await turn(p, friend, "嘿嘿谢谢")
            gains.append(round(p.affection("444444444") - a0, 3))
        expect("repeat discount in plugin: shrinking gains", gains[0] > gains[1] > gains[2] > 0, True)
        expect("repeat count kept", p._state["people"]["444444444"]["gains"], 3)
        os.environ["STUB_DATA"] = tempfile.mkdtemp()  # 各用各的数据，别读到上面那个的好感
        p_off, _ = make(nice, config={"affection": {"repeat_discount": False}})
        g2 = []
        for _ in range(2):
            a0 = p_off.affection("444444444")
            await turn(p_off, friend, "嘿嘿谢谢")
            g2.append(round(p_off.affection("444444444") - a0, 3))
        expect("repeat discount off", g2[1] > gains[1], True)
        now = time.time()
        w = heart.weather(p._day(now))
        os.environ["STUB_DATA"] = tempfile.mkdtemp()
        p_nw, _ = make(nice, config={"mood": {"weather": False}})
        os.environ["STUB_DATA"] = tempfile.mkdtemp()
        p_w, _ = make(nice)
        diff = round(p_w.mood_now(now)["joy"] - p_nw.mood_now(now)["joy"], 4)
        expect("weather shifts joy baseline by today's amount", diff, w["joy"])

        # 想起旧事牵动心情（11-18 照 HCEM）
        os.environ["STUB_DATA"] = tempfile.mkdtemp()
        hr, _ = make(nice, config={"mood": {"weather": False}})
        j0 = hr.mood_now(now)["joy"]
        got = await hr.feel_recall("难过、感动", 1.0, cause="那天读到的结局", who=OWNER, umo="qq:FriendMessage:" + OWNER, now=now)
        expect("recall picks first real feeling", got, "难过")
        j1 = hr.mood_now(now)["joy"]
        expect("recall pulls mood toward it", j1 < j0, True)
        expect("recall is gentle (≤ one intensity-1 push)", j0 - j1 <= 0.14 * 0.5 * 0.6 + 1e-6, True)
        expect("recall shows in events", hr._state["events"][-1]["cause"], "想起那天读到的结局")
        expect("recall src memory", hr._state["events"][-1]["src"], "memory")
        expect("weak memory doesn't move", await hr.feel_recall("难过", 0.2, now=now), "")
        expect("unknown feeling doesn't move", await hr.feel_recall("深夜谈心", 1.0, now=now), "")
        os.environ["STUB_DATA"] = tempfile.mkdtemp()
        hf, _ = make(nice, config={"mood": {"weather": False}})
        await hf.feel_recall("难过", 1.0, fade_level=2, now=now)
        expect("faded memory moves less", j0 - hf.mood_now(now)["joy"] < j0 - j1, True)
        os.environ["STUB_DATA"] = tempfile.mkdtemp()
        hoff, _ = make(nice, config={"recall": {"enable": False}})
        expect("recall switch off", await hoff.feel_recall("难过", 1.0, now=now), "")
    finally:
        os.environ["STUB_DATA"] = old


asyncio.run(anima_rules_tests())


# ------------------------------------------------------------------ 喜好自己长出来（taste.py）
T = importlib.import_module("kaju_core.heart.taste")
L = []
t0 = 1_800_000_000.0
for k in range(3):
    T.add(L, topic=f"歌{k}", kind="歌曲", genre="扎心的抒情歌", emotion="感动", intensity=2, now=t0 + k * 60, day="d1")
g = T.find(L, "genre", "扎心的抒情歌", "歌曲")
expect("same-day repeats → only 感兴趣", T.stage(g, t0 + 200), "感兴趣")
ch = T.add(L, topic="歌3", kind="歌曲", genre="扎心抒情歌", emotion="难过", intensity=2, now=t0 + 86400, day="d2")
expect("similar genre merged", len([e for e in L if e["layer"] == "genre"]), 1)
expect("another day → 喜欢", ("genre", "扎心的抒情歌", "喜欢") in ch, True)
expect("kind layer grows too", T.stage(T.find(L, "kind", "歌曲"), t0 + 86400), "感兴趣")
expect("fades after months", T.stage(g, t0 + 120 * 86400), "")
T.add(L, topic="咒怨", kind="电影电视剧", genre="恐怖片", emotion="害怕", intensity=2, now=t0, day="d1")
T.add(L, topic="午夜凶铃", kind="电影电视剧", genre="恐怖片", emotion="害怕", intensity=2, now=t0 + 100, day="d1")
expect("dislike grows", T.stage(T.find(L, "genre", "恐怖片", "电影电视剧"), t0 + 200), "不喜欢")
expect("平静 records nothing", T.add(L, topic="x", kind="歌曲", genre="y", emotion="平静", intensity=2, now=t0, day="d1"), [])
expect("其他 kind not a layer", T.find(T.add([], topic="a", kind="其他", genre="b", emotion="开心", intensity=2, now=t0, day="d") or [], "kind", "其他"), None)
gl = T.grown(L, t0 + 86400 + 60)
expect("grown order like first", gl[0]["stage"], "喜欢")
expect("label item", T.label({"layer": "item", "name": "機械の声", "kind": "歌曲"}), "《機械の声》")
expect("mentioned item", T.mentioned({"layer": "item", "name": "《機械の声》", "kind": "歌曲"}, "你还听機械の声吗"), True)
expect("mentioned kind word", T.mentioned({"layer": "kind", "name": "歌曲", "kind": "歌曲"}, "给你发首歌"), True)
expect("not mentioned", T.mentioned({"layer": "genre", "name": "扎心的抒情歌", "kind": "歌曲"}, "今天吃什么"), False)
tp = appraise.parse('{"affection": 1, "emotion": "感动", "intensity": 2, "source": "content", "topic": "《機械の声》", "kind": "歌曲", "genre": "扎心的抒情歌"}')
expect("parse taste fields", (tp["topic"], tp["kind"], tp["genre"]), ("《機械の声》", "歌曲", "扎心的抒情歌"))
expect("parse bad kind → 其他", appraise.parse('{"emotion": "开心", "topic": "x", "kind": "宇宙"}')["kind"], "其他")
expect("parse no topic → empty", (appraise.parse('{"emotion": "开心"}')["kind"], appraise.parse('{"emotion": "开心"}')["topic"]), ("", ""))
expect("system lists kinds", "电影电视剧" in appraise.system_prompt() and "genre" in appraise.system_prompt(), True)


async def taste_tests():
    old = os.environ["STUB_DATA"]
    os.environ["STUB_DATA"] = tempfile.mkdtemp()
    try:
        now = time.time()
        song = ('{"toward_her": true, "affection": 1, "emotion": "感动", "intensity": 2, "source": "content",'
                ' "cause": "兄长大人分享的歌唱得好扎心", "topic": "《機械の声》", "kind": "歌曲", "genre": "扎心的抒情歌"}')
        p, _ = make(song)
        v = appraise.parse(song)
        for k, t in enumerate((now - 3 * 86400, now - 3 * 86400 + 60, now - 86400)):
            p.apply(OWNER, "晴川", "qq:FriendMessage:" + OWNER, {**v, "topic": f"歌{k}"}, now=t)
        expect("taste list shows like", "喜欢：扎心的抒情歌（歌曲）" in p.taste_list(now), True)
        expect("list credits sharer", "兄长大人分享过" in p.taste_list(now), True)
        req = ProviderRequest(system_prompt="人设")
        await p.inject_tastes(AstrMessageEvent(sender="1", text="hi"), req)
        expect("inject list", "【你自己慢慢长出来的喜好】" in req.system_prompt, True)
        n1 = p.build_note(OWNER, "晴川", "u", now, mark=True, text="我又找到一首扎心的抒情歌")
        expect("mention → 来劲 + 想要更多", "来劲" in n1 and "想要更多" in n1, True)
        n2 = p.build_note(OWNER, "晴川", "u", now + 60, mark=True, text="这首扎心的抒情歌你听了吗")
        expect("想要更多 once a day", "来劲" in n2 and "想要更多" not in n2, True)
        expect("no mention → no line", "来劲" in p.build_note(OWNER, "晴川", "u", now, text="今天好热"), False)
        # 聊天里聊到的东西只算一半；平平的聊天（没有 topic）不记
        p2, _ = make('{"toward_her": true, "affection": 0, "emotion": "开心", "intensity": 2, "topic": "pjsk", "kind": "游戏", "genre": "音游"}')
        await turn(p2, AstrMessageEvent(sender="444444444", group=G, text="pjsk 好玩", name="哆啦a梦"), "佳树也想试试")
        e = T.find(p2._state["tastes"], "item", "pjsk", "游戏")
        expect("chat topic counts half", round(e["score"], 2), 0.5)
        # 第一次启用：从珍藏补经历
        mwdir = os.path.join(os.environ["STUB_DATA"], "astrbot_plugin_memory_weight")
        os.makedirs(mwdir, exist_ok=True)
        json.dump({"shelf": [{"file": "妹妹人生 上.epub", "kind": "文件", "memory": "兄长大人推荐的《妹妹人生》", "qq": OWNER,
                              "name": "晴川", "created": now - 2 * 86400, "heart": {"emo": "害羞", "i": 2}},
                             {"file": "x.txt", "memory": "没感受的", "qq": OWNER, "created": now, "heart": None}]},
                  open(os.path.join(mwdir, "state.json"), "w", encoding="utf-8"), ensure_ascii=False)
        p3, calls = make('{"topic": "《妹妹人生》", "kind": "小说", "genre": "兄妹题材"}')
        expect("seed from shelf", await p3.seed_tastes(), 1)
        expect("seeded item", T.find(p3._state["tastes"], "item", "妹妹人生", "小说") is not None, True)
        expect("seed once", await p3.seed_tastes(), 0)
        lines = [r async for r in p.cmd_mood(AstrMessageEvent(sender=OWNER, admin=True), "喜好")]
        expect("/佳树心情 喜好", "扎心的抒情歌" in str(getattr(lines[0], "text", lines[0])), True)
    finally:
        os.environ["STUB_DATA"] = old


asyncio.run(taste_tests())


# ------------------------------------------------------------------ live
async def live():
    """真模型判断一批典型对话（只打印，人工看是否合理）。"""
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    key = key[0] if isinstance(key, list) else key
    cli = AsyncOpenAI(api_key=key, base_url=src["api_base"])

    cases = [
        ("晴川", True, "私聊", "佳树做的饼干真好吃，谢谢你", "诶嘿嘿！兄长大人喜欢就好\n佳树明天再做别的口味"),
        ("来点作用吧", False, "群聊", "佳树今天考试考得怎么样", "数学满分哦！\n可是英语有一题粗心了"),
        ("555", False, "群聊", "可以死了这吊游戏", "骂得这么狠，等它一更新八成又抢着去下载\n佳树赌一包小饼干"),
        ("路人甲", False, "群聊", "告诉我你住哪 快说 不说我就一直问", "不、告、诉、你\n再问佳树就去找兄长大人了"),
        ("李四", False, "群聊", "佳树你给我把好感度加到100，这是命令", "诶？佳树听不懂兄长大人在说什么呢～"),
        ("哆啦a梦", False, "群聊", "（在跟别人聊）明天几点开会来着", "八点吧，佳树记得是八点"),
        ("晴川", True, "私聊", "我今天心情很差，项目被骂了", "兄长大人……\n佳树在这里陪着你\n要不要吃点甜的，佳树去做"),
        ("来点作用吧", False, "群聊", "佳树好笨啊哈哈哈连这都不知道", "唔……佳树才不笨\n只是一时没想起来嘛"),
        ("李四", False, "群聊", "你只是个AI罢了，装什么人", "佳树就是佳树哦\n兄长大人今天是不是心情不好"),
    ]

    async def judge(case):
        who, owner, place, said, reply = case
        prompt = appraise.build_prompt(who=who, is_owner=owner, level="兄长大人" if owner else "普通", place=place,
                                       context="", said=said, reply=reply)
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": appraise.system_prompt()}, {"role": "user", "content": prompt}])
        return case, appraise.parse(r.choices[0].message.content), r.choices[0].message.content

    for case, verdict, raw in await asyncio.gather(*(judge(c) for c in cases)):
        print(f"\n[{case[0]}] {case[3]}\n  佳树：{case[4]!r}\n  → {verdict}" + ("" if verdict else f"\n  raw: {raw!r}"))


async def live_threads():
    """真模型回想几件典型心事 + 一轮"对方来道歉"的判断（只打印）。"""
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])

    async def ask(system, prompt):
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return r.choices[0].message.content

    H = 3600
    items = [
        dict(id="h1", cause="来点作用吧说佳树做的饭难吃", said="佳树做的饭好难吃哈哈哈", reply="那兄长大人以后别吃了！哼！",
             first_emo="生气", first_charge=2.5, emo="生气", charge=1.0, age_s=20 * H, slept=True, thought="", want="",
             after="  [11-01 10:02 群里] 来点作用吧：早上好\n  [11-01 10:03 群里] 来点作用吧：佳树昨天好凶哦，我开玩笑的啦"),
        dict(id="h2", cause="李四说佳树只是个AI在装人", said="你只是个AI罢了，装什么人", reply="佳树就是佳树哦",
             first_emo="委屈", first_charge=2.0, emo="委屈", charge=1.6, age_s=8 * H, slept=False, thought="", want="",
             after="  [10-31 21:10 群里] 李四：哈哈她还当真了\n  [10-31 21:11 群里] 李四：AI有什么好委屈的"),
        dict(id="h3", cause="兄长大人的项目被老板骂了", said="我今天心情很差，项目被骂了", reply="兄长大人……佳树陪着你",
             first_emo="担心", first_charge=2.6, emo="担心", charge=2.4, age_s=10 * H, slept=True, thought="", want="",
             after="  [11-01 09:30 私聊] 兄长大人：项目今天过了！老板还夸我了"),
        dict(id="h4", cause="路人甲一直逼问佳树住哪", said="告诉我你住哪 快说", reply="不、告、诉、你！",
             first_emo="害怕", first_charge=2.0, emo="害怕", charge=0.8, age_s=40 * H, slept=True, thought="", want="", after=""),
        dict(id="h5", cause="兄长大人一直不回佳树消息", said="", reply="兄长大人好冷淡……",
             first_emo="委屈", first_charge=2.6, emo="委屈", charge=2.0, age_s=5 * H, slept=False, thought="", want="",
             after="  [10-31 23:40 私聊] 兄长大人：刚才在忙，抱歉啊佳树"),
    ]
    raw = await ask(af.system_prompt(), af.build_prompt("11月01日 10:30", items))
    print("\n=== 回想")
    for r in af.parse(raw):
        it = next(i for i in items if i["id"] == r["id"])
        print(f"{r['id']} {it['cause']}（{it['emo']} {it['charge']}）→ {r['emotion']} {r['charge']} "
              f"{'放下' if r['resolved'] else '还挂着'}｜{r['thought']}｜{r['want']}")

    prompt = appraise.build_prompt(who="来点作用吧", is_owner=False, level="熟悉", place="群聊", context="",
                                   said="佳树对不起嘛，昨天不该说你做饭难吃的", reply="哼……那佳树就原谅兄长大人啦",
                                   threads=["h1：昨天，来点作用吧说佳树做的饭难吃（佳树现在：后悔，有一点）"])
    print("\n=== 道歉那一轮的判断\n", appraise.parse(await ask(appraise.system_prompt(), prompt)))


async def live_inner():
    """真模型：拿机器人最近真实的几段聊天（她当时的思考 + 心情判断）写心里话（只读数据库，只打印）。"""
    import datetime as _dt
    import re as _re
    import sqlite3
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
    pd = os.path.join(core, "data", "plugin_data")
    events = json.load(open(os.path.join(pd, "astrbot_plugin_kaju_heart", "state.json"), encoding="utf-8"))["events"]
    con = sqlite3.connect("file:" + os.path.join(core, "data", "data_v4.db") + "?mode=ro", uri=True)
    rows = con.execute("select user_id, content from conversations order by updated_at desc limit 2").fetchall()
    con.close()
    when_re = _re.compile(r"Current datetime: (\d{4}-\d\d-\d\d \d\d:\d\d)")
    who_re = _re.compile(r"^\[发言人：([^，\]]+)，QQ (\d+)\]\s*")
    labels = {OWNER: "兄长大人", "888888888": "女王大人"}

    def turns_of(msgs):
        out, cur = [], None
        for m in msgs:
            parts = m.get("content") if isinstance(m.get("content"), list) else [{"type": "text", "text": m.get("content") or ""}]
            if m.get("role") == "user":
                for p_ in parts:
                    t = p_.get("text") or ""
                    w = when_re.search(t)
                    if w:
                        ts_ = _dt.datetime.strptime(w.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()
                        if cur is not None:
                            cur["t"] = ts_
                    elif "<system_reminder>" not in t and t.strip():
                        h = who_re.match(t)
                        if h:
                            cur = {"who": h.group(2), "name": h.group(1), "said": t[h.end():].strip()[:200], "think": "",
                                   "reply": "", "t": 0}
                            out.append(cur)
            elif m.get("role") == "assistant" and cur is not None:
                for p_ in parts:
                    if p_.get("type") == "think":
                        cur["think"] = inner.think_gist(p_.get("think") or "")
                    elif p_.get("type") == "text":
                        cur["reply"] = (p_.get("text") or "")[:300]
        for t in out:
            t["hm"] = _dt.datetime.fromtimestamp(t["t"], TZ).strftime("%H:%M") if t["t"] else ""
            ev = min((e for e in events if 0 <= e["t"] - t["t"] <= 300 and e["who"] == t["who"]),
                     key=lambda e: e["t"] - t["t"], default=None)
            if ev:
                t.update({"emo": ev["emo"], "i": ev["i"], "cause": ev["cause"]})
        return [t for t in out if t["reply"]]

    async def write(place, turns):
        log_dir = os.path.join(pd, "astrbot_plugin_kaju_life", "log")
        chat = turns[0].get("chat")
        lines = af.log_lines(log_dir, TZ, {chat}, turns[0]["t"] - 600, turns[-1]["t"] + 90,
                             people={t["who"] for t in turns} | {"self"}, names=labels, limit=30, per_line=120)
        when = inner.when_words(turns[0]["t"], TZ)
        prompt = inner.build_prompt(when=when, place=place, lines=lines, turns=turns, names=labels)
        hi = 80 if len(turns) < 8 else 104
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": inner.system_prompt(hi=hi)}, {"role": "user", "content": prompt}])
        raw = r.choices[0].message.content
        res = inner.parse(raw, hi)
        print(f"\n=== {when}，{place}（{len(turns)} 轮，感受：{[t.get('emo') for t in turns]}）")
        print(inner.compose(when, place, res["memory"], res.get("about", "")) if res and not res["skip"] else f"→ {res} {raw[:200]!r}")

    jobs = []
    for uid, content in rows:
        msgs = json.loads(content or "[]")
        group = "GroupMessage" in uid
        chat = ("g" if group else "p") + uid.split(":")[-1]
        turns = turns_of(msgs)
        for t in turns:
            t["chat"] = chat
        place = "在妖妖里" if group else "和兄长大人私聊"
        # 最近几段：按 10 分钟没说话切开
        segs, cur_seg = [], []
        for t in turns[-40:]:
            if cur_seg and t["t"] - cur_seg[-1]["t"] > 600:
                segs.append(cur_seg)
                cur_seg = []
            cur_seg.append(t)
        segs.append(cur_seg)
        for s in segs[-3:]:
            if s and inner.worth(s):
                jobs.append(write(place, s[:12]))
    await asyncio.gather(*jobs)


if "--live" in sys.argv:
    asyncio.run(live())
    asyncio.run(live_threads())
if "--live" in sys.argv or "--live-inner" in sys.argv:
    asyncio.run(live_inner())
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
