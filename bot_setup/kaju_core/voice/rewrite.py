"""写她的话这一层的公用零件：表情标签、上下文行的格式、核对（GUARD）和改错（REPAIR）、清理模型输出。

她的话由回复器（replyer.py）照大脑的指导写。它偶尔会编出指导里没有的事，所以写完再核对一遍：
编了事、丢了要紧的信息、叫错了人 → 再写一遍（mind.py）。
（2026-11-13 删掉了看草稿改写的旧 kaju-rewriter 模式；11-21 删掉了第四版要点卡和本地写手。）
"""

import json
import re

MEME_TAG = re.compile(r"&&[^&\n]*&&")
REMIND = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)
QUOTE = re.compile(r"<Quoted Message>\s*(?:\((.*?)\):\s*)?(.*?)\n?</Quoted Message>", re.S)
SPEAKER = re.compile(r"^\[发言人：([^，\]]*)，QQ (\d+)\]\s*")
SKIP = re.compile(r"```|https?://|www\.|\[SKIP")

# 兄长大人第三轮标注（2026-11-04）：他想要的佳树会自己添一句心情或对他的感情（"佳树也想兄长大人了呢""佳树相信兄长大人"），
# 旧核对把这些全当"加了草稿没有的事"拦下 → 这类放行，新的事实、事件、决定和变了的看法照样拦。
GUARD = """比较同一条聊天回复的草稿和改写。
改写可以：删掉客套、重复、多余的追问和语气词；变短、换说法；开头加一句应答（"好的兄长大人""真的嘛！"）；
加一两句佳树自己的心情或对对方的感情（开心、害羞、想念、心疼、累、撒娇、"佳树也爱兄长大人""佳树相信兄长大人"）；
把"你"换成对方的称呼；顺着对方刚说的话应一句（对方说"假先别请"→"那佳树不请假了"，对方夸她的汤→"给兄长大人煮"）。这些都不算错。
只判断改写有没有：
- 说错事实或改变意思，包括把她的看法、建议、决定改成别的（比如"建议放开心类"变成"已经放进开心类"，"不服气"变成"认同"）
- 加了草稿里没有的事实、经历、细节，或者她新答应要做的事
- 删掉了回应对方必需的信息（对方问的答案、对方纠正的内容、对方要的建议、她答应要做的事）
- 叫错人或把对象弄错（比如把某位学长叫成兄长大人；只是提到兄长大人不算）
- 草稿里已经做完、查到了的事，改写却说成还要去做（草稿给了查到的结果，改写开头又说“这就去查”“马上去看”）
- 编了她自己的经历：草稿里没有的“佳树试过 / 用过 / 去过 / 看过 / 以前做过 / 自己体会过”（11-20：草稿只说“这是通病”，改写加了“佳树也是之前自己试过才知道的”）
只输出 JSON：{"bad": true/false, "what": "≤20字"}"""


def split_tags(text: str) -> tuple[str, list[str]]:
    """The reply without &&tag&& stickers, and the tags (they go back at the end)."""
    return MEME_TAG.sub("", text or "").strip(), MEME_TAG.findall(text or "")


def with_tags(text: str, tags: list[str]) -> str:
    return text.rstrip() + ("\n" + "".join(tags) if tags else "")


def skip_reason(draft: str, max_chars: int) -> str:
    """Why this draft should go out as it is ('' = rewrite it)."""
    if not draft.strip():
        return "空"
    if SKIP.search(draft):
        return "带代码/链接/SKIP"
    if len(draft) > max_chars:
        return "太长"
    if len(re.findall(r"[\u4e00-\u9fff]", draft)) < len(draft) * 0.3:
        return "中文太少"
    return ""


def label(role: str, content: str, title_of) -> str:
    """One context line the way the training data had it: "佳树：…" / "兄长大人：…" / "八奈见学姐：…"."""
    t = REMIND.sub("", content or "").strip()
    t = QUOTE.sub(lambda q: f"（引用{q.group(1) or '身份不明'}：{q.group(2).strip()[:40]}）", t)
    if role == "assistant":
        return "佳树：" + MEME_TAG.sub("", t).replace("\n", " / ")[:120]
    m = SPEAKER.match(t)
    if m:
        name, qq, t = m.group(1), m.group(2), t[m.end():]
        who = title_of(qq, name) or name or "身份不明"
    else:
        who = title_of("", "") or "兄长大人"
    return f"{who}：" + t.replace("\n", " / ")[:120]


# 混进聊天历史的系统文字：定时任务的指令、"Output your last task result"、[系统记录]、时间戳、发言人标记。
# 写手训练时从没见过这些（2026-11-09 第六批标注：144 条线上记录里 30 多条带着），线上和训练要对齐。
SYS_LINE = re.compile(r"\[CronJob\]|^Output your last task result|^\[系统记录\]")
SPEAKER_ANY = re.compile(r"\[发言人：[^\]]*\]\s*")
REMIND_OPEN = re.compile(r"<system_reminder>.*$", re.S)  # 被截断、没有结尾标签的


def tidy_ctx(lines: list[str]) -> list[str]:
    """上下文行（"称呼：话"）去掉系统文字和空行；整行都是系统文字的去掉。"""
    out = []
    for ln in lines or []:
        who, sep, x = str(ln).partition("：")
        if not sep:
            who, x = "", who
        x = REMIND_OPEN.sub("", REMIND.sub("", x))
        x = SPEAKER_ANY.sub("", x)
        x = re.sub(r"(?:\s*/\s*){2,}", " / ", x).strip().strip("/").strip()
        if not x or SYS_LINE.search(x):
            continue
        out.append(f"{who}：{x}" if sep else x)
    return out


