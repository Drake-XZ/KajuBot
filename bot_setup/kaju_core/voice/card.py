"""要点卡：DeepSeek 只决定"说什么"，本地模型（kaju-writer，v4 起）照卡片决定"怎么说"。

为什么：v3.1 重说层看着 DeepSeek 的整段草稿改，草稿里有现成的句子，小模型最省事的做法就是照抄
（线上 79 条：前 30 字和草稿相似度中位 0.87，"心里暖得不行"这类说法 5 条留下 3 条）。
卡片只留关键词，没有句子可抄。2026-11-06 测过（voice_train\\scripts\\card_test.py）：只看卡片写回，
30 条里 28 条意思完整，原回复 4 字片段在卡上中位只出现 8%。

训练数据（voice_train\\scripts\\build_stage_v4.py）和线上抽卡都用这里的提示词和格式，两边必须一模一样。
场合、对象由代码填（已知），模型只填回哪句 / 情绪 / 态度 / 要点 / 问。
情绪、态度只能从固定词表里挑：测试时自由填写的情绪把"不是滋味""雀跃"带进了卡片，写的人就照着说出来。
抽卡调用 deepseek-flash 时关掉思考（EXTRACT_EXTRA_BODY）：思考每张卡要 1000～2000 token，卡片只有 50 个左右，质量一样。
"""

import json
import re

EMOTIONS = ["开心", "好笑", "害羞", "感动", "期待", "好奇", "得意", "担心", "心疼", "难过",
            "委屈", "生气", "吃醋", "无奈", "惊讶", "累", "困", "平常"]
ATTITUDES = ["回答", "解释", "赞同", "反对", "答应", "拒绝", "撒娇", "道歉", "安慰", "关心",
             "夸", "逗", "吐槽", "分享", "追问", "打招呼", "感谢", "平常"]

EXTRACT = f"""下面是一段聊天和其中一条回复。把这条回复的内容提炼成一张要点卡：别人只看卡片，就能写出意思一样的回复。

要填的：
- reply_to：这条回复在回哪句话，几个关键词；回复没在接前面的话（另起话题、新的一天打招呼）就写"无"
- emotion：说话人此刻的感受，从这些词里挑 1～2 个：{"、".join(EMOTIONS)}
- attitude：回复的态度，从这些词里挑 1～2 个：{"、".join(ATTITUDES)}
- points：回复说了的内容，按原来的顺序，一条一项：事实、答案、看法、理由、要做的事、提到的人和东西
- ask：回复里问了对方什么（关键词），没问就写"无"
- to：回复是说给谁的（称呼或名字），看不出来写"无"

points 的规矩：
- 只写"说什么"，不写"怎么说"：每项是几个关键词或很短的短语，不写成句子，去掉语气词、无关的招呼或修饰性称呼、修饰和比喻，不照抄原回复的说法；保留主体和动作对象所需的名字或称呼
- 每项写清是谁的事：用聊天里的名字或称呼开头（"兄长先去睡""佳树守着""建议兄长先煮粥""兄长一个人回公寓"），
  叫对方做的事写成"让兄长…""建议学姐…"，别只写一个动作——不然别人会以为是说话人自己要做；不要写"我""你""对方"
- emotion 记录感受类别；针对具体人或事的感受、担心、想念、愿望和打算也要在 points 写清对象与内容，
  如"佳树担心兄长吃不惯""佳树想和兄长旅行"。别只写"心里暖""不是滋味"等含糊说法
- 回复里的猜测、看法要写清是说话人的判断；有不确定性的猜测保留不确定性，不能写成已经发生的事实
- 具体的东西要留全：人名、作品名、数字、时间、地点、答应的事、理由
- 只记事情本身，不记描写：画面、样子、形容（"两块肉叠得老高""平时穿得那么随便""眼睛都瞪大了""笑得停不下来"）不写进 points，
  除非对方问的正是这个；说话人的反应有多强烈交给 emotion，不写成要点
- 但对对方的回应本身要留：被夸、被关心、被道歉、被逗时那一下的表态（"佳树被兄长夸了很开心""佳树答应听兄长的"）写成要点，
  只是去掉形容它有多强烈的说法（"尾巴都要翘起来"）
- 回复里问对方的话一定写进 ask，不能丢，也不能改成说话人自己的判断；问了几件就写几件
- 含糊的指代（"那首歌""那句话""被人说……""那件事"）：上下文里能看出具体是什么，就写具体的（歌名、谁说了什么）；
  看不出来就整项不写，不要原样留着让别人照抄
- 必须原样说出来的（歌词、书里的原句、对方要求复述的话）用「」括起来，其他一律改写成关键词
- 客套、语气、重复的话不算内容；回复只是简单应答（嗯、好、哈哈）时 points 可以只有一项
- 越短越好，但该有的内容一项都不能少

只输出 JSON：{{"reply_to": "…", "emotion": ["…"], "attitude": ["…"], "points": ["…", "…"], "ask": "…", "to": "…"}}"""

