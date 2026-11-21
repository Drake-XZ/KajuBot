"""挑主模型（2026-11-14 兄长：“动态调整调用的 api 顺序，以及动态使用回复速度与质量兼备的模型及其思考强度”）。

原来主模型和后备是配置里写死的顺序：aigocode 一挂，每条消息都先在它那儿等五十秒、再在 hardysapi 那儿白等 15 秒。现在：

1. 记成绩：AstrBot 每次调模型（text_chat）都记下成没成、几秒（kaju_core/senses/health.py，和看图共用一份）。
   连着失败 2 次的账号冷却 10 分钟，排到最后；每 probe_minutes 分钟用“回一个字”探一下冷却中的 / 好久没用的，好了就放回来。
2. 每条消息现排：候选 = 配置里的主模型 + 后备 + model_router.json 里登记的（比如同一个模型的不同思考档）。
   这条想要哪档（场合）：私聊、问句、长消息 → high（预算 budget_high 秒），群里闲聊 → low（budget_low 秒）。
   最近中位耗时在预算内的里，挑 质量 - 价格×price_weight（档位对上再加 think_bonus）最高的打头；
   超预算的按快慢排在后面，冷却中的放最后；同一个账号的第二档排到所有账号的第一档后面（账号挂了两档一起挂）。
3. 接进去的地方：AstrBot 的 _select_provider / _get_fallback_chat_providers（聊天主流程）和 AstrBody.generate 的后备链
   （心情、记忆、核对这些直接调主模型的）。都是热补丁，插件重载 / 卸载时还原。
质量分、价格、思考档写在 kaju_data/accounts/model_router.json（兄长可以改，改完不用重载）。
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import math
import os
import re
import time

from kaju_core.senses import health

ORIG = "_kaju_router_orig"
BIG_CHARS = 12_000
CANCEL_COUNTS = 20.0  # 等了这么多秒才被外面取消 = 算一次失败
PROBE_PROMPT = "回一个字：好"

_order: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("kaju_router_order", default=None)
_want: contextvars.ContextVar[str] = contextvars.ContextVar("kaju_router_want", default="high")
_table_cache: tuple[float, dict] = (0.0, {})


# ------------------------------------------------------------------ 表（质量 / 价格 / 思考档）

def table_path() -> str:
    from kaju_core import paths
    return paths.account("model_router.json")


def load_table(path: str | None = None) -> dict:
    """{provider_id: {quality, price, think, secs}}；文件改了重新读；没有 / 坏了返回 {}。"""
    global _table_cache
    path = path or table_path()
    try:
        m = os.path.getmtime(path)
    except OSError:
        return {}
    if m != _table_cache[0]:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            models = d.get("models") if isinstance(d, dict) else None
            _table_cache = (m, {k: v for k, v in (models or {}).items() if isinstance(v, dict) and not k.startswith("_")})
        except (OSError, ValueError):
            return _table_cache[1]
    return _table_cache[1]


# ------------------------------------------------------------------ 一个提供方的身份

def _pid(prov) -> str:
    cfg = getattr(prov, "provider_config", None) or {}
    pid = cfg.get("id")
    if not pid:
        try:
            pid = prov.meta().id
        except Exception:  # noqa: BLE001
            pid = ""
    return str(pid or "")


def _key_of(prov) -> str:
    for name in ("chosen_api_key",):
        v = getattr(prov, name, None)
        if isinstance(v, str) and v:
            return v
    try:
        keys = prov.get_keys()
        if keys:
            return str(keys[0])
    except Exception:  # noqa: BLE001
        pass
    k = (getattr(prov, "provider_config", None) or {}).get("key")
    return str(k[0] if isinstance(k, list) and k else k or "")


def account_of(prov) -> str:
    cfg = getattr(prov, "provider_config", None) or {}
    return health.account(str(cfg.get("api_base") or ""), _key_of(prov))


def slot_of(prov) -> str:
    cfg = getattr(prov, "provider_config", None) or {}
    return f"{account_of(prov)}|{cfg.get('model', '')}|{_pid(prov)}"


def _size(kw: dict) -> tuple[bool, int]:
    n = len(str(kw.get("prompt") or "")) + len(str(kw.get("system_prompt") or ""))
    for c in kw.get("contexts") or []:
        n += len(str(c))
    tools = kw.get("func_tool")
    has_tools = bool(tools is not None and getattr(tools, "tools", None))
    return has_tools or n > BIG_CHARS, n


# ------------------------------------------------------------------ 排序

def situation(event, long_chars: int = 30) -> str:
    """这条想要哪档：私聊 / 问句 / 长消息 → high，群里闲聊 → low。只看来的消息，不碰她要说的话。"""
    try:
        if event.is_private_chat():
            return "high"
    except Exception:  # noqa: BLE001
        pass
    text = str(getattr(event, "message_str", "") or "")
    if len(text) >= long_chars or "?" in text or "？" in text:
        return "high"
    # 2026-11-18：引用她的话、或者在纠正她（“没叫你”“不是说你”“理解错了”），要想清楚谁在说谁 → high
    # （那天兄长引用她那句说“没叫你吧”，低思考档的大脑读反成“是学姐叫的”）
    if quotes_her(event) or CORRECTS.search(text):
        return "high"
    # 2026-11-19：叫她判断、推测、估算、比较、分析的（“主机端刚上线，你判断一下PC端得什么配置”没问号、不到 30 字，
    # 走了低档，她只答“这就去查”、后来又说“没法推测”）→ high
    if REASONS.search(text):
        return "high"
    return "low"


REASONS = re.compile(r"判断|推测|推断|估计|估算|预估|算一下|算算|算下|比较|对比|比一比|哪个好|哪个更|哪个划算|划算|值不值|"
                     r"相当于|为什么|为啥|怎么回事|分析|推一下|推导|证明|有没有可能|能不能行|靠谱吗|是真是假|真假")


CORRECTS = re.compile(r"没叫你|没在叫你|不是叫你|不是说你|不是跟你|没说你|没跟你说|认错|搞错|理解错|弄错|会错意|想多了")


def quotes_her(event) -> bool:
    """这条消息引用的是不是她自己说过的话（QQ 引用回复里引的那条是她发的）。"""
    try:
        me = str(event.get_self_id() or "")
        chain = event.get_messages()
    except Exception:  # noqa: BLE001
        return False
    for c in chain or []:
        if type(c).__name__ == "Reply" and me and str(getattr(c, "sender_id", "") or "") == me:
            return True
    return False


MEDIA = {"Image", "Video", "Record", "File", "Forward", "Node", "Nodes"}


def media_kinds(event) -> dict:
    """这条消息（连它引用的那条）带的图、视频、语音、文件、合并转发：{类名: 个数}。"""
    try:
        chain = event.get_messages()
    except Exception:  # noqa: BLE001
        chain = getattr(getattr(event, "message_obj", None), "message", None)
    out: dict = {}
    for c in chain or []:
        name = type(c).__name__
        if name in MEDIA:
            out[name] = out.get(name, 0) + 1
        if name == "Reply":
            for x in getattr(c, "chain", None) or []:
                if type(x).__name__ in MEDIA:
                    out[type(x).__name__] = out.get(type(x).__name__, 0) + 1
    return out


def has_media(event) -> bool:
    """带了就不让只认文字的模型（Claude）上。"""
    return bool(media_kinds(event))


def only_images(event, max_n: int = 6) -> bool:
    """只带图（≤ max_n 张）：这种图在 OnLLMRequest 里会先交给 Gemini 看成文字（main._turn_images）。"""
    kinds = media_kinds(event)
    return bool(kinds) and set(kinds) == {"Image"} and kinds["Image"] <= max_n


def head_can_see(ranked: list[dict], table: dict) -> list[dict]:
    """排好的顺序里，把第一个能看图的（不是 text_only）挪到最前面，其余照原顺序。"""
    i = next((k for k, x in enumerate(ranked) if not table.get(x["pid"], {}).get("text_only")), None)
    if i is None:
        return ranked
    return [ranked[i]] + ranked[:i] + ranked[i + 1:]


rank = health.rank  # 2026-11-14 挪进 kaju_core/senses/health.py：看图、看视频也用同一个排法


# ------------------------------------------------------------------ 后备链上一家一家试的时候（2026-11-22）
# 那晚兄长发小说：顺序在这条开头排好就不动了，aether3 502 等了 63 秒、bb-api 两个 key 各读超时 60 秒、hardys2 524，
# 第 5 家原生 Gemini 才答上来，前后 4 分钟。现在每换一家之前再看一眼：
#   - 这家正在冷却（别的消息刚把它弄进冷却）、或者同一个网站这条消息里刚超时 / 5xx 过 → 后面还有好的就跳过；
#   - 不是最后一家的，最多等 max(attempt_min, 预算 × attempt_mult) 秒，没答上来就换下一家（最后一家不限时）。

class Skipped(RuntimeError):
    """这一家这次不试了（冷却中 / 同网站刚挂）。AstrBot 的后备循环当它报错，接着试下一家。"""


def host_of(acc: str) -> str:
    return str(acc or "").split("#")[0]


def outage(e: BaseException) -> bool:
    """像是那个网站整个挂了：超时、连不上、5xx。400 这种多半只是这个模型 / 格式的毛病，不算。"""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    name = type(e).__name__
    if any(w in name for w in ("Timeout", "Connect", "ServerError", "Unavailable", "Gateway")):
        return True
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    try:
        if code is not None and int(code) >= 500:
            return True
    except (TypeError, ValueError):
        pass
    return bool(re.search(r"(?:Error code|status)[:\s]*5\d\d|\b5(?:0[0-9]|2[0-9])\b None", str(e)))


def skip_reason(acc: str, later: list[str], failed_hosts: set, now: float | None = None) -> str:
    """这家要不要跳过（返回原因，空 = 照试）。只有后面还有不冷却、网站也没刚挂的，才跳。"""
    def bad(a: str) -> str:
        left = health.cooled(a, now)
        if left > 0:
            return f"冷却中还有 {left / 60:.0f} 分钟"
        if host_of(a) in failed_hosts:
            return f"{host_of(a)} 这条消息里刚没答上来"
        return ""
    why = bad(acc)
    if why and any(not bad(a) for a in later):
        return why
    return ""


def attempt_limit(cfg: dict, want: str) -> float:
    """不是最后一家时最多等几秒（0 = 不限）。"""
    mult = float(cfg.get("attempt_mult", 2.0) or 0)
    if mult <= 0:
        return 0.0
    budget = float(cfg.get("budget_high" if want == "high" else "budget_low", 25 if want == "high" else 12))
    return max(float(cfg.get("attempt_min", 30) or 0), budget * mult)


class Router:
    """装在 kaju_basics 上：get_cfg() 返回插件配置的 model_router 段。"""

    def __init__(self, context, get_cfg, log):
        self.context = context
        self.get_cfg = get_cfg
        self.log = log
        self._probe_task = None
        # 2026-11-19：看图的 Gemini 开着时返回 True（main.py 设）。AstrBot 先定后备链、后跑 OnLLMRequest
        # 把图看成文字，所以只带图的消息里只认文字的 Claude 原来一个都进不了链；现在排在所有能看图的后面兜底
        self.images_become_text = lambda: bool(False)

    # ---- 配置
    def on(self) -> bool:
        return bool(self.get_cfg().get("enable", True))

    def _model_cfg(self) -> dict:
        try:
            return self.context.get_config()["agent_runner"]["config"]["model"]
        except Exception:  # noqa: BLE001
            return {}

    def _prov(self, pid: str):
        try:
            return self.context.get_provider_by_id(pid)
        except Exception:  # noqa: BLE001
            return None

    def candidates(self, text_ok: bool = True) -> list[dict]:
        """text_ok=False（这条带图 / 视频 / 语音…）时，表里写了 "text_only": true 的（Claude）不参与。"""
        self._patch_providers()  # 后来才加载的提供方类（比如新加的原生 Gemini）也记上成绩
        m = self._model_cfg()
        table = load_table()
        ids = [m.get("provider_id")] + list(m.get("fallback_provider_ids") or []) + list(table)
        out, seen = [], set()
        for pid in ids:
            if not pid or pid in seen:
                continue
            seen.add(pid)
            row = table.get(pid, {})
            if row.get("enabled") is False or (row.get("text_only") and not text_ok):
                continue
            prov = self._prov(pid)
            if prov is None or (getattr(prov, "provider_config", None) or {}).get("enable") is False:
                continue
            out.append({"pid": pid, "account": account_of(prov), "slot": slot_of(prov),
                        "quality": row.get("quality", 5), "price": row.get("price", 1),
                        "think": row.get("think", ""), "secs": row.get("secs")})
        return out

    def order(self, want: str, text_ok: bool = True) -> list[dict]:
        cfg = dict(self.get_cfg())
        health.configure(cfg.get("fail_streak"), cfg.get("cool_minutes"))
        # 2026-11-15：大请求没答上来的账号 15 分钟内每一档都靠后（探测成功不算）；没成绩的档借同模型别的档
        cfg.setdefault("big_bad_minutes", 15)
        cfg.setdefault("share_tiers", True)
        ranked = rank(self.candidates(text_ok), want, cfg)
        # 只认文字的不打头时也行；但后备里总要有能看图的：万一图没被先看成文字、原样留给了主模型
        if ranked and all(load_table().get(x["pid"], {}).get("text_only") for x in ranked):
            return ranked + rank(self.candidates(False), want, cfg)
        return ranked

    def _say(self, want: str, ranked: list[dict]) -> None:
        if not self.get_cfg().get("log_choice", True) or not ranked:
            return
        head = ranked[0]
        rest = " → ".join(x["pid"] for x in ranked[1:])
        skipped = "；".join(f"{x['pid']} {x['why']}" for x in ranked if x["why"].startswith(("冷却", "最近")))
        self.log(f"kaju_basics: 挑模型（{want}）{head['pid']}（{head['why']}）→ {rest}" + (f"｜{skipped}" if skipped else ""))

    # ---- 聊天主流程：AstrBot 的 _select_provider / _get_fallback_chat_providers
    def install(self) -> bool:
        try:
            import astrbot.core.astr_main_agent as am
        except Exception:  # noqa: BLE001
            return False
        self._patch_agent(am)
        self._patch_runner()
        self._patch_body()
        self._patch_providers()
        return True

    # ---- AstrBot 后备循环里每一家的那次调用：跳过冷却 / 同网站刚挂的、不是最后一家的限时
    def _plan(self, runner) -> tuple[str, float, str] | None:
        """(跳过原因, 限时秒, 网站)；最后一家 / 没后备 / 没开 → None（照原样）。"""
        if not self.on():
            return None
        cur = getattr(runner, "provider", None)
        fbs = list(getattr(runner, "fallback_providers", None) or [])
        idx = next((i for i, p in enumerate(fbs) if p is cur), -1)
        later = fbs[idx + 1:]
        if cur is None or not later:
            return None
        acc = account_of(cur)
        failed = runner.__dict__.setdefault("_kaju_failed_hosts", set())
        why = skip_reason(acc, [account_of(p) for p in later], failed)
        return why, attempt_limit(dict(self.get_cfg()), _want.get()), host_of(acc)

    def _patch_runner(self) -> None:
        try:
            from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner as R
        except Exception:  # noqa: BLE001
            return
        orig = R.__dict__.get(ORIG) or R._iter_llm_responses
        setattr(R, ORIG, orig)
        router = self

        @functools.wraps(orig)
        async def _iter_llm_responses(runner, *args, **kw):
            try:
                plan = router._plan(runner)
            except Exception:  # noqa: BLE001 - 出了岔子就照原样
                plan = None
            if plan is None:
                async for r in orig(runner, *args, **kw):
                    yield r
                return
            why, limit, host = plan
            pid = _pid(runner.provider)
            if why:
                router.log(f"kaju_basics: 后备链跳过 {pid}（{why}），直接试下一家")
                raise Skipped(f"跳过：{why}")
            failed = runner.__dict__.setdefault("_kaju_failed_hosts", set())
            gen = orig(runner, *args, **kw)

            async def _next():
                return await gen.__anext__()

            first = True
            try:
                while True:
                    try:
                        r = await (asyncio.wait_for(_next(), limit) if first and limit else _next())
                    except StopAsyncIteration:
                        return
                    except asyncio.TimeoutError:
                        failed.add(host)
                        router.log(f"kaju_basics: {pid} {limit:.0f} 秒没答上来，换下一家")
                        raise asyncio.TimeoutError(f"{limit:.0f} 秒没答上来") from None
                    except Exception as e:  # noqa: BLE001
                        if outage(e):
                            failed.add(host)
                        raise
                    first = False
                    yield r
            finally:
                try:
                    await gen.aclose()
                except Exception:  # noqa: BLE001
                    pass

        R._iter_llm_responses = _iter_llm_responses

    def _patch_agent(self, am) -> None:
        origs = am.__dict__.get(ORIG) or {"sel": am._select_provider, "fb": am._get_fallback_chat_providers}
        setattr(am, ORIG, origs)
        router = self

        @functools.wraps(origs["sel"])
        async def _select_provider(event, plugin_context):
            prov = await origs["sel"](event, plugin_context)
            try:
                if prov is None or not router.on() or event.get_extra("selected_provider"):
                    return prov  # 别处点名用哪个模型：不管
                if _pid(prov) != router._model_cfg().get("provider_id"):
                    return prov  # 这段聊天单独换过模型：不管
                want = situation(event, int(router.get_cfg().get("long_chars", 30)))
                if only_images(event) and router.images_become_text():
                    # 图会先变成文字：Claude 和别的一起按成绩排；只是打头的得能看图（定链时图还在，
                    # AstrBot 的 _select_image_chat_provider 也会把不能看图的打头换掉）。11-19 起，原来接在最后。
                    ranked = head_can_see(router.order(want, text_ok=True), load_table())
                else:
                    ranked = router.order(want, text_ok=not has_media(event))
                first = router._prov(ranked[0]["pid"]) if ranked else None
                if first is None:
                    return prov
                _order.set([x["pid"] for x in ranked])
                _want.set(want)
                router._say(want, ranked)
                return first
            except Exception as e:  # noqa: BLE001 - 挑不出来就照原样
                router.log(f"kaju_basics: 挑模型出错，照配置的顺序 {type(e).__name__}: {e}")
                return prov

        @functools.wraps(origs["fb"])
        def _get_fallback_chat_providers(provider, plugin_context, fallback_ids):
            ordered = _order.get()
            if ordered and ordered[0] == _pid(provider):
                _order.set(None)
                return origs["fb"](provider, plugin_context, ordered[1:])
            return origs["fb"](provider, plugin_context, fallback_ids)

        am._select_provider = _select_provider
        am._get_fallback_chat_providers = _get_fallback_chat_providers

    # ---- 心情、记忆、核对这些直接调主模型的：AstrBody.generate 的后备链
    def _patch_body(self) -> None:
        try:
            from kaju_astr import AstrBody
        except Exception:  # noqa: BLE001
            return
        origs = AstrBody.__dict__.get(ORIG) or {"gen": AstrBody.generate, "fb": AstrBody._fallbacks}
        setattr(AstrBody, ORIG, origs)
        router = self

        @functools.wraps(origs["gen"])
        async def generate(body, model_id, prompt, system="", timeout=None):
            ranked = None
            try:
                if router.on() and model_id and model_id == router._model_cfg().get("provider_id"):
                    ranked = router.order(str(router.get_cfg().get("direct_want", "high")))
            except Exception as e:  # noqa: BLE001 - 挑不出来就照原样
                router.log(f"kaju_basics: 挑模型出错，照配置的顺序 {type(e).__name__}: {e}")
                ranked = None
            if not ranked:
                return await origs["gen"](body, model_id, prompt, system, timeout)
            token = _order.set([x["pid"] for x in ranked])
            try:
                return await origs["gen"](body, ranked[0]["pid"], prompt, system, timeout)
            finally:
                _order.reset(token)

        @functools.wraps(origs["fb"])
        def _fallbacks(body, pid):
            ordered = _order.get()
            if ordered and ordered[0] == pid:
                return ordered[1:]
            return origs["fb"](body, pid)

        AstrBody.generate = generate
        AstrBody._fallbacks = _fallbacks

    # ---- 记成绩：每个提供方类的 text_chat
    def _patch_providers(self) -> list[str]:
        done = []
        for prov in self._all_chat():
            cls = type(prov)
            if ORIG in cls.__dict__ or not hasattr(cls, "text_chat"):
                continue
            orig = cls.text_chat
            setattr(cls, ORIG, orig)
            router = self

            @functools.wraps(orig)
            async def text_chat(self_, *args, _orig_fn=orig, **kw):
                big, _ = _size(kw)
                t0 = time.monotonic()
                try:
                    resp = await _orig_fn(self_, *args, **kw)
                except asyncio.CancelledError:
                    # 外面等太久取消的（AstrBody.generate 的限时、探测的 60 秒）也算没答上来；很快就取消的多半是别的原因，不记
                    waited = time.monotonic() - t0
                    if waited >= CANCEL_COUNTS:
                        router.note(self_, False, waited, big, f"等了 {waited:.0f}s 被取消")
                    raise
                except Exception as e:  # noqa: BLE001
                    router.note(self_, False, time.monotonic() - t0, big, f"{type(e).__name__}: {str(e)[:60]}")
                    raise
                bad = getattr(resp, "role", "") == "err"
                router.note(self_, not bad, time.monotonic() - t0, big,
                            str(getattr(resp, "completion_text", "") or "")[:60] if bad else "")
                return resp

            cls.text_chat = text_chat
            done.append(cls.__name__)
        return done

    def _all_chat(self) -> list:
        pm = getattr(self.context, "provider_manager", None)
        provs = list(getattr(pm, "provider_insts", None) or [])
        if not provs:
            try:
                provs = list(self.context.get_all_providers() or [])
            except Exception:  # noqa: BLE001
                provs = []
        return provs

    def note(self, prov, ok: bool, secs: float, big: bool, why: str = "") -> None:
        try:
            acc = account_of(prov)
            if health.record(acc, slot_of(prov), ok, secs, big, why):
                self.log(f"kaju_basics: {_pid(prov)}（{acc.split('#')[0]}）连着没答上来，先冷却 "
                         f"{health.COOL_MINUTES:.0f} 分钟，挑模型时排到最后（{why}）")
        except Exception:  # noqa: BLE001
            pass

    # ---- 探测
    async def probe_loop(self) -> None:
        first = True
        while True:
            every = max(1.0, float(self.get_cfg().get("probe_minutes", 10) or 10))
            await asyncio.sleep(15 if first else every * 60)  # 刚装上先探一遍：没成绩的账号别凭先验排第一
            first = False
            if self.on():
                try:
                    await self.probe_once()
                except Exception as e:  # noqa: BLE001
                    self.log(f"kaju_basics: 探测模型出错 {type(e).__name__}: {e}")

    async def probe_once(self, now: float | None = None) -> list[str]:
        """冷却中的、上次没答上来的、或者 probe_minutes×3 分钟没消息的账号，各挑一个提供方问一句“回一个字”（成绩自己记上）。"""
        now = time.time() if now is None else now
        idle = max(1.0, float(self.get_cfg().get("probe_minutes", 10) or 10)) * 3 * 60
        picked, seen = [], set()
        for c in self.candidates():
            if c["account"] in seen:
                continue
            seen.add(c["account"])
            if (health.cooled(c["account"], now) or health.streak(c["account"])
                    or now - health.last_seen(c["account"]) > idle):
                picked.append(c["pid"])

        async def one(pid):
            try:
                await asyncio.wait_for(self.context.llm_generate(chat_provider_id=pid, prompt=PROBE_PROMPT), 60)
            except Exception:  # noqa: BLE001 - 成绩已经由 text_chat 记了
                pass

        if picked:
            await asyncio.gather(*(one(p) for p in picked))
        return picked

    def start(self) -> None:
        try:
            self._probe_task = asyncio.get_running_loop().create_task(self.probe_loop())
        except RuntimeError:
            self._probe_task = None

    def uninstall(self) -> None:
        if self._probe_task is not None:
            self._probe_task.cancel()
        try:
            import astrbot.core.astr_main_agent as am
            origs = am.__dict__.get(ORIG)
            if origs:
                am._select_provider, am._get_fallback_chat_providers = origs["sel"], origs["fb"]
                delattr(am, ORIG)
        except Exception:  # noqa: BLE001
            pass
        try:
            from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner as R
            orig = R.__dict__.get(ORIG)
            if orig is not None:
                R._iter_llm_responses = orig
                delattr(R, ORIG)
        except Exception:  # noqa: BLE001
            pass
        try:
            from kaju_astr import AstrBody
            origs = AstrBody.__dict__.get(ORIG)
            if origs:
                AstrBody.generate, AstrBody._fallbacks = origs["gen"], origs["fb"]
                delattr(AstrBody, ORIG)
        except Exception:  # noqa: BLE001
            pass
        for prov in self._all_chat():
            cls = type(prov)
            orig = cls.__dict__.get(ORIG)
            if orig is not None:
                cls.text_chat = orig
                delattr(cls, ORIG)
