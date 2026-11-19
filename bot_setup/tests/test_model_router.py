r"""挑主模型（kaju_basics/router.py）和共用成绩（kaju_core/senses/health.py）。不连 AstrBot、不发请求。
    <venv>\Scripts\python.exe -I tests\test_model_router.py
"""
import asyncio
import json
import math
import os
import sys
import tempfile
import time
import types

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from kaju_core.senses import health  # noqa: E402

fails = []


def expect(name, got, want):
    if got != want:
        fails.append(name)
        print("FAIL", name, "\n  got ", got, "\n  want", want)


def fresh_health():
    health._path_override = os.path.join(tempfile.mkdtemp(), "model_health.json")
    health._state = {"accounts": {}, "slots": {}}
    health._mtime = 0.0
    health.configure(2, 10)


# ------------------------------------------------------------------ health
fresh_health()
acc = health.account("https://api.example.com/v1", "sk-abc")
expect("账号不含 key 本身", "sk-abc" in acc, False)
expect("账号带主机", acc.startswith("api.example.com#"), True)
expect("同主机不同 key 不同账号", acc == health.account("https://api.example.com", "sk-xyz"), False)
expect("一次失败不冷却", health.record(acc, "s1", False, 50, True, "502", now=1000), False)
expect("一次失败 cooled=0", health.cooled(acc, now=1001), 0.0)
expect("第二次失败进冷却", health.record(acc, "s1", False, 50, True, "502", now=1100), True)
expect("冷却 10 分钟", round(health.cooled(acc, now=1100)), 600)
expect("失败的耗时算无穷大", math.isinf(health.latency("s1", big=True)), True)
expect("成功一次解除冷却", (health.record(acc, "s1", True, 4, False, now=1200), health.cooled(acc, now=1201)), (False, 0.0))
expect("大小请求分开记", health.latency("s1", big=False), 4)
# 另一份模块（热重载前后）通过文件看得到
health._state = {"accounts": {}, "slots": {}}
health._mtime = 0.0
expect("从文件读回成绩", health.latency("s1", big=False), 4)
expect("中位数", (health.record(acc, "s2", True, 2, True, now=1300), health.record(acc, "s2", True, 9, True, now=1301),
                  health.record(acc, "s2", True, 3, True, now=1302), health.latency("s2", big=True))[-1], 3)
k1 = {"base_url": "https://a.test", "api_key": "k1", "model": "m"}
k2 = {"base_url": "https://b.test", "api_key": "k2", "model": "m"}
a1 = health.account(k1["base_url"], k1["api_key"])
health.record(a1, "x", False, 1, now=2000)
health.record(a1, "x", False, 1, now=2001)
expect("冷却的 key 挪到最后", [k["api_key"] for k in health.order_keys([k1, k2], now=2002)], ["k2", "k1"])
expect("没冷却照原顺序", [k["api_key"] for k in health.order_keys([k1, k2], now=9999)], ["k1", "k2"])

# ------------------------------------------------------------------ rank
from kaju_basics import router  # noqa: E402

fresh_health()
CFG = {"budget_high": 25, "budget_low": 12, "price_weight": 0.5, "think_bonus": 1.0}


def cand(pid, acc, q, price, think="", secs=8):
    return {"pid": pid, "account": acc, "slot": f"{acc}|{pid}", "quality": q, "price": price, "think": think, "secs": secs}


cs = [cand("aigo", "aigo#1", 9, 2, "high"), cand("aigo_low", "aigo#1", 8, 2, "low", 6),
      cand("hardys", "hardys#1", 6, 1, "", 30), cand("daitu", "daitu#1", 8, 3, "", 20),
      cand("bb15", "bb#15", 8, 0.5, "low", 10), cand("bb15_high", "bb#15", 9, 0.5, "high", 15)]
order = [x["pid"] for x in router.rank(cs, "high", CFG, now=5000)]
expect("high：便宜的同款 3.8 高档打头，同账号另一档放后面",
       order, ["bb15_high", "aigo", "daitu", "hardys", "bb15", "aigo_low"])
