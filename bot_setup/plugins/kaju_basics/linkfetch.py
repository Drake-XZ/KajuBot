"""她用网页抓取工具（deepseek_fetch_web_page 等）去看抖音 / B站视频链接时，改走真正看视频的流程。

2026-11-08：兄长说"再试一下"让她重看之前发过的抖音图文，她调了 deepseek_fetch_web_page，
只拿到页面文字（标题、点赞数），图一张都没看到，还说"网页只把文字给了佳树"。
看链接的流程（describe.py：抖音开浏览器看图 / 下视频，B站下视频看画面 + 听声音）只在消息里带链接时才跑，
旧链接让她自己去看，就走到了网页抓取。这里把 AstrBot 自带的几个"抓一个网页"工具包一层：
url 是抖音 / B站视频，就交给 handler（看完的整段介绍）；不是、或者没看成，原样走原来的抓网页。
重复安装 / 热重载时总是包在最初的函数外面。
"""

from __future__ import annotations

NAMES = ("DeepSeekFetchWebPageTool", "TavilyExtractWebPageTool", "FirecrawlExtractWebPageTool")
ORIG_ATTR = "_kaju_link_orig_call"


def _module():
    try:
        from astrbot.core.tools import web_search_tools
    except Exception:  # noqa: BLE001
        return None
    return web_search_tools


def _event(context):
    try:
        return context.context.event
    except Exception:  # noqa: BLE001
        return None


def install(handler, log, mod=None) -> list[str]:
    """handler(url, event) -> 给她看的整段介绍（不是视频链接 / 没看成返回 ""）。返回包上了哪些工具。"""
    mod = mod or _module()
    if mod is None:
        return []
    done = []
    for name in NAMES:
        cls = getattr(mod, name, None)
        if cls is None or not hasattr(cls, "call"):
            continue
        orig = getattr(cls, ORIG_ATTR, None) or cls.call

        async def call(self, context, _orig=orig, **kwargs):
            url = str(kwargs.get("url") or "").strip()
            event = _event(context)
            if url and event is not None:
                try:
                    text = await handler(url, event)
                except Exception as e:  # noqa: BLE001
                    log(f"kaju_basics: 抓网页时改看视频出错，照常抓网页 {type(e).__name__}: {e}")
                    text = ""
                if text:
                    return text
            return await _orig(self, context, **kwargs)

        setattr(cls, ORIG_ATTR, orig)
        cls.call = call
        done.append(name)
    return done


def uninstall(mod=None) -> None:
    mod = mod or _module()
    if mod is None:
        return
    for name in NAMES:
        cls = getattr(mod, name, None)
        if cls is not None and hasattr(cls, ORIG_ATTR):
            cls.call = getattr(cls, ORIG_ATTR)
            delattr(cls, ORIG_ATTR)
