"""Offline tests for B 站视频链接 (kaju_basics bili.py + Describer.bili_* + describe_media + group history),
plus the bits of kaju_heart / memory_weight that take the shared video.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_bili.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_bili.py --live [链接]
        真联网打开链接（默认是兄长 10/31 发的那个）+ 真模型：看封面、她的回复、情绪判断、珍藏评分量（只打印）
"""

import asyncio
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import time
import types
import zlib

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import File, Json, Plain, Reply  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402

bili = importlib.import_module("kaju_platforms.bili.bili")
kb = importlib.import_module("kaju_basics.main")
appraise = importlib.import_module("kaju_core.heart.appraise")
shelf = importlib.import_module("kaju_core.memory.shelf")
failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


SHARE = "【佳树的独特到底在哪？兄妹羁绊能超过男女之爱？温水佳树的人物解读！-哔哩哔哩】 https://b23.tv/iOcLavf"
TITLE = "佳树的独特到底在哪？兄妹羁绊能超过男女之爱？温水佳树的人物解读！"
BV = "BV1Sd5v6QEJD"

# ------------------------------------------------------------------ 认链接
expect("share text", bili.find_links(SHARE), ["https://b23.tv/iOcLavf"])
expect("bare domain + p, mobile, bare BV",
       bili.find_links(f"看 bilibili.com/video/{BV}?p=2，还有 https://m.bilibili.com/video/BV1ZLe267Ec4。", 5),
       [f"https://bilibili.com/video/{BV}?p=2", "https://m.bilibili.com/video/BV1ZLe267Ec4"])
expect("bare BV", bili.find_links(f"BV号是{BV}哦"), [BV])
expect("same video twice → once", bili.find_links(f"https://www.bilibili.com/video/{BV}/ 和 {BV}"),
       [f"https://www.bilibili.com/video/{BV}/"])
expect("no false hits", bili.find_links("BV1abc 和 bilibili.com/read/cv123 还有 ABV1Sd5v6QEJDX"), [])
expect("limit", len(bili.find_links(" ".join(f"https://b23.tv/a{i}" for i in range(5)))), 2)
card = {"app": "com.tencent.miniapp_01", "meta": {"detail_1": {
    "title": "哔哩哔哩", "desc": TITLE, "qqdocurl": "https://b23.tv/iOcLavf?share_medium=android&share_source=qq"}}}
expect("mini-app card", bili.card_links(card), ["https://b23.tv/iOcLavf"])
expect("card nested as string", bili.card_links({"data": json.dumps(card).replace("/", "\\/")}), ["https://b23.tv/iOcLavf"])
expect("news card", bili.card_links({"meta": {"news": {"title": "t", "jumpUrl": f"https://www.bilibili.com/video/{BV}"}}}),
       [f"https://www.bilibili.com/video/{BV}"])
expect("video_key", [bili.video_key(u) for u in (f"https://www.bilibili.com/video/{BV}?p=1&x=2",
                                                  f"https://www.bilibili.com/video/{BV}?vd=1&p=3",
                                                  "https://www.bilibili.com/video/av170001", "https://b23.tv/x")],
       [BV, f"{BV}#3", "av170001", ""])
expect("page_url", (bili.page_url(BV), bili.page_url(f"{BV}#3")),
       (f"https://www.bilibili.com/video/{BV}/", f"https://www.bilibili.com/video/{BV}/?p=3"))
expect("is_short", (bili.is_short("https://b23.tv/x"), bili.is_short(f"https://www.bilibili.com/video/{BV}")), (True, False))


# ------------------------------------------------------------------ 页面
def video_page(pages=None, desc="-"):
    state = {"bvid": BV, "videoData": {
        "bvid": BV, "title": TITLE, "desc": desc, "duration": 722, "tname": "动漫杂谈",
        "pic": "http://i0.hdslb.com/bfs/archive/cover.jpg", "owner": {"name": "那谁21"},
        "stat": {"view": 1713454, "like": 142942, "danmaku": 2365, "favorite": 60892}, "cid": 111,
        "pages": pages or [{"cid": 111, "page": 1, "part": "正片", "duration": 722}]},
        "tags": [{"tag_name": "温水佳树"}, {"tag_name": "败犬女孩太多啦！"}]}
    return ("<html><head><title>x_哔哩哔哩_bilibili</title></head><body><script>window.__INITIAL_STATE__="
            + json.dumps(state, ensure_ascii=False) + ";(function(){var s;}());</script></body></html>")


info = bili.parse_page(video_page())
expect("page fields", {k: info[k] for k in ("title", "up", "duration", "area", "tags", "cid", "part_title", "parts")},
       {"title": TITLE, "up": "那谁21", "duration": 722, "area": "动漫杂谈", "tags": ["温水佳树", "败犬女孩太多啦！"],
        "cid": 111, "part_title": "", "parts": 1})
two = bili.parse_page(video_page(pages=[{"cid": 1, "page": 1, "part": "上", "duration": 60},
                                        {"cid": 2, "page": 2, "part": "下集", "duration": 90}]), part=2)
expect("multi-p picks part", (two["cid"], two["part_title"], two["duration"], two["p"]), (2, "下集", 90, 2))
meta_page = ('<meta property="og:title" content="某个视频_哔哩哔哩_bilibili"><meta name="author" content="UP甲">'
             '<meta name="description" content="这是简介，相关视频：别的"><meta property="og:image" content="//i0.hdslb.com/a.jpg@100w">')
expect("meta fallback", {k: bili.parse_page(meta_page)[k] for k in ("title", "up", "desc", "cover")},
       {"title": "某个视频", "up": "UP甲", "desc": "这是简介", "cover": "//i0.hdslb.com/a.jpg"})
expect("error page", bili.parse_page("<title>出错啦! - bilibili.com</title>"), {})
expect("generic page", bili.parse_generic('<meta property="og:title" content="番剧第1话_bilibili">'
                                          '<meta property="og:description" content="简介">')["title"], "番剧第1话")

# ------------------------------------------------------------------ 弹幕
DM = [(5, "这期神了")] * 8 + [(6, "神了")] * 6 + [
    (12, "我的我的我的我的我的我的我的我的"), (30, "哈哈哈哈哈"), (40, "佳树和兄长大人叠一起"),
    (100, "只有妹妹会无条件的安慰自己，这才是原因"), (101, "确实"), (300, "这世间有多少恋人追求的，不过是兄妹自出生起就有的关系"),
    (500, "白玉和橡皮擦是强绑定的"), (700, "也许过去最喜欢的，未来也仍是最喜欢的")]