def clean_output(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    lines = (re.sub(r"^佳树[：:]\s*", "", ln.strip()) for ln in text.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def needs_title_guard(new: str, title: str, kind: str) -> bool:
    """提到兄长时，非兄长的对象需要结合上下文区分提及和错称。"""
    return bool("兄长大人" in new and title != "兄长大人" and (title or kind == "群聊"))


REPAIR = """下面是佳树要发出去的一条聊天回复，核对发现了一处问题。请只改有问题的那一处，让它和草稿的意思一致；
其余每个字都照抄，不润色、不加新内容、不删别的内容、不改语气。草稿只用来对照意思，不要照搬草稿的句子。
只输出改好的整条回复（多行就照原样分行）。实在改不了，只输出：[无法修改]"""


def repair_prompt(said: str, draft: str, new: str, why: str, title: str = "") -> str:
    """核对几遍都没过时，交给核对用的模型只改那一处（2026-11-15）。"""
    who = f"佳树这句是回给「{title}」的。\n\n" if title else ""
    return (f"{who}对方刚说：{said[-200:]}\n\n草稿（意思以它为准）：\n{draft}\n\n"
            f"佳树要发的话：\n{new}\n\n核对说的问题：{why}")


def small_edit(old: str, new: str, min_ratio: float = 0.7) -> bool:
    """改错只能小改：和原来那句的相似度不低于 min_ratio（防止它整句重写成草稿那样）。"""
    import difflib
    a, b = "".join((old or "").split()), "".join((new or "").split())
    if not (a and b) or not (len(a) * 0.7 - 4 <= len(b) <= len(a) * 1.3 + 4):  # 长短也不能差太多（不许添一大段）
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= min_ratio


def guard_prompt(said: str, draft: str, new: str, title: str = "", ctx: list[str] | None = None, known: str = "") -> str:
    """ctx = the same labeled lines the rewriter saw — without them, things said a few lines up look invented.
    known = 规划器从记忆 / 材料里整理出的事，写手说到不算新加的（离线回放脚本用；线上“规划器出卡”11-18 删了，不传）。"""
    who = (f"佳树这句是回给「{title}」的" + ("（私聊里就是她哥哥本人）" if title == "兄长大人" else "")
           + f"，用「{title}」称呼对方是对的；回复里提到或夸别人时用那个人的称呼也是对的。\n\n") if title else ""
    before = ("前面的聊天（这里出现过的事不算新加的）：\n" + "\n".join(ctx[-6:]) + "\n\n") if ctx else ""
    op = added_opener(new, draft)
    rule = ("\n\n" + OPENER_RULE.format(op=op)) if op else ""
    extra = (f"\n\n她确实知道的事（从记忆和材料里整理的，改写说到这些不算新加的）：\n{known}") if known else ""
    return f"{who}{before}对方刚说：{said[-200:]}\n\n草稿：\n{draft}{extra}\n\n改写：\n{new}{rule}"


# 开头的应答（"好的兄长大人！""真的嘛！""是的呢哆啦a梦学姐，"）：v3.1 放开以后偶尔用错场合
# （对方只问"咋了"也先答"好的兄长大人！"）。兄长大人 2026-11-04 说直接加回限制 → 改写新加的开头让核对顺便看场合，
# 不合适就只去掉开头，其余照发。
OPENER = re.compile(r"^(好的|真的嘛|是的呢)((?:兄长大人|[^\s，,！!/\n]{1,6}?(?:学长|学姐|大人))?)([！!，,~～]+\s*|\s+|$)")
OPENER_RULE = ("改写开头加了「{op}」，草稿里没有。另外判断这个开头合不合场合："
               "「好的」只在对方让佳树做事、请她帮忙、和她说定一件事时用；"
               "「真的嘛」只在对方夸她、说了让她高兴或惊喜的话时用；"
               "「是的呢」只在对方说对了、她认同对方的话时用。"
               "别的时候（对方在问问题、闲聊、诉苦、问她咋了）都不合适。"
               "JSON 里再加一项 \"opener\": true/false（合场合是 true）。")


def added_opener(new: str, draft: str) -> str:
    """The opener the rewrite put in front that the draft didn't start with ('' if none)."""
    m = OPENER.match(new or "")
    if not m:
        return ""
    if (draft or "").lstrip().startswith(m.group(1)):  # 草稿本来就这么开头（"好的呀"也算）
        return ""
    return m.group(0).strip()


def strip_opener(new: str) -> str:
    """Drop the leading opener; keep it if almost nothing would be left."""
    rest = OPENER.sub("", new, count=1).lstrip("\n，, ")
    return rest if len(re.sub(r"[\s，。！？、～…,.!?~]", "", rest)) >= 4 else new


def guard_opener_ok(out: str) -> bool:
    """The guard's "opener" verdict; missing or unreadable → keep the opener."""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except ValueError:
        return True
    return not (isinstance(j, dict) and j.get("opener") is False)


def guard_bad(out: str) -> tuple[bool, str]:
    """(bad?, why) from the guard model's JSON; unreadable → treat as bad (send the draft)."""
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else None
    except ValueError:
        j = None
    if not isinstance(j, dict) or not isinstance(j.get("bad"), bool):
        return True, "核对结果读不懂"
    return j["bad"], str(j.get("what") or "")
