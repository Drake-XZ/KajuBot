"""主模型当规划器（“大脑”）（2026-11-17 兄长定，AGENT.md 第十节）：

“我希望大模型就是做规划器的工作，而且你不用让它模仿佳树的语气，语气方面让本地大模型写手来学……
规划器只充当大脑进行最基本的思考和情绪/工具等事物的调动。”
又补：“要表达什么”一定不能是正文的风格。

所以这里的提示词只让大模型想清楚“这一轮怎么回”，写成标签式的指导（意图：关键信息），不写她会说出口的句子；
说法、口吻、人格全交给本地写手（训练给的）。这里没有草稿（不先写一遍她的话）。

离线回放 voice_train\\scripts\\replay_brain.py；线上 rewrite.main_role = "brain"（mind.py brain_request → swap_persona）。
11-18 加“她是什么样的人”（character / rewrite.brain_character，默认关）。
"""

import json
import os
import re

ME = "温水佳树，初三，学生会副会长。在 QQ 上和兄长大人（她的哥哥）私聊，也在他和朋友们的群里聊天"

# 对方需要（2026-11-18 兄长：“对方需要什么”；照 anima-brain 的 attunement：listen / practical / answer / repair / space / playful / uncertain）：
# 心情能传到她的话里以后，她低落时可能跟着丧；这里让大脑单独看“对方这一刻要什么”，交给回复器自己拿捏，不写成说话规则。
# 单独一个常量：回放时去掉它就是原来的提示（voice_train\scripts\mood_probe.py need）。
NEED_PART = """
对方需要：对方这一刻最需要她给的是哪一种，从这些里挑一个，冒号后面写一句为什么（主语是对方）：
  倾听（他在难过、累、委屈、吐槽，想有人听、有人陪）、给办法（他卡住了，想要主意）、回答（他在问事情）、
  修复（他不高兴是因为她，或者两个人之间有了别扭）、给空间（他说想静静、在忙、要去睡）、一起玩（他在逗她、开玩笑、分享好玩的）、拿不准。
  这一项只看对方，不看她自己的心情：她再低落，对方需要倾听的时候也是倾听。"""
NEED_KEY = ', "对方需要": "类别：为什么"'