xml = "<i>" + "".join(f'<d p="{s},1,25,16777215,0,0,0,0">{t}</d>' for s, t in DM) + '<d p="bad">x</d></i>'
dm = bili.parse_danmaku(xml.replace("安慰", "安&amp;慰"))
expect("parse danmaku", (len(dm), dm[0], any("安&慰" in t for _, t in dm)), (len(DM), (5.0, "这期神了"), True))
hot = bili.popular(bili.parse_danmaku(xml))
expect("popular", hot, [("这期神了", 8), ("神了", 6)])
picked = [t for _, t in bili.pick_danmaku(bili.parse_danmaku(xml), 6, 722, {t for t, _ in hot})]
expect("pick: spam/crude/short/hot dropped", (any("我的我的" in t for t in picked), any("叠" in t for t in picked),
                                               "确实" in picked, "这期神了" in picked), (False, False, False, False))
expect("pick: content spread over time", picked[:2], ["只有妹妹会无条件的安慰自己，这才是原因",
                                                      "这世间有多少恋人追求的，不过是兄妹自出生起就有的关系"])
text = bili.describe(info, "温水佳树捧着脸笑", [(100.0, "只有妹妹会无条件的安慰自己")], hot)
expect("describe", (text.startswith(f"B站视频《{TITLE}》（UP主：那谁21，12分2秒，动漫杂谈）。标签：温水佳树、败犬女孩太多啦！"),
                    "播放171万，点赞14万，弹幕2365" in text, "简介：" in text, "封面：温水佳树捧着脸笑" in text,
                    "01:40 只有妹妹会无条件的安慰自己" in text, "「这期神了」×8" in text,
                    text.index(bili.SEEN_ONLY_PAGE) < text.index("弹幕（观众")),
       (True, True, False, True, True, True, True))
plain = bili.describe(info, "温水佳树捧着脸笑")
expect("describe without danmaku", ("弹幕（" in plain, plain.endswith(bili.SEEN_ONLY_PAGE)), (False, True))
expect("seen override", bili.describe(info, watched="看完了。", seen=bili.SEEN_VIDEO).endswith(bili.SEEN_VIDEO), True)
expect("asks danmaku", [bili.asks_danmaku(t) for t in (
    "弹幕都说啥", "你看看弹幕", SHARE, "【弹幕版】某某 https://b23.tv/x", "看看这个", "https://b23.tv/弹幕")],
    [True, True, False, False, False, False])
expect("mobile play urls", bili.mobile_play_urls(
    '<script>window.__INITIAL_STATE__={"video":{"x":1,"playUrlInfo":[{"url":"\\u002F\\u002Fupos.bilivideo.com\\u002Fa.mp4",'
    '"size":10,"length":2000}]}};</script>'), [{"url": "https://upos.bilivideo.com/a.mp4", "size": 10, "length": 2000,
                                             "backup": []}])
U = "https://upos-sz-mirrorcosov.bilivideo.com/upgcxcode/a.mp4?e=1&os=cosovbv"
expect("video urls mirrors", bili.video_urls(U, ["//cn-x.bilivideo.com/b.mp4"]), [
    U, "https://cn-x.bilivideo.com/b.mp4",
    "https://upos-sz-mirroraliov.bilivideo.com/upgcxcode/a.mp4?e=1&os=cosovbv",
    "https://upos-sz-mirrorhw.bilivideo.com/upgcxcode/a.mp4?e=1&os=cosovbv"])
AK = "https://upos-hz-mirrorakam.akamaized.net/upgcxcode/a.mp4?os=akam"
expect("video urls akam -> bilivideo mirrors", bili.video_urls(AK), [
    AK, "https://upos-sz-mirrorcosov.bilivideo.com/upgcxcode/a.mp4?os=akam",
    "https://upos-sz-mirroraliov.bilivideo.com/upgcxcode/a.mp4?os=akam",
    "https://upos-sz-mirrorhw.bilivideo.com/upgcxcode/a.mp4?os=akam"])
expect("video urls non-upos", bili.video_urls("https://cn-x.bilivideo.com/b.mp4"), ["https://cn-x.bilivideo.com/b.mp4"])


async def _try_urls_test():
    import aiohttp
    from kaju_basics.describe import Describer
    tried = []

    async def fetch(u):
        tried.append(u)
        if len(tried) < 3:
            raise aiohttp.ClientConnectionError("down")
        return 7
    got = await Describer._try_urls(["a://h1/x", "a://h2/x", "a://h3/x", "a://h4/x"], fetch)
    expect("try urls switches host", (got, len(tried)), (7, 3))
    async def down(u):
        raise aiohttp.ClientConnectionError("x")
    try:
        await Describer._try_urls(["a://h1/x", "a://h2/x"], down)
        expect("try urls all fail raises", False, True)
    except aiohttp.ClientConnectionError:
        pass
asyncio.run(_try_urls_test())
expect("mobile play urls none", bili.mobile_play_urls("<html></html>"), [])
expect("brief", bili.brief(info), f"B站视频《{TITLE}》（UP主那谁21，12分2秒）")
expect("fmt", (bili.fmt_count(1713454), bili.fmt_count(14294), bili.fmt_count(46), bili.fmt_secs(3725), bili.fmt_secs(60)),
       ("171万", "1.4万", "46", "1小时2分", "1分钟"))

# ------------------------------------------------------------------ 登录后的字幕（纯逻辑）
expect("cookie forms", [bili.cookie_header(x) for x in (
    "", "  abc123%2C  ", "SESSDATA=abc; buvid3=x-y;", "Cookie: SESSDATA=abc;\n buvid3=x")],
    ["", "SESSDATA=abc123%2C", "SESSDATA=abc; buvid3=x-y", "SESSDATA=abc; buvid3=x"])
AID = 116577424905844
ZH_URL = f"//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/{AID}111abcdef?auth_key=1-2-3"
WRONG_ZH_URL = "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/11332293027736726334791097zz?auth_key=9"
JA_URL = "//aisubtitle.hdslb.com/bfs/subtitle/49d5655aedfa77cc.json?auth_key=4"


def player(*subs_):
    return {"code": 0, "data": {"aid": AID, "cid": 111, "login_mid": 1, "subtitle": {"subtitles": [
        {"lan": lan, "lan_doc": doc, "subtitle_url": url} for lan, doc, url in subs_]}}}


PLAYER = player(("ai-en", "English", "//aisubtitle.hdslb.com/bfs/subtitle/en.json"), ("ai-zh", "中文", ZH_URL))
subs, logged = bili.parse_player(PLAYER)
expect("parse player", (len(subs), subs[1]["url"], logged), (2, "https:" + ZH_URL, True))
expect("rank zh first", bili.rank_subtitles(subs)[0]["lan"], "ai-zh")
expect("rank uploader zh first", bili.rank_subtitles(subs + [{"lan": "zh-CN", "name": "中文", "url": "u"}])[0]["lan"], "zh-CN")
expect("rank zh > ja > en > other", [s["lan"] for s in bili.rank_subtitles(
    [{"lan": x} for x in ("fr", "ai-en", "ai-ja", "ai-zh")])], ["ai-zh", "ai-ja", "ai-en", "fr"])
