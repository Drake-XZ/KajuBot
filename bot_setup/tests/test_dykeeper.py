"""Offline tests for kaju_basics 1.28.0 抖音小号常驻浏览器（dykeeper.py + main._dy_keep_tick）.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_dykeeper.py
"""

import asyncio
import contextlib
import importlib
import os
import sys
import tempfile
import types

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

dk = importlib.import_module("kaju_platforms.douyin.dykeeper")
dy = importlib.import_module("kaju_platforms.douyin.douyin")
km = importlib.import_module("kaju_basics.main")

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


expect("self ok", dk.parse_self({"status_code": 0, "user": {"uid": "1", "nickname": "温水小佳树"}}),
       {"state": "ok", "nickname": "温水小佳树", "uid": "1"})
expect("self out", dk.parse_self({"status_code": 8, "user": None})["state"], "out")
expect("self unknown", dk.parse_self({"raw": "x"})["state"], "unknown")
expect("chrome found", bool(dk.find_chrome()), True)
expect("douyin dance video", dy.is_music_video({"category": "二次元/宅舞", "desc": "#初音未来 #mmd"}), True)
expect("douyin music tag", dy.is_music_video({"tags": ["钢琴"], "desc": "x"}), True)
expect("douyin plain vlog", dy.is_music_video({"category": "生活/美食", "desc": "今天做了红烧肉", "tags": ["美食"]}), False)


class FakeKeeper:
    def __init__(self, me):
        self.me = me
        self.calls = []
        self.alive = False
        self.profile = "P"

    async def running(self, headless=None):
        return "http://x" if self.alive else ""

    async def whoami(self, p):
        self.calls.append("whoami")
        self.alive = True
        return dict(self.me)

    async def refresh(self, p):
        self.calls.append("refresh")

    async def stop(self):
        self.calls.append("stop")
        self.alive = False


class Store:
    def __init__(self, data):
        self.data = data
        self.saved = 0

    def save(self):
        self.saved += 1


@contextlib.asynccontextmanager
async def fake_pw():
    yield object()


dy._playwright = fake_pw


def plugin(me, data, logged=True):
    told = []
    self = types.SimpleNamespace(_dy_login=Store(data), _dy_keeper=FakeKeeper(me), told=told,
                                 log=types.SimpleNamespace(info=print, warning=print, debug=print, error=print))
    self._dy_logged = lambda: logged and not self._dy_login.data.get("gone")
    self._dy_num = lambda k, d: d
    self._sec = lambda name: {}
    self._dy_gone = lambda why: self._dy_login.data.__setitem__("gone", True)

    async def tell(text):
        told.append(text)
        return True
    self._tell_owner = tell
    self._warn_dy_gone = types.MethodType(km.KajuBasics._warn_dy_gone, self)
    self._dy_keep_tick = types.MethodType(km.KajuBasics._dy_keep_tick, self)
    return self


async def main():
    # 登录着：起来、问一次、刷新一次；名字记下来
    s = plugin({"state": "ok", "nickname": "温水小佳树", "uid": "1"}, {"login_at": 1})
    expect("ok said", await s._dy_keep_tick(), "登录着（温水小佳树）")
    expect("ok calls", s._dy_keeper.calls, ["whoami", "refresh"])
    expect("ok nickname", s._dy_login.data["nickname"], "温水小佳树")
    # 刚问过、还开着：不再问，也不刷新
    s._dy_keeper.calls.clear()
    expect("quiet tick", (await s._dy_keep_tick(), s._dy_keeper.calls), ("登录着", []))

    # 登录掉了：记 gone、关掉、告诉兄长（三天内只说一次）
    s = plugin({"state": "out", "nickname": "", "uid": ""}, {"login_at": 1})
    expect("out said", await s._dy_keep_tick(), "登录掉了")
    expect("out gone/stop", (s._dy_login.data.get("gone"), s._dy_keeper.calls), (True, ["whoami", "stop"]))
    expect("out told once", len(s.told), 1)
    s._dy_login.data["gone"] = False
    await s._dy_keep_tick()
    expect("out not told again", len(s.told), 1)

    # 没登录、但常驻浏览器还记着：关掉
    s = plugin({"state": "ok"}, {"keeper": {"port": 9350}}, logged=False)
    expect("not logged stops", (await s._dy_keep_tick(), s._dy_keeper.calls), ("没登录", ["stop"]))

    # _context 借常驻浏览器：资料夹对得上才借
    class FakePage:
        def __init__(self):
            self.closed = False

        async def set_viewport_size(self, v):
            pass

        def is_closed(self):
            return self.closed

        async def close(self):
            self.closed = True

    class FakeCtx:
        pages = []

        async def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeCtx()]
        disconnected = False

        async def close(self):
            FakeBrowser.disconnected = True

    class Chromium:
        async def connect_over_cdp(self, ep):
            return FakeBrowser()

    class K:
        profile = "D:\\prof"

        async def ensure(self, headless=True, url=""):
            return "http://127.0.0.1:9350"

    dy.KEEPER = K()
    p = types.SimpleNamespace(chromium=Chromium())
    async with dy._context(p, "chrome", "d:\\PROF") as ctx:
        pg = await ctx.new_page()
        expect("borrowed", (type(ctx).__name__, ctx._kaju_profile, ctx.pages == [pg]), ("_Borrowed", True, True))
    expect("borrowed page closed, browser only disconnected", (pg.closed, FakeBrowser.disconnected), (True, True))
    dy.KEEPER = None

    # 失效的 sessionid 还留着：session_id 有值，但问抖音是 out（扫码时不能当成"已经登录着"）
    class Resp:
        def __init__(self, d):
            self.d = d

        async def json(self):
            return self.d

    class Req:
        def __init__(self, d):
            self.d = d

        async def get(self, url, **kw):
            return Resp(self.d)

    class StaleCtx:
        def __init__(self, d):
            self.request = Req(d)

        async def cookies(self, url):
            return [{"name": "sessionid", "value": "old"}, {"name": "ttwid", "value": "x"}]

    stale = StaleCtx({"status_code": 8, "user": None})
    expect("stale sid kept", await dy.session_id(stale), "old")
    expect("stale whoami out", (await dy.whoami(stale))["state"], "out")
    expect("live whoami ok", (await dy.whoami(StaleCtx({"status_code": 0, "user": {"uid": "9", "nickname": "n"}})))["state"], "ok")


asyncio.run(main())
print("dykeeper tests:", "ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
