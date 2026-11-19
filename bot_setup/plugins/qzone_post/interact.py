"""QQ 空间互动的纯逻辑（不碰网络、不碰 AstrBot，方便离线测）。

- 点赞：对比上次看到的点赞名单，找出新点赞的人。
- 评论：SnowLuma get_qzone_msg_detail 给的评论树（一级评论 + 楼中楼 replies），找出没处理过、在跟她说话的那几条，
  同一个人在同一楼里连着说的并成一条，一起回。
"""

from __future__ import annotations

import re

EMOJI = re.compile(r"\[em\]e?\d+\[/em\]")
MENTION = re.compile(r"@\{uin:(\d+),nick:([^,}]*)[^}]*\}")
MEME_TAG = re.compile(r"&&[^&\n]{1,40}&&")
SELF_NAMES = ("佳树",)


def clean(text) -> str:
    """评论正文：空间表情 → [表情]，@{uin:..,nick:..} → @昵称。"""
    text = str(text or "")
    text = MENTION.sub(lambda m: "@" + (m.group(2) or m.group(1)), text)
    text = EMOJI.sub("[表情]", text)
    return re.sub(r"\s+", " ", text).strip()


def brief(text, n: int = 24) -> str:
    text = clean(text).replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


def new_likers(prev, now: list[dict], self_uin: str) -> list[dict]:
    """prev = 上次存的 QQ 号列表（None = 第一次看这条说说）。返回新点赞的人 [{uin, nick}]。"""
    seen = set(prev or [])
    out = []
    for x in now:
        uin = str(x.get("uin") or x.get("fuin") or "")
        if uin and uin != self_uin and uin not in seen:
            out.append({"uin": uin, "nick": str(x.get("nick") or x.get("name") or uin)})
            seen.add(uin)
    return out


def _key(tid: str, top: dict, m: dict | None = None) -> str:
    if m is None:
        return f"{tid}/{top.get('comment_id')}"
    rid = m.get("comment_id") or f"{m.get('uin')}-{m.get('time')}"
    return f"{tid}/{top.get('comment_id')}/{rid}"


def scan(detail: dict, self_uin: str, seen: dict, now: float, max_age: float) -> tuple[list[dict], list[str]]:
    """找出要回的评论。

    Returns:
        (items, skip_keys)。items 每项是同一个人在同一楼里没回的几句；skip_keys 是看过但不用回的（太旧、
        不是跟她说的、已经回过了），直接记成已处理。
    """
    tid = str(detail.get("tid") or "")
    items: dict[tuple, dict] = {}
    skip: list[str] = []
    for top in detail.get("comments") or []:
        if top.get("comment_id") is None:
            continue
        thread = [(top, None)] + sorted(((r, r) for r in top.get("replies") or []),
                                        key=lambda x: int(x[0].get("time") or 0))
        mine = [int(m.get("time") or 0) for m, _ in thread if str(m.get("uin")) == self_uin]
        top_uin = str(top.get("uin") or "")
        for m, sub in thread:
            uin = str(m.get("uin") or "")
            if not uin or uin == self_uin:
                continue
            key = _key(tid, top, sub)
            if key in seen:
                continue
            t = int(m.get("time") or 0)
            text = clean(m.get("content"))
            answered = any(x >= t for x in mine)  # 她（或兄长用她的号）在这句之后已经在这楼里说过话了
            to_her = (sub is None or uin == top_uin or any(x < t for x in mine)
                      or any(n in text for n in SELF_NAMES))
            if not text or answered or not to_her or now - t > max_age:
                skip.append(key)
                continue
            it = items.setdefault((top.get("comment_id"), uin), {
                "tid": tid, "comment_id": str(top.get("comment_id")), "comment_uin": top_uin,
                "uin": uin, "name": str(m.get("name") or uin), "texts": [], "keys": [], "t": t,
                "is_reply": sub is not None, "reply_to": None, "top": top,
            })
            it["texts"].append(text)
            it["keys"].append(key)
            it["t"] = max(it["t"], t)
            if sub is not None and uin != top_uin:  # 楼中楼里别人说的：回复时 @ 回这个人
                it["reply_to"] = {"uin": uin, "name": str(m.get("name") or uin)}
    out = sorted(items.values(), key=lambda x: x["t"])
    for it in out:
        it["thread"] = thread_lines(it.pop("top"), self_uin)
    return out, skip


def thread_lines(top: dict, self_uin: str, limit: int = 12) -> list[str]:
    """这一楼从早到晚谁说了什么（给她看上下文）。"""
    msgs = [top] + sorted(top.get("replies") or [], key=lambda r: int(r.get("time") or 0))
    lines = []
    for m in msgs[-limit:]:
        who = "你" if str(m.get("uin")) == self_uin else str(m.get("name") or m.get("uin"))
        lines.append(f"{who}：{clean(m.get('content'))}")
    return lines


def message_text(item: dict, post: str) -> str:
    """交给她的那条"消息"（也是聊天记录 / 日记里记下的样子）。"""
    how = "回复你" if item["is_reply"] else "评论"
    return f"【QQ空间】在你的说说「{brief(post)}」下{how}：" + "\n".join(item["texts"])


def join_reply(parts: list[str], limit: int = 300) -> str:
    """她按行分段发出来的几句 → 一条评论。[SKIP] 或空 → ""。"""
    lines = []
    for p in parts:
        p = MEME_TAG.sub("", str(p or "")).strip()
        if not p:
            continue
        if "[SKIP]" in p.upper():
            return ""
        lines.extend(x.strip() for x in p.splitlines() if x.strip())
    text = " ".join(lines)
    return text[:limit].rstrip()
