"""body 的发消息接口（AstrBody.send / private_chat_id / qq_call / add_to_history）和搬进 kaju_platforms 的
账号部分（shared.owner.Owner、bili.account.BiliAccount、douyin.account.DouyinAccount）。离线，不碰真数据。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_body_accounts.py
"""

import asyncio
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core / kaju_astr / kaju_platforms
sys.stdout.reconfigure(encoding="utf-8")
os.environ.pop("KAJU_DATA", None)
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from kaju_astr import AstrBody  # noqa: E402
from kaju_core import people  # noqa: E402
from kaju_platforms.bili import account as bili_account  # noqa: E402
from kaju_platforms.douyin import account as dy_account  # noqa: E402
from kaju_platforms.shared import owner as owner_mod  # noqa: E402

fails = 0


def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"got {got!r} want {want!r}")


class FakeBot:
    def __init__(self, res=None):
        self.calls, self.res = [], res

    async def call_action(self, action, **kw):
        self.calls.append((action, kw))
        return self.res if self.res is not None else {}


class FakeCM:
    def __init__(self, cid="c1"):
        self.cid, self.pairs = cid, []

    async def get_curr_conversation_id(self, umo):
        return self.cid

    async def add_message_pair(self, cid, user, assistant):
        self.pairs.append((cid, user, assistant))


class FakeContext:
    def __init__(self, bot=None, cid="c1"):
        self.sent, self.bot = [], bot
        self.conversation_manager = FakeCM(cid)

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))
        return True

    def get_platform(self, name):
        bot = self.bot
        return types.SimpleNamespace(meta=lambda: types.SimpleNamespace(id="qq_555555555"),
                                     get_client=lambda: bot)

    def get_all_stars(self):
        return []


async def body_tests():
    ctx = FakeContext(bot=FakeBot({"status": "ok", "retcode": 0, "data": {"group_name": "妖妖"}}))
    body = AstrBody(ctx)
    # 私聊会话 id：有已知会话借它的平台名，没有问平台
    expect("private id like", body.private_chat_id("111111111", like="qq_x:GroupMessage:1"), "qq_x:FriendMessage:111111111")
    expect("private id platform", body.private_chat_id("111111111"), "qq_555555555:FriendMessage:111111111")
    # qq_call：去掉外壳；消息自带客户端优先
    expect("qq_call unwraps", await body.qq_call("get_group_info", group_id=1), {"group_name": "妖妖"})
    own = FakeBot({"x": 1})
    turn = types.SimpleNamespace(bot=own)
    expect("qq_call turn bot", (await body.qq_call("a", turn=turn, k=2), own.calls), ({"x": 1}, [("a", {"k": 2})]))
    try:
        await AstrBody(FakeContext(bot=None)).qq_call("a")
        expect("qq_call no client raises", False, True)
    except RuntimeError:
        expect("qq_call no client raises", True, True)
    # send：图在前、文字在后；什么都没有就不发
    expect("send text+image", await body.send("u1", "看这个", image="C:/qr.png"), True)
    umo, chain = ctx.sent[-1]
    expect("send parts", (umo, [type(c).__name__ for c in chain.chain], chain.chain[0].path, chain.chain[1].text),
           ("u1", ["Image", "Plain"], "C:/qr.png", "看这个"))
    expect("send nothing", (await body.send("u1"), len(ctx.sent)), (False, 1))
    # add_to_history：写进当前对话；没有对话返回 False
    expect("history", (await body.add_to_history("u1", "U", "A"), ctx.conversation_manager.pairs),
           (True, [("c1", {"role": "user", "content": "U"}, {"role": "assistant", "content": "A"})]))
    expect("history no conversation", await AstrBody(FakeContext(cid="")).add_to_history("u1", "U", "A"), False)


class Host(owner_mod.Owner, bili_account.BiliAccount, dy_account.DouyinAccount):
    """kaju_basics 的样子：body、log、_sec、_describer。"""

    def __init__(self, body):
        self.body = body
        self.log = types.SimpleNamespace(info=print, warning=print, debug=print, error=print)
        self.config = {}
        self._describer = types.SimpleNamespace(download_dir=lambda: tempfile.gettempdir())
        self._bili_account_init()
        self._douyin_account_init()

    def _sec(self, name):
        return self.config.get(name) or {}


