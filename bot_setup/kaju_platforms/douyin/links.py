"""抖音链接：用本机 Chrome 打开作品、下载视频 / 图文给她看（原来在 kaju_basics 的 describe.py 里）。

DouyinLinks 是 mixin，宿主（kaju_basics 的 Describer）要有：_cfg()、_cached()、_douyin 表、douyin_profile()、
download_dir()、watch_file(path, event, …)、caption(path, prompt, who)、log。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid

from kaju_core.senses import docs, media, music
from kaju_core.senses.perceive import VIDEO_DIGEST_SYSTEM, SkipVideo
from kaju_core.senses.perceive import temp_dir as _temp_dir
from kaju_core.senses.perceive import unlink as _unlink

from kaju_platforms.bili import bili

from . import douyin

DOUYIN_IMAGE_PROMPT = ("这是抖音图文作品《{title}》的第 {n} 张图（共 {total} 张）。用中文描述：画面上是什么、"
                       "图里能看清的文字原样写出来。80 字以内，不要用 markdown。")


class DouyinLinks:
    """抖音那部分（宿主见模块说明）。"""

    # ------------------------------------------------------------ 抖音（douyin.py：开真浏览器看页面，下载视频按 B 站的办法看）
    async def douyin_video(self, url: str, event) -> tuple[dict | None, str]:
        """(作品信息, 给她看的整段介绍)。没看成时信息是 None，介绍以"没打开："开头。同一个作品半小时内只看一次。"""
        key = douyin.aweme_id(url) or url
        try:
            return await asyncio.shield(self._cached(self._douyin, key, lambda: self._douyin_full(url, event)))
        except douyin.SkipDouyin as e:
            self._douyin.pop(key, None)  # 没看成的不记，下次再试
            return None, f"没打开：{e}"
        except Exception as e:  # noqa: BLE001
            self._douyin.pop(key, None)
            self.log.warning(f"kaju_basics: 抖音链接没打开 {type(e).__name__}: {e}")
            return None, "没打开：抖音链接没能打开，佳树没看到是什么视频"

    async def _douyin_full(self, url: str, event) -> tuple[dict, str]:
        cfg = self._cfg()
        t0 = time.time()
        got = await douyin.fetch(
            url, self.download_dir(), channel=str(cfg.get("douyin_browser") or "chrome"),
            timeout=float(cfg.get("douyin_timeout", 30)), max_mb=float(cfg.get("douyin_max_mb", 60)),
            max_seconds=float(cfg.get("douyin_max_minutes", 20)) * 60, max_images=int(cfg.get("douyin_images", 4)),
            want_comments=int(cfg.get("douyin_comments", 6)) > 0,
            profile=self.douyin_profile() if cfg.get("douyin_use_login", True) else "",
            image_side=int(cfg.get("douyin_image_side", 1024)))
        info = got["info"]
        comments = got["comments"][:int(cfg.get("douyin_comments", 6))]
        watched, seen = "", ""
        if got.get("video"):
            try:
                watched = await self.watch_file(got["video"], event, title=info["title"],
                                           listen_music=douyin.is_music_video(info))
                seen = bili.SEEN_VIDEO
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"kaju_basics: 抖音视频下载了但没看成 {type(e).__name__}: {e}")
        elif got.get("images"):
            umo = event.unified_msg_origin
            caps = []
            for i, path in enumerate(got["images"]):
                try:
                    cap = await self.caption(path, DOUYIN_IMAGE_PROMPT.format(
                        n=i + 1, total=len(info["images"]), title=info["title"]), umo)
                except Exception as e:  # noqa: BLE001
                    self.log.info(f"kaju_basics: 抖音图文第 {i + 1} 张没看成 {type(e).__name__}: {e}")
                    cap = ""
                finally:
                    _unlink(path)
                if cap:
                    caps.append(f"第{i + 1}张：{cap}")
            if caps:
                watched = "看了" + (f"前 {len(caps)} 张" if len(info["images"]) > len(caps) else "全部") + "图：" + " ".join(caps)
        elif got.get("skip"):
            self.log.info(f"kaju_basics: 抖音《{info['title']}》{got['skip']}")
        text = douyin.describe(info, watched, comments, seen)
        self.log.info(f"kaju_basics: 看了抖音《{info['title']}》（{'视频' if got.get('video') else '图文' if got.get('images') else '只有页面'}，"
                    f"评论 {len(comments)} 条，{time.time() - t0:.1f}s）")
        return info, text
