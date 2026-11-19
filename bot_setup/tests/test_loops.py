"""Offline tests for 未了的事 (kaju_core/memory/loops.py + MemoryMind 接线). Model is faked; nothing live is touched.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_loops.py
Exit code 0 = all passed.
"""

import asyncio
import datetime as dt
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
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
from kaju_core.memory import loops, rater  # noqa: E402
from memory_weight.main import MemoryWeight  # noqa: E402

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


DAY = 86400.0
TODAY = dt.date(2026, 11, 18)  # 周三
NOW = dt.datetime(2026, 11, 18, 12, 0, tzinfo=TZ).timestamp()

# ------------------------------------------------------------------ 纯逻辑
base = {"imp": 7, "care": 1.5, "created": NOW, "last_seen": NOW}  # care 1.5/3 = A 0.5
expect("priority no date = I(1+A)", round(loops.priority(base, NOW, TODAY), 2), 10.5)
expect("priority tomorrow +1", round(loops.priority({**base, "date": "2026-11-19"}, NOW, TODAY), 2), 11.5)
expect("priority yesterday == tomorrow", loops.priority({**base, "date": "2026-11-17"}, NOW, TODAY),
       loops.priority({**base, "date": "2026-11-19"}, NOW, TODAY))
expect("priority 90 days ~0.47", round(loops.priority(base, NOW + 90 * DAY, TODAY), 2), 0.47)
expect("when tomorrow", loops.when_text({"date": "2026-11-19"}, TODAY), "11月19日周四，明天")
expect("when in 6 days", loops.when_text({"date": "2026-11-24"}, TODAY), "11月24日周二，还有6天")
expect("when 3 days ago", loops.when_text({"date": "2026-11-15"}, TODAY), "11月15日周日，已经过去3天")
expect("when no date", loops.when_text({"date": ""}, TODAY), "")
expect("today text", loops.today_text(TODAY), "2026-11-18（周三）")
expect("calendar next tue", "2026-11-24 下周二" in loops.calendar_text(TODAY) and "2026-11-19 这周四（明天）" in loops.calendar_text(TODAY), True)
expect("parse_date junk", loops.parse_date("下周二"), None)
SAT = dt.date(2026, 11, 14)
for expr, want in (("下周二", "2026-11-17"), ("周二", "2026-11-17"), ("这周五", "2026-11-13"), ("下下周一", "2026-11-23"),
                   ("明天", "2026-11-15"), ("后天下午", "2026-11-16"), ("11月20号", "2026-11-20"), ("20号", "2026-11-20"),
                   ("2号", "2026-12-02"), ("1月3日", "2027-01-03"), ("周日", "2026-11-15"), ("过几天", None), ("", None)):
    got = loops.resolve_when(expr, SAT)
    expect(f"when {expr!r}", got.isoformat() if got else None, want)
expect("parse json fenced", loops.parse_json('```json\n{"new": [], "update": []}\n```'), {"new": [], "update": []})

OWNER, QUEEN, GROUP = "111111111", "333333333", "222222222"
batch = [
    {"u": OWNER, "n": "晴川", "x": "下周二我有日语考试，有点慌", "ts": NOW},
    {"u": "self", "n": "佳树", "x": "兄长大人加油！", "ts": NOW},
    {"u": OWNER, "n": "晴川", "x": "嗯", "ts": NOW},
]
L = []
data = {"new": [{"i": 1, "what": "兄长大人下周二有日语考试，还不知道考得怎样", "date": "2026-11-24", "imp": 7, "care": 2, "kw": ["日语", "考试"]},
                {"i": 2, "what": "佳树自己的事", "date": "", "imp": 3, "care": 0},   # 佳树说的 → 不收
                {"i": 9, "what": "编号越界", "imp": 3}, {"i": 0, "what": "编号 0", "imp": 3}],
        "update": []}
data["new"][0]["when"] = "下周二"
data["new"][0]["date"] = "2026-11-25"  # 模型数错了：以原话为准
expect("apply adds only valid", loops.apply(L, data, batch, f"p{OWNER}", NOW, lambda ts: TODAY), (1, 0))
expect("loop fields", (L[0]["qq"], L[0]["date"], L[0]["imp"], L[0]["care"], L[0]["kw"]),
       (OWNER, "2026-11-24", 7, 2, ["日语", "考试"]))
expect("same thing not duplicated", loops.apply(L, {"new": [{"i": 1, "what": "兄长大人下周二有日语考试，不知道考得怎样"}]},
                                                batch, f"p{OWNER}", NOW), (0, 0))

# 给不给她看
kw_of = lambda lp: set()  # noqa: E731
expect("private: far date, low priority, no cue -> none",
       loops.pick(L, OWNER, f"p{OWNER}", {"晚饭"}, kw_of, NOW, TODAY), [])
