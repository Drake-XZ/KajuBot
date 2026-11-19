"""抖音链接：兄长转发来的抖音分享（"3.87 复制打开抖音，看看【…】… https://v.douyin.com/xxx/"）、抖音网页链接、QQ 分享卡片。

抖音的接口要签名，服务器给普通程序的分享页是空的。这里不模仿签名、也不伪装成别的东西，
而是像人一样开一个真浏览器（本机装的 Chrome，后台不显示窗口）打开视频页：
页面自己会去拿视频信息（标题、作者、点赞收藏转发、标签、背景音乐）和评论，这里只记下页面收到的；
再按页面给的地址下载最低画质的视频文件，交给跟 B 站视频一样的看视频流程（画面 + 整段声音 → 观后笔记）。
图文作品看前几张图。看完就关浏览器。弹出验证、打不开就老实说没看成，不去破解。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import urllib.parse

LINK = re.compile(
    r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?"
    r"|https?://(?:www\.|m\.)?(?:ies)?douyin\.com/(?:share/)?(?:video|note)/\d{15,20}[^\s，。！？一-鿿]*"
    r"|https?://(?:www\.)?douyin\.com/[^\s，。]*?modal_id=\d{15,20}"
)
ID = re.compile(r"(?:video|note)/(\d{15,20})|modal_id=(\d{15,20})")
PAGE_HOSTS = ("douyin.com", "iesdouyin.com")
MEDIA_HOSTS = ("zjcdn.com", "douyinvod.com", "douyin.com", "douyinpic.com", "bytecdn.cn", "byteimg.com",
               "amemv.com", "douyincdn.com", "bytedns.net", "ixigua.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
SEEN_PAGE = "（这个抖音视频本身佳树没看成，只看到了页面上的文字，问到内容别编。）"
SEEN_IMAGES = "（佳树看过这组图了。）"
_TAG = re.compile(r"[#＃][^\s#＃@]+|@[^\s#＃@]+")


class SkipDouyin(Exception):
    """抖音链接没看成，message 是给她看的原因。"""


# ------------------------------------------------------------------ 认链接
def find_links(text: str, limit: int = 2) -> list[str]:
    out, keys = [], set()
    for m in LINK.finditer(text or ""):
        url = m.group(0).rstrip(".,)）】")
        key = aweme_id(url) or url
        if key not in keys:
            keys.add(key)
            out.append(url)
        if len(out) >= limit:
            break
    return out


def card_links(data, limit: int = 2) -> list[str]:
    """QQ 分享卡片（Json）里的抖音链接。"""
    if isinstance(data, dict) and isinstance(data.get("data"), str):
        try:
            data = json.loads(data["data"])
        except json.JSONDecodeError:
            pass
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    return find_links(text.replace("\\/", "/"), limit)


def aweme_id(url: str) -> str:
    m = ID.search(url or "")
    return (m.group(1) or m.group(2)) if m else ""


def is_short(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") == "v.douyin.com"


def host_ok(url: str, hosts=PAGE_HOSTS) -> bool:
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


def page_url(aid: str, note: bool = False) -> str:
    return f"https://www.douyin.com/{'note' if note else 'video'}/{aid}"


# ------------------------------------------------------------------ 页面收到的数据
def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def title_of(desc: str, limit: int = 60) -> str:
    """文案去掉 #话题 和 @人，当标题用。"""
    t = _clean(_TAG.sub(" ", desc or "")).strip(" ，,。")
    return (t[:limit] + "…") if len(t) > limit else t


