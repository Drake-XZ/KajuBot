"""B站私信：她的小号（kaju_basics 的 bili_login.json 里那份登录）收发私信、看互关、关注。

只用 B站网页自己用的接口（message.bilibili.com 页面发的同一批请求），Cookie 由 kaju_basics 登录和续期，
这里只借用（不刷新、不另存）。

- 有没有新私信：session_svr/single_unread（轻，轮询用）→ get_sessions 里 unread_count>0 的会话
- 读消息：svr_sync/fetch_session_msgs（begin_seqno 之后的），msg_seqno 递增
- 发消息：web_im/send_msg（w_sender_uid / w_receiver_id / w_dev_id 带 WBI 签名，表单带 csrf）
- 标已读：session_svr/update_ack
- 关系：x/relation?fid= 的 attribute 是"我对TA"：0 没关注、2 关注了、6 互关、128 拉黑
- 关注：x/relation/modify act=1
- 粉丝：x/relation/fans（新关注她的人）；资料：x/web-interface/card（名字、性别）
"""

from __future__ import annotations

import json
import re
import time
import uuid

VC = "https://api.vc.bilibili.com"
API = "https://api.bilibili.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
REFERER = "https://message.bilibili.com/"

MUTUAL = 6
BLOCKED = 128

# 私信 msg_type：1 文字、2 图片、5 撤回、6 自定义表情、7 分享（视频卡片等）、10/11/12/13/14 系统通知/推送、18 系统提示
TEXT, IMAGE, WITHDRAW, EMOJI, SHARE = 1, 2, 5, 6, 7
SYSTEM_TYPES = {10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}

BV_RE = re.compile(r"BV1[0-9A-Za-z]{9}")


class BiliError(Exception):
    """接口返回 code != 0（message 里是 B站给的原因）。"""

    def __init__(self, code, message: str):
        super().__init__(f"{code} {message}")
        self.code = code


def _content(msg: dict) -> dict:
    raw = msg.get("content")
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"content": str(raw or "")}
    return val if isinstance(val, dict) else {"content": str(val)}


def share_url(c: dict) -> str:
    """分享卡片 → 能打开的链接（视频优先认 bvid，其次 url / 纯数字 id 当 av 号）。"""
    bvid = str(c.get("bvid") or "")
    if not BV_RE.fullmatch(bvid):
        m = BV_RE.search(" ".join(str(c.get(k) or "") for k in ("url", "id", "jump_url")))
        bvid = m.group(0) if m else ""
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    url = str(c.get("url") or c.get("jump_url") or "")
    if url.startswith("http"):
        return url
    src, oid = c.get("source"), str(c.get("id") or "")
    if oid.isdigit() and src in (5, None):  # source 5 = 视频
        return f"https://www.bilibili.com/video/av{oid}"
    return ""


def parse(msg: dict) -> dict | None:
    """一条私信 → {seq, t, sender, text, images[], share{title,url}|None}；系统通知、撤回之类 → None。"""
    mt = int(msg.get("msg_type") or 0)
    if mt in SYSTEM_TYPES or mt == WITHDRAW or int(msg.get("msg_status") or 0) == 1:
        return None
    c = _content(msg)
    out = {"seq": int(msg.get("msg_seqno") or 0), "t": int(msg.get("timestamp") or 0),
           "sender": str(msg.get("sender_uid") or ""), "text": "", "images": [], "share": None}
    if mt == TEXT:
        out["text"] = str(c.get("content") or "").strip()
    elif mt == IMAGE:
        url = str(c.get("url") or "")
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http"):
            out["images"].append(url)
    elif mt == EMOJI:
        out["text"] = "[表情]"
    elif mt == SHARE:
        url = share_url(c)
        title = str(c.get("title") or c.get("headline") or "").strip()
        if not url and not title:
            return None
        out["share"] = {"title": title, "url": url, "author": str(c.get("author") or "")}
    else:
        text = str(c.get("content") or c.get("text") or "").strip()
        if not text:
            return None
        out["text"] = text
    return out


def joined(items: list[dict]) -> tuple[str, list[str]]:
    """一个人连着发的几条 → (一段文字, 图片链接)。分享卡片写成"【标题】链接"，kaju_basics 照常认链接去看。"""
    lines, images = [], []
    for it in items:
        if it.get("text"):
            lines.append(it["text"])
        if it.get("share"):
            sh = it["share"]
            lines.append((f"【{sh['title']}】" if sh.get("title") else "") + (sh.get("url") or ""))
        images += it.get("images") or []
    return "\n".join(x for x in lines if x).strip(), images