async def owner_tests():
    real_owner = people.owner
    people.owner = lambda: ""
    try:
        book = types.SimpleNamespace(owner="999", address_of=lambda qq: "")
        body = AstrBody(FakeContext(bot=FakeBot()))
        body.find = lambda attr: book if attr == "address_of" else None
        h = Host(body)
        expect("owner from address book", h._owner(), "999")
        body.find = lambda attr: None
        expect("owner default", h._owner(), "111111111")
        people.owner = lambda: "123"
        expect("owner from people", h._owner(), "123")
        expect("owner umo", h._owner_umo(types.SimpleNamespace(unified_msg_origin="qq_y:GroupMessage:5")),
               "qq_y:FriendMessage:123")
        bot = FakeBot()
        body.qq = lambda: (None, bot)
        expect("tell owner", (await h._tell_owner("hi"), bot.calls),
               (True, [("send_private_msg", {"user_id": 123, "message": [{"type": "text", "data": {"text": "hi"}}]})]))
        body.qq = lambda: (None, None)
        expect("tell owner offline", await h._tell_owner("hi"), False)
    finally:
        people.owner = real_owner


async def account_tests():
    h = Host(AstrBody(FakeContext(bot=FakeBot())))
    # B 站：没登录时的状态、群里不发二维码、退出
    expect("bili status", await h.bili_login_command("状态", "u", False), ("还没登录B站小号。私聊发「/佳树B站登录」扫码。", False))
    expect("bili group", await h.bili_login_command("", "u", True), ("扫码登录请私聊发我哦，二维码别发在群里。", False))
    expect("bili logout", (await h.bili_login_command("退出", "u", False))[0].startswith("B站小号退出了"), True)
    # 抖音：没登录、群里、重复、开始扫码（扫码本身换成假的）
    expect("dy status", await h.douyin_login_command("状态", "u", False), ("还没登录抖音小号。私聊发「/佳树抖音登录」扫码。", False))
    expect("dy group", await h.douyin_login_command("", "u", True), ("扫码登录请私聊发我哦，二维码别发在群里。", False))
    scans = []

    async def fake_scan(umo):
        scans.append(umo)
    h._douyin_scan = fake_scan
    expect("dy start", await h.douyin_login_command("", "u9", False), ("在电脑上开抖音登录窗口，二维码马上发过来…", True))
    await asyncio.sleep(0)
    expect("dy scan started", scans, ["u9"])
    h._dy_qr_task = None
    expect("dy duplicate", await h.douyin_login_command("", "u9", False), ("", True))
    expect("dy not logged", h._dy_logged(), False)
    expect("dy keep on by default", dy_account.douyin.KEEPER is h._dy_keeper, True)
    dy_account.douyin.KEEPER = None


def parts_tests():
    from kaju_core import parts

    class A:
        def feel_x(self):
            pass

    a1, a2 = A(), A()
    parts.register("t_a", a1)
    expect("parts find", parts.find("feel_x") is a1, True)
    parts.register("t_a", a2)  # 热重载：新实例顶掉旧的
    expect("parts newer wins", parts.find("feel_x") is a2, True)
    parts.unregister("t_a", a1)  # 旧实例停下时不能把新的去掉
    expect("parts old unregister keeps new", parts.get("t_a") is a2, True)
    # AstrBody.find：先找登记的，再翻插件表
    star = types.SimpleNamespace(address_of=lambda *a: "学长")
    ctx = FakeContext()
    ctx.get_all_stars = lambda: [types.SimpleNamespace(star_cls=star)]
    body = AstrBody(ctx)
    expect("body.find own part", body.find("feel_x") is a2, True)
    expect("body.find plugin table", body.find("address_of") is star, True)
    parts.unregister("t_a", a2)
    expect("parts gone", (parts.find("feel_x"), body.find("feel_x")), (None, None))


async def main():
    parts_tests()
    await body_tests()
    await owner_tests()
    await account_tests()


asyncio.run(main())
print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