def parse_detail(data: dict) -> dict:
    """aweme/detail 的回复 → {id, title, desc, author, duration, stat, tags, category, music, images, video_urls, video_size, cover, ai}。"""
    a = (data or {}).get("aweme_detail") or {}
    if not a:
        return {}
    v = a.get("video") or {}
    rates = [b for b in v.get("bit_rate") or [] if ((b.get("play_addr") or {}).get("url_list"))]
    # 每档清晰度都有 mp4（画面 + 声音）和 dash（只有画面，声音另给）两份；挑最小的会挑中 dash，听不到声音
    # （2026-11-08 兄长分享的 MMD：下下来的 2.6MB 文件没有音轨）。有 mp4 就只在 mp4 里挑。
    muxed = [b for b in rates if str(b.get("format") or "mp4").lower() != "dash"]
    rates = sorted(muxed or rates, key=lambda b: b.get("bit_rate") or 10 ** 12)
    if rates:
        urls, size = list(rates[0]["play_addr"]["url_list"]), int(rates[0]["play_addr"].get("data_size") or 0)
    else:
        urls, size = list((v.get("play_addr") or {}).get("url_list") or []), 0
    images = [((im.get("url_list") or [""])[0]) for im in a.get("images") or [] if im.get("url_list")]
    tags = []
    for x in a.get("text_extra") or []:
        name = _clean(x.get("hashtag_name") or "")
        if name and name not in tags:
            tags.append(name)
    music = a.get("music") or {}
    author = _clean((a.get("author") or {}).get("nickname") or "")
    m_title, m_author = _clean(music.get("title") or ""), _clean(music.get("author") or "")
    own_sound = not m_title or "原声" in m_title or (m_author and m_author == author)
    st = a.get("statistics") or {}
    desc = _clean(a.get("desc") or a.get("caption") or "")
    return {
        "id": str(a.get("aweme_id") or ""), "desc": desc,
        "title": _clean(a.get("item_title") or "") or title_of(desc) or "（没有文案）",
        "author": author, "duration": float(a.get("duration") or v.get("duration") or 0) / 1000,
        "stat": {"like": int(st.get("digg_count") or 0), "comment": int(st.get("comment_count") or 0),
                 "collect": int(st.get("collect_count") or 0), "share": int(st.get("share_count") or 0)},
        "tags": tags, "category": "/".join(_clean(t.get("tag_name")) for t in a.get("video_tag") or [] if t.get("tag_name")),
        "music": "" if own_sound else f"{m_title}" + (f"（{m_author}）" if m_author else ""),
        "images": images, "video_urls": [] if images else urls, "video_size": size,
        "cover": v["cover"] if isinstance(v.get("cover"), str) else ((v.get("cover") or {}).get("url_list") or [""])[0],
        "ai": bool(a.get("is_aigc_media")), "created": int(a.get("create_time") or 0),
    }


DANCE_OR_MUSIC = re.compile(r"舞|跳|[Dd]ance|MMD|宅舞|翻跳|音乐|歌|唱|演奏|弹奏|钢琴|吉他|[Cc]over|MV|PV|BGM|卡点")


def is_music_video(info: dict) -> bool:
    """抖音作品 → 是不是音乐 / 舞蹈视频（分类、话题、文案里看得出来就算）。是的话看视频时顺便听一遍歌。
    2026-11-08：兄长分享的 MMD 舞蹈视频她只记了"转身、抬手"，没听歌、也没说出在跳舞。"""
    text = " ".join([str(info.get("category") or ""), str(info.get("desc") or ""), str(info.get("title") or "")]
                    + [str(t) for t in info.get("tags") or []])
    return bool(DANCE_OR_MUSIC.search(text))


_CAMEL = re.compile(r"(?<=[a-z0-9])([A-Z])")
_SSR_KEYS = {"author_info": "author", "stats": "statistics"}


def _snake(o):
    """页面自带数据是驼峰写法（awemeId、urlList），换成接口的写法（aweme_id、url_list）。"""
    if isinstance(o, list):
        return [_snake(x) for x in o]
    if not isinstance(o, dict):
        return None if o == "$undefined" else o
    out = {}
    for k, v in o.items():
        k = _CAMEL.sub(r"_\1", str(k)).lower()
        k = _SSR_KEYS.get(k, k)
        v = _snake(v)
        if k == "play_addr" and isinstance(v, list):  # 页面里是 [{src}]，接口里是 {url_list}
            v = {"url_list": [x.get("src") for x in v if isinstance(x, dict) and x.get("src")]}
        out[k] = v
    return out


def _find_detail(o, aid: str, depth: int = 0):
    if depth > 12:
        return None
    if isinstance(o, dict):
        d = (o.get("aweme") or {}).get("detail") if isinstance(o.get("aweme"), dict) else None
        if isinstance(d, dict) and str(d.get("awemeId") or "") == aid:
            return d
        items = o.values()
    elif isinstance(o, list):
        items = o
    else:
        return None
    for v in items:
        if isinstance(v, (dict, list)):
            hit = _find_detail(v, aid, depth + 1)
            if hit is not None:
                return hit
    return None


def ssr_detail(chunks: list[str], aid: str) -> dict:
    """图文作品的页面不去调 aweme/detail，作品信息直接写在页面里（self.__pace_f 的一段 "7:[…{awemeId, aweme:{detail}}]"）。
    读出来换成 aweme/detail 回复的样子（{"aweme_detail": …}），读不到给 {}。"""
    dec = json.JSONDecoder()
    for s in chunks or []:
        for line in str(s).split("\n"):
            head, sep, body = line.partition(":")
            if not sep or not body.lstrip().startswith(("[", "{")):
                continue
            try:
                obj, _ = dec.raw_decode(body.lstrip())
            except ValueError:
                continue
            d = _find_detail(obj, aid)
            if d:
                return {"aweme_detail": _snake(d)}
    return {}