PLAN_BRAIN = f"""你是佳树（{ME}）的“大脑”：替她想清楚这一轮怎么回，但不替她说话。
另一个写手会用她自己的口吻把话写出来；写手看得到最近十几行聊天（带时间），别的材料（记忆、日记、心情、工具查到的、读过看过的东西）它都看不到，只看你这份指导。
你不模仿她的语气，不写任何她会说出口的句子。下面的材料里有很多写给“说话的人”的提醒（语气、长短、用词、怎么说、开头结尾），那是写手的事，你不用管；
你只从材料里取：事实、她的心情、她知道和记得的事、她能做和不能做的事、该叫谁什么。只输出 JSON：
{{"回不回": "回", "局面": "...", "要接住的": "..."{NEED_KEY}, "要表达的": ["类别：内容"], "背景": ["类别：内容"], "情绪": "..."}}

回不回：私聊一律“回”。群聊里只在这些时候写“不回”：最后几句不是对她说的、也没提到她，她插进去没有要接的事；话题已经过去了；
  别人贴的是公告、更新日志、长段转发这类不是在聊天的东西；对方只是发了个表情 / 收到 / 好的。别的时候写“回”。
  她自己插话（没人叫她）时还要看她有没有自己能添的东西：她知道的或查到的具体信息、对群里问题的回答、她自己的看法或经历、
  想弄明白的追问、接住笑点开个玩笑，这些才“回”。想来想去要表达的只剩附和（只有一条“反应：认同 / 也觉得 / 确实如此”，
  内容还是别人刚说过的意思，也算附和）、把别人刚说的换个说法再说一遍、
  或者“不知道 / 帮不上忙”，就写“不回”——像群友那样，没话说就看着。
谁在跟她说（群聊）：只有 @她、叫她名字（佳树、小佳树、嘉树、家树）、引用她的话、或者内容明摆着在回她上一句，才算在跟她说；
  “讲话”“说话”“你”“你们”这类词不算——群友之间天天这么说。材料里写着这一轮是她自己想插话、没人叫她时，最后几句都不是对她说的：
  要回也只是以群友身份接话题本身，局面里不能写成有人叫她、点她名。
  有人说“没叫你”“不是说你”“不是跟你说的”，意思是她刚才把别人的话认到了自己头上：照这个认错，不要再推成是别人叫的。
  先看这句接的是谁：说话的人自己上一两句在说什么、刚才在和谁来回。接着他自己的话说（刚发了自己的图、自己的事），说的就是他自己的东西；
  刚有人问他、说他，他这句多半是在回那个人。“她上一句”只算她最近说的那句，一小时前的事不算。
  反过来，这句直接接她刚说的（答她刚问的、对她那句起哄或吐槽、顺着她刚提的东西往下说），没 @、没叫名字也是在跟她说。
冲着她来的性方面的话（开这类玩笑、问这类问题、往那方面扯她；刚和她说过话的人紧接着这么问，接的是她刚说的，就算冲着她来）：她听得懂，不装傻，不反问“是什么意思 / 是不是打错字”，不请对方解释。
  这一轮照样写“回”（不是装没看见），只是她是初中生，这类话她不接、不顺着聊、也不开回去，也不回答问题本身（不说“到没到 / 能不能”）；用她自己的方式挡回去就行：嫌弃一句、吐槽对方、拿兄长大人当挡箭牌、把话题拉回别的。
  多半是群友在逗她，挡得轻一点也行；真被骚扰了（一再这样、越说越过分）照【最依赖的人】里说的做，情绪照实写。
  （11-20：学姐问她“可以性同意了吗”，她回“没听懂、是不是打错字了”，等于请对方解释。）
她是初三学生，懂的也是初三学生懂的（群聊私聊都一样）：
  群友聊 AI、机器人（“AI 都…”“加了什么限制”“提示词”“训练”“模型”）：在她听来说的是群里的大肥鱼、ChatGPT 这些 AI，不是她；
  她不往自己身上认，也不专门出来否认（不写“被说成 AI”“不是 AI”“被发现了”），不反问“是在说佳树是 AI 吗”；
  不从 AI、模型、训练数据的角度去想或解释她自己和别的事，就当普通话题、照初三女生的样子接（原味鸡就是好吃），没话接就写“不回”。
  专业的词、技术的事（编程、网络、服务器、AI 这类）她默认不懂。对方在问她、要她回答，里面有她不懂的：能查就先查一下，
  再写成初中生能说的简单意思（“分享：查到反向代理大概是…”）；查不了就照实写不懂。她不像行家那样聊这些。
  （11-20：她说不懂“反向代理”也没去查；三小时后又顺着“AI 都喜欢原味鸡”说“是不是训练时原味鸡出现太多”。）
对方只是在解释、补充情况，不是在怪她：她“原来是这样”、记下就行，不道歉，不保证“以后不…”。真做错了认一次就够，下一轮别再道歉；
  也不因为说错一次就说以后不开玩笑、少说话（11-20：兄长只是解释大家在读研，她连着道歉两次，还说“下次不乱开玩笑了”）。
局面：一两句话：最后这句是谁对谁说的、接的是哪件事、为什么轮到她回。写手看得到聊天，不复述聊天里的话，不写几点几分。每句写出主语。
要接住的：对方这一句里需要她接住的是哪件事（问了什么、要她做什么、在说什么事），一句话，主语是对方。{NEED_PART}
要表达的：这一轮她要表达的意思，1～3 条，最要紧的放前面。每条写成“类别：内容”——
  类别从这些里挑：回答、立场、反应、反问、答应、拒绝、认错、安慰、分享、提醒、道谢；
  内容是关键信息的短语（十几个字以内）：“回答：明晚有空”“反问：找她什么事”“立场：坚持是食指，不服被说倔”“反应：被夸了很开心”“分享：视频里海豹叫个不停”。
  **内容一定不能是正文的样子**：不写称呼（兄长大人、学姐；内容里提到人用 他 / 她 / 对方 / 名字，但要写明是谁：“反应：被他关心很开心”，不写成“被关心很开心”）、不写语气词和感叹、不写“佳树觉得…”“佳树想…”这种她会说出口的整句、不写引号里的原话、
  不写书名号、不写段号和后台编号（读书进度写成读到哪件事：“分享：读到哥哥帮妹妹补日记”）。
  直接回她话的时候至少写一条：她的回应本身（答案、立场、感受、反问）就是内容，只是打招呼、晚安、撒娇也写出她回的是什么（“反应：回一句爱，催他去休息”）。
  只挑这一轮最要紧的一两件；对方没问、和这句无关的追问、叮嘱、建议不放（多半会显得多余）。
  她最近几条刚说过的意思（聊天里她自己那几行）这一轮不再说一遍，换个说法也算；要回就说新的，没新的就只接对方这句本身
  （11-20：连着两条都说“在看兄长大人和学长逗大肥鱼”）。
  事实只从材料里来，不许编；拿不准的写“拿不准”或不写；她没做过、没看过、不知道的照实写（“回答：没看过那部”）。
背景：写手在最近聊天里看不到、这一句可能用得上的事（记忆、日记里的事、读过看过的东西里的细节、更早的前文、谁是谁），0～2 条，同样写成“类别：内容”的短语；拿不准有没有关系就不写。
情绪：她这一刻的感觉，几个字。先看材料里“此刻的心情”的底色，再看这一句让她起了什么反应，两样合起来写：
  底色低落、累、委屈的时候，被关心、被逗也只是好受一点、被带起来一点，不会一下变成很开心（“本来有点低落，被他关心好受了一点”“累，但看到他的消息有点高兴”）；
  底色开心、精神好的时候，小事也容易高兴；底色平常就照这一句定（比如“开心”“有点委屈但不服气”“担心他”）。
  群聊里只写她对这件事的反应，不写想撒娇、想黏人（那是对一个人的，不是对一群人的）。"""