# ---------------------------------------------------------------------- 第二版卡片（2026-11-09，要点卡改进方案第二步）
# 第一版的毛病（第六批 63 条改写 + ab6 盲选 30 条的备注）：要点拆成互不相干的关键词，写手乱补"而且""反而"、乱安主语
# （"佳树和兄长大人共享账号"）；每条都用"佳树…"开头，写手照抄转述腔；回复要用的来龙去脉写手看不到（"很烦"其实是练推胸）。
# 格式（两份一样）：一项里留"但/因为/所以"；说话人自己的事不写主语；加 background。
# 训练抽卡（EXTRACT_V2，从真人的回复抽）必须一项不漏：卡上少了回复里的事，写手就学会自己编。
# 从草稿抽（EXTRACT_V2_LIVE，线上 + K 层原作对齐卡）才挑：不讲表情包画面、不复述对方、去掉没依据的经历和硬加的关心。
# ab6 盲选里"最多 3 条"把兄长想留的感受和追问也切掉了（旧卡 14:3 赢），所以这里不限条数。

_V2_FIELDS = f"""要填的：
- reply_to：这条回复在回哪句话，几个关键词；回复没在接前面的话（另起话题、新的一天打招呼）就写"无"
- emotion：说话人此刻的感受，从这些词里挑 1～2 个：{"、".join(EMOTIONS)}
- attitude：回复的态度，从这些词里挑{{attitude}}：{"、".join(ATTITUDES)}
- background：只在回复说到的东西聊天里完全没出现时才写（比如对方只说了"很烦"，回复却在说他练推胸练到胳膊抖），一句话写清是什么；
  聊天里出现过的、从聊天能看出来的、只是把聊天再总结一遍的，都写"无"——大多数卡都是"无"
- points：回复要说的内容，按说的顺序，一项一件事：事实、答案、看法、理由、要做的事、提到的人和东西
- ask：回复里问了对方什么（关键词），{{ask}}；没问就写"无"
- to：回复是说给谁的（称呼或名字），看不出来写"无\""""

_V2_POINTS = """points 的写法：
- 只写"说什么"，不写"怎么说"：每项是关键词或很短的短语，去掉语气词、招呼、修饰性称呼、修饰和比喻，不照抄原话的说法
- 一件事里的转折、因果、让步要留着，用"但""因为""所以""不过""可能"连在同一项里（"想去，但今天没空""因为下雨，改天再去"）；
  不要把一句话拆成互不相干的几项，也不要把不相干的事硬连起来
- 说话人自己的事不写主语（"去刷一会儿""有点委屈""谢兄长帮忙领""猜是早年挂上去的老号"）；
  别人的事用聊天里的名字或称呼开头（"兄长先去睡""女王大人这两天折腾"）；叫对方做的事写成"让兄长…""建议学姐…"；
  一般的道理、东西本身的情况就写它（"共享号容易互相踢下线"）；不要写"我""你""对方"
- 同一个意思只写一项
- 针对具体人或事的感受、担心、想念、愿望和打算写清对象和内容（"担心兄长吃不惯""想和兄长旅行"），别只写"心里暖""不是滋味"
- 猜测、看法写清是判断，不确定的保留"可能""猜"，不能写成已经发生的事
- 具体的东西要留全：人名、作品名、数字、时间、地点、答应的事、理由
- 只记事情本身，不记描写：画面、样子、形容不写进 points，除非对方问的正是这个；反应有多强烈交给 emotion
- 被夸、被关心、被道歉、被逗时那一下的表态写成要点（"被兄长夸了很开心""答应听兄长的"），去掉形容它有多强烈的说法
- 含糊的指代（"那首歌""那件事"）：上下文看得出是什么就写具体的，看不出来就整项不写
- 必须原样说出来的（歌词、书里的原句、对方要求复述的话）用「」括起来，其他一律改写成关键词
- 客套、语气、重复的话不算内容；简单应答（嗯、好、哈哈）points 只写一项"""

