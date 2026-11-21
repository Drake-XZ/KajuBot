"""kaju_learn 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_core.learn.mind.LearnMind（逻辑都在那边）。

原说明：
学到的东西：她接触到的一切——私聊、群聊、看过的视频、读过的书和文件、听过的歌、上网查过的——
都能让她学到东西，攒成她自己的一本"懂的东西"，越学越懂。

以前：看完视频只留"感受"（kaju_heart 的心声、喜好账本只记喜不喜欢），聊天里别人讲给她的事
只在那一轮的上下文里，过了就没了。她每次都像第一次看，不会越看越懂。

这里做五件事：
1. 学（从哪儿学）
   - 聊天：后台每几分钟读 kaju_life 的聊天记录（私聊、群聊都算，她没说话的群聊也算），一段聊天安静下来后
     整段交给模型，挑出她能学到的"世上的东西"（作品、角色、梗、歌、UP主、知识、做法……），
     比如兄长大人说"那只小傻龙是终末地的陈千语"。她自己说的只当上下文（她可能说错），别人纠正她的记对的。
     聊天里这些人自己的私事、对她的要求和称呼不记（另有人物记忆、铭记、称呼簿）。
   - 看过/读过/听过的：kaju_basics 读过的文件、看过的 B站/抖音视频、听过的歌（event extra kaju_docs_read），
     她自己刷 B 站看完的每个视频（kaju_basics 调 learn_content）。记视频讲到的东西，不是视频本身。
   - 上网查过的：她调用搜索/打开网页的工具，查到的内容也学进去。
   - 第一次启用时：最近几天的聊天记录、memory_weight 珍藏里兄长大人分享过的书和视频也补学一遍。
2. 记（book.py）：一样东西一条——是什么、知道的几个点、她的看法、跟别的东西的关系、拿不准的说法、
   在哪儿碰到过。再碰到就往这条上补；不靠谱的说法（"好像"、二创玩梗、跟已有的对不上）进"拿不准"；
   被纠正了把旧说法挪走、记一句"以前弄错过"。碰到的日子越多、知道得越多、用得越多就越熟
   （听说过 → 知道一些 → 挺熟 → 很懂）；很久没碰也没用就记不清（越熟忘得越慢）。
3. 消化：每天睡前（digest_hour 点）把最近碰到过的条目和跟它们有关的旧条目一起交给模型理一理：
   同一样东西合并、知道的去重、矛盾的以靠谱的为准、发现东西之间的联系、冒出"想弄明白的事"，
   有时还有一句"原来是这样"。想弄明白的事会在她自己刷 B 站又没说看什么时拿去搜（kaju_basics 调 wonder_topic）。
4. 用：每轮请求前，对方这句话（还有这轮她正在看的视频/文件）提到了她知道的东西（名字、别名，
   或者本地向量模型 bge-m3 觉得意思很近），就在提示里给她看【你知道的】：熟悉程度、是什么、知道的几点、
   关系、看法、拿不准的、从哪儿知道的（别人私聊里讲的只说"听人说的"）。她回复里说出来了就算用了一次（更熟、更不容易忘）。
   工具 recall_knowledge 让她自己想一想（"你最近学到什么了""你知道 XX 吗"）。
5. 命令 /佳树学到的 [最近｜看 名字｜忘掉 名字｜好奇｜消化｜学]（管理员）。

状态在 plugin_data/astrbot_plugin_kaju_learn/book.json（本子 + 读到哪了），向量在 vec.json。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
import kaju_core
kaju_core.fresh("learn")  # 热重载这个插件时，重新部署过的 kaju_core.learn 也跟着换新
from kaju_core.learn.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_core.learn.mind import LearnMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "学到的东西：聊天、看过的视频和书、听过的歌、上网查过的都能让她学到东西，攒成自己懂的东西，越学越懂", "1.7.0")
class KajuLearn(LearnMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        LearnMind.__init__(self, AstrBody(context, plugin_log(logger)), config)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await LearnMind.terminate(self)

    @filter.on_llm_request(priority=-13)  # 每轮会变：kaju_basics 的稳定前缀会把它挪到这一轮消息末尾
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        return await LearnMind.inject(self, event, req)

    @filter.on_llm_tool_respond()
    async def learn_from_tool(self, event: AstrMessageEvent, tool, tool_args, tool_result):
        """上网查过的：查到的内容也学进去。"""
        return await LearnMind.learn_from_tool(self, event, tool, tool_args, tool_result)

    @filter.on_llm_response(priority=11)  # kaju_style 的问句把关（10）、照指导写（5）之前：先把读书情况改对
    async def reading_check(self, event: AstrMessageEvent, resp: LLMResponse):
        """草稿里说的读书进度、情节对着实际核对；答应了接着读 / 先停却没改的，照她答应的改过来。"""
        return await LearnMind.reading_check(self, event, resp)

    @filter.on_agent_done()
    async def reading_history(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        """历史里的草稿也换成改对的那份（kaju_style 换成写手的话时不动）。"""
        return await LearnMind.reading_history(self, event, run_context, response)

    @filter.on_llm_response(priority=-100002)
    async def after_reply(self, event: AstrMessageEvent, resp: LLMResponse):
        return await LearnMind.after_reply(self, event, resp)

    @filter.llm_tool(name="recall_knowledge")
    async def recall_knowledge(self, event: AstrMessageEvent, keyword: str = ""):
        """想一想你自己以前学到、知道的东西（看过的视频和书、听别人讲过的、上网查过的）。对方问你知不知道某样东西（作品、角色、梗、歌、知识……）、你想不起细节时，或者问你最近学到了什么、懂些什么时用。

        Args:
            keyword(string): 要想的东西的名字或者话题，比如"伊蕾娜"、"蓝色大肥鱼"、"星星"；想看最近学到了什么就留空
        """
        return await LearnMind.recall_knowledge(self, event, keyword)

    @filter.llm_tool(name="reading_pace")
    async def reading_pace(self, event: AstrMessageEvent, action: str, title: str = ""):
        """改你读那本长书的节奏。对方让你读快点、一口气读完、先停一下、接着读、不读了时用（你在读的书在【你正在读的】里）。

        Args:
            action(string): 快一点 / 一口气读完 / 慢慢读 / 先停一下 / 接着读 / 不读了
            title(string): 书名（只在读好几本时才需要）
        """
        return await LearnMind.reading_pace(self, event, action, title)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树学到的")
    async def admin(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        async for _r in LearnMind.admin(self, event, action, arg):
            yield _r

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树教训")
    async def lessons_admin(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        """她自己总结的教训：不带参数看清单；删 编号；复盘 [YYYY-MM-DD]（重新复盘那天，默认昨天）。"""
        async for _r in LearnMind.lessons_admin(self, event, action, arg):
            yield _r
