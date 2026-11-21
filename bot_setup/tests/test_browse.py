"""Offline tests for 佳树的 B 站小号（kaju_basics bililogin.py）和有许可时自己刷 B 站（browse.py + main.py），
plus kaju_heart.feel_browsed（browsed.py）.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_browse.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_browse.py --live
        真联网（不登录、只读）：要设备号、拿 WBI 密钥、刷一页首页推荐和热门、要一张登录二维码（不扫），只打印
"""

import asyncio
import importlib
import json
import os
os.environ.setdefault("KAJU_OWNER_QQ", "111111111")  # 测试里的假兄长（代码兜底读这个环境变量）
import sys
import tempfile
import time
import zoneinfo

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from astrbot.core.agent.tool import ToolSet  # noqa: E402

bl = importlib.import_module("kaju_platforms.bili.bililogin")
bw = importlib.import_module("kaju_platforms.shared.browse")
kb = importlib.import_module("kaju_basics.main")
hm = importlib.import_module("kaju_heart.main")
browsed = importlib.import_module("kaju_core.heart.browsed")
failures = []
OWNER = "111111111"
TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ WBI 签名、correspondPath、Cookie 解析
expect("mixin key (文档的例子)", bl.mixin_key("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
       "ea1db124af3c7062474693fa704f4ff8")
signed = bl.wbi_sign({"foo": "114", "bar": "514", "zab": 1919810}, "ea1db124af3c7062474693fa704f4ff8", now=1702204169)
expect("wbi sign (文档的例子)", (signed["w_rid"], signed["wts"]), ("8f6f2b5b3d485fe1886cec6a0be8c5d4", "1702204169"))
expect("wbi strips !'()*", bl.wbi_sign({"k": "a!b'(c)*"}, "x" * 32, now=1)["k"], "abc")
expect("wbi keys from nav", bl.wbi_keys({"wbi_img": {"img_url": "https://i0.hdslb.com/bfs/wbi/7cd0849.png",
                                                     "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caf.png"}}),
       ("7cd0849", "4932caf"))
expect("mixin key needs 64 chars", bl.mixin_key("abc", "def"), "")
p1, p2 = bl.correspond_path(1684466082562), bl.correspond_path(1684466082562)
expect("correspond path: 1024-bit RSA → 256 hex, OAEP random", (len(p1), all(c in "0123456789abcdef" for c in p1), p1 != p2),
       (256, True, True))
HTML = '<body>\n  <div id="1-name">b0cc8411ded2f9db2cff2edb3123acac</div>\n  <div id="token-iframe-app"></div>'
expect("refresh_csrf from correspond page", bl.parse_refresh_csrf(HTML), "b0cc8411ded2f9db2cff2edb3123acac")
expect("refresh_csrf missing", bl.parse_refresh_csrf("<html>404</html>"), "")
expect("set-cookie parse (drops empty)", bl.parse_set_cookie([
    "SESSDATA=abc%2C123%2Cx; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT; HttpOnly; Secure",
    "bili_jct=j1; Path=/; Domain=bilibili.com", "sid=; Path=/", "broken;;=="]),
    {"SESSDATA": "abc%2C123%2Cx", "bili_jct": "j1"})
expect("cookies from crossDomain url", bl.cookies_from_cross_url(
    "https://passport.biligame.com/crossDomain?DedeUserID=42&DedeUserID__ckMd5=ck&Expires=1&SESSDATA=s%2C1&bili_jct=j&gourl=x"),
    {"SESSDATA": "s,1", "bili_jct": "j", "DedeUserID": "42", "DedeUserID__ckMd5": "ck"})
expect("only bilibili hosts get cookies", (bl._host_ok("https://api.bilibili.com/x"), bl._host_ok("https://bilibili.com.evil.cn/x"),
                                           bl._host_ok("https://evil.cn/?bilibili.com")), (True, False, False))

# ------------------------------------------------------------------ 登录状态存文件
store_path = os.path.join(os.environ["STUB_DATA"], "t", "bili_login.json")
st = bl.Store(store_path)
st.cookies.update(buvid3="B3", buvid4="B4")
expect("not logged in: device cookies only", (st.logged_in, st.header()), (False, "buvid3=B3; buvid4=B4"))
st.set_login({"SESSDATA": "S", "bili_jct": "J", "DedeUserID": "42", "x": "nope"}, "RT", now=100)
st.save()
st2 = bl.Store(store_path)
expect("login saved + reloaded", (st2.logged_in, st2.data["refresh_token"], st2.header(), "x" in st2.cookies),
       (True, "RT", "SESSDATA=S; bili_jct=J; DedeUserID=42; buvid3=B3; buvid4=B4", False))
st2.data["gone"] = True
expect("gone → not logged in, no login cookies", (st2.logged_in, st2.header()), (False, "buvid3=B3; buvid4=B4"))
st2.logout()
expect("logout keeps device", (st2.cookies, "refresh_token" in st2.data), ({"buvid3": "B3", "buvid4": "B4"}, False))


# ------------------------------------------------------------------ 假网络：扫码、续期
class Headers(dict):
    def __init__(self, cookies=()):
        super().__init__()
        self.cookies = list(cookies)

    def getall(self, k, default=None):
        return list(self.cookies) if k == "Set-Cookie" else (default or [])


class Resp:
    def __init__(self, body, status=200, cookies=()):
        self.status = status
        self.body = body if isinstance(body, str) else json.dumps(body)
        self.headers = Headers(cookies)

    async def text(self, errors="strict"):
        return self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Net:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, headers=None, params=None, data=None, **kw):
        self.calls.append((method, url.split("?")[0], dict(headers or {}), dict(params or {}), dict(data or {})))
        hit = self.routes.get(url.split("?")[0])
        hit = hit(params or {}, data or {}, headers or {}) if callable(hit) else hit
        return hit if hit is not None else Resp({"code": -404}, 404)

    def get(self, url, headers=None, **kw):
        return self.request("GET", url, headers=headers, **kw)


P = bl.PASSPORT + "/x/passport-login/web"


