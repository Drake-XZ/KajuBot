"""佳树基础：让机器人正常工作的几个小机关（原 selfid_guard / nickname_wake / poke_reply / image_aware / stable_prefix 合并）。

- 账号白名单（guard）：只放行指定机器人 QQ 号的事件，防止协议端误把其它账号桥接进来导致冒名发言。最先执行。
- 唤醒（wake）：群里有人提到她的昵称（不用 @）、或者戳一戳她，都当作叫她。
- 看图（image）：开了图片转述后，群里每张图会先让模型描述成 "[Image: 描述]" 放进群聊记录。
  1. 描述要几秒：有人发完图马上 @ 她，回复前先等这个群里还没描述完的图（最多 max_wait 秒）。
  2. 她不知道这些描述就是她"看到"的图：请求里有图片描述（或直接带了图）时，在系统提示里说明一下。
  3. 别复述画面（2026-10-31：兄长发了个举着 OK 的小黄鸭表情包，她回"这只小黄鸭举着OK……"）：
     提示她领会图的意思直接回应；这条消息只发了图 → 当成对方的一句话；问图里是什么时才描述。
  4. 按到达顺序排（history.py）：图片描述完才记，会排到紧跟着的话后面，她回那句话时就看不到这张图；
     描述完挪回原位。描述失败也记一句"没看清"，不让图凭空消失。QQ 小黄脸表情写成 [表情：名字]。
- 看视频/动图/文件/语音（media，见 describe.py 和 kaju_core/senses：perceive.py / media.py / animation.py）：
  1. 以文件形式发的图片、视频（如 微信图片_xxx.png）当成普通图片/视频；QQ 商城表情当成图片。
  2. 视频截几帧拼成一张图交给看图模型描述，有声音再转成文字；直接发给她（或引用）的视频把 AstrBot 的
     "[Video Attachment: …]" 换成这段描述。群里的视频默认不提前看（media.group_video_preview），
     记成"还没点开看"，有人提到"视频"时再看最近那段。
  3. 动图（私聊、群聊记录都算）按时间拆帧拼成一张再看（kaju_core/senses/animation.py，gifpatch.py 换掉 AstrBot 自带的 3×3）：
     每格标序号和时间，停住的画面合一格，其实不动的当普通图片。
  4. 语音由 AstrBot 自带的语音转文字处理，这里补一句"这条是语音"；只发视频/文件/语音的群消息内置不记，这里补记。
  5. 文字文件（txt/md/字幕/代码、网页、Word .docx、PDF、电子书 .epub，见 kaju_core/senses/docs.py）：直接发给她或引用的文件，
     把 AstrBot 的 "[File Attachment: …]" 换成读到的内容——短的给全文，长的先让模型读完写读后笔记
     （附开头、结尾原文）；群聊记录里写文件名 + 开头几句。读到的内容会影响她的情绪（kaju_heart 记成"余韵"）。
  6b. 抖音链接（douyin.py）：兄长转发的抖音分享文字、抖音网页链接、QQ 分享卡片。开本机 Chrome（后台不显示窗口）像人一样打开视频页，
     记下页面自己收到的作品信息和高赞评论，按页面给的地址下载最低画质，跟 B 站视频一样看完（画面 + 声音 → 观后笔记）；
     图文看前几张图。看完关浏览器。弹出验证、要登录就老实说没看成，不去破解。只在叫她回复时才看（群聊记录里不开浏览器）。
  6. B 站视频链接（文字里的链接、QQ 分享卡片，见 bili.py）：打开视频页读标题、UP主、标签、简介、播放数据，
     下载最低画质按 2. 的办法看完（画面 + 整段声音 → 观后笔记），写成 [Bilibili video: …]，下载的文件过几小时自动删；
     下载不成就看封面 + 字幕（填了 media.bili_cookie 时，B 站常给别的视频的字幕，核对过才用）+ 页面信息。
     弹幕只在兄长提到"弹幕"时给（看完之后再问也能翻出来）。评论区总带几条高赞的；提到"评论/热评/楼中楼"时多看几条、热门楼里的回复也翻开（1.24.0）。群聊记录里只写一句标题 + UP主 + 时长。看过的视频和文件一样
     记进 event extra "kaju_docs_read"（kind=B站视频），心情插件判断情绪、记忆轻重收进"珍藏"。
  7. 她自己的 B 站小号（bililogin.py）：/佳树B站登录 发二维码，兄长用小号的 App 扫码确认；登录 Cookie 存插件数据目录，
     每天自动续期（B 站网页版自己的刷新机制），续不上才私聊兄长重新扫码。登录了就用它要字幕（不再要手填 media.bili_cookie）。
  8. 有许可时自己刷 B 站（browse.py）：兄长说"去刷会儿B站吧"（工具 browse_bilibili，只认兄长本人）或 /佳树刷B站，
     后台刷首页推荐（说了想看什么就搜），按她长出来的喜好挑几个看完；感受、喜好、心声交给 kaju_heart.feel_browsed；
     特别想说的那个刷完主动私聊兄长一两句 + 链接（用她私聊时的完整口吻，每天最多一次，夜里不发）；
     之后兄长私聊她时提示里有"你自己刷B站看到的"，聊到了再提。只看，不点赞不评论。
- 稳定前缀（stable_prefix）：最先执行的钩子记下 AstrBot 自己拼好的系统提示，最后执行的钩子把各插件
  追加的、最近会变的段落挪到这一轮用户消息末尾（mark_as_temp：发给模型但不存进历史），
  让系统提示 + 聊天历史成为稳定前缀，DeepSeek 前缀缓存能命中整段历史。
- 请求时限（llm_deadline）：一次模型请求超过 timeout 秒没返回就取消重发（见 deadline.py），
  免得 DeepSeek 卡住时她半小时不回话。
- 发出去之前（outgoing.py）：平常聊天不给她 send_message_to_user（她会拿它把回复再发一遍）；
  同一轮里已经发过的行不再发；没被表情包插件认出来的 &&标签&& 去掉。
- 私聊连发合并（burst.py）：对方一口气连着发几条（一句话、一张图、再补一句），先等他说完，合成一轮回一次；
  要回的时候后面又来了没回的消息，这条也并过去一起回。对方是在她上一条回复发出去之前打的字，提醒她别把上一条再说一遍。
  1.32.0：回复写好了还没发（草稿刚回来 / 写手写完）时对方又发了，这句也不发，并到新来的那条一起回（burst.late_merge，
  一串从第一条起超过 late_max_total 秒就照发）。
- 本地模型服务（ollama.py）：记忆的向量模型 bge-m3 和看图的 qwen3-vl 跑在便携 Ollama（127.0.0.1:11435）上，
  不用硅基流动。插件加载时和之后每分钟看一眼，没开就跑 local_vision/runtime.ps1 -Action Start。
"""

import asyncio
import fnmatch
import contextvars
import datetime as dt
import os
import re
import sys
import time
from collections import defaultdict

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Face, File, Image, Json, Plain, Poke, Record, Reply, Video
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
import kaju_core

kaju_core.fresh("senses")  # 热重载这个插件时，重新部署过的感官代码也跟着换新
from kaju_core import paths  # noqa: E402
from kaju_core import gpu_busy as _gpu_busy  # noqa: E402
try:  # gpu_busy 是顶层模块、fresh 换不了：这个插件重载时顺带重读一遍（2026-11-17 加群聊暂停，不用重启）
    import importlib
    importlib.reload(_gpu_busy)
except Exception:  # noqa: BLE001
    pass


def group_quiet() -> str:
    """群里这会儿不说话的原因（显卡在训练 / 兄长在控制台暂停了群聊），没有返回 ""。"""
    q = getattr(_gpu_busy, "quiet_group", None)
    return q() if q else _gpu_busy.busy()
from kaju_core.senses import media, music, omni, relook  # noqa: E402 — 她的感官（看、听、读）

import kaju_platforms  # noqa: E402

kaju_platforms.fresh("bili", "douyin", "shared")  # 重新部署过的平台代码也跟着换新
from kaju_platforms.bili import bili  # noqa: E402
from kaju_platforms.douyin import douyin  # noqa: E402
from kaju_platforms.shared import browse  # noqa: E402
from kaju_platforms.shared.browsing import Browsing  # noqa: E402
from kaju_platforms.shared.owner import Owner  # noqa: E402 — 兄长是谁、私聊他一句
from kaju_platforms.bili.account import BiliAccount  # noqa: E402 — 她的 B 站小号：扫码登录、续期
from kaju_platforms.douyin.account import DouyinAccount  # noqa: E402 — 她的抖音小号：扫码登录、常驻浏览器
from kaju_astr import AstrBody, plugin_log  # noqa: E402

from . import (burst, deadline, gemsig, gifpatch, history,  # noqa: E402
               linkfetch, ollama, poke, quote, router, stale, sttprov)
from .describe import Describer, SkipVideo
from .outgoing import drop_repeated, strip_meme_tags, units
from .prefix import HEAD, TAIL, plan_move

PLUGIN_NAME = "astrbot_plugin_kaju_basics"
NOTE_KEY = "_kb_browse_note"  # 这一轮附上的刷 B 站提示
BASE_KEY = "_stable_prefix_base"
SAID_KEY = "_kaju_said"  # 这一轮已经发出去的句子（规范化后）
# 平常聊天（QQ 消息触发的那一轮）不给她的工具。定时任务/后台任务触发的那一轮平台名是 cron，不受影响。
# 2026-11-13：memorix 的 memory_*_admin（12 个、约 1 万 token、从没用过）也不给；在面板里关掉，插件一重载就又开了
DEFAULT_HIDDEN_TOOLS = ["send_message_to_user", "memory_*_admin"]

