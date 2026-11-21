"""kaju_style 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_core.voice.mind.StyleMind（逻辑和说明都在那边）。

还在用的：聊天节奏（rhythm）、被纠正提醒（rebuttal）、聊作品说具体（concrete）、先回应别当解说员（respond）、
深夜催睡（bedtime）、问之前先听懂（asks）、写她的话（rewrite：大脑出指导 → 回复器写 → 核对）。
2026-11-13 删掉了早就关着的几条（开头少用"诶"、开头别老"好的…"、说话要有变化、说大白话、句子说短、带称呼和语气词）
和看草稿改写的旧"重说"模式。
"""

from astrbot.api import logger
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
import kaju_core
kaju_core.fresh("voice")  # 热重载这个插件时，重新部署过的 kaju_core.voice 也跟着换新
from kaju_core.voice.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_core.voice.mind import StyleMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "佳树的说话习惯：一句一条不打句号、聊作品说具体、先回应别当解说员、被纠正先接住、深夜别老催睡、别问他刚说过的、大脑出指导+回复器写、群里能 @ 人", "1.31.0")
class KajuStyle(StyleMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        StyleMind.__init__(self, AstrBody(context, plugin_log(logger)), config)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await StyleMind.terminate(self)

    @filter.on_llm_request()
    async def remind(self, event: AstrMessageEvent, req: ProviderRequest):
        return await StyleMind.remind(self, event, req)

    @filter.on_llm_request(priority=-60)
    async def remind_rhythm(self, event: AstrMessageEvent, req: ProviderRequest):
        return await StyleMind.remind_rhythm(self, event, req)

    @filter.on_llm_request(priority=-66)
    async def remind_concrete(self, event: AstrMessageEvent, req: ProviderRequest):
        return await StyleMind.remind_concrete(self, event, req)

    @filter.on_llm_request(priority=-68)
    async def remind_respond(self, event: AstrMessageEvent, req: ProviderRequest):
        return await StyleMind.remind_respond(self, event, req)

    @filter.on_llm_request(priority=-70)
    async def remind_rebuttal(self, event: AstrMessageEvent, req: ProviderRequest):
        return await StyleMind.remind_rebuttal(self, event, req)

    @filter.on_llm_request(priority=-80)
    async def asks_snapshot(self, event: AstrMessageEvent, req: ProviderRequest):
        """记下这一轮的聊天上下文，回复回来时拿去把关。"""
        return await StyleMind.asks_snapshot(self, event, req)

    @filter.on_llm_response(priority=10)
    async def asks_check(self, event: AstrMessageEvent, resp: LLMResponse):
        """回复里认真问了对方刚说过答案的事：发之前删掉那一行（出错、超时就照原样发）。"""
        return await StyleMind.asks_check(self, event, resp)

    @filter.on_agent_done()
    async def asks_history(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        """存进历史的那份在回复钩子之前就写好了：也删掉，免得下一轮她以为自己问过。"""
        return await StyleMind.asks_history(self, event, run_context, response)

    @filter.on_llm_request(priority=-(2 ** 61))  # 别的插件都加完材料之后、draft_request_ref（记下请求）之前
    async def brain_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """主模型这一轮当大脑，人设里扮佳树说话的那段换成大脑的要求（brain.py）。"""
        return await StyleMind.brain_request(self, event, req)

    @filter.on_llm_request(priority=-(2 ** 62))  # 别的插件都改完之后（kaju_basics 最后挪动的是 -sys.maxsize，拿的是同一个对象）
    async def draft_request_ref(self, event: AstrMessageEvent, req: ProviderRequest):
        """记下主模型这一轮真正收到的请求对象（records.py 的草稿输入日志用；插话那条路 provider_request 是另一份）。"""
        event.set_extra("_ks_draft_req", req)

    @filter.on_llm_request(priority=-81)
    async def rewrite_snapshot(self, event: AstrMessageEvent, req: ProviderRequest):
        """记下这一轮的上下文（称呼：话）和回复器看的前文，回复回来时用。"""
        return await StyleMind.rewrite_snapshot(self, event, req)

    @filter.on_llm_response(priority=5)
    async def rewrite_reply(self, event: AstrMessageEvent, resp: LLMResponse):
        """外面这层只负责记录（records.py）：照指导写本身在 _rewrite_reply。"""
        return await StyleMind.rewrite_reply(self, event, resp)

    @filter.on_agent_done()
    async def rewrite_history(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        """历史里存的是大脑的指导（回复钩子之前就写好了）：换成真正发出去的。"""
        return await StyleMind.rewrite_history(self, event, run_context, response)

    @filter.on_llm_response()
    async def after_reply(self, event: AstrMessageEvent, resp: LLMResponse):
        return await StyleMind.after_reply(self, event, resp)

    @filter.on_decorating_result(priority=20)
    async def hush_model_error(self, event: AstrMessageEvent):
        """主模型全挂时 AstrBot 自己发的报错 / 固定句子不发，DeepSeek 告诉兄长（只发回复器的话时）。"""
        return await StyleMind.hush_model_error(self, event)

    @filter.on_decorating_result(priority=10)
    async def restyle_outgoing(self, event: AstrMessageEvent):
        return await StyleMind.restyle_outgoing(self, event)

    @filter.on_decorating_result(priority=-100001)  # 别的插件都改完文字之后：开头 @ 大脑点名的人（11-21）
    async def add_at(self, event: AstrMessageEvent):
        StyleMind.put_at(self, event, lambda qq, name: Comp.At(qq=qq, name=name), Comp.Plain)

    @filter.on_agent_done()
    async def restyle_history(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        """把存进历史的那条回复也改掉，模型就不会从上下文里学回句号。"""
        return await StyleMind.restyle_history(self, event, run_context, response)