order = [x["pid"] for x in router.rank(cs, "low", CFG, now=5000)]
expect("low：低档优先；预算内的同账号第二档（aigo）在超预算的（bb15_high 15s）前面",
       order, ["bb15", "aigo_low", "daitu", "hardys", "aigo", "bb15_high"])
# bb-api 挂了：冷却 → 放最后
health.record("bb#15", "bb#15|bb15_high", False, 7, True, now=5000)
health.record("bb#15", "bb#15|bb15_high", False, 7, True, now=5001)
r = router.rank(cs, "high", CFG, now=5002)
expect("冷却的账号两档都在最后", sorted(x["pid"] for x in r[-2:]), ["bb15", "bb15_high"])
expect("冷却写了原因", r[-1]["why"].startswith("冷却中"), True)
# aigocode 实测很慢 → 超预算，让给 daitu
for t in range(3):
    health.record("aigo#1", "aigo#1|aigo", True, 48, True, now=5100 + t)
r = [x["pid"] for x in router.rank(cs, "high", CFG, now=5200)]
expect("实测 48s 的 aigocode 让给预算内的（低档还没成绩先试）", (r[:2], r.index("aigo") > r.index("daitu")), (["aigo_low", "daitu"], True))
# 只有探测（小请求）失败过、还没有大请求成绩：当最慢
fresh_health()
health.record("daitu#1", "daitu#1|daitu", False, 60, False, now=6000)
r = router.rank([cand("daitu", "daitu#1", 8, 3, "", 20), cand("hardys", "hardys#1", 6, 1, "", 10)], "high", CFG, now=6001)
expect("探测没答上来的排后面", [x["pid"] for x in r], ["hardys", "daitu"])
expect("原因：最近都没答上来", r[1]["why"], "最近都没答上来")

# 2026-11-15 实际情形：bb-api 高档大请求 429 → 探测（小请求）成功清了失败 → 低档没大请求成绩、按预估排第一
fresh_health()
CFG2 = dict(CFG, big_bad_minutes=15, share_tiers=True)
c15 = {"pid": "bb15", "account": "bb#15", "slot": "bb#15|flash|bb15", "quality": 9, "price": 0.5, "think": "low", "secs": 10}
c15h = {"pid": "bb15_high", "account": "bb#15", "slot": "bb#15|flash|bb15_high", "quality": 9, "price": 0.5, "think": "high", "secs": 15}
ccl = {"pid": "claude", "account": "cl#1", "slot": "cl#1|sonnet|claude", "quality": 8, "price": 1, "think": "", "secs": 5}
health.record("bb#15", c15h["slot"], False, 20, True, "429", now=8000)
health.record("bb#15", c15h["slot"], True, 3, False, now=8300)  # 探测“回一个字”成功
expect("探测成功照样清 streak", health.streak("bb#15"), 0)
r = router.rank([c15, c15h, ccl], "low", CFG2, now=8360)
expect("大请求失败 15 分钟内：低档也不打头", r[0]["pid"], "claude")
expect("原因写明大请求", r[1]["why"].startswith("最近大请求没答上来"), True)
expect("不传 big_bad_minutes（出卡 / 看图）照旧", router.rank([c15, ccl], "low", CFG, now=8360)[0]["pid"], "bb15")
r = router.rank([c15, ccl], "low", CFG2, now=8000 + 16 * 60)
expect("15 分钟后再给一次机会（借高档成绩：失败=最慢）", [x["pid"] for x in r], ["claude", "bb15"])
health.record("bb#15", c15["slot"], True, 6, True, now=9000)
expect("真的大请求成功才清掉", health.big_fail_ago("bb#15", now=9001), None)
expect("清掉以后按自己的成绩排", router.rank([c15, ccl], "low", CFG2, now=9001)[0]["pid"], "bb15")
fresh_health()
health.record("bb#15", c15h["slot"], True, 4, True, now=8000)
expect("没成绩的档借同模型别档的成绩", round(router.rank([c15], "low", CFG2, now=8001)[0]["est"]), 4)

