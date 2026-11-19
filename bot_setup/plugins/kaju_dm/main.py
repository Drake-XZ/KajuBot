"""kaju_dm 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_platforms.dm.mind.DmMind（逻辑都在那边）。

原说明：
佳树私信：别人在B站（以后还有抖音）私信她，她像在 QQ 私聊一样回。

规矩（兄长定的，2026-11-08）：
- 只回和她互关的人。别人可以随便关注她；她要关注谁（回关），得先在 QQ 上问兄长，兄长同意了才关注。
  没互关的人发来的私信先存着（ledger.held），等兄长同意、关注上、互关了再接着回。兄长说不关注的人，以后不再问。
- 兄长以外的人，每人每天最多让她看 video_per_day 条视频；多的先不看，去 QQ 问兄长，同意了再看。
- 兄长本人的B站号（owner_bili_mid）不受这些限制，而且就是他的 QQ 私聊那段聊天（在哪边聊她都记得）。

怎么做：
- 后台每 poll_seconds 秒看一眼有没有未读私信（bilidm.py，借 kaju_basics 的B站小号登录）；
  有就读出新消息、标已读，按人交给 _chat：当成这个人发来的私聊送进完整流程（turn.py），
  她说的每一句（包括看视频前那句"先去看"）都发成B站私信；表情包传到B站图床发成图片私信（_patch_memes）。
- 每 fans_minutes 分钟看一眼粉丝列表：新关注她、还没互关的人 → 登记"要不要回关"。
- 要兄长批的事攒在 ledger.requests，通知用 QQ 私聊发给兄长（安静时段不发，攒着）。
  兄长回「/佳树私信 批准 n」「/佳树私信 拒绝 n」，或者在 QQ 私聊里直接跟她说，她调 answer_dm_request。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from . import turn  # noqa: E402
import kaju_platforms  # noqa: E402

kaju_platforms.fresh("bili", "douyin", "shared", "dm")  # 重新部署过的平台代码也跟着换新
from kaju_platforms.dm.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_platforms.dm.mind import DmMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "B站私信：互关的人能私信佳树聊天、发视频；回关和多看的视频要兄长在 QQ 同意", "1.6.0")
class KajuDm(DmMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        self.turn = turn  # 把私信变成 AstrBot 的私聊事件、送进完整流程（turn.py，AstrBot 专用，留在外壳）
        DmMind.__init__(self, AstrBody(context, plugin_log(logger)), config)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await DmMind.terminate(self)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树私信")
    async def cmd_dm(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        """B站私信：/佳树私信（待批的事和今天的情况）｜批准 n｜拒绝 n｜关注 B站UID"""
        async for _r in DmMind.cmd_dm(self, event, action, arg):
            yield _r

    @filter.on_llm_request(priority=-60)
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        return await DmMind.inject(self, event, req)

    @filter.on_agent_done()
    async def mark_done(self, event: AstrMessageEvent, run_context, response):
        return await DmMind.mark_done(self, event, run_context, response)

    @filter.llm_tool(name=TOOL)
    async def answer_dm_request(self, event: AstrMessageEvent, request_id: str, approve: bool):
        """兄长大人回答了B站/抖音私信那边等他决定的事（要不要关注某人、某人多发的视频要不要看）时调用。只有兄长大人本人说了才算。

        Args:
            request_id(string): 那件事的编号（#后面的数字）
            approve(boolean): 兄长大人同意填 true，不同意填 false
        """
        return await DmMind.answer_dm_request(self, event, request_id, approve)

    @filter.llm_tool(name=TOOL_CLAIM)
    async def claim_same_person(self, event: AstrMessageEvent, who: str):
        """在B站/抖音私信里，对方说自己就是你在 QQ（群里或私聊）认识的某个人时调用（比如"我是女王大人""我就是群里的某某"）。会去 QQ 问兄长大人是不是同一个人，兄长大人确认了才算。

        Args:
            who(string): 对方说自己是谁：TA说的称呼、名字或 QQ 号，照TA的原话填
        """
        return await DmMind.claim_same_person(self, event, who)

    @filter.llm_tool(name=TOOL_LINK)
    async def link_same_person(self, event: AstrMessageEvent, site: str, account_name: str, who: str):
        """兄长大人告诉你，B站或抖音上私信你的某个人就是 QQ 上的某个人时调用（比如"抖音那个 dy_demo 就是女王大人""刚才关注你的就是来点作用吧"）。记下以后，TA在两边就是同一个人。只有兄长大人本人说了才算。

        Args:
            site(string): 抖音 或 B站
            account_name(string): TA在B站/抖音上的名字；兄长大人说的是"刚才那个人"、没说名字就留空（用最近私信过你的那个）
            who(string): TA在 QQ 上是谁：称呼、群名片或 QQ 号
        """
        return await DmMind.link_same_person(self, event, site, account_name, who)
