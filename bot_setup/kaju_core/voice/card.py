"""要点卡（第四版）：大脑的指导解析不了时，Gemini 把主模型的草稿整理成卡，再照卡写（mind.py 摘卡那条退路）。

第一、二版卡（本地 4B 写手时代：从回复抽关键词卡、照卡写）11-20 删了，来龙去脉见 AGENT.md 和 git 历史。
"""

import json
import re


def loads_obj(out: str):
    """模型回的文字里抠出 {…} 解析；中文里夹了英文引号（11-21：局面写成 喊了一声"妈妈"，整张卡作废、她没回）
    就换成中文引号再试一次（和 brain.parse 一样）。解析不了返回 None。"""
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        pass
    try:
        return json.loads(re.sub(r'([一-鿿])"([^"\n,:{}\[\]]{1,30})"(?=[一-鿿，。、！？,])', r"\1“\2”", m.group(0)))
    except ValueError:
        return None


# 第一、二版卡（v1 EXTRACT / v2 EXTRACT_V2(_LIVE)、WRITE_SYSTEM、parse / render / write_prompt / sane / copy_ratio）11-20 删了：
# 4B 线 11-18 已删、线上只剩第四版（大脑解析不了时摘卡），这些没地方用了。

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
    v = loads_obj(out)
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
    v = loads_obj(out)
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


NONE_WORDS = {"", "无", "没有", "无。", "none", "None", "null"}
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


def fix_formal(new: str, draft: str, title: str) -> str:
    """写手爱用"您"（LCCC 带来的习惯，v4 盲选 54 条里 6 条），佳树从不这么叫人 → 换成对方的称呼。草稿本来就有"您"不动。"""
    if not title or "您" not in (new or "") or "您" in (draft or ""):
        return new
    return new.replace("您们", "大家").replace("您", title)