async def login_tests():
    net = Net({P + "/qrcode/poll": lambda p, d, h: Resp({"code": 0, "data": {
        "code": 0, "refresh_token": "RT0",
        "url": "https://passport.biligame.com/crossDomain?DedeUserID=42&SESSDATA=fromurl&bili_jct=J0"}},
        cookies=["SESSDATA=S0; Path=/", "bili_jct=J0; Path=/", "DedeUserID=42; Path=/", "sid=SID0; Path=/"])})
    code, cookies, token = await bl.qr_poll(net, "k" * 32)
    expect("qr ok: cookies + token", (code, cookies, token),
           (0, {"DedeUserID": "42", "SESSDATA": "S0", "bili_jct": "J0", "sid": "SID0"}, "RT0"))
    expect("qr poll sends key", net.calls[0][3], {"qrcode_key": "k" * 32})
    net = Net({P + "/qrcode/poll": Resp({"code": 0, "data": {"code": 86090, "refresh_token": "", "url": ""}})})
    expect("qr scanned not confirmed", await bl.qr_poll(net, "k"), (86090, {}, ""))

    st = bl.Store(os.path.join(os.environ["STUB_DATA"], "t2", "bili_login.json"))
    st.set_login({"SESSDATA": "S0", "bili_jct": "J0", "DedeUserID": "42"}, "RT0")
    net = Net({P + "/cookie/info": Resp({"code": 0, "data": {"refresh": False, "timestamp": 1}})})
    expect("no refresh needed", await bl.refresh_if_needed(net, st), "不用刷新")
    expect("info sends csrf + cookie", (net.calls[0][3], "SESSDATA=S0" in net.calls[0][2]["Cookie"]), ({"csrf": "J0"}, True))

    net = Net({
        P + "/cookie/info": Resp({"code": 0, "data": {"refresh": True, "timestamp": 1684466082562}}),
        bl.WWW + "/correspond/1/" + "x": None,
        P + "/cookie/refresh": lambda p, d, h: Resp({"code": 0, "data": {"refresh_token": "RT1"}},
                                                   cookies=["SESSDATA=S1; Path=/", "bili_jct=J1; Path=/", "sid=SID1"]),
        P + "/confirm/refresh": Resp({"code": 0}),
    })
    corr = {}

    def correspond(p, d, h):
        corr["cookie"] = h.get("Cookie", "")
        return Resp(HTML)
    orig_req = net.request

    def request(method, url, headers=None, params=None, data=None, **kw):
        if "/correspond/1/" in url:
            net.calls.append((method, "correspond", dict(headers or {}), {}, {}))
            corr["path"] = url.rsplit("/", 1)[1]
            return correspond(params, data, headers or {})
        return orig_req(method, url, headers=headers, params=params, data=data, **kw)
    net.request = request
    expect("refresh flow", await bl.refresh_if_needed(net, st), "刷新了")
    refresh = next(c for c in net.calls if c[1].endswith("/cookie/refresh"))
    confirm = next(c for c in net.calls if c[1].endswith("/confirm/refresh"))
    expect("refresh posts csrf/refresh_csrf/token", refresh[4], {"csrf": "J0", "refresh_csrf": "b0cc8411ded2f9db2cff2edb3123acac",
                                                               "source": "main_web", "refresh_token": "RT0"})
    expect("confirm: new csrf + OLD token", confirm[4], {"csrf": "J1", "refresh_token": "RT0"})
    expect("new cookies + token stored", (st.cookies["SESSDATA"], st.cookies["bili_jct"], st.cookies["sid"],
                                          st.data["refresh_token"], st.data["refreshed_at"] > 0), ("S1", "J1", "SID1", "RT1", True))
    expect("correspond path is 256 hex, sent with cookie", (len(corr["path"]), "SESSDATA=S0" in corr["cookie"]), (256, True))

    net = Net({P + "/cookie/info": Resp({"code": -101, "message": "账号未登录"})})
    try:
        await bl.refresh_if_needed(net, st)
        expect("-101 raises LoginGone", False, True)
    except bl.LoginGone:
        expect("-101 → gone", st.data["gone"], True)
    st.data["gone"] = False
    net = Net({P + "/cookie/info": Resp({"code": 0, "data": {"refresh": True, "timestamp": 1}}),
               P + "/cookie/refresh": Resp({"code": 86095, "message": "refresh_csrf 错误"})})
    net.request = (lambda orig: lambda m, u, **kw: Resp(HTML) if "/correspond/" in u else orig(m, u, **kw))(net.request)
    try:
        await bl.refresh_if_needed(net, st)
        expect("86095 raises LoginGone", False, True)
    except bl.LoginGone:
        expect("86095 → gone", st.data["gone"], True)
    st.data.pop("refresh_token")
    st.data["gone"] = False
    net = Net({P + "/cookie/info": Resp({"code": 0, "data": {"refresh": True, "timestamp": 1}})})
    try:
        await bl.refresh_if_needed(net, st)
        expect("no refresh_token raises", False, True)
    except bl.LoginGone as e:
        expect("no refresh_token → LoginGone", "refresh_token" in str(e), True)


asyncio.run(login_tests())

# ------------------------------------------------------------------ 刷出来的列表
RCMD = {"code": 0, "data": {"item": [
    {"goto": "av", "bvid": "BV1QGxE6TEYs", "title": "小猫第一次见到雪", "duration": 95, "owner": {"name": "猫猫日记"},
     "business_info": None, "rcmd_reason": {"content": "1万点赞"}, "stat": {"view": 123456}, "is_followed": 0},
    {"goto": "av", "bvid": "BV1Dwx26mEb9", "title": "广告：买它", "duration": 30, "owner": {"name": "品牌"},
     "business_info": {"id": 1}},
    {"goto": "live", "bvid": "", "title": "直播中", "room_info": {}},
    {"goto": "av", "bvid": "BV1ztxx6gEdk", "title": "三小时游戏实况", "duration": 10800, "owner": {"name": "UP"}},
    {"goto": "av", "bvid": "BV1REx46NEc4", "title": "戚风蛋糕&amp;教程", "duraion": 300, "owner": {"name": "烘焙"},
     "is_followed": 1},
]}}
got = bw.parse_rcmd(RCMD)
expect("rcmd: no ads / live", [v["bvid"] for v in got], ["BV1QGxE6TEYs", "BV1ztxx6gEdk", "BV1REx46NEc4"])
expect("rcmd fields", (got[0]["up"], got[0]["duration"], got[0]["views"], got[0]["reason"], got[2]["title"], got[2]["duration"],
                       got[2]["reason"], got[0]["url"]),
       ("猫猫日记", 95, 123456, "1万点赞", "戚风蛋糕&教程", 300, "已关注", "https://www.bilibili.com/video/BV1QGxE6TEYs"))
SEARCH = {"code": 0, "data": {"result": [
    {"type": "video", "bvid": "BV1Cfni6cELz", "title": '<em class="keyword">猫</em>咪踩奶合集', "author": "喵",
     "duration": "3:05", "play": 999, "typename": "动物圈"},
    {"type": "video", "bvid": "BV1abc", "title": "坏的 BV"},
]}}
s = bw.parse_search(SEARCH)
expect("search: strip em, mm:ss, bad bv dropped", [(v["title"], v["duration"], v["tname"]) for v in s], [("猫咪踩奶合集", 185, "动物圈")])
expect("h:mm:ss", bw._dur("1:02:03"), 3723)
POP = {"code": 0, "data": {"list": [{"bvid": "BV1Sd5v6QEJD", "title": "热门", "duration": 600, "owner": {"name": "x"},
                                      "tname": "知识", "rcmd_reason": {"content": "百万播放"}, "stat": {"view": 2000000}}]}}
expect("popular", [(v["bvid"], v["tname"], v["reason"]) for v in bw.parse_popular(POP)], [("BV1Sd5v6QEJD", "知识", "百万播放")])
ok = bw.usable(got + got, {"BV1REx46NEc4": 1}, 12 * 60)
expect("usable: no seen / too long / dupes", [v["bvid"] for v in ok], ["BV1QGxE6TEYs"])
lines = bw.candidate_lines(got[:1])
expect("candidate line", lines, "1. 《小猫第一次见到雪》（UP主 猫猫日记，1分35秒，12.3万播放，1万点赞）")
pp = bw.pick_prompt(got, 2, tastes="【你自己慢慢长出来的喜好】\n- 喜欢：猫的视频", topic="猫")
expect("pick prompt has tastes / topic / n", ("喜欢：猫的视频" in pp, "\"猫\"相关" in pp, "最多 2 个" in pp, "3. 《戚风蛋糕&教程》" in pp),
       (True, True, True, True))
picked = bw.parse_pick('好的：[{"i": 3, "why": "想学着做给兄长大人"}, {"i": 3}, {"i": 9}, {"i": "1", "why": "好可爱"}, {"i": 2}]', got, 2)
expect("parse pick: order, dupes, range, cap", [(v["bvid"], v["why"]) for v in picked],
       [("BV1REx46NEc4", "想学着做给兄长大人"), ("BV1QGxE6TEYs", "好可爱")])
expect("parse pick: junk", (bw.parse_pick("不想看", got, 2), bw.parse_pick("[]", got, 2)), ([], []))