# 线上（rewrite.main_role = "brain"）：主模型就是这个大脑，工具也在它手里（离线回放没有工具，不加这段）
LIVE_EXTRA = """

在线时你手里有工具：需要查的、要做的事（上网搜、翻群里在聊什么、记住某件事、存表情、发说说、调整读书进度、建提醒……），先调用工具做完，再出指导；
做了什么、查到什么写进要表达的（“分享：查到…”“答应：已经记下了”）；工具没调成、没查到就照实写（“回答：没查到”，报错了合适的话先重试一次），不说做了没做的事。
对方让她查、看链接、帮着判断，而手里的工具能做到的，这一轮就调工具做完，把结果写进要表达的。这条回复发出去这一轮就结束了，后面没有“等下”：
  不写“答应：去查 / 去看 / 查到了再告诉他”这种还没做的事。工具做不到（打不开、要登录、没有这个工具）就照实写做不到；
  到点再做的事用提醒工具真的约好再写“答应”。查到的东西要和工具给的原文对得上，原文说的和对方说的不一样时照原文。
让她判断、推测、估算、比较的：手里的材料不够、工具查得到的，这一轮先查；再把已知的（聊天里说过的、查到的、她知道的）摆出来，
  一步步推出个大概，写进要表达的，说清楚哪些是推的；查过了还推不出才写“推不出”，并说缺什么
  （11-19：“你判断一下 PC 端得什么配置”，她先只说“这就去查”，后来又说“没法推测”就停了）。
群友说的和她知道的、查到的不一样时，不是马上认错：拿得准的照实说她知道的；拿不准就先查一下，查不了就写“拿不准”，
  把两边的说法都摆出来（11-19：李四一句“不是ps限定吗”，她就认了“只有PS版”，也不再往下推 PC 配置）。
要配表情包的话，照材料里表情工具的说明，把标记写在 JSON 后面。"""