async def _page_detail(page, aid: str) -> dict:
    try:
        chunks = await page.evaluate(
            """(aid) => (self.__pace_f || []).map(x => x && x[1])
                 .filter(s => typeof s === 'string' && s.includes('"awemeId":"' + aid + '"') && s.includes('"detail"'))""",
            aid)
    except Exception:  # noqa: BLE001
        return {}
    return ssr_detail(chunks, aid)


def _captcha(body: str, url: str) -> bool:
    """真的人机验证页。页面上的登录框也有"验证码登录"，那不算。"""
    return "verify" in (url or "") or any(w in body for w in ("安全验证", "滑块", "拖动", "请完成验证", "完成下列验证"))


def shrink(data: bytes, side: int = 1024) -> tuple[bytes, str]:
    """图太大（图文常见 1856×2464）本地看图模型的上下文装不下（2026-11-08：4098 > 4096 token）：
    长边缩到 side，存成 JPEG。缩不了（不是图、没装 PIL）就原样。返回 (数据, 扩展名)。"""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if max(img.size) <= side:
            return data, _img_ext(data)
        img.thumbnail((side, side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=88)
        return out.getvalue(), ".jpg"
    except Exception:  # noqa: BLE001
        return data, _img_ext(data)


def _img_ext(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ".jpg"


def parse_comments(data: dict, n: int = 6) -> list[tuple[str, int]]:
    """评论 → 点赞最多的 n 条（太短、只有表情的不要）。"""
    out = []
    for c in (data or {}).get("comments") or []:
        if c.get("is_folded"):
            continue
        text = _clean(re.sub(r"\[[^\]]{1,6}\]", "", c.get("text") or ""))
        if len(text) < 2:
            continue
        out.append((text[:80] + ("…" if len(text) > 80 else ""), int(c.get("digg_count") or 0)))
    out.sort(key=lambda x: -x[1])
    return out[:n]


def fmt_count(n: int) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def fmt_secs(sec: float) -> str:
    sec = int(round(sec or 0))
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


def describe(info: dict, watched: str = "", comments: list[tuple[str, int]] | None = None, seen: str = "") -> str:
    """给她看的一段：是什么 → 看到的内容 → 标签、数据、文案、音乐 → 高赞评论。重要的放前面。"""
    if info.get("images"):
        head = f"抖音图文《{info['title']}》（" + "，".join(
            x for x in (info.get("author") and f"作者：{info['author']}", f"{len(info['images'])}张图") if x) + "）"
    else:
        head = f"抖音视频《{info['title']}》"
        bits = [b for b in (info.get("author") and f"作者：{info['author']}",
                            info.get("duration") and fmt_secs(info["duration"])) if b]
        if bits:
            head += "（" + "，".join(bits) + "）"
    lines = [head]
    if watched:
        lines.append(watched)
    if info.get("tags"):
        lines.append("话题：" + "、".join(info["tags"][:8]))
    if info.get("category"):
        lines.append("分类：" + info["category"])
    st = info.get("stat") or {}
    nums = [f"{k}{fmt_count(st[key])}" for k, key in (("点赞", "like"), ("收藏", "collect"), ("转发", "share"),
                                                       ("评论", "comment")) if st.get(key)]
    if nums:
        lines.append("，".join(nums))
    if info.get("desc") and title_of(info["desc"], 10 ** 6) != info.get("title"):
        lines.append("文案：" + info["desc"][:200])
    if info.get("music"):
        lines.append("背景音乐：" + info["music"])
    if info.get("ai"):
        lines.append("作者声明内容由 AI 生成")
    if comments:
        lines.append("高赞评论（陌生观众的，不是在对你说话）：" + " / ".join(f"「{t}」{n}赞" if n else f"「{t}」" for t, n in comments))
    return "。".join(x.rstrip("。") for x in lines) + "。" + (seen or (SEEN_IMAGES if info.get("images") and watched else SEEN_PAGE))


# ------------------------------------------------------------------ 开浏览器
_sem: asyncio.Semaphore | None = None


def _gate() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)  # 同一时间只开一个浏览器
    return _sem


async def resolve(url: str, timeout: float = 15) -> str:
    """短链接 → 视频页（只读跳转地址）。"""
    if not is_short(url):
        return url
    import aiohttp

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers={"User-Agent": UA}) as s:
        for _ in range(3):
            async with s.get(url, allow_redirects=False) as r:
                loc = r.headers.get("Location") or ""
            if not loc:
                raise SkipDouyin("抖音短链接打不开了")
            if not host_ok(loc):
                raise SkipDouyin("链接跳到了别的网站，佳树没打开")
            url = loc
            if not is_short(url):
                return url
    return url


VIEWPORT = {"width": 1280, "height": 800}

