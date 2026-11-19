"""被纠正提醒：对方在纠正/反驳她刚说的话时，提醒她先接住对方的意思，别再沿用原来的说法。

2026-10-30 的私聊：兄长大人引用她那句「被蹭成那样，老师也真好脾气」，连着纠正了两次
（老师怎么会生气、妃咲是在亲老师），她每次都照着自己那句的句式，把"老师在忍着"的意思又写了一遍。
被引用的原话会原样放进这一轮输入，模型很容易顺着抄。

- 对方引用了她的话，并且带"不是/怎么会/当然不/其实……"这类语气 → 提醒。
- 没引用时，只认很明确的纠正（"不是……""你看错了""搞错了"）。
- 短时间里被纠正了好几次，就说明前面都没接住，提醒里点明这是第几次。
只做提醒，不改写她的回复。
"""

import re


QUOTE_PART = re.compile(r"^<Quoted Message>\n(?:\([^)\n]*\): )?(.*?)\n</Quoted Message>", re.S)
ERR = r"(?<![没不])错"  # "没错""不错"不算
# 引用了她的话时：带这些就像在纠正/反驳
CUES = re.compile(
    r"不是|不对|" + ERR + r"了|搞错|弄错|看错|认错|误会|怎么会|哪会|哪有|才不|并不|当然不|其实|而是"
    r"|没有啦|没那回事|想多了"
)
# 没引用时：只认很明确的纠正
STRONG = re.compile(
    r"^[\s，,。…~～]*(不是|不对|才不|哪有|并不|没有啦|不不)|你.{0,3}" + ERR + r"|搞错|看错|弄错|认错|误会"
    r"|怎么会.{0,12}呢"  # 反问："老师怎么会生气呢"
)
# 网页聊天里她发的消息，发送者 ID 记成 "bot"
WEBCHAT_BOT_ID = "bot"

BODY = (
    "先弄明白对方真正想说什么，认同对方的看法（可以有点不好意思，比如\"原来是这样\"），再顺着对方的意思接着聊；"
    "别再沿用你原来那句的看法，也别换个说法把原来的意思再说一遍，更别照着那句的句式写。"
)


def _clip(text: str, n: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def quoted_own(event, req) -> str | None:
    """Her own message that the user quoted this turn.

    Returns:
        The quoted text ('' when it is her message but the text is unknown), or None when the
        user did not quote one of her messages.
    """
    reply = next((c for c in (event.get_messages() or []) if type(c).__name__ == "Reply"), None)  # 引用（AstrBot 的 Reply 组件）
    if reply is None:
        return None
    self_id = str(event.get_self_id() or "")
    sid = str(getattr(reply, "sender_id", "") or "")
    if sid in ("", "0"):
        if "佳树" not in str(getattr(reply, "sender_nickname", "") or ""):
            return None
    elif sid not in (self_id, WEBCHAT_BOT_ID):
        return None
    text = ""
    for part in getattr(req, "extra_user_content_parts", None) or []:
        m = QUOTE_PART.match(getattr(part, "text", "") or "")
        if m:
            text = m.group(1).strip()
            break
    if not text:
        text = str(getattr(reply, "message_str", "") or "").strip()
    return "" if text == "[Empty Text]" else text  # 取不到原文时 AstrBot 填的占位


def is_rebuttal(user_text: str, quoted: str | None, last_reply: str) -> bool:
    """Whether the user's message looks like a correction of what she just said."""
    text = user_text or ""
    if quoted is not None:
        return bool(CUES.search(text))
    return bool(last_reply) and bool(STRONG.search(text))


def build_note(quoted: str | None, last_reply: str, times: int) -> str:
    """The reminder text appended to the system prompt.

    Args:
        quoted: Her quoted message (None when the user did not quote her).
        last_reply: Her previous reply in this conversation.
        times: How many times she has been corrected recently, this one included.
    """
    if quoted is not None:
        head = f"对方引用了你说的「{_clip(quoted or last_reply)}」，听起来是在纠正或反驳这句（如果只是普通接话，就忽略这条）。"
    else:
        head = f"对方这句像是在纠正你上一条说的「{_clip(last_reply)}」（如果不是，就忽略这条）。"
    again = ""
    if times >= 2:
        again = f"这已经是对方最近第 {times} 次纠正你了，说明前面的回复都没接住，这次一定要正面回应对方说的那一点。"
    return "\n\n【对方在纠正你】" + head + again + BODY