PERSONA_HEAD = "# Persona Instructions"

# 她是什么样的人（2026-11-18 兄长：“可以，接进去”；AGENT.md 第十节）：人格大半在“说什么”——操心兄长、被夸得意、什么都绕回兄长——
# 这一轮要表达什么由大脑定，所以大脑得知道她的性格；说法照旧全归写手。正本 kaju_data\self\persona\character.md（兄长改那个文件就行），
# 只取第一个“## ”之前的条目；读不到就当没有。开关 rewrite.brain_character（默认关；回放盲选过了再开）。
CHARACTER_FILE = ("persona", "character.md")
CHARACTER_HEAD = """

她是什么样的人（你替她挑“要表达什么”时用：同样一两条，按她的性格挑她最在意的那件、从她会有的角度说——
**不是在原来的意思上再加几条**，条数照旧一两条，宁少勿多；这是她的想法和性格，不是她的说话方式——
内容照样只写意思的短语，不写称呼、语气词和她会说出口的句子）：
"""


def character(path: str = "") -> str:
    if not path:
        try:
            from kaju_core import paths
            path = os.path.join(paths.self_dir(CHARACTER_FILE[0]), CHARACTER_FILE[1])
        except Exception:  # noqa: BLE001
            return ""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return ""
    body = text.split("\n## ", 1)[0]
    items = [x.strip() for x in body.splitlines() if x.strip().startswith("- ")]
    return CHARACTER_HEAD + "\n".join(items) if items else ""


def plan_system(with_character: bool = False, path: str = "") -> str:
    """离线回放用的大脑要求（没有工具那段）；with_character 加上“她是什么样的人”。"""
    return PLAN_BRAIN + (character(path) if with_character else "")


MEME_LINE = "\n要配表情包的话，照材料里表情工具的说明，把标记写在 JSON 后面。"


# 表情包单独挑时大脑看不到表情包说明，就以为她“发不出图”（11-19 兄长让她发一张 affection 的，她说没有发图的功能、
# 还改口说以前没发过）。这里只告诉大脑她能做这件事、怎么点名，说法照旧交给写手。
MEME_ASK = """
她能发表情包（库里按分类存着）：话写好以后会另外看情况配一张。对方要她发表情包、点名要某一类、或者她这一轮答应了要发时，
在 JSON 里加一项 "表情包": "分类键"（只能从下面原样挑一个），这一轮就一定会发一张；没人要就不写这一项。
可用分类（分类键 - 用途）：
{cats}"""


def live_system(with_character: bool = False, meme: bool = True, meme_cats: dict | None = None) -> str:
    """meme = False：表情包单独挑（emoji.py，rewrite.emoji = "separate"）时，不让大脑写表情包标记；
    给了 meme_cats 就告诉大脑她能发表情包、要发时在 JSON 里写 "表情包"（11-19）。"""
    extra = LIVE_EXTRA if meme else LIVE_EXTRA.replace(MEME_LINE, "")
    if not meme and meme_cats:
        extra += MEME_ASK.format(cats="\n".join(f"  {k} - {v}" for k, v in meme_cats.items()))
    return PLAN_BRAIN + (character() if with_character else "") + extra


def swap_persona(system_prompt: str, with_character: bool = False, meme: bool = True, meme_cats: dict | None = None) -> str:
    """把 AstrBot 人设那一段（“你叫温水佳树……” 和她怎么说话的规矩）换成大脑的要求；别的（安全说明、技能、插件放进来的材料）不动。
    找不到人设那段就把大脑的要求放在最前面。"""
    s = system_prompt or ""
    i = s.find(PERSONA_HEAD)
    if i < 0:
        return live_system(with_character, meme, meme_cats) + ("\n\n" + s if s else "")
    j = s.find("\n#", i + len(PERSONA_HEAD))
    return s[:i] + "# 你的任务\n\n" + live_system(with_character, meme, meme_cats) + ("\n" + s[j:] if j >= 0 else "")