_V2_JSON = """只输出 JSON：{"reply_to": "…", "emotion": ["…"], "attitude": ["…"], "background": "…", "points": ["…", "…"], "ask": "…", "to": "…"}"""

EXTRACT_V2 = ("下面是一段聊天和其中一条回复。把这条回复的内容提炼成一张要点卡：别人只看卡片，就能写出意思一样的回复。\n\n"
              + _V2_FIELDS.format(attitude=" 1～2 个", ask="问了几件就写几件") + "\n\n" + _V2_POINTS
              + "\n- 回复里说了的事一项都不能少，没说的一项都不能加\n\n" + _V2_JSON)

EXTRACT_V2_LIVE = (
    "下面是一段聊天和一份回复草稿。草稿是别人替说话人先写的，常常写得太满或带毛病。"
    "把它提炼成一张要点卡：别人只看卡片，就能写出一条真人会发的回复——留下草稿里该说的，去掉不该说的。\n\n"
    + _V2_FIELDS.format(attitude=" 1 个，确实有两种不同的态度才写 2 个", ask="连问好几个时只留最想问的一两个") + "\n\n"
    + """哪些不写进卡：
- 描述对方发的表情包、图片、视频画面的话（除非对方问的就是画面里有什么）；对方只发了表情，就当他的态度（[赞]是夸，笑哭是好笑），写进 reply_to
- 把对方刚说过的事、对方自己的处境复述一遍的话（对方说累了，草稿又把他为什么累讲一遍）：只留说话人对这件事的回应
- 和前面重复的意思
- 说话人自己的经历、近况、做过的事（"查过""翻看后发现""明天要交海报""贴在冰箱上了"），聊天和 background 里看不出依据的
- 结尾附带的关心、叮嘱、撒娇（"别熬太晚""记得吃饭"），前面的话里没有由头（对方没说累、晚、病、难过）的
哪些一定要留：
- 对方问的、要她回应的（问题、请求、夸、关心、道歉、玩笑），以及说话人对它的感受和反应
- 草稿里说话人自己的想法、打算和想问的

""" + _V2_POINTS + "\n\n" + _V2_JSON)

# 本地模型的系统提示（和 kaju_train_kit\scripts\train_lora.py 的 SYSTEM 一字不差；test_card 会对一遍）
WRITE_SYSTEM = {
    1: ("你是写手：照要点卡写出真人在聊天里会发的回复。忠实表达卡上的要点，不编造已经发生的事、做过的事或别人说过的话；"
        "可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。长短、用词、语气像真人随手打的字。只输出回复。"),
    2: ("你是写手：照要点卡写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。忠实表达卡上的要点，"
        "不编造已经发生的事、做过的事或别人说过的话；可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。"
        "自称佳树，按场合自然使用对象的称呼，不说\"你\"；像她平时说话，也像真人随手打的字。只输出回复。"),
}

EXTRACT_EXTRA_BODY = {"thinking": {"type": "disabled"}}