expect("rank none", (bili.rank_subtitles([]), bili.parse_player({"code": 0, "data": {"subtitle": {}}})), ([], ([], False)))
expect("url belongs to video", [bili.subtitle_url_ok("https:" + u, AID) for u in (ZH_URL, WRONG_ZH_URL, JA_URL)],
       [True, False, True])
expect("url check needs aid", bili.subtitle_url_ok("https:" + WRONG_ZH_URL, ""), True)
expect("subtitle fits duration", [bili.subtitle_fits(ls, 722) for ls in (
    [(0, "a"), (700, "b")], [(0, "a"), (120, "b")], [(0, "a"), (900, "b")], [])], [True, False, False, False])
expect("short video any coverage", bili.subtitle_fits([(0, "a"), (5, "b")], 60), True)
body = {"body": [{"from": 0.5, "to": 2, "content": "大家好"}, {"from": 30, "content": "今天讲佳树"},
                 {"from": 75, "content": " 她  很特别 "}, {"from": 80, "content": ""}]}
expect("parse subtitle", bili.parse_subtitle(body), [(0.5, "大家好"), (30.0, "今天讲佳树"), (75.0, "她 很特别")])
expect("transcript marks", bili.transcript(bili.parse_subtitle(body)), "[00:00] 大家好 今天讲佳树 [01:15] 她 很特别")
w = bili.describe(info, "封面", watched="看完了，观后笔记：讲佳树。")
expect("describe watched", (w.index("看完了，观后笔记") < w.index("标签："), w.endswith(bili.SEEN_SUBTITLE)), (True, True))


# ------------------------------------------------------------------ 联网部分（假网络）
class Web:
    routes: dict = {}
    calls: list = []
    sent: list = []  # (url, headers, params)


class FakeContent:
    def __init__(self, body): self.body = body

    async def iter_chunked(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]


class FakeResp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}
        self.content = FakeContent(body)

    async def text(self, errors="strict"): return self.body.decode("utf-8", errors)
    async def read(self): return self.body
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class FakeSession:
    def __init__(self, timeout=None, headers=None): self.headers = headers

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, allow_redirects=True, headers=None, params=None, **kw):
        Web.calls.append(url)
        Web.sent.append((url, dict(headers or {}), dict(params or {})))
        hit = Web.routes.get(url)
        if callable(hit):
            hit = hit(params or {}, headers or {})
        return hit if hit is not None else FakeResp(404, b"not found")


def deflate(data: bytes) -> bytes:
    c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return c.compress(data) + c.flush()


PAGE = f"https://www.bilibili.com/video/{BV}/"
real_aiohttp = sys.modules.get("aiohttp")
sys.modules["aiohttp"] = types.SimpleNamespace(ClientSession=FakeSession, ClientTimeout=lambda total=None, **k: None,
                                               ClientConnectionError=ConnectionError, ClientPayloadError=IOError)
Web.routes = {
    "https://b23.tv/iOcLavf": FakeResp(302, headers={"Location": f"https://www.bilibili.com/video/{BV}?share_source=COPY&p=1"}),
    PAGE: FakeResp(200, video_page().encode("utf-8")),
    "https://comment.bilibili.com/111.xml": FakeResp(200, deflate(xml.encode("utf-8"))),
    "https://i0.hdslb.com/bfs/archive/cover.jpg": FakeResp(200, b"\xff\xd8jpegdata"),
    "https://b23.tv/evil": FakeResp(302, headers={"Location": "https://evil.example.com/video/x"}),
    "https://b23.tv/gone": FakeResp(302, headers={"Location": "https://www.bilibili.com/video/BV1xx411c7mD"}),
    "https://b23.tv/ep": FakeResp(302, headers={"Location": "https://www.bilibili.com/bangumi/play/ep1?from=share"}),
    "https://www.bilibili.com/bangumi/play/ep1": FakeResp(200, '<meta property="og:title" content="番剧第1话_bilibili">'.encode()),
}


class FakeGcc:
    def __init__(self): self.lines = []

    async def handle_message(self, event):
        self.lines.append("".join(c.text for c in event.get_messages() if isinstance(c, Plain)))


class FakeProvider:
    provider_config = {"id": "ds"}


class FakeWriter:
    """kaju_style 的本地写手（看视频前先说的那句由它照卡片写）。"""

    def __init__(self):
        self.cards = []

    async def say_from_card(self, event, points, **kw):
        self.cards.append((points, kw))
        return "佳树先去看看哦"


def make(cfg=None, answer="这是一期人物解读视频，UP主认为佳树的独特在于……「兄妹之间不需要理由」"):
    gcc = FakeGcc()
    ctx = Context({"timezone": "Asia/Shanghai", "provider_ltm_settings": {"group_icl_enable": True}})
    ctx.stars = [type("Meta", (), {"star_cls": type("S", (), {"group_chat_context": gcc})()})(),
                 type("Meta", (), {"star_cls": FakeWriter()})()]
    ctx.providers = {"ds": FakeProvider()}
    ctx.prompts = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        ctx.prompts.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(answer)

    ctx.llm_generate = llm_generate
    b = kb.KajuBasics(ctx, {"media": cfg or {}})
    captions = []

    async def caption(path, prompt, umo):
        captions.append((os.path.exists(path), prompt))
        return "温水佳树捧着脸，大字「佳树的独特」"

    b._describer.caption = caption
    return b, gcc, captions


PAGE_ONLY = {"bili_download": False}