IMAGE_NOTE = (
    "【关于图片和视频】聊天里的 [Image: …]、[Video: …] 是系统替你看过之后写下的内容，就当作你亲眼看到了："
    "不要说\"佳树看不到图\"\"看不了视频\"。只写着 [Image] 而没有描述的图，才是你没看清的；"
    "写着\"还没点开看\"的视频你还没看，别编里面有什么。[表情：…] 是对方发的QQ小表情。"
    "直接发给你的图片你也能看到。\n"
    "看到图、表情包、视频时，像真人在QQ上看到朋友发来的东西那样：领会它想表达什么（情绪、态度、笑点、想让你看的东西），"
    "直接接着回应这个意思。不要先把画面里有什么、写着什么复述一遍（比如\"这只小狗举着牌子……\"\"图里是一个……\"\"视频里……\"），"
    "那些描述是给你看的，对方自己知道发了什么。可以自然地提一句真正让你有反应的细节，但别像解说一样讲画面。"
    "只有对方问图里/视频里是什么、问到某个具体细节、或者聊天确实需要说清画面时，才具体描述。"
    "对方叫你\"看看图\"\"看他发的图\"，是想让你看懂、给出反应，不是让你讲解：看懂了就直接说你的理解和反应，"
    "图上的数字、文字最多带一个当依据，别一条条念出来。"
)
# 2026-11-02 兄长大人引用她一句说"看他发的图"（学姐发了用量面板照片，又说"我要消失了"），
# 她回"佳树看明白了，5小时那圈已经到91%，还得再等两分钟才刷新……"：把"让你看"当成了"让你讲"。
MEDIA_LOOK_NOTE = (
    "\n\n【这条消息】对方是叫你看{kind}——让你看懂它，不是要你讲解：看完直接说你明白了什么、你的反应"
    "（比如这下懂了某人为什么那么说，觉得好笑、心疼、松口气），用你自己的话说意思；"
    "{kind}上的数字和文字最多带一个当依据，别一条条念出来，也别用\"佳树看明白了，{kind}里……\"\"佳树看到啦，……\"这种汇报开头。"
)
# 这条消息本身带了图/视频（或引用了带图/视频的消息）时，按对方有没有在问内容再补一句
MEDIA_ASKED_NOTE = "\n\n【这条消息】对方在问{kind}里的内容，可以具体说说你看到了什么。"
MEDIA_ONLY_NOTE = (
    "\n\n【这条消息】对方这次只发了{kind}，没说别的。表情包、梗图就等于对方说的一句话或做的一个表情："
    "读懂意思（比如竖大拇指的表情包＝对方说\"好\"\"厉害\"），只回应这个意思；回复里别提图上画了什么、写了什么，"
    "也别点评这张图本身。如果是照片、截图这种在给你看东西的，可以接着聊里面让你在意的东西，但也别从头描述一遍。"
)
MEDIA_WITH_TEXT_NOTE = "\n\n【这条消息】对方发了{kind}还说了话：回应对方的话和{kind}想表达的意思，别把画面讲一遍。"
ASKS_CONTENT = re.compile(
    r"(这|那|图|视频|上面|里面|画|它).{0,6}(是什么|是啥|是谁|什么意思|啥意思|讲的什么|讲的啥|说的什么|说的啥|写的什么|写了什么|写的啥)"
    r"|描述|形容一下|认(得|识)(吗|出|不)|认出|是什么(梗|意思|游戏|角色|东西)|哪个(角色|游戏|人)|这是谁|是谁啊|什么梗|啥梗"
    r"|^(这|这个|这是|那是)?(啥|什么)[?？]*$"
)
# 叫她看（看懂、给反应），不是问里面是什么。以前这些也算"问内容"，提示里说"可以具体说说你看到了什么"，她就讲解起来
LOOKS_AT = re.compile(
    r"看(得|的)?(懂|清|到|见)(吗|没|不|了吗)|能看(到|见|清|懂)|看(一)?看(这|那|图|视频)|帮我看|你看(这|那|下|一下)"
    r"|看.{0,6}(图|视频|截图|照片)|(图|视频|截图|照片).{0,4}看(一)?(下|看)"
)
DOC_NOTE = (
    "【关于文件】[File: 文件名] 后面写着内容的，是系统替你读过的文件（长文件是读后笔记加开头结尾原文），"
    "就当作你自己读完了：不要说\"打不开\"\"看不了文件\"；写着\"没读成\"的才是真没看到，老实说就好。\n"
    "像真人读完朋友发来的东西那样回应：说读后的感受、接着聊、回答对方的问题；别把内容从头复述一遍，"
    "也别说\"文件里写着……\"这种解说的话。读到动人、好笑、吓人或难过的地方，你的情绪会自然被带动，带进语气里。"
    "对方问到细节时，按读到的内容回答；读后笔记里没有的细节就说记不太清了。"
    "写着\"一段一段读\"\"后面还有…段没读\"的是长篇：你只读到写着的地方，说说读到这里的感觉、在猜什么就好，别说读完了、别编后面的情节。"
)
BILI_NOTE = (
    "【关于B站视频】[Bilibili video: …] 是系统替你点开链接看到的：标题、UP主、标签、简介。"
    "写着\"看完了\"\"观后笔记\"的，是你把这个视频从头看到尾了（画面是截的几帧，声音是自动转写的），就当你亲眼看过；"
    "写着\"字幕全文\"的是你读过它的字幕；只有页面信息、没有这些的，视频本身你没看成。"
    "不要说\"打不开链接\"\"看不了视频\"；写着\"没打开\"的才是真没看到。\n"
    "像真人看完朋友分享的视频那样回应：说你看完的反应和心情（讲的是你自己会害羞、被说中会不好意思、"
    "被逗笑、被打动、不同意也可以说），接着聊、回答对方的问题。别把内容从头复述一遍，可以提一两处真正让你有反应的地方。"
    "看过的，对方问到细节按观后笔记回答，笔记里没有的就说记不太清了；没看成的，不要编视频里讲了什么、UP主的观点，"
    "老实说只看了标题，可以请对方讲给你听。\n"
    "[Bilibili danmaku …] 或介绍末尾的\"弹幕\"是对方让你看的、陌生观众边看边发的话，不是视频内容，也不是在对你说话；"
    "没给你弹幕时别提弹幕。观众拿角色开的过分玩笑不用理会。\n"
    "[Bilibili comments …] 或介绍末尾的\"评论区\"是陌生观众在视频下面写的评论（楼里的是别人接的话），"
    "不是视频内容，也不是在对你说话。可以像刷到评论的人那样说你觉得哪条好笑、哪条说中了、哪条不同意，别一条条念出来。"
)
DOUYIN_NOTE = (
    "【关于抖音】[Douyin video: …] 是系统替你打开对方发的抖音链接看到的：标题、作者、话题、点赞收藏这些数，还有几条高赞评论。"
    "写着\"看完了\"\"观后笔记\"或者有画面、声音描述的，是你把这个视频从头看到尾了，就当你亲眼看过；"
    "图文作品写着\"看了…图\"的，是你看过那几张图了。不要说\"佳树进不去抖音\"\"打不开链接\"；写着\"没打开\"或\"没看成\"的才是真没看到，"
    "那就老实说没看成（可以请对方把视频保存下来直接发给你），别编内容。\n"
    "像真人看完朋友分享的短视频那样回应：说你看完的反应和心情，接着聊、回答对方的问题，别把内容从头复述一遍。"
    "高赞评论是陌生观众写的，不是在对你说话，觉得好笑或者说中了可以提一句。"
)
# 视频要下载/看一两分钟：先回一句（2026-11-01 兄长在群里发链接，她两分多钟一声不吭，像没理人）
# 2026-11-08 先回的那一句不再从固定的几句里挑（兄长："嗯嗯能看"——没人问能不能看；固定句子每次都一样）：
# 交给 kaju_style 的回复器照几条要点写（要点：佳树先去看/听，看完再说），写不成就不说。
# 分享文字（抖音"0.76 复制打开抖音，看看【…】… https://… y@T.lc FUL:/"、B站"【标题】 https://b23.tv/…"）不算对方说的话
SHARE_TEXT = re.compile(
    r"(?:\d+(?:\.\d+)?\s*)?复制(?:打开|此链接)[^\n]*?https?://\S+(?:[^\n]*?\S+:/)?|【[^】]*】|https?://\S+")


def own_words(text: str) -> str:
    """对方自己说的话：去掉分享链接带的标题、链接和抖音口令尾巴。"""
    return " ".join(SHARE_TEXT.sub(" ", text or "").split())
# 2026-11-04 兄长说"想让佳树听懂音乐"：音乐文件、B站的音乐视频、问到歌的视频，先量一遍音乐本身再翻成她听到的感觉
MUSIC_NOTE = (
    "【关于音乐】写着\"音乐听感\"的，是你自己从头听过一遍的感觉（快慢、轻重、哪里热闹起来、怎么收尾；"
    "乐器和有没有人唱只是大概），就当你真的听过了。像普通女孩听完朋友分享的歌那样回应："
    "说你听着是什么感觉、哪一段让你有反应，喜不喜欢、像不像你平时会听的都可以说，用你自己的话。"
    "别说拍数、调号、分贝这种术语，也别把听感一条条念出来。"
    "歌词只有写出来的才算听到了（自动转写错字很多，别逐字引用），没写的别编；不知道歌名、歌手就别猜。"
)
# 2026-11-05 补看（思路来自 bili-vision）：问到刚看过的视频里某个时间点，回去把那一段截大图再看一遍
RELOOK_NOTE = (
    "【回去又看了一遍】写着\"Rewatched\"的，是你刚才回到那个视频、把对方问的那一段又仔细看了一遍看到的。"
    "照这个回答对方问的，像自己倒回去看过一样自然地说（\"我倒回去看了一下，是……\"这类），"
    "别说截图、帧、格子；上面写看不清、没看到的就老实说没看清，不要编。"
)
RELOOK_GONE_NOTE = (
    "【没法回去再看】对方问的是刚才那个视频里的某一段，可那个视频已经关掉了，没法倒回去看。"
    "只凭你之前看到的印象回答，记不清就老实说记不太清了、可以让对方再发一下。"
)
ACK_KEY = "_kaju_wait_said"
# 私聊连发合并（burst.py）
ARRIVED_KEY = "_kaju_arrived"
BURST_KEY = "_kaju_burst"
CALLED_KEY = "_kaju_called"  # 群里直接叫她："at" / "poke"（提到名字、自己插话都没有）
LATE_KEY = "_kaju_burst_late"  # 这一轮回的是哪一串（回复写好、发出去之前再看一眼后面有没有新的）
QUOTE_T_KEY = "_kaju_quote_t"  # 这条消息出现的时间（离得远了就引用）
QUOTE_START_KEY = "_kaju_quote_start"  # 这一轮开始发的时间
QUOTE_DONE_KEY = "_kaju_quote_done"
BURST_NOTE = (
    "\n\n【这条消息】对方刚才是连着发的 {n} 条（按顺序：{kinds}），上面一行一条：合在一起看，回一次就好，"
    "别一条一条分开回，也别把同一个意思说两遍。"
)
UNSEEN_NOTE = (
    "\n\n【这条消息】对方发{which}的时候，你上一条回复还没发到（你们是同时在打字），对方多半还没看到它："
    "你上一条已经说过的意思别再说一遍，接着回应这次新说的就好。"
)
VOICE_NOTE = "（这条是语音，上面的文字是自动转写的，同音字可能写错，比如\"佳树\"可能被写成\"家树\"\"家属\"。）"
VOICE_MARK = " （↑这条是语音，文字是自动转写的）"
# 内置群聊上下文正在记哪条消息（描述图片时把描述也挂到这条消息上）
_RECORDING = contextvars.ContextVar("kaju_recording_event", default=None)
OWN_CAPTIONS_KEY = "_kaju_own_captions"


def media_turn_note(event) -> str:
    """Turn-specific hint when this message itself carries (or quotes) a picture / video.

    Asking what's in it → she may describe; a bare sticker → treat it as something they said;
    picture + words → answer both, don't narrate the picture.
    """
    own, quoted = [], []
    for comp in event.get_messages() or []:
        if isinstance(comp, (Image, Video)):
            own.append(comp)
        elif isinstance(comp, Reply):
            quoted += [c for c in (getattr(comp, "chain", None) or []) if isinstance(c, (Image, Video))]
    media = own + quoted
    text = re.sub(r"\[(图片|动画表情|表情|视频)\]", "", event.get_message_str() or "").strip()
    if not media:
        # 图在之前的群聊/聊天记录里（"看他发的图""你看看上面那张图"）
        if LOOKS_AT.search(text) and not ASKS_CONTENT.search(text):
            return MEDIA_LOOK_NOTE.format(kind="视频" if "视频" in text else "图")
        return ""
    kind = "视频" if all(isinstance(c, Video) for c in media) else "图"
    if ASKS_CONTENT.search(text):
        return MEDIA_ASKED_NOTE.format(kind=kind)
    if LOOKS_AT.search(text):
        return MEDIA_LOOK_NOTE.format(kind=kind)
    if own and not text:
        return MEDIA_ONLY_NOTE.format(kind=kind)
    return MEDIA_WITH_TEXT_NOTE.format(kind=kind)


def raw_segments(event) -> list[dict]:
    """协议端发来的原始消息段（OneBot 的 message 数组）。AstrBot 会丢掉商城表情、把语音换成转写文字，要看原样就得看这里。"""
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    segs = raw.get("message") if hasattr(raw, "get") else None
    return [s for s in segs if isinstance(s, dict)] if isinstance(segs, list) else []


def had_voice(event) -> bool:
    return any(s.get("type") == "record" for s in raw_segments(event))


def chain_bili_links(chain, limit: int = 2) -> list[str]:
    """B 站链接：文字里的、QQ 分享卡片（Json）里的。"""
    out: list[str] = []
    for comp in chain or []:
        if isinstance(comp, Plain):
            found = bili.find_links(comp.text or "", limit)
        elif isinstance(comp, Json):
            found = bili.card_links(getattr(comp, "data", None), limit)
        else:
            continue
        out += [u for u in found if u not in out]
    return out[:limit]


def douyin_links(event, limit: int = 2) -> tuple[list[str], list[str]]:
    """(这条消息里的, 引用的消息里的) 抖音链接：文字里的、QQ 分享卡片里的。"""
    def of(chain) -> list[str]:
        out: list[str] = []
        for comp in chain or []:
            if isinstance(comp, Plain):
                found = douyin.find_links(comp.text or "", limit)
            elif isinstance(comp, Json):
                found = douyin.card_links(getattr(comp, "data", None), limit)
            else:
                continue
            out += [u for u in found if u not in out]
        return out[:limit]
    own = of(event.get_messages())
    quoted: list[str] = []
    for r in event.get_messages() or []:
        if isinstance(r, Reply):
            found = of(getattr(r, "chain", None)) or douyin.find_links(getattr(r, "message_str", "") or "", limit)
            quoted += [u for u in found if u not in own and u not in quoted]
    return own, quoted[: max(0, limit - len(own))]


def bili_links(event, limit: int = 2) -> tuple[list[str], list[str]]:
    """(这条消息里的, 引用的消息里的) B 站链接。"""
    own = chain_bili_links(event.get_messages(), limit)
    quoted: list[str] = []
    for r in event.get_messages() or []:
        if isinstance(r, Reply):
            found = chain_bili_links(getattr(r, "chain", None), limit) or bili.find_links(
                getattr(r, "message_str", "") or "", limit)
            quoted += [u for u in found if u not in own and u not in quoted]
    return own, quoted[: max(0, limit - len(own))]