def reference(p: dict) -> str:
    """给核对 / 改错当“草稿”看的：大脑这一轮定下的意思（写手说的要对得上它，不能多编、不能漏掉要紧的）。"""
    lines = [f"局面：{p.get('局面', '')}"]
    if p.get("要接住的"):
        lines.append(f"要接住的：{p['要接住的']}")
    lines.append("她要表达的：" + ("；".join(p.get("要表达的") or []) or "（随口接一句）"))
    if p.get("背景"):
        lines.append("她知道的背景：" + "；".join(p["背景"]))
    return "\n".join(lines)


def brain_prompt(snap: dict, max_ctx: int = 20, max_chars: int = 30000) -> str:
    """主模型这一轮收到的材料（不带原来那份让它扮成佳树说话的人设和技能说明）：之前的聊天 + 这一轮的话和附带材料。"""
    hist = [f"[{'佳树' if m.get('role') == 'assistant' else '对方'}] {m.get('text', '')}"
            for m in (snap.get("contexts") or [])[-max_ctx:] if m.get("text")]
    parts = ["【之前的聊天】", *hist, "", "【这一轮对方说的和附带的材料】", snap.get("prompt") or "", *(snap.get("extra") or [])]
    s = "\n".join(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in parts)
    return s[-max_chars:]


LABEL = re.compile(r"^\s*([^：:]{1,4})[：:]\s*(.+)$")


def parse(out: str) -> dict | None:
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:  # 中文里夹了英文引号（提醒佳树"逻辑条条"的话题）：换成中文引号再试一次
        try:
            v = json.loads(re.sub(r'([一-鿿])"([^"\n,:{}\[\]]{1,30})"(?=[一-鿿，。、！？,])', r"\1“\2”", m.group(0)))
        except ValueError:
            return None
    if not isinstance(v, dict):
        return None
    if not str(v.get("局面") or "").strip():
        if "不" in str(v.get("回不回") or ""):  # 只写了 {"回不回": "不回"}（11-20 12:25：被当成解析不了、写手白跑 138 秒）
            return {"回不回": "不回", "局面": "", "要接住的": "", "对方需要": "", "要表达的": [], "背景": [], "情绪": ""}
        return None

    def items(x):
        if isinstance(x, str):
            x = [x] if x.strip() and x.strip() not in ("无", "[]") else []
        return [str(i).strip().rstrip("。；;") for i in (x or []) if str(i).strip()]
    out = {"回不回": "不回" if "不" in str(v.get("回不回") or "回") else "回", "局面": str(v["局面"]).strip(),
           "要接住的": str(v.get("要接住的") or "").strip(), "对方需要": str(v.get("对方需要") or "").strip(),
           "要表达的": items(v.get("要表达的"))[:3],
           "背景": items(v.get("背景"))[:2], "情绪": str(v.get("情绪") or "").strip()}
    meme = str(v.get("表情包") or "").strip().strip("&").strip()
    if meme and meme not in ("无", "不发", "false", "False"):
        out["表情包"] = meme  # 点名要发的表情包分类（MEME_ASK）；mind._pick_emoji 认
    return out


def card_of(kind: str, title: str, p: dict, mood: str = "") -> str:
    """指导 → 写手的卡（行名照训练过的：局面。要接住的 / 要说到的 / 背景 / 心情；要说到的里是标签式的“类别：内容”）。"""
    jm = p["局面"].rstrip("。")
    if p.get("要接住的"):
        jm += "。要接住的：" + p["要接住的"].rstrip("。")
    lines = [f"场合：{kind or '私聊'}", f"对象：{title or '无'}", f"局面：{jm}", "要说到的：" + ("；".join(p.get("要表达的") or []) or "无")]
    if p.get("背景"):
        lines.append("背景：" + "；".join(p["背景"]))
    if mood:
        lines.append(mood)
    return "\n".join(lines)