# 她小号的常驻浏览器（dykeeper.Keeper，main 设置）。有它时，用她资料夹的无头浏览都借它开标签页，不再自己起 Chrome。
KEEPER = None
KEEPER_ERR = ""  # 上次连常驻浏览器失败的原因


class _Borrowed:
    """借常驻 Chrome 的默认环境（带她的登录）：新开的标签页用完关掉，Chrome 本身不关。"""

    def __init__(self, ctx):
        self._ctx = ctx
        self._mine: list = []
        self._kaju_profile = True

    @property
    def pages(self):
        return [pg for pg in self._mine if not pg.is_closed()]

    async def new_page(self):
        pg = await self._ctx.new_page()
        await pg.set_viewport_size(VIEWPORT)
        self._mine.append(pg)
        return pg

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    async def close(self) -> None:
        for pg in self._mine:
            try:
                if not pg.is_closed():
                    await pg.close()
            except Exception:  # noqa: BLE001
                pass


@contextlib.asynccontextmanager
async def _context(p, channel: str = "chrome", profile: str = "", headless: bool = True):
    """开一个浏览器页面环境。profile：她小号登录过的 Chrome 资料夹（登录着就用它，评论能看全、推荐是她自己的）；
    没给、或者资料夹被占着打不开，就开一个不登录的。
    有常驻浏览器（KEEPER，管着同一个资料夹）时：连上它、开新标签页，用完只关标签页。"""
    keeper = KEEPER
    if profile and headless and keeper is not None and os.path.normcase(keeper.profile) == os.path.normcase(profile):
        browser = None
        try:
            browser = await p.chromium.connect_over_cdp(await keeper.ensure(True))
        except Exception as e:  # noqa: BLE001 — 连不上就开不登录的（KEEPER_ERR 给 main 记日志）
            global KEEPER_ERR
            KEEPER_ERR = f"{type(e).__name__}: {e}"
            browser = None
        if browser is not None:
            ctx = _Borrowed(browser.contexts[0] if browser.contexts else await browser.new_context())
            try:
                yield ctx
            finally:
                await ctx.close()
                try:
                    await browser.close()  # 只断开连接
                except Exception:  # noqa: BLE001
                    pass
            return
        profile = ""
    if profile:
        ctx = None
        try:
            ctx = await p.chromium.launch_persistent_context(
                profile, channel=channel, headless=headless, locale="zh-CN", viewport=VIEWPORT)
        except Exception as e:  # noqa: BLE001
            if not headless:
                raise SkipDouyin(f"登录用的浏览器没打开（{type(e).__name__}）") from e
        if ctx is not None:
            ctx._kaju_profile = True  # 开的是她的资料夹（ctx.browser 在新版 Playwright 里也不是 None，不能拿来判断）
            try:
                yield ctx
            finally:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass
            return
    try:
        browser = await p.chromium.launch(channel=channel, headless=headless)
    except Exception:  # noqa: BLE001
        browser = await p.chromium.launch(channel="msedge", headless=headless)
    try:
        yield await browser.new_context(locale="zh-CN", viewport=VIEWPORT)
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass


def _playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise SkipDouyin("看抖音用的浏览器组件没装") from e
    return async_playwright()


