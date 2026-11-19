"""抖音私信：在她小号的常驻浏览器（kaju_basics dykeeper）里开着抖音网页私信页（douyin.com/chat），
像人一样读会话、点开、打字、回车。

做法借 NEWJO123/dsh-douyin-scroll 的浏览器那条路（tools/chat-watch.mjs、im-send.mjs）：
- 会话列表：[data-e2e="conversation-item"]，React 数据里的 conversation（toParticipantSecUserId、
  toParticipantUserId、badgeCount 未读、type 1 = 私聊、isStrangerConversation）。
- 消息：[class*="messageMessageBox"]，React 数据里的 message。2026-11-08 实测它直接带 sender（uid）、
  secSender、serverId、createdAt、parsedContent.text，所以"谁发的"不用像那个仓库那样看头像在左还是右。
  同一条消息会挂在好几层节点上，按 serverId 去重。
- 发：先点开那个人的会话、核对右边打开的确实是他，点输入框，insertText，回车，
  再回读"她发的"里多了这一句才算发出去（和那个仓库一样）。
- 互关：用浏览器自己的 Cookie 问抖音 user/profile/other（不签名的只读接口），follow_status 2 = 互关。
- 关注：打开对方主页点"关注/回关"，再刷新看 follow_status；2026-11-08 网页端回关会被抖音悄悄撤销
  （接口回 follow_status 1、一刷新变 0），所以一定回头核对，不作数就让兄长用手机 App 关注。

不借的：它的 im-http.py（curl_cffi 伪装浏览器指纹直接打私信接口）、dy-signer（a_bogus 签名）。
"""

from __future__ import annotations

import asyncio
import json
import time

CHAT_URL = "https://www.douyin.com/chat"
PROFILE_API = "https://www.douyin.com/aweme/v1/web/user/profile/other/?device_platform=webapp&aid=6383&sec_user_id="
SELF_API = "https://www.douyin.com/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383"
MUTUAL = 2

_FIBER = """(n, want, depth) => { const fk = Object.keys(n).find(k => k.startsWith('__reactFiber$'));
  let f = fk ? n[fk] : null, d = 0;
  while (f && d < depth) { const p = f.memoizedProps; if (p && p[want] && typeof p[want] === 'object') return p[want]; f = f.return; d++; }
  return null; }"""

CONV_JS = """() => { const fib = %s; const out = [];
  document.querySelectorAll('[data-e2e="conversation-item"]').forEach((n, i) => {
    const c = fib(n, 'conversation', 16); if (!c) return;
    const name = ((n.innerText || '').split('\\n')[0] || '').trim();
    out.push({i, sec: String(c.toParticipantSecUserId || ''), uid: String(c.toParticipantUserId || ''),
              badge: Number(c.badgeCount || 0), type: Number(c.type || 0), stranger: !!c.isStrangerConversation,
              id: String(c.id || ''), name});
  });
  return out; }""" % _FIBER

MSG_JS = """() => { const fib = %s; const out = [], seen = new Set();
  document.querySelectorAll('[class*="messageMessageBox"]').forEach(n => {
    const m = fib(n, 'message', 24); if (!m || !m.serverId || seen.has(String(m.serverId))) return;
    seen.add(String(m.serverId));
    const pc = m.parsedContent || {};
    const pick = (o, ks) => { for (const k of ks) { if (o && o[k] != null && o[k] !== '') return o[k]; } return ''; };
    let img = '';
    try { const r = pc.resource_url || pc.url || pc.image || {}; img = (r.url_list || r.urlList || [])[0] || ''; } catch (e) {}
    out.push({id: String(m.serverId), sender: String(m.sender || ''), sec: String(m.secSender || ''),
              conv: String(m.conversationId || ''), t: Date.parse(m.createdAt || '') || 0,
              text: String(pc.text || ''), awe: Number(pc.aweType || 0),
              item: String(pick(pc, ['itemId', 'item_id', 'aweme_id', 'awemeId']) || ''),
              title: String(pick(pc, ['content_title', 'title', 'desc', 'content_name']) || ''),
              img: String(img || '')});
  });
  return out; }""" % _FIBER

OPEN_JS = """(sec) => { const fib = %s;
  for (const n of document.querySelectorAll('[data-e2e="conversation-item"]')) {
    const c = fib(n, 'conversation', 16);
    if (c && String(c.toParticipantSecUserId || '') === sec) { n.scrollIntoView({block: 'center'}); const r = n.getBoundingClientRect();
      return {x: r.x + r.width / 2, y: r.y + r.height / 2}; } }
  return null; }""" % _FIBER