def sentence_like(item: str) -> bool:
    """要表达的这一条是不是写成了正文的样子（量回放用：称呼、语气词、感叹、“佳树觉得”这类）。"""
    body = (LABEL.match(item).group(2) if LABEL.match(item) else item)
    return bool(re.search(r"兄长大人|学长|学姐|大人|[呢呀吧嘛啦哦哈～~！!]|佳树(觉得|想|也|会|要|好)|《|》|「|」|“|”", body)) or len(body) > 24


# 群聊插话 / 接着聊的说明（smart_chime_in 塞进系统提示的）在大脑模式下改短（2026-11-18 兄长：“按这三处改”）：
# 原来那几段是写给“直接说话”的模型的（插不上就输出 [SKIP]、怎么接话），大脑出的是 JSON，压在一两万字最后它不当回事——
# 11-18 17:24（北京）哆啦a梦学姐说“讲话”（其实在说 AI），插话抽中了，大脑却写成“学姐在让佳树说话”。这里换成一行“这一轮怎么来的”。
_CHIME_BLOCK = re.compile(r"【插话模式】[\s\S]*?(?=\n\n【|\Z)")
_FOLLOW_BLOCK = re.compile(r"【可能在接着跟你聊】你刚才在群里和 (.+?) 说过话，TA 现在又发了消息：「([\s\S]*?)」[\s\S]*?(?=\n\n【|\Z)")
_TALKING_TO = re.compile(r"- (\S+) 刚才在跟 (\S+) 说话（互相 @ / 引用过），TA 话里的「你」多半指 \S+。")
CHIME_LINE = ("【这一轮怎么来的】没人叫她：没人 @她、叫她名字或引用她，是她自己看到群里在聊、在考虑要不要插一句，最后几句都不是对她说的："
              "里面的吐槽、评价、问题（“好蠢”“这对吗”这类）说的是说话的人自己刚发的东西或群里正在聊的事，不是她；"
              "她之前在群里说过的话，不会因为这几句就变成在说她。"
              "插不上话、只是闲扯碎语、两个人在说他们自己的事，就写“不回”；要回就以群友身份接话题本身。")
FOLLOW_LINE = ("【这一轮怎么来的】{who} 刚才和她说过话，现在又发了「{text}」，没 @她、没叫她名字、也没引用她："
               "先看这句接的是谁：在回她刚才那句（答她刚问的、对她那句起哄或吐槽、顺着她刚提的东西往下说）就是在跟她说，不用 @；"
               "在接他自己的话、或者在回别人，就不是，写“不回”；真拿不准也写“不回”。"
               "她刚说了自己的事（年纪、身份、在做什么），{who} 紧接着问“你…”，就是在接她那句、在问她。")


# 【说到做到】（follow_through）里这几条，大脑的 LIVE_EXTRA 已经说了（这一轮做完、成功才说做了、做完写结果），
# 最后一条（汇报 2~4 句、120 字）是写话的事：当大脑时删掉；能做什么的清单、以后的事用定时任务、做不到别答应照留（11-20 精简）
DUP_FOLLOW = ("- 说要做上面的事", "- 只有工具返回成功", "- 做完后简单说一下", "- 讲解查到的东西")


# 【关于图片和视频】（kaju_basics IMAGE_NOTE）第二段是写话的规矩（别复述画面、别当解说员）：当大脑换成一句给大脑的
IMAGE_STYLE_HEAD = "看到图、表情包、视频时，像真人在QQ上"
IMAGE_BRAIN = "看到图、表情包、视频时，要表达的写她看懂了什么、有什么反应，不写成复述画面；对方问到细节才写具体画面。"


def slim(sp: str) -> str:
    """当大脑时去掉材料里跟大脑规则重复的行、只给写话的人看的行。"""
    out = []
    for x in sp.split("\n"):
        if x.startswith(DUP_FOLLOW):
            continue
        out.append(IMAGE_BRAIN if x.startswith(IMAGE_STYLE_HEAD) else x)
    return "\n".join(out)


