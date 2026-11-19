"""把 AstrBot 自带的动图拆帧（media_utils._prepare_model_image_sync）换成 kaju_core.senses.animation 的按时间拆帧，
主流程里给看图模型的动图提示（astr_main_agent.ANIMATION_CAPTION_NOTICE）也换成配套的。只有这一步认识 AstrBot。"""

from __future__ import annotations

import io

from kaju_core.senses.animation import CAPTION_NOTICE, build

ORIG_ATTR = "_kaju_anim_orig_prepare"
ORIG_NOTICE_ATTR = "_kaju_anim_orig_notice"


def _target():
    try:
        from astrbot.core.utils import media_utils
    except Exception:  # noqa: BLE001
        return None
    return media_utils if hasattr(media_utils, "_prepare_model_image_sync") else None


def _agent():
    try:
        from astrbot.core import astr_main_agent
    except Exception:  # noqa: BLE001
        return None
    return astr_main_agent if hasattr(astr_main_agent, "ANIMATION_CAPTION_NOTICE") else None


def install(get_opts, log, mod=None, agent=None) -> bool:
    """get_opts() 每次读 {"enable": bool, "max_frames": int}。重复安装 / 热重载时总是包在最初的函数外面。"""
    mod = mod or _target()
    if mod is None:
        return False
    orig = getattr(mod, ORIG_ATTR, None) or mod._prepare_model_image_sync

    def prepare(source_bytes: bytes, max_size: int):
        try:
            opts = get_opts() or {}
        except Exception:  # noqa: BLE001
            opts = {}
        if opts.get("enable", True):
            try:
                from PIL import Image

                with Image.open(io.BytesIO(source_bytes)) as im:
                    if getattr(im, "n_frames", 1) > 1:
                        frames = max(2, min(16, int(opts.get("max_frames", 8) or 8)))
                        img, animated = build(im, max(64, int(max_size or 1280)), frames)
                        try:
                            if animated:
                                return mod._encode_image_frame_bytes(img), True
                            return mod._encode_image_frame_bytes(img, max_size), False
                        finally:
                            img.close()
            except Exception as e:  # noqa: BLE001 - 出了问题就用自带的
                log(f"kaju_basics: 动图拆帧失败，用自带的：{type(e).__name__}: {e}")
        return orig(source_bytes, max_size)

    setattr(mod, ORIG_ATTR, orig)
    mod._prepare_model_image_sync = prepare

    agent = agent or _agent()
    if agent is not None:
        if not hasattr(agent, ORIG_NOTICE_ATTR):
            setattr(agent, ORIG_NOTICE_ATTR, agent.ANIMATION_CAPTION_NOTICE)
        agent.ANIMATION_CAPTION_NOTICE = CAPTION_NOTICE
    return True


def uninstall(mod=None, agent=None) -> None:
    mod = mod or _target()
    if mod is not None and hasattr(mod, ORIG_ATTR):
        mod._prepare_model_image_sync = getattr(mod, ORIG_ATTR)
        delattr(mod, ORIG_ATTR)
    agent = agent or _agent()
    if agent is not None and hasattr(agent, ORIG_NOTICE_ATTR):
        agent.ANIMATION_CAPTION_NOTICE = getattr(agent, ORIG_NOTICE_ATTR)
        delattr(agent, ORIG_NOTICE_ATTR)
