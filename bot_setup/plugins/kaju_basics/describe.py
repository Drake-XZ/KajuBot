"""kaju_basics 这边的"看"：把 AstrBot 消息里的视频 / 文件 / 图片变成本地文件交给佳树的感官（kaju_core.senses），
再加上 B 站、抖音链接的打开和下载（这部分第 5 步会搬到 platforms）。

- 真正看视频、补看、听音乐、读文件的是 kaju_core.senses.perceive.Senses；这里只负责"文件从哪来"和"用 AstrBot 的哪个模型"。
- 动图：群聊记录里的图片描述是直接把原图发给模型，只能看到第一帧；这里先用 AstrBot 自己的拆帧函数把动图变成一张拼图，再去描述。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from astrbot.api import logger
from kaju_astr import plugin_log
import kaju_core.senses as core_senses
from kaju_core.senses import docs, media, music, perceive
from kaju_core.senses.perceive import (  # noqa: F401 — 老名字：别处和测试还从这里拿
    CACHE_MAX, CACHE_SECONDS, DEFAULT_MUSIC_DIR, DOC_DIGEST_PROMPT, DOC_SYSTEM, GIF_NOTE, MUSIC_PROMPT, MUSIC_SYSTEM,
    RELOOK_PROMPT, SCENE_VIDEO_PROMPT, VIDEO_DIGEST_SYSTEM, VIDEO_PROMPT, WATCH_DIGEST_PROMPT, SkipDoc, SkipVideo,
    watch_segments,
)

from kaju_platforms.bili import bili
from kaju_platforms.bili import links as bili_links
from kaju_platforms.bili.links import (  # noqa: F401 — 老名字：别处和测试还从这里拿
    BILI_API, BILI_HOSTS, BILI_MOBILE_UA, BILI_UA, COVER_PROMPT, SUB_MISMATCH, TRANSLATED_NOTE, VIDEO_DIGEST_PROMPT,
    VIDEO_HOSTS, BiliLinks, SkipBili, _Incomplete, _NoRange,
)
from kaju_platforms.douyin import douyin
from kaju_platforms.douyin.links import DOUYIN_IMAGE_PROMPT, DouyinLinks  # noqa: F401


class Describer(BiliLinks, DouyinLinks):
    def __init__(self, context, cfg):
        self.context = context
        self._cfg = cfg  # () -> dict，插件配置里的 media 段
        self._bili: dict[str, tuple[float, asyncio.Future]] = {}  # 链接 → 页面信息；"full|" + 视频 → 给她看的整段介绍
        self._douyin: dict[str, tuple[float, asyncio.Future]] = {}  # 抖音作品 → (信息, 给她看的介绍)
        self.douyin_profile = lambda: ""  # 她的抖音小号登录着时：那个 Chrome 资料夹（main 设置）
        self.login_cookie = lambda: ""  # 扫码登录的小号 Cookie（bililogin.py，插件装上）；没有就用配置里的 bili_cookie
        self.learner = lambda: None  # kaju_learn（插件装上）：长篇一段一段读、长视频边看边想
        # 她的感官（看图、看视频、补看、听音乐、读文件）：只有这一套，登记在 kaju_core.parts 里，各平台都用它；
        # 这里只告诉它模型从 AstrBot 拿（_AstrModels）、设置在哪
        self.senses = core_senses.start(_AstrModels(self), cfg, learner=lambda: self.learner(), log=logger)
        self.log = plugin_log(logger)  # B站 / 抖音那部分（kaju_platforms 的 BiliLinks / DouyinLinks）用
        bili_links.LOG = self.log

    @property
    def _videos(self) -> dict:
        return self.senses._videos


    # ------------------------------------------------------------ 文字文件（读的是 senses，这里只管把 QQ 文件下载下来）
    async def document(self, comp, event) -> str:
        """读文字文件，返回给她看的内容（见 Senses.document）。失败时返回一句原因（以"没读成："开头）。"""
        return await self.senses.document(self.key(comp), getattr(comp, "name", "") or "",
                                          lambda mb: self._doc_path(comp, mb), event.unified_msg_origin, event)

    async def _doc_path(self, comp, max_mb: float) -> str:
        try:
            path = await comp.get_file()
        except Exception as e:  # noqa: BLE001
            logger.info(f"kaju_basics: 文件下载失败 {type(e).__name__}: {e}")
            raise SkipDoc("文件没能下载下来，佳树没看到内容") from e
        if not path or not os.path.exists(path):
            raise SkipDoc("文件没能下载下来，佳树没看到内容")
        size_mb = os.path.getsize(path) / 1024 / 1024
        if size_mb > max_mb:
            raise SkipDoc(f"文件太大了（{size_mb:.0f}MB），佳树没打开")
        return path

    async def doc_excerpt(self, comp, n: int) -> str:
        """群聊记录用：只读开头几句（不调模型），读不了返回空字符串。"""
        return await self.senses.doc_excerpt(getattr(comp, "name", "") or "", lambda mb: self._doc_path(comp, mb), n)

    # ------------------------------------------------------------ B 站链接
    def _cached(self, table: dict, key: str, make) -> asyncio.Future:
        return perceive.cached(table, key, make)


    # ------------------------------------------------------------ 视频
    @staticmethod
    def key(comp) -> str:
        return str(getattr(comp, "file", "") or getattr(comp, "url", "") or getattr(comp, "path", "") or id(comp))

    async def watch(self, comp, event, title: str = "", listen_music: bool = False) -> str:
        """看视频（见 Senses.watch），看不成就抛异常（SkipVideo 等）。同一个视频半小时内只看一次。"""
        return await self.senses.watch(self.key(comp), lambda: self._local_path(comp, event),
                                       getattr(event, "unified_msg_origin", ""), title, listen_music)

    async def watch_file(self, path: str, event, title: str = "", listen_music: bool = False) -> str:
        """平台下载好的本地视频（B站、抖音）：当成一个视频组件交给 watch。"""
        from astrbot.api.message_components import Video

        return await self.watch(Video.fromFileSystem(path), event, title=title, listen_music=listen_music)

    # ------------------------------------------------------------ 补看（relook.py）
    def last_video(self, umo: str, minutes: float) -> dict | None:
        """这个聊天里 minutes 分钟内看过的最近那个视频；没有返回 None。"""
        return self.senses.last_video(umo, minutes)

    async def relook(self, meta: dict, start: float, end: float, question: str, umo: str) -> str:
        """回到看过的视频，把 start~end 这一段截几帧大图、带着问题再看一遍。文件已经删了抛 SkipVideo。"""
        return await self.senses.relook(meta, start, end, question, umo)

    async def video(self, comp, event, listen_music: bool = False) -> str:
        """返回视频描述（失败时返回一句原因），同一个视频只处理一次。"""
        try:
            return await self.watch(comp, event, listen_music=listen_music)
        except SkipVideo as e:
            return str(e)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kaju_basics: 视频描述失败 {type(e).__name__}: {e}")
            return "视频没能打开，佳树没看到内容"

    async def _local_path(self, comp, event) -> str:
        try:
            path = await comp.convert_to_file_path()
            if path and os.path.exists(path):
                return path
        except Exception as e:  # noqa: BLE001
            logger.info(f"kaju_basics: 视频直接下载失败（{type(e).__name__}: {e}），试试协议端 get_file")
        bot = getattr(event, "bot", None)
        file_id = getattr(comp, "file", "") or ""
        if bot is not None and file_id and not file_id.startswith(("http", "file:", "base64:")):
            ret = await bot.call_action("get_file", file=file_id)
            ret = ret or {}
            path = ret.get("file") or ""
            if path and os.path.exists(path):
                return path
            url = ret.get("url") or ""
            if url.startswith("http"):
                from astrbot.api.message_components import Video

                return await Video.fromURL(url).convert_to_file_path()
        raise SkipVideo("视频下载不下来，佳树没看到内容")

    async def _watch_digest(self, title: str, duration: str, caption: str, speech: str, umo: str) -> str:
        return await self.senses.watch_digest(title, duration, caption, speech, umo)

    async def _fit_local_video_text(self, text: str, pid: str) -> str:
        return await self.senses.fit_text(text, pid)

    # ------------------------------------------------------------ 音乐（听的是 senses）
    def _music_on(self) -> bool:
        return self.senses.music_on()

    async def hear_music(self, path: str, what: str, umo: str) -> str:
        return await self.senses.hear_music(path, what, umo)

    async def music_file(self, comp, event) -> str:
        """发来的音乐文件（mp3/flac/…）：听音乐本身 + 有人声的话转写歌词/说话。同一个文件半小时内只听一次。"""
        return await self.senses.music_file(self.key(comp), getattr(comp, "name", "") or "",
                                            lambda mb: self._doc_path(comp, mb), event.unified_msg_origin)

    # ------------------------------------------------------------ 看图用的模型
    async def caption(self, image_path: str, prompt: str, umo: str, key: str = "vision_provider_id") -> str:
        """key：设置里哪一项管这次用的模型（vision_provider_id 看视频画面，image_provider_id 看图片动图）。"""
        selected = str(self._cfg().get(key) or "").strip()
        pid = selected
        if not pid:
            try:
                pid = self.context.get_config(umo=umo)["provider_ltm_settings"].get("image_caption_provider_id") or ""
            except Exception:  # noqa: BLE001
                pass
        provider = self.context.get_provider_by_id(pid) if pid else None
        if provider is None and selected:
            raise RuntimeError(f"没有加载指定的视觉模型：{selected}")
        if provider is None:
            provider = await self.context.get_using_provider_async(umo)
        if provider is None:
            raise RuntimeError("没有能看图的模型")
        resp = await provider.text_chat(prompt=prompt, session_id=uuid.uuid4().hex,
                                        image_urls=[image_path], persist=False)
        return (resp.completion_text or "").strip()

    # ------------------------------------------------------------ 动图（群聊记录里的图片描述）
    async def image_caption(self, orig, image_url: str, provider_id: str, prompt: str) -> str:
        """包住内置的 get_image_caption：图先下载成本地文件，交给她的感官看（Senses.image：动图拆帧拼成一张再描述，
        其它图原样）。用哪个模型：设置里填了 image_provider_id 就用它，没填照旧用内置的图片描述模型。"""
        if not self._cfg().get("gif_frames", True):
            return await orig(image_url, provider_id, prompt)
        try:
            from pathlib import Path

            from astrbot.core.utils.media_utils import prepare_model_image

            # 只借它下载、拿到原图在哪；拆帧在 Senses.image 里做
            prepared = await prepare_model_image(image_url, max_size=int(self._cfg().get("max_edge", 1280)),
                                                 output_dir=Path(_temp_dir()))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"kaju_basics: 图片预处理失败，按原图描述：{e}")
            prepared = None
        if not prepared:
            return await orig(image_url, provider_id, prompt)
        path, _is_montage, delete, original = prepared
        look = None
        if not str(self._cfg().get("image_provider_id") or "").strip():
            async def look(p: str, pr: str) -> str:
                return await orig(p, provider_id, pr)
        look_gif = None
        if str(self._cfg().get("gif_provider_id") or "").strip():
            # 动图拼图交给专门的模型（2026-11-11：同一张动图各看 3 遍，本地 qwen3-vl 3 次都认对手势，DeepSeek 只对 1 次）
            async def look_gif(p: str, pr: str) -> str:
                return await self.caption(p, pr, "", key="gif_provider_id")
        try:
            # 普通图：用下载好的原图（不缩小，长截图里的字才看得清）
            return await self.senses.image(original or image_url, prompt=prompt, look=look, look_gif=look_gif)
        finally:
            if delete and path != original:
                _unlink(path)

    async def turn_image(self, image_url: str, said: str, umo: str) -> str:
        """当前这条消息里的图（本来是写回复的模型自己看）：先交给 Gemini 看，返回描述。
        Gemini 这双眼睛没开、没看成都抛异常——调用的地方就照旧把图留给写回复的模型。"""
        from pathlib import Path

        from astrbot.core.utils.media_utils import prepare_model_image

        prepared = await prepare_model_image(image_url, max_size=int(self._cfg().get("max_edge", 1280)), output_dir=Path(_temp_dir()))
        if not prepared:
            raise RuntimeError("图片没下载下来")
        path, _is_montage, delete, original = prepared
        prompt = perceive.IMAGE_PROMPT
        if said:
            prompt += f"\n发图的人同时说了：「{said[:200]}」。和这句话有关的地方看仔细、写清楚；这句话本身不用回答。"
        try:
            return await self.senses.image(original or path, who=umo, prompt=prompt, fallback=False)
        finally:
            if delete and path != original:
                _unlink(path)

    def close(self) -> None:
        """插件停下时：把登记的感官去掉（新实例已经顶上就不动）。"""
        core_senses.stop(self.senses)


class _AstrModels(perceive.Models):
    """感官要的模型，从 AstrBot 拿。看图走 Describer.caption（测试会替换它）。"""

    def __init__(self, d: "Describer"):
        self.d = d

    async def look(self, image_path: str, prompt: str, who: str) -> str:
        return await self.d.caption(image_path, prompt, who)

    async def look_image(self, image_path: str, prompt: str, who: str) -> str:
        return await self.d.caption(image_path, prompt, who, key="image_provider_id")

    async def think(self, prompt: str, system: str, who: str, model: str = "", timeout: float = 150) -> str:
        ctx = self.d.context
        prov = ctx.get_provider_by_id(model) if model else await ctx.get_using_provider_async(who)
        if prov is None:
            raise RuntimeError("没有可用的模型")
        pid = (getattr(prov, "provider_config", None) or {}).get("id") or prov.meta().id
        resp = await asyncio.wait_for(ctx.llm_generate(chat_provider_id=pid, prompt=prompt, system_prompt=system),
                                      timeout=timeout)
        return getattr(resp, "completion_text", "") or ""

    def ears(self, who: str):
        stt = self.d.context.get_using_stt_provider(who)
        if stt is None:
            return None

        async def hear(wav: str) -> str:
            return await stt.get_text(audio_url=wav) or ""

        return hear


async def _empty() -> str:
    return ""


async def _empty_dict() -> dict:
    return {}


_temp_dir = perceive.temp_dir
_unlink = perceive.unlink