expect("private: cue word -> shown", [lp["id"] for lp in loops.pick(L, OWNER, f"p{OWNER}", {"考试"}, kw_of, NOW, TODAY)], [L[0]["id"]])
day_before = dt.date(2026, 11, 23)
expect("near date -> shown", len(loops.pick(L, OWNER, f"p{OWNER}", set(), kw_of, NOW + 5 * DAY, day_before)), 1)
small = [{**L[0], "id": "s1", "imp": 3, "kw": []}]
expect("small thing: near date not enough", len(loops.pick(small, OWNER, f"p{OWNER}", set(), kw_of, NOW + 5 * DAY, day_before)), 0)
expect("small thing: cue ok", len(loops.pick(small, OWNER, f"p{OWNER}", {"日语"}, lambda lp: {"日语"}, NOW + 5 * DAY, day_before)), 1)
L[0]["last_shown"] = NOW + 5 * DAY
expect("cooldown blocks near-date", len(loops.pick(L, OWNER, f"p{OWNER}", set(), kw_of, NOW + 5 * DAY + 3600, day_before)), 0)
expect("cooldown doesn't block cue", len(loops.pick(L, OWNER, f"p{OWNER}", {"日语"}, kw_of, NOW + 5 * DAY + 3600, day_before)), 1)
expect("other person sees nothing", loops.pick(L, QUEEN, f"p{QUEEN}", {"考试"}, kw_of, NOW, TODAY), [])
expect("group doesn't see private loop", loops.pick(L, OWNER, f"g{GROUP}", {"考试"}, kw_of, NOW, TODAY), [])
expect("note line", loops.note_lines(L, TODAY, TZ), ["- 11月18日说的：兄长大人下周二有日语考试，还不知道考得怎样（11月24日周二，还有6天）"])

# 下文：日子改了 / 有结果
expect("update date", loops.apply(L, {"update": [{"id": L[0]["id"][:6], "status": "open", "date": "2026-11-25"}]}, [], "", NOW), (0, 1))
expect("date moved", (L[0]["date"], L[0]["status"]), ("2026-11-25", "open"))
loops.apply(L, {"update": [{"id": L[0]["id"][:6], "status": "done", "result": "考完了，觉得还行"}]}, [], "", NOW + 7 * DAY)
expect("done", (L[0]["status"], L[0]["result"]), ("done", "考完了，觉得还行"))
expect("done not shown", loops.pick(L, OWNER, f"p{OWNER}", {"考试"}, kw_of, NOW, TODAY), [])
expect("done can't be updated again", loops.apply(L, {"update": [{"id": L[0]["id"][:6], "status": "drop"}]}, [], "", NOW), (0, 0))

# 收起
S = [{**base, "id": "a1", "qq": OWNER, "chat": "p1", "what": "x", "status": "open", "date": "2026-11-05"},
     {**base, "id": "a2", "qq": OWNER, "chat": "p1", "what": "y", "status": "open", "date": "2026-11-15"},
     {**base, "id": "a3", "qq": OWNER, "chat": "p1", "what": "z", "status": "open", "date": "", "created": NOW - 120 * DAY,
      "last_seen": NOW - 120 * DAY, "care": 0}]
expect("tidy: >7d past + old undated", loops.tidy(S, NOW, TODAY), 2)
U = [{**base, "id": "u1", "qq": OWNER, "chat": "p1", "what": "w", "status": "open", "date": "", "imp": 10, "care": 3,
      "last_seen": NOW - 15 * DAY}]
expect("tidy: undated quiet 15d", (loops.tidy(U, NOW, TODAY), U[0]["status"]), (1, "stale"))
expect("tidy statuses", [s["status"] for s in S], ["stale", "open", "stale"])

# ------------------------------------------------------------------ 接进 MemoryWeight
LIFE = os.path.join(DATA, "astrbot_plugin_kaju_life", "log")
os.makedirs(LIFE)


def write_log(day, rows):
    with open(os.path.join(LIFE, day + ".jsonl"), "a", encoding="utf-8") as f:
        for t, c, u, n, x in rows:
            f.write(json.dumps({"t": t, "c": c, "u": u, "n": n, "x": x}, ensure_ascii=False) + "\n")


write_log("2026-11-16", [  # 补看的旧记录
    ("20:00", f"p{OWNER}", OWNER, "晴川", "我明天要去医院复查一下"),
    ("20:01", f"p{OWNER}", "self", "佳树", "要佳树陪着吗"),
])
write_log("2026-11-18", [
    ("10:00", f"g{GROUP}", QUEEN, "来点作用吧", "抽卡又歪了，下周面试也好烦"),  # 她不在场 → 不看
    ("10:01", f"g{GROUP}", "444444444", "哆啦a梦", "哈哈"),
])

prompts = []