# ------------------------------------------------------------------ situation


class Ev:
    def __init__(self, text, private=False, extra=None):
        self.message_str = text
        self._p = private
        self._extra = extra or {}

    def is_private_chat(self):
        return self._p

    def get_extra(self, k):
        return self._extra.get(k)


expect("私聊 high", router.situation(Ev("嗯", True)), "high")
expect("群里问句 high", router.situation(Ev("你吃了吗？")), "high")
expect("群里长消息 high", router.situation(Ev("今" * 30)), "high")
expect("群里闲聊 low", router.situation(Ev("wwww")), "low")
expect("群里纠正她 high", router.situation(Ev("没叫你吧")), "high")
expect("群里叫她判断 high（11-19）", router.situation(Ev("主机端刚上线，你判断一下PC端得什么配置")), "high")
expect("群里比较 high", router.situation(Ev("这俩哪个划算")), "high")
expect("群里普通一句仍 low", router.situation(Ev("不是ps限定吗现在")), "low")


class QuoteEv(Ev):
    def __init__(self, text, quoted_sender):
        super().__init__(text)
        self._q = quoted_sender

    def get_self_id(self):
        return "555555555"

    def get_messages(self):
        Reply = type("Reply", (), {})
        r = Reply()
        r.sender_id = self._q
        return [r]


expect("引用她的话 high", router.situation(QuoteEv("确实", "555555555")), "high")
expect("引用别人的话 low", router.situation(QuoteEv("确实", "111111111")), "low")

# ------------------------------------------------------------------ 装进 AstrBot（假的 astr_main_agent / 提供方）
fresh_health()


class Prov:
    def __init__(self, pid, base, key, model="m"):
        self.provider_config = {"id": pid, "api_base": base, "key": [key], "model": model, "enable": True}

    def get_keys(self):
        return self.provider_config["key"]

    async def text_chat(self, **kw):
        if self.provider_config["id"] == "bad":
            raise RuntimeError("502 Upstream")
        return types.SimpleNamespace(role="assistant", completion_text="好")


class Prov2(Prov):
    pass


provs = {"aigo": Prov("aigo", "https://aigo.test", "k1"), "hardys": Prov("hardys", "https://hardys.test", "k2"),
         "bad": Prov2("bad", "https://bad.test", "k3")}
calls = []


class Ctx:
    provider_manager = types.SimpleNamespace(provider_insts=list(provs.values()))

    def get_config(self):
        return {"agent_runner": {"config": {"model": {"provider_id": "aigo", "fallback_provider_ids": ["hardys", "bad"]}}}}

    def get_provider_by_id(self, pid):
        return provs.get(pid)

    async def llm_generate(self, chat_provider_id, prompt):
        calls.append(chat_provider_id)
        return await provs[chat_provider_id].text_chat(prompt=prompt)


am = types.ModuleType("astrbot.core.astr_main_agent")


async def _select_provider(event, plugin_context):
    return provs["aigo"]


def _get_fallback_chat_providers(provider, plugin_context, fallback_ids):
    return [provs[i] for i in fallback_ids if i in provs and provs[i] is not provider]


am._select_provider = _select_provider
am._get_fallback_chat_providers = _get_fallback_chat_providers
sys.modules["astrbot.core.astr_main_agent"] = am
import astrbot.core  # noqa: E402

astrbot.core.astr_main_agent = am

table = os.path.join(tempfile.mkdtemp(), "model_router.json")
with open(table, "w", encoding="utf-8") as f:
    json.dump({"models": {"aigo": {"quality": 9, "price": 2, "secs": 8}, "hardys": {"quality": 6, "price": 1, "secs": 5},
                          "bad": {"quality": 9, "price": 0, "secs": 5}}}, f)
