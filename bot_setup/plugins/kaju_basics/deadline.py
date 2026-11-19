"""模型请求总时限。

DeepSeek 排队或卡住时会一直发空行保活，HTTP 的读超时（两次收到数据的间隔）因此永远触发不了，
AstrBot 也没有整次请求的时限，一次卡住的请求能挂半小时：她一直不回，期间发来的消息也都排在这次后面。

这里给非流式的 chat.completions.create 套一个总时限，超时就取消，抛 openai 自己的 APITimeoutError，
交给 AstrBot 现成的重试（retry_provider_request 会重发）。流式请求不管（这边没开流式）。
"""

import asyncio
import functools

ORIG_ATTR = "_kaju_deadline_orig_create"


def _target():
    try:
        from openai.resources.chat.completions import AsyncCompletions
    except Exception:  # noqa: BLE001 - 没有 openai 就不装
        return None
    return AsyncCompletions


def _timeout_error(completions):
    import openai
    from openai import _exceptions

    hx = getattr(_exceptions, "httpx2", None) or getattr(_exceptions, "httpx", None)
    if hx is None:
        import httpx as hx
    base = str(getattr(getattr(completions, "_client", None), "base_url", "") or "http://llm/")
    return openai.APITimeoutError(request=hx.Request("POST", base.rstrip("/") + "/chat/completions"))


def install(get_limit, log, cls=None, make_error=_timeout_error, get_hedge=None) -> bool:
    """get_limit() 每次调用时读秒数（<=0 表示不限）。重复安装 / 热重载时总是包在最初的方法外面。

    get_hedge()（可选）：请求过了这么多秒还没回，就同样的请求再发一份，两份一起等、谁先回用谁、另一份取消。
    2026-11-03 群里聊得正热时三次卡住（64s / 125s / 66s，平时 4~6 秒）：60 秒时限到了才重发，
    这期间叫她的消息全排在后面。正常的慢回复（12~28 秒，少见）也不会被扔掉：第一份照样在等。
    """
    cls = cls or _target()
    if cls is None:
        return False
    orig = cls.__dict__.get(ORIG_ATTR) or cls.create

    @functools.wraps(orig)
    async def create(self, *args, **kwargs):
        limit = get_limit()
        if kwargs.get("stream") or not limit or limit <= 0:
            return await orig(self, *args, **kwargs)
        hedge = 0.0
        try:
            hedge = float(get_hedge() or 0) if get_hedge else 0.0
        except (TypeError, ValueError):
            hedge = 0.0
        client = getattr(self, "_client", None)
        if getattr(getattr(client, "base_url", None), "host", "") in ("127.0.0.1", "localhost", "::1"):
            # Local model loading can exceed the cloud deadline; retain its configured timeout.
            configured = getattr(client, "timeout", None)
            local_limit = getattr(configured, "read", configured)
            if isinstance(local_limit, (int, float)) and local_limit > limit:
                limit = local_limit
            hedge = 0.0  # 本地模型再发一份只会更慢
        if hedge <= 0 or hedge >= limit:
            cm = asyncio.timeout(limit)
            try:
                async with cm:
                    return await orig(self, *args, **kwargs)
            except TimeoutError:
                if not cm.expired():
                    raise
                log(f"kaju_basics: 模型请求 {limit:.0f}s 没返回（多半卡在服务端排队），取消后重试")
                raise make_error(self) from None
        return await _hedged(lambda: orig(self, *args, **kwargs), limit, hedge, log, lambda: make_error(self))

    setattr(cls, ORIG_ATTR, orig)
    cls.create = create
    return True


async def _hedged(call, limit: float, hedge: float, log, make_error):
    """先发一份；hedge 秒还没回再发一份；谁先成功用谁。都失败抛第一份的错；总共 limit 秒还没有就抛超时（AstrBot 会重试）。"""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    tasks = [asyncio.ensure_future(call())]
    try:
        done, _ = await asyncio.wait(tasks, timeout=hedge)
        if not done:
            log(f"kaju_basics: 模型请求 {hedge:.0f}s 还没回，同样的再发一份一起等，谁先回用谁")
            tasks.append(asyncio.ensure_future(call()))
        while True:
            for t in tasks:
                if t.done() and not t.cancelled() and t.exception() is None:
                    if len(tasks) > 1:
                        which = "后发的那份" if t is tasks[1] else "第一份"
                        log(f"kaju_basics: {which}先回来了（共 {loop.time() - t0:.1f}s）")
                    return t.result()
            pending = [t for t in tasks if not t.done()]
            if not pending:
                raise tasks[0].exception()
            remaining = limit - (loop.time() - t0)
            if remaining <= 0:
                done = set()
            else:
                done, _ = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                log(f"kaju_basics: 模型请求 {limit:.0f}s 没返回（多半卡在服务端排队），取消后重试")
                raise make_error() from None
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
            elif not t.cancelled():
                t.exception()  # 取走，免得"exception was never retrieved"


def uninstall(cls=None) -> None:
    cls = cls or _target()
    if cls is None:
        return
    orig = cls.__dict__.get(ORIG_ATTR)
    if orig is not None:
        cls.create = orig
        delattr(cls, ORIG_ATTR)
