"""kaju_life 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_core.life.mind.LifeMind（逻辑都在那边）。

原说明：
佳树的生活：她自己的每日日程 + 日记/周记/月记（原 kaju_daily / kaju_diary 合并）。

- 日程（daily.py）：每天第一次需要时后台写一份"佳树今天"的小日程，聊天时把到现在为止的事放进提示。
- 日记（diary.py）：记录聊天，后台每天写日记、每周写周记、每月写月记，把最近的回忆放进提示；
  写日记时会参考她当天的日程。
- 都按 AstrBot 配置的时区（北京时间）过日子，day_start_hour 点算新的一天。
- 工具：read_diary / search_diary。管理员命令：/佳树日程 [重写]、/佳树日记 [日期|上周|10月|补写 日期]。
- 关于自己（selffacts.py，1.1.0）：人设卡换成两句身份后，每轮按对方刚说的话从"关于自己"清单里想起最相关的几条。
"""

import sys
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
import kaju_core
kaju_core.fresh("life")  # 热重载这个插件时，重新部署过的 kaju_core.life 也跟着换新
from kaju_core.life.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_core.life.mind import LifeMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "佳树的生活：每天的小日程 + 日记/周记/月记，聊天时记得最近发生的事；想起关于自己的事", "1.2.1")
class KajuLife(LifeMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        LifeMind.__init__(self, AstrBody(context, plugin_log(logger)), config)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await LifeMind.terminate(self)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize - 5)
    async def log_incoming(self, event: AstrMessageEvent):
        return await LifeMind.log_incoming(self, event)

    @filter.on_llm_response(priority=-100000)
    async def log_reply(self, event: AstrMessageEvent, resp: LLMResponse):
        return await LifeMind.log_reply(self, event, resp)

    @filter.on_llm_request(priority=-500)  # 每轮都变，放在系统提示后面，不打乱前面稳定的部分
    async def inject_self_facts(self, event: AstrMessageEvent, req: ProviderRequest):
        return await LifeMind.inject_self_facts(self, event, req)

    @filter.on_llm_request(priority=99000)  # 早执行：日记一天才变一次，留在系统提示的稳定前缀里
    async def inject_diary(self, event: AstrMessageEvent, req: ProviderRequest):
        return await LifeMind.inject_diary(self, event, req)

    @filter.on_llm_request(priority=-40)
    async def inject_daily(self, event: AstrMessageEvent, req: ProviderRequest):
        return await LifeMind.inject_daily(self, event, req)

    @filter.llm_tool(name="read_diary")
    async def read_diary(self, event: AstrMessageEvent, when: str = ""):
        """翻看你自己以前写的日记、周记或月记，回想某天/某周/某月发生了什么。被问到"那天/上周/上个月发生了什么、你还记得吗"时先翻一下再回答。

        Args:
            when(string): 想看哪天，例如 昨天、前天、2026-10-29、10月29日、上周、这周、上个月、10月；留空看最近一篇
        """
        return await LifeMind.read_diary(self, event, when)

    @filter.llm_tool(name="search_diary")
    async def search_diary(self, event: AstrMessageEvent, keywords: str):
        """在你自己写过的日记、周记、月记里按关键词找某件事、某个人是哪天的事。想不起来某件事什么时候发生、细节是什么时用。

        Args:
            keywords(string): 关键词，可以用空格隔开好几个，例如 "音游 兄长大人" 或 "女王大人 加班"
        """
        return await LifeMind.search_diary(self, event, keywords)

    @filter.command("佳树日程")
    async def show_daily(self, event: AstrMessageEvent, action: str = ""):
        async for _r in LifeMind.show_daily(self, event, action):
            yield _r

    @filter.command("佳树日记")
    async def show_diary(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        async for _r in LifeMind.show_diary(self, event, action, arg):
            yield _r