# ------------------------------------------------------------------ 给兄长私聊看的提示
log = bw.Log(os.path.join(os.environ["STUB_DATA"], "t3", "browse.json"))
now = time.time()
expect("no sessions → no note", bw.chat_note(log, now, TZ), "")
log.data["running"] = {"t0": now, "items": [{"title": "a"}]}
expect("running note", bw.chat_note(log, now, TZ).startswith("【你正在刷B站】") and "已经看完 1 个" in bw.chat_note(log, now, TZ), True)
log.data.pop("running")
log.data["sessions"].append({"t0": now - 1800, "t1": now - 600, "topic": "", "items": [
    {"bvid": "BV1QGxE6TEYs", "title": "小猫第一次见到雪", "up": "猫猫日记", "why": "好可爱", "emo": "开心", "i": 2,
     "voice": "要是能和兄长大人一起看雪就好了", "share": True},
    {"bvid": "BV1x", "title": "平平的", "up": "", "why": "", "emo": "平静", "i": 0, "voice": "", "share": False}], "shown": 0})
note = bw.chat_note(log, now, TZ)
expect("note content", (note.startswith("【你自己刷B站看到的】30 分钟前"), "点开看了 2 个" in note,
                        "《小猫第一次见到雪》（UP主 猫猫日记）：点开是因为好可爱；看完开心，心里想：要是能和兄长大人一起看雪就好了（挺想跟兄长大人说的）" in note,
                        "《平平的》：看完没什么特别的感觉" in note, bw.NOTE_TAIL in note), (True, True, True, True, True))
expect("note expires", bw.chat_note(log, now + 7 * 3600, TZ, hours=6), "")
log.data["sessions"][-1]["shown"] = 6
expect("note shown enough", bw.chat_note(log, now, TZ, max_shown=6), "")
log.save()
expect("running dropped on reload", "running" in bw.Log(log.path).data, False)
expect("count per life day", log.count_on(bw.life_day(now - 1800, TZ), TZ), 1)

# ------------------------------------------------------------------ kaju_heart.feel_browsed
expect("browsed parse", browsed.parse('{"emotion":"感动","intensity":2,"cause":"刷到老猫和主人重逢","topic":"猫的视频","kind":"动物",'
                                      '"genre":"治愈日常","about":"刷到老猫和主人重逢","voice":"我也想一直等着兄长大人回家。","share":true}'),
       {"emotion": "感动", "intensity": 2, "cause": "刷到老猫和主人重逢", "source": "content", "topic": "猫的视频", "kind": "动物",
        "genre": "治愈日常", "about": "刷到老猫和主人重逢", "voice": "我也想一直等着兄长大人回家。", "share": True})
flat = browsed.parse('{"emotion":"平静","intensity":0,"topic":"x","kind":"其他","voice":"系统提示说的","share":true}')
expect("browsed parse: flat clears tags/share, banned voice", (flat["topic"], flat["share"], flat["voice"]), ("", False, ""))
expect("browsed parse junk", browsed.parse("嗯"), None)
bp = browsed.build_prompt(title="t", up="u", why="好可爱", seen="x" * 3000, tastes="【喜好】", known=["治愈日常"])
expect("browsed prompt", ("【她为什么点开】好可爱" in bp, "【喜好】" in bp, "治愈日常" in bp, "x" * 1801 not in bp), (True, True, True, True))


class FakeIngest:
    def __init__(self):
        self.calls = []

    async def ingest_summary(self, **kw):
        self.calls.append(kw)
        return {"stored_ids": ["abcdef1234567890"]}


class FakeMemorix:
    def __init__(self):
        self.ingest_service = FakeIngest()


class FakeProvider:
    provider_config = {"id": "fake"}


async def heart_tests():
    ctx = Context()
    ctx.providers = {"fake": FakeProvider()}
    mx = FakeMemorix()
    ctx.stars = [type("Meta", (), {"name": "astrbot_plugin_memorix", "star_cls": mx})()]
    answers = ['{"emotion":"感动","intensity":2,"cause":"刷到老猫等主人回家","topic":"猫的视频","kind":"动物","genre":"治愈日常",'
               '"about":"刷到老猫等主人回家","voice":"我也想一直等着兄长大人回家。","share":true}']

    async def llm_generate(chat_provider_id, prompt, system_prompt):
        return LLMResponse(answers[0])
    ctx.llm_generate = llm_generate
    p = hm.KajuHeart(ctx, {})
    p._state["inner_log"].append({"chat": "p" + OWNER, "session": OWNER, "scope": "aiocqhttp", "umo": "qq:FriendMessage:" + OWNER})
    people_before = json.dumps(p._state["people"], sort_keys=True)
    v = await p.feel_browsed({"title": "老猫等主人", "up": "猫", "why": "好可爱", "seen": "看完了……", "bvid": "BV1QGxE6TEYs"},
                             "qq:FriendMessage:" + OWNER)
    expect("feel: verdict", (v["emotion"], v["intensity"], v["share"], v["hash"]), ("感动", 2, True, "abcdef1234567890"))
    expect("feel: no affection change", json.dumps(p._state["people"], sort_keys=True), people_before)
    t = next((e for e in p._state["tastes"] if e["name"].strip("《》") == "猫的视频"), None)
    expect("feel: taste ledger, who=自己刷到的", (t is not None, (t or {}).get("who") or (t or {}).get("whos") or (t or {}).get("by")),
           (True, (t or {}).get("who") or (t or {}).get("whos") or (t or {}).get("by")))
    expect("feel: taste mentions self", "自己刷到的" in json.dumps(t, ensure_ascii=False), True)
    th = [x for x in p._open_threads("content")]
    expect("feel: 余韵 thread", (len(th), th[-1]["emo"] if th else "", th[-1]["chat"] if th else ""), (1, "感动", "p" + OWNER))
    last = p._state["inner_log"][-1]
    expect("feel: inner memory", (last["text"].startswith("【佳树心里】"), "自己刷B站（刷到老猫等主人回家）：我也想一直等着兄长大人回家。" in last["text"],
                                  last["browsed"]), (True, True, "BV1QGxE6TEYs"))
    call = mx.ingest_service.calls[-1]
    expect("feel: memorix in owner's private chat", (call["chat_id"], call["user_id"], call["group_id"], call["scope_key"]),
           (OWNER, OWNER, "", "aiocqhttp"))
    expect("feel: mood event", p._state["events"][-1]["src"], "content")
    answers[0] = '{"emotion":"平静","intensity":0,"voice":"","share":false}'
    n = len(mx.ingest_service.calls)
    v = await p.feel_browsed({"title": "平平", "seen": "…"}, "")
    expect("feel: flat → nothing stored", (v["emotion"], len(mx.ingest_service.calls) - n, v["hash"]), ("平静", 0, ""))
    answers[0] = "嗯？"
    expect("feel: junk → None", await p.feel_browsed({"title": "x"}, ""), None)
    await p.terminate()  # 停下（像线上停插件一样从 kaju_core.parts 注销）：后面的测试用插件表里的假心情


asyncio.run(heart_tests())


# ------------------------------------------------------------------ kaju_basics：工具、命令、后台刷、提示
class FakeHeartStar:
    def __init__(self):
        self.felt = []

    def taste_list(self, now=None):
        return "【你自己慢慢长出来的喜好】\n- 喜欢：猫的视频"

    async def feel_browsed(self, item, umo):
        self.felt.append((item, umo))
        return {"emotion": "开心", "intensity": 2, "voice": "好想摸摸它", "share": item["bvid"] == "BV1QGxE6TEYs"}


