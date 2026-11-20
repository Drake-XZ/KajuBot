"""B 站链接：打开视频页、读字幕弹幕评论、下载最低画质给她看（原来在 kaju_basics 的 describe.py 里）。

BiliLinks 是 mixin，宿主（kaju_basics 的 Describer）要有：_cfg()、_cached()、_bili 表、login_cookie()、
watch_file(path, event, …)、caption(path, prompt, who)、_fit_local_video_text()、senses、log。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid

from kaju_core.senses import docs, media, music
from kaju_core.senses.perceive import DIGEST_RULES, VIDEO_DIGEST_SYSTEM, SkipVideo
from kaju_core.senses.perceive import temp_dir as _temp_dir
from kaju_core.senses.perceive import unlink as _unlink

from . import bili

LOG = None  # _try_urls 是静态方法，用这个记日志（宿主装上自己的 log）


async def _empty() -> str:
    return ""


async def _empty_dict() -> dict:
    return {}

COVER_PROMPT = (
    "这是B站视频《{title}》的封面。用中文描述封面：画面上是谁或什么、表情动作和气氛，封面上的大字原样写出来。"
    "60 字以内，不要用 markdown，不要说\"这张封面\"。"
)


BILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/130.0.0.0 Safari/537.36")


BILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "hdslb.com")


BILI_MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0.0.0 Mobile Safari/537.36")


VIDEO_HOSTS = ("bilivideo.com", "bilivideo.cn", "akamaized.net")  # B 站视频文件所在的服务器


BILI_API = "https://api.bilibili.com"


SUB_MISMATCH = "字幕对不上"


VIDEO_DIGEST_PROMPT = """下面是 B 站视频《{title}》（{meta}）的字幕：UP主上传的或自动识别的旁白、台词（自动识别的可能有错字、同音字）。
""" + DIGEST_RULES + """
如果字幕内容跟标题明显对不上（像是别的视频的字幕），只输出四个字：""" + SUB_MISMATCH + """