# ---------------------------------------------------------------------- 第四版卡（2026-11-12，新写手 kaju-writer-p4-8b-k 上线）
# 训练包 voice_train\train_pack\kaju_train_pack（train.py 的 prompt_of、data\system.json 的 "2"）：
#   用户消息 "聊天：\n…\n\n材料：\n场合 / 对象 / 局面 / 要说到的 [/ 心情]"，没有"长短"。两边必须一字不差（test_card 会对一遍）。
# 线上：DeepSeek 照旧写草稿（记忆、工具、关于自己都在它那边），Gemini 把草稿整理成卡（决定 14，不再用 DeepSeek 抽卡）。
# 和训练卡（build_guide_v3 对着真话倒着写）比，两处按兄长 ab11 盲选改了（都 5:1 赢）：
#   - “要说到的”不留空：没有事实时写她怎么接住这一句（ab10 里"无"卡 2:3 输——K 层"无"卡大多是原作台词，写手学成了随口说小说腔）；
#   - 看完东西的感受写进事实里、不用括号（括号里的感受词写手会原样念出来）。
SYSTEM_V4 = ("你是写手：看着聊天和局面，写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。“要说到的”里的事都要说到、不能说错；"
             "除此之外不编造已经发生的事、做过的事或别人说过的话。怎么接话、说不说自己的感受、怎么说，都由你定。"
             "自称佳树，按场合自然使用对象的称呼，不说\"你\"；像她平时说话，也像真人随手打的字。只输出回复。")

# 第 7 轮起（2026-11-17 兄长：说“你”贴近原作，偶尔说可以）：去掉“不说你”。和写手一起换：rewrite.writer_system = "v5"
# （训练包 system.json 的 "2" 要和它一字不差；r6 及以前是 SYSTEM_V4）。
SYSTEM_V5 = ("你是写手：看着聊天和局面，写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。“要说到的”里的事都要说到、不能说错；"
             "除此之外不编造已经发生的事、做过的事或别人说过的话。怎么接话、说不说自己的感受、怎么说，都由你定。"
             "自称佳树，按场合自然使用对象的称呼；像她平时说话，也像真人随手打的字。只输出回复。")

EXTRACT_V4 = """下面是一段聊天，和别人替佳树先写好的一份回复草稿（草稿常常写得太满、带毛病）。
请整理成交给佳树的材料：她只看聊天和这份材料，自己把话说出来。材料里只有要说的事，没有现成的句子。只输出 JSON：
{"局面": "...", "要说到的": ["..."]}

局面：一两句话，只根据聊天写，不许用草稿里才有的信息。聊到哪了、最后这句是谁对谁说的、接的是前面哪句，最后写“轮到佳树回。”
  不写佳树接下来说什么、该怎么回、什么情绪、什么语气。最后一句里有“那个”“他”“你说的”这种指代，聊天里看得出指的是什么，顺手点明。

要说到的：佳树这一回要说出来的事，按草稿说的顺序，一条一件、一个十来个字的短事实：
  - 外面的事实和知识（是什么、怎么做、名字、数字、时间、地点）；佳树自己的事、打算、决定；对是非问题答的是“是”还是“不是”。
  - 佳树怎么接住对方这一句：答应、同意、拒绝、道谢、看不懂、问对方什么（“佳树答应陪兄长大人聊轻松的”“佳树问学姐是不是打错字了”）。
  - 看完视频、听完歌的感想：事实和感受写在同一条里，用平常说话的词，不用括号（“仙人掌亮灯扭着学说话，又魔性又好笑”）。
  至少写一条，不能是空的。
  下面这些不写进去：描述对方发的表情包、图片画面的话（除非对方问的就是画面）；把对方刚说过的事复述一遍；和前面重复的意思；
  聊天里看不出依据的佳树自己的经历（“查过”“已经贴在冰箱上了”）；结尾没有由头的关心叮嘱（对方没说累、晚、病，草稿却叮嘱早点睡）。
  用概括的说法，不照抄草稿的句子，不写语气词。提到她自己写“佳树”，不写“我”；别人用聊天里的称呼，兄长大人只在他真在这段聊天里时才写；不写“你”“对方”。"""


def extract_prompt_v4(ctx: list[str], draft: str, kind: str, to: str, felt: bool = False) -> str:
    """给 Gemini 出卡的用户消息。felt：这一轮她刚看完 / 听完东西（草稿里的感想照第三类写）。"""
    note = "\n（这一轮佳树刚看完、听完对方发的东西，草稿里的感想照“看完的感想”那一类写。）" if felt else ""
    return (f"场合：{kind}\n佳树在回的人：{to or '无'}\n\n聊天：\n" + ("\n".join(ctx) if ctx else "（没有前文）")
            + f"\n\n草稿：\n{(draft or '').strip()}{note}")


