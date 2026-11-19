"""memory_weight 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_core.memory.mind.MemoryMind（逻辑都在那边）。

原说明：
记忆轻重：让佳树记得牢的是"郑重的话"和"常用的事"，琐碎又从没用过的闲聊慢慢忘掉。

memorix 自己的遗忘对所有记忆一视同仁（关系一律 30 天半衰期，聊天摘要段落永远不忘），
也从来没把"用上过"算进去（access_count 全是 0）。这里补上三件事：

1. 记下时看分量（编码）：
   - 铭记：后台每几分钟读一遍 kaju_life 的聊天记录，挑出别人对她说的、分量重的话
     （语重心长、真心话、郑重叮嘱、诉说心事、气氛凝重时说的；约定、规矩、以后怎么称呼谁……），
     存成"铭记"——一句话 + 原话。同一件事被郑重地说了好几次，记得更牢。
   - memorix 的每条聊天记忆段落也打分量（0 琐碎闲聊 / 1 一般 / 2 要紧 / 3 郑重），参考当时的原始聊天和气氛。
2. 用上了就更牢（使用）：每轮看 memorix 给她检索出的记忆、给她看的铭记、以及她回复里出现的
   "只有某几条记忆才有的词"（比如"女王大人"），她回复里真用上了（对方这次没说过、她自己说出来的）就算用了一次：
   半衰期翻倍、从现在重新算，memorix 里对应的关系也加强一次。
3. 遗忘曲线：保留强度 = 2^(-距上次用上的天数 / 半衰期)，半衰期按分量 4 / 15 / 90 / 365 天，每用一次翻倍。
   - 分量 ≥2 或用过的：memorix 里的关系加保护，在它该被记住的期间不会被 memorix 冻结删除。
   - 分量 ≤1、强度降到 0.1 以下、至少记了 7 天的聊天摘要：从 memorix 里软删除（可以 /记忆轻重 恢复）。
     人物事实（person_fact）和导入的资料不删。
   - 铭记强度太低就不再拿给她看（不删，命令里还能看到）。

3b. 褪色（fade.py）：细节比"这件事本身"忘得快。聊天摘要的细节清晰度按分量 2 / 7 / 30 / 90 天半衰，
   当时情绪越强、想起得越多越慢，同一个聊天里差不多的事越多越快。清晰度 < 0.5 褪成"片段"，< 0.2 只剩"印象"
   （模型改写一次，两个版本一起存）。原文留在 memorix 里，只是给她看的时候换成褪色后的样子、提醒她别补细节；
   只来自褪了色的记忆的关系（细节事实）也不再给她看。她自己的心里话、人物事实不褪。

3c. 触景生情（cue.py）：对方一句话里少见的词（在她记忆里少见、平常说话里也少见）和这个聊天里一段旧记忆对上，
   按"意义 + 情绪残留 + 线索 + 新近 + 想起次数 − 干扰"算可检索性，够了就让那段记忆（长摘要只给被勾到的那一两句）
   自己冒出来，提示她可以自然带一句。memorix 这轮已经给的、琐碎的、刚聊过的不算；有冷却。

4. 珍藏的文件（shelf.py）：兄长大人分享给她的文件（kaju_basics 读过的那些）单独收好——当时读到的内容（全文或读后笔记）、
   他分享时说的话、她读完的回复和情绪（kaju_heart 的判断），原文件也复制一份。模型按分量打 1 普通 / 2 要紧 / 3 郑重
   （读完情绪波动大、兄长大人语重心长的更重），封存 30 / 180 / 365 天内一直记得清楚，之后才按遗忘曲线淡忘，
   每想起一次（她回复里用上、或者用 recall_shared_file 翻出来）半衰期翻倍。

5. 工作记忆（working.py，原 working_memory 插件）：每回完一轮，后台把刚才聊天的要点（弄清的事、图里有什么、
   她自己的推断、没弄清的）整理成一份备忘，下一轮回复前放在她眼前；90 分钟没更新或换了对话就作废。

6. 未了的事（loops.py，1.7.0，2026-11-18 照 anima-brain 的 open loops）：读聊天记录时顺带看对方提过、还不知道结果的事
   （考试、面试、看病、出远门、等通知……）和记着的有没有下文；按要紧 × 上心 × 新近 + 离那天多近排，
   对方这句碰到了这件事、或者日子近了，就放进【还没结果的事】给她看。/记忆轻重 未了 看清单。

7. 铭记作废线（1.9.0，2026-11-18 照 dsh-soul 的 supersedes）：挑铭记时把这个人已经记着的铭记也给模型看，
   新的一条改掉了旧的（"replaces"）、或者新消息让旧的不再成立（"retire"：说不用了、那是一时的事已经过去了），旧的标 superseded、
   留着原因，不再给她看（/记忆轻重 铭记 里看得到"不再成立：……"）。

兄长大人本人是谁：读称呼簿（address_book）的 owner_qq，这里不另配。

给她看：
- 【铭记在心】这次说话的人以前郑重对她说过的话（群里只给这个群里说过的，私聊给这个人说过的全部）。
- 【珍藏的文件】这次说话的人分享给她、还记得的文件清单（同样的范围）；对方提到其中某份时，把当时读到的内容也翻出来。
  2026-11-03（1.5.0）：翻出来以后 shelf.carry_minutes（20）分钟内接着聊（"而且节奏很快""也没多少剧情"这种不提书名的话）
  也继续给，期间又碰到文件里的词就重新计时。以前只有提到文件名/关键词的那一句才给，后面几句她手里只剩书名，
  只能说"心里一沉""平平的"这种空话。对比测试（9 个真实聊书时刻 ×2，配合 kaju_style 的"说具体"）：具体 1.11→2.00。
- memorix 检索结果里，郑重的标"这是很郑重的事"，快忘了的标"记得有点模糊了"。

管理员命令：/记忆轻重 [铭记|珍藏|未了|褪色|遗忘|删 编号|恢复 操作号|整理]、/佳树备忘（这个会话的工作记忆）
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
import kaju_core
kaju_core.fresh("memory")  # 热重载这个插件时，重新部署过的 kaju_core.memory 也跟着换新
from kaju_core.memory.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_core.memory.mind import MemoryMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "记忆轻重：郑重的话、常用的事、珍藏的文件记得牢，琐碎闲聊慢慢忘，细节慢慢褪色，一句话能勾起旧回忆；边聊边记刚才的要点；聊着珍藏的文件时一直记得内容；记得对方还没结果的事", "1.10.0")
class MemoryWeight(MemoryMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        MemoryMind.__init__(self, AstrBody(context, plugin_log(logger)), config)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await MemoryMind.terminate(self)

    @filter.on_llm_request(priority=98500)  # 早执行：不常变，留在系统提示的稳定前缀里
    async def inject_keepsakes(self, event: AstrMessageEvent, req: ProviderRequest):
        return await MemoryMind.inject_keepsakes(self, event, req)

    @filter.on_llm_request(priority=-10)  # memorix 注入（优先级 0）之后
    async def collect_offered(self, event: AstrMessageEvent, req: ProviderRequest):
        return await MemoryMind.collect_offered(self, event, req)

    @filter.on_llm_request(priority=-11)  # collect_offered（-10）之后：知道 memorix 这轮已经给了哪些
    async def cue_recall(self, event: AstrMessageEvent, req: ProviderRequest):
        return await MemoryMind.cue_recall(self, event, req)

    @filter.on_llm_response(priority=-100001)
    async def after_reply(self, event: AstrMessageEvent, resp: LLMResponse):
        return await MemoryMind.after_reply(self, event, resp)

    @filter.on_llm_request(priority=98400)  # 早执行：清单不常变，留在系统提示的稳定前缀里
    async def inject_shelf(self, event: AstrMessageEvent, req: ProviderRequest):
        return await MemoryMind.inject_shelf(self, event, req)

    @filter.on_llm_request(priority=-12)  # 每轮会变：稳定前缀会把它挪到这一轮消息末尾
    async def shelf_detail(self, event: AstrMessageEvent, req: ProviderRequest):
        """对方提到了某份珍藏的文件（文件名、关键词、"上次那篇"），把当时读到的内容翻出来给她看。"""
        return await MemoryMind.shelf_detail(self, event, req)

    @filter.on_llm_request(priority=-14)  # memorix（0）放进人物画像之后、collect_offered（-10）读完之后
    async def swap_profiles(self, event: AstrMessageEvent, req: ProviderRequest):
        """人物印象（impress.py）：memorix 的【人物画像】里有印象的人换成睡前整理的印象。"""
        return await MemoryMind.swap_profiles(self, event, req)

    @filter.on_llm_request(priority=-13)  # 每轮会变（碰到的词、日子远近）：稳定前缀会把它挪到这一轮消息末尾
    async def inject_loops(self, event: AstrMessageEvent, req: ProviderRequest):
        """未了的事（loops.py）：对方提过、还不知道后来怎么样的事，聊到相关的或者日子近了给她看。"""
        return await MemoryMind.inject_loops(self, event, req)

    @filter.llm_tool(name="recall_shared_file")
    async def recall_shared_file(self, event: AstrMessageEvent, keyword: str):
        """翻出对方以前分享给你、你收着的文件或B站视频，重读一遍当时读到/看到的内容。对方问起以前发给你的文件、故事、文章、视频，你想不起细节时用。

        Args:
            keyword(string): 文件名、书名或者里面的人物、关键事物，比如"邮差"、"那封信"
        """
        return await MemoryMind.recall_shared_file(self, event, keyword)

    @filter.on_llm_request(priority=50)
    async def inject_memo(self, event: AstrMessageEvent, req: ProviderRequest):
        return await MemoryMind.inject_memo(self, event, req)

    @filter.on_agent_done()
    async def update_memo(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        return await MemoryMind.update_memo(self, event, run_context, response)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树备忘")
    async def show_memo(self, event: AstrMessageEvent):
        """查看这个会话当前的工作记忆备忘"""
        async for _r in MemoryMind.show_memo(self, event):
            yield _r

    @filter.command("记忆轻重")
    async def admin(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        async for _r in MemoryMind.admin(self, event, action, arg):
            yield _r
