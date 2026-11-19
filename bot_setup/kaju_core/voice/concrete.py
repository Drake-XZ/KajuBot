"""说具体、说连贯：聊一部作品（书、动画、电影、游戏、视频）的时候，用里面具体的东西说看法。

2026-11-03 兄长大人：跟她聊《妹妹人生》时她说话跳、不具体，"几个词一个逗号"——
  "大半篇幅都是吃饭、等门、说不上几句话的日子，句子还平得很 / 可偏偏就是这些平平的地方，读到一半会突然心里一沉"。
原因两个：书的笔记只在提到书名那一句才给她（memory_weight 1.5.0 改成话题延续）；
句长提醒（brevity）和逗号拆句把她往短碎片上推。
这一轮在聊作品时：加这条提醒、不在逗号处拆消息（句长提醒 2026-11-13 已删）。
对比测试（9 个真实聊书时刻 ×2，deepseek-v4-pro 评审）：具体 1.11→2.00、连贯 1.94→2.00；
兄长大人盲选 18 对：回得对、看得懂 10 比 7，像佳树 11 比 5。回复中位 70→110 字。
"""

import re

NOTE = (
    "\n\n【说具体、说连贯】这一轮在聊一部作品。说看法的时候用里面具体的东西来说：具体的情节、人物或原话"
    "（比如\"哥哥为了妹妹和女友分手那段\"），别只说\"心里一沉\"\"平平的\"\"藏着东西\"这种印象；"
    "句和句要接得上（因为、所以、可是），一次说清一两点就好，别把几个词用逗号堆在一起。"
)

WORK = re.compile(r"书|小说|漫画|动画|番剧|新番|电影|剧情|角色|主角|结局|这本|那本|这部|那部|这集|那集|游戏|视频|歌|作者|原作")
OPINION = re.compile(r"感觉|感想|觉得|怎么看|怎么想|想法|喜欢|评价|印象|哪里不一样|哪段|哪里|为什么|节奏|剧情")


def should_fire(message: str, shelf_offered: bool, docs_read: bool) -> bool:
    """This turn is about a work: its notes are in front of her, she just read one, or he asks her view on one."""
    if shelf_offered or docs_read:
        return True
    text = message or ""
    return bool(WORK.search(text) and OPINION.search(text))