async def plugin_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    prompts = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        prompts.append((prompt, system_prompt))
        return LLMResponse('[{"i": 1, "why": "好可爱"}, {"i": 2, "why": "想学"}]')
    ctx.llm_generate = llm_generate
    heart = FakeHeartStar()
    ctx.stars = [type("Meta", (), {"star_cls": heart})()]
    b = kb.KajuBasics(ctx, {"browse": {"max_videos": 3, "daily_limit": 2}})
    expect("describer cookie: none", b._describer.cookie(), "")
    b.config["media"] = {"bili_cookie": "SESSDATA=cfg"}
    expect("describer cookie: config fallback", b._describer.cookie(), "SESSDATA=cfg")
    b._login.set_login({"SESSDATA": "mine", "bili_jct": "j"}, "rt")
    expect("describer cookie: login first", b._describer.cookie(), "SESSDATA=mine; bili_jct=j")
    b._login.logout()

    cands = [bw._video("BV1QGxE6TEYs", "小猫第一次见到雪", "猫猫日记", 95), bw._video("BV1REx46NEc4", "戚风蛋糕教程", "烘焙", 300),
             bw._video("BV1ztxx6gEdk", "第三个", "UP", 60)]

    async def candidates(topic):
        candidates.topics.append(topic)
        return cands, "首页推荐（没登录）"
    candidates.topics = []
    b._browse_candidates = candidates
    watched = []

    async def bili_video(url, event, danmaku=False):
        watched.append((url, event.unified_msg_origin, event.bot))
        if "BV1REx46NEc4" in url:
            return None, "没打开：要登录才能看"
        return {"title": "小猫第一次见到雪", "up": "猫猫日记"}, "[Bilibili video: 看完了，观后笔记：小猫踩雪……]"
    b._describer.bili_video = bili_video

    friend = AstrMessageEvent(sender=OWNER, text="去刷会儿B站吧")
    stranger = AstrMessageEvent(sender="999", text="去刷B站")
    expect("tool: stranger refused", (await b.browse_bilibili(stranger)).startswith("没去：只有兄长大人本人"), True)
    said = await b.browse_bilibili(friend, minutes=10, topic="猫")
    expect("tool: owner starts", (said.startswith("开始刷B站了（在后台看，最多 10 分钟、3 个视频），先找「猫」相关的"), "别说看到了什么" in said),
           (True, True))
    expect("tool: already running", await b.browse_bilibili(friend), "已经在刷B站了，还没看完（看完了 0 个）。 用佳树的口吻如实告诉兄长大人。")
    expect("tool: same topic again", (await b.browse_bilibili(friend, topic="猫")).startswith("已经在B站上找「猫」相关的了"), True)
    await b._browsing
    expect("browse: topic passed", candidates.topics, ["猫"])
    expect("browse: pick prompt has tastes + topic", ("喜欢：猫的视频" in prompts[-1][0], "\"猫\"相关" in prompts[-1][0],
                                                       prompts[-1][1] == bw.PICK_SYSTEM), (True, True, True))
    expect("browse: watched picks with owner's private umo, no bot",
           watched, [("https://www.bilibili.com/video/BV1QGxE6TEYs", "qq:FriendMessage:" + OWNER, None),
                     ("https://www.bilibili.com/video/BV1REx46NEc4", "qq:FriendMessage:" + OWNER, None)])
    sess = b._browse_log.data["sessions"][-1]
    expect("browse: session saved", (sess["topic"], sess["source"], [i["title"] for i in sess["items"]], sess["items"][0]["voice"],
                                     sess["items"][0]["share"], "running" in b._browse_log.data),
           ("猫", "首页推荐（没登录）", ["小猫第一次见到雪"], "好想摸摸它", True, False))
    expect("browse: both marked seen", sorted(b._browse_log.data["seen"]), ["BV1QGxE6TEYs", "BV1REx46NEc4"])
    expect("browse: heart got the watch text", (heart.felt[0][0]["seen"].startswith("[Bilibili video"), heart.felt[0][0]["why"],
                                               heart.felt[0][1]), (True, "好可爱", "qq:FriendMessage:" + OWNER))

    req = ProviderRequest(system_prompt="BASE")
    req.func_tool = ToolSet([type("T", (), {"name": "browse_bilibili"})()])
    await b.browse_note(friend, req)
    expect("note in owner's private chat", ("【你自己刷B站看到的】" in req.system_prompt, "好想摸摸它" in req.system_prompt,
                                            req.func_tool.names(), sess["shown"]), (True, True, ["browse_bilibili"], 1))
    req2 = ProviderRequest(system_prompt="BASE")
    req2.func_tool = ToolSet([type("T", (), {"name": "browse_bilibili"})()])
    await b.browse_note(stranger, req2)
    expect("stranger: no note, tool hidden", (req2.system_prompt, req2.func_tool.names()), ("BASE", []))
    grp = AstrMessageEvent(sender=OWNER, group="222222222", text="hi")
    req3 = ProviderRequest(system_prompt="BASE")
    req3.func_tool = ToolSet([type("T", (), {"name": "browse_bilibili"})()])
    await b.browse_note(grp, req3)
    expect("owner in group: tool kept, note too", ("【你自己刷B站看到的】" in req3.system_prompt, req3.func_tool.names()), (True, ["browse_bilibili"]))

    expect("daily limit", b.start_browsing(friend), "开始刷B站了（在后台看，最多 20 分钟、3 个视频）")
    await b._browsing
    expect("daily limit reached", b.start_browsing(friend).startswith("没去成：今天已经刷了 2 次了"), True)
    b.config["browse"]["enable"] = False
    expect("disabled", b.start_browsing(friend), "没去成：刷B站的功能关着。")

    out = [x async for x in b.cmd_bili_login(friend, "状态")]
    expect("login status: not logged in", out, ["还没登录B站小号。私聊发「/佳树B站登录」扫码。"])
    out = [x async for x in b.cmd_bili_login(grp)]
    expect("login in group refused", out, ["扫码登录请私聊发我哦，二维码别发在群里。"])
    out = [x async for x in b.cmd_browse(friend, "记录")]
    expect("browse record", out[0].startswith("【你自己刷B站看到的】"), True)
    await b.terminate()


asyncio.run(plugin_tests())


# ------------------------------------------------------------------ 刷抖音：同一套流程，候选从抖音精选来，看用 douyin_video
async def douyin_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    prompts = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None, contexts=None):
        prompts.append((prompt, system_prompt))
        return LLMResponse('[{"i": 1, "why": "想看小猫"}]')
    ctx.llm_generate = llm_generate
    heart = FakeHeartStar()
    ctx.stars = [type("Meta", (), {"star_cls": heart})()]
    b = kb.KajuBasics(ctx, {"browse": {"max_videos": 2, "daily_limit": 5, "share": False}})
    dy_cand = {"bvid": "dy7703997413695219810", "aid": "7703997413695219810", "title": "小猫踩奶", "up": "猫猫日常",
               "duration": 30, "reason": "", "views": 0, "likes": 12000, "tname": "萌宠", "site": "douyin",
               "url": "https://www.douyin.com/video/7703997413695219810"}
    calls = []

    async def browse_list(profile, topic="", **kw):
        calls.append((profile, topic))
        return [dict(dy_cand)], "抖音精选（没登录）", ("抖音搜索要人机验证，没搜成" if topic else "")
    kb.douyin.browse_list = browse_list
    watched = []

    async def douyin_video(url, event):
        watched.append(url)
        return {"title": "小猫踩奶", "author": "猫猫日常"}, "抖音视频《小猫踩奶》（作者：猫猫日常，30秒）。看完了。"
    b._describer.douyin_video = douyin_video

    async def no_bili(*a, **k):
        raise AssertionError("刷抖音不该去看 B 站")
    b._describer.bili_video = no_bili
    owner = AstrMessageEvent(sender=OWNER, text="去刷会儿抖音吧")
    stranger = AstrMessageEvent(sender="999", text="去刷抖音")
    expect("dy tool: stranger refused", (await b.browse_douyin(stranger)).startswith("没去：只有兄长大人本人能让你去刷抖音"), True)
    said = await b.browse_douyin(owner, minutes=10, topic="猫")
    expect("dy tool: owner starts", said.startswith("开始刷抖音了"), True)
    expect("dy: bili request while running is queued", b.start_browsing(owner, site="bili").startswith("换过去了：手上正在看的这个看完，就去刷B站（"), True)
    b._browse_next = None
    await b._browsing
    sess = b._browse_log.data["sessions"][-1]
    expect("dy: not logged in → no profile, topic tried", calls, [("", "猫")])
    expect("dy: search miss → picked from 精选 without the topic", ("\"猫\"相关" in prompts[-1][0], "抖音" in prompts[-1][1],
                                                                   "作者 猫猫日常" in prompts[-1][0], "1.2万赞" in prompts[-1][0]),
           (False, True, True, True))
    expect("dy: watched with douyin_video", watched, [dy_cand["url"]])
    expect("dy: session", (sess["site"], sess["miss"], sess["items"][0]["up"], sess["items"][0]["url"],
                           "dy7703997413695219810" in b._browse_log.data["seen"]),
           ("douyin", "抖音搜索要人机验证，没搜成", "猫猫日常", dy_cand["url"], True))
    expect("dy: heart told it was douyin", heart.felt[-1][0]["site"], "douyin")
    note = bw.chat_note(b._browse_log, time.time(), TZ)
    expect("dy: note", (note.startswith("【你自己刷抖音看到的】"), "但抖音搜索要人机验证，没搜成，刷的是精选" in note,
                        "（作者 猫猫日常）" in note), (True, True, True))
    sp = bw.share_prompt(sess["items"][0], "看完了", asked="猫", site="douyin", miss=sess["miss"])
    expect("dy: share prompt honest about the miss", ("刷抖音" in sp, "没搜成" in sp, "作者 猫猫日常" in sp), (True, True, True))
    req = ProviderRequest(system_prompt="BASE")
    req.func_tool = ToolSet([type("T", (), {"name": "browse_bilibili"})(), type("T", (), {"name": "browse_douyin"})()])
    await b.browse_note(stranger, req)
    expect("dy: stranger has neither tool", req.func_tool.names(), [])
    b.config["browse"]["douyin"] = False
    expect("dy: switch off", b.start_browsing(owner, site="douyin"), "没去成：刷抖音的功能关着。")
    out = [x async for x in b.cmd_douyin_login(owner, "状态")]
    expect("dy login status: not logged in", out, ["还没登录抖音小号。私聊发「/佳树抖音登录」扫码。"])
    out = [x async for x in b.cmd_douyin_login(AstrMessageEvent(sender=OWNER, group="222222222", text="x"))]
    expect("dy login in group refused", out, ["扫码登录请私聊发我哦，二维码别发在群里。"])
    await b.terminate()