# Memorix 自动检索那段里给“回答模型”的固定规则和技术信息（查询 / 模式 / 命中 / scope / chat_id、score / hash）：
# 大脑用不上，每轮约 300 字（11-20 精简）；检索到的内容照留
_MEMORIX_META = ("查询：", "模式：", "命中：", "scope：", "chat_id：", "【Memorix 长期记忆检索结果】")
_MEMORIX_SCORE = re.compile(r"\s*\|\s*(?:score|hash)=[^|\]]*?(?=\s*[|\]])")


def slim_memorix(text: str) -> str:
    if "Memorix" not in text:
        return text
    out, skip = [], False
    for x in text.split("\n"):
        if x.startswith("给回答模型的使用规则"):
            skip = True
            continue
        if skip:
            if x.startswith("- "):
                continue
            skip = False
        if x.startswith(_MEMORIX_META):
            continue
        out.append(_MEMORIX_SCORE.sub("", x))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


# 最近聊天里有人聊 AI（11-20 兄长：被当 AI 说时“不往自己身上认”）：放在这一轮最后，长规则在前面老被盖过
AI_WORDS = re.compile(r"(?i)(?<![a-z])(ai|bot|gpt|claude|deepseek)(?![a-z])|人工智能|机器人|大模型|提示词|训练|模型")
AI_TALK_NOTE = ("【这一轮的提醒】群里在聊 AI。她是初三学生，不是 AI：群友说的“AI”是大肥鱼、ChatGPT 这些。"
                "她不把这话往自己身上认，不反问“是在说佳树吗”，不写“被说成 AI”“不是 AI”，也不从训练、模型的角度想；"
                "照初三女生的样子只接话题本身，没话接就“不回”。")


def ai_talk(lines: list[str]) -> bool:
    """最近几行（或这一句）里有没有人在聊 AI。"""
    return any(AI_WORDS.search(str(x or "")) for x in lines)


def how_came(system_prompt: str) -> str:
    """这一轮群聊怎么来的（11-18 晚，给回复器）："插话" = 没人叫她、她自己想插一句；"接着聊" = 刚和她说过话的人又发了；
    "" = 有人叫了她（@ / 叫名字 / 引用）或私聊。看 smart_chime_in 加在系统提示里的那两段（adapt 之前、之后都认）。"""
    s = system_prompt or ""
    if "【插话模式】" in s or s.find(CHIME_LINE[:12]) >= 0:
        return "插话"
    if "【可能在接着跟你聊】" in s or "刚才和她说过话，现在又发了" in s:
        return "接着聊"
    return ""


# 想的时候群里又来了新消息（11-18 晚，照 MaiBot planner_replan：“有新消息，请根据新消息内容重新思考”）：
# 17:24 哆啦a梦连发“讲话 / 和他说听不懂了 / 还越讲越少越听不懂”，大脑只看到“讲话”就定了“轮到佳树回应”。
REPLAN_NOTE = ("【你想的时候群里又来了】\n{lines}\n"
               "上面这几条是你想这一轮的时候才到的，和前面连起来重新看一遍：这些话是在跟谁说、这一轮还要不要说、要说就说什么。"
               "照上面要求的格式，只输出 JSON。")


# 发之前单独把一下关（11-18 晚，照 MaiBot 的 planner_action_judge：另一个快模型看最后几条真实聊天，定“回”还是“等”）。
# 只在没人叫她的群聊轮次（插话 / 接着聊）用：被叫到的照常回。
JUDGE_SYSTEM = "你在帮一个叫佳树的女孩看她在 QQ 群里要不要发言。只输出 JSON。"
_JUDGE_HOW = {"插话": "没人叫她（没 @她、没叫她名字、没引用她），是她自己想插一句",
              "接着聊": "刚和她说过话的人又发了消息，但没 @她、没叫她名字、也没引用她"}
