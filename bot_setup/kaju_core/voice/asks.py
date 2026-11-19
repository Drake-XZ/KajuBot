"""问之前先听懂：她准备发的回复里，要是认真地问了一个对方刚说过答案的问题，发之前把那一行删掉。

2026-11-01：兄长说"我觉得这个跟我心里的想法很接近，这本几乎没有波荡起伏的剧情，但就是很沉重又自然地写二人相依为命的生活"，
她回"兄长大人说很接近心里的想法，是哪种想法呀？佳树想听"——想法他就在这句里说了。她的思考里写着"这符合'追问'风格"。

试过的：只加一句提示（"先在他话里找答案"）——真实人格+真实历史重放，问题本来就很少复现（12 次 0 次），
加了提示也看不出差别。真实日志 188 条私聊回复里这种"没读懂又问"大约 2~3 条。
所以改成发前把关：回复里有问句才问一次模型（约 1.8 秒，最多几秒；大约五条回复里一条有问句），
真实的 35 条带问句的回复里只挑出了这一句（惊讶式确认"那是老师？""是亲呀？"都留着）。
"""

from __future__ import annotations

import json
import re

QMARK = re.compile(r"[？?]")
MEME_LINE = re.compile(r"^\s*&&\w+&&\s*$")
REMINDER = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)

SYSTEM = """你帮一个QQ聊天机器人"佳树"在发出回复前把关。下面是最近的聊天和她准备发的回复。
只挑出这种问句：她认真地向对方要一个答案，可这个答案对方刚才已经明明白白说过了（她没读懂或没注意）。例：对方说"跟我想的很接近：几乎没剧情，但写得很沉重"，她问"是哪种想法呀？"。
这些都不算，照常保留：
- 听到新消息时惊讶、感叹、确认式的重复（"诶——是亲呀？""那是老师？""真的可以吗？""是给佳树做的吗？"）
- 撒娇、反问、语气上的问句，不是真要对方回答
- 对方只说了大概，她问更具体的、或往下一步问
- 不确定就保留
只输出 JSON：{"drop":["要删掉的那一行原文（逐字），没有就空列表"],"why":"一句话"}"""


def question_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if QMARK.search(ln) and not MEME_LINE.match(ln)]


def text_of(content) -> str:
    """历史里一条消息的文字（去掉 <system_reminder>）。"""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = []
        for p in content:
            t = p.get("text") if isinstance(p, dict) else getattr(p, "text", None)
            if isinstance(t, str):
                parts.append(t)
    else:
        parts = []
    text = "\n".join(REMINDER.sub("", p).strip() for p in parts)
    return "\n".join(ln for ln in text.splitlines() if ln.strip()).strip()


def context_lines(contexts, user_text: str, quote: str = "", keep: int = 8) -> list[str]:
    """最近几条聊天（她/对方）+ 这一轮对方说的话。"""
    out = []
    for m in contexts or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role not in ("user", "assistant"):
            continue
        t = text_of(m.get("content") if isinstance(m, dict) else getattr(m, "content", None))
        if t:
            out.append(("佳树：" if role == "assistant" else "对方：") + t)
    out = out[-(keep - 1):] if keep > 1 else []
    now = (f"（他引用了：{quote}）" if quote else "") + (user_text or "").strip()
    out.append("对方（这一条，佳树正在回）：" + now)
    return out


def build_prompt(lines: list[str], reply: str) -> str:
    return "【最近的聊天】\n" + "\n".join(lines) + "\n\n【她准备发的回复】\n" + reply.strip()


def parse(out: str, reply: str) -> list[str]:
    """模型说要删的行：只认回复里真有、而且带问号的整行。"""
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return []
    try:
        drop = json.loads(m.group(0)).get("drop") or []
    except (ValueError, AttributeError):
        return []
    qs = question_lines(reply)
    keep = []
    for d in drop if isinstance(drop, list) else []:
        d = str(d).strip()
        if d and d in qs and d not in keep:
            keep.append(d)
    return keep


def drop_lines(text: str, lines: list[str]) -> str | None:
    """删掉这些行；删完没剩正经内容（只剩表情包标记或空）就返回 None——宁可照原样发。"""
    if not lines:
        return text
    kept, removed = [], False
    for ln in (text or "").splitlines():
        if ln.strip() in lines:
            removed = True
            continue
        kept.append(ln)
    if not removed:
        return text
    if not any(ln.strip() and not MEME_LINE.match(ln) for ln in kept):
        return None
    return "\n".join(kept).strip("\n")