asyncio.run(douyin_tests())


# ------------------------------------------------------------------ kaju_learn：看完的视频交给它学；没说看什么时去搜想弄明白的事
class FakeLearner:
    def __init__(self):
        self.jobs = []

    def wonder_topic(self, now=None):
        return {"kw": "终末地 陈千语", "q": "陈千语在终末地里是什么样的角色"}

    async def learn_content(self, **kw):
        self.jobs.append(kw)


async def learner_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    prompts = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        prompts.append(prompt)
        return LLMResponse('[{"i": 1, "why": "想弄明白她是谁"}]')
    ctx.llm_generate = llm_generate
    heart, learner = FakeHeartStar(), FakeLearner()
    ctx.stars = [type("Meta", (), {"star_cls": heart})(), type("Meta", (), {"star_cls": learner})()]
    b = kb.KajuBasics(ctx, {"browse": {"max_videos": 1, "daily_limit": 5}})
    topics = []

    async def candidates(topic):
        topics.append(topic)
        return [bw._video("BV1QGxE6TEYs", "陈千语是谁", "UP", 95)], "搜索"
    b._browse_candidates = candidates

    async def bili_video(url, event, danmaku=False):
        return {"title": "陈千语是谁", "up": "UP"}, "[Bilibili video: 观后笔记：讲了终末地里的陈千语……]"
    b._describer.bili_video = bili_video
    await b._browse("qq:FriendMessage:" + OWNER, 10, "", "兄长大人")
    expect("learn: no topic → searched her wonder", topics, ["终末地 陈千语"])
    expect("learn: pick prompt says it's her own wonder", ("一直想弄明白" in prompts[-1], "兄长大人说了" in prompts[-1]), (True, False))
    job = learner.jobs[0] if learner.jobs else {}
    expect("learn: watched video handed over", (job.get("how"), job.get("key"), job.get("chat"), "陈千语" in job.get("content", ""),
                                                 "好想摸摸它" in job.get("extra", "")),
           ("自己刷B站看到的", "bili:BV1QGxE6TEYs", "p" + OWNER, True, True))
    sess = b._browse_log.data["sessions"][-1]
    expect("learn: session remembers the wonder", sess.get("wonder"), "陈千语在终末地里是什么样的角色")


asyncio.run(learner_tests())

# ------------------------------------------------------------------ 特别想说的：刷完主动私聊兄长
items = [{"bvid": "BV1a", "title": "a", "share": True, "i": 1}, {"bvid": "BV1b", "title": "b", "share": True, "i": 3},
         {"bvid": "BV1c", "title": "c", "share": False, "i": 3}, {"bvid": "BV1d", "title": "d", "share": True, "i": 3}]
expect("pick share: strongest wanted, first on tie", bw.pick_share(items)["bvid"], "BV1b")
expect("pick share: none strong enough", bw.pick_share(items[:1]), None)
expect("clean share", bw.clean_share("&&开心&&兄长大人！我刚刷到**小猫**踩雪\nhttps://b23.tv/x 你看BV1QGxE6TEYs\n\n好可爱\n4\n5"),
       "兄长大人！我刚刷到小猫踩雪\n你看\n好可爱")
expect("clean share: skip", bw.clean_share("[SKIP]"), "")
expect("quiet hours", [bw.in_quiet(h, 23, 8) for h in (22, 23, 2, 7, 8)] + [bw.in_quiet(3, 1, 6), bw.in_quiet(3, 5, 5)],
       [False, True, True, True, False, True, False])
expect("strip note", bw.strip_note("BASE\n\nNOTE", "NOTE"), "BASE")
sp = bw.share_prompt({"title": "小猫", "up": "猫猫日记", "why": "好可爱", "emo": "开心", "voice": "想摸"}, "x" * 900)
expect("share prompt", ("《小猫》（UP主 猫猫日记）" in sp, "你心里想：想摸" in sp, "[SKIP]" in sp, "x" * 501 not in sp),
       (True, True, True, True))


class FakeConv:
    def __init__(self):
        self.history = json.dumps([{"role": "user", "content": "去刷会儿B站吧"},
                                   {"role": "assistant", "content": "好呀，那佳树去看一会儿"},
                                   {"role": "user", "content": [{"type": "text", "text": "嗯"}]}])
        self.pairs = []

    async def get_curr_conversation_id(self, umo):
        return "cid1"

    async def get_conversation(self, umo, cid):
        return self

    async def add_message_pair(self, cid, user, assistant):
        self.pairs.append((user, assistant))


class FakeStyle:
    def __init__(self):
        self.calls = []

    async def polish(self, text, ctx, said=""):
        self.calls.append((text, ctx, said))
        return text.replace("！", "\n")