router.table_path = lambda: table
logs = []
rt = router.Router(Ctx(), lambda: {"enable": True, **CFG}, logs.append)
expect("装上", rt.install(), True)
patched_cls = {c.__name__ for c in (Prov, Prov2) if router.ORIG in c.__dict__}
expect("两个提供方类都记成绩", patched_cls, {"Prov", "Prov2"})


async def agent_flow(ev):
    p = await am._select_provider(ev, None)
    return [router._pid(p)] + [router._pid(x) for x in am._get_fallback_chat_providers(p, None, ["hardys", "bad"])]


expect("没成绩：bad 分最高打头", asyncio.run(agent_flow(Ev("在吗？"))), ["bad", "aigo", "hardys"])


async def fail_twice():
    for _ in range(2):
        try:
            await provs["bad"].text_chat(prompt="x")
        except RuntimeError:
            pass


asyncio.run(fail_twice())
expect("text_chat 失败被记上、进冷却", health.cooled(router.account_of(provs["bad"])) > 0, True)
expect("冷却写了日志", any("先冷却" in x for x in logs), True)
expect("冷却后排到最后", asyncio.run(agent_flow(Ev("在吗？"))), ["aigo", "hardys", "bad"])
expect("别处点名用哪个模型就不管", asyncio.run(agent_flow(Ev("x", extra={"selected_provider": "hardys"})))[0], "aigo")
expect("挑模型写了日志", any(x.startswith("kaju_basics: 挑模型（high）aigo") for x in logs), True)

# 只认文字的（Claude）：带图 / 引用了图的消息不让它上；纯文字可以打头，但后备里总有能看图的
class Image:
    pass


class Plain:
    pass


class Video:
    pass


class Reply:
    def __init__(self, chain):
        self.chain = chain


class EvM(Ev):
    def __init__(self, text, chain, private=True):
        super().__init__(text, private)
        self._chain = chain

    def get_messages(self):
        return self._chain


expect("纯文字没有媒体", router.has_media(EvM("x", [Plain()])), False)
expect("带图", router.has_media(EvM("x", [Plain(), Image()])), True)
expect("引用了图", router.has_media(EvM("x", [Reply([Image()]), Plain()])), True)
provs["claude"] = Prov("claude", "https://claude.test", "kc")
Ctx.provider_manager.provider_insts.append(provs["claude"])
with open(table, "w", encoding="utf-8") as f:
    json.dump({"models": {"aigo": {"quality": 9, "price": 2, "secs": 8}, "hardys": {"quality": 6, "price": 1, "secs": 5},
                          "bad": {"quality": 9, "price": 0, "secs": 5},
                          "claude": {"quality": 10, "price": 0, "secs": 5, "text_only": True}}}, f)
os.utime(table, (time.time() + 7, time.time() + 7))
fresh_health()
expect("纯文字：Claude 打头", asyncio.run(agent_flow(EvM("在吗？", [Plain()])))[0], "claude")
expect("带图：Claude 不在里面", "claude" in asyncio.run(agent_flow(EvM("看这个？", [Image()]))), False)
# 2026-11-19：看图的 Gemini 开着时，只带图的消息图会先变成文字 → Claude 排在所有能看图的后面兜底
rt.images_become_text = lambda: True
flow = asyncio.run(agent_flow(EvM("看这个？", [Image()])))
expect("图会变文字：打头的能看图", flow[0] != "claude", True)
expect("图会变文字：Claude 照成绩排第二（不再接在最后）", flow[1], "claude")
tbl = {"c": {"text_only": True}}
expect("head_can_see 挪能看图的到最前", [x["pid"] for x in router.head_can_see([{"pid": "c"}, {"pid": "a"}, {"pid": "b"}], tbl)], ["a", "c", "b"])
expect("head_can_see 全是 Claude 照原样", [x["pid"] for x in router.head_can_see([{"pid": "c"}], tbl)], ["c"])
expect("带视频：照样没有 Claude", "claude" in asyncio.run(agent_flow(EvM("看这个？", [Image(), Video()]))), False)
expect("图太多（7 张）：没有 Claude", "claude" in asyncio.run(agent_flow(EvM("看", [Image()] * 7))), False)
rt.images_become_text = lambda: False
only = [x["pid"] for x in rt.order("high", text_ok=True)]
expect("后备里有能看图的", any(p != "claude" for p in only[1:]), True)
del provs["claude"]  # 后面的测试不带它
Ctx.provider_manager.provider_insts.remove(next(p for p in Ctx.provider_manager.provider_insts if router._pid(p) == "claude"))
with open(table, "w", encoding="utf-8") as f:
    json.dump({"models": {"aigo": {"quality": 9, "price": 2, "secs": 8}, "hardys": {"quality": 6, "price": 1, "secs": 5},
                          "bad": {"quality": 9, "price": 0, "secs": 5}}}, f)