RECHECK_V4 = """
—— 这是第二次整理 ——
上一份材料交给佳树后，她照着写出的话两次被核对拦下（核对拿草稿比，草稿为准）。
上一份材料：
{old}
佳树照它写出的话：{new}
核对说的问题：{why}

先逐条对着草稿查上一份材料里的每条“要说到的”：在草稿里找出说这件事的原句，抄下来；找不到、或者原句的意思和这条不一样（比如草稿是叮嘱对方，这条却成了佳树自己的事），这条就是错的。
核对也可能看错，一切以草稿为准：有原句、意思一样的条目照留，不要因为核对的话删掉草稿里本来有的事。
只输出 JSON：
{{"逐条": [{{"条": "上一份材料里的一条", "草稿原句": "草稿里说这件事的原句，没有就写“没有”", "对不对": "对" 或 "错"}}],
 "局面": "...", "要说到的": ["..."]}}
有一条错：“局面”“要说到的”按最上面的要求重新整理（错的那条改对或去掉）。
条条都对（是佳树自己写的时候多说了、说错了）：“局面”“要说到的”照抄上一份材料。"""


def recheck_prompt_v4(ctx: list[str], draft: str, kind: str, to: str, card_text: str, new: str, why: str,
                      felt: bool = False) -> str:
    """带着核对的问题回去重新出卡（2026-11-13：卡把“午饭要好好吃哦”抽成“佳树吃过午饭了”，同一张卡写 4 遍都被拦）。
    上一份材料只给局面和要说到的（心情行是写手用的，和出卡无关）。"""
    old = "\n".join(x for x in (card_text or "").splitlines() if x.startswith(("局面：", "要说到的：")))
    return (extract_prompt_v4(ctx, draft, kind, to, felt)
            + RECHECK_V4.format(old=old or "（无）", new=(new or "").strip(), why=(why or "").strip() or "（没说）"))


def parse_recheck_v4(out: str) -> tuple[str, dict | None]:
    """重新出卡的回答 → ("new", guide) 有一条错、给了新卡 / ("keep", None) 条条都对 / ("bad", None) 看不懂。
    （先前只问“材料有没有错”，Gemini 三条都答没错，连把叮嘱抽成“佳树吃过午饭了”的那张也是，所以改成逐条找草稿原句。）"""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        v = None
    if not isinstance(v, dict):
        return "bad", None
    rows = v.get("逐条")
    if not isinstance(rows, list) or not rows:
        return "bad", None
    wrong = any(isinstance(r, dict) and (str(r.get("对不对", "")).strip() == "错"
                                         or str(r.get("草稿原句", "")).strip() in ("", "没有", "无"))
                for r in rows)
    if not wrong:
        return "keep", None
    g = parse_v4(json.dumps({"局面": v.get("局面"), "要说到的": v.get("要说到的")}, ensure_ascii=False))
    return ("new", g) if g else ("bad", None)


def parse_v4(out: str) -> dict | None:
    """Gemini 的 JSON → {"局面", "要说到的"}；局面空或要说到的空都算没出好（返回 None）。"""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(v, dict) or not str(v.get("局面") or "").strip():
        return None
    pts = v.get("要说到的")
    if isinstance(pts, str):
        pts = re.split(r"[；;\n]+", pts)
    pts = [re.sub(r"\s+", " ", str(x)).strip().rstrip("。；;") for x in (pts or [])]
    pts = [p for p in pts if p and p not in NONE_WORDS]
    if not pts:
        return None
    return {"局面": re.sub(r"\s+", " ", str(v["局面"])).strip(), "要说到的": pts}


def render_v4(kind: str, to: str, guide: dict, mood: str = "") -> str:
    """给写手看的材料（和训练包 make_train_pack.py 拼的一样：没有长短；心情那一行有读数才加，放最后）。"""
    lines = [f"场合：{kind}", f"对象：{to or '无'}", f"局面：{guide['局面']}",
             "要说到的：" + ("；".join(guide.get("要说到的") or []) or "无")]
    if mood:
        lines.append(mood)
    return "\n".join(lines)