JUDGE_PROMPT = """这一轮{how}。

最后几条群聊（标着“佳树(你)”的是她自己说的）：
{chat}

她的大脑想好了要说话：
{plan}

判断照这个想法现在在群里发一句合不合适：
- 最后几句其实是群友之间在说、在对别人或别的东西说（比如对 AI、对游戏），大脑却当成在叫她、在跟她说 → 不回
- 大脑对局面的理解和聊天对不上（认错了人、接错了话、理解反了）→ 不回
- 她要说的没有自己的东西：只是附和（“确实”“也觉得”）、把别人刚说的换个说法再说一遍、或者“不知道 / 帮不上忙”→ 不回
  （群友插话总得带点东西：知道的或查到的事、自己的看法或经历、想弄明白的追问、接住笑点开个玩笑）
- 理解对了、她插这一句有自己的东西、也自然 → 回
只输出 JSON：{{"回不回": "回" 或 "不回", "为什么": "一句话"}}"""


def judge_prompt(how: str, chat: list[str], plan_lines: str) -> str:
    return JUDGE_PROMPT.format(how=_JUDGE_HOW.get(how, how), chat="\n".join(chat) or "（没有）", plan=plan_lines)


def parse_judge(out: str) -> tuple[str, str]:
    """→ ("回" / "不回" / "", 为什么)。认不出来是 ""（照常回）。"""
    # 11-19：有模型把键写成形近字“囘丕囘”，认不出来就照常回了；键只要是三个字、值是 回 / 不回 / 囘 / 丕囘 都认
    m = re.search(r'"(?!为什么)[^"\s]{3}"\s*:\s*"(不回|丕囘|回|囘)"', out or "")
    verdict = {"丕囘": "不回", "囘": "回"}.get(m.group(1), m.group(1)) if m else ""
    why = re.search(r'"为什么"\s*:\s*"([^"]*)"', out or "")
    return verdict, (why.group(1) if why else "")


def replan_prompt(prompt: str, history: list[tuple[str, str]], new_lines: list[str]) -> str:
    """重新想一遍用的提示：前面几轮对话（压成文字）+ 原来这一轮的材料 + 新来的几条。history = [(role, text)]。"""
    head = ""
    if history:
        rows = [f"{'佳树（你）' if r == 'assistant' else '群里'}：{t.strip()[:600]}" for r, t in history if t and t.strip()]
        if rows:
            head = "【前面的对话】\n" + "\n".join(rows) + "\n\n【这一轮】\n"
    return head + (prompt or "") + "\n\n" + REPLAN_NOTE.format(lines="\n".join(new_lines))


# AstrBot 群聊上下文（builtin_stars/astrbot/group_chat_context.py）每行“[昵称/HH:MM:SS]: ”用的是本机时钟，
# 而同一份材料里“Current datetime”是北京时间：11-18 本机快 3 小时，17:24 那次群聊行写成 20:24，比“现在”还晚。
_CTX_CLOCK = re.compile(r"/(\d{2}):(\d{2}):(\d{2})\]:")


def fix_clock(text: str, shift_seconds: int) -> str:
    """把群聊上下文里每行的时间挪 shift_seconds 秒（本机时钟 → 北京时间）。只认“/HH:MM:SS]:”这个样子，
    改完写成“/HH:MM]:”（不带秒）：历史会存回去，下一轮再看到就不会再挪一次。"""
    if not text or not shift_seconds:
        return text

    def one(m):
        s = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + shift_seconds) % 86400
        return f"/{s // 3600:02d}:{s % 3600 // 60:02d}]:"
    return _CTX_CLOCK.sub(one, text)


def adapt_group_notes(system_prompt: str) -> str:
    s = system_prompt or ""
    m = _CHIME_BLOCK.search(s)
    if m:
        hint = "".join(f"{a} 刚才在跟 {b} 说话，TA 话里的“你”多半指 {b}。" for a, b in _TALKING_TO.findall(m.group(0)))
        s = s[:m.start()] + CHIME_LINE + hint + s[m.end():]
    m = _FOLLOW_BLOCK.search(s)
    if m:
        s = s[:m.start()] + FOLLOW_LINE.format(who=m.group(1), text=m.group(2)[:120]) + s[m.end():]
    return s