class Client:
    """借 kaju_basics 的登录（store：cookies dict + header()）。wbi 签名也借它的 bililogin。"""

    def __init__(self, http, store, bililogin, dev_id: str = ""):
        self.http = http
        self.store = store
        self.bl = bililogin
        self.dev_id = dev_id or str(uuid.uuid4()).upper()
        self._mixin = ("", 0.0)

    @property
    def mid(self) -> str:
        return str(self.store.cookies.get("DedeUserID") or "")

    @property
    def csrf(self) -> str:
        return str(self.store.cookies.get("bili_jct") or "")

    def _headers(self) -> dict:
        return {"Cookie": self.store.header(), "User-Agent": UA, "Referer": REFERER,
                "Origin": REFERER.rstrip("/")}

    async def _json(self, method: str, url: str, **kw) -> dict:
        async with self.http.request(method, url, headers=self._headers(), **kw) as r:
            data = await r.json(content_type=None)
        if not isinstance(data, dict):
            raise BiliError(-1, "不是 JSON")
        if int(data.get("code", -1)) != 0:
            raise BiliError(data.get("code"), str(data.get("message") or data.get("msg") or ""))
        return data.get("data") or {}

    async def mixin(self) -> str:
        key, at = self._mixin
        if key and time.time() - at < 6 * 3600:
            return key
        async with self.http.get(f"{API}/x/web-interface/nav", headers=self._headers()) as r:
            nav = (await r.json(content_type=None)).get("data") or {}
        key = self.bl.mixin_key(*self.bl.wbi_keys(nav))
        self._mixin = (key, time.time())
        return key

    # ---------------------------------------------------------------- 读
    async def unread(self) -> int:
        d = await self._json("GET", f"{VC}/session_svr/v1/session_svr/single_unread",
                             params={"unread_type": 0, "show_unfollow_list": 1, "show_dustbin": 1,
                                     "build": 0, "mobi_app": "web"})
        return int(d.get("follow_unread") or 0) + int(d.get("unfollow_unread") or 0)

    async def sessions(self, session_type: int) -> list[dict]:
        """session_type 1 = 她关注的人（含互关），2 = 没关注的人（陌生人私信）。"""
        d = await self._json("GET", f"{VC}/session_svr/v1/session_svr/get_sessions",
                             params={"session_type": session_type, "group_fold": 1, "unfollow_fold": 0,
                                     "sort_rule": 2, "build": 0, "mobi_app": "web"})
        return list(d.get("session_list") or [])

    async def messages(self, talker: str, session_type: int = 1, begin_seqno: int = 0, size: int = 20) -> list[dict]:
        """begin_seqno 之后的消息（从早到晚）。"""
        params = {"talker_id": talker, "session_type": session_type, "size": size,
                  "build": 0, "mobi_app": "web"}
        if begin_seqno:
            params["begin_seqno"] = begin_seqno
        d = await self._json("GET", f"{VC}/svr_sync/v1/svr_sync/fetch_session_msgs", params=params)
        msgs = [m for m in d.get("messages") or [] if int(m.get("msg_seqno") or 0) > begin_seqno]
        return sorted(msgs, key=lambda m: int(m.get("msg_seqno") or 0))

    async def ack(self, talker: str, session_type: int, seqno: int) -> None:
        await self._json("POST", f"{VC}/session_svr/v1/session_svr/update_ack",
                         data={"talker_id": talker, "session_type": session_type, "ack_seqno": seqno,
                               "build": 0, "mobi_app": "web", "csrf_token": self.csrf, "csrf": self.csrf})

    async def relation(self, fid: str) -> int:
        d = await self._json("GET", f"{API}/x/relation", params={"fid": fid})
        return int(d.get("attribute") or 0)

    async def fans(self, ps: int = 50) -> list[dict]:
        d = await self._json("GET", f"{API}/x/relation/fans", params={"vmid": self.mid, "pn": 1, "ps": ps})
        return [{"mid": str(x.get("mid")), "name": str(x.get("uname") or ""), "attribute": int(x.get("attribute") or 0),
                 "t": int(x.get("mtime") or 0)} for x in d.get("list") or []]

    async def card(self, mid: str) -> dict:
        d = await self._json("GET", f"{API}/x/web-interface/card", params={"mid": mid})
        c = d.get("card") or {}
        sex = {"男": "male", "女": "female"}.get(str(c.get("sex") or ""), "unknown")
        return {"mid": str(mid), "name": str(c.get("name") or ""), "sex": sex}

    # ---------------------------------------------------------------- 写
    async def follow(self, fid: str) -> None:
        await self._json("POST", f"{API}/x/relation/modify",
                         data={"fid": fid, "act": 1, "re_src": 11, "csrf": self.csrf})

    async def upload_image(self, data: bytes, filename: str = "meme.png") -> dict:
        """图片传到B站图床（网页发图片私信、发动态都先走这一步）→ {url, width, height, size(KB), type}。"""
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("file_up", data, filename=filename, content_type=image_mime(data))
        form.add_field("biz", "im")
        form.add_field("category", "daily")
        form.add_field("csrf", self.csrf)
        d = await self._json("POST", f"{API}/x/dynamic/feed/draw/upload_bfs", data=form)
        url = str(d.get("image_url") or d.get("location") or "")
        if not url:
            raise BiliError(-1, "图片传上去了但没拿到地址")
        return {"url": url, "width": int(d.get("image_width") or 0), "height": int(d.get("image_height") or 0),
                "size": float(d.get("img_size") or len(data) / 1024), "type": image_mime(data).split("/")[-1]}

    async def _send(self, talker: str, msg_type: int, content: dict) -> None:
        now = int(time.time())
        query = self.bl.wbi_sign({"w_sender_uid": self.mid, "w_receiver_id": talker, "w_dev_id": self.dev_id},
                                 await self.mixin())
        form = {
            "msg[sender_uid]": self.mid, "msg[receiver_type]": 1, "msg[receiver_id]": talker,
            "msg[msg_type]": msg_type, "msg[msg_status]": 0, "msg[dev_id]": self.dev_id, "msg[timestamp]": now,
            "msg[new_face_version]": 0, "msg[content]": json.dumps(content, ensure_ascii=False),
            "from_firework": 0, "build": 0, "mobi_app": "web",
            "csrf_token": self.csrf, "csrf": self.csrf,
        }
        await self._json("POST", f"{VC}/web_im/v1/web_im/send_msg", params=query, data=form)

    async def send_text(self, talker: str, text: str) -> None:
        await self._send(talker, TEXT, {"content": text})

    async def send_image(self, talker: str, img: dict) -> None:
        """img 是 upload_image 的结果。"""
        await self._send(talker, IMAGE, {"url": img["url"], "height": img["height"], "width": img["width"],
                                         "imageType": img["type"], "original": 1, "size": img["size"]})


def image_mime(data: bytes) -> str:
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
