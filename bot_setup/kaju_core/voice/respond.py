"""先回应，别先当解说员。

2026-11-02 群里女王大人说"这个zcode老是偷偷用我的api额度""服了"，佳树插话：
  "女王大人这会儿是真上火了呀，额度被悄悄吃掉最气人啦 / 佳树猜是后台一直在自动发请求……"
她看出了对方在恼火，却先把这一点说了出来（像旁白在描述对方），然后才说看法。
真人会直接回应那份情绪："女王大人别气啦，……"，再说猜测和办法。

真实日志里第一句这样"点评对方"的很多：
  "学姐这是要把一句话全打成错字才甘心呀" "这句听着像要下线了呀"
  "兄长大人这么一说佳树就明白了" "555学长这是把佳树当成大肥鱼了吧"
一部分是 voice 提醒带出来的：它要求第一句"叫一声称呼或拿佳树当主语"，
她就写成"称呼 + 这是/这会儿 + 描述"，例句里也有一句"兄长大人这是把整张桌子都换新了呀"（已换掉）。

- 对方在抱怨/发泄（服了、烦死了、无语……）→ 提醒接住对方，尊重对方的请求。
- 她最近一两条回复第一句是在点评对方 → 提醒，并引用那句。
只做提醒，不改写她的回复。
"""

import re

MEME_TAG = re.compile(r"&&[^&\n]*&&")

# 对方在抱怨、发泄、不痛快
VENT = re.compile(
    r"服了|无语|烦死|好烦|真烦|烦人|心烦|气死|好气|气人|离谱|崩溃|裂开|麻了|难受|累死|好累|心累|"
    r"哭了|哭死|想哭|郁闷|破防|寄了|绷不住|受不了|醉了|吐了|头疼|头大|倒霉|晦气|恶心|"
    r"怎么又|为什么又|又被|老是|总是.{0,8}(坏|崩|卡|错|慢|丢)|"
    r"[坏崩挂卡]了|蓝屏|骂了|挨骂|被坑|白干|白费|搞砸|没考好|挂科|失眠|睡不着|emo|心态炸|血压"
)
# 对方其实在说别人/玩梗时的常见误报：问句里的"怎么又"之类先不排除，误报的代价只是多一句提醒

# 第一句在描述/总结对方（说了什么、在干嘛、什么心情），而不是直接对 TA 说话
_WHO = r"(?:[^\s，,。！!？?～~、]{0,8}(?:大人|学姐|学长|前辈|老师)|兄长|对方|你|学姐|学长|这|那)"
COMMENTARY = [
    re.compile(_WHO + r"这(?:会儿|下|回|次)?(?:是|又|就)(?!不是)"),          # 女王大人这会儿是真…/学姐这是要…
    re.compile(_WHO + r"这(?:几句|句|话|一句)"),                              # 学姐这几句一句比一句抽象呀
    re.compile(r"^(?:这|那)(?:句|几句|话|样|一下|个)?(?:话)?(?:听着|听起来|看着|看来|读着)"),  # 这句听着像…
    re.compile(r"^(?:听着|听起来|看来|看样子|看得出|感觉得出)"),
    re.compile(r"(?:这么|这样)(?:一)?(?:说|讲|夸|认真地?答|问)[，,]?\s*佳树"),  # 兄长大人这么一说佳树就懂了
    re.compile(r"^佳树(?:看|听|读)(?:明白|懂|清楚?|到|见)(?:了|啦)?$"),  # 佳树看明白了，5小时那圈已经到91%……
    re.compile(r"^(?:这张|那张|学姐的|他的)?(?:图|截图|照片)(?:里|上)(?:是|写着|说|显示)"),  # 图里是说……
]
# 这几种开头本身就是在回应，不算
RESPONDING = re.compile(r"^(?:别|不气|摸摸|抱抱|辛苦|好过分|太过分|呜|欸|诶|哇|哈哈|好呀|好～|嗯|对|是呀|没事)")


def _first_line(reply: str) -> str:
    for line in MEME_TAG.sub("", reply or "").split("\n"):
        if line.strip():
            return line.strip()
    return ""


def is_commentary(line: str) -> bool:
    """The line opens by describing/summing up the other person instead of answering them."""
    head = re.split(r"[，,。！!？?～~]", line or "", maxsplit=1)[0]
    if not head or RESPONDING.search(head):
        return False
    return any(p.search(head) for p in COMMENTARY)


def is_venting(text: str) -> bool:
    """The other person is complaining / letting off steam (not talking about 佳树's feelings)."""
    for m in VENT.finditer(text or ""):
        if "佳树" not in text[max(0, m.start() - 8):m.start()]:
            return True
    return False


def _clip(text: str, n: int = 26) -> str:
    return text if len(text) <= n else text[:n] + "…"


NOTE = (
    "\n\n【先回应，别当解说员】先接住对方真正想说的话，尊重对方的请求；问问题就回答，说了件事就接着聊。"
    "可以用不确定的语气关心对方的心情，不要把猜测说成确定的事实；别只复述对方的话而不回应。"
)
VENT_NOTE = (
    "对方可能不痛快，可以自然地关心、安慰或陪着聊；是否给建议要看对方的意思，不强行套固定开头。"
)
SAID = "你最近有一句「{line}」容易读起来像旁白，这次留意先接住对方的话。"


def build_note(message: str, recent: list[str], title: str = "兄长大人") -> str:
    """The 先回应 note for this turn ('' when not needed).

    Args:
        message: What the other person just said (merged burst lines are fine).
        recent: Her recent replies in this chat, oldest first.
        title: What she calls the person she is answering.
    """
    vent = is_venting(message)
    last = [r for r in recent if MEME_TAG.sub("", r or "").strip()][-2:]
    said = next((_first_line(r) for r in reversed(last) if is_commentary(_first_line(r))), "")
    if not vent and not said:
        return ""
    note = NOTE.format(t=title)
    if vent:
        note += VENT_NOTE.format(t=title)
    if said:
        note += SAID.format(line=_clip(said))
    return note