async def fake_loop_ask(system, prompt):
    prompts.append(prompt)
    new = prompt.split("【新消息】\n")[1].split("\n\n")[0]
    if "医院复查" in new:
        return json.dumps({"new": [{"i": 1, "what": "兄长大人要去医院复查，还不知道结果", "date": "2026-11-17", "imp": 7,
                                    "care": 2, "kw": ["医院", "复查"]}], "update": []}, ensure_ascii=False)
    if "复查结果" in new:
        known = prompt.split("【已经记着的还没结果的事】")[1]
        lid = known.split("\n")[1].split(":")[0]
        return json.dumps({"new": [], "update": [{"id": lid, "status": "done", "result": "没事"}]}, ensure_ascii=False)
    return '{"new": [], "update": []}'


async def main():
    mw = MemoryWeight(Context(), {"first_delay_seconds": 99999, "keepsake": {"enable": True}, "paragraph": {"enable": False},
                                  "loops": {"seed_days": 7}})
    if mw._task:
        mw._task.cancel()
    mw._loop_ask = fake_loop_ask

    async def no_keep(system, prompt):
        return '{"mood": "闲聊", "level": 0, "keep": [], "scores": []}'
    mw._ask = no_keep

    now = dt.datetime(2026, 11, 18, 12, 0, tzinfo=TZ).timestamp()
    stats = await mw.tick(now)
    expect("seeded once", bool(mw._state.get("loops_seeded")), True)
    expect("group w/o her not sent to model", any("下周面试" in p for p in prompts), False)
    open_ = [lp for lp in mw._state["loops"] if lp["status"] == "open"]
    expect("seed found hospital", [lp["what"] for lp in open_], ["兄长大人要去医院复查，还不知道结果"])
    expect("seed prompt used the old day's date", any("[11-16 周一 20:00]" in p for p in prompts), True)

    # 第二次 tick 不再补看
    n = len(prompts)
    await mw.tick(now + 60)
    expect("no second seed", len(prompts), n)

    # 私聊：碰到"医院" → 给她看
    req = ProviderRequest(system_prompt="人设")
    ev = AstrMessageEvent(sender=OWNER, text="今天医院人好多")
    await mw.inject_loops(ev, req)
    expect("note injected", "【还没结果的事】下面是兄长大人以前提过" in req.system_prompt, True)
    expect("note has date words", "11月17日周二" in req.system_prompt, True)
    expect("extra set", len(ev.get_extra("memory_weight_loops", [])), 1)
    # 群里：私聊的事不给
    req_g = ProviderRequest(system_prompt="人设")
    await mw.inject_loops(AstrMessageEvent(sender=OWNER, group=GROUP, text="今天医院人好多"), req_g)
    expect("group: private loop hidden", req_g.system_prompt, "人设")

    # 新的聊天：有了结果 → done
    write_log("2026-11-18", [
        ("12:30", f"p{OWNER}", OWNER, "晴川", "复查结果出来了，没事"),
        ("12:31", f"p{OWNER}", "self", "佳树", "太好了！"),
    ])
    await mw.tick(now + 3600)
    expect("known loop listed in prompt", "兄长大人 - 兄长大人要去医院复查" in prompts[-1], True)
    expect("closed by follow-up", [lp["status"] for lp in mw._state["loops"]], ["done"])
    req2 = ProviderRequest(system_prompt="人设")
    await mw.inject_loops(AstrMessageEvent(sender=OWNER, text="医院"), req2)
    expect("closed not shown", req2.system_prompt, "人设")

    rep = mw.report("未了", now + 3600)
    expect("report lists it", "有了结果" in rep or "有结果了" in rep, True)
    expect("calendar in prompt", "2026-11-24 下周二" in prompts[-1], True)
    expect("lines carry their date", "[11-18 周三 12:30]" in prompts[-1], True)
    seed_p = next(p for p in prompts if "医院复查" in p)
    expect("seed prompt multi-day span", "这段聊天是 2026-11-16（周一） 到" in seed_p or "今天是 2026-11-16" in seed_p, True)

    # reset_token：换新值 → 清掉、重看一遍；同一个值不再触发
    n = len(prompts)
    mw.config["loops"]["reset_token"] = "r2"
    await mw.tick(now + 7200)
    expect("reset reseeds", len(prompts) > n and mw._state.get("loops_reset") == "r2", True)
    # 补看时 11-16 和 11-18 的私聊在同一段里，假模型只认“医院复查” → 又记成 open（真模型看得到后面那句结果）
    expect("reset rebuilt from logs", [lp["what"] for lp in mw._state["loops"]], ["兄长大人要去医院复查，还不知道结果"])
    n = len(prompts)
    await mw.tick(now + 7300)
    expect("same token no reseed", len(prompts), n)

    # 关掉开关：不注入、不看
    mw.config["loops"]["enable"] = False
    req3 = ProviderRequest(system_prompt="人设")
    await mw.inject_loops(AstrMessageEvent(sender=OWNER, text="医院"), req3)
    expect("disabled: nothing", req3.system_prompt, "人设")
    await mw.terminate()


asyncio.run(main())
print("FAILED:" if failures else "all passed", *failures)
sys.exit(1 if failures else 0)