def write_prompt_v4(ctx: list[str], card_text: str) -> str:
    """写手的用户消息，和 train.py 的 prompt_of 一字不差。"""
    return "聊天：\n" + ("\n".join(ctx) if ctx else "（没有前文）") + "\n\n材料：\n" + card_text


LEAK_V4 = re.compile(r"^(场合|对象|局面|要说到的|心情|材料|聊天)：|要说到的：", re.M)


def loops(text: str, n: int = 6, times: int = 3) -> bool:
    """写手卡死在打转：同一段（n 字以上）出现 times 次以上，或同一行（n 字以上）出现两次。
    只用来判这一遍不算写好、扔掉重写，不改她的字（2026-11-12 试过：1.0 下 80 句里 2 句打转，都被抓到，没有误判）。"""
    t = re.sub(r"\s", "", text or "")
    lines = [x.strip() for x in (text or "").split("\n") if len(x.strip()) >= n]
    if len(lines) != len(set(lines)):
        return True
    seen = {}
    for i in range(0, max(0, len(t) - n + 1)):
        g = t[i:i + n]
        seen[g] = seen.get(g, 0) + 1
        if seen[g] >= times:
            return True
    return False


def sane_v4(new: str, card_text: str, draft: str = "") -> bool:
    """第四版：空的、漏出材料格式、写出卡和草稿里都没有的繁体字、打转，都不算写好。不按字数卡长短（兄长：不要强行限制她的字数）。"""
    if not (new or "").strip() or LEAK_V4.search(new) or trad_chars(new, (card_text or "") + (draft or "")):
        return False
    return not loops(new)

NONE_WORDS = {"", "无", "没有", "无。", "none", "None", "null"}


def extract_prompt(ctx: list[str], reply: str, kind: str = "", to: str = "") -> str:
    """User message for the extractor. ctx = labeled lines ("兄长大人：…"), reply = the text to boil down."""
    head = f"【聊天】（{kind}）\n" if kind else "【聊天】\n"
    who = f"（回给{to}）" if to else ""
    return head + ("\n".join(ctx) if ctx else "（没有前文）") + f"\n\n【回复】{who}\n{reply.strip()}"


def _words(v, allowed: list[str]) -> list[str]:
    items = v if isinstance(v, list) else re.split(r"[、，,；;/\s]+", str(v or ""))
    out = []
    for w in items:
        w = str(w).strip()
        if w in allowed and w not in out:
            out.append(w)
    return out[:2] or ["平常"]


def _text(v) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip().strip("。")
    return "" if s in NONE_WORDS else s


def parse(out: str) -> dict | None:
    """The extractor's JSON → normalized dict, or None if unusable."""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(j, dict):
        return None
    pts = j.get("points")
    if isinstance(pts, str):
        pts = re.split(r"[；;\n]+", pts)
    pts = [p for p in (_text(x) for x in (pts or [])) if p]
    if not pts:
        return None
    res = {"reply_to": _text(j.get("reply_to")), "emotion": _words(j.get("emotion"), EMOTIONS),
           "attitude": _words(j.get("attitude"), ATTITUDES), "points": pts,
           "ask": _text(j.get("ask")), "to": _text(j.get("to"))}
    if _text(j.get("background")):  # 第二版卡片才有；没有就不出这一栏，第一版卡片渲染出来一字不变
        res["background"] = _text(j.get("background"))
    return res


def render(c: dict, kind: str, to: str = "") -> str:
    """Card text the writer model sees. kind = 私聊 / 群聊 / 说说 / 当面 / 聊天; to overrides the extractor's guess."""
    lines = [f"场合：{kind}", f"对象：{to or c.get('to') or '无'}"]
    if c.get("reply_to"):
        lines.append(f"回哪句：{c['reply_to']}")
    lines += [f"情绪：{'、'.join(c['emotion'])}", f"态度：{'、'.join(c['attitude'])}"]
    if c.get("background"):
        lines.append(f"背景：{c['background']}")
    lines += [f"要点：{'；'.join(c['points'])}", f"问：{c.get('ask') or '无'}"]
    return "\n".join(lines)


