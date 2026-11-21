r"""挑主模型：AstrBot 后备链上一家一家试的时候（kaju_basics/router.py _patch_runner，2026-11-22）。不连 AstrBot、不发请求。
    <venv>\Scripts\python.exe -I tests\test_router_chain.py
后备循环照 AstrBot 4.29 tool_loop_agent_runner._iter_llm_responses_with_fallback 简写。
"""
import asyncio
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


# ---- 假的 AstrBot 后备循环
class Resp:
    def __init__(self, text, role="assistant"):
        self.completion_text, self.role, self.is_chunk = text, role, False


class ToolLoopAgentRunner:
    def __init__(self, provider, fallbacks):
        self.provider, self.fallback_providers = provider, fallbacks

    async def _iter_llm_responses(self, include_model=True):
        resp = await self.provider.text_chat(prompt="x")
        if resp is not None:
            yield resp

    async def run(self):
        for cand in [self.provider, *self.fallback_providers]:
            self.provider = cand
            try:
                async for r in self._iter_llm_responses(include_model=True):
                    return r
            except Exception as e:  # noqa: BLE001
                tried.append((cand.provider_config["id"], type(e).__name__))
                continue
        return Resp("all failed", "err")


mod = types.ModuleType("astrbot.core.agent.runners.tool_loop_agent_runner")
mod.ToolLoopAgentRunner = ToolLoopAgentRunner
sys.modules.setdefault("astrbot.core.agent.runners", types.ModuleType("astrbot.core.agent.runners"))
sys.modules[mod.__name__] = mod

tried = []


class Prov:
    def __init__(self, pid, base, key, behave, secs=0.0):
        self.provider_config = {"id": pid, "api_base": base, "key": [key], "model": "m", "enable": True}
        self.behave, self.secs = behave, secs

    def get_keys(self):
        return self.provider_config["key"]

    async def text_chat(self, **kw):
        await asyncio.sleep(self.secs)
        if self.behave == "ok":
            tried.append((self.provider_config["id"], "ok"))
            return Resp("ok:" + self.provider_config["id"])
        tried.append((self.provider_config["id"], "raise"))
        raise TimeoutError("ReadTimeout")


from kaju_basics import router  # noqa: E402

# ---- 纯函数
fresh_health()
expect("超时算网站挂了", router.outage(TimeoutError()), True)
expect("524 算", router.outage(RuntimeError("InternalServerError: Error code: 524")), True)
expect("502 None 算", router.outage(RuntimeError("502 None. {'error'")), True)
expect("400 不算", router.outage(RuntimeError("Error code: 400 bad request")), False)
expect("ReadTimeout 名字算", router.outage(type("ReadTimeout", (Exception,), {})()), True)
expect("限时 high = 50", router.attempt_limit({"budget_high": 25}, "high"), 50.0)
expect("限时 low 至少 30", router.attempt_limit({"budget_low": 12}, "low"), 30.0)
expect("attempt_mult=0 不限", router.attempt_limit({"attempt_mult": 0}, "high"), 0.0)
a = health.account("https://a.test", "k1")
b = health.account("https://b.test", "k2")
health.record(a, "s", False, 1, now=time.time())
health.record(a, "s", False, 1, now=time.time())
expect("冷却中、后面有好的 → 跳", router.skip_reason(a, [b], set()).startswith("冷却中"), True)
expect("冷却中、后面都不好 → 照试", router.skip_reason(a, [a], set()), "")
expect("同网站刚挂 → 跳", router.skip_reason(b, [a, health.account("https://c.test", "k")], {"b.test"}) != "", True)
expect("好的照试", router.skip_reason(health.account("https://c.test", "k"), [b], set()), "")

# ---- 那晚的链：aether 卡住、bb-api 两个 key 都超时、hardys2 524、最后原生 Gemini 好的
fresh_health()


class Rt(router.Router):
    pass


logs = []
cfg = {"enable": True, "budget_high": 25, "attempt_mult": 2.0, "attempt_min": 30}
rt = Rt(types.SimpleNamespace(), lambda: cfg, logs.append)
rt._patch_runner()
expect("装上了", router.ORIG in ToolLoopAgentRunner.__dict__, True)

cfg.update(budget_high=0.05, attempt_min=0.1)  # 限时缩成 0.1 秒好测
aether = Prov("aether3", "https://api.aethergate.cc", "a1", "ok", secs=5)  # 不答（会被限时截断）
bb15 = Prov("bb15", "https://www.bb-api.com", "b1", "raise")
bb25 = Prov("bb25", "https://www.bb-api.com", "b2", "ok", secs=5)  # 同网站：前一个刚挂 → 跳过
hy2 = Prov("hardys2", "https://hardysapi.com", "h1", "raise")
gem = Prov("gemini", "https://generativelanguage.googleapis.com", "g1", "ok")
runner = ToolLoopAgentRunner(aether, [bb15, bb25, hy2, gem])
t0 = time.monotonic()
out = asyncio.run(runner.run())
took = time.monotonic() - t0
expect("最后原生 Gemini 答了", out.completion_text, "ok:gemini")
expect("顺序：aether 限时、bb15 挂、bb25 跳过、hardys2 挂、gemini 成",
       tried, [("aether3", "TimeoutError"), ("bb15", "raise"), ("bb15", "TimeoutError"), ("bb25", "Skipped"),
               ("hardys2", "raise"), ("hardys2", "TimeoutError"), ("gemini", "ok")])
expect("没白等（< 1 秒）", took < 1.0, True)
expect("日志写了跳过", any("跳过 bb25" in x for x in logs), True)

# 冷却中的（别的消息刚弄进冷却）跳过；最后一家不限时、不跳
fresh_health()
tried.clear()
x1 = Prov("x1", "https://x.test", "k", "ok")
last = Prov("last", "https://y.test", "k", "ok", secs=0.3)  # 超过 0.1 秒限时，但是最后一家
acc = router.account_of(x1)
health.record(acc, "s", False, 1)
health.record(acc, "s", False, 1)
out = asyncio.run(ToolLoopAgentRunner(x1, [last]).run())
expect("冷却的跳过、最后一家等满", (tried, out.completion_text), ([("x1", "Skipped"), ("last", "ok")], "ok:last"))

# 都在冷却：不跳（不然一家都不试）
tried.clear()
health.record(router.account_of(last), "s", False, 1)
health.record(router.account_of(last), "s", False, 1)
last.secs = 0
out = asyncio.run(ToolLoopAgentRunner(x1, [last]).run())
expect("都冷却就照试", tried[0], ("x1", "ok"))

# 关了 = 照原样
tried.clear()
cfg["enable"] = False
slowp = Prov("slow", "https://s.test", "k", "ok", secs=0.3)
out = asyncio.run(ToolLoopAgentRunner(slowp, [gem]).run())
expect("关了不限时", out.completion_text, "ok:slow")
cfg["enable"] = True

rt.uninstall()
expect("卸载还原", router.ORIG in ToolLoopAgentRunner.__dict__, False)

print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