@register(PLUGIN_NAME, "dsh", "佳树基础：账号白名单、昵称/戳一戳唤醒、等图片描述、视频场景分镜与本地视觉、动图/文件/语音/B站链接、B站小号扫码登录、有许可时自己刷B站、稳定前缀、私聊连发合并、离得远了就引用、本地语音转文字", "1.19.0")
class KajuBasics(Browsing, BiliAccount, DouyinAccount, Owner, Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.body = AstrBody(context, plugin_log(logger))  # 自己刷视频（kaju_platforms 的 Browsing）挑视频用的模型
        self.log = self.body.log
        self.config = config or {}
        self._bursts = burst.Bursts()
        self._seen = quote.Seen()
        self._pokes = poke.Lines()  # 群里每个人最近说的话：被戳时交给她（poke.py）
        self._inflight: dict[str, int] = defaultdict(int)
        self._inflight_video: dict[str, int] = defaultdict(int)
        self._describer = Describer(context, lambda: self._sec("media"))
        data_dir = paths.self_dir(PLUGIN_NAME)
        self._bili_account_init()  # 她自己的 B 站小号（kaju_platforms/bili/account.py）
        self._douyin_account_init()  # 她自己的抖音小号 + 常驻浏览器（kaju_platforms/douyin/account.py）
        self._browse_log = browse.Log(os.path.join(data_dir, "browse.json"))  # 自己刷 B 站的记录
        self._describer.login_cookie = lambda: self._login.header() if self._login.logged_in else ""
        self._describer.douyin_profile = lambda: self._dy_profile if self._dy_logged() else ""
        self._describer.learner = self._learner
        self._describer.senses.about_her = self._about_her
        self._browsing = None  # 正在刷 B 站的任务
        self._browse_topic = ""  # 这次刷是兄长点名让看的什么（没点名为空）
        self._browse_site = "bili"  # 这次刷的是哪儿（bili / douyin）
        self._browse_next = None  # 正在刷时兄长又点名想让她看的：手上这个看完就换过去 {topic, minutes, by, umo, where}
        self._chat_seen = 0.0  # 上次有人找她说话（她要回复）的时间：刷 B 站时两个视频之间先让一让
        self._gcc = None
        self._orig_handle = None
        self._orig_caption = None
        self._since: dict[str, dict[str, float]] = {}
        self._warned_prefix = False
        self._hook_group_context()
        if deadline.install(self._llm_deadline, logger.warning, get_hedge=self._llm_hedge):
            logger.info(f"kaju_basics: 模型请求时限 {self._llm_deadline():.0f}s，"
                        f"{self._llm_hedge():.0f}s 没回就再发一份" if self._llm_hedge() else
                        f"kaju_basics: 模型请求时限 {self._llm_deadline():.0f}s")
        # 挑主模型（2026-11-14，router.py）：按最近成绩每条消息现排顺序、挂了的冷却、定时探测
        self._router = router.Router(context, lambda: self._sec("model_router"), logger.info)
        # 只带图的消息：图会先被 Gemini 看成文字（_turn_images），Claude 可以排在最后兜底（2026-11-19）
        self._router.images_become_text = lambda: bool(
            self._sec("media").get("gemini_eyes", True) and omni.gemini_keys())
        if self._router.install():
            logger.info("kaju_basics: 主模型按最近成绩挑（挂了的先冷却、私聊/问句用高思考档）")
            self._router.start()
        if gifpatch.install(self._anim_opts, logger.warning):
            logger.info("kaju_basics: 动图按时间拆帧（换掉了自带的 3×3）")
        if gemsig.install(logger.warning):
            logger.info("kaju_basics: Gemini 历史整理：空文字补空格、没签名的工具调用补签名（daitu 改写成文字）")
        wrapped = linkfetch.install(self._link_fetch, logger.warning)
        if wrapped:
            logger.info(f"kaju_basics: 抓网页工具碰到抖音 / B站视频链接改成真的去看（{', '.join(wrapped)}）")
        self._bili_check = None
        self._cleanup_task = None
        self._stt_task = None
        self._ollama_task = None
        self._stt = None  # 本地 SenseVoice 语音转文字（sttprov.py）
        self._prewarmed = 0.0  # 上次预热 bge-m3 的时间
        self._recent_bili: dict[str, tuple[float, str]] = {}  # 聊天 → (什么时候, 最近看的 B 站链接)
        self._arrived: dict[str, dict[str, float]] = defaultdict(dict)  # 群 → 群聊记录 id → 消息到达时间
        self._unseen_video: dict[str, list] = defaultdict(list)  # 群 → [(时间, 发的人, 视频, 事件)] 还没看的视频
        try:
            loop = asyncio.get_running_loop()
            if self._bili_on() and (self._login.logged_in or str(self._sec("media").get("bili_cookie") or "").strip()):
                # 填了 B 站 Cookie：启动（改配置会重载）时查一下登录着没有，结果写进日志
                self._bili_check = loop.create_task(self._log_bili_login())
            self._cleanup_task = loop.create_task(self._cleanup_loop())
            if self._bili_on():
                self._login_task = loop.create_task(self._login_loop())
            if self._sec("stt").get("enable", True):
                self._stt_task = loop.create_task(self._stt_loop())
            if self._sec("ollama").get("enable", True):
                self._ollama_task = loop.create_task(self._ollama_loop())
            if self._dy_keep_on():
                self._dy_keep_task = loop.create_task(self._dy_keep_loop())
        except RuntimeError:  # 没有事件循环（离线测试直接构造）
            pass

    async def _ollama_loop(self) -> None:
        """本地模型服务（记忆向量 bge-m3、看图 qwen3-vl）没开就拉起来（ollama.py）。"""
        sec = self._sec("ollama")
        host, port = str(sec.get("host") or "127.0.0.1"), int(sec.get("port", 11435))
        script = str(sec.get("script") or r"D:\JiashuBot\local_vision\runtime.ps1")
        every = max(10.0, float(sec.get("check_seconds", 60)))
        retry_after = 0.0
        while True:
            if not await ollama.is_up(host, port) and time.time() >= retry_after:
                logger.info(f"kaju_basics: 本地模型服务 {host}:{port} 没开，正在启动…")
                ok, said = await ollama.start(script)
                if ok:
                    logger.info(f"kaju_basics: 本地模型服务已启动 {said}")
                else:
                    retry_after = time.time() + 300
                    logger.warning(f"kaju_basics: 本地模型服务没启动成功（5 分钟后再试）：{said}")
            await asyncio.sleep(every)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-1)
    async def prewarm_local(self, event: AstrMessageEvent):
        """私聊来消息（连"正在输入"也算）或群里有人叫她：先让 Ollama 把记忆用的向量模型加载上（ollama.py）。"""
        sec = self._sec("ollama")
        model = str(sec.get("prewarm_embed", "bge-m3") or "")
        if not model or not sec.get("enable", True) or (event.get_group_id() and not event.is_at_or_wake_command):
            return
        if time.time() - self._prewarmed < 60:
            return
        self._prewarmed = time.time()
        host, port = str(sec.get("host") or "127.0.0.1"), int(sec.get("port", 11435))
        asyncio.create_task(ollama.prewarm(f"http://{host}:{port}/api/embed", {"model": model, "input": []}))

    async def _stt_loop(self) -> None:
        """本地语音转文字：先装上（模型用到时才加载）；之后每 10 秒看一眼：
        AstrBot 一改提供商就会把不在它配置里的提供商（包括这个）清掉，清掉了就挂回去；闲置太久就先把模型放掉。"""
        try:
            self._stt = await sttprov.install(self.context, self._sec("stt"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 本地语音转文字没装上 {type(e).__name__}: {e}")
            return
        while self._stt is not None:
            await asyncio.sleep(10)
            idle = float(self._sec("stt").get("idle_minutes", 10) or 0)
            if idle > 0 and self._stt.sv.release_if_idle(idle * 60):
                logger.info(f"kaju_basics: 本地语音转文字闲置 {idle:.0f} 分钟，先放掉模型（约 300 MB 内存），下次用到再加载")
            pm = self.context.provider_manager
            if pm.inst_map.get(sttprov.PROVIDER_ID) is not self._stt:
                pm.inst_map[sttprov.PROVIDER_ID] = self._stt
                if self._stt not in pm.stt_provider_insts:
                    pm.stt_provider_insts.append(self._stt)
                logger.info("kaju_basics: 本地语音转文字被 AstrBot 重载挤掉了，重新挂上")

    async def _log_bili_login(self) -> None:
        try:
            logger.info(f"kaju_basics: {await self._describer.bili_login_status()}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: B站登录检查出错 {type(e).__name__}: {e}")

    def _llm_deadline(self) -> float:
        sec = self._sec("llm_deadline")
        if not sec.get("enable", True):
            return 0.0
        try:
            return float(sec.get("timeout", 60))
        except (TypeError, ValueError):
            return 60.0

    def _llm_hedge(self) -> float:
        sec = self._sec("llm_deadline")
        if not sec.get("enable", True):
            return 0.0
        try:
            return max(0.0, float(sec.get("hedge_after", 15)))
        except (TypeError, ValueError):
            return 15.0

    def _anim_opts(self) -> dict:
        sec = self._sec("media")
        return {"enable": bool(sec.get("gif_frames", True)), "max_frames": sec.get("gif_max_frames", 8)}

    def _sec(self, name: str) -> dict:
        sec = self.config.get(name)
        return sec if isinstance(sec, dict) else {}

    def _bili_on(self) -> bool:
        sec = self._sec("media")
        return bool(sec.get("enable", True) and sec.get("bili", True))

    def _list(self, section: str, key: str) -> list[str]:
        raw = self._sec(section).get(key) or []
        if isinstance(raw, str):
            raw = raw.replace("，", ",").split(",")
        return [str(x).strip() for x in raw if str(x).strip()]

    # ------------------------------------------------------------ 账号白名单
    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def guard(self, event: AstrMessageEvent):
        if event.get_platform_name() != "aiocqhttp":  # 只管 QQ；WebUI 自带的聊天不拦
            return
        allowed = self._list("guard", "allowed_self_ids")
        self_id = str(event.get_self_id() or "")
        if allowed and self_id and self_id not in allowed:
            logger.warning(f"kaju_basics: 拦截非授权账号事件 self_id={self_id} session={event.unified_msg_origin}")
            event.is_at_or_wake_command = False  # 只 stop_event 的话，唤醒消息 AstrBot 仍会去请求模型
            event.stop_event()

    # ------------------------------------------------------------ 唤醒
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize - 1)
    async def note_called(self, event: AstrMessageEvent):
        """群里这条是不是 @ 了她（戳一戳在 wake_on_poke 里记）：别处看 CALLED_KEY 分清“直接叫她”和
        “提到名字 / 自己插话”（2026-11-15：核对一直不过时，只有直接叫她才说一句在忙）。"""
        self_id = str(event.get_self_id() or "")
        if not self_id:
            return
        for comp in event.get_messages() or []:
            if type(comp).__name__ == "At" and str(getattr(comp, "qq", "") or "") == self_id:
                event.set_extra(CALLED_KEY, "at")
                return

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def wake_on_poke(self, event: AstrMessageEvent):
        if event.is_at_or_wake_command or not self._sec("wake").get("poke", True):
            return
        self_id = str(event.get_self_id() or "")
        if not self_id:
            return
        for comp in event.get_messages():
            if isinstance(comp, Poke) and str(getattr(comp, "id", "") or getattr(comp, "qq", "") or "") == self_id:
                break
        else:
            return
        sender = str(event.get_sender_id() or "")
        recent = []
        if event.get_group_id():
            umo = event.unified_msg_origin
            name = self._pokes.name_of(umo, sender)
            sender_obj = getattr(getattr(event, "message_obj", None), "sender", None)
            if name and sender_obj is not None and (not getattr(sender_obj, "nickname", "")
                                                     or str(sender_obj.nickname).isdigit()):
                sender_obj.nickname = name  # 戳一戳事件不带昵称：用 TA 在群里最近的名字，别让她叫 QQ 号
            recent = self._pokes.recent(umo, sender, window=float(self._sec("wake").get("poke_context_seconds", 180)))
        event.message_str = poke.poke_text(recent)
        event.is_at_or_wake_command = True
        event.is_wake = True
        event.set_extra(CALLED_KEY, "poke")
        logger.info(f"kaju_basics: 被 {event.get_sender_name() or sender} 戳了 [{event.get_group_id() or 'private'}]"
                    + (f"，戳之前TA刚说了 {len(recent)} 句" if recent else ""))

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize - 4)
    async def note_group_line(self, event: AstrMessageEvent):
        """记下群里每个人最近说的话（被戳时用：poke.py）。"""
        sender = str(event.get_sender_id() or "")
        if not sender or sender == str(event.get_self_id() or "-"):
            return
        if any(isinstance(c, Poke) for c in event.get_messages()):
            return
        text = "".join(c.text for c in event.get_messages() if isinstance(c, Plain)).strip()
        self._pokes.note(event.unified_msg_origin, sender, event.get_sender_name() or "", text)

    @filter.after_message_sent()
    async def note_group_reply(self, event: AstrMessageEvent):
        if event.get_group_id():
            self._pokes.replied(event.unified_msg_origin)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def wake_on_nickname(self, event: AstrMessageEvent):
        if event.is_at_or_wake_command:
            return
        names = self._list("wake", "nicknames")
        text = (event.get_message_str() or "").strip()
        if not names or not text or not any(k in text for k in names):
            return
        event.is_at_or_wake_command = True
        event.is_wake = True
        logger.info(f"kaju_basics: 昵称唤醒 [{event.get_group_id() or 'private'}] {text[:40]}")

    # ------------------------------------------------------------ 私聊连发合并（burst.py）
    def _burst_on(self, event) -> bool:
        cfg = self._sec("burst")
        if not cfg.get("enable", True) or event.get_group_id():
            return False
        if event.get_extra("qzone_comment") or event.get_extra("kaju_dm"):  # QQ 空间评论 / B站私信（kaju_dm 自己并好了）：不等也不并
            return False
        platforms = self._list("burst", "platforms") if "platforms" in cfg else ["aiocqhttp"]
        return event.get_platform_name() in platforms

    def _burst_num(self, key: str, default: float) -> float:
        try:
            return max(0.0, float(self._sec("burst").get(key, default)))
        except (TypeError, ValueError):
            return default

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=sys.maxsize - 1)
    async def note_private(self, event: AstrMessageEvent):
        """记下每条私聊什么时候到的，和 QQ 推来的"对方正在输入"（空消息，AstrBot 自己会丢掉）。"""
        if not self._burst_on(event):
            return
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if burst.is_input_status(raw):
            self._bursts.typing(event.unified_msg_origin, kind=raw.get("event_type"))
            return
        now = time.time()
        event.set_extra(ARRIVED_KEY, now)
        try:
            text = (event.get_message_str() or "").strip()
            if (text or event.get_messages()) and not text.startswith("/"):
                self._bursts.arrived(event.unified_msg_origin, event, str(event.get_sender_id()), now)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 记新消息出错 {type(e).__name__}: {e}")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=-1000)
    async def hold_private(self, event: AstrMessageEvent):
        """最后执行（别的插件先把每条都记下）：等对方说完，连着发的几条并成一条回。"""
        if not self._burst_on(event):
            return
        if event.is_stopped() or not event.is_at_or_wake_command:
            self._bursts.forget(event.unified_msg_origin, event)
            return
        try:
            await self._hold(event)
        except Exception as e:  # noqa: BLE001  这里出错 AstrBot 会把报错发给对方：宁可照常回
            logger.warning(f"kaju_basics: 连发合并出错，照常回 {type(e).__name__}: {e}")

    async def _hold(self, event: AstrMessageEvent) -> None:
        text = (event.get_message_str() or "").strip()
        chain = event.get_messages() or []
        umo = event.unified_msg_origin
        if (not text and not chain) or text.startswith("/"):  # 空的、指令不管
            self._bursts.forget(umo, event)
            return
        part = burst.Part(t=float(event.get_extra(ARRIVED_KEY) or time.time()), text=text, comps=list(chain))
        p = self._bursts.add(umo, event, part, str(event.get_sender_id()))
        event.set_extra(BURST_KEY, p)
        quiet = self._burst_num("quiet_seconds", 2.0)
        grace = self._burst_num("typing_grace", 4)
        max_hold = self._burst_num("max_hold", 12)
        said_typing = 0.0
        while p.state != burst.YIELDED:
            now = time.time()
            until = self._bursts.hold_until(umo, p, quiet, grace, max_hold)
            if now >= until:
                break
            tt = self._bursts.typed_after(umo, p.last_t)
            if tt and tt != said_typing:
                said_typing = tt
                logger.info(f"kaju_basics: {umo} 对方正在输入"
                            f"（type={self._bursts.typing_kind.get(umo)}），再等等")
            await asyncio.sleep(min(0.2, until - now))
        if p.state == burst.YIELDED:
            event.is_at_or_wake_command = False  # 只 stop_event 的话 AstrBot 仍会去请求模型
            event.stop_event()
            return
        p.state = burst.WAITING
        if len(p.parts) > 1:
            logger.info(f"kaju_basics: {umo} 连着发的 {len(p.parts)} 条并成一轮回：{burst.describe(p.parts)}"
                        f"（等了 {time.time() - p.first_t:.1f}s）")

    @filter.on_llm_request(priority=sys.maxsize - 1)
    async def burst_catch_up(self, event: AstrMessageEvent, req: ProviderRequest):
        """真要请求模型了（前一轮刚回完）：后面又来了还没回的消息，这条就交给最新那条一起回。"""
        p = event.get_extra(BURST_KEY)
        if not isinstance(p, burst.Pending):
            return
        event.set_extra(BURST_KEY, None)
        try:
            await self._catch_up(event, req, p)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 连发合并出错，照常回 {type(e).__name__}: {e}")

    async def _catch_up(self, event: AstrMessageEvent, req: ProviderRequest, p: "burst.Pending") -> None:
        umo = event.unified_msg_origin
        max_total = self._burst_num("max_total", 30)
        # 后一条已经到了、还在别的插件那里记着没排进来：等它一下（最多 catch_up_wait 秒）
        wait = min(self._burst_num("catch_up_wait", 3), max(0.0, p.first_t + max_total - time.time()))
        t0 = time.time()
        if self._bursts.newer(umo, p) is None and self._bursts.on_the_way(umo, p):
            while time.time() - t0 < wait and self._bursts.newer(umo, p) is None and self._bursts.on_the_way(umo, p):
                await asyncio.sleep(0.05)
            logger.info(f"kaju_basics: {umo} 正要回，后面一条刚到还没排进来，等了 {time.time() - t0:.2f}s")
        n = self._bursts.newer(umo, p)
        if n is not None and time.time() - p.first_t < max_total:
            self._bursts.hand_over(umo, p, n)
            event.is_at_or_wake_command = False
            event.stop_event()
            logger.info(f"kaju_basics: {umo} 正要回，后面又来了 {burst.describe(n.parts[len(p.parts):])}，"
                        f"这条并过去一起回")
            return
        self._bursts.done(umo, p)
        event.set_extra(LATE_KEY, p)
        if not self._sec("burst").get("notes", True):
            return
        notes = ""
        if len(p.parts) > 1:
            notes += BURST_NOTE.format(n=len(p.parts), kinds=burst.describe(p.parts))
        if self._bursts.unseen_reply(umo, p.first_t):
            notes += UNSEEN_NOTE.format(which="这几条" if len(p.parts) > 1 else "这条")
            logger.info(f"kaju_basics: {umo} 对方是在她上一条回复发出去之前打的字，提醒别重复")
        if notes:
            req.system_prompt = (req.system_prompt or "") + notes

    # 回复写好了、还没发：这期间对方又发了（2026-11-13 兄长：连发两句，第一句等模型 99 秒，第二句在那期间到了，
    # 她先回第一句、再单独回第二句）→ 这一句不发，内容并到新来的那条前面，由那一轮一起回。
    # 看两次：主模型的草稿一回来（重说之前，省掉写手和核对的时间）、写手写完核对过了（发之前）。
    @filter.on_llm_response(priority=200000)
    async def burst_late_on_draft(self, event: AstrMessageEvent, resp: LLMResponse):
        await self._late_merge(event, resp, "草稿刚回来")

    @filter.on_llm_response(priority=4)  # kaju_style 的重说是 5：写完、核对完之后
    async def burst_late_before_send(self, event: AstrMessageEvent, resp: LLMResponse):
        await self._late_merge(event, resp, "回复写好了")

    async def _late_merge(self, event: AstrMessageEvent, resp: LLMResponse, when: str) -> None:
        p = event.get_extra(LATE_KEY)
        if not isinstance(p, burst.Pending) or not self._burst_on(event) or event.is_stopped():
            return
        cfg = self._sec("burst")
        if not cfg.get("late_merge", True):
            return
        try:
            umo = event.unified_msg_origin
            # 一串消息从第一条起太久了就先回（对方一直隔一会儿发一句、模型又慢，不能一直不回）
            if time.time() - p.first_t > self._burst_num("late_max_total", 180):
                return
            n = self._bursts.newer(umo, p)
            if n is None and self._bursts.on_the_way(umo, p):  # 刚到、还没排进来：等它一下
                t0 = time.time()
                while time.time() - t0 < self._burst_num("catch_up_wait", 3) and self._bursts.newer(umo, p) is None:
                    await asyncio.sleep(0.05)
                n = self._bursts.newer(umo, p)
            if n is None:
                return
            event.set_extra(LATE_KEY, None)
            self._bursts.hand_over(umo, p, n)
            resp.completion_text = ""
            event.clear_result()
            event.stop_event()  # 停了就不存历史、不发（并过去的那一轮会连这句一起存）
            logger.info(f"kaju_basics: {umo} {when}，后面又来了 {burst.describe(n.parts[len(p.parts):])}，"
                        f"这句不发，并过去一起回：{burst.merged_text(n.parts)[:60]!r}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 回复前合并出错，照常发 {type(e).__name__}: {e}")

    @filter.on_decorating_result(priority=100001)
    async def burst_reply_start(self, event: AstrMessageEvent):
        if self._burst_on(event) and getattr(event.get_result(), "chain", None):
            self._bursts.reply_started(event.unified_msg_origin)

    @filter.after_message_sent()
    async def burst_reply_sent(self, event: AstrMessageEvent):
        if self._burst_on(event):
            self._bursts.reply_sent(event.unified_msg_origin)

    # ------------------------------------------------------------ 离得远了就引用（quote.py）
    def _quote_on(self, event: AstrMessageEvent) -> bool:
        cfg = self._sec("quote")
        if not cfg.get("enable", True):
            return False
        platforms = self._list("quote", "platforms") if "platforms" in cfg else ["aiocqhttp"]
        return event.get_platform_name() in platforms

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize - 2)
    async def quote_note(self, event: AstrMessageEvent):
        """聊天里每出现一条别人的消息就记一下（输入提示、她自己的、空的不算）。"""
        if not self._quote_on(event):
            return
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if burst.is_input_status(raw):
            return
        if str(event.get_sender_id() or "") == str(event.get_self_id() or "-"):
            return
        if not ((event.get_message_str() or "").strip() or event.get_messages()):
            return
        event.set_extra(QUOTE_T_KEY, self._seen.message(event.unified_msg_origin))

    @filter.on_decorating_result(priority=100002)
    async def quote_far(self, event: AstrMessageEvent):
        """这一轮要发的回复离他那条已经隔了别的消息：开头带上 QQ 引用（分段发时只挂在第一条上）。"""
        result = event.get_result()
        if not result or not getattr(result, "chain", None) or not self._quote_on(event):
            return
        if event.get_extra(QUOTE_START_KEY) is None:
            event.set_extra(QUOTE_START_KEY, self._seen.clock())
        since = event.get_extra(QUOTE_T_KEY)
        if since is None or event.get_extra(QUOTE_DONE_KEY) or not result.is_llm_result():
            return
        event.set_extra(QUOTE_DONE_KEY, True)  # 一轮只看第一次发的
        group = bool(event.get_group_id())
        chime = event.get_extra("_chime_in")
        if group and (chime is True or not (event.is_at_or_wake_command or chime == "follow")):
            return  # 群里没人叫她、是她自己插话：不引用（有人接着跟她说话 follow 算）
        if event.get_extra("qzone_comment") or any(isinstance(c, Reply) for c in result.chain):
            return
        msg_id = getattr(getattr(event, "message_obj", None), "message_id", None)
        if not msg_id:
            return
        cfg = self._sec("quote")
        gap = self._seen.gap(event.unified_msg_origin, float(since))
        try:
            pg, gg = int(cfg.get("private_gap", 1)), int(cfg.get("group_gap", 2))
        except (TypeError, ValueError):
            pg, gg = 1, 2
        if not quote.should_quote(gap, group, pg, gg):
            return
        result.chain.insert(0, Reply(id=msg_id))
        logger.info(f"kaju_basics: {event.unified_msg_origin} 离他那条隔了 {gap} 条，引用着回："
                    f"{(event.get_message_str() or '')[:30]}")

    @filter.after_message_sent()
    async def quote_sent(self, event: AstrMessageEvent):
        """记下她这次发了几个气泡、什么时候发的。"""
        if not self._quote_on(event):
            return
        result = event.get_result()
        seg = (self.context.get_config().get("platform_settings", {}).get("segmented_reply", {}) or {}).get("enable", False)
        n = quote.bubbles_of(getattr(result, "chain", None), bool(seg))
        if n:
            start = event.get_extra(QUOTE_START_KEY) or self._seen.clock()
            self._seen.reply(event.unified_msg_origin, float(start), bubbles=n)
        event.set_extra(QUOTE_START_KEY, None)

    # ------------------------------------------------------------ 看图：记录哪些图还没描述完
    def _hook_group_context(self) -> None:
        for meta in self.context.get_all_stars():
            gcc = getattr(getattr(meta, "star_cls", None), "group_chat_context", None)
            if gcc is not None and hasattr(gcc, "handle_message"):
                break
        else:
            return

        orig = gcc.handle_message
        inflight, inflight_video = self._inflight, self._inflight_video

        async def handle_message(event, *args, **kwargs):
            chain = event.get_messages()
            has_image = any(isinstance(c, Image) for c in chain)
            has_video = any(isinstance(c, Video) for c in chain) or bool(self._bili_on() and chain_bili_links(chain, 1))
            umo = event.unified_msg_origin
            inflight[umo] += has_image
            inflight_video[umo] += has_video
            added: list = []
            token = _RECORDING.set(event)
            try:
                # 视频描述、文件名、"这是语音" 只在这条记录期间临时加进消息链，别的插件看不到
                added = await self._history_extras(event)
                chain.extend(added)
                ret = await orig(event, *args, **kwargs)
                await self._put_in_order(gcc, event)
                return ret
            finally:
                _RECORDING.reset(token)
                inflight[umo] -= has_image
                inflight_video[umo] -= has_video
                for comp in added:
                    for i, c in enumerate(chain):
                        if c is comp:
                            del chain[i]
                            break

        gcc.handle_message = handle_message
        self._gcc, self._orig_handle = gcc, orig

        if hasattr(gcc, "get_image_caption"):
            orig_caption = gcc.get_image_caption
            describer = self._describer

            async def get_image_caption(image_url, provider_id, prompt, *args, **kwargs):
                if args or kwargs:  # 内置函数以后改了参数就别管它
                    return await orig_caption(image_url, provider_id, prompt, *args, **kwargs)
                try:
                    caption = await describer.image_caption(orig_caption, image_url, provider_id, prompt)
                except Exception as e:  # noqa: BLE001
                    # 内置的描述失败就把这张图整个丢掉，她连"有人发了图"都不知道
                    logger.warning(f"kaju_basics: 群里的图没描述成 {type(e).__name__}: {e}")
                    caption = "一张图，佳树没看清"
                ev = _RECORDING.get()
                if ev is not None:  # 这条消息自己的图：她回这条时群聊记录里没有它，要单独给（_own_images）
                    ev.set_extra(OWN_CAPTIONS_KEY, (ev.get_extra(OWN_CAPTIONS_KEY) or []) + [caption])
                    try:  # 也记进她的聊天记录（回复器看的那几十行里图片有内容，11-18 晚）
                        from kaju_core.life import diary as _diary
                        _diary.note_caption(ev, caption)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"kaju_basics: 图片描述没记进聊天记录 {type(e).__name__}: {e}")
                return caption

            gcc.get_image_caption = get_image_caption
            self._orig_caption = orig_caption
        logger.info("kaju_basics: 已挂上内置群聊上下文（等图片描述、记视频/动图/语音）")

    async def terminate(self):
        for task in (getattr(self, "_cleanup_task", None), getattr(self, "_stt_task", None),
                     getattr(self, "_ollama_task", None), getattr(self, "_login_task", None),
                     getattr(self, "_qr_task", None), getattr(self, "_browsing", None),
                     getattr(self, "_dy_qr_task", None), getattr(self, "_dy_keep_task", None)):
            if task is not None:
                task.cancel()
        douyin.KEEPER = None  # 常驻的 Chrome 不关：重载后新的实例照样接回去
        if getattr(self, "_describer", None) is not None:
            self._describer.close()
        if getattr(self, "_stt", None) is not None:
            try:
                sttprov.uninstall(self.context)
            except Exception:  # noqa: BLE001
                pass
            self._stt = None
        if self._gcc is not None and self._orig_handle is not None:
            self._gcc.handle_message = self._orig_handle
        if self._gcc is not None and self._orig_caption is not None:
            self._gcc.get_image_caption = self._orig_caption
        deadline.uninstall()
        if getattr(self, "_router", None) is not None:
            self._router.uninstall()
        gifpatch.uninstall()
        gemsig.uninstall()
        linkfetch.uninstall()

    async def _put_in_order(self, gcc, event) -> None:
        """内置的是描述完才记：慢的图（十几秒）会排到后发的话后面。按消息到达时间挪回原位。"""
        rid = event.get_extra("_group_context_record_id", None)
        lock_of = getattr(gcc, "_get_lock", None)
        if not isinstance(rid, str) or lock_of is None or not self._sec("image").get("keep_order", True):
            return
        umo = event.unified_msg_origin
        arrived = self._arrived[umo]
        arrived[rid] = float(getattr(event, "created_at", 0) or time.time())
        try:
            async with lock_of(umo):
                ids_q, recs_q = gcc._record_ids.get(umo), gcc.raw_records.get(umo)
                if ids_q is None or recs_q is None:
                    return
                ids, recs = list(ids_q), list(recs_q)
                keep = set(ids)
                for k in [k for k in arrived if k not in keep]:
                    del arrived[k]
                moved = history.move_into_place(ids, recs, arrived, rid)
                if moved:
                    ids_q.clear()
                    ids_q.extend(ids)
                    recs_q.clear()
                    recs_q.extend(recs)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 群聊记录排序失败 {type(e).__name__}: {e}")
            return
        if moved:
            logger.info(f"kaju_basics: 群聊记录里这条（{event.get_sender_name()}）描述得慢，往前挪 {moved} 条回到原来的位置")

    async def _history_extras(self, event) -> list:
        """群聊记录里这条消息要补上的内容：视频描述、文件名、语音标记。"""
        if not self._sec("media").get("enable", True):
            return []
        extras = []
        for comp in list(event.get_messages()):
            if isinstance(comp, Video) and self._sec("media").get("video", True):
                if self._sec("media").get("group_video_preview", False):
                    extras.append(Plain(f" [Video: {await self._describer.video(comp, event)}]"))
                else:
                    # 视频不提前看：记下来，有人提到视频时再看（describe_media）
                    seen = self._unseen_video[event.unified_msg_origin]
                    seen.append((time.time(), event.get_sender_name() or "", comp, event))
                    del seen[:-3]
                    extras.append(Plain(history.UNSEEN_VIDEO_TEXT))
            elif isinstance(comp, File):
                name = getattr(comp, "name", "") or "文件"
                n = int(self._sec("media").get("doc_group_excerpt", 120))
                head = await self._describer.doc_excerpt(comp, n) if self._sec("media").get("doc", True) and n > 0 else ""
                extras.append(Plain(f" [File: {name}" + (f"，开头：{head}" if head else "") + "]"))
            elif isinstance(comp, Record):
                extras.append(Plain(" [Voice: 一条语音，没转成文字]"))
        if self._bili_on():
            for url in chain_bili_links(event.get_messages()):
                line = await self._describer.bili_brief(url)
                if line:
                    extras.append(Plain(f" [Bilibili video: {line}]"))
        if had_voice(event) and not any(isinstance(c, Record) for c in event.get_messages()):
            extras.append(Plain(VOICE_MARK))
        return extras

    # ------------------------------------------------------------ 视频/文件/表情：先整理消息链
    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def normalize_media(self, event: AstrMessageEvent):
        """要早于内置群聊上下文：文件形式的图片/视频换成图片/视频，商城表情补成图片（AstrBot 会丢掉它）。"""
        sec = self._sec("media")
        if event.is_stopped() or not sec.get("enable", True):
            return
        chain = event.get_messages()
        sizes = {}
        for s in raw_segments(event):
            d = s.get("data") or {}
            if s.get("type") == "file":
                name = d.get("name") or d.get("file_name") or d.get("file") or ""
                try:
                    sizes[name] = int(d.get("file_size") or d.get("size") or 0)
                except (TypeError, ValueError):
                    pass
            elif s.get("type") == "mface" and sec.get("mface", True):
                url = str(d.get("url") or "")
                if url.startswith("http"):
                    chain.append(Image.fromURL(url))
        if sec.get("file_as_media", True):
            await self._files_to_media(chain, sizes)
            for comp in list(chain):
                if isinstance(comp, Reply) and getattr(comp, "chain", None):
                    await self._files_to_media(comp.chain, sizes)
        if sec.get("face", True):
            # QQ 小黄脸表情：AstrBot 和内置群聊记录都不认，换成文字 [表情：捂脸]
            faces = []
            for i, comp in enumerate(chain):
                if isinstance(comp, Face):
                    chain[i] = Plain(history.face_text(getattr(comp, "id", None)))
                    faces.append(chain[i].text)
            if faces:
                extra = "".join(faces)
                event.message_str = (event.message_str or "") + extra
                obj = getattr(event, "message_obj", None)
                if obj is not None and hasattr(obj, "message_str"):
                    obj.message_str = (obj.message_str or "") + extra

    async def _files_to_media(self, chain: list, sizes: dict) -> None:
        sec = self._sec("media")
        limits = {"image": float(sec.get("file_image_max_mb", 20)), "video": float(sec.get("video_max_mb", 200))}
        for i, comp in enumerate(chain):
            if not isinstance(comp, File):
                continue
            name = getattr(comp, "name", "") or ""
            kind = media.file_kind(name)
            if kind is None or sizes.get(name, 0) > limits[kind] * 1024 * 1024:
                continue
            try:
                path = await comp.get_file()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"kaju_basics: 文件 {name} 下载失败：{e}")
                continue
            if not path or not os.path.exists(path) or os.path.getsize(path) > limits[kind] * 1024 * 1024:
                continue
            chain[i] = Image.fromFileSystem(path) if kind == "image" else Video.fromFileSystem(path)
            logger.info(f"kaju_basics: 文件 {name} 当作{'图片' if kind == 'image' else '视频'}看")

    # 只有视频/文件/语音的群消息，内置群聊上下文不记（它只认文字/图片/卡片）：这里补记一条
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize - 3)
    async def record_media_only(self, event: AstrMessageEvent):
        if self._gcc is None or not self._sec("media").get("enable", True):
            return
        chain = event.get_messages()
        if any(isinstance(c, (Plain, Image, Json)) for c in chain):
            return  # 内置的已经记过了
        if not any(isinstance(c, (Video, File, Record)) for c in chain):
            return
        try:
            ltm = self.context.get_config(umo=event.unified_msg_origin)["provider_ltm_settings"]
            if not ltm.get("group_icl_enable") or event.get_extra("handlers_parsed_params", {}):
                return
            await self._gcc.handle_message(event)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 补记群消息失败 {type(e).__name__}: {e}")

    # 加载时内置插件可能还没实例化：在第一条群消息时挂上（要早于内置群聊上下文记录这条消息）
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=sys.maxsize)
    async def ensure_hooked(self, event: AstrMessageEvent):
        if self._gcc is None:
            self._hook_group_context()

    # ------------------------------------------------------------ 请求钩子（按执行顺序）
    @filter.on_llm_request(priority=sys.maxsize)
    async def capture_base(self, event: AstrMessageEvent, req: ProviderRequest):
        """最先执行：记下插件追加内容之前的系统提示。
        显卡在训练写手时（kaju_core.gpu_busy，2026-11-13 兄长定）群聊这一轮直接停：记忆检索、主模型、写手都不跑。"""
        if event.get_group_id():
            what = group_quiet()  # 显卡在训练 / 兄长在控制台暂停了群聊（11-17）
            if what:
                logger.info(f"kaju_basics: 群聊先不回（{what}） {event.unified_msg_origin}")
                event.stop_event()
                return
        event.set_extra(BASE_KEY, req.system_prompt or "")

    @filter.on_llm_request(priority=sys.maxsize - 10)
    async def drop_stale_history(self, event: AstrMessageEvent, req: ProviderRequest):
        """群聊里太久以前的对话不再带给主模型（stale.py；2026-11-13 她接着三天前和 555 争“食指”的话回）。"""
        cfg = self._sec("group_history")
        if not event.get_group_id() or not cfg.get("enable", True):
            return
        try:
            hours = float(cfg.get("max_hours", 6))
            now = dt.datetime.now(self._tz()).replace(tzinfo=None)
            kept, dropped = stale.trim(list(req.contexts or []), now, hours)
            if dropped:
                req.contexts = kept
                logger.info(f"kaju_basics: 群聊历史里 {hours:g} 小时前的 {dropped} 条不再带上（留 {len(kept)} 条）"
                            f" {event.unified_msg_origin}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 去掉旧群聊历史出错，照原样 {type(e).__name__}: {e}")

    @filter.on_llm_request(priority=100)
    async def wait_for_captions(self, event: AstrMessageEvent, req: ProviderRequest):
        """要在内置群聊上下文注入之前跑：等这个群里还没描述完的图。"""
        if self._gcc is None:
            self._hook_group_context()
        umo = event.unified_msg_origin
        if self._inflight.get(umo, 0) > 0 or self._inflight_video.get(umo, 0) > 0:
            await self._wait_inflight(umo)
        self._own_images(event, req)
        await self._turn_images(event, req)

    async def _turn_images(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """这条消息里直接发给她的图（本来由写回复的模型自己看）：先交给 Gemini 看，把描述写进这一轮、图不再给写回复的模型。
        2026-11-12 兄长定：看图、看动图都改成 Gemini（17 张表情包和动图对比里它最准）。Gemini 这双眼睛没开、
        或者有一张没看成：什么都不改，照旧让写回复的模型自己看。"""
        urls = list(req.image_urls or [])
        if not urls or len(urls) > 6 or not self._sec("media").get("gemini_eyes", True) or not omni.gemini_keys():
            return
        said = (event.message_str or "").strip()
        start = time.time()
        try:
            caps = await asyncio.gather(*(self._describer.turn_image(u, said, event.unified_msg_origin) for u in urls))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 这条消息里的图 Gemini 没看成，照旧让写回复的模型自己看 {type(e).__name__}: {str(e)[:160]}")
            return
        for cap in caps:
            req.extra_user_content_parts.append(TextPart(text=f"[Image in this message: {cap}]"))
        req.image_urls = []
        logger.info(f"kaju_basics: 这条消息里的 {len(caps)} 张图交给 Gemini 看了（{time.time() - start:.1f}s）")

    def _own_images(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """她回的这条消息自己带着图（"[图片] 已经什么也看不懂了"）：自己插话/接话那一轮 AstrBot 不把图给她，
        内置群聊上下文又把"这一条"的记录（带着图片描述）拿掉了——她就只看到一句话。把描述补进这一轮。"""
        if not event.get_group_id() or req.image_urls or not self._sec("image").get("own_image", True):
            return
        captions = [c for c in (event.get_extra(OWN_CAPTIONS_KEY) or []) if c]
        if not captions or not any(isinstance(c, Image) for c in event.get_messages()):
            return
        for cap in captions:
            req.extra_user_content_parts.append(TextPart(text=f"[Image in this message: {cap}]"))
        logger.info(f"kaju_basics: 这条消息自己带的 {len(captions)} 张图，描述补进这一轮")

    async def _wait_inflight(self, umo: str) -> None:
        max_wait = float(self._sec("image").get("max_wait", 15))
        video_wait = float(self._sec("media").get("video_wait", 45))
        start = time.time()

        def pending() -> bool:
            spent = time.time() - start
            return ((self._inflight.get(umo, 0) > 0 and spent < max_wait)
                    or (self._inflight_video.get(umo, 0) > 0 and spent < video_wait))

        while pending():
            await asyncio.sleep(0.2)
        left = self._inflight.get(umo, 0) + self._inflight_video.get(umo, 0)
        logger.info(
            f"kaju_basics: 等图片/视频描述 {time.time() - start:.1f}s"
            + (f"，还有 {left} 条没描述完，先回复" if left > 0 else "")
        )

    @filter.on_llm_request(priority=98)
    async def feel_media(self, event: AstrMessageEvent, req: ProviderRequest):
        """这一轮刚看 / 听完的视频、歌（全模态那条路，kaju_core.senses.omni）：她看的时候心里的感受，
        在写回复之前就交给心情（kaju_heart.feel_watched）——排在 describe_media 后面、心情提示前面。"""
        try:
            felt = self._describer.senses.take_felt(event.unified_msg_origin)
        except Exception:  # noqa: BLE001
            return
        if felt:
            event.set_extra("_kaju_felt", True)  # kaju_style 看到这个就不催"说具体"；kaju_heart 事后不再把内容算一遍
        heart = self.body.find("feel_watched") if felt else None
        for p in felt if heart is not None else []:
            try:
                await heart.feel_watched(p, event)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"kaju_basics: 看完的感受交给心情出错 {type(e).__name__}: {e}")

    def _about_her(self) -> str:
        """她现在喜欢 / 感兴趣 / 不喜欢什么（喜好账本）：全模态模型替她看的时候参考。"""
        heart = self.body.find("taste_list")
        try:
            return str(heart.taste_list() or "") if heart is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    @filter.on_llm_request(priority=99)
    async def describe_media(self, event: AstrMessageEvent, req: ProviderRequest):
        """直接发给她（或她引用）的视频：把 AstrBot 的 "[Video Attachment: 文件名, 路径]" 换成看过的描述；
        语音：转写成功就补一句"这是语音"，没转成就说没听清（别把音频塞给不支持的模型）。"""
        sec = self._sec("media")
        if not sec.get("enable", True):
            return
        parts = req.extra_user_content_parts
        if sec.get("video", True):
            own = [c for c in event.get_messages() if isinstance(c, Video)]
            quoted = [c for r in event.get_messages() if isinstance(r, Reply)
                      for c in (getattr(r, "chain", None) or []) if isinstance(c, Video)]
            if (own or quoted) and sec.get("wait_notice", True):
                await self._notice_long_video(event, own + quoted)
            if own or quoted:
                parts[:] = [p for p in parts if not (getattr(p, "text", "") or "").startswith("[Video Attachment")]
                tune = music.asks_music(event.get_message_str() or "")  # 对方提到歌、音乐：顺便听听音乐本身
                for comp in own:
                    parts.append(TextPart(text=f"[Video: {await self._describer.video(comp, event, tune)}]"))
                for comp in quoted:
                    parts.append(TextPart(
                        text=f"[Video in quoted message: {await self._describer.video(comp, event, tune)}]"))
            elif history.MENTIONS_VIDEO.search(event.get_message_str() or ""):
                # 群里的视频没提前看：有人提到视频（没引用）时，看最近那段还没看的
                earlier = self._take_unseen_video(event.unified_msg_origin)
                if earlier is not None:
                    _, who, comp, ev = earlier
                    if sec.get("wait_notice", True):
                        await self._notice_long_video(event, [comp])
                    text = await self._describer.video(comp, ev)
                    parts.append(TextPart(text=f"[Video sent earlier by {who or '群友'}: {text}]"))
                    logger.info(f"kaju_basics: 有人提到视频，补看了 {who} 刚才发的那段")
        read = []  # 读过的文件、看过的 B 站视频：给 memory_weight 收进"珍藏的文件"，kaju_heart 判断情绪时也看
        if sec.get("doc", True):
            own = [c for c in event.get_messages() if isinstance(c, File)]
            quoted = [c for r in event.get_messages() if isinstance(r, Reply)
                      for c in (getattr(r, "chain", None) or []) if isinstance(c, File)]
            if own or quoted:
                parts[:] = [p for p in parts if not (getattr(p, "text", "") or "").startswith("[File Attachment")]
                tunes = {id(c) for c in own + quoted if music.is_audio(getattr(c, "name", "") or "")}
                if tunes and sec.get("wait_notice", True) and self._describer._music_on():
                    await self._say_wait(event, 0, "歌", "听")
                for label, comps in (("File", own), ("File in quoted message", quoted)):
                    for comp in comps:
                        name = getattr(comp, "name", "") or "文件"
                        if id(comp) in tunes:
                            content = await self._describer.music_file(comp, event)
                            parts.append(TextPart(text=f"[{'Music file' if label == 'File' else 'Music file in quoted message'}: "
                                                       f"{name}] {content}"))
                            if not content.startswith("没听成"):
                                read.append({"name": name, "content": content, "path": "",
                                             "quoted": label != "File", "kind": "音乐"})
                            continue
                        content = await self._describer.document(comp, event)
                        parts.append(TextPart(text=f"[{label}: {name}] {content}"))
                        if not content.startswith("没读成"):
                            try:
                                path = await comp.get_file()
                            except Exception:  # noqa: BLE001
                                path = ""
                            read.append({"name": name, "content": content, "path": path or "",
                                         "quoted": label != "File", "kind": "文件"})
                req.system_prompt = (req.system_prompt or "") + "\n\n" + DOC_NOTE
        if self._bili_on():
            own, quoted = bili_links(event)
            want_dm = bili.asks_danmaku(event.get_message_str() or "")  # 对方自己提到"弹幕"才给她看弹幕
            want_cm = bili.asks_comments(event.get_message_str() or "")  # 提到"评论/热评/楼中楼"就把评论区多翻几条
            if (own or quoted) and sec.get("wait_notice", True):
                await self._notice_bili(event, own + quoted)
            for label, urls in (("Bilibili video", own), ("Bilibili video in quoted message", quoted)):
                for url in urls:
                    info, text = await self._describer.bili_video(url, event, danmaku=want_dm, comments=want_cm)
                    parts.append(TextPart(text=f"[{label}: {text}]"))
                    if info is not None:
                        self._recent_bili[event.unified_msg_origin] = (time.time(), url)
                        read.append({"name": info["title"], "content": text, "path": "", "url": info.get("url", ""),
                                     "quoted": label != "Bilibili video", "kind": "B站视频"})
            if not own and not quoted and want_dm:
                # 看完视频之后才问"弹幕怎么说"：把这个聊天里最近看的那个视频的弹幕翻出来
                line = await self._recent_danmaku(event.unified_msg_origin)
                if line:
                    parts.append(TextPart(text=line))
                    own = ["recent"]
            if not own and not quoted and want_cm:
                # 看完视频之后才问"评论区怎么说"：把最近看的那个视频的评论区翻开
                line = await self._recent_comments(event.unified_msg_origin)
                if line:
                    parts.append(TextPart(text=line))
                    own = ["recent"]
            if own or quoted:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + BILI_NOTE
        if sec.get("douyin", True):
            own, quoted = douyin_links(event)
            if (own or quoted) and sec.get("wait_notice", True):
                await self._say_wait(event, 0)  # 开浏览器 + 下载 + 看，要半分钟到一两分钟
            for label, urls in (("Douyin video", own), ("Douyin video in quoted message", quoted)):
                for url in urls:
                    info, text = await self._describer.douyin_video(url, event)
                    parts.append(TextPart(text=f"[{label}: {text}]"))
                    if info is not None:
                        read.append({"name": info["title"], "content": text, "path": "", "url": douyin.page_url(info["id"]),
                                     "quoted": label != "Douyin video", "kind": "抖音视频"})
            if own or quoted:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + DOUYIN_NOTE
        fresh = any((getattr(p, "text", "") or "").startswith(("[Video", "[Bilibili video", "[Douyin video"))
                    for p in parts)
        if sec.get("relook", True) and not fresh:
            await self._relook(event, req)
        if read:
            event.set_extra("kaju_docs_read", read)
        if any(music.LISTEN_MARK in (getattr(p, "text", "") or "") for p in parts):
            req.system_prompt = (req.system_prompt or "") + "\n\n" + MUSIC_NOTE
        if any((getattr(p, "text", "") or "").startswith("[Audio Attachment") for p in parts):
            parts[:] = [p for p in parts if not (getattr(p, "text", "") or "").startswith("[Audio Attachment")]
            parts.append(TextPart(text="[Voice: 对方发了一条语音，没能转成文字，佳树没听清]"))
            if hasattr(req, "audio_urls"):
                req.audio_urls = []
        elif had_voice(event) and (event.get_message_str() or "").strip():
            parts.append(TextPart(text=VOICE_NOTE))

    async def _say_wait(self, event: AstrMessageEvent, seconds: float, what: str = "视频", verb: str = "看") -> None:
        """要花一两分钟看视频/听歌：先让写手说一句"先去看"（每条消息最多说一次；写手不在就不说）。"""
        if event.get_extra(ACK_KEY):
            return
        event.set_extra(ACK_KEY, True)
        style = self.body.find("say_from_card")
        if style is None or not callable(getattr(style, "say_from_card", None)):
            return
        own = own_words(event.get_message_str() or "")
        # 卡片只给关键词（和训练时一样）：写成整句或带上时长，写手会照抄成"佳树先去看这个视频（12分2秒），看完再回话"
        try:
            text = await asyncio.wait_for(style.say_from_card(
                event, points=[f"佳树去{verb}{what}"], emotion="好奇", attitude="平常",
                reply_to=own[:20] or f"分享的{what}", said=(f"[分享了一个{what}] {own}").strip()),
                timeout=float(self._sec("media").get("wait_notice_timeout", 8)))
        except Exception as e:  # noqa: BLE001
            logger.info(f"kaju_basics: 先回一句没写成（不说了） {type(e).__name__}: {e}")
            return
        if not text:
            return
        try:
            await event.send(MessageChain().message(text))
            logger.info(f"kaju_basics: 视频要看一会儿，先回了一句：{text}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 先回一句没发出去 {type(e).__name__}: {e}")

    async def _notice_bili(self, event: AstrMessageEvent, urls: list[str]) -> None:
        for url in urls:
            try:
                info = await self._describer.bili_info(url)
            except Exception:  # noqa: BLE001
                continue
            if self._describer.will_take_a_while(info):
                await self._say_wait(event, info.get("duration") or 0)
                return

    async def _notice_long_video(self, event: AstrMessageEvent, comps: list) -> None:
        """直接发来的长视频（本地有文件、还没看过）也先回一句。"""
        least = float(self._sec("media").get("wait_notice_seconds", 90))
        for comp in comps:
            path = getattr(comp, "path", "") or ""
            if not path or not os.path.isfile(path) or self._describer.key(comp) in self._describer._videos:
                continue
            try:
                dur, _ = await asyncio.to_thread(media.probe, path)
            except Exception:  # noqa: BLE001
                continue
            if dur and dur >= least:
                await self._say_wait(event, dur)
                return

    async def _relook(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """问到刚看过的视频里某个时间点：回到那个视频把这一段再看一遍（relook.py）。"""
        sec = self._sec("media")
        meta = self._describer.last_video(event.unified_msg_origin, float(sec.get("relook_minutes", 60)))
        if meta is None:
            return
        text = event.get_message_str() or ""
        moment = relook.parse_moment(text, meta.get("duration"))
        if moment is None:
            return
        start, end = moment
        span = bili.stamp(start) if end - start < 1 else f"{bili.stamp(start)}~{bili.stamp(end)}"
        title = f"《{meta['title']}》" if meta.get("title") else ""
        parts = req.extra_user_content_parts
        try:
            note = await self._describer.relook(meta, start, end, text, event.unified_msg_origin)
        except SkipVideo as e:
            logger.info(f"kaju_basics: 想补看 {span}，{e}")
            parts.append(TextPart(text=f"[Rewatch failed: 刚才那个视频{title}{e}]"))
            req.system_prompt = (req.system_prompt or "") + "\n\n" + RELOOK_GONE_NOTE
            return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 补看 {span} 没成 {type(e).__name__}: {e}")
            parts.append(TextPart(text=f"[Rewatch failed: 想倒回去看刚才那个视频{title}的 {span}，没打开]"))
            req.system_prompt = (req.system_prompt or "") + "\n\n" + RELOOK_GONE_NOTE
            return
        parts.append(TextPart(text=f"[Rewatched {span} of the video just watched{title}: {note}]"))
        req.system_prompt = (req.system_prompt or "") + "\n\n" + RELOOK_NOTE

    def _take_unseen_video(self, umo: str):
        """这个群最近一段还没看的视频（unseen_video_minutes 分钟内），拿出来就不再算没看。"""
        minutes = float(self._sec("media").get("unseen_video_minutes", 30))
        seen = self._unseen_video.get(umo) or []
        seen[:] = [x for x in seen if time.time() - x[0] <= minutes * 60]
        return seen.pop() if seen else None

    async def _recent_comments(self, umo: str) -> str:
        t, url = self._recent_bili.get(umo, (0.0, ""))
        if not url or time.time() - t > float(self._sec("media").get("bili_recent_minutes", 60)) * 60:
            return ""
        try:
            info = await self._describer.bili_info(url)
        except Exception:  # noqa: BLE001
            return ""
        text = bili.comments_text(await self._describer.bili_comments(info, full=True))
        if not text:
            return f"[Bilibili comments: 刚才那个B站视频《{info['title']}》的评论区没读到]"
        return f"[Bilibili comments: 刚才那个B站视频《{info['title']}》的{text}]"

    async def _recent_danmaku(self, umo: str) -> str:
        t, url = self._recent_bili.get(umo, (0.0, ""))
        if not url or time.time() - t > float(self._sec("media").get("bili_recent_minutes", 60)) * 60:
            return ""
        try:
            info = await self._describer.bili_info(url)
        except Exception:  # noqa: BLE001
            return ""
        dm, hot = await self._describer.bili_danmaku(info)
        text = bili.danmaku_text(dm, hot)
        if not text:
            return f"[Bilibili danmaku: 刚才那个B站视频《{info['title']}》的弹幕没读到]"
        return f"[Bilibili danmaku: 刚才那个B站视频《{info['title']}》的{text}]"

    # ------------------------------------------------------------ 她自己的 B 站小号（kaju_platforms/bili/account.py）
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树B站登录")
    async def cmd_bili_login(self, event: AstrMessageEvent, action: str = ""):
        """佳树的B站小号：发二维码扫码登录（状态｜续期｜退出）"""
        said, stop = await self.bili_login_command(action, event.unified_msg_origin, bool(event.get_group_id()))
        if said:
            yield event.plain_result(said)
        if stop:
            event.stop_event()

    # ------------------------------------------------------------ 抓网页工具碰到视频链接（linkfetch.py）
    async def _link_fetch(self, url: str, event) -> str:
        """她自己拿网页抓取工具去看抖音 / B站视频链接（多半是之前发过的、让她再看一次）：改走看视频的流程。
        不是视频链接、开关关着、没看成都返回 ""（照常抓网页）。"""
        sec = self._sec("media")
        if not sec.get("enable", True) or not sec.get("fetch_watch", True):
            return ""
        if sec.get("douyin", True) and douyin.find_links(url, 1):
            info, text = await self._describer.douyin_video(douyin.find_links(url, 1)[0], event)
        elif self._bili_on() and bili.find_links(url, 1):
            info, text = await self._describer.bili_video(bili.find_links(url, 1)[0], event)
        else:
            return ""
        if info is None:
            logger.info(f"kaju_basics: 抓网页时改看视频，没看成（照常抓网页）：{text}")
            return ""
        logger.info(f"kaju_basics: 抓网页工具碰到视频链接，改成真的去看了：《{info.get('title', '')}》")
        return "（这个链接是用看视频的方式打开的：下面是你自己看到的内容，不只是网页文字）\n" + text

    # ------------------------------------------------------------ 她自己的抖音小号（kaju_platforms/douyin/account.py）
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树抖音登录")
    async def cmd_douyin_login(self, event: AstrMessageEvent, action: str = ""):
        """佳树的抖音小号：在这台电脑上开浏览器、发二维码扫码登录（状态｜退出）"""
        said, stop = await self.douyin_login_command(action, event.unified_msg_origin, bool(event.get_group_id()))
        if said:
            yield event.plain_result(said)
        if stop:
            event.stop_event()


    def _heart(self):
        return self.body.find("feel_browsed")

    def _learner(self):
        """kaju_learn（学到的东西）：看完的视频交给它学，没说看什么时问它有没有想弄明白的事。"""
        star = self.body.find("learn_content")
        return star if star is not None and hasattr(star, "wonder_topic") else None

    def _tz(self):
        import zoneinfo

        try:
            return zoneinfo.ZoneInfo(str(self.context.get_config().get("timezone") or "Asia/Shanghai"))
        except Exception:  # noqa: BLE001
            return zoneinfo.ZoneInfo("Asia/Shanghai")


    @filter.llm_tool(name="browse_bilibili")
    async def browse_bilibili(self, event: AstrMessageEvent, minutes: int = 0, topic: str = ""):
        """兄长大人本人允许你、或者叫你去刷一会儿 B 站时用：你会在后台自己刷 B 站，按自己的口味挑几个视频看完（不用等，看完的会记在心里，之后聊到再说）。别人叫你去刷不要用；你自己想刷也要先问兄长大人。

        Args:
            minutes(number): 他让你刷多久（分钟），没说就留空
            topic(string): 他让你看某一类的（比如"猫""做饭""pjsk"），就填关键词；没说就留空。正在刷的时候他又让你看别的，也用这个填上（会看完手上这个就换过去）
        """
        if str(event.get_sender_id() or "") != self._owner():
            return "没去：只有兄长大人本人能让你去刷B站。用佳树的口吻婉拒，说要兄长大人同意才行。"
        said = self.start_browsing(event, minutes, topic)
        if said.startswith(("开始刷", "换过去了")):
            return (said + "。现在用佳树的口吻回一句就好（比如开开心心答应着去看啦）；你还没看，别说看到了什么，"
                    "也别说看完了会汇报。")
        return said + " 用佳树的口吻如实告诉兄长大人。"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树刷B站")
    async def cmd_browse(self, event: AstrMessageEvent, arg: str = "", arg2: str = ""):
        """让佳树去刷一会儿B站：/佳树刷B站 [分钟] [想看什么]｜记录｜停"""
        arg = arg.strip()
        if arg in ("记录", "看看"):
            text = browse.chat_note(self._browse_log, time.time(), self._tz(), hours=24 * 7, max_shown=10 ** 6)
            yield event.plain_result(text or "最近没刷过B站。")
            return
        if arg in ("停", "停下"):
            if self._browsing is not None and not self._browsing.done():
                self._browse_next = None
                self._browsing.cancel()
                yield event.plain_result("叫她别刷了。")
            else:
                yield event.plain_result("她现在没在刷。")
            return
        minutes, topic = 0.0, arg2.strip()
        try:
            minutes = float(arg)
        except ValueError:
            topic = (arg + " " + topic).strip()
        yield event.plain_result(self.start_browsing(event, minutes, topic, by="管理员命令"))

    @filter.llm_tool(name="browse_douyin")
    async def browse_douyin(self, event: AstrMessageEvent, minutes: int = 0, topic: str = ""):
        """兄长大人本人允许你、或者叫你去刷一会儿抖音时用：你会在后台用自己的抖音小号刷抖音精选，按自己的口味挑几个视频看完（不用等，看完的会记在心里，之后聊到再说）。别人叫你去刷不要用；你自己想刷也要先问兄长大人。他说刷 B 站就用 browse_bilibili。

        Args:
            minutes(number): 他让你刷多久（分钟），没说就留空
            topic(string): 他让你看某一类的（比如"猫""做饭"），就填关键词；没说就留空（抖音搜索有时要验证，搜不了就刷精选）
        """
        if str(event.get_sender_id() or "") != self._owner():
            return "没去：只有兄长大人本人能让你去刷抖音。用佳树的口吻婉拒，说要兄长大人同意才行。"
        said = self.start_browsing(event, minutes, topic, site="douyin")
        if said.startswith(("开始刷", "换过去了")):
            return (said + "。现在用佳树的口吻回一句就好（比如开开心心答应着去看啦）；你还没看，别说看到了什么，"
                    "也别说看完了会汇报。")
        return said + " 用佳树的口吻如实告诉兄长大人。"

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("佳树刷抖音")
    async def cmd_browse_douyin(self, event: AstrMessageEvent, arg: str = "", arg2: str = ""):
        """让佳树去刷一会儿抖音：/佳树刷抖音 [分钟] [想看什么]（记录、停 跟 /佳树刷B站 共用）"""
        arg = arg.strip()
        if arg in ("记录", "看看", "停", "停下"):
            async for r in self.cmd_browse(event, arg, arg2):
                yield r
            return
        minutes, topic = 0.0, arg2.strip()
        try:
            minutes = float(arg)
        except ValueError:
            topic = (arg + " " + topic).strip()
        yield event.plain_result(self.start_browsing(event, minutes, topic, by="管理员命令", site="douyin"))

    @filter.on_llm_request(priority=-80)
    async def browse_note(self, event: AstrMessageEvent, req: ProviderRequest):
        """兄长找她时（私聊或群里）：她正在刷 / 最近刷到了什么（只给她看，聊到了再说）。不是兄长的人不给 browse_bilibili。"""
        if event.get_platform_name() != "aiocqhttp":
            return
        self._chat_seen = time.time()
        if str(event.get_sender_id() or "") != self._owner():
            tools = getattr(req, "func_tool", None)
            names = set(tools.names()) if tools else set()
            for tool in ("browse_bilibili", "browse_douyin"):
                if tool in names:
                    tools.remove_tool(tool)
            return
        if not self._bw("enable", True):
            return
        if not event.get_group_id():  # 群里叫她去刷的，群里问起也得知道刷没刷完、刷到了什么
            self._owner_seen = time.time()
        note = browse.chat_note(self._browse_log, time.time(), self._tz(), hours=self._bw("note_hours", 6.0),
                                max_shown=self._bw("note_turns", 6))
        if not note:
            return
        req.system_prompt = (req.system_prompt or "") + "\n\n" + note
        event.set_extra(NOTE_KEY, note)
        if not self._browse_log.data.get("running") and self._browse_log.data["sessions"]:
            last = self._browse_log.data["sessions"][-1]
            last["shown"] = int(last.get("shown", 0)) + 1
            self._browse_log.save()

    @filter.on_llm_request(priority=-95)  # 别的插件都加完提示之后、挪动会变的提示（move_volatile）之前
    async def voice_snapshot(self, event: AstrMessageEvent, req: ProviderRequest):
        """记下和兄长私聊时她完整的系统提示（人设 + 各插件的说话习惯）：刷到视频想主动说时用同一套口吻写。"""
        if event.get_platform_name() != "aiocqhttp" or event.get_group_id() or not self._bw("share", True):
            return
        if str(event.get_sender_id() or "") != self._owner():
            return
        system = browse.strip_note(req.system_prompt or "", event.get_extra(NOTE_KEY) or "")
        if not system.strip():
            return
        snap = self._browse_log.data.get("voice") or {}
        saved = float(snap.get("saved", 0) or 0)
        self._browse_log.data["voice"] = {"t": time.time(), "system": system, "saved": saved}
        if time.time() - saved > 600:  # 文件十分钟最多写一次
            self._browse_log.data["voice"]["saved"] = time.time()
            self._browse_log.save()

    def _style(self):
        return self.body.find("polish")

    async def _owner_history(self, umo: str, n: int = 10) -> list[dict]:
        """和兄长私聊最近的 n 条（只要文字）。"""
        import json as _json

        try:
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(umo)
            conv = await cm.get_conversation(umo, cid) if cid else None
            hist = conv.history if conv else []
            hist = _json.loads(hist) if isinstance(hist, str) and hist else (hist or [])
        except Exception as e:  # noqa: BLE001
            logger.info(f"kaju_basics: 私聊历史没读到 {type(e).__name__}: {e}")
            return []
        out = []
        for m in hist:
            if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
                continue
            c = m.get("content")
            if isinstance(c, list):
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            c = str(c or "").strip()
            if c:
                out.append({"role": m["role"], "content": c[:600]})
        return out[-n:]


    async def say_to_owner(self, prompt: str, *, said: str, record: str, link: str = "", umo: str = "",
                           skip_minutes: float | None = None) -> tuple[bool, str]:
        """自己这边发生了事（刷到视频、书读到一半/读完），用她和兄长私聊时的完整口吻主动私聊他一两句。
        prompt 写清发生了什么、想怎么说（可以让模型 [SKIP]）；said 给 kaju_style.polish 看的场合；record 记进私聊历史的那句。
        夜里（browse.quiet_*）、他 skip_minutes（默认 browse.share_skip_minutes 三分钟）内刚聊过、还没有口吻快照时不发。
        返回 (发了没有, 发的话 / 没发的原因)。"""
        now = time.time()
        umo = umo or self._owner_umo()
        in_group = ":GroupMessage:" in umo  # 他在群里叫她去的：回群里（他多半正在群里等）
        if in_group and group_quiet():
            return False, f"群聊暂停中（{group_quiet()}）"
        if browse.in_quiet(dt.datetime.fromtimestamp(now, self._tz()).hour, self._bw("quiet_start", 23), self._bw("quiet_end", 8)):
            return False, "太晚了 / 太早了"
        skip = self._bw("share_skip_minutes", 3.0) if skip_minutes is None else float(skip_minutes)
        if not in_group and now - float(getattr(self, "_owner_seen", 0) or 0) < skip * 60:
            return False, "兄长正在跟她聊，聊到再说"
        snap = self._browse_log.data.get("voice") or {}
        if not snap.get("system") or now - float(snap.get("t", 0)) > 7 * 86400:
            return False, "还没有她最近和兄长私聊时的口吻（重启后兄长跟她说过话就有了）"
        try:
            pid = ""
            get_pid = getattr(self.context, "get_current_chat_provider_id", None)
            if get_pid is not None:
                pid = await get_pid(umo)
            if not pid:
                prov = await self.context.get_using_provider_async(umo)
                pid = (getattr(prov, "provider_config", None) or {}).get("id") or prov.meta().id
            history = await self._owner_history(umo, 10)
            resp = await asyncio.wait_for(self.context.llm_generate(
                chat_provider_id=pid, prompt=prompt, system_prompt=snap["system"], contexts=history), timeout=90)
            text = browse.clean_share(getattr(resp, "completion_text", "") or "")
            if not text:
                return False, "模型觉得现在不合适（SKIP）"
            style = self._style()
            if style is not None:
                ctx = [("佳树：" if m["role"] == "assistant" else "群里：" if in_group else "兄长大人：") + m["content"].replace("\n", " / ")[:120]
                       for m in history[-3:]]
                only_writer = bool(getattr(style, "writer_only", lambda: False)())
                try:
                    polished = await style.polish(text, ctx, said=said)
                    if not polished and only_writer:  # 只发回复器的话（2026-11-13）：没写成就不发主模型的原稿
                        logger.info("kaju_basics: 回复器没写成，这次不主动跟兄长说")
                        return False, "回复器没写成"
                    text = polished or text
                except Exception as e:  # noqa: BLE001
                    if only_writer:
                        logger.info(f"kaju_basics: 回复器没写成，这次不主动跟兄长说 {type(e).__name__}: {e}")
                        return False, "回复器没写成"
                    logger.info(f"kaju_basics: 说话习惯没过成（用原稿） {type(e).__name__}: {e}")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                if i:
                    await asyncio.sleep(1.2)
                await self.context.send_message(umo, MessageChain().message(ln))
            if link:
                await asyncio.sleep(0.8)
                await self.context.send_message(umo, MessageChain().message(link))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 主动跟兄长说没说成 {type(e).__name__}: {e}")
            return False, f"出错了 {type(e).__name__}"
        star = self.body.find("log_own")  # 记进 kaju_life 的聊天记录：日记、心里话、记忆星海才看得到
        if star is not None:
            try:
                star.log_own(("g" + umo.rsplit(":", 1)[-1]) if in_group else ("p" + self._owner()), text)
            except Exception as e:  # noqa: BLE001
                logger.info(f"kaju_basics: 主动说的话没记进聊天记录 {type(e).__name__}: {e}")
        try:  # 记进私聊历史：他回的时候她知道在说哪个
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(umo)
            if cid:
                await cm.add_message_pair(cid, {"role": "user", "content": record},
                                          {"role": "assistant", "content": text + (f"\n{link}" if link else "")})
        except Exception as e:  # noqa: BLE001
            logger.info(f"kaju_basics: 主动说的话没记进私聊历史 {type(e).__name__}: {e}")
        return True, text

    async def _cleanup_loop(self) -> None:
        """看完的 B 站视频过一阵自动删（启动时先清一次，之后每 10 分钟查一次）。"""
        while True:
            try:
                await asyncio.to_thread(self._describer.cleanup_downloads)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"kaju_basics: 清理下载的视频出错 {type(e).__name__}: {e}")
            await asyncio.sleep(600)

    @filter.on_llm_request(priority=-90)
    async def hide_chat_tools(self, event: AstrMessageEvent, req: ProviderRequest):
        """QQ 上平常聊天这一轮不给 send_message_to_user：她会写好回复、再用它把同一段话发一遍。"""
        if event.get_platform_name() != "aiocqhttp" or not req.func_tool:
            return
        hide = self._sec("chat_tools").get("hide", DEFAULT_HIDDEN_TOOLS)
        if isinstance(hide, str):
            hide = hide.replace("，", ",").split(",")
        pats = [str(n).strip() for n in hide or [] if str(n).strip()]
        for name in list(req.func_tool.names()):
            if any(fnmatch.fnmatchcase(name, p) for p in pats):  # 可以写通配符：memory_*_admin
                req.func_tool.remove_tool(name)

    @filter.on_using_llm_tool()
    async def clean_tool_message(self, event: AstrMessageEvent, tool, tool_args: dict | None):
        """定时任务里她用 send_message_to_user 直接发消息，不经过表情包插件：把 &&标签&& 去掉。"""
        if getattr(tool, "name", "") != "send_message_to_user" or not isinstance(tool_args, dict):
            return
        msgs = tool_args.get("messages")
        if not isinstance(msgs, list):
            return
        kept = []
        for m in msgs:
            if isinstance(m, dict) and m.get("type") == "plain" and isinstance(m.get("text"), str):
                m["text"] = strip_meme_tags(m["text"])
                if not m["text"].strip():
                    continue
            kept.append(m)
        msgs[:] = kept

    @filter.on_decorating_result(priority=100000)  # 早于表情包插件（99999），看到的还是原文
    async def drop_repeats(self, event: AstrMessageEvent):
        """同一轮里已经发过的行不再发（模型把同一段话在一轮里说了好几遍）。"""
        result = event.get_result()
        chain = getattr(result, "chain", None)
        if not chain:
            return
        said: set[str] = event.get_extra(SAID_KEY) or set()
        dropped = 0
        words_before = words_after = False
        for comp in chain:
            if isinstance(comp, Plain) and comp.text:
                words_before = words_before or bool(units(comp.text))
                comp.text, n = drop_repeated(comp.text, said)
                dropped += n
                words_after = words_after or bool(units(comp.text))
        if dropped:
            logger.info(f"kaju_basics: 这一轮已经说过的 {dropped} 行不再发 ({event.unified_msg_origin})")
            if words_before and not words_after and all(isinstance(c, Plain) or type(c).__name__ in ("Reply", "At")
                                                        for c in chain):
                chain.clear()
                return
            chain[:] = [c for c in chain if not (isinstance(c, Plain) and not c.text)]
        for comp in chain:
            if isinstance(comp, Plain) and comp.text:
                said.update(units(comp.text))
        event.set_extra(SAID_KEY, said)

    @filter.on_decorating_result(priority=-100000)  # 晚于表情包插件
    async def strip_leftover_tags(self, event: AstrMessageEvent):
        """表情包插件没认出来的 &&标签&& 不要原样发出去。"""
        chain = getattr(event.get_result(), "chain", None)
        if not chain:
            return
        changed = False
        for comp in chain:
            if isinstance(comp, Plain) and comp.text and "&&" in comp.text:
                new = strip_meme_tags(comp.text)
                changed = changed or new != comp.text
                comp.text = new
        if changed:
            chain[:] = [c for c in chain if not (isinstance(c, Plain) and not c.text)]

    @filter.on_llm_request(priority=-100)
    async def add_image_note(self, event: AstrMessageEvent, req: ProviderRequest):
        texts = [getattr(p, "text", "") or "" for p in (req.extra_user_content_parts or [])]
        texts.append(req.prompt or "")
        if req.image_urls or any("[Image" in t or "[Video" in t for t in texts):
            req.system_prompt = (req.system_prompt or "") + "\n\n" + IMAGE_NOTE + media_turn_note(event)

    @filter.on_llm_request(priority=-sys.maxsize)
    async def move_volatile(self, event: AstrMessageEvent, req: ProviderRequest):
        """最后执行：把最近会变的插件提示挪到本轮用户消息末尾。"""
        cfg = self._sec("stable_prefix")
        if not cfg.get("enable", True):
            return
        base = event.get_extra(BASE_KEY)
        if base is None:
            return
        umo = event.unified_msg_origin
        result = plan_move(
            base, req.system_prompt or "", self._since.get(umo, {}), time.time(),
            float(cfg.get("stable_hours", 4)) * 3600,
        )
        if result is None:
            if not (req.system_prompt or "").startswith(base.rstrip()) and not self._warned_prefix:
                self._warned_prefix = True
                logger.info("kaju_basics: 有插件改动了系统提示的开头，这一轮不挪")
            return
        new_sys, moved, since = result
        self._since[umo] = since
        req.system_prompt = new_sys
        req.extra_user_content_parts.append(TextPart(text=HEAD + moved + TAIL).mark_as_temp())
        logger.info(f"kaju_basics: {umo} 系统提示保留 {len(new_sys)} 字，挪走 {len(moved)} 字到本轮消息末尾")