def write_prompt(ctx: list[str], card_text: str) -> str:
    """User message for the writer model (training and live)."""
    return "上下文：\n" + ("\n".join(ctx) if ctx else "（没有前文）") + "\n\n要点卡：\n" + card_text


LEAK = re.compile(r"要点卡|^(场合|对象|回哪句|情绪|态度|背景|要点|问)：|上下文：", re.M)


# 只在繁体里出现的常用字（简体不用）。写手偶尔冒出繁体（2026-11-09 "今天也要上課"）：
# 原稿/卡片里没有、写手自己写出来的 → 这一遍不算写好（不替她改字，交给"再写一次 / 发原稿"）
TRAD = set(
    "這個們說話時會來對還沒為麼樣嗎學開關點錢見讓給過現間問題聽覺東車長門電腦書寫買賣從後裡帶頭謝愛歡樂媽爺歲氣體實應當經"
    "網線號機發認識記讀練習鐘夢雙邊遠進選運達課週準備場決參與壓壞歷總變權風飛馬魚鳥龍麵飯飲館憶聲臉帳團園圖幾兩亂產價優傳"
    "傷僅兒內劃劇動務勝勢區協單卻員喚嚇嚴國圍圓執堅報塊夠夥奪奮嬌孫寧寶寵審寬導將專尋屬島幣幫幹廣廠廢廳彈彎徑徹戀戰戲戶"
    "擁擇擊擔據擴擺攜敗敵數斷晝曉暫曆朧條棄楊業極構槍標檢歐歸殺毀漢潔濟灣無熱爭爾牆獎獨獲環畫療盡盤眾睏礙禮禱稱種穩窮"
    "競筆節範簡糧紀約紅級細終組結絕絲綠維緊練縣繼續纏罰羅職聯聖肅腳興舉舊艱藝蘋蘭處蟲術衛裝補複視親觀計訂討訓託訪設許訴"
    "診詞試詩該詳語誤請諸調談論諾謎護豐貓貝負財貧貨販貴費貼賀資賓賞質購賽趕趙跡踐蹤軌軍軟較載輕輛輩輪輸辦農迴連遊違遞適遺"
    "郵鄉醫釋針鈕鉛銀銷鋼錄錯鍵鍋鏡鐵閃閉閒閱陽階際陳陸隊隨險隱隻雖雜雞離難電霧靈靜韓頁項順須預頓額顏願類顯餅養餓駕騎"
    "驗驚鬆鬧鮮鴨鹽麥黃黨齊齒")


def trad_chars(new: str, ref: str = "") -> str:
    """写手写出来、ref（原稿/卡片）里没有的繁体字。"""
    return "".join(sorted({ch for ch in new or "" if ch in TRAD and ch not in (ref or "")}))


def sane(new: str, draft: str) -> bool:
    """Throw away output that isn't a reply: leaked card format, empty, runaway length, 写出了原稿没有的繁体字."""
    if not (new or "").strip() or LEAK.search(new) or trad_chars(new, draft):
        return False
    return len(new) <= len(draft or "") * 2.5 + 40


def fix_formal(new: str, draft: str, title: str) -> str:
    """写手爱用"您"（LCCC 带来的习惯，v4 盲选 54 条里 6 条），佳树从不这么叫人 → 换成对方的称呼。草稿本来就有"您"不动。"""
    if not title or "您" not in (new or "") or "您" in (draft or ""):
        return new
    return new.replace("您们", "大家").replace("您", title)


def copy_ratio(reply: str, card_text: str) -> float:
    """Share of the reply's 4-char pieces that sit verbatim in the card's 要点/回哪句 (high = the writer could just copy)."""
    body = "".join(ln for ln in card_text.split("\n") if ln.startswith(("要点：", "回哪句：", "问：")))
    quoted = re.findall(r"「([^」]*)」", body)  # 原样要说的话本来就该照抄，不算
    body = re.sub(r"\s|「[^」]*」", "", body)
    r = re.sub(r"\s|&&[^&]*&&", "", reply or "")
    for q in quoted:
        r = r.replace(re.sub(r"\s", "", q), "|")
    grams = {r[i:i + 4] for i in range(len(r) - 3) if "|" not in r[i:i + 4]}
    return sum(g in body for g in grams) / len(grams) if grams else 0.0