async def net_tests():
    b, gcc, captions = make(PAGE_ONLY)
    d = b._describer
    Web.calls = []
    expect("brief via short link", await d.bili_brief("https://b23.tv/iOcLavf"), f"B站视频《{TITLE}》（UP主那谁21，12分2秒）")
    expect("short link not followed into share page", Web.calls, ["https://b23.tv/iOcLavf", PAGE])
    info2, full = await d.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("page: cover, no danmaku", ("封面：温水佳树捧着脸" in full, "弹幕（" in full, info2["url"], info2["kind"],
                                       any("comment.bilibili.com" in u for u in Web.calls)), (True, False, PAGE, "video", False))
    expect("cover caption prompt has title", (captions[0][0], TITLE in captions[0][1]), (True, True))
    n = len(Web.calls)
    await d.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("cached", len(Web.calls), n)
    _, with_dm = await d.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent(), danmaku=True)
    expect("asked: danmaku appended", (with_dm.startswith(full), "01:40 只有妹妹" in with_dm, "「这期神了」×8" in with_dm),
           (True, True, True))
    expect("other host refused", (await d.bili_video("https://b23.tv/evil", AstrMessageEvent()))[1],
           "没打开：链接跳到了别的网站，佳树没打开")
    expect("missing video", (await d.bili_video("https://b23.tv/gone", AstrMessageEvent()))[1].startswith("没打开：视频页打不开"),
           True)
    ginfo, gtext = await d.bili_video("https://b23.tv/ep", AstrMessageEvent())
    expect("non-video page", (ginfo["kind"], gtext.startswith("B站视频《番剧第1话》")), ("page", True))
    expect("no brief when gone", await d.bili_brief("https://b23.tv/gone"), "")

    # 私聊发分享链接：消息里加上看到的视频页、系统提示里说明、记给珍藏和心情
    ev = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("direct link part", (len(texts), texts[0].startswith(f"[Bilibili video: B站视频《{TITLE}》")), (1, True))
    expect("bili note", ("【关于B站视频】" in req.system_prompt, "【关于文件】" in req.system_prompt), (True, False))
    read = ev.get_extra("kaju_docs_read")
    expect("docs_read for shelf/heart", [(r["name"], r["kind"], r["url"], r["quoted"], r["path"]) for r in read],
           [(TITLE, "B站视频", PAGE, False, "")])
    # 引用一张 QQ 分享卡片问她
    ev = AstrMessageEvent(text="你看这个", messages=[Reply(chain=[Json(card)]), Plain("你看这个")])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    expect("quoted card", [p.text.startswith(f"[Bilibili video in quoted message: B站视频《{TITLE}》")
                           for p in req.extra_user_content_parts], [True])
    expect("quoted flag", ev.get_extra("kaju_docs_read")[0]["quoted"], True)
    # 引用的消息只有文字（message_str）
    ev = AstrMessageEvent(text="这个", messages=[Reply(message_str=SHARE), Plain("这个")])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    expect("quoted message_str", len(req.extra_user_content_parts), 1)
    # 打不开：老实说没打开，不收进珍藏
    ev = AstrMessageEvent(text="https://b23.tv/gone", messages=[Plain("https://b23.tv/gone")])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    expect("failed link", (req.extra_user_content_parts[0].text.startswith("[Bilibili video: 没打开："),
                           ev.get_extra("kaju_docs_read"), "【关于B站视频】" in req.system_prompt), (True, None, True))
    # 文件 + 视频一起：两样都记
    tmp = os.path.join(tempfile.mkdtemp(), "信.txt")
    open(tmp, "w", encoding="utf-8").write("佳树，生日快乐！")
    ev = AstrMessageEvent(text=SHARE, messages=[File(name="信.txt", file=tmp), Plain(SHARE)])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[File Attachment: name 信.txt, path x]"))
    await b.describe_media(ev, req)
    expect("file + video", [r["kind"] for r in ev.get_extra("kaju_docs_read")], ["文件", "B站视频"])
    # 普通消息不动
    req = ProviderRequest("SYS")
    await b.describe_media(AstrMessageEvent(text="你好", messages=[Plain("你好")]), req)
    expect("plain untouched", (req.system_prompt, req.extra_user_content_parts), ("SYS", []))
    # 弹幕：没让她看就不读；让她看了才附上；看完之后再问也能翻出来
    Web.calls = []
    b4, _, _ = make(PAGE_ONLY)
    ev = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    req = ProviderRequest("SYS")
    await b4.describe_media(ev, req)
    expect("no danmaku unless asked", ("弹幕（观众" in req.extra_user_content_parts[0].text,
                                       any("comment.bilibili.com" in u for u in Web.calls)), (False, False))
    asked = SHARE + " 你看看弹幕"
    req = ProviderRequest("SYS")
    await b4.describe_media(AstrMessageEvent(text=asked, messages=[Plain(asked)]), req)
    expect("danmaku when asked", "弹幕（观众边看边发的" in req.extra_user_content_parts[0].text, True)
    req = ProviderRequest("SYS")
    await b4.describe_media(AstrMessageEvent(text="弹幕都说了啥", messages=[Plain("弹幕都说了啥")]), req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("danmaku asked later", (len(texts), texts[0].startswith(f"[Bilibili danmaku: 刚才那个B站视频《{TITLE}》的弹幕（观众"),
                                   "【关于B站视频】" in req.system_prompt), (1, True, True))
    req = ProviderRequest("SYS")
    await b4.describe_media(AstrMessageEvent(sender="1", text="弹幕呢", messages=[Plain("弹幕呢")]), req)
    expect("other chat: no recent video", (req.extra_user_content_parts, req.system_prompt), ([], "SYS"))
    umo = AstrMessageEvent().unified_msg_origin
    b4._recent_bili[umo] = (time.time() - 3700, b4._recent_bili[umo][1])
    req = ProviderRequest("SYS")
    await b4.describe_media(AstrMessageEvent(text="弹幕呢", messages=[Plain("弹幕呢")]), req)
    expect("an hour later: forgotten", req.extra_user_content_parts, [])
    # 关掉
    b_off, _, _ = make({"bili": False})
    req = ProviderRequest("SYS")
    await b_off.describe_media(AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)]), req)
    expect("bili off", (req.system_prompt, req.extra_user_content_parts), ("SYS", []))
    # 群聊记录：一句话（不看封面、不读弹幕）
    Web.calls = []
    b3, gcc3, caps3 = make()
    await gcc3.handle_message(AstrMessageEvent(group="1", text=SHARE, messages=[Plain(SHARE)]))
    expect("group history line", gcc3.lines[-1], SHARE + f" [Bilibili video: B站视频《{TITLE}》（UP主那谁21，12分2秒）]")
    expect("group history cheap", (caps3, [u for u in Web.calls if "comment" in u]), ([], []))
    await gcc3.handle_message(AstrMessageEvent(group="1", messages=[Json(card)]))
    expect("group card line", gcc3.lines[-1], f" [Bilibili video: B站视频《{TITLE}》（UP主那谁21，12分2秒）]")
    expect("inflight released", dict(b3._inflight_video), {"qq:GroupMessage:1": 0})


asyncio.run(net_tests())


LONG_SUB = {"body": [{"from": i * 4.0, "content": f"第{i}句，佳树对兄长的感情是独一无二的"} for i in range(150)]}
SHORT_SUB = {"body": [{"from": 0, "content": "大家好，今天聊佳树"}, {"from": 600, "content": "就这么多"}]}
JA_SUB = {"body": [{"from": i * 5.0, "content": f"温水佳樹は{i}番目の話"} for i in range(140)]}
EARLY_SUB = {"body": [{"from": i * 1.0, "content": f"别的视频第{i}句"} for i in range(60)]}  # 只到 1 分钟，视频 12 分钟