async def fetch(url: str, out_dir: str, *, channel: str = "chrome", timeout: float = 30, max_mb: float = 60,
                max_seconds: float = 1200, max_images: int = 4, want_comments: bool = True, profile: str = "",
                image_side: int = 1024) -> dict:
    """打开视频页 → {info, comments, video, images}（video / images 是下载到 out_dir 的文件）。看不成抛 SkipDouyin。
    profile：小号登录过的资料夹（有就用登录着的浏览器打开）。"""
    url = await resolve(url)
    aid = aweme_id(url)
    if not aid:
        raise SkipDouyin("这个抖音链接不是视频或图文")
    note = "/note/" in url
    pw = _playwright()
    got: dict = {}
    detail_seen = asyncio.Event()

    async def on_response(r):
        u = r.url
        try:
            if "/aweme/v1/web/aweme/detail" in u and "detail" not in got:
                data = await r.json()
                if ((data or {}).get("aweme_detail") or {}).get("aweme_id") == aid:
                    got["detail"] = data
                    detail_seen.set()
            elif want_comments and "/aweme/v1/web/comment/list" in u and "comments" not in got and f"aweme_id={aid}" in u:
                got["comments"] = await r.json()
        except Exception:  # noqa: BLE001
            pass

    async with _gate():
        async with pw as p:
            async with _context(p, channel, profile) as ctx:
                page = await ctx.new_page()
                page.on("response", on_response)
                await page.goto(page_url(aid, note), wait_until="domcontentloaded", timeout=timeout * 1000)
                # 视频页会去调 aweme/detail；图文页不调，作品信息写在页面里。两边都看，谁先有用谁。
                loop = asyncio.get_running_loop()
                end = loop.time() + timeout
                while not detail_seen.is_set() and loop.time() < end:
                    try:
                        await asyncio.wait_for(detail_seen.wait(), 2)
                    except asyncio.TimeoutError:
                        ssr = await _page_detail(page, aid)
                        if ssr:
                            got.setdefault("detail", ssr)
                            break
                if "detail" not in got:
                    body = ""
                    try:
                        body = await page.inner_text("body", timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    if _captcha(body[:3000], page.url):
                        raise SkipDouyin("抖音要人机验证，佳树没看成")
                    raise SkipDouyin("抖音页面没给出视频信息（可能删了、要登录才能看，或者被拦了）")
                if want_comments and "comments" not in got:
                    for _ in range(16):  # 评论是页面接着去拿的（一般两三秒），最多再等 8 秒
                        await asyncio.sleep(0.5)
                        if "comments" in got:
                            break
                info = parse_detail(got["detail"])
                out = {"info": info, "comments": parse_comments(got.get("comments") or {}), "video": "", "images": []}
                req = ctx.request
                headers = {"Referer": "https://www.douyin.com/"}
                if info["images"]:
                    for i, src in enumerate(info["images"][:max_images]):
                        if not host_ok(src, MEDIA_HOSTS):
                            continue
                        r = await req.get(src, headers=headers, timeout=timeout * 1000)
                        if r.ok:
                            data, ext = shrink(await r.body(), image_side) if image_side else (await r.body(), "")
                            path = os.path.join(out_dir, f"douyin_{aid}_{i + 1}{ext or _img_ext(data)}")
                            with open(path, "wb") as f:
                                f.write(data)
                            out["images"].append(path)
                elif info["duration"] and info["duration"] > max_seconds:
                    out["skip"] = f"视频太长（{fmt_secs(info['duration'])}），佳树没下载来看"
                elif info["video_size"] and info["video_size"] > max_mb * 1024 * 1024:
                    out["skip"] = f"视频太大（{info['video_size'] / 1024 / 1024:.0f}MB），佳树没下载来看"
                else:
                    path = os.path.join(out_dir, f"douyin_{aid}.mp4")
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        os.utime(path)
                        out["video"] = path
                    for src in info["video_urls"]:
                        if out["video"]:
                            break
                        if not host_ok(src, MEDIA_HOSTS):
                            continue
                        try:
                            r = await req.get(src, headers=headers, timeout=max(60, timeout * 4) * 1000)
                        except Exception:  # noqa: BLE001
                            continue
                        if not r.ok:
                            continue
                        data = await r.body()
                        if not data or len(data) > max_mb * 1024 * 1024:
                            continue
                        with open(path + ".part", "wb") as f:
                            f.write(data)
                        os.replace(path + ".part", path)
                        out["video"] = path
                    if not out["video"]:
                        out["skip"] = "视频文件没下载下来"
                return out


# ------------------------------------------------------------------ 她自己的抖音小号（扫码登录到一个 Chrome 资料夹）
HOME = "https://www.douyin.com/jingxuan"
SESSION_COOKIES = ("sessionid", "sessionid_ss")
# 2026-11-08 实测：二维码是 #douyin_login_comp_scan_code_qrcode 里的一张 data:image/png（class 是乱码，id 里才有 qrcode）
QR_SELECTOR = ('#douyin_login_comp_scan_code_qrcode img, #animate_qrcode_container img, [id*="qrcode"] img, '
               '[class*="qrcode"] img, [class*="qr-code"] img, img[alt*="二维码"], [id*="qrcode"] canvas, [class*="qrcode"] canvas')
_QR_JS = """() => {
  const QR_SELECTOR = %s;""" % json.dumps(QR_SELECTOR) + """
  const nodes = [...document.querySelectorAll(QR_SELECTOR)];
  const hit = nodes.find(e => { const r = e.getBoundingClientRect();
    return e.offsetParent !== null && r.width >= 80 && r.height >= 80 && r.width < 600 && r.height < 600; });
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return {x: Math.max(0, r.x - 8), y: Math.max(0, r.y - 8), width: r.width + 16, height: r.height + 16};
}"""
_QR_BOX = "#douyin_login_comp_scan_code_container"
_QR_STATE_JS = """() => {
  const box = document.querySelector('#douyin_login_comp_scan_code_container');
  const img = document.querySelector('#douyin_login_comp_scan_code_qrcode img');
  const t = box ? box.innerText : '';
  return {src: img ? img.src.slice(-80) : '', expired: /失效|过期|点击刷新/.test(t)};
}"""


async def _open_login(page) -> bool:
    """点右上角「登录」（真的鼠标点那个看得见的按钮；JS 点有时点到看不见的同名元素，登录框不出来）。"""
    for loc in (page.get_by_role("button", name="登录", exact=True), page.get_by_text("登录", exact=True)):
        try:
            n = await loc.count()
            for i in range(min(n, 6)):
                el = loc.nth(i)
                if await el.is_visible():
                    await el.click(timeout=3000)
                    return True
        except Exception:  # noqa: BLE001
            continue
    try:
        return bool(await page.evaluate(_LOGIN_BUTTON_JS))
    except Exception:  # noqa: BLE001
        return False


async def _qr_src(page) -> str:
    try:
        return (await page.evaluate(_QR_STATE_JS)).get("src") or ""
    except Exception:  # noqa: BLE001
        return ""


_LOGIN_BUTTON_JS = """() => {
  const hit = [...document.querySelectorAll('div,span,button,a,p')]
    .find(e => (e.innerText || '').trim() === '登录' && e.offsetParent !== null);
  if (hit) { hit.click(); return true; }
  return false;
}"""


async def session_id(ctx) -> str:
    """浏览器里抖音 sessionid 的值（没有就 ''）。"""
    try:
        cookies = await ctx.cookies("https://www.douyin.com")
    except Exception:  # noqa: BLE001
        return ""
    return next((str(c.get("value") or "") for c in cookies if c.get("name") in SESSION_COOKIES and c.get("value")), "")


async def whoami(ctx) -> dict:
    """问抖音"我是谁"（不签名的只读接口 user/profile/self，带浏览器自己的 Cookie）→ {state: ok/out/unknown, nickname}。
    只看 sessionid 在不在不够：2026-11-08 登录早被注销了，失效的 sessionid 还留在资料夹里（到期前一直在）。"""
    from .dykeeper import SELF_API, parse_self

    try:
        r = await ctx.request.get(SELF_API, headers={"Referer": "https://www.douyin.com/"}, timeout=15000)
        d = await r.json()
    except Exception:  # noqa: BLE001
        d = {}
    return parse_self(d)


async def has_session(ctx) -> bool:
    """登录着没有：看浏览器里有没有抖音的 sessionid（HttpOnly，页面自己读不到，只能从浏览器这层看）。"""
    try:
        cookies = await ctx.cookies("https://www.douyin.com")
    except Exception:  # noqa: BLE001
        return False
    return any(c.get("name") in SESSION_COOKIES and c.get("value") for c in cookies)


async def _nickname(ctx, timeout: float = 6) -> str:
    """登录的是谁：打开"我的"页面，记下页面自己拿到的 user/profile/self。"""
    got: dict = {}
    seen = asyncio.Event()

    async def on_response(r):
        if "/aweme/v1/web/user/profile/self" in r.url and not seen.is_set():
            try:
                got["user"] = ((await r.json()) or {}).get("user") or {}
            except Exception:  # noqa: BLE001
                got["user"] = {}
            seen.set()

    page = await ctx.new_page()
    try:
        page.on("response", on_response)
        await page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded", timeout=timeout * 1000)
        await asyncio.wait_for(seen.wait(), timeout)
    except Exception:  # noqa: BLE001
        pass
    finally:
        await page.close()
    return _clean((got.get("user") or {}).get("nickname") or "")


async def check_login(profile: str, *, channel: str = "chrome") -> dict:
    """{logged_in, nickname}。资料夹没有就是没登录过。"""
    if not profile or not os.path.isdir(profile):
        return {"logged_in": False, "nickname": ""}
    keeper = KEEPER
    if keeper is not None and os.path.normcase(keeper.profile) == os.path.normcase(profile):
        async with _gate():
            async with _playwright() as p:
                me = await keeper.whoami(p)
        if me["state"] != "unknown":
            return {"logged_in": me["state"] == "ok", "nickname": me["nickname"], "state": me["state"]}
    async with _gate():
        async with _playwright() as p:
            async with _context(p, channel, profile) as ctx:
                if not await has_session(ctx):
                    return {"logged_in": False, "nickname": ""}
                return {"logged_in": True, "nickname": await _nickname(ctx)}


async def qr_login(profile: str, qr_png: str, say, *, channel: str = "chrome", timeout: float = 300) -> dict:
    """扫码登录：在这台电脑上开一个看得见的 Chrome（她自己的资料夹），点「登录」，把二维码截下来交给 say("qr", 图)；
    兄长用小号的抖音 App 扫。扫完要是还要短信 / 滑块 / 新设备确认，在那个窗口里由兄长自己做完（这边不碰）。
    say(kind, data)：kind = qr / scanned / already。返回 {logged_in, nickname, why}。"""
    os.makedirs(profile, exist_ok=True)
    keeper = KEEPER if KEEPER is not None and os.path.normcase(KEEPER.profile) == os.path.normcase(profile) else None
    async with _gate():
        async with _playwright() as p:
            async with (_visible(p, keeper) if keeper else _context(p, channel, profile, headless=False)) as ctx:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto(HOME, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                old_sid = await session_id(ctx)
                if old_sid and (await whoami(ctx))["state"] == "ok":  # 真登录着（不只是留着一个失效的 sessionid）
                    name = await _nickname(ctx)
                    await say("already", name)
                    return {"logged_in": True, "nickname": name, "why": "已经登录着"}
                box = None
                for i in range(25):  # 登录框是慢慢渲染出来的
                    if i in (0, 8, 16) and not await page.query_selector(_QR_BOX):
                        await _open_login(page)
                    await asyncio.sleep(1)
                    try:
                        box = await page.evaluate(_QR_JS)
                    except Exception:  # noqa: BLE001
                        box = None
                    if box:
                        break
                if not box:
                    return {"logged_in": False, "nickname": "", "why": "登录框里没找到二维码（电脑上那个窗口还开着的话可以直接在里面登录）"}
                await asyncio.sleep(1)  # 二维码图片画完
                await page.screenshot(path=qr_png, clip=await page.evaluate(_QR_JS) or box)
                await say("qr", qr_png)
                sent = await _qr_src(page)
                loop = asyncio.get_running_loop()
                end, scanned, gone_since, resent = loop.time() + timeout, False, 0.0, 0
                while loop.time() < end:
                    await asyncio.sleep(2)
                    sid = await session_id(ctx)
                    if sid and sid != old_sid:  # 换成了新的 sessionid：扫码登录成了
                        await asyncio.sleep(3)
                        me = await whoami(ctx)
                        return {"logged_in": True, "nickname": me["nickname"] or await _nickname(ctx), "why": "",
                                "check": me["state"]}
                    if scanned:
                        continue
                    try:
                        state = await page.evaluate(_QR_STATE_JS)
                    except Exception:  # noqa: BLE001
                        continue
                    if state.get("expired"):  # 过期了：像人一样点一下刷新
                        try:
                            await page.click(_QR_BOX, timeout=3000)
                        except Exception:  # noqa: BLE001
                            pass
                        continue
                    src = state.get("src") or ""
                    if src and src != sent and resent < 6:  # 页面自己换了新二维码：把新的再发一次
                        await asyncio.sleep(1)
                        clip = await page.evaluate(_QR_JS)
                        if clip:
                            await page.screenshot(path=qr_png, clip=clip)
                            sent, resent, gone_since = src, resent + 1, 0.0
                            await say("qr", qr_png)
                        continue
                    if src:
                        gone_since = 0.0
                    elif not gone_since:
                        gone_since = loop.time()
                    elif loop.time() - gone_since >= 6:  # 二维码不见了好一会儿（不是在换新的）：扫到了
                        scanned = True
                        await say("scanned", "")
                        end = max(end, loop.time() + 180)  # 给手机确认 / 电脑上的验证留时间
                return {"logged_in": False, "nickname": "",
                        "why": "等太久了，没登录上" + ("（扫到了，但没等到确认 / 验证做完）" if scanned else "（二维码没扫）")}


@contextlib.asynccontextmanager
async def _visible(p, keeper):
    """扫码用：常驻的无头 Chrome 先关掉，同一个资料夹起一个看得见的普通 Chrome（没有自动化标记），连上去操作。
    结束时关掉它；登录着就再起无头的常驻。"""
    await keeper.stop()
    try:
        browser = await p.chromium.connect_over_cdp(await keeper.ensure(False, HOME))
    except Exception as e:  # noqa: BLE001
        raise SkipDouyin(f"登录用的浏览器没打开（{type(e).__name__}: {e}）") from e
    ctx = browser.contexts[0]
    try:
        yield ctx
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass
        await keeper.stop()


def logout(profile: str) -> bool:
    """只删这台电脑上的资料夹（登录状态），账号本身不动。"""
    import shutil

    if profile and os.path.isdir(profile):
        shutil.rmtree(profile, ignore_errors=True)
        return True
    return False


# ------------------------------------------------------------------ 自己刷抖音：打开精选 / 搜索页，记下页面自己拿到的列表
SRC_LOGGED, SRC_NOT_LOGGED, SRC_PROFILE_BUSY, SRC_ANON = "（小号）", "（小号没登录着）", "（小号的浏览器被占着，没登录）", "（没登录）"


def search_url(kw: str) -> str:
    return "https://www.douyin.com/search/" + urllib.parse.quote(kw) + "?type=video"


def feed_items(data: dict) -> list[dict]:
    """精选（module/feed、tab/feed）或搜索（search/item、general/search）的回复 → 作品原始数据列表。"""
    out = []
    for it in (data or {}).get("aweme_list") or (data or {}).get("data") or []:
        if not isinstance(it, dict):
            continue
        a = it.get("aweme_info") or it.get("aweme") or it
        if isinstance(a, dict) and a.get("aweme_id"):
            out.append(a)
    return out


def candidate(a: dict) -> dict | None:
    """一条作品 → 刷视频用的候选 {bvid: "dy<id>", aid, title, up, duration, reason, views, likes, tname, url, site}。
    广告、直播、私密的不要。"""
    if a.get("is_ads") or a.get("raw_ad_data") or a.get("cell_room") or (a.get("status") or {}).get("is_private"):
        return None
    info = parse_detail({"aweme_detail": a})
    if not info.get("id") or not (info["images"] or info["video_urls"] or info["duration"]):
        return None
    return {"bvid": "dy" + info["id"], "aid": info["id"], "title": info["title"][:80], "up": info["author"][:30],
            "duration": int(info["duration"] or 0), "reason": "图文" if info["images"] else "",
            "views": 0, "likes": int((info.get("stat") or {}).get("like") or 0),
            "tname": (info.get("category") or "").split("/")[-1][:12], "url": page_url(info["id"], bool(info["images"])),
            "site": "douyin"}


async def browse_list(profile: str, topic: str = "", *, channel: str = "chrome", timeout: float = 25,
                      want: int = 15) -> tuple[list[dict], str, str]:
    """(作品候选, 从哪儿刷的, 没搜成的原因)。说了想看什么先开搜索页；然后开精选，不够就像人一样往下滚两下。
    弹验证就不搜了（不去破解），老实回精选。"""
    found: dict[str, dict] = {}
    hits = {"search": 0, "feed": 0}
    arrived = asyncio.Event()

    async def on_response(r):
        u = r.url
        kind = ("search" if ("/aweme/v1/web/search/item" in u or "/aweme/v1/web/general/search" in u)
                else "feed" if ("/aweme/v2/web/module/feed" in u or "/aweme/v1/web/tab/feed" in u) else "")
        if not kind:
            return
        try:
            data = await r.json()
        except Exception:  # noqa: BLE001
            return
        for a in feed_items(data):
            c = candidate(a)
            if c and c["bvid"] not in found:
                found[c["bvid"]] = {**c, "from": kind}
                hits[kind] += 1
        arrived.set()

    async def wait_list(page, until: float) -> None:
        loop = asyncio.get_running_loop()
        while loop.time() < until:
            arrived.clear()
            try:
                await asyncio.wait_for(arrived.wait(), max(0.5, until - loop.time()))
                await asyncio.sleep(1.5)  # 一页可能分几次到
                return
            except asyncio.TimeoutError:
                return

    why = ""
    async with _gate():
        async with _playwright() as p:
            async with _context(p, channel, profile) as ctx:
                page = await ctx.new_page()
                page.on("response", on_response)
                loop = asyncio.get_running_loop()
                if topic:
                    await page.goto(search_url(topic), wait_until="domcontentloaded", timeout=timeout * 1000)
                    await wait_list(page, loop.time() + timeout)
                    if not hits["search"]:
                        body = ""
                        try:
                            body = await page.inner_text("body", timeout=3000)
                        except Exception:  # noqa: BLE001
                            pass
                        verifying = _captcha(body[:3000], page.url) or not body.strip()
                        why = "抖音搜索要人机验证，没搜成" if verifying else "抖音搜索没搜出东西"
                    else:
                        cands = [c for c in found.values() if c["from"] == "search"]
                        return cands, f"抖音搜「{topic}」", ""
                await page.goto(HOME, wait_until="domcontentloaded", timeout=timeout * 1000)
                await wait_list(page, loop.time() + timeout)
                for _ in range(2):
                    if len(found) >= want:
                        break
                    await asyncio.sleep(2 + 2 * (len(found) % 2))  # 像人一样看一会儿再往下滚
                    await page.mouse.move(640, 500)
                    await page.mouse.wheel(0, 1600)
                    await wait_list(page, loop.time() + 10)
                own = bool(profile) and getattr(ctx, "_kaju_profile", False)  # 资料夹打不开时会退回不登录的浏览器
                state = (SRC_LOGGED if await has_session(ctx) else SRC_NOT_LOGGED) if own else (
                    SRC_PROFILE_BUSY if profile else SRC_ANON)
    cands = [c for c in found.values() if c["from"] == "feed"]
    return cands, "抖音精选" + state, why