os.utime(table, (time.time() + 14, time.time() + 14))
fresh_health()
asyncio.run(fail_twice())

# 探测：冷却中的 + 从没用过的都探
calls.clear()
asyncio.run(rt.probe_once())
expect("探测冷却中的和好久没用的（假流程没真调过 aigo）", sorted(calls), ["aigo", "bad", "hardys"])
calls.clear()
asyncio.run(rt.probe_once())
expect("刚探过、没冷却的不再探", sorted(calls), ["bad"])

# 同一个账号哪一档上次没答上来，别的档也排到健康的后面
fresh_health()
health.record("bb#15", "bb#15|bb15", False, 36, False, now=7000)
r = [x["pid"] for x in router.rank([cand("bb15_high", "bb#15", 9, 0.5, "high", 15), cand("aigo", "aigo#1", 9, 2, "high")],
                                   "high", CFG, now=7001)]
expect("账号上次失败，没成绩的另一档也排后面", r, ["aigo", "bb15_high"])

# 外面等太久取消的也算失败；很快取消的不算
fresh_health()
router.CANCEL_COUNTS = 0.05


class Slow(Prov):
    async def text_chat(self, **kw):
        await asyncio.sleep(5)


slow = Slow("slow", "https://slow.test", "k9")
provs["slow"] = slow
Ctx.provider_manager.provider_insts.append(slow)
rt._patch_providers()


async def cancel_after(sec):
    try:
        await asyncio.wait_for(slow.text_chat(prompt="x"), sec)
    except asyncio.TimeoutError:
        pass


asyncio.run(cancel_after(0.01))
expect("很快取消不记", health.streak(router.account_of(slow)), 0)
asyncio.run(cancel_after(0.2))
expect("等久了被取消记一次失败", health.streak(router.account_of(slow)), 1)
router.CANCEL_COUNTS = 20.0

# AstrBody.generate：主模型按排好的顺序试（bad 挂着、aigo 质量最高）
fresh_health()
asyncio.run(fail_twice())
from kaju_astr import AstrBody  # noqa: E402

tried = []


class GenCtx(Ctx):
    async def llm_generate(self, chat_provider_id, prompt, system_prompt=""):
        tried.append(chat_provider_id)
        if chat_provider_id == "aigo":
            raise RuntimeError("502")
        return types.SimpleNamespace(role="assistant", completion_text="ok:" + chat_provider_id)