INPUT_JS = """() => { for (const e of document.querySelectorAll('[contenteditable="true"], textarea')) {
    const r = e.getBoundingClientRect(); if (r.width > 80 && r.height > 10) return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }
  return null; }"""
TYPED_JS = """() => { const e = document.querySelector('[contenteditable="true"], textarea');
  return e ? String(e.innerText || e.value || '').replace(/[\\u200b\\r]/g, '') : ''; }"""


# 她的表情包分类（meme_manager 的文件夹名）→ 在抖音里打什么字去搜表情。打招呼按时间另算（sticker_word）。
STICKER_WORDS = {
    "happy": "开心", "affection": "喜欢", "sad": "难过", "angry": "生气", "shy": "害羞", "embarrassed": "尴尬",
    "surprised": "震惊", "scare": "害怕", "confused": "疑惑", "question": "疑惑", "sleep": "晚安", "tired": "累了",
    "approval": "好的", "reply": "收到", "encourage": "加油", "proud": "得意", "apology": "对不起", "reject": "不要",
    "cold-shoulder": "无语", "ridicule": "笑死", "entertainment": "哈哈哈", "eating": "干饭", "food": "好吃",
    "money": "有钱", "interaction": "贴贴", "attack": "打你", "surrender": "投降",
}

STRIP_JS = """() => { const out = []; const row = document.querySelector('[class*="messageMsgInputinputRow"]');
  const top = row ? row.getBoundingClientRect().y : 640;
  for (const im of document.querySelectorAll('img')) { const r = im.getBoundingClientRect();
    if (r.width > 40 && r.width < 120 && r.y > top - 110 && r.y + r.height <= top + 2 && /im-emoticon/.test(im.src || ''))
      out.push({x: r.x + r.width / 2, y: r.y + r.height / 2}); }
  return out.sort((a, b) => a.x - b.x); }"""


def sticker_word(category: str, hour: int) -> str:
    """表情包分类 → 抖音里打的字。没对上的分类用"嘿嘿"。"""
    if category == "greeting":
        return "早上好" if 5 <= hour < 11 else ("晚上好" if 18 <= hour < 23 else ("晚安" if hour >= 23 or hour < 5 else "你好"))
    return STICKER_WORDS.get(category, "嘿嘿")


def to_item(m: dict) -> dict | None:
    """页面里读到的一条消息 → kaju_dm 的 item（和 bilidm.parse 一样的样子）。"""
    text = (m.get("text") or "").strip()
    share = None
    if m.get("item"):
        share = {"title": (m.get("title") or "").strip(), "url": f"https://www.douyin.com/video/{m['item']}", "author": ""}
    images = [m["img"]] if m.get("img", "").startswith("http") else []
    if not text and not share and not images:
        return None
    return {"seq": int(m.get("t") or 0), "t": int((m.get("t") or 0) / 1000), "sender": m.get("sender", ""),
            "text": text, "images": images, "share": share, "id": m.get("id", "")}


def mutual(profile: dict) -> bool:
    return int(profile.get("follow_status") or 0) == MUTUAL