字幕：
{text}"""


TRANSLATED_NOTE = ("\n\n注意：这份字幕是 B 站把视频的中文旁白自动翻译成{lang}的版本。观后笔记一律用中文写，"
                   "摘的原话也翻回自然的中文；人名、作品名用中文里通行的写法（比如日文的 温水佳樹 写成 温水佳树）。")


class SkipBili(Exception):
    """B 站链接没打开（不是视频、页面打不开），message 是给她看的原因。"""


class _Incomplete(Exception):
    """分段下载有一段没下完整（服务器中途断了）：换一台服务器再下。"""


class _NoRange(Exception):
    """视频服务器不支持分段下载。"""


class BiliLinks:
    """B 站那部分（宿主见模块说明）。"""

    def cookie(self) -> str:
        """向 B 站要字幕用的 Cookie：扫码登录的小号优先，其次是配置里手填的 media.bili_cookie。"""
        return self.login_cookie() or bili.cookie_header(self._cfg().get("bili_cookie", ""))

    async def bili_info(self, url: str) -> dict:
        """链接 → 视频页上的信息（bili.parse_page 的结果 + url），打不开抛 SkipBili。同一个链接半小时内只打开一次。"""
        return await asyncio.shield(self._cached(self._bili, url, lambda: self._bili_page(url)))

    async def bili_brief(self, url: str) -> str:
        """群聊记录用的一句话（不看封面、不读弹幕）；打不开返回空字符串。"""
        try:
            return bili.brief(await self.bili_info(url))
        except SkipBili:
            return ""
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_basics: B站链接没打开 {type(e).__name__}: {e}")
            return ""

    async def bili_video(self, url: str, event, danmaku: bool = False, comments: bool = False) -> tuple[dict | None, str]:
        """(页面信息, 给她看的整段介绍)。打不开时信息是 None，介绍以"没打开："开头。
        danmaku=True（对方让她看弹幕）时最后附几条弹幕。评论区总附几条高赞的（像抖音那样）；
        comments=True（对方让她看评论）时多看几条，热门楼里的回复也翻开看。"""
        try:
            info = await self.bili_info(url)
        except SkipBili as e:
            return None, f"没打开：{e}"
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: B站链接没打开 {type(e).__name__}: {e}")
            return None, "没打开：链接没能打开，佳树没看到是什么视频"
        fut = self._cached(self._bili, "full|" + info["url"], lambda: self._bili_full(info, event))
        try:
            parts = await asyncio.shield(fut)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: B站视频介绍没写成 {type(e).__name__}: {e}")
            parts = {}
        dm, hot = (await self.bili_danmaku(info)) if danmaku else ([], [])
        text = bili.describe(info, parts.get("cover", ""), dm, hot, watched=parts.get("watched", ""), seen=parts.get("seen"))
        cm = bili.comments_text(await self.bili_comments(info, full=comments))
        return info, (text + cm if cm else text)

    async def bili_comments(self, info: dict, full: bool = False) -> list[dict]:
        """评论区：高赞的几条一楼（full=True 时多几条，热门楼里的回复也翻开）。读不到返回 []。同一个视频半小时内只读一次。"""
        n = int(self._cfg().get("bili_comments", 4))
        if not info.get("aid") or n <= 0:
            return []
        key = ("cmf|" if full else "cm|") + info["url"]
        try:
            return await asyncio.shield(self._cached(self._bili, key, lambda: self._bili_cm(info, full)))
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_basics: B站评论没读成 {type(e).__name__}: {e}")
            return []

    async def _bili_cm(self, info: dict, full: bool) -> list[dict]:
        import aiohttp

        cfg = self._cfg()
        n = int(cfg.get("bili_comments_full", 10)) if full else int(cfg.get("bili_comments", 4))
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("bili_timeout", 15)))
        cookie = self.cookie()
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_UA}) as s:
            data = await self._bili_api(s, "/x/v2/reply", cookie, type=1, oid=info["aid"], sort=1, ps=20, pn=1)
            cms = bili.parse_replies(data.get("data") or {}, n, sub_n=3 if full else 1)
            if full:  # 回复多的几楼翻开看：楼里大家怎么接话
                for c in [c for c in cms if c["rcount"] > len(c["sub"])][:3]:
                    try:
                        d2 = await self._bili_api(s, "/x/v2/reply/reply", cookie, type=1, oid=info["aid"], root=c["rpid"],
                                                  ps=10, pn=1)
                        c["sub"] = bili.parse_sub((d2.get("data") or {}).get("replies") or [], 6) or c["sub"]
                    except Exception as e:  # noqa: BLE001
                        self.log.info(f"kaju_basics: 楼中楼没读成 {type(e).__name__}: {e}")
                    await asyncio.sleep(0.5)
        self.log.info(f"kaju_basics: 读了《{info['title']}》的评论区（{len(cms)} 条{'，翻开了楼里' if full else ''}）")
        return cms

    async def bili_danmaku(self, info: dict) -> tuple[list, list]:
        """(按时间挑的弹幕, 刷得最多的几句)，读不到返回两个空列表。同一个视频半小时内只读一次。"""
        if not info.get("cid") or int(self._cfg().get("bili_danmaku", 12)) <= 0:
            return [], []
        try:
            return await asyncio.shield(self._cached(self._bili, "dm|" + info["url"], lambda: self._bili_dm(info)))
        except Exception as e:  # noqa: BLE001
            self.log.info(f"kaju_basics: B站弹幕没读成 {type(e).__name__}: {e}")
            return [], []

    async def _bili_dm(self, info: dict) -> tuple[list, list]:
        import aiohttp

        cfg = self._cfg()
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("bili_timeout", 15)))
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_UA}) as s:
            dm = await self._bili_danmaku(s, info["cid"])
        hot = bili.popular(dm)
        picked = bili.pick_danmaku(dm, int(cfg.get("bili_danmaku", 12)), info.get("duration") or 0, {t for t, _ in hot})
        self.log.info(f"kaju_basics: 读了《{info['title']}》的弹幕（{len(dm)} 条挑 {len(picked)}）")
        return picked, hot

    async def _get(self, session, url: str, hosts=BILI_HOSTS, **kw):
        host = (url.split("/")[2] if "://" in url else "").split(":")[0].lower()
        if not any(host == h or host.endswith("." + h) for h in hosts):
            raise SkipBili("链接跳到了别的网站，佳树没打开")
        return await session.get(url, **kw)

    async def _bili_page(self, url: str) -> dict:
        import aiohttp

        cfg = self._cfg()
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("bili_timeout", 15)))
        t0 = time.time()
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_UA}) as s:
            for _ in range(3):  # 短链跳到真正的视频页（只读跳转地址，不打开带分享参数的那一页）
                if not bili.is_short(url):
                    break
                async with await self._get(s, url, allow_redirects=False) as r:
                    loc = r.headers.get("Location") or ""
                if not loc:
                    raise SkipBili("短链接打不开了，佳树没看到是什么视频")
                url = loc if "://" in loc else "https:" + loc if loc.startswith("//") else url
            key = bili.video_key(url)
            page_url = bili.page_url(key) if key else url.split("?")[0]  # 去掉分享时带的追踪参数
            async with await self._get(s, page_url) as r:
                if r.status != 200:
                    raise SkipBili(f"视频页打不开（{r.status}），佳树没看到是什么视频")
                page = await r.text(errors="replace")
        part = int(key.partition("#")[2] or 1) if key else 1
        info = bili.parse_page(page, part) if key else bili.parse_generic(page)
        if not info.get("title"):
            raise SkipBili("页面上没读到是什么视频（可能删了或者要登录才能看）")
        info["url"] = page_url
        info["kind"] = "video" if key else "page"
        self.log.info(f"kaju_basics: 打开B站链接《{info['title']}》（{time.time() - t0:.1f}s）")
        return info

    async def _bili_full(self, info: dict, event) -> dict:
        """{watched, seen, cover}：先下载最低画质看完（画面 + 声音）；下不了再试字幕；都不行就只有页面和封面。"""
        import aiohttp

        cfg = self._cfg()
        umo = event.unified_msg_origin
        t0 = time.time()
        if self._can_download(info):
            try:
                path = await self._bili_download(info)
                watched = await self.watch_file(path, event, title=info["title"],
                                           listen_music=music.is_music_video(info))
                self.log.info(f"kaju_basics: 看完了B站视频《{info['title']}》（{time.time() - t0:.1f}s）")
                return {"watched": watched, "seen": bili.SEEN_VIDEO, "cover": ""}
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_basics: B站视频没下载/没看成，退回字幕和页面 {type(e).__name__}: {e}")
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("bili_timeout", 15)))
        cookie = self.cookie()
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_UA}) as s:
            cover, sub = await asyncio.gather(
                self._bili_cover(s, info, umo) if cfg.get("bili_cover", True) and info.get("cover") else _empty(),
                self._bili_subtitle(s, info, cookie) if cookie and info.get("kind") == "video" and info.get("cid")
                else _empty_dict(),
                return_exceptions=True,
            )
        if isinstance(cover, BaseException):
            self.log.info(f"kaju_basics: B站封面没看成 {type(cover).__name__}: {cover}")
            cover = ""
        if isinstance(sub, BaseException):
            self.log.warning(f"kaju_basics: B站字幕没拿到 {type(sub).__name__}: {sub}")
            sub = {}
        subs = sub.get("lines") or [] if isinstance(sub, dict) else []
        watched = await self._bili_watched(info, sub, umo) if subs and isinstance(sub, dict) else ""
        self.log.info(f"kaju_basics: 看了B站视频页《{info['title']}》（封面{'✓' if cover else '✗'}，"
                    f"字幕 {len(subs)} 句{'' if watched or not subs else '没用上'}，{time.time() - t0:.1f}s）")
        return {"watched": watched, "seen": None, "cover": cover}

    # ------------------------------------------------------------ B 站视频下载（最低画质，看完过一阵自动删）
    def _can_download(self, info: dict) -> bool:
        cfg = self._cfg()
        dur = info.get("duration") or 0
        return bool(cfg.get("bili_download", True) and info.get("kind") == "video" and info.get("bvid")
                    and 0 < dur <= float(cfg.get("bili_max_minutes", 40)) * 60)

    def download_dir(self) -> str:
        """下载的视频、扫码图：kaju_data/cache/video（随时能清）。"""
        from kaju_core import paths

        return paths.cache_dir("video")

    def cleanup_downloads(self, now: float | None = None) -> list[str]:
        """删掉看完超过 bili_keep_hours 小时的视频（按文件最后一次被看的时间），返回删了哪些。"""
        now = now or time.time()
        keep = float(self._cfg().get("bili_keep_hours", 2)) * 3600
        removed = []
        try:
            names = os.listdir(self.download_dir())
        except OSError:
            return removed
        for name in names:
            p = os.path.join(self.download_dir(), name)
            try:
                age = now - os.path.getmtime(p)
            except OSError:
                continue
            if age > keep or (name.endswith(".part") and age > 3600):
                try:
                    os.remove(p)
                    removed.append(name)
                except OSError:
                    pass
        if removed:
            self.log.info(f"kaju_basics: 删掉看完的B站视频 {removed}")
        return removed

    async def _bili_download(self, info: dict) -> str:
        """从手机版视频页拿最低画质（360P）的 mp4 下载到 temp/kaju_bili/，返回路径。下过的直接用（顺便重新计时）。"""
        import aiohttp

        cfg = self._cfg()
        self.cleanup_downloads()
        p = int(info.get("p") or 1)
        path = os.path.join(self.download_dir(), f"{info['bvid']}-p{p}.mp4")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            os.utime(path, None)
            return path
        page = f"https://m.bilibili.com/video/{info['bvid']}" + (f"?p={p}" if p > 1 else "")
        max_bytes = float(cfg.get("video_max_mb", 200)) * 1024 * 1024
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("bili_download_timeout", 180)),
                                        sock_connect=float(cfg.get("bili_connect_timeout", 10)))
        t0 = time.time()
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_MOBILE_UA}) as s:
            async with await self._get(s, page) as r:
                if r.status != 200:
                    raise SkipBili(f"手机版视频页打不开（{r.status}）")
                mobile_page = await r.text(errors="replace")
                segs = bili.mobile_play_urls(mobile_page)
            if not segs:
                raise SkipBili("手机版视频页上没有能播放的视频（可能要登录、付费或者是番剧）")
            seg = segs[0]  # 长视频可能分几段，先看第一段
            part = path + ".part"
            n = max(1, int(cfg.get("bili_download_parts", 4)))
            how = "一条线"
            try:
                written = 0
                # Some mobile pages return a large 1080p MP4 even when 360p DASH is available.
                quality = (bili._initial_state(mobile_page).get("video") or {}).get("streamQuality") or 16
                if int(quality) > 16 and info.get("cid"):
                    try:
                        written = await self._download_dash(s, info, page, part, max_bytes)
                        if written:
                            how = "低画质画面 + 声音"
                    except Exception as e:  # noqa: BLE001
                        self.log.info(f"kaju_basics: 低画质视频没下成，改用手机版视频 {type(e).__name__}: {e}")
                if not written and seg["size"] > max_bytes:
                    raise SkipBili(f"视频太大（{seg['size'] / 1024 / 1024:.0f}MB）")
                urls = bili.video_urls(seg["url"], seg.get("backup"))
                if not written and n > 1 and seg["size"] >= float(cfg.get("bili_parts_min_mb", 4)) * 1024 * 1024:
                    try:  # 视频服务器单条连接常常很慢（2026-11-01：21.7MB 下了 67 秒）：分几段同时下
                        written = await self._try_urls(
                            urls, lambda u: self._download_ranges(s, u, page, seg["size"], n, part))
                        how = f"{n} 段同时"
                    except _NoRange:
                        written = 0
                if not written:
                    written = await self._try_urls(urls, lambda u: self._download_stream(s, u, page, part, max_bytes))
                os.replace(part, path)
            finally:
                _unlink(part)
        self.log.info(f"kaju_basics: 下载了B站视频《{info['title']}》最低画质 {written / 1024 / 1024:.1f}MB"
                    f"（{how}，{time.time() - t0:.1f}s{'，只下了第一段' if len(segs) > 1 else ''}），"
                    f"{float(cfg.get('bili_keep_hours', 2)):g} 小时后自动删")
        return path

    async def _download_dash(self, s, info: dict, page: str, part: str, max_bytes: float) -> int:
        """Download the lowest-quality video and audio, then mux without re-encoding."""
        data = await self._bili_api(s, "/x/player/playurl", "", bvid=info["bvid"], cid=str(info["cid"]),
                                    qn="16", fnval="16", fnver="0", fourk="0")
        dash = (data.get("data") or {}).get("dash") or {}
        videos = [v for v in dash.get("video", []) if v.get("baseUrl") or v.get("base_url")]
        if not videos:
            return 0
        tracks = [min(videos, key=lambda v: (int(v["id"]), int(v.get("bandwidth") or 0)))]
        audio = [v for v in dash.get("audio", []) if v.get("baseUrl") or v.get("base_url")]
        if audio:
            tracks.append(min(audio, key=lambda v: int(v.get("bandwidth") or 0)))
        paths = [part + ".video", part + ".audio"][:len(tracks)]
        written = 0
        try:
            for track, target in zip(tracks, paths):
                urls = bili.video_urls(track.get("baseUrl") or track["base_url"],
                                       track.get("backupUrl") or track.get("backup_url"))
                size = await self._try_urls(
                    urls, lambda u, t=target, room=max_bytes - written: self._download_stream(s, u, page, t, room))
                if not size:
                    raise SkipBili("低画质视频没有下载到内容")
                written += size
            if len(paths) == 2:
                await asyncio.to_thread(media.merge_av, paths[0], paths[1], part)
            else:
                os.replace(paths[0], part)
            return written
        finally:
            for target in paths:
                _unlink(target)

    @staticmethod
    async def _try_urls(urls: list[str], fetch):
        """按顺序试这几个地址：服务器连不上、断了、超时就换下一个（2026-11-08 cosov 那台连接超时，整条视频没看成）。"""
        import aiohttp

        last: Exception | None = None
        for i, u in enumerate(urls):
            try:
                return await fetch(u)
            except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, asyncio.TimeoutError, _Incomplete) as e:
                last = e
                host = u.split("/")[2] if "://" in u else u
                more = "，换一台" if i + 1 < len(urls) else ""
                (LOG or logging.getLogger("kaju.bili")).info(f"kaju_basics: 视频服务器 {host} 没连上（{type(e).__name__}）{more}")
        raise last or SkipBili("没有能下载的地址")

    async def _download_stream(self, s, url: str, page: str, part: str, max_bytes: float) -> int:
        written = 0
        headers = {"Referer": page, "User-Agent": BILI_UA, "Range": "bytes=0-"}
        async with await self._get(s, url, hosts=VIDEO_HOSTS, headers=headers) as r:
            if r.status not in (200, 206):
                raise SkipBili(f"视频下载不下来（{r.status}）")
            with open(part, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 16):
                    written += len(chunk)
                    if written > max_bytes:
                        raise SkipBili("视频太大，没下完")
                    f.write(chunk)
        return written

    async def _download_ranges(self, s, url: str, page: str, size: int, n: int, part: str) -> int:
        """分成 n 段（Range 请求）同时下，再按顺序拼起来。服务器不支持分段就抛 _NoRange，改成一条线下。"""
        step = -(-size // n)
        spans = [(i * step, min(size, (i + 1) * step) - 1) for i in range(n) if i * step < size]
        pieces = [f"{part}.{i}" for i in range(len(spans))]

        async def one(i: int, start: int, end: int) -> int:
            got = 0
            headers = {"Referer": page, "Range": f"bytes={start}-{end}"}
            async with await self._get(s, url, hosts=VIDEO_HOSTS, headers=headers) as r:
                if r.status != 206:
                    raise _NoRange()
                with open(pieces[i], "wb") as f:
                    async for chunk in r.content.iter_chunked(1 << 16):
                        got += len(chunk)
                        if got > end - start + 1:
                            raise _NoRange()
                        f.write(chunk)
            if got != end - start + 1:
                raise _Incomplete(f"第 {i + 1} 段没下完整（{got}/{end - start + 1}）")
            return got

        try:
            sizes = await asyncio.gather(*(one(i, a, b) for i, (a, b) in enumerate(spans)))
            with open(part, "wb") as out:
                for p in pieces:
                    with open(p, "rb") as f:
                        while True:
                            buf = f.read(1 << 20)
                            if not buf:
                                break
                            out.write(buf)
            return sum(sizes)
        finally:
            for p in pieces:
                _unlink(p)

    def will_take_a_while(self, info: dict) -> bool:
        """这个视频要下载下来看（还没看过）：得花一两分钟，先跟对方说一声。"""
        hit = self._bili.get("full|" + info.get("url", ""))
        return self._can_download(info) and not (hit is not None and hit[1].done())

    async def _bili_api(self, s, path: str, cookie: str, **params) -> dict:
        """带兄长的登录 Cookie 调 B 站接口（Cookie 只发给 api.bilibili.com）。"""
        headers = {"Cookie": cookie, "Referer": "https://www.bilibili.com/", "Accept": "application/json"}
        async with await self._get(s, BILI_API + path, params=params, headers=headers) as r:
            if r.status != 200:
                raise RuntimeError(f"B站接口 {path} 返回 {r.status}")
            data = json.loads(await r.text(errors="replace"))
        code = data.get("code") if isinstance(data, dict) else None
        if code == -101:
            raise RuntimeError("B站登录失效了（Cookie 过期或填错），私聊发 /佳树B站登录 重新扫码")
        if code not in (0, None):
            raise RuntimeError(f"B站接口 {path} 返回 code {code}：{data.get('message', '')}")
        return data

    async def _bili_subtitle(self, s, info: dict, cookie: str) -> dict:
        """视频的字幕 {lan, name, lines}（UP主上传的或 B 站 AI 识别/翻译的），没有能用的返回 {}。
        播放器接口时灵时不灵、还会串别的视频的字幕：最多问 bili_sub_tries 次，每条都核对属于这个视频再用。"""
        params = {"cid": str(info["cid"])}
        if info.get("bvid"):
            params["bvid"] = info["bvid"]
        tried: set[str] = set()
        rejected = 0
        for i in range(max(1, int(self._cfg().get("bili_sub_tries", 2)))):
            path = ("/x/player/wbi/v2", "/x/player/v2")[i % 2]
            data = await self._bili_api(s, path, cookie, **params)
            aid = (data.get("data") or {}).get("aid") or ""
            subs, _ = bili.parse_player(data)
            for sub in bili.rank_subtitles(subs):
                if sub["url"] in tried:
                    continue
                tried.add(sub["url"])
                if not bili.subtitle_url_ok(sub["url"], aid):
                    rejected += 1
                    continue
                async with await self._get(s, sub["url"]) as r:
                    if r.status != 200:
                        continue
                    lines = bili.parse_subtitle(json.loads(await r.text(errors="replace")))
                if not bili.subtitle_fits(lines, info.get("duration") or 0):
                    rejected += 1
                    continue
                self.log.info(f"kaju_basics: 《{info['title']}》拿到字幕（{sub['name'] or sub['lan']}，{len(lines)} 句，"
                            f"第 {i + 1} 次问到）")
                return {**sub, "lines": lines}
        self.log.info(f"kaju_basics: 《{info['title']}》没有能用的字幕" + (f"（{rejected} 条是别的视频的，没用）" if rejected else ""))
        return {}

    async def _bili_watched(self, info: dict, sub: dict, umo: str) -> str:
        """字幕 → 给她看的内容：中文的短字幕给全文，长的（或日文/英文翻译版）让模型写观后笔记。"""
        cfg = self._cfg()
        text = bili.transcript(sub["lines"])
        zh = bili.is_chinese(sub.get("lan", ""))
        direct = int(cfg.get("bili_direct_chars", 1500))
        if zh and len(text) <= direct:
            return "字幕全文（自动识别的可能有错字）：" + text
        meta = "，".join(x for x in (info.get("up") and f"UP主{info['up']}",
                                     info.get("duration") and bili.fmt_secs(info["duration"])) if x) or "B站视频"
        read = int(cfg.get("doc_read_chars", 80000))
        try:
            local_id = str(cfg.get("vision_provider_id") or "").strip()
            evidence = await self._fit_local_video_text(text, local_id) if local_id else text[:read]
            prompt = VIDEO_DIGEST_PROMPT.format(title=info["title"], meta=meta, text=evidence,
                                                limit=int(cfg.get("bili_digest_chars", 900)))
            if not zh:
                prompt += TRANSLATED_NOTE.format(lang=sub.get("name") or sub.get("lan") or "外语")
            # 指定了本地模型就只用它（没加载就抛"没有可用的模型"，不偷偷换成别的）；没指定用这段聊天正在用的
            digest = (await self.senses.models.think(prompt, VIDEO_DIGEST_SYSTEM, umo, model=local_id,
                                                     timeout=float(cfg.get("doc_timeout", 150)))).strip()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"kaju_basics: 《{info['title']}》观后笔记没写成 {type(e).__name__}: {e}")
            return "字幕太长没看完，只看了开头：" + docs.excerpt(text, direct) if zh else ""
        if not digest or SUB_MISMATCH in digest[:20]:
            self.log.warning(f"kaju_basics: 《{info['title']}》的字幕跟视频对不上，不用")
            return ""
        self.log.info(f"kaju_basics: 《{info['title']}》写好观后笔记（字幕 {len(text)} 字 → {len(digest)} 字）")
        return f"看完了，观后笔记：{digest}" + (f" 开头原话：{docs.excerpt(text, 120)}" if zh else "")

    async def bili_login_status(self) -> str:
        """检查配置里的 Cookie 还登录着没有，返回一句给日志看的话（不含 Cookie 本身）。"""
        import aiohttp

        cookie = self.cookie()
        if not cookie:
            return "B站没登录（/佳树B站登录 扫码）：只看视频页和弹幕"
        timeout = aiohttp.ClientTimeout(total=float(self._cfg().get("bili_timeout", 15)))
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": BILI_UA}) as s:
                data = await self._bili_api(s, "/x/web-interface/nav", cookie)
        except Exception as e:  # noqa: BLE001
            return f"B站登录检查失败：{e}"
        d = data.get("data") or {}
        if not d.get("isLogin"):
            return "B站 Cookie 没登录上（过期或填错了），私聊发 /佳树B站登录 重新扫码"
        return f"B站已登录：{d.get('uname') or '（没有昵称）'}，看视频时会读字幕"

    async def _bili_cover(self, s, info: dict, umo: str) -> str:
        url = info["cover"].replace("http://", "https://", 1)
        async with await self._get(s, url) as r:
            if r.status != 200:
                return ""
            data = await r.read()
        if not data or len(data) > 10 * 1024 * 1024:
            return ""
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        img = os.path.join(_temp_dir(), f"kaju_bili_{uuid.uuid4().hex[:8]}{ext if ext in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'}")
        with open(img, "wb") as f:
            f.write(data)
        try:
            return await self.caption(img, COVER_PROMPT.format(title=info["title"]), umo)
        finally:
            _unlink(img)

    async def _bili_danmaku(self, s, cid: int) -> list:
        import zlib

        async with await self._get(s, f"https://comment.bilibili.com/{int(cid)}.xml") as r:
            if r.status != 200:
                return []
            raw = await r.read()
        if not raw.lstrip().startswith(b"<"):  # 弹幕文件是 raw deflate，aiohttp 一般会自己解开
            for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS, 16 + zlib.MAX_WBITS):
                try:
                    raw = zlib.decompress(raw, wbits)
                    break
                except zlib.error:
                    continue
        return bili.parse_danmaku(raw.decode("utf-8", errors="replace"))