rt.context = GenCtx()
body = AstrBody(GenCtx(), types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
out = asyncio.run(body.generate("aigo", "hi", timeout=30))
expect("generate 按排好的顺序：aigo 失败换 hardys", (tried, out), (["aigo", "hardys"], "ok:hardys"))
tried.clear()
out = asyncio.run(body.generate("hardys", "hi", timeout=30))
expect("不是主模型的照原样", (tried, out), (["hardys"], "ok:hardys"))

rt.uninstall()
expect("卸载还原 _select_provider", am._select_provider is _select_provider, True)
expect("卸载还原 text_chat", router.ORIG in Prov.__dict__, False)
expect("卸载还原 AstrBody", router.ORIG in AstrBody.__dict__, False)

# ------------------------------------------------------------------ 出卡叠着问（omni.text）
import time  # noqa: E402

from kaju_core.senses import omni  # noqa: E402

fresh_health()
KEYS = [{"name": n, "base_url": f"https://{n}.test", "api_key": n, "model": "m"} for n in ("hardys", "aigo", "daitu")]
BEHAVE = {}
asked = []


def fake_gemini_text(k, system, user, thinking, t):
    asked.append(k["name"])
    kind, sec = BEHAVE[k["name"]]
    time.sleep(min(sec, t))
    if kind == "ok" and sec <= t:
        return "卡:" + k["name"]
    if kind == "ok":
        raise TimeoutError("timed out")
    raise RuntimeError("502")


real_keys, real_call = omni.gemini_keys, omni._gemini_text
omni.gemini_keys, omni._gemini_text = (lambda: KEYS), fake_gemini_text
try:
    BEHAVE.update(hardys=("ok", 0.05), aigo=("ok", 0.05), daitu=("ok", 0.05))
    asked.clear()
    expect("第一个快就只问它", (asyncio.run(omni.text("s", "u", timeout=1, stagger=0.3)), asked), (("卡:hardys", 1), ["hardys"]))
    # 第一个慢（还没超时）：过了 stagger 同时问第二个，第二个先回
    BEHAVE.update(hardys=("ok", 0.8), aigo=("ok", 0.05))
    asked.clear()

    async def timed():  # 在协程里计时（asyncio.run 退出时会等后台线程睡完，机器人里不会）
        t0 = time.monotonic()
        r = await omni.text("s", "u", timeout=1, stagger=0.2)
        return r, time.monotonic() - t0

    out, took = asyncio.run(timed())
    expect("慢的没停、同时问下一个，谁先回用谁", (out, asked[:2]), (("卡:aigo", 2), ["hardys", "aigo"]))
    expect("没有排队等满", took < 0.6, True)
    # 报错了马上补问下一个（不用等 stagger）
    fresh_health()
    BEHAVE.update(hardys=("bad", 0.01), aigo=("bad", 0.01), daitu=("ok", 0.05))
    asked.clear()
    t0 = time.monotonic()
    out = asyncio.run(omni.text("s", "u", timeout=1, stagger=5))
    expect("报错马上换下一个", (out, asked, time.monotonic() - t0 < 1), (("卡:daitu", 3), ["hardys", "aigo", "daitu"], True))
    # 原来会判“全挂”的情况：每个 key 等 timeout 都不够，但 daitu 在 timeout×2 内能回
    fresh_health()
    BEHAVE.update(hardys=("ok", 9), aigo=("bad", 0.01), daitu=("ok", 0.35))
    out = asyncio.run(omni.text("s", "u", timeout=0.25, stagger=0.05))
    expect("每个 key 多等一点：慢一点的 daitu 也能答上", out, ("卡:daitu", 3))
    # 真的全挂
    fresh_health()
    BEHAVE.update(hardys=("bad", 0.01), aigo=("bad", 0.01), daitu=("bad", 0.01))
    try:
        asyncio.run(omni.text("s", "u", timeout=1, stagger=0.1))
        expect("全挂抛 GeminiDown", "没抛", "GeminiDown")
    except omni.GeminiDown as e:
        expect("全挂抛 GeminiDown，带每个的原因", str(e).split("没答上来 ")[1], "1:RuntimeError 2:RuntimeError 3:RuntimeError")
finally:
    omni.gemini_keys, omni._gemini_text = real_keys, real_call

# gemini_keys.json："video": false 不看视频；写坏了接着用上次读对的
from kaju_core import paths  # noqa: E402

kp = paths.account(omni.GEMINI_LIST)
os.makedirs(os.path.dirname(kp), exist_ok=True)
good = {"keys": [{"name": "a", "api_key": "k1", "base_url": "https://a.test", "model": "m"},
                 {"name": "lite", "api_key": "k2", "base_url": "https://b.test", "model": "m", "video": False},
                 {"name": "oa", "api_key": "k3", "base_url": "https://c.test", "model": "m", "format": "openai"}]}
with open(kp, "w", encoding="utf-8") as f:
    json.dump(good, f)
omni._list_cache = (0.0, [])
real_omni_key = omni.key
omni.key = lambda: {}
try:
    expect("三个 key 都能出卡", [k["api_key"] for k in omni.gemini_keys()], ["k1", "k2", "k3"])
    expect("看视频跳过 video:false 和 OpenAI 格式的", [k["api_key"] for k in omni.keys()], ["k1"])
    time.sleep(0.05)
    with open(kp, "w", encoding="utf-8") as f:
        f.write('{"keys": [{"name": "x", "_备注": \n}]}')
    os.utime(kp, (time.time() + 5, time.time() + 5))
    expect("写坏了接着用上次读对的", [k["api_key"] for k in omni.gemini_keys()], ["k1", "k2", "k3"])
finally:
    omni.key = real_omni_key
    os.remove(kp)
    omni._list_cache = (0.0, [])

# 按功能挑（model_router.json 的 tasks）：出卡带 Claude 后备、视频不给 Claude、enabled:false、每条自己的思考档
fresh_health()
tp = paths.account("model_router.json")
txp = paths.account(omni.TEXT_LIST)
with open(kp, "w", encoding="utf-8") as f:
    json.dump({"keys": [{"name": "hardys", "api_key": "g1", "base_url": "https://h.test", "model": "g3", "format": "openai"},
                        {"name": "aigo", "api_key": "g2", "base_url": "https://a.test", "model": "g38"},
                        {"name": "lite", "api_key": "g3", "base_url": "https://l.test", "model": "lite", "video": False}]}, f)
with open(txp, "w", encoding="utf-8") as f:
    json.dump({"keys": [{"name": "claude", "api_key": "c1", "base_url": "https://c.test", "model": "sonnet", "format": "openai"}]}, f)
with open(tp, "w", encoding="utf-8") as f:
    json.dump({"tasks": {
        "card": {"budget": 25, "models": [
            {"from": "gemini_keys", "match": "hardys", "think": "low", "quality": 9, "price": 1, "secs": 4},
            {"from": "gemini_keys", "match": "aigo", "think": "high", "quality": 8, "price": 2, "secs": 8},
            {"from": "text_models", "match": "claude", "quality": 6, "price": 0.2, "secs": 6}]},
        "video": {"models": [
            {"from": "gemini_keys", "match": "aigo", "quality": 9, "price": 2},
            {"from": "gemini_keys", "match": "lite", "quality": 9, "price": 0},
            {"from": "text_models", "match": "claude", "quality": 10, "price": 0},
            {"from": "gemini_keys", "match": "hardys", "quality": 10, "price": 0}]},
        "image": {"models": [
            {"from": "gemini_keys", "match": "aigo", "quality": 9, "price": 2, "enabled": False},
            {"from": "text_models", "match": "claude", "quality": 5, "price": 0.2},
            {"from": "gemini_keys", "match": "lite", "model": "lite-v2", "quality": 7, "price": 0.5}]}}}, f)
for x in (kp, txp, tp):
    os.utime(x, (time.time() + 20, time.time() + 20))
omni._list_cache = (0.0, [])
omni._text_cache = (0.0, [])
omni._table_cache = (0.0, {})
card_plan = omni.plan("card", omni.gemini_keys())
expect("出卡顺序（Claude 当后备）", [(k["api_key"], t) for k, t in card_plan], [("g1", "low"), ("g2", "high"), ("c1", "")])
expect("视频只给原生、能看视频的", [k["api_key"] for k, _ in omni.plan("video", omni.keys())], ["g2"])
expect("enabled:false 不用、model 能换", [(k["api_key"], k["model"]) for k, _ in omni.plan("image", omni.look_keys())],
       [("g3", "lite-v2"), ("c1", "sonnet")])
expect("表里没写的功能照原来顺序", [k["api_key"] for k, _ in omni.plan("audio", omni.keys())], ["g2"])

# 出卡：Gemini 两个都挂，Claude 接住；思考档按每条的传
said = []
real_call = omni._gemini_text


def fake_text(k, system, user, thinking, t):
    said.append((k["api_key"], thinking))
    if k["api_key"] != "c1":
        raise RuntimeError("502")
    return "卡:claude"


omni._gemini_text = fake_text
try:
    expect("Gemini 挂了 Claude 出卡", asyncio.run(omni.text("s", "u", timeout=1, stagger=5)), ("卡:claude", 3))
    expect("每条的思考档", sorted(said), [("c1", ""), ("g1", "low"), ("g2", "high")])
finally:
    omni._gemini_text = real_call
    for x in (kp, txp, tp):
        os.remove(x)
    omni._list_cache = (0.0, [])
    omni._text_cache = (0.0, [])
    omni._table_cache = (0.0, {})

# 每条可以指定格式：出卡 Gemini 走 OpenAI、Claude 走原生；视频只给原生
fresh_health()
with open(kp, "w", encoding="utf-8") as f:
    json.dump({"keys": [{"name": "aigo", "api_key": "g2", "base_url": "https://a.test", "model": "g38"}]}, f)
with open(txp, "w", encoding="utf-8") as f:
    json.dump({"keys": [{"name": "claude", "api_key": "c1", "base_url": "https://c.test/v1", "model": "sonnet", "format": "openai"}]}, f)
with open(tp, "w", encoding="utf-8") as f:
    json.dump({"tasks": {
        "card": {"models": [{"from": "gemini_keys", "match": "aigo", "format": "openai", "quality": 9, "price": 1},
                            {"from": "text_models", "match": "claude", "format": "anthropic", "quality": 6, "price": 1}]},
        "video": {"models": [{"from": "gemini_keys", "match": "aigo", "format": "openai", "quality": 9, "price": 1}]}}}, f)
for x in (kp, txp, tp):
    os.utime(x, (time.time() + 30, time.time() + 30))
omni._list_cache = (0.0, [])
omni._text_cache = (0.0, [])
omni._table_cache = (0.0, {})
expect("format 换格式", [k["fmt"] for k, _ in omni.plan("card", omni.gemini_keys())], ["openai", "anthropic"])
expect("视频不给 OpenAI 格式", omni.plan("video", omni.keys()), [])

sent = []


class FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    sent.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
    return FakeResp({"content": [{"type": "text", "text": "卡:原生"}]})


import urllib.request  # noqa: E402

real_open = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
try:
    ck = next(k for k, _ in omni.plan("card", omni.gemini_keys()) if k["fmt"] == "anthropic")
    expect("Claude 原生出卡", omni._gemini_text(ck, "sys", "u", "", 5), "卡:原生")
    url, hdr, body = sent[-1]
    expect("Claude 原生的地址和头", (url, hdr.get("X-api-key"), body["system"], body["messages"][0]["content"][0]["text"]),
           ("https://c.test/v1/messages", "c1", "sys", "u"))
    omni._gemini_look(ck, "image/png", b"abc", "看图", 5)
    expect("Claude 原生看图", sent[-1][2]["messages"][0]["content"][0]["type"], "image")
finally:
    urllib.request.urlopen = real_open
    for x in (kp, txp, tp):
        os.remove(x)
    omni._list_cache = (0.0, [])
    omni._text_cache = (0.0, [])
    omni._table_cache = (0.0, {})

from kaju_core.voice import mind  # noqa: E402

expect("报信：太慢和报错分开说",
       mind.down_summary("Gemini 的 key 全都没答上来 1:URLError 2:TimeoutError 3:TimeoutError 4:HTTPError 5:URLError", 5),
       "5个 Gemini 的 key 都试了：2个回得太慢、等不及，3个报错或连不上。")
expect("报信：主模型那一路", mind.down_summary("main", 5).startswith("写回复的主模型"), True)
expect("报信：原因里没有编号就照旧", mind.down_summary("全挂了 https://relay.example/v1 key...aaa8", 5), "5个 Gemini 的 key 都没答上来。")

print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