async def share_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    asked = []
    answer = ["兄长大人！我刚刷到一只小猫第一次见到雪"]

    async def llm_generate(chat_provider_id, prompt, system_prompt=None, contexts=None):
        asked.append((chat_provider_id, prompt, system_prompt, contexts))
        return LLMResponse(answer[0])

    async def current_pid(umo):
        return "ds"
    sent = []

    async def send_message(umo, chain):
        sent.append((umo, "".join(str(x) for x in chain.chain)))
        return True
    conv, style = FakeConv(), FakeStyle()
    ctx.llm_generate, ctx.get_current_chat_provider_id, ctx.send_message = llm_generate, current_pid, send_message
    ctx.conversation_manager = conv
    ctx.stars = [type("Meta", (), {"star_cls": style})()]
    b = kb.KajuBasics(ctx, {"browse": {"quiet_start": 0, "quiet_end": 0, "share_per_day": 1}})
    friend = AstrMessageEvent(sender=OWNER, text="嗯")
    umo = "qq:FriendMessage:" + OWNER

    # 快照：她和兄长私聊时的完整系统提示（去掉附上的刷 B 站提示）
    b._browse_log.data["sessions"].append({"t0": time.time() - 60, "t1": time.time() - 30, "items": [
        {"bvid": "BV1x", "title": "旧的", "emo": "开心", "i": 1}], "shown": 0})
    req = ProviderRequest(system_prompt="人设：佳树")
    await b.browse_note(friend, req)
    await b.voice_snapshot(friend, req)
    expect("snapshot without browse note", b._browse_log.data["voice"]["system"], "人设：佳树")
    expect("snapshot saved to disk", json.load(open(b._browse_log.path, encoding="utf-8"))["voice"]["system"], "人设：佳树")
    await b.voice_snapshot(AstrMessageEvent(sender="999", text="hi"), ProviderRequest(system_prompt="别人的"))
    expect("snapshot only owner", b._browse_log.data["voice"]["system"], "人设：佳树")

    run = {"items": [{"bvid": "BV1QGxE6TEYs", "title": "小猫第一次见到雪", "up": "猫猫日记", "why": "好可爱", "emo": "开心",
                      "i": 2, "voice": "好想摸摸它", "share": True}]}
    b._owner_seen = time.time()
    await b._maybe_share(run, umo, {"BV1QGxE6TEYs": "看完了：小猫踩雪"})
    expect("owner chatting right now → don't send", (sent, run["items"][0].get("shared")), ([], None))
    b._owner_seen = 0
    await b._maybe_share(run, umo, {"BV1QGxE6TEYs": "看完了：小猫踩雪"})
    expect("shared: her lines + link", sent, [(umo, "兄长大人"), (umo, "我刚刷到一只小猫第一次见到雪"),
                                              (umo, "https://www.bilibili.com/video/BV1QGxE6TEYs")])
    pid, prompt, system, contexts = asked[-1]
    expect("share request: her voice + history", (pid, system, "小猫第一次见到雪" in prompt, "小猫踩雪" in prompt,
                                                  contexts[-1], len(contexts)),
           ("ds", "人设：佳树", True, True, {"role": "user", "content": "嗯"}, 3))
    expect("share went through kaju_style", (style.calls[-1][1][-1], "小猫第一次见到雪" in style.calls[-1][2]),
           ("兄长大人：嗯", True))
    expect("share recorded", (run["items"][0]["shared"], len(b._browse_log.data["shares"])), (True, 1))
    expect("share in history", (conv.pairs[-1][0]["content"].startswith("[系统记录] 你刚才自己刷B站看到《小猫第一次见到雪》"),
                                conv.pairs[-1][1]["content"]),
           (True, "兄长大人\n我刚刷到一只小猫第一次见到雪\nhttps://www.bilibili.com/video/BV1QGxE6TEYs"))
    b._browse_log.data["sessions"].append({"t0": time.time() - 60, "t1": time.time(), **run, "shown": 0})
    note = bw.chat_note(b._browse_log, time.time(), TZ)
    expect("note: already told him", "你已经主动跟他说过这个了" in note, True)

    run2 = {"items": [dict(run["items"][0], bvid="BV1REx46NEc4", shared=False)]}
    n = len(sent)
    await b._maybe_share(run2, umo, {})
    expect("once a day", len(sent) - n, 0)
    b._browse_log.data["shares"] = []
    answer[0] = "[SKIP]"
    await b._maybe_share(run2, umo, {})
    expect("model says not now → nothing sent", (len(sent) - n, run2["items"][0]["shared"]), (0, False))
    b.config["browse"].update(quiet_start=0, quiet_end=24)
    answer[0] = "看这个"
    await b._maybe_share(run2, umo, {})
    expect("quiet hours → nothing sent", len(sent) - n, 0)
    b.config["browse"].update(quiet_start=0, quiet_end=0, share=False)
    await b._maybe_share(run2, umo, {})
    expect("share off", len(sent) - n, 0)
    b.config["browse"]["share"] = True
    b._browse_log.data.pop("voice")
    await b._maybe_share(run2, umo, {})
    expect("no snapshot yet → nothing sent", len(sent) - n, 0)
    await b.terminate()


asyncio.run(share_tests())

# ------------------------------------------------------------------ 2026-11-05 修正：每次刷完都说一声、记进聊天记录、有人说话先让一让
expect("pick report: wanted first", bw.pick_report(items)[0]["bvid"], "BV1b")
calm = [{"bvid": "x1", "title": "无聊的", "emo": "无聊", "i": 2}, {"bvid": "x2", "title": "小猫", "emo": "开心", "i": 1},
        {"bvid": "x3", "title": "好奇的", "emo": "好奇", "i": 1}, {"bvid": "x4", "title": "平平", "emo": "平静", "i": 0}]
expect("pick report: no wanted → most felt (not 无聊)", (bw.pick_report(calm)[0]["bvid"], bw.pick_report(calm)[1]), ("x2", False))
expect("pick report: all flat → nothing", bw.pick_report(calm[3:]), (None, False))
expect("report prompt", (bw.REPORT_LEAD in bw.share_prompt(calm[1], wanted=False), bw.SHARE_LEAD in bw.share_prompt(calm[1])),
       (True, True))


class FakeLife:
    def __init__(self):
        self.lines = []

    def log_own(self, chat, text):
        self.lines.append((chat, text))


async def report_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    asked, sent = [], []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None, contexts=None):
        asked.append(prompt)
        if prompt.startswith("兄长大人允许佳树刷一会儿"):  # 挑视频
            return LLMResponse('[{"i": 1, "why": "好可爱"}, {"i": 2, "why": "想看"}]')
        return LLMResponse("兄长大人，佳树刷完啦\n有只小猫好可爱")

    async def current_pid(umo):
        return "ds"

    async def send_message(umo, chain):
        sent.append("".join(str(x) for x in chain.chain))
        return True
    life = FakeLife()
    ctx.llm_generate, ctx.get_current_chat_provider_id, ctx.send_message = llm_generate, current_pid, send_message
    ctx.conversation_manager = FakeConv()
    ctx.stars = [type("Meta", (), {"star_cls": life})()]
    b = kb.KajuBasics(ctx, {"browse": {"quiet_start": 0, "quiet_end": 0}})
    umo = "qq:FriendMessage:" + OWNER
    b._browse_log.data["voice"] = {"t": time.time(), "system": "人设"}
    run = {"items": [dict(calm[1]), dict(calm[0])]}
    await b._maybe_share(run, umo, {})
    expect("report even when nothing strongly wanted", (sent[:2], "跟他说一声你刷完了" in asked[-1], run["items"][0].get("shared")),
           (["兄长大人，佳树刷完啦", "有只小猫好可爱"], True, True))
    expect("logged into kaju_life chat log", life.lines, [("p" + OWNER, "兄长大人，佳树刷完啦\n有只小猫好可爱")])
    for _ in range(5):  # 每天最多 share_per_day（默认 5）次
        await b._maybe_share({"items": [dict(calm[1], bvid="y")]}, umo, {})
    expect("default cap 5 a day", len(b._browse_log.data["shares"]), 5)
    b._browse_log.data["shares"] = []
    b.config["browse"]["report"] = False
    n = len(sent)
    await b._maybe_share({"items": [dict(calm[1], bvid="z")]}, umo, {})
    expect("report off → only strongly wanted", len(sent) - n, 0)
    b.config["browse"]["report"] = True

    # 有人在跟她说话：两个视频之间先等一等
    cands = [bw._video("BV1QGxE6TEYs", "小猫", "u", 60), bw._video("BV1REx46NEc4", "蛋糕", "u", 60)]

    async def candidates(topic):
        return cands, "首页推荐"
    b._browse_candidates = candidates
    order = []

    async def bili_video(url, event, danmaku=False):
        order.append((url[-12:], round(time.time() - t0)))
        return {"title": "t", "up": "u"}, "看完了"
    b._describer.bili_video = bili_video
    sleeps = []
    real_sleep = asyncio.sleep

    async def fast_sleep(s):
        sleeps.append(s)
        b._chat_seen = 0  # 等了一下，聊天就停了
        await real_sleep(0)
    kb.asyncio.sleep = fast_sleep
    try:
        t0 = time.time()
        b._chat_seen = time.time()
        await b._browse(umo, 10, "", "兄长大人")
    finally:
        kb.asyncio.sleep = real_sleep
    expect("paused before the next video while chatting", (sleeps[:1], len(order)), ([5], 2))
    req = ProviderRequest(system_prompt="x")
    before = b._chat_seen
    await b.browse_note(AstrMessageEvent(sender="999", group="222222222", text="佳树"), req)
    expect("any reply turn marks chat time", b._chat_seen > before, True)
    await b.terminate()