def api_routes(players=(PLAYER,), sub=LONG_SUB, nav=None, ja=JA_SUB, wrong=EARLY_SUB):
    """players: 播放器接口依次返回的结果（问完了就一直返回最后一个）。"""
    queue = list(players)

    def play(_params, _headers=None):
        data = queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeResp(200, json.dumps(data, ensure_ascii=False).encode())

    def file(body):
        return FakeResp(200, json.dumps(body, ensure_ascii=False).encode())

    return {
        "https://api.bilibili.com/x/player/v2": play,
        "https://api.bilibili.com/x/player/wbi/v2": play,
        "https:" + ZH_URL: file(sub),
        "https:" + WRONG_ZH_URL: file(wrong),
        "https:" + JA_URL: file(ja),
        "https://aisubtitle.hdslb.com/bfs/subtitle/en.json": file(LONG_SUB),
        "https://aisubtitle.hdslb.com/bfs/subtitle/early.json": file(wrong),
        "https://api.bilibili.com/x/web-interface/nav": FakeResp(200, json.dumps(
            nav or {"code": 0, "data": {"isLogin": True, "uname": "晴川"}}, ensure_ascii=False).encode()),
    }


BASE_ROUTES = dict(Web.routes)
COOKIE = "SESSDATA=abc; buvid3=x"
EMPTY = player()


def player_calls():
    return [x for x in Web.sent if "/x/player/" in x[0]]


async def watch(cfg_extra=None, answer=None, **routes):
    Web.routes, Web.sent = {**BASE_ROUTES, **api_routes(**routes)}, []
    b, _, _ = make({"bili_cookie": COOKIE, **PAGE_ONLY, **(cfg_extra or {})},
                   **({"answer": answer} if answer is not None else {}))
    _, text = await b._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    return b, text


async def cookie_tests():
    sys.modules["aiohttp"] = types.SimpleNamespace(ClientSession=FakeSession, ClientTimeout=lambda total=None, **k: None,
                                               ClientConnectionError=ConnectionError, ClientPayloadError=IOError)
    Web.routes, Web.sent = {**BASE_ROUTES, **api_routes()}, []
    b, _, _ = make({"bili_cookie": COOKIE, **PAGE_ONLY})
    await asyncio.sleep(0)  # 启动时的登录检查
    await (b._bili_check or asyncio.sleep(0))
    info3, text = await b._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("watched via subtitles", (text.startswith(f"B站视频《{TITLE}》（UP主：那谁21，12分2秒，动漫杂谈）。看完了，观后笔记：这是一期人物解读视频"),
                                      "开头原话：[00:00] 第0句" in text, text.endswith(bili.SEEN_SUBTITLE),
                                      "弹幕（观众边看边发的" in text), (True, True, True, False))
    prompt = b.context.prompts[-1]
    expect("digest prompt", (f"《{TITLE}》（UP主那谁21，12分2秒）" in prompt, "[02:00] 第30句" in prompt, "字幕对不上" in prompt,
                             "自动翻译" in prompt), (True, True, True, False))
    expect("player params + first try newer endpoint", (player_calls()[0][0].endswith("/x/player/wbi/v2"), player_calls()[0][2]),
           (True, {"cid": "111", "bvid": BV}))
    with_cookie = sorted({x[0].split("/")[2] for x in Web.sent if "Cookie" in x[1]})
    expect("cookie only to api host", with_cookie, ["api.bilibili.com"])
    expect("login check logged", await b._describer.bili_login_status(), "B站已登录：晴川，看视频时会读字幕")

    ev = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    expect("shelf/heart get the notes", "观后笔记" in ev.get_extra("kaju_docs_read")[0]["content"][:200], True)

    # 中文字幕短：整段给她，不调模型
    b, text = await watch(sub=SHORT_SUB)
    expect("short subtitle in full", ("字幕全文（自动识别的可能有错字）：[00:00] 大家好，今天聊佳树 [10:00] 就这么多" in text,
                                      b.context.prompts), (True, []))
    # 串台：别的视频的中文 AI 字幕不用，用这个视频的日文翻译版写中文笔记（不附日文原话）
    b, text = await watch(players=(player(("ai-zh", "中文", WRONG_ZH_URL), ("ai-ja", "日本語", JA_URL)),))
    prompt = b.context.prompts[-1] if b.context.prompts else ""
    expect("wrong-video zh skipped, ja used", ("看完了，观后笔记：" in text, "开头原话" in text, "温水佳樹は0番目" in prompt,
                                                "自动翻译成日本語" in prompt, WRONG_ZH_URL.split("/")[-1][:10] in str(Web.calls)),
           (True, False, True, True, False))
    # 时灵时不灵：第一次只有串台的、第二次才有对的
    b, text = await watch(players=(player(("ai-zh", "中文", WRONG_ZH_URL)), PLAYER))
    expect("retry until a real one", ("看完了，观后笔记" in text, len(player_calls()),
                                      [c[0].rsplit("/", 2)[-2] for c in player_calls()]), (True, 2, ["wbi", "player"]))
    # 一直都是串台的 / 一直没有：默认问 2 次就算了，只看页面
    b, text = await watch(players=(player(("ai-zh", "中文", WRONG_ZH_URL)),))
    expect("always wrong → page only", (text.endswith(bili.SEEN_ONLY_PAGE), len(player_calls()), b.context.prompts), (True, 2, []))
    b, text = await watch(players=(EMPTY, EMPTY, PLAYER), cfg_extra={"bili_sub_tries": 3})
    expect("tries configurable", ("看完了，观后笔记" in text, len(player_calls())), (True, 3))
    # 文件名看不出是谁的、但时间对不上（只有开头一分钟）：也不用，同一个文件不重复下载
    b, text = await watch(players=(player(("zh-CN", "中文", "//aisubtitle.hdslb.com/bfs/subtitle/early.json")),))
    expect("too short for the video → page only", (text.endswith(bili.SEEN_ONLY_PAGE),
                                                    sum(1 for c in Web.calls if c.endswith("early.json"))), (True, 1))
    # 模型说字幕跟视频对不上：不用
    b, text = await watch(answer="字幕对不上")
    expect("mismatch → page only", ("观后笔记" in text, text.endswith(bili.SEEN_ONLY_PAGE)), (False, True))
    # 写笔记的模型出错：中文给开头，翻译版就不给了
    b, text = await watch(answer=RuntimeError("超时"))
    expect("digest fails → head", ("字幕太长没看完，只看了开头：[00:00] 第0句" in text, text.endswith(bili.SEEN_SUBTITLE)), (True, True))
    b, text = await watch(answer=RuntimeError("超时"), players=(player(("ai-ja", "日本語", JA_URL)),))
    expect("digest fails on translation → page only", text.endswith(bili.SEEN_ONLY_PAGE), True)
    # Cookie 过期
    expired = {"code": -101, "message": "账号未登录"}
    b, text = await watch(players=(expired,), nav=expired)
    expect("expired → page only", text.endswith(bili.SEEN_ONLY_PAGE), True)
    expect("expired login status", "登录失效" in await b._describer.bili_login_status(), True)
    # 没填 Cookie：不调接口
    Web.routes, Web.sent = {**BASE_ROUTES, **api_routes()}, []
    b, _, _ = make()
    await b._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("no cookie → no api", [x[0] for x in Web.sent if "api.bilibili.com" in x[0]], [])
    expect("no cookie status", await b._describer.bili_login_status(), "B站没登录（/佳树B站登录 扫码）：只看视频页和弹幕")


