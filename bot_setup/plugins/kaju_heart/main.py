"""kaju_heart 的 AstrBot 外壳：只把 AstrBot 的钩子接到 kaju_core.heart.mind.HeartMind（逻辑都在那边）。

原说明：
佳树的心情与好感（kaju_heart）。

- 心情：全局一份（她只有一颗心），四维——开心 / 精神 / 委屈紧张 / 想黏人，每维有基线（精神跟着作息走），
  没事时慢慢回到基线；她每回一轮话，后台让模型判断她此刻的感受（从固定列表里选）和强度，
  再按表推一下各维（每轮钳位）。最近的强烈感受连同原因保留一阵，下一轮还记得"刚才为什么不开心"。
- 好感：每个人一份，0~100，第一次见面从 50 起（以前聊得多的高一点），兄长大人本人固定在最高档附近。
  同一次后台判断里给出 -5~+3 的变化：越高越难涨、每轮/每天有上限，刷好感没用；很久没聊会慢慢回到中间。
- 说话受影响：每轮请求前把【此刻的心情】（心情、刚才的事、怎么带进语气）和【对这个人的感觉】
  （档位 + 态度 + 最近的事）放进提示；心情还会改变她在群里主动插话的积极性（smart_chime_in 读 chime_factor）。
- 心事：强烈的负面感受（委屈、生气、难过、担心、害怕、吃醋……）变成一件"心事"，不会只按时间消失：
  · 时间冲淡它（生气来得快去得快，委屈、担心挂得久）；心里压着事时，心情的"平常值"也被往下拽；
  · 对方道歉、哄她、说开了 → 放下；同样的事又来一次 → 加重（每轮的后台判断顺带看）；
  · 每隔几个小时、第二天早上，后台让她把心事"回想"一遍，参考之后真实发生的聊天：越想越委屈、慢慢平复、
    冷静下来后悔自己太凶、或者放下；每次最多变一档多，超过几天的直接放下（她不记仇）。
  · 提示里给她看"心里还压着的事"+ 她心里怎么想 + 想怎么做（比如等TA先道歉、找机会说句软话）。
- 隐私：别的聊天里发生的事，只告诉她"刚才在别处有点不开心"，不把原因带到这里；兄长大人本人例外。
- 心里记下的（inner.py）：长期记忆（memorix）的聊天总结只记"谁说了什么"。这里每轮回复后把她的感受（上面的判断）
  和回复前的思考（去掉"怎么写回复"的部分）攒下来，这个聊天安静下来后，让模型写成一段她自己的心里话——
  当时怎么理解对方、哪句话让她有什么感受、想了没说出口的话、暗暗决定的事——以这个聊天的记忆存进 memorix
  （以【佳树心里】开头，只在这个聊天里被想起来）。寻常寒暄不记。

- 关系的几个侧面（relation.py）：好感之外，每个人还有信任（说话算不算数）、在意（TA是不是也在意她）、边界（有没有越过线），
  每轮判断顺带挑出"守约/失约/在意她/冷落她/越界/尊重她/骗她"，代码按规则慢慢改；谁一般多久来一次（读 kaju_life 聊天记录），
  兄长大人比平时晚很多还没来，她会有点想他，回来时可以带点小委屈。同样的经历反复发生会沉淀成她自己的倾向
  （怕被丢下、戒心），具体哪几次记不清了，倾向还在。提示里只用一两句人话说明显的部分。思路来自抖音「小凌的创造者」。
- 喜好自己长出来（taste.py）：判断顺带写出她的感受来自哪样东西（具体名字 / 什么样的 / 大类），记进账本；
  同一类东西在不同的日子里反复打动她，就长成她自己的"喜欢"（反复不舒服就是"不太喜欢"），
  提示里有一张她自己长出来的喜好清单，聊到时会来劲、偶尔想要更多。同样来自「小凌的创造者」（触受爱取有）。
- 最依赖的人（bond.py，原 kaju_bond 插件）：每轮告诉她最依赖兄长大人本人、这次说话的是不是他；
  被骚扰时用 ask_brother_for_help 去找兄长大人（私聊告诉他；在群里她回对方的那条开头 @ 他，走 kaju_style 的 @ 人）。
- 兄长大人本人是谁：读称呼簿（address_book）的 owner_qq，这里不另配。

思路参考抖音「玄清」的 WhaleGirl V5.0 图文笔记（激素基线回归、事件扰动、单轮钳位、离线时间压缩、
状态只由代码保存），代码是自己写的。

命令：/好感度 [@某人|QQ]（自己的谁都能看；看别人、/好感度 全部、/好感度 设 QQ 值 要管理员）
      /佳树心情 [重置|回想|放下 编号|心里话|记下]（管理员）
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
import kaju_core
kaju_core.fresh("heart")  # 热重载这个插件时，重新部署过的 kaju_core.heart 也跟着换新
import kaju_platforms  # noqa: E402

kaju_platforms.fresh("qq")  # noqa: E402
from kaju_platforms.qq import bond  # noqa: E402 — 找兄长帮忙是 QQ 上的动作
from kaju_core.heart.mind import *  # noqa: E402,F401,F403 — 老名字（常量、函数）：测试和别处还从这里拿
from kaju_core.heart.mind import HeartMind  # noqa: E402
from kaju_astr import AstrBody, plugin_log  # noqa: E402


@register(PLUGIN_NAME, "dsh", "佳树的心情与好感：心情随聊天起伏、对每个人有好感和信任，说话的语气跟着变；她当时的感受和想法也记进长期记忆；喜好自己长出来；最依赖兄长大人；自己刷到的视频也会记在心里", "1.12.0")
class KajuHeart(HeartMind, Star):
    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        HeartMind.__init__(self, AstrBody(context, plugin_log(logger)), config)
        # 找兄长帮忙（私聊他、群里 @ 他、记进私聊历史）是 QQ 上的动作（kaju_platforms.qq），通过 body 发
        self.bond = bond.Bond(self.body, lambda: self.config.get("bond") or {}, lambda: self.owner, self._address)

    async def terminate(self):
        # AstrBot 只认这个类自己写的 terminate（继承来的不调）：不写的话热重载时旧实例的后台循环停不下来
        # （2026-11-15 kaju_learn 重载后新旧两个读书循环各读一遍同一段）
        await HeartMind.terminate(self)

    @filter.on_llm_request(priority=98300)  # 早执行：清单不常变，留在系统提示的稳定前缀里
    async def inject_tastes(self, event: AstrMessageEvent, req: ProviderRequest):
        return await HeartMind.inject_tastes(self, event, req)

    @filter.on_llm_request(priority=-30)
    async def inject(self, event: AstrMessageEvent, req: ProviderRequest):
        return await HeartMind.inject(self, event, req)

    @filter.on_llm_request()
    async def inject_bond(self, event: AstrMessageEvent, req: ProviderRequest):
        return await HeartMind.inject_bond(self, event, req)

    @filter.llm_tool(name="ask_brother_for_help")
    async def ask_brother_for_help(self, event: AstrMessageEvent, what_happened: str, message_to_brother: str):
        """有人骚扰你、欺负你时，去找你最依赖的兄长大人本人帮忙：私聊告诉他发生了什么，在群里还会 @ 他。先按你的情绪回对方，再调用这个工具。普通玩笑、斗嘴不要用。

        Args:
            what_happened(string): 一句话说清楚发生了什么，例如"一直问佳树住哪里，说了不告诉还追着问"
            message_to_brother(string): 你对兄长大人说的话，用佳树的口吻，短一点（一两句），比如"兄长大人！有人一直欺负佳树，快来帮帮佳树嘛"
        """
        return await HeartMind.ask_brother_for_help(self, event, what_happened, message_to_brother)

    @filter.on_agent_done()
    async def on_done(self, event: AstrMessageEvent, run_context, response: LLMResponse):
        return await HeartMind.on_done(self, event, run_context, response)

    @filter.command("好感度")
    async def cmd_affection(self, event: AstrMessageEvent, action: str = "", arg: str = "", value: str = ""):
        """看佳树对你（或别人）的感觉"""
        async for _r in HeartMind.cmd_affection(self, event, action, arg, value):
            yield _r

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树心情")
    async def cmd_mood(self, event: AstrMessageEvent, action: str = "", arg: str = ""):
        """查看佳树此刻的心情和心事（重置｜回想｜放下 编号｜心里话｜记下｜喜好｜忘掉喜好 名字）"""
        async for _r in HeartMind.cmd_mood(self, event, action, arg):
            yield _r
