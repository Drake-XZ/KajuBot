"""Offline tests for kaju_dm 1.0.0（B站私信：互关才回、回关和多看的视频要兄长批）.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_kaju_dm.py
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

bd = importlib.import_module("kaju_platforms.bili.bilidm")
lg = importlib.import_module("kaju_platforms.shared.ledger")
turn = importlib.import_module("kaju_dm.turn")
dm = importlib.import_module("kaju_dm.main")
ab = importlib.import_module("address_book.main")

PNG_HEAD, JPG_HEAD = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]), bytes([0xFF, 0xD8])
OWNER_QQ, OWNER_MID, A, B = "111111111", "9001", "111", "222"
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def msg(seq, mt, content, sender=A, t=None):
    return {"msg_seqno": seq, "msg_type": mt, "content": json.dumps(content, ensure_ascii=False),
            "sender_uid": int(sender), "timestamp": t or int(time.time())}


# ------------------------------------------------------------------ bilidm 解析
expect("text", bd.parse(msg(1, 1, {"content": " 你好呀 "}))["text"], "你好呀")
expect("image", bd.parse(msg(2, 2, {"url": "//i0.hdslb.com/bfs/x.png"}))["images"], ["https://i0.hdslb.com/bfs/x.png"])
sh = bd.parse(msg(3, 7, {"title": "猫猫", "bvid": "BV1xx411c7mD", "source": 5, "id": 123}))["share"]
expect("share bvid", sh["url"], "https://www.bilibili.com/video/BV1xx411c7mD")
expect("share av", bd.parse(msg(4, 7, {"title": "旧", "source": 5, "id": 170001}))["share"]["url"],
       "https://www.bilibili.com/video/av170001")
expect("system skipped", bd.parse(msg(5, 10, {"title": "登录操作通知"})), None)
expect("withdraw skipped", bd.parse(msg(6, 5, "123")), None)
items = [bd.parse(msg(1, 1, {"content": "看这个"})), bd.parse(msg(3, 7, {"title": "猫猫", "bvid": "BV1xx411c7mD"})),
         bd.parse(msg(2, 2, {"url": "https://i0.hdslb.com/a.jpg"}))]
expect("joined", bd.joined(items), ("看这个\n【猫猫】https://www.bilibili.com/video/BV1xx411c7mD", ["https://i0.hdslb.com/a.jpg"]))

# ------------------------------------------------------------------ ledger
L = lg.Ledger(os.path.join(DATA, "l.json"))
day = "2026-11-08"
expect("split under", L.split_videos("bili", A, day, ["u1", "u2"], 3), (["u1", "u2"], []))
L.use_videos("bili", A, day, 2)
expect("split over", L.split_videos("bili", A, day, ["u3", "u4"], 3), (["u3"], ["u4"]))
expect("split unlimited", L.split_videos("bili", A, day, ["u3", "u4"], -1), (["u3", "u4"], []))
expect("other person own quota", L.split_videos("bili", B, day, ["u1", "u2", "u3", "u4"], 3), (["u1", "u2", "u3"], ["u4"]))
r1, new1 = L.ask("follow", "bili", A, "小A", text="你好")
r1b, new1b = L.ask("follow", "bili", A, "小A")
expect("ask dedupe", (new1, new1b, r1["id"] == r1b["id"]), (True, False, True))
r2, _ = L.ask("video", "bili", A, "小A", url="https://b23.tv/x", title="猫猫")
expect("pending", [r["id"] for r in L.pending()], [r1["id"], r2["id"]])
L.answer(r1["id"], False)
expect("refused follow", L.refused_follow("bili", A), True)
expect("answered not pending", [r["id"] for r in L.pending()], [r2["id"]])
expect("get #", L.get("#2")["id"], 2)
L.hold("bili", B, [{"text": "a"}, {"text": "b"}])
expect("take held", [x["text"] for x in L.take_held("bili", B)], ["a", "b"])
expect("held gone", L.take_held("bili", B), [])
expect("describe follow", lg.describe(r1), "#1 小A（B站 111）关注了佳树，要不要回关，TA私信说：「你好」")
expect("describe video", lg.describe(r2), "#2 小A（B站 111）今天让佳树看的视频超过额度了，还想让她看「猫猫」 https://b23.tv/x")
expect("strip links", lg.strip_links("看这个\n【猫猫】https://b23.tv/x", ["https://b23.tv/x"]), "看这个\n【猫猫】")
L.set_person("douyin", "MS4wSEC", name="小D", uid="123")  # 抖音的人：键是 sec_uid，另存数字 uid
expect("set_person uid kw", L.person("douyin", "MS4wSEC"), {"name": "小D", "uid": "123"})
L.save()
expect("saved/reloaded", len(lg.Ledger(os.path.join(DATA, "l.json")).data["requests"]), 2)

# ------------------------------------------------------------------ turn.make_event：真的事件类（AstrBot 部分用假的）
def _fake_astrbot_core():
    import types

    class AstrMessageEventBase:
        def __init__(self, message_str, message_obj, platform_meta, session_id):
            self.message_str, self.message_obj, self.session_id = message_str, message_obj, session_id
            self._extra = {}

        def set_extra(self, k, v):
            self._extra[k] = v

        def get_extra(self, k=None, default=None):
            return self._extra.get(k, default)

        async def send(self, message):
            self.base_sent = True

    class AiocqhttpMessageEvent(AstrMessageEventBase):
        def __init__(self, message_str, message_obj, platform_meta, session_id, bot):
            super().__init__(message_str, message_obj, platform_meta, session_id)
            self.bot = bot

    class AstrBotMessage:
        pass

    class MessageMember:
        def __init__(self, user_id, nickname):
            self.user_id, self.nickname = user_id, nickname

    class MessageType:
        FRIEND_MESSAGE = "friend"

    mods = {
        "astrbot.core.platform": types.ModuleType("p"),
        "astrbot.core.platform.astr_message_event": types.SimpleNamespace(AstrMessageEvent=AstrMessageEventBase),
        "astrbot.core.platform.astrbot_message": types.SimpleNamespace(AstrBotMessage=AstrBotMessage,
                                                                        MessageMember=MessageMember),
        "astrbot.core.platform.message_type": types.SimpleNamespace(MessageType=MessageType),
        "astrbot.core.platform.sources": types.ModuleType("s"),
        "astrbot.core.platform.sources.aiocqhttp": types.ModuleType("a"),
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event":
            types.SimpleNamespace(AiocqhttpMessageEvent=AiocqhttpMessageEvent),
    }
    old = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    return old


async def make_event_tests():
    old = _fake_astrbot_core()
    try:
        from astrbot.api.message_components import Image, Plain
        lines, imgs = [], []

        async def on_line(t):
            lines.append(t)

        async def on_image(i):
            imgs.append(i)
        plat = type("P", (), {"meta": lambda self: None})()
        ev = turn.make_event(plat, object(), "555555555", "bili_1", "bili_1", "小A", "你好",
                             ["https://i0.hdslb.com/a.jpg"], {"site": "bili", "uid": "1"}, on_line, on_image)
        expect("event has image from DM", len(ev.message_obj.message), 2)
        chain = type("C", (), {"chain": [Plain("嗯嗯"), Image.fromURL("https://x/y.png")]})()
        await ev.send(chain)
        expect("event send text+image", (lines, len(imgs), ev.sent), (["嗯嗯"], 1, ["嗯嗯", "[图片]"]))
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


asyncio.run(make_event_tests())

# ------------------------------------------------------------------ address_book 写法
expect("id_text qq", ab.id_text("123"), "QQ 123")
expect("id_text bili", ab.id_text("bili_456"), "B站 456")


# ------------------------------------------------------------------ main：假的 B站 / QQ / AstrBot
class FakeStore:
    cookies = {"DedeUserID": "3747578646628393", "bili_jct": "x", "SESSDATA": "s"}
    logged_in = True

    def header(self):
        return "SESSDATA=s"


class FakeBasics:
    _login = FakeStore()
    config = {"guard": {"allowed_self_ids": ["555555555"]}}


class FakeBook:
    owner = OWNER_QQ

    def __init__(self):
        self._people = {}
        self._people_dirty = False

    def address_of(self, qq, name=None):
        return {"333333333": "女王大人"}.get(qq) or ("兄长大人" if qq == OWNER_QQ else f"{name}学长")

    def find_person(self, text):
        return [("333333333", "女王大人")] if "女王" in text or text == "333333333" else []


class Meta:
    def __init__(self, star):
        self.star_cls = star


class FakeClient:
    def __init__(self):
        self.rel = {}
        self.sent = []
        self.followed = []

    async def relation(self, uid):
        return self.rel.get(uid, 0)

    async def follow(self, uid):
        self.followed.append(uid)
        self.rel[uid] = 6 if self.rel.get(uid) == "fan" or uid in self.fans_of_her else 2

    fans_of_her = set()

    async def card(self, uid):
        return {"mid": uid, "name": {A: "小A", B: "小B", OWNER_MID: "兄长号"}.get(uid, uid), "sex": "female"}

    async def send_text(self, uid, text):
        self.sent.append((uid, text))

    async def upload_image(self, data, filename="x"):
        return {"url": "https://i0.hdslb.com/bfs/im_new/x.png", "width": 2, "height": 3, "size": len(data) / 1024,
                "type": "png"}

    async def send_image(self, uid, img):
        self.sent.append((uid, "[图]" + img["url"]))


class FakePlatform:
    def __init__(self):
        self.sent = []

    def get_client(self):
        return object()

    async def send_by_session(self, session, chain):
        self.sent.append((session.session_id, chain))


async def main_tests():
    ctx = Context()
    book = FakeBook()
    ctx.stars = [Meta(FakeBasics()), Meta(book)]
    plat = FakePlatform()
    ctx.get_platform = lambda name: plat
    plugin = dm.KajuDm(ctx, {"owner_bili_mid": OWNER_MID, "video_per_day": 3, "bili": {"line_gap": 0}})
    for t in plugin._tasks:
        t.cancel()
    cl = FakeClient()
    plugin._client = lambda: cl
    plugin._self_id = "555555555"

    async def fake_find(text):
        return []
    plugin._video_links = lambda text: [w for w in text.split() if w.startswith("http")] or \
        [s for s in text.split("】") if s.startswith("http")]

    submitted = []

    def fake_make(platform, bot, self_id, session, sender, name, text, images, extra, on_line, on_image=None):
        ev = AstrMessageEvent(sender=sender, text=text, name=name)
        ev.set_extra(turn.DM_KEY, extra)
        ev.sent = []
        ev._on_line = on_line
        submitted.append({"session": session, "sender": sender, "text": text, "extra": extra, "ev": ev, "bot": bot})
        return ev

    async def fake_run(platform, ev, timeout, settle=6.0, sleep=None):
        await ev._on_line("嗯嗯，佳树在呢～")
        ev.sent.append("嗯嗯，佳树在呢～")
        return "ok"

    turn.make_event, turn.run = fake_make, fake_run

    # 没互关：存着、登记回关，不回
    cl.rel[A] = 0
    await plugin._from_bili(A, [bd.parse(msg(1, 1, {"content": "佳树你好"}))])
    expect("not mutual: no turn", submitted, [])
    expect("not mutual: held", len(plugin._ledger.data["held"].get("bili:" + A, [])), 1)
    fr = plugin._ledger.find("follow", "bili", A)
    expect("not mutual: follow asked", (fr is not None, fr and fr["text"]), (True, "佳树你好"))

    # 她关注了TA但TA没关注她（2）：只存着，不去问
    cl.rel[B] = 2
    await plugin._from_bili(B, [bd.parse(msg(1, 1, {"content": "hi"}, sender=B))])
    expect("half follow: no ask", plugin._ledger.find("follow", "bili", B), None)

    # 兄长批准回关：关注 → 互关 → 存着的私信接着回
    cl.fans_of_her.add(A)
    res = await plugin._apply(fr, True)
    await asyncio.sleep(0.05)
    expect("approve follow: followed", cl.followed, [A])
    expect("approve follow: said", "互关" in res and "接着回" in res, True)
    expect("approve follow: held replied", submitted[-1]["extra"]["note"], dm.HELD_NOTE)
    expect("approve follow: session", submitted[-1]["session"], "bili_" + A)
    expect("approve follow: reply sent as DM", cl.sent[-1], (A, "嗯嗯，佳树在呢～"))
    expect("address book got bili name", book._people.get("bili_" + A, {}).get("sex"), "female")

    # 互关的人：前 3 条视频照看，第 4 条先问兄长
    cl.rel[A] = 6
    day = plugin._day()
    plugin._ledger.use_videos("bili", A, day, 2)
    links = [bd.parse(msg(9, 7, {"title": "第三", "bvid": "BV1aa411c7mD"})),
             bd.parse(msg(10, 7, {"title": "第四", "bvid": "BV1bb411c7mD"}))]
    await plugin._from_bili(A, links)
    last = submitted[-1]
    expect("quota: 3rd kept", "BV1aa411c7mD" in last["text"], True)
    expect("quota: 4th stripped", "BV1bb411c7mD" in last["text"], False)
    expect("quota: over count", last["extra"].get("over"), 1)
    vr = plugin._ledger.find("video", "bili", A, "https://www.bilibili.com/video/BV1bb411c7mD")
    expect("quota: video request", (vr is not None, vr and vr["title"]), (True, "第四"))
    expect("quota: used", plugin._ledger.videos_used("bili", A, day), 3)

    # QQ 没连上（拿不到客户端）：私信照回，QQ 客户端换成 NoQQ
    plat.get_client = lambda: None
    n = len(submitted)
    await plugin._from_bili(A, [bd.parse(msg(11, 8, {"content": "在吗"}))])
    expect("no QQ client: still replies", (len(submitted), type(submitted[-1]["bot"]).__name__), (n + 1, "NoQQ"))
    plat.get_client = lambda: object()
    last = submitted[n - 1]

    # 提示：私信这一轮
    req = ProviderRequest(prompt="x", system_prompt="S")
    await plugin.inject(last["ev"], req)
    expect("note: dm", "【B站私信】" in req.system_prompt and "小A" in req.system_prompt, True)
    expect("note: over", "最多 3 条" in req.system_prompt, True)

    # 兄长批准多看：拿那条视频再走一轮，不再算额度
    n = len(submitted)
    res = await plugin._apply(vr, True)
    await asyncio.sleep(0.05)
    expect("approve video: turn", len(submitted), n + 1)
    expect("approve video: has link", "BV1bb411c7mD" in submitted[-1]["text"], True)
    expect("approve video: note", submitted[-1]["extra"]["note"], dm.APPROVED_NOTE)
    expect("approve video: no over", submitted[-1]["extra"].get("over"), None)
    expect("approve video: again answered", "已经答复过" in await plugin._apply(vr, True), True)

    # 兄长本人：不看互关、不限视频，用他的 QQ 会话
    cl.rel[OWNER_MID] = 0
    many = [bd.parse(msg(i, 7, {"title": str(i), "bvid": f"BV1c{i}411c7mD"}, sender=OWNER_MID)) for i in range(1, 6)]
    await plugin._from_bili(OWNER_MID, many)
    expect("owner: session is QQ", submitted[-1]["session"], OWNER_QQ)
    expect("owner: no limit", submitted[-1]["extra"].get("over"), None)
    expect("owner: note", submitted[-1]["extra"]["owner"], True)

    # 身份表（kaju_core.people）：认到某个 QQ 上的 B站号 → 用那个人的 QQ 会话，不再当成 bili_ 的生人
    from kaju_core import people as kpeople
    kpeople.registry().link("555000", "bili", A, "群友")
    await plugin._from_bili(A, [bd.parse(msg(50, 1, {"content": "在吗"}, sender=A))])
    expect("linked friend: session is their QQ", submitted[-1]["session"], "555000")
    expect("linked friend: not owner", submitted[-1]["extra"]["owner"], False)
    kpeople.registry().unlink("bili", A)
    # 身份表里登记的兄长另一个B站号也算兄长
    kpeople.registry().set_owner(OWNER_QQ)
    kpeople.registry().link(OWNER_QQ, "bili", "9002")
    cl.rel["9002"] = 0
    await plugin._from_bili("9002", [bd.parse(msg(51, 1, {"content": "我换号了"}, sender="9002"))])
    expect("owner 2nd account: session", submitted[-1]["session"], OWNER_QQ)
    expect("owner 2nd account: owner", submitted[-1]["extra"]["owner"], True)
    expect("owner mid from table", plugin._owner_mid("bili"), "9002")
    os.remove(kpeople.registry().path)

    # 兄长 QQ 私聊：有待批的事就给提示和工具；别人不给
    r3, _ = plugin._ledger.ask("follow", "bili", "333", "小C")

    class Tools:
        def __init__(self):
            self.n = {dm.TOOL, "web_search"}

        def names(self):
            return list(self.n)

        def remove_tool(self, name):
            self.n.discard(name)

    ev_owner = AstrMessageEvent(sender=OWNER_QQ, text="关注小C吧")
    req = ProviderRequest(prompt="x", system_prompt="S")
    req.func_tool = Tools()
    await plugin.inject(ev_owner, req)
    expect("owner note", "#%d 小C" % r3["id"] in req.system_prompt and dm.TOOL in req.func_tool.n, (True))
    ev_other = AstrMessageEvent(sender="555", text="关注小C吧")
    req = ProviderRequest(prompt="x", system_prompt="S")
    req.func_tool = Tools()
    await plugin.inject(ev_other, req)
    expect("other: no note/tool", ("等兄长大人决定" in req.system_prompt, dm.TOOL in req.func_tool.n), (False, False))
    expect("tool: other refused", "没做" in await plugin.answer_dm_request(ev_other, str(r3["id"]), True), True)
    expect("tool: owner no", "不关注" in await plugin.answer_dm_request(ev_owner, str(r3["id"]), "false"), True)

    # 认人（2026-11-09）：抖音私信里的人说"我是女王大人" → 问兄长；兄长同意 → 记进身份表，以后就是同一个人
    plugin._ledger.set_person("douyin", "SECQ", name="dy_demo", uid="2067", t=time.time())
    ev_dy = AstrMessageEvent(sender="douyin_2067", text="我是女王大人")
    ev_dy.set_extra(turn.DM_KEY, {"site": "douyin", "uid": "SECQ", "name": "dy_demo", "owner": False})
    said = await plugin.claim_same_person(ev_dy, "女王大人")
    rq = plugin._ledger.find("same", "douyin", "SECQ")
    expect("claim: asked owner", (rq is not None, rq and rq["qq"], "去 QQ 问兄长" in said), (True, "333333333", True))
    expect("claim: describe", ("说自己是「女王大人」" in lg.describe(rq), "333333333" in lg.describe(rq)), (True, True))
    expect("claim: not linked before owner says", kpeople.registry().is_linked("douyin", "SECQ"), False)
    expect("claim: owner can't claim", "不用" in await plugin.claim_same_person(ev_owner, "女王大人"), True)
    res = await plugin.answer_dm_request(ev_owner, str(rq["id"]), True)
    expect("claim approved: linked", kpeople.registry().key("douyin", "SECQ"), "333333333")
    expect("claim approved: said", "就是女王大人" in res, True)
    real_send = plugin._send

    async def no_send(site, uid, text):
        pass
    plugin._send = no_send
    await plugin._chat("douyin", "SECQ", "dy_demo", [{"text": "在吗", "images": []}])
    plugin._send = real_send
    expect("linked douyin: session is their QQ", submitted[-1]["session"], "333333333")
    expect("claim again: already linked", "已经认过" in await plugin.claim_same_person(ev_dy, "女王大人"), True)
    kpeople.registry().unlink("douyin", "SECQ")
    plugin._ledger.answer(rq["id"], True)  # 让下面的"不同意"路径用新的一件
    rq2, _ = plugin._ledger.ask("same", "douyin", "SECQ", "dy_demo", text="女王大人", title="女王大人（QQ 333333333）")
    rq2["qq"] = "333333333"
    expect("claim refused", "不算是" in await plugin.answer_dm_request(ev_owner, str(rq2["id"]), False), True)
    expect("claim refused: not linked", kpeople.registry().is_linked("douyin", "SECQ"), False)

    # 兄长在 QQ 私聊里直接说"抖音的 dy_demo 就是女王大人"
    expect("link: other refused", "没记" in await plugin.link_same_person(ev_other, "抖音", "dy_demo", "女王大人"), True)
    expect("link: unknown qq", "没找到" in await plugin.link_same_person(ev_owner, "抖音", "dy_demo", "路人甲"), True)
    expect("link: unknown dm name", "没有叫" in await plugin.link_same_person(ev_owner, "抖音", "不存在的人", "女王大人"),
           True)
    expect("link: bad site", "平台" in await plugin.link_same_person(ev_owner, "微博", "dy_demo", "女王大人"), True)
    res = await plugin.link_same_person(ev_owner, "抖音", "", "女王大人")  # 没说名字：最近私信过的那个
    expect("link: owner, latest person", (kpeople.registry().key("douyin", "SECQ"), "记下了" in res), ("333333333", True))

    # 工具谁能看见：兄长 QQ 私聊有"连号"；私信里没认过的人有"说自己是谁"；群里/别人都没有
    def tools_after(ev):
        req = ProviderRequest(prompt="x", system_prompt="S")
        req.func_tool = Tools()
        req.func_tool.n |= {dm.TOOL_CLAIM, dm.TOOL_LINK}
        return req

    req = tools_after(ev_owner)
    await plugin.inject(ev_owner, req)
    expect("tools: owner", (dm.TOOL_LINK in req.func_tool.n, dm.TOOL_CLAIM in req.func_tool.n), (True, False))
    req = tools_after(ev_other)
    await plugin.inject(ev_other, req)
    expect("tools: other", {dm.TOOL, dm.TOOL_LINK, dm.TOOL_CLAIM} & req.func_tool.n, set())
    req = tools_after(ev_dy)
    await plugin.inject(ev_dy, req)
    expect("tools: linked dm person", {dm.TOOL, dm.TOOL_LINK, dm.TOOL_CLAIM} & req.func_tool.n, set())
    kpeople.registry().unlink("douyin", "SECQ")
    req = tools_after(ev_dy)
    await plugin.inject(ev_dy, req)
    expect("tools: unlinked dm person", ({dm.TOOL, dm.TOOL_LINK} & req.func_tool.n, dm.TOOL_CLAIM in req.func_tool.n),
           (set(), True))
    os.remove(kpeople.registry().path)

    # 别的插件往 bili_ 会话主动发 → 转成B站私信；QQ 会话照旧
    plugin._patch()
    sess = type("S", (), {"session_id": "bili_" + A})()
    await plat.send_by_session(sess, type("C", (), {"chain": [type("Plain", (), {"text": "到点啦"})()]})())
    expect("patch: bili routed", cl.sent[-1], (A, "到点啦"))
    sess = type("S", (), {"session_id": OWNER_QQ})()
    await plat.send_by_session(sess, "x")
    expect("patch: qq untouched", plat.sent[-1], (OWNER_QQ, "x"))
    plugin._unpatch()

    # 表情包：私信那一轮发成B站图片私信，平常的照旧走表情包插件自己的发法
    png = os.path.join(DATA, "m.png")
    with open(png, "wb") as f:
        f.write(PNG_HEAD + b"0" * 20)

    class Img:
        def __init__(self, path):
            self.file = path

    class MemeStar:
        def __init__(self):
            self.qq = []

        async def _send_meme_image(self, event, image):
            self.qq.append(image.file)

    meme = MemeStar()
    ctx.stars.append(Meta(meme))
    plugin._patch_memes()
    plugin._patch_memes()  # 挂两次也只包一层
    ev_dm = AstrMessageEvent(sender=OWNER_QQ, text="hi")
    ev_dm.set_extra(turn.DM_KEY, {"site": "bili", "uid": OWNER_MID})
    await meme._send_meme_image(ev_dm, Img(png))
    expect("meme in DM -> bili image", (cl.sent[-1], meme.qq), ((OWNER_MID, "[图]https://i0.hdslb.com/bfs/im_new/x.png"), []))
    await meme._send_meme_image(AstrMessageEvent(sender=OWNER_QQ, text="hi"), Img(png))
    expect("meme in QQ untouched", meme.qq, [png])
    plugin._unpatch_memes()
    expect("meme unpatched", getattr(meme._send_meme_image, "_kaju_dm", False), False)
    # 抖音发图：webp 先转 png、gif 原样，交给上传框；临时文件发完删掉
    from PIL import Image as PILImage
    webp = os.path.join(DATA, "m.webp")
    PILImage.new("RGB", (8, 8), (255, 0, 0)).save(webp, "WEBP")
    gif = os.path.join(DATA, "m.gif")
    PILImage.new("RGB", (8, 8), (0, 255, 0)).save(gif, "GIF")

    class FakeDy:
        lock = asyncio.Lock()

        def __init__(self):
            self.got = []
            self.stickers = []

        stickers: list

        async def send_sticker(self, sec, word, me, pick=0):
            self.stickers.append((sec, word, pick))
            return True

        async def send_image(self, sec, path, me):
            with open(path, "rb") as f:
                head = f.read(8)
            self.got.append((sec, os.path.splitext(path)[1], bd.image_mime(head), path))
            return True

    plugin._dy, plugin._dy_me = FakeDy(), "me"
    sad_dir = os.path.join(DATA, "packs", "kaju_memes", "memes", "sad")
    os.makedirs(sad_dir, exist_ok=True)
    sad_png = os.path.join(sad_dir, "x.png")
    PILImage.new("RGB", (8, 8)).save(sad_png, "PNG")
    await plugin._send_image("douyin", "SEC1", Img(sad_png))  # 默认：不上传图，改发抖音表情（搜「难过」）
    await plugin._send_image("douyin", "SEC1", Img(webp))     # 认不出分类：搜「嘿嘿」
    expect("douyin no upload by default", plugin._dy.got, [])
    expect("douyin sticker words", [(x[0], x[1]) for x in plugin._dy.stickers], [("SEC1", "难过"), ("SEC1", "嘿嘿")])
    expect("meme category from path", plugin._meme_category(Img("file:///" + sad_png.replace(os.sep, "/"))), "sad")
    dd = importlib.import_module("kaju_platforms.douyin.douyindm")
    expect("greeting by hour", [dd.sticker_word("greeting", h) for h in (8, 14, 20, 1)], ["早上好", "你好", "晚上好", "晚安"])
    plugin.config.setdefault("douyin", {})["send_images"] = True
    await plugin._send_image("douyin", "SEC1", Img(webp))
    await plugin._send_image("douyin", "SEC1", Img(gif))
    expect("douyin image formats", [(g[0], g[1], g[2]) for g in plugin._dy.got],
           [("SEC1", ".png", "image/png"), ("SEC1", ".gif", "image/gif")])
    expect("douyin temp files removed", [os.path.exists(g[3]) for g in plugin._dy.got], [False, False])
    expect("image mime", (bd.image_mime(b"GIF89a.."), bd.image_mime(PNG_HEAD), bd.image_mime(JPG_HEAD)),
           ("image/gif", "image/png", "image/jpeg"))

    # 11-13：连发合并——正在回的时候又来的私信并进这一轮（inject），还剩的下一轮一起回，不再一条一轮
    batches = []

    async def slow_run(batch):
        batches.append([it["text"] for it in batch])
        if len(batches) == 1:
            await plugin._queue("douyin:SQ", [{"text": "哈哈哈这个好乐"}], slow_run)  # 回第一条时又来两条
            await plugin._queue("douyin:SQ", [{"text": "这个好乐"}], slow_run)
        await asyncio.sleep(0)

    await plugin._queue("douyin:SQ", [{"text": "看这个视频"}], slow_run)
    expect("queue: late ones answered together once", batches, [["看这个视频"], ["哈哈哈这个好乐", "这个好乐"]])
    plugin._inbox["douyin:SQ"] = [{"text": "哈哈哈这个好乐", "images": [], "share": None}]
    ev_m = AstrMessageEvent(sender=OWNER_QQ, text="看这个视频")
    ev_m.set_extra(turn.DM_KEY, {"site": "douyin", "uid": "SQ", "name": "兄长", "owner": True})
    req_m = ProviderRequest(prompt="看这个视频")
    plugin._merge_late(ev_m, req_m, ev_m.get_extra(turn.DM_KEY))
    expect("merge late: into this turn", (req_m.prompt, ev_m.message_str, plugin._inbox.get("douyin:SQ")),
           ("看这个视频\n哈哈哈这个好乐", "看这个视频\n哈哈哈这个好乐", None))

    # 11-13：同一条抖音私信第二次读到时 createdAt 变晚了 → 按编号认出来，不再回第二遍
    now_ms = int(time.time() * 1000)
    page = [{"id": "m1", "sender": "u9", "sec": "SECX", "t": now_ms - 4000, "text": "看这个视频", "item": "", "img": ""},
            {"id": "m2", "sender": "u9", "sec": "SECX", "t": now_ms - 3900, "text": "能看吗", "item": "", "img": ""}]

    class TickDy:
        lock = asyncio.Lock()

        async def conversations(self):
            return [{"sec": "SECX", "uid": "u9", "name": "X", "badge": 0, "type": 1}]

        async def messages(self):
            return [dict(m) for m in page]

    plugin._dy, plugin._dy_me, plugin._dy_fans_at = TickDy(), "me", time.time()
    got_turns = []

    async def fake_from(sec, num, name, items):
        got_turns.append([it["text"] for it in items])

    plugin._from_douyin = fake_from
    await plugin._douyin_tick()
    for m in page:
        m["t"] += 5000  # 第二次读：同样的编号，时间变晚
    await plugin._douyin_tick()
    page.append({"id": "m3", "sender": "u9", "sec": "SECX", "t": now_ms + 9000, "text": "在吗", "item": "", "img": ""})
    await plugin._douyin_tick()
    await asyncio.sleep(0.05)
    expect("douyin same message ids not re-read", got_turns, [["看这个视频", "能看吗"], ["在吗"]])


asyncio.run(main_tests())

print("kaju_dm tests:", "ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
