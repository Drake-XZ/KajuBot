"""Offline tests for 抖音链接（kaju_basics douyin.py + Describer.douyin_video + describe_media）.

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_douyin.py
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_douyin.py --live [抖音链接或分享文字]
        真开本机 Chrome（后台）打开链接：打印作品信息、高赞评论、下载的视频大小，再用本地 SenseVoice 听一遍（只打印，看完删掉）
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import Json, Plain, Reply  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402

dy = importlib.import_module("kaju_platforms.douyin.douyin")
kb = importlib.import_module("kaju_basics.main")
failures = []


class FakeWriter:
    """kaju_style 的本地写手：先说的那句由它照卡片写。"""

    def __init__(self):
        self.cards = []

    async def say_from_card(self, event, points, **kw):
        self.cards.append(points)
        return points[0] + "哦"


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


SHARE = ("3.87 复制打开抖音，看看【小杨数码说的作品】超简单教程！手把手教你把蓝色大肥鱼接入抖音，不仅能... "
         "https://v.douyin.com/Bvf9hl0ibGA/ r@e.bN :7pm 08/24 uFH:/ ")
AID = "7702990304026871269"

# ------------------------------------------------------------------ 认链接
expect("share text", dy.find_links(SHARE), ["https://v.douyin.com/Bvf9hl0ibGA/"])
expect("web links + dedupe", dy.find_links(
    f"https://www.douyin.com/video/{AID} 和 https://www.iesdouyin.com/share/video/{AID}/?region=AU 还有 "
    "https://www.douyin.com/jingxuan?modal_id=7697973875389584548，图文 https://www.douyin.com/note/7600000000000000001", 5),
    [f"https://www.douyin.com/video/{AID}", "https://www.douyin.com/jingxuan?modal_id=7697973875389584548",
     "https://www.douyin.com/note/7600000000000000001"])
expect("no false hits", dy.find_links("抖音 douyin.com 还有 https://www.douyin.com/user/abc 和 v.douyin.com 没有协议"), [])
expect("limit", len(dy.find_links(" ".join(f"https://v.douyin.com/a{i}/" for i in range(5)))), 2)
expect("aweme id", (dy.aweme_id(f"https://www.iesdouyin.com/share/video/{AID}/?x=1"),
                    dy.aweme_id("https://www.douyin.com/jingxuan?modal_id=7697973875389584548"), dy.aweme_id("https://v.douyin.com/x/")),
       (AID, "7697973875389584548", ""))
card = {"app": "com.tencent.structmsg", "meta": {"news": {"title": "抖音", "jumpUrl": "https://v.douyin.com/Bvf9hl0ibGA/"}}}
expect("qq card", dy.card_links({"data": json.dumps(card)}), ["https://v.douyin.com/Bvf9hl0ibGA/"])
expect("hosts", (dy.host_ok("https://www.iesdouyin.com/x"), dy.host_ok("https://douyin.com.evil.cn/x"),
                 dy.host_ok("https://v5-dy-ov-experiment.zjcdn.com/v", dy.MEDIA_HOSTS), dy.host_ok("https://evil.cn/zjcdn.com", dy.MEDIA_HOSTS)),
       (True, False, True, False))
expect("page url", (dy.page_url(AID), dy.page_url(AID, note=True)),
       (f"https://www.douyin.com/video/{AID}", f"https://www.douyin.com/note/{AID}"))
expect("title from desc", dy.title_of("超简单教程！手把手教你🐟✅#DeepSeek #deepseek #保姆级教程 @抖音小助手"), "超简单教程！手把手教你🐟✅")

# ------------------------------------------------------------------ 页面收到的数据
DETAIL = {"aweme_detail": {
    "aweme_id": AID, "desc": "超简单教程！手把手教你把蓝色大肥鱼接入抖音#DeepSeek #deepseek #保姆级教程 @抖音小助手",
    "duration": 39000, "author": {"nickname": "小杨数码说"}, "item_title": "",
    "statistics": {"digg_count": 2520, "comment_count": 185, "collect_count": 2093, "share_count": 780},
    "text_extra": [{"hashtag_name": "deepseek"}, {"hashtag_name": "deepseek"}, {"hashtag_name": "保姆级教程"}, {"user_id": "1"}],
    "video_tag": [{"tag_name": "个人管理"}, {"tag_name": "职场技能"}],
    "music": {"title": "暖律轻环", "author": "纯音空间"}, "is_aigc_media": 1, "images": None,
    "video": {"duration": 39000, "cover": {"url_list": ["https://p3-pc-sign.douyinpic.com/c.jpg"]},
              "play_addr": {"url_list": ["https://v3-dy-o.zjcdn.com/big"]},
              "bit_rate": [{"bit_rate": 693087, "play_addr": {"url_list": ["https://v3-dy-o.zjcdn.com/1080"], "data_size": 3378803}},
                           {"bit_rate": 233858, "play_addr": {"url_list": ["https://v5-dy.zjcdn.com/540a", "https://www.douyin.com/aweme/v1/play/?x"],
                                                              "data_size": 1140060}},
                           {"bit_rate": 300000, "play_addr": {"url_list": []}}]}}}
info = dy.parse_detail(DETAIL)
_rates = {"aweme_detail": {"aweme_id": "9", "desc": "#MMD", "author": {"nickname": "a"}, "video": {"bit_rate": [
    {"bit_rate": 362161, "format": "mp4", "play_addr": {"url_list": ["https://v.douyinvod.com/mp4"], "data_size": 2990869}},
    {"bit_rate": 333445, "format": "dash", "play_addr": {"url_list": ["https://v.douyinvod.com/dash"], "data_size": 2753711}},
    {"bit_rate": 900000, "format": "mp4", "play_addr": {"url_list": ["https://v.douyinvod.com/big"], "data_size": 9000000}}]}}}
expect("lowest muxed mp4, not video-only dash", dy.parse_detail(_rates)["video_urls"], ["https://v.douyinvod.com/mp4"])
expect("detail: basics", (info["id"], info["title"], info["author"], info["duration"], info["stat"]),
       (AID, "超简单教程！手把手教你把蓝色大肥鱼接入抖音", "小杨数码说", 39.0,
        {"like": 2520, "comment": 185, "collect": 2093, "share": 780}))
expect("detail: lowest bitrate first", (info["video_urls"], info["video_size"]),
       (["https://v5-dy.zjcdn.com/540a", "https://www.douyin.com/aweme/v1/play/?x"], 1140060))
expect("detail: tags/category/music/ai", (info["tags"], info["category"], info["music"], info["ai"]),
       (["deepseek", "保姆级教程"], "个人管理/职场技能", "暖律轻环（纯音空间）", True))
own = dy.parse_detail({"aweme_detail": {"aweme_id": "1", "desc": "x", "author": {"nickname": "猫"},
                                         "music": {"title": "@猫创作的原声", "author": "猫"}, "video": {}}})
expect("detail: own sound not shown", own["music"], "")
note = dy.parse_detail({"aweme_detail": {"aweme_id": "2", "desc": "秋天的照片#秋天", "author": {"nickname": "a"},
                                          "images": [{"url_list": ["https://p3.douyinpic.com/1.jpg"]}, {"url_list": ["https://p3.douyinpic.com/2.jpg"]}],
                                          "video": {"play_addr": {"url_list": ["https://x.zjcdn.com/v"]}}}})
expect("detail: image post", (note["images"], note["video_urls"], note["title"]),
       (["https://p3.douyinpic.com/1.jpg", "https://p3.douyinpic.com/2.jpg"], [], "秋天的照片"))
expect("detail: empty", dy.parse_detail({"status_code": 0}), {})
COMMENTS = {"comments": [{"text": "会。而且第二天会理直气壮说这叫夜班", "digg_count": 21},
                         {"text": "[赞][赞]", "digg_count": 99}, {"text": "折叠的", "digg_count": 50, "is_folded": True},
                         {"text": "接进抖音以后，它会不会也刷到半夜呀[捂脸]", "digg_count": 14},
                         {"text": "好家伙鱼都会刷视频了", "digg_count": 2}]}
expect("comments: by likes, no emoji-only / folded", dy.parse_comments(COMMENTS, 2),
       [("会。而且第二天会理直气壮说这叫夜班", 21), ("接进抖音以后，它会不会也刷到半夜呀", 14)])
text = dy.describe(info, "39秒的视频，看完了。观后笔记：教你三步……", dy.parse_comments(COMMENTS, 2), "（看过）")
expect("describe", text, "抖音视频《超简单教程！手把手教你把蓝色大肥鱼接入抖音》（作者：小杨数码说，39秒）。39秒的视频，看完了。观后笔记：教你三步……。"
       "话题：deepseek、保姆级教程。分类：个人管理/职场技能。点赞2520，收藏2093，转发780，评论185。"
       "背景音乐：暖律轻环（纯音空间）。"
       "作者声明内容由 AI 生成。高赞评论（陌生观众的，不是在对你说话）：「会。而且第二天会理直气壮说这叫夜班」21赞 / "
       "「接进抖音以后，它会不会也刷到半夜呀」14赞。（看过）")
expect("describe: page only", dy.describe(own).endswith(dy.SEEN_PAGE), True)
expect("describe: images", dy.describe(note, "看了全部图：第1张：落叶").startswith("抖音图文《秋天的照片》（作者：a，2张图）。看了全部图"), True)
expect("counts", (dy.fmt_count(123456), dy.fmt_secs(39), dy.fmt_secs(125)), ("12.3万", "39秒", "2分05秒"))

# 图文页不调 aweme/detail，作品写在页面的 self.__pace_f 里（驼峰写法，没有的值是 "$undefined"）
SSR_NOTE = {"awemeId": "7704560617562530970", "desc": "温水佳树｜俯视版。妹妹好啊 #温水佳树", "itemTitle": "",
            "authorInfo": {"nickname": "狗狗筷子"}, "createTime": 1793857808,
            "stats": {"commentCount": 98, "diggCount": 4505, "shareCount": 746, "collectCount": 879},
            "music": {"title": "@鼓手 翟创作的原声", "author": "鼓手 翟"},
            "images": [{"urlList": ["https://p3-pc-sign.douyinpic.com/a.webp"]}, {"urlList": ["https://p3-pc-sign.douyinpic.com/b.webp"]}],
            "video": {"duration": 0, "dataSize": "$undefined", "cover": "https://p3.douyinpic.com/c.jpg",
                      "playAddr": [{"src": "https://sf6-cdn-tos.douyinstatic.com/obj/ies-music/1.mp3"}]},
            "textExtra": [{"hashtagName": ""}, {"hashtagName": "温水佳树"}],
            "videoTag": [{"tagName": "二次元"}, {"tagName": "动漫IP"}]}
chunk = "7:" + json.dumps(["$", "$L9", None, {"awemeId": SSR_NOTE["awemeId"], "aweme": {"statusCode": 0, "detail": SSR_NOTE}}],
                          ensure_ascii=False)
ssr = dy.parse_detail(dy.ssr_detail(["2:[]\n" + chunk], SSR_NOTE["awemeId"]))
expect("ssr: image post from page data",
       (ssr["id"], ssr["author"], ssr["images"], ssr["video_urls"], ssr["tags"], ssr["category"], ssr["music"], ssr["stat"]),
       ("7704560617562530970", "狗狗筷子", ["https://p3-pc-sign.douyinpic.com/a.webp", "https://p3-pc-sign.douyinpic.com/b.webp"], [],
        ["温水佳树"], "二次元/动漫IP", "",
        {"like": 4505, "comment": 98, "collect": 879, "share": 746}))
expect("ssr: other aweme ignored", dy.ssr_detail([chunk], "123456789012345"), {})
expect("ssr: junk", dy.ssr_detail(["not json", "1:{bad"], "1"), {})
expect("captcha: login box is not a captcha", dy._captcha("登录后免费畅享高清视频 验证码登录 密码登录", "https://www.douyin.com/note/1"), False)
expect("captcha: real one", (dy._captcha("请完成下列验证后继续", ""), dy._captcha("", "https://verify.douyin.com/x")), (True, True))
def _png(w, h):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 100, 50)).save(out, "PNG")
    return out.getvalue()


def _size(data):
    import io

    from PIL import Image

    return Image.open(io.BytesIO(data)).size


big, big_ext = dy.shrink(_png(1856, 2464), 1024)
expect("shrink: big image fits the vision model", (_size(big), big_ext), ((771, 1024), ".jpg"))
small_png = _png(400, 300)
expect("shrink: small image untouched", dy.shrink(small_png, 1024), (small_png, ".png"))
expect("shrink: not an image → as is", dy.shrink(b"RIFF\0\0\0\0WEBPjunk", 1024), (b"RIFF\0\0\0\0WEBPjunk", ".webp"))

FEED = {"aweme_list": [
    {"aweme_id": "7703997413695219810", "desc": "谁小时候能忍住不看蚂蚁搬家呢 #童年", "author": {"nickname": "我叫涂布"},
     "duration": 68000, "statistics": {"digg_count": 845395}, "video_tag": [{"tag_name": "二次元"}, {"tag_name": "动漫IP"}],
     "video": {"play_addr": {"url_list": ["https://v3.zjcdn.com/a.mp4"]}}},
    {"aweme_id": "7700000000000000001", "desc": "广告", "is_ads": True, "video": {"play_addr": {"url_list": ["x"]}}},
    {"aweme_id": "7700000000000000002", "desc": "直播中", "cell_room": {"rawdata": "{}"}},
    {"aweme_id": "7700000000000000003", "desc": "秋天", "author": {"nickname": "a"},
     "images": [{"url_list": ["https://p3.douyinpic.com/1.jpg"]}]},
]}
SEARCH = {"data": [{"type": 1, "aweme_info": FEED["aweme_list"][0]}, {"type": 999}]}
cands = [dy.candidate(a) for a in dy.feed_items(FEED)]
expect("feed: ads / live dropped, image post kept",
       [(c["bvid"], c["title"], c["up"], c["duration"], c["likes"], c["tname"], c["reason"], c["url"]) for c in cands if c],
       [("dy7703997413695219810", "谁小时候能忍住不看蚂蚁搬家呢", "我叫涂布", 68, 845395, "动漫IP", "",
         "https://www.douyin.com/video/7703997413695219810"),
        ("dy7700000000000000003", "秋天", "a", 0, 0, "", "图文", "https://www.douyin.com/note/7700000000000000003")])
expect("search: aweme_info unwrapped", [a["aweme_id"] for a in dy.feed_items(SEARCH)], ["7703997413695219810"])
expect("image ext",(dy._img_ext(b"RIFF\0\0\0\0WEBPVP8 "), dy._img_ext(b"\x89PNG\r\n\x1a\n.."), dy._img_ext(b"\xff\xd8\xff")),
       (".webp", ".png", ".jpg"))


# ------------------------------------------------------------------ Describer + describe_media（假浏览器）
class FakeProvider:
    provider_config = {"id": "ds"}


async def plugin_tests():
    ctx = Context()
    ctx.stars = [type("Meta", (), {"star_cls": FakeWriter()})()]
    ctx.providers = {"ds": FakeProvider()}
    b = kb.KajuBasics(ctx, {"media": {}})
    calls = []
    results = {}

    async def fake_fetch(url, out_dir, **kw):
        calls.append((url, kw))
        r = results[url]
        if isinstance(r, Exception):
            raise r
        return r
    orig = dy.fetch
    dy.fetch = fake_fetch
    watched = []

    async def watch(comp, event, title="", listen_music=False):
        watched.append((comp.path, title, event.unified_msg_origin))
        return "39秒的视频，看完了。画面：……观后笔记：三步接入"
    b._describer.watch = watch
    caps = []

    async def caption(path, prompt, umo):
        caps.append((os.path.basename(path), prompt))
        return "落叶铺满小路"
    b._describer.caption = caption
    try:
        vid = os.path.join(os.environ["STUB_DATA"], "douyin_x.mp4")
        open(vid, "wb").write(b"x")
        results["https://v.douyin.com/Bvf9hl0ibGA/"] = {"info": info, "comments": dy.parse_comments(COMMENTS), "video": vid, "images": []}
        ev = AstrMessageEvent(sender="111111111", text=SHARE + "\n你看一下这个", messages=[Plain(SHARE + "\n你看一下这个")])
        req = ProviderRequest(system_prompt="BASE")
        await b.describe_media(ev, req)
        parts = [p.text for p in req.extra_user_content_parts]
        expect("media: one douyin part", len(parts), 1)
        expect("media: watched + comments", (parts[0].startswith("[Douyin video: 抖音视频《超简单教程"), "观后笔记：三步接入" in parts[0],
                                             "理直气壮说这叫夜班" in parts[0], bool(dy.SEEN_PAGE in parts[0])), (True, True, True, False))
        expect("media: note added", "【关于抖音】" in req.system_prompt, True)
        expect("media: watched the downloaded file with title", watched, [(vid, info["title"], ev.unified_msg_origin)])
        read = ev.get_extra("kaju_docs_read")
        expect("media: shared content for heart/shelf", (read[0]["kind"], read[0]["name"], read[0]["url"]),
               ("抖音视频", info["title"], f"https://www.douyin.com/video/{AID}"))
        expect("fetch options from config", (calls[0][1]["channel"], calls[0][1]["max_seconds"], calls[0][1]["max_images"]),
               ("chrome", 1200.0, 4))
        expect("wait notice said once", len(ev.sent), 1)
        # 同一个作品半小时内不再开浏览器
        ev2 = AstrMessageEvent(sender="111111111", text="https://v.douyin.com/Bvf9hl0ibGA/", messages=[Plain("https://v.douyin.com/Bvf9hl0ibGA/")])
        await b.describe_media(ev2, ProviderRequest())
        expect("cached", len(calls), 1)
        # 引用的消息里的链接
        results["https://www.douyin.com/note/7600000000000000002"] = {"info": dict(note, id="7600000000000000002"), "comments": [], "video": "",
                                                    "images": [os.path.join(os.environ["STUB_DATA"], "douyin_2_1.jpg")]}
        open(results["https://www.douyin.com/note/7600000000000000002"]["images"][0], "wb").write(b"x")
        quoted = Reply(chain=[Plain("https://www.douyin.com/note/7600000000000000002")]) if "chain" in Reply.__init__.__code__.co_varnames else None
        if quoted is None:
            quoted = Reply()
            quoted.chain = [Plain("https://www.douyin.com/note/7600000000000000002")]
        ev3 = AstrMessageEvent(sender="111111111", text="这个呢", messages=[quoted, Plain("这个呢")])
        req3 = ProviderRequest()
        await b.describe_media(ev3, req3)
        p3 = req3.extra_user_content_parts[0].text
        expect("quoted image post", (p3.startswith("[Douyin video in quoted message: 抖音图文《秋天的照片》"), "第1张：落叶铺满小路" in p3,
                                     os.path.exists(results["https://www.douyin.com/note/7600000000000000002"]["images"][0])), (True, True, False))
        expect("image prompt", "第 1 张图（共 2 张）" in caps[0][1], True)
        # 没看成
        results["https://v.douyin.com/bad/"] = dy.SkipDouyin("抖音要人机验证，佳树没看成")
        ev4 = AstrMessageEvent(sender="111111111", text="https://v.douyin.com/bad/", messages=[Plain("https://v.douyin.com/bad/")])
        req4 = ProviderRequest()
        await b.describe_media(ev4, req4)
        expect("skip → honest", req4.extra_user_content_parts[0].text, "[Douyin video: 没打开：抖音要人机验证，佳树没看成]")
        expect("skip → nothing shared", ev4.get_extra("kaju_docs_read"), None)
        await b.describe_media(ev4, ProviderRequest())
        expect("failures are retried next time", len([c for c in calls if c[0] == "https://v.douyin.com/bad/"]), 2)
        results["https://v.douyin.com/boom/"] = RuntimeError("chrome crashed")
        ev5 = AstrMessageEvent(sender="111111111", text="https://v.douyin.com/boom/", messages=[Plain("https://v.douyin.com/boom/")])
        req5 = ProviderRequest()
        await b.describe_media(ev5, req5)
        expect("crash → honest", req5.extra_user_content_parts[0].text, "[Douyin video: 没打开：抖音链接没能打开，佳树没看到是什么视频]")
        # 关掉
        b.config["media"]["douyin"] = False
        req6 = ProviderRequest()
        await b.describe_media(AstrMessageEvent(sender="1", text=SHARE, messages=[Plain(SHARE)]), req6)
        expect("off", req6.extra_user_content_parts, [])
        # QQ 卡片
        b.config["media"]["douyin"] = True
        ev7 = AstrMessageEvent(sender="111111111", text="", messages=[Json(data={"data": json.dumps(card)})])
        expect("card links via event", kb.douyin_links(ev7), (["https://v.douyin.com/Bvf9hl0ibGA/"], []))
    finally:
        dy.fetch = orig
    await b.terminate()


asyncio.run(plugin_tests())


# ------------------------------------------------------------------ 抓网页工具碰到视频链接（linkfetch.py）
async def linkfetch_tests():
    import types

    from kaju_basics import linkfetch

    class FakeFetch:
        async def call(self, context, **kwargs):
            return "PAGE TEXT " + kwargs.get("url", "")

    mod = types.SimpleNamespace(DeepSeekFetchWebPageTool=FakeFetch)
    ctx = types.SimpleNamespace(context=types.SimpleNamespace(event="EV"))
    seen = []

    async def handler(url, event):
        seen.append((url, event))
        return "WATCHED" if "douyin" in url else ""
    expect("linkfetch: installed", linkfetch.install(handler, print, mod), ["DeepSeekFetchWebPageTool"])
    linkfetch.install(handler, print, mod)  # 热重载：再装一次不会包两层
    tool = FakeFetch()
    expect("linkfetch: douyin → watched", await tool.call(ctx, url="https://v.douyin.com/Q8LF47lUeKo/"), "WATCHED")
    expect("linkfetch: other page → original fetch", await tool.call(ctx, url="https://example.com"), "PAGE TEXT https://example.com")
    expect("linkfetch: handler saw event, once per call", seen,
           [("https://v.douyin.com/Q8LF47lUeKo/", "EV"), ("https://example.com", "EV")])

    async def boom(url, event):
        raise RuntimeError("x")
    linkfetch.install(boom, lambda *_: None, mod)
    expect("linkfetch: handler error → original fetch", await tool.call(ctx, url="https://v.douyin.com/x/"), "PAGE TEXT https://v.douyin.com/x/")
    linkfetch.uninstall(mod)
    expect("linkfetch: uninstall restores", (await tool.call(ctx, url="u"), hasattr(FakeFetch, linkfetch.ORIG_ATTR)), ("PAGE TEXT u", False))

    ctx2 = Context()
    b = kb.KajuBasics(ctx2, {})
    calls = []

    async def douyin_video(url, event):
        calls.append(("dy", url))
        return ({"title": "温水佳树｜俯视版"}, "抖音图文《温水佳树｜俯视版》（作者：狗狗筷子，7张图）。看了前 4 张图：…") if "Q8L" in url else (None, "没打开：要验证")
    b._describer.douyin_video = douyin_video

    async def bili_video(url, event, danmaku=False, comments=False):
        calls.append(("bili", url))
        return {"title": "B站视频"}, "[Bilibili video: …]"
    b._describer.bili_video = bili_video
    ev = AstrMessageEvent(sender="111111111", text="再试一下")
    text = await b._link_fetch("https://v.douyin.com/Q8LF47lUeKo/", ev)
    expect("link_fetch: douyin watched", (text.startswith("（这个链接是用看视频的方式打开的"), "看了前 4 张图" in text), (True, True))
    expect("link_fetch: not watched → fall back", await b._link_fetch("https://v.douyin.com/zzzz/", ev), "")
    expect("link_fetch: bili", (await b._link_fetch("https://www.bilibili.com/video/BV1QGxE6TEYs", ev)).endswith("[Bilibili video: …]"), True)
    expect("link_fetch: plain page untouched", await b._link_fetch("https://example.com/a", ev), "")
    b.config["media"] = {"fetch_watch": False}
    expect("link_fetch: switch off", await b._link_fetch("https://v.douyin.com/Q8LF47lUeKo/", ev), "")
    expect("link_fetch: calls", calls, [("dy", "https://v.douyin.com/Q8LF47lUeKo/"), ("dy", "https://v.douyin.com/zzzz/"),
                                        ("bili", "https://www.bilibili.com/video/BV1QGxE6TEYs")])
    await b.terminate()


asyncio.run(linkfetch_tests())


# ------------------------------------------------------------------ --live：真开浏览器
async def live(url: str):
    import glob

    from kaju_core.senses import localstt, media

    out = tempfile.mkdtemp()
    got = await dy.fetch(dy.find_links(url)[0] if dy.find_links(url) else url, out)
    i = got["info"]
    print("=== 作品\n", {k: i[k] for k in ("id", "title", "author", "duration", "stat", "tags", "category", "music", "ai")})
    print("图文" if i["images"] else "视频", "；评论：", got["comments"][:4])
    print("下载：", got.get("video"), os.path.getsize(got["video"]) if got.get("video") else got.get("skip") or got.get("images"))
    if got.get("video"):
        chunks, secs = media.extract_wav_chunks(got["video"], out, chunk_seconds=300, max_seconds=600)
        vad = (glob.glob(r"D:\JiashuBot\models\**\silero_vad*.onnx", recursive=True) or [""])[0]
        sv = localstt.SenseVoice(r"D:\JiashuBot\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17", vad)
        for s, p in chunks:
            print(f"=== 听到的 [{s:.0f}s]\n", sv.transcribe(p))
    print("\n=== 给她看的（没接看图模型，只有页面部分）\n", dy.describe(i, "", got["comments"]))


if "--live" in sys.argv:
    rest = [a for a in sys.argv[1:] if a != "--live"]
    asyncio.run(live(" ".join(rest) if rest else SHARE))
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