asyncio.run(report_tests())


# ------------------------------------------------------------------ 2026-11-07 修正：群里叫她去看五条悟，她却一直在刷自己挑的
# 当时：群里"看完了吗"→ 群里没有刷B站的提示，她以为还没刷，又开了一次（搜她自己想弄明白的哈莉·奎茵）；
# 接着"去刷刷五条悟的视频吧"→ "已经在刷了" 把五条悟丢了；刷完只私聊汇报，群里问起还说"还没刷完"。
async def switch_tests():
    ctx = Context()
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    sent, prompts = [], []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None, contexts=None):
        prompts.append(prompt)
        if prompt.startswith("兄长大人允许佳树刷一会儿"):
            return LLMResponse('[{"i": 1, "why": "想看"}, {"i": 2, "why": "也想看"}]')
        return LLMResponse("兄长大人，五条悟的看完啦\n领域展开那段好帅")

    async def current_pid(umo):
        return "ds"

    async def send_message(umo, chain):
        sent.append((umo, "".join(str(x) for x in chain.chain)))
        return True
    life, learner = FakeLife(), FakeLearner()
    learner.wonder_topic = lambda now=None: {"kw": "哈莉·奎茵 小丑", "q": "哈莉当时是怎么答的"}
    ctx.llm_generate, ctx.get_current_chat_provider_id, ctx.send_message = llm_generate, current_pid, send_message
    ctx.conversation_manager = FakeConv()
    ctx.stars = [type("Meta", (), {"star_cls": life})(), type("Meta", (), {"star_cls": learner})()]
    b = kb.KajuBasics(ctx, {"browse": {"quiet_start": 0, "quiet_end": 0, "max_videos": 2, "pause_seconds": 0, "daily_limit": 99,
                                          "share_per_day": 99}})
    b._browse_log.data["voice"] = {"t": time.time(), "system": "人设"}
    topics = []

    async def candidates(topic):
        topics.append(topic)
        tag = "五条悟" if "五条悟" in topic else "哈莉"
        return [bw._video(f"BV1{tag == '五条悟' and 'G' or 'H'}xxxxxxx1", f"{tag}一", "u", 60),
                bw._video(f"BV1{tag == '五条悟' and 'G' or 'H'}xxxxxxx2", f"{tag}二", "u", 60)], f"搜「{topic}」"
    b._browse_candidates = candidates
    gate = asyncio.Event()
    watched = []

    async def bili_video(url, event, danmaku=False):
        watched.append(url[-12:])
        if len(watched) == 1:
            await gate.wait()  # 第一个视频看到一半，兄长在群里又说了五条悟
        return {"title": "看了", "up": "u"}, "看完了"
    b._describer.bili_video = bili_video
    grp = AstrMessageEvent(sender=OWNER, group="222222222", text="佳树去刷刷五条悟的视频吧")
    gumo = "qq:GroupMessage:222222222"

    said = await b.browse_bilibili(AstrMessageEvent(sender=OWNER, group="222222222", text="佳树看完了吗"))
    expect("group: starts (her own wonder)", said.startswith("开始刷B站了"), True)
    for _ in range(5):
        await asyncio.sleep(0)
    said = await b.browse_bilibili(grp, topic="五条悟")
    expect("new topic while browsing → queued, not dropped", (said.startswith("换过去了"), "五条悟" in said,
                                                             b._browse_log.data["running"].get("switch_to")), (True, True, "五条悟"))
    expect("same queued topic again", (await b.browse_bilibili(grp, topic="五条悟")).startswith("已经在B站上找「五条悟」"), True)
    req = ProviderRequest(system_prompt="BASE")
    await b.browse_note(grp, req)
    expect("group asks mid-browse → running note with the switch", ("【你正在刷B站】" in req.system_prompt,
                                                                    "哈莉当时是怎么答的" in req.system_prompt,
                                                                    "又让你去看\"五条悟\"" in req.system_prompt,
                                                                    "别说刷完了" in req.system_prompt), (True, True, True, True))
    gate.set()
    first = b._browsing
    await first
    await b._browsing  # 换过去的那次
    expect("switched after the current video", (topics, watched),
           (["哈莉·奎茵 小丑", "五条悟"], ["BV1Hxxxxxxx1", "BV1Gxxxxxxx1", "BV1Gxxxxxxx2"]))
    s1, s2 = b._browse_log.data["sessions"][-2:]
    expect("sessions: cut one + asked one", (s1.get("switched"), len(s1["items"]), s2["asked"], s2["where"], len(s2["items"])),
           ("五条悟", 1, "五条悟", gumo, 2))
    expect("report went to the group (only once, for 五条悟)", [u for u, _ in sent], [gumo, gumo, gumo])
    share_prompt = next(p for p in reversed(prompts) if "你刚刷完" in p)
    expect("report prompt: asked topic + in group", ("他让你看\"五条悟\"相关的" in share_prompt, "在群里跟他说" in share_prompt),
           (True, True))
    expect("logged into the group chat log", life.lines[-1][0], "g222222222")
    req = ProviderRequest(system_prompt="BASE")
    await b.browse_note(grp, req)
    expect("group asks after → finished note", ("【你自己刷B站看到的】" in req.system_prompt, "按兄长大人说的找了\"五条悟\"" in req.system_prompt,
                                                "你已经主动跟他说过这个了" in req.system_prompt), (True, True, True))
    expect("pick report: asked topic but flat → still report", bw.pick_report(calm[3:], must=True), (calm[3], False))
    await b.terminate()


asyncio.run(switch_tests())