asyncio.run(cookie_tests())


# ------------------------------------------------------------------ 下载最低画质看完、整段声音
def make_clip(path, seconds=3, fps=10, tone=True):
    """PyAV 现做一段小视频（底色逐渐变红，带 440Hz 声音）。"""
    import av
    import numpy as np
    from PIL import Image as PILImage

    c = av.open(path, "w")
    vs = c.add_stream("mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 160, 120, "yuv420p"
    aus = c.add_stream("aac", rate=16000, layout="mono")
    for i in range(seconds * fps):
        img = PILImage.new("RGB", (160, 120), (int(255 * i / (seconds * fps)), 40, 40))
        for p in vs.encode(av.VideoFrame.from_image(img)):
            c.mux(p)
    for p in vs.encode():
        c.mux(p)
    t = np.arange(seconds * 16000) / 16000
    pcm = ((np.sin(2 * np.pi * 440 * t) * 8000) if tone else np.zeros_like(t)).astype(np.int16)
    for k in range(0, len(pcm), 1024):
        fr = av.AudioFrame.from_ndarray(pcm[k:k + 1024].reshape(1, -1), format="s16", layout="mono")
        fr.sample_rate = 16000
        for p in aus.encode(fr):
            c.mux(p)
    for p in aus.encode():
        c.mux(p)
    c.close()


class FakeSTT:
    def __init__(self): self.calls = []

    async def get_text(self, audio_url=""):
        self.calls.append(audio_url)
        return f"佳树最重要的是兄长大人第{len(self.calls)}段"


CLIP = os.path.join(tempfile.mkdtemp(), "clip.mp4")
make_clip(CLIP)
MP4 = open(CLIP, "rb").read()
TRACKS = {}
import av

for kind in ("video", "audio"):
    track_path = os.path.join(os.path.dirname(CLIP), kind + ".mp4")
    with av.open(CLIP) as src, av.open(track_path, "w", format="mp4") as dst:
        stream = getattr(src.streams, kind)[0]
        target = dst.add_stream_from_template(stream)
        for packet in src.demux(stream):
            if packet.dts is not None:
                packet.stream = target
                dst.mux(packet)
    TRACKS[kind] = open(track_path, "rb").read()
MOBILE = f"https://m.bilibili.com/video/{BV}"
MP4_URL = "https://upos-sz-mirrorcosov.bilivideo.com/upgcxcode/97/28/111/111-1-16.mp4?e=x&deadline=1"


def mobile_page(url=MP4_URL, size=None, quality=16):
    seg = {"order": 1, "length": 3000, "size": len(MP4) if size is None else size, "url": url.replace("/", "\\u002F")}
    return ('<script>window.__INITIAL_STATE__={"video":{"viewInfo":{"bvid":"%s"},"streamQuality":%s,"playUrlInfo":[%s]}};'
            '</script>' % (BV, quality, json.dumps(seg).replace("\\\\u002F", "\\u002F"))).encode()


VIDEO_CFG = {"audio_chunk_seconds": 1, "video_speech_direct": 10, "video_grid": 2, "video_grid_long": 2}


async def download_tests():
    sys.modules["aiohttp"] = types.SimpleNamespace(ClientSession=FakeSession, ClientTimeout=lambda total=None, **k: None,
                                               ClientConnectionError=ConnectionError, ClientPayloadError=IOError)
    routes = {**BASE_ROUTES, MOBILE: FakeResp(200, mobile_page()), MP4_URL: FakeResp(200, MP4)}
    Web.routes, Web.sent, Web.calls = dict(routes), [], []
    b, _, caps = make(VIDEO_CFG, answer="这是一期人物解读，UP主说佳树最重要的是兄长大人。「佳树最重要的是兄长大人」")
    stt = FakeSTT()
    b.context.stt = stt
    d = b._describer
    for name in os.listdir(d.download_dir()):
        os.remove(os.path.join(d.download_dir(), name))
    info5, text = await d.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("downloaded + watched", (text.startswith(f"B站视频《{TITLE}》（UP主：那谁21，12分2秒，动漫杂谈）。3秒的视频，看完了。画面："),
                                    "观后笔记：这是一期人物解读" in text, text.endswith(bili.SEEN_VIDEO), "封面：" in text),
           (True, True, True, False))
    mp4_req = next(x for x in Web.sent if x[0] == MP4_URL)
    expect("lowest quality from mobile page, referer = that page", mp4_req[1].get("Referer"), MOBILE)
    expect("whole audio in 1s chunks", len(stt.calls), 3)
    prompt = b.context.prompts[-1]
    expect("watch digest prompt", (f"视频《{TITLE}》（3秒）" in prompt, "画面：温水佳树捧着脸" in prompt,
                                   "[00:01] 佳树最重要的是兄长大人" in prompt), (True, True, True))
    expect("frame caption knows the title", f"视频《{TITLE}》" in caps[-1][1], True)
    saved = os.path.join(d.download_dir(), f"{BV}-p1.mp4")
    expect("kept for a while", (os.path.isfile(saved), [n for n in os.listdir(d.download_dir()) if n.endswith(".part")]),
           (True, []))
    expect("no chunk wavs left", [n for n in os.listdir(os.path.dirname(d.download_dir())) if n.startswith("kaju_audio_")], [])
    # 换个插件实例（缓存没了）再看：直接用下好的文件，不重新下载
    Web.routes, Web.sent = dict(routes), []
    b2, _, _ = make(VIDEO_CFG)
    b2.context.stt = FakeSTT()
    await b2._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("reuse downloaded file", [x[0] for x in Web.sent if x[0] == MP4_URL], [])
    # 过了 bili_keep_hours（默认 2 小时）自动删
    expect("not yet", d.cleanup_downloads(time.time() + 3600), [])
    expect("deleted after keep hours", (d.cleanup_downloads(time.time() + 3 * 3600), os.path.exists(saved)),
           ([f"{BV}-p1.mp4"], False))
    # A mobile page can return a 106 MB 1080p file; use the smaller DASH video AND audio.
    play_api = "https://api.bilibili.com/x/player/playurl"
    video_url = "https://upos-sz-mirrorcosov.bilivideo.com/low-video.m4s"
    audio_url = "https://upos-sz-mirrorcosov.bilivideo.com/low-audio.m4s"
    dash = {"code": 0, "data": {"dash": {
        "video": [{"id": 32, "bandwidth": 1, "baseUrl": MP4_URL},
                  {"id": 16, "bandwidth": 200, "baseUrl": MP4_URL},
                  {"id": 16, "bandwidth": 100, "base_url": video_url}],
        "audio": [{"id": 30280, "bandwidth": 320000, "baseUrl": MP4_URL},
                  {"id": 30216, "bandwidth": 64000, "baseUrl": audio_url}]}}}

    def slow_hd(_params, _headers):
        raise asyncio.TimeoutError("1080p download timed out")

    def dash_source(body):
        def get(_params, headers):
            if "Mobile" in headers.get("User-Agent", "Mobile"):
                return FakeResp(403)
            if headers.get("Range") != "bytes=0-":
                return FakeResp(567)
            return FakeResp(206, body)
        return get

    Web.routes, Web.sent = {**routes, MOBILE: FakeResp(200, mobile_page(size=111184741, quality=80)),
                            MP4_URL: slow_hd, play_api: FakeResp(200, json.dumps(dash).encode()),
                            video_url: dash_source(TRACKS["video"]),
                            audio_url: dash_source(TRACKS["audio"])}, []
    low, _, caps = make(VIDEO_CFG)
    low.context.stt = FakeSTT()
    _, text = await low._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("1080p mobile source still watched with low-quality DASH", text.endswith(bili.SEEN_VIDEO), True)
    expect("DASH keeps frames and all audio", (len(caps), len(low.context.stt.calls)), (1, 3))
    expect("oversized mobile MP4 is not downloaded", any(u == MP4_URL for u, _, _ in Web.sent), False)
    if os.path.exists(saved):
        with av.open(saved) as merged:
            expect("DASH merged into one playable video with audio", (len(merged.streams.video), len(merged.streams.audio)), (1, 1))
        os.remove(saved)
    limited, _, _ = make({**VIDEO_CFG, "video_max_mb": (len(TRACKS["video"]) + len(TRACKS["audio"]) - 1) / 1024 / 1024})
    _, text = await limited._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("combined DASH tracks obey size limit and clean partial files",
           (text.endswith(bili.SEEN_ONLY_PAGE), os.listdir(limited._describer.download_dir())), (True, []))
    Web.routes, Web.sent = {**routes, MOBILE: FakeResp(200, mobile_page(quality=80))}, []
    fallback, _, _ = make(VIDEO_CFG)
    fallback.context.stt = FakeSTT()
    _, text = await fallback._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
    expect("DASH unavailable still uses mobile MP4", text.endswith(bili.SEEN_VIDEO), True)
    if os.path.exists(saved):
        os.remove(saved)
    # 下不了：视频地址不是 B 站的服务器 / 太大 / 页面上没有地址 / 太长不下 → 退回只看页面（有封面）
    for label, extra, cfg in (
            ("video host refused", {MOBILE: FakeResp(200, mobile_page(url="https://evil.example.com/a.mp4"))}, {}),
            ("too big", {MOBILE: FakeResp(200, mobile_page(size=500 * 1024 * 1024))}, {}),
            ("no play url", {MOBILE: FakeResp(200, b"<html></html>")}, {}),
            ("too long: not downloaded", {}, {"bili_max_minutes": 5})):
        Web.routes, Web.sent = {**routes, **extra}, []
        bx, _, _ = make({**VIDEO_CFG, **cfg})
        _, t = await bx._describer.bili_video("https://b23.tv/iOcLavf", AstrMessageEvent())
        expect(label, (t.endswith(bili.SEEN_ONLY_PAGE), "封面：" in t, os.listdir(bx._describer.download_dir())), (True, True, []))
    expect("too long: page not even asked", any(MOBILE in x[0] for x in Web.sent), False)

    # 分段同时下载：拼出来跟原文件一模一样；服务器不支持分段（不理 Range，给 200 整个文件）就改成一条线下
    def ranged(_params, headers):
        rng = (headers or {}).get("Range", "")
        if not rng:
            return FakeResp(200, MP4)
        a, b_ = (int(x) for x in rng.split("=")[1].split("-"))
        return FakeResp(206, MP4[a:b_ + 1])

    for label, route, want_ranges in (("parallel ranges", ranged, 3), ("no range support → one stream", lambda p, h: FakeResp(200, MP4), 0)):
        Web.routes, Web.sent = {**routes, MP4_URL: route}, []
        br, _, _ = make({**VIDEO_CFG, "bili_parts_min_mb": 0, "bili_download_parts": 3})
        for name in os.listdir(br._describer.download_dir()):
            os.remove(os.path.join(br._describer.download_dir(), name))
        p = await br._describer._bili_download(info5)
        expect(label, (open(p, "rb").read() == MP4, sum(1 for x in Web.sent if x[0] == MP4_URL and "Range" in x[1]) if want_ranges
                       else sum(1 for x in Web.sent if x[0] == MP4_URL and x[1].get("Range", "bytes=0-") == "bytes=0-"),
                       [n for n in os.listdir(br._describer.download_dir()) if ".part" in n]),
               (True, want_ranges or 1, []))
        os.remove(p)

    # 要下载看一会儿：先让写手说一句"先去看"；看过了（缓存里有）再问就不说；只看页面时也不说
    Web.routes = dict(routes)
    bw, _, _ = make(VIDEO_CFG)
    bw.context.stt = FakeSTT()
    ev = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    await bw.describe_media(ev, ProviderRequest("SYS"))
    writer = bw.context.stars[1].star_cls
    expect("wait notice first (written by the writer)", (ev.sent, writer.cards[0][0][0]),
           (["佳树先去看看哦"], "佳树去看视频"))
    ev2 = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    await bw.describe_media(ev2, ProviderRequest("SYS"))
    expect("no notice once watched", ev2.sent, [])
    bpo, _, _ = make(PAGE_ONLY)
    ev3 = AstrMessageEvent(text=SHARE, messages=[Plain(SHARE)])
    await bpo.describe_media(ev3, ProviderRequest("SYS"))
    expect("no notice when page only", ev3.sent, [])
    for name in os.listdir(bw._describer.download_dir()):
        os.remove(os.path.join(bw._describer.download_dir(), name))
    # 直接发的长视频文件也先说一声（这里把"长"设成 1 秒）；短的不说
    from astrbot.api.message_components import Video as V
    for label, secs, n in (("long video file notice", 1, 1), ("short video file: no notice", 90, 0)):
        bl, _, _ = make({**VIDEO_CFG, "wait_notice_seconds": secs})
        bl.context.stt = FakeSTT()
        ev4 = AstrMessageEvent(messages=[V.fromFileSystem(CLIP)])
        await bl.describe_media(ev4, ProviderRequest("SYS"))
        expect(label, len(ev4.sent), n)

    # 直接发的视频文件：整段声音都听（之前只听前 90 秒），话多就写观后笔记
    bv, _, _ = make({"audio_chunk_seconds": 1, "video_speech_direct": 10})
    bv.context.stt = FakeSTT()
    out = await bv._describer.video(types.SimpleNamespace(file="clip.mp4", path=CLIP, convert_to_file_path=_path(CLIP)),
                                    AstrMessageEvent())
    expect("sent video: notes from whole audio", (out.startswith("3秒的视频，看完了。画面："), "观后笔记：" in out,
                                                  len(bv.context.stt.calls)), (True, True, 3))
    # 只听前 2 秒：说明一下
    bp, _, _ = make({"audio_chunk_seconds": 1, "video_audio_seconds": 2})
    bp.context.stt = FakeSTT()
    out = await bp._describer.video(types.SimpleNamespace(file="c2.mp4", path=CLIP, convert_to_file_path=_path(CLIP)),
                                    AstrMessageEvent())
    expect("partial listen noted", ("（只听了前 2秒）" in out, len(bp.context.stt.calls)), (True, 2))
    # 说的话少：原样给（不调模型）
    bs, _, _ = make({})
    bs.context.stt = FakeSTT()
    out = await bs._describer.video(types.SimpleNamespace(file="c3.mp4", path=CLIP, convert_to_file_path=_path(CLIP)),
                                    AstrMessageEvent())
    expect("short speech verbatim", (out, bs.context.prompts),
           ("3秒的视频。温水佳树捧着脸，大字「佳树的独特」 视频里的声音（自动转写，可能有错字）：「佳树最重要的是兄长大人第1段」", []))


def _path(p):
    async def convert():
        return p
    return convert


asyncio.run(download_tests())
if real_aiohttp is not None:
    sys.modules["aiohttp"] = real_aiohttp
else:
    sys.modules.pop("aiohttp", None)

# ------------------------------------------------------------------ 心情、珍藏
p = appraise.build_prompt(who="晴川", is_owner=True, level="", place="群聊", context="很多群聊记录……",
                          said=SHARE, reply="诶，是讲佳树的……", shared=[f"《{TITLE}》（B站视频）：B站视频《{TITLE}》……"])
expect("appraise sees shared video", ("【TA这次分享给佳树的东西】" in p, "（B站视频）" in p,
                                       p.index("【TA这次分享") < p.index("【TA这次说的】")), (True, True, True))
expect("appraise without shared", "分享给佳树的东西" in appraise.build_prompt(
    who="a", is_owner=False, level="普通", place="私聊", context="", said="hi", reply="hi"), False)
rp = shelf.rate_prompt(who="兄长大人", place="私聊", said="", context="", file=TITLE, content="B站视频……",
                       reply="……", feeling="害羞（明显）", kind="B站视频")
expect("shelf rate prompt kind", (f"【B站视频】《{TITLE}》" in rp, "（只发了B站视频，没说别的）" in rp), (True, True))
tz = dt.timezone(dt.timedelta(hours=8))
item = {"created": dt.datetime(2026, 10, 31, 23, 14, tzinfo=tz).timestamp(), "file": TITLE, "memory": "讲佳树的视频",
        "feeling": "害羞", "kind": "B站视频"}
expect("shelf index video", shelf.index_line(item, tz, "兄长大人"), f"- 10月31日《{TITLE}》（B站视频）：讲佳树的视频（看完害羞）")
item.pop("kind")
expect("shelf index file unchanged", shelf.index_line(item, tz, "兄长大人"), f"- 10月31日《{TITLE}》：讲佳树的视频（读完害羞）")


# ------------------------------------------------------------------ live
async def live(url: str):
    """真联网打开链接 + 真模型：封面描述 → 她用真人设回复 3 次 → 情绪判断 → 珍藏评分量（只打印）。"""
    import base64

    from openai import AsyncOpenAI

    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])

    async def chat(system, user, image=None):
        content = user if image is None else [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image}}]
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
        r = await cli.chat.completions.create(model="deepseek-flash", messages=msgs)
        return r.choices[0].message.content.strip()

    # 用机器人现在的插件配置（填了 B 站 Cookie 就会读字幕；Cookie 不打印）
    plugin_cfg = os.path.join(core, "data", "config", "astrbot_plugin_kaju_basics_config.json")
    media_cfg = json.load(open(plugin_cfg, encoding="utf-8-sig")).get("media", {}) if os.path.exists(plugin_cfg) else {}
    b, _, _ = make(media_cfg)

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        return LLMResponse(await chat(system_prompt or "", prompt))

    b.context.llm_generate = llm_generate
    # 跟机器人用的同一个语音转文字：本地 SenseVoice（2026-11-02 起不再用硅基流动）
    stt_sec = json.load(open(plugin_cfg, encoding="utf-8-sig")).get("stt", {}) if os.path.exists(plugin_cfg) else {}
    from kaju_core.senses import localstt
    sv = localstt.SenseVoice(stt_sec.get("model_dir", r"D:\JiashuBot\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"),
                             stt_sec.get("vad_model", r"D:\JiashuBot\models\silero_vad.onnx"))
    if not sv.check():
        class LiveSTT:
            async def get_text(self, audio_url=""):
                return await asyncio.to_thread(sv.transcribe, audio_url)

        b.context.stt = LiveSTT()
    else:
        print("本地语音转文字没装好：", sv.check())
    print("B站登录：", await b._describer.bili_login_status())

    async def caption(path, prompt, umo):
        data = base64.b64encode(open(path, "rb").read()).decode()
        return await chat("", prompt, image=f"data:image/jpeg;base64,{data}")

    b._describer.caption = caption
    ev = AstrMessageEvent(text=url, messages=[Plain(url)])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    part = req.extra_user_content_parts[0].text
    print(f"=== 她看到的（{len(part)} 字）\n{part}\n")
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()
    user = f"[发言人：晴川（QQ 111111111）] {url}\n{part}\n\n<system_reminder>{kb.BILI_NOTE}</system_reminder>"
    replies = await asyncio.gather(*(chat(persona, user) for _ in range(3)))
    for r in replies:
        print("佳树：", r.replace("\n", " / "))
    asked = await chat(persona, user.replace(url, url + " 你觉得up主讲的对吗"))
    print("（问她内容）佳树：", asked.replace("\n", " / "))
    read = ev.get_extra("kaju_docs_read")[0]
    prompt = appraise.build_prompt(who="晴川", is_owner=True, level="", place="私聊", context=part[-600:],
                                   said=url, reply=replies[0],
                                   shared=[f"《{read['name']}》（{read['kind']}）：{read['content'][:600]}"])
    print("\n=== 情绪判断\n", appraise.parse(await chat(appraise.system_prompt(), prompt)))
    rate = await chat(shelf.rate_system("兄长大人"), shelf.rate_prompt(
        who="兄长大人", place="私聊", said=url, context="", file=read["name"], content=read["content"],
        reply=replies[0], feeling="", kind=read["kind"]))
    print("\n=== 珍藏评分量\n", shelf.parse_rate(rate))
    removed = b._describer.cleanup_downloads(time.time() + 365 * 86400)  # 测试下载的视频不留
    print("删掉测试下载的视频：", removed)


if "--live" in sys.argv:
    rest = [a for a in sys.argv[1:] if a != "--live"]
    asyncio.run(live(rest[0] if rest else "https://b23.tv/iOcLavf"))
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