class Chat:
    """连着常驻浏览器的那一页私信页。keeper()：返回 dykeeper.Keeper（没登录 / 没开时 None）。"""

    def __init__(self, keeper):
        self._keeper = keeper
        self._pw = None
        self._browser = None
        self._page = None
        self.lock = asyncio.Lock()

    async def close(self) -> None:
        for obj, how in ((self._browser, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    await getattr(obj, how)()  # browser.close() 只断开连接，常驻的 Chrome 不关
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._page = None

    async def page(self):
        k = self._keeper()
        if k is None:
            raise RuntimeError("抖音小号没登录着")
        if self._browser is None or not self._browser.is_connected():
            await self.close()
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(await k.ensure(True))
        if self._page is not None and not self._page.is_closed() and "/chat" in (self._page.url or ""):
            return self._page
        ctx = self._browser.contexts[0]
        pg = next((x for x in ctx.pages if "douyin.com/chat" in (x.url or "")), None)
        if pg is None:  # 常驻浏览器停着的那页换成私信页（抖音网页一直在，私信也一直推过来）
            pg = next((x for x in ctx.pages if "douyin.com" in (x.url or "")), None) or await ctx.new_page()
            await pg.goto(CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(6)
        for x in list(ctx.pages):  # 私信页在，多出来停着的"我的"页就不用了（一页就占 150~400 MB）
            if x is not pg and "douyin.com/user/self" in (x.url or ""):
                try:
                    await x.close()
                except Exception:  # noqa: BLE001
                    pass
        self._page = pg
        return pg

    async def conversations(self) -> list[dict]:
        pg = await self.page()
        return [c for c in await pg.evaluate(CONV_JS) if c.get("sec")]

    async def open(self, sec: str) -> bool:
        pg = await self.page()
        pos = await pg.evaluate(OPEN_JS, sec)
        if not pos:
            return False
        await pg.mouse.click(pos["x"], pos["y"])
        await asyncio.sleep(2.2)
        return await self.current_is(sec)

    async def current_is(self, sec: str) -> bool:
        """右边打开的会话是不是他：看已经显示的消息里对方的 secSender（他还没说过话就看会话 id 里的 uid）。"""
        msgs = await (await self.page()).evaluate(MSG_JS)
        return any(m.get("sec") == sec for m in msgs)

    async def messages(self) -> list[dict]:
        msgs = await (await self.page()).evaluate(MSG_JS)
        return sorted(msgs, key=lambda m: (m.get("t") or 0, m.get("id")))

    async def send(self, sec: str, text: str, me: str) -> bool:
        """发一句。→ 回读时她发的里多了这一句才算 True。"""
        pg = await self.page()
        if not await self.current_is(sec) and not await self.open(sec):
            raise RuntimeError("没找到这个人的会话")
        # 按消息编号认"新发的"：页面只留最近一段消息，新的进来旧的会被挤掉，数条数不准（11-08 误报过好几次）
        before = {m.get("id") for m in await self.messages()}
        pos = await pg.evaluate(INPUT_JS)
        if not pos:
            raise RuntimeError("没找到输入框")
        await pg.mouse.click(pos["x"], pos["y"])
        await asyncio.sleep(0.4)
        await pg.keyboard.insert_text(text)
        await asyncio.sleep(0.8)
        if not (await pg.evaluate(TYPED_JS)).strip():
            raise RuntimeError("字没打进输入框")
        await pg.keyboard.press("Enter")
        for _ in range(10):
            await asyncio.sleep(0.8)
            if any(m.get("sender") == me and m.get("id") not in before and _same(m.get("text"), text)
                   for m in await self.messages()):
                return True
        return False

    async def me(self) -> str:
        """她自己的 uid（分辨哪句是她发的）。"""
        await self.page()
        try:
            r = await self._browser.contexts[0].request.get(SELF_API, headers={"Referer": "https://www.douyin.com/"},
                                                            timeout=15000)
            d = json.loads(await r.text())
        except Exception:  # noqa: BLE001
            return ""
        return str(((d.get("user") or {}) if isinstance(d, dict) else {}).get("uid") or "")

    async def send_image(self, sec: str, path: str, me: str) -> bool:
        """发一张图：交给输入框旁边的上传框（只收 jpg/png/gif/mp4）→ 弹出的确认框里点「发送（1）」→
        回读出现她发的新消息才算 True。2026-11-08 实测：图片消息 aweType 2703、没有文字。"""
        import re

        pg = await self.page()
        if not await self.current_is(sec) and not await self.open(sec):
            raise RuntimeError("没找到这个人的会话")
        before = {m.get("id") for m in await self.messages()}
        await pg.locator('[class*="MsgInputFileUpload"] input.semi-upload-hidden-input').first.set_input_files(path)
        btn = pg.get_by_role("button", name=re.compile(r"^发送")).locator("visible=true")
        for _ in range(10):
            await asyncio.sleep(0.5)
            if await btn.count():
                break
        else:
            raise RuntimeError("选好图以后没出现「发送」确认框")
        await btn.first.click(timeout=5000)
        for _ in range(15):
            await asyncio.sleep(1)
            if any(m.get("sender") == me and m.get("id") not in before for m in await self.messages()):
                return True
        return False

    async def send_sticker(self, sec: str, word: str, me: str, pick: int = 0) -> bool:
        """发一个抖音表情库里的表情（和手机上一样）：在输入框里一个字一个字打 word（insert_text 一次塞进去不会触发），
        等输入框上方弹出一排建议表情，点第 pick 个；回读出现她发的新消息才算 True。
        点了表情，输入框里的字抖音会自己清掉；没弹出来就把字删掉，什么都不发。
        2026-11-08 实测：打字后抖音去 im/resource/emoticon/search 搜，建议栏 1~8 秒出来；发出的是 aweType 510，兄长手机上收得到
        （上传的图片 2703 收不到）。"""
        pg = await self.page()
        if not await self.current_is(sec) and not await self.open(sec):
            raise RuntimeError("没找到这个人的会话")
        before = {m.get("id") for m in await self.messages()}
        pos = await pg.evaluate(INPUT_JS)
        if not pos:
            raise RuntimeError("没找到输入框")
        await pg.mouse.click(pos["x"], pos["y"])
        await asyncio.sleep(0.3)
        await pg.keyboard.type(word, delay=120)
        strip: list = []
        for _ in range(24):
            await asyncio.sleep(0.5)
            strip = await pg.evaluate(STRIP_JS)
            if strip:
                await asyncio.sleep(0.6)  # 一排图画完
                strip = await pg.evaluate(STRIP_JS) or strip
                break
        try:
            if not strip:
                return False
            target = strip[min(max(0, pick), len(strip) - 1)]
            await pg.mouse.click(target["x"], target["y"])
            for _ in range(10):
                await asyncio.sleep(0.8)
                if any(m.get("sender") == me and m.get("id") not in before for m in await self.messages()):
                    return True
            return False
        finally:
            if (await pg.evaluate(TYPED_JS)).strip():  # 字还留在输入框里：删掉，绝不当成一句话发出去
                await pg.keyboard.press("Control+A")
                await pg.keyboard.press("Backspace")

    async def profile(self, sec: str) -> dict:
        """{follow_status, follower_status, nickname, sex}；问不到 → {}。"""
        await self.page()
        ctx = self._browser.contexts[0]
        try:
            r = await ctx.request.get(PROFILE_API + sec, headers={"Referer": "https://www.douyin.com/"}, timeout=15000)
            d = json.loads(await r.text())
        except Exception:  # noqa: BLE001
            return {}
        u = d.get("user") if isinstance(d, dict) and int(d.get("status_code") or 0) == 0 else None
        if not isinstance(u, dict):
            return {}
        return {"follow_status": int(u.get("follow_status") or 0), "follower_status": int(u.get("follower_status") or 0),
                "nickname": str(u.get("nickname") or ""), "uid": str(u.get("uid") or ""),
                "sex": {1: "male", 2: "female"}.get(int(u.get("gender") or 0), "unknown")}

    async def fans(self, timeout: float = 15) -> list[dict]:
        """新关注她的人：打开"我的"→ 粉丝，记下页面自己拿到的粉丝列表（用另一个标签页，私信页不动）。"""
        await self.page()
        ctx = self._browser.contexts[0]
        got: dict = {}
        pg = await ctx.new_page()
        try:
            async def on(r):
                if "/user/follower/list" in r.url and "fans" not in got:
                    try:
                        got["fans"] = await r.json()
                    except Exception:  # noqa: BLE001
                        got["fans"] = {}
            pg.on("response", on)
            await pg.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
            await pg.get_by_text("粉丝", exact=True).locator("visible=true").first.click(timeout=5000)
            end = time.time() + timeout
            while "fans" not in got and time.time() < end:
                await asyncio.sleep(0.5)
        finally:
            await pg.close()
        return [{"sec": str(f.get("sec_uid") or ""), "uid": str(f.get("uid") or ""), "name": str(f.get("nickname") or ""),
                 "follow_status": int(f.get("follow_status") or 0)}
                for f in (got.get("fans") or {}).get("followers") or [] if f.get("sec_uid")]

    async def follow(self, sec: str) -> bool:
        """打开他的主页点"关注/回关"，刷新后核对。→ 真关注上了才 True。"""
        await self.page()
        ctx = self._browser.contexts[0]
        pg = await ctx.new_page()
        try:
            await pg.goto(f"https://www.douyin.com/user/{sec}", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            for name in ("回关", "关注"):
                btn = pg.get_by_role("button", name=name, exact=True).locator("visible=true")
                if await btn.count():
                    await btn.first.click(timeout=5000)
                    break
            await asyncio.sleep(4)
        finally:
            await pg.close()
        await asyncio.sleep(2)
        return int((await self.profile(sec)).get("follow_status") or 0) >= 1


def _same(a, b) -> bool:
    norm = lambda s: " ".join(str(s or "").split())  # noqa: E731
    return norm(a) == norm(b) or (len(norm(b)) > 20 and norm(a).startswith(norm(b)[:20]))