# follow_through：刷B站的工具调过了，"马上去搜五条悟"不算没做（以前会后台另外上网搜一遍文字资料）
async def follow_tests():
    ft = importlib.import_module("follow_through.main")
    p = ft.FollowThrough(Context(), {})
    ran = []
    p._follow_up = lambda event, snap, reply, missing: ran.append([a.key for a in missing]) or asyncio.sleep(0)
    ev = AstrMessageEvent(sender=OWNER, group="222222222", text="佳树去刷刷五条悟的视频吧")
    req = ProviderRequest(system_prompt="x")
    req.func_tool = ToolSet([type("T", (), {"name": n})() for n in ("browse_bilibili", "web_search_deepseek")])
    await p.remember_request(ev, req)
    ev.set_extra("_ft_calls", [{"name": "browse_bilibili", "ok": True, "result": "换过去了"}])
    await p.check(ev, LLMResponse("好的兄长大人，佳树马上去搜五条悟！"))
    expect("follow_through: browse counts for 去搜", ran, [])
    ev2 = AstrMessageEvent(sender=OWNER, group="222222222", text="帮我查查明天天气")
    await p.remember_request(ev2, req)
    await p.check(ev2, LLMResponse("佳树马上去查一下"))
    await asyncio.sleep(0)
    expect("follow_through: plain search promise still followed up", ran, [["search"]])
    # 11-19：说“这就去看Hoody那个”、或大脑定了“答应：去查…”却没调工具 → 也补做；随口的话不算
    for i, (said, plan, want) in enumerate((
            ("好的兄长大人，佳树这就去看Hoody那个！", None, [["search"]]),
            ("好的兄长大人~", {"要表达的": ["答应：去查 Hoody 平台的情况"]}, [["search"]]),
            ("好的兄长大人~", {"要表达的": ["反应：被派任务很开心"]}, []),
    )):
        ran.clear()
        p._last_follow_up.clear()
        ev3 = AstrMessageEvent(sender=OWNER, group="222222222", text=f"那你再看看这个吧{i}")
        await p.remember_request(ev3, req)
        if plan:
            ev3.set_extra("_ks_plan", plan)
        await p.check(ev3, LLMResponse(said))
        await asyncio.sleep(0)
        expect(f"follow_through: promise {i}", ran, want)
    # 补做的话交给 kaju_style polish（回复器写）；polish 写不成且只发写手的话 → 不发
    sent, polished = [], []

    class Style:
        def writer_only(self):
            return True

        async def polish(self, text, ctx, said="", title="", kind="私聊", split=True):
            polished.append((text, kind))
            return "" if "写不成" in text else "查到啦\n是个云平台"
    p._style = lambda: Style()

    async def send_message(umo, chain):
        sent.append(chain)
    p.context.send_message = send_message

    async def no_hist(umo, text):
        return None
    p._append_to_history = no_hist
    ev4 = AstrMessageEvent(sender=OWNER, group="222222222", text="看看")
    await p._deliver(ev4, "佳树看了，Hoody 是个云平台", {"contexts": [], "user_text": "看看"})
    expect("follow_through: deliver via polish", (len(sent), polished[-1][1]), (2, "群聊"))
    await p._deliver(ev4, "写不成", {"contexts": [], "user_text": "看看"})
    expect("follow_through: writer failed → silent", len(sent), 2)


asyncio.run(follow_tests())


async def polish_tests():
    ks = importlib.import_module("kaju_style.main")
    cls = ks.KajuStyle  # 插件类（StyleMind 是 kaju_core 里的逻辑，外壳 KajuStyle 才是插件）
    st = cls(Context(), {"rewrite": {"enable": False}})
    out = await st.polish("兄长大人我刚刷到一只小猫第一次见到雪，它踩来踩去的好可爱。")
    expect("polish: rewrite off → rhythm only, no 句号", (out.endswith("。"), "小猫" in out), (False, True))
    # writer_only 关着：查“核对不过就用原稿”那条退路
    st = cls(Context(), {"rewrite": {"enable": True, "guard": True, "retry": 0, "writer_only": False}})
    seen = {}

    async def plan_of(ctx, draft, kind, title):
        seen["ctx"] = ctx
        return {"局面": "她刚刷到一个视频，想分享给兄长大人", "要表达的": ["分享：小猫第一次见到雪"]}

    async def write(ctx, plan, kind, title, ref=""):
        return "兄长大人！我刷到一只小猫第一次见到雪"

    async def guard(said, draft, new, title="", ctx=None):
        seen["said"] = said
        return False, "", True
    st._plan_from_draft, st._write, st._guard = plan_of, write, guard
    out = await st.polish("兄长大人，我刷到了一只小猫第一次见到雪", ["兄长大人：嗯"], said="刷到视频")
    expect("polish: rewrite + guard", ("小猫" in out, seen["ctx"], seen["said"]), (True, ["兄长大人：嗯"], "刷到视频"))

    async def bad_guard(said, draft, new, title="", ctx=None):
        return True, "改了意思", True
    st._guard = bad_guard
    out = await st.polish("兄长大人，我刷到了一只小猫", [], said="x")
    expect("polish: guard says no → draft", "我刷到了一只小猫" in out.replace("\n", ""), True)


asyncio.run(polish_tests())


# ------------------------------------------------------------------ --live：真联网（只读，不登录）
async def live():
    import aiohttp

    st = bl.Store(os.path.join(tempfile.mkdtemp(), "bili_login.json"))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        await bl.ensure_device(s, st)
        print("设备号：", {k: v[:8] + "…" for k, v in st.cookies.items()})
        d = await bl.nav(s, st)
        mixin = bl.mixin_key(*bl.wbi_keys(d))
        print("nav isLogin:", d.get("isLogin"), "mixin:", mixin[:6] + "…")
        data, _ = await bl.api_json(s, "GET", bl.API + "/x/web-interface/wbi/index/top/feed/rcmd", st.header(),
                                    params=bl.wbi_sign({"fresh_type": 4, "ps": 20, "fresh_idx": 1, "fresh_idx_1h": 1, "brush": 1,
                                                        "web_location": 1430650}, mixin))
        rc = bw.usable(bw.parse_rcmd(data), {}, 12 * 60)
        print(f"\n=== 首页推荐（code {data.get('code')}，能看的 {len(rc)} 个）\n" + bw.candidate_lines(rc[:10]))
        data, _ = await bl.api_json(s, "GET", bl.API + "/x/web-interface/wbi/search/type", st.header(),
                                    params=bl.wbi_sign({"search_type": "video", "keyword": "猫", "page": 1}, mixin))
        sr = bw.usable(bw.parse_search(data), {}, 12 * 60)
        print(f"\n=== 搜「猫」（code {data.get('code')}，能看的 {len(sr)} 个）\n" + bw.candidate_lines(sr[:5]))
        data, _ = await bl.api_json(s, "GET", bl.API + "/x/web-interface/popular", st.header(), params={"ps": 10, "pn": 1})
        print(f"\n=== 热门（code {data.get('code')}）\n" + bw.candidate_lines(bw.parse_popular(data)[:5]))
        url, key = await bl.qr_generate(s)
        print("\n二维码链接拿到了：", url.split("?")[0], "key", key[:6] + "…")
        print("没扫：", await bl.qr_poll(s, key))
        png = os.path.join(tempfile.mkdtemp(), "qr.png")
        bl.make_qr_png(url, png)
        print("二维码图片：", os.path.getsize(png), "字节")


async def live_share():
    """真人设 + 真模型：看完一个视频的感受和心声 → 她主动私聊兄长的那一两句（只打印，不发）。"""
    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()

    async def chat(system, msgs):
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[{"role": "system", "content": system}, *msgs])
        return r.choices[0].message.content.strip()
    seen = ("2分18秒的视频，看完了。画面：一只橘猫被主人抱去宠物医院打预防针，一路扒着主人肩膀不肯下来，"
            "打针时把脸埋进主人怀里，打完立刻窝在主人腿上睡着了。观后笔记：UP主记录自家橘猫第一次打疫苗，"
            "从紧张发抖到被摸头安抚，最后在回家路上的猫包里呼噜呼噜睡着。「不怕不怕，我们回家了」")
    item = {"title": "打预防针", "up": "橘猫黄小胖", "why": "我想看小猫被安慰的样子"}
    raw = await chat(browsed.system_prompt(hi=60), [{"role": "user", "content": browsed.build_prompt(
        title=item["title"], up=item["up"], why=item["why"], seen=seen, tastes="【你自己慢慢长出来的喜好】\n- 有点感兴趣：猫的视频")}])
    v = browsed.parse(raw, 60)
    print("=== 看完的感受\n", v)
    item.update(emo=v["emotion"], i=v["intensity"], voice=v["voice"], share=True)
    history = [{"role": "user", "content": "去刷会儿B站吧，我去洗个澡"}, {"role": "assistant", "content": "好~那佳树去看一会儿\n兄长大人洗完记得吹头发哦"}]
    for i in range(3):
        out = await chat(persona, [*history, {"role": "user", "content": bw.share_prompt(item, seen)}])
        print(f"\n=== 主动说的（第 {i + 1} 次）\n{bw.clean_share(out) or '（SKIP）'}")


if "--live" in sys.argv:
    asyncio.run(live())
if "--live-share" in sys.argv:
    asyncio.run(live_share())
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
