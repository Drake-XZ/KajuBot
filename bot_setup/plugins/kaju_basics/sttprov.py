"""把本地 SenseVoice（localstt.py）挂进 AstrBot，当成一个语音转文字提供商（id: local_sensevoice）。

AstrBot 自己收到语音时（预处理阶段）、kaju_basics 听视频声音时，都是问 AstrBot 要"当前的语音转文字提供商"，
所以挂进去、再把 AstrBot 配置里的 provider_stt_settings.provider_id 指向它，两边就都用本地的了。
提供商类型要在 AstrBot 的注册表里登记（WebUI 列提供商时会查），插件重载时不能重复登记，只换掉类。
"""

from __future__ import annotations

import asyncio
import os

from astrbot.api import logger

from kaju_core.senses.localstt import SenseVoice

PROVIDER_ID = "local_sensevoice"
PROVIDER_TYPE = "kaju_local_sensevoice"
DIRECT_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".flac", ".webm", ".mkv", ".mov"}


def make_provider(sv: SenseVoice):
    from astrbot.core.provider.entities import ProviderType
    from astrbot.core.provider.provider import STTProvider
    from astrbot.core.provider.register import provider_cls_map, register_provider_adapter

    class KajuLocalSenseVoice(STTProvider):
        def __init__(self, provider_config: dict, provider_settings: dict) -> None:
            super().__init__(provider_config, provider_settings)
            self.set_model("SenseVoiceSmall-int8（本地）")
            self.sv = sv

        async def get_text(self, audio_url: str) -> str:
            path = audio_url[8:] if audio_url.startswith("file:///") else audio_url
            ext = os.path.splitext(path.split("?")[0])[1].lower()
            if os.path.isfile(path) and ext in DIRECT_EXTS:
                return await asyncio.to_thread(self.sv.transcribe, path)
            # QQ 语音（silk/amr）、网址：交给 AstrBot 自己的转换（跟原来的硅基流动提供商一样）
            from astrbot.core.utils.media_utils import MediaResolver

            async with MediaResolver(audio_url, media_type="audio", default_suffix=".wav").as_path(
                    target_format="wav") as audio:
                return await asyncio.to_thread(self.sv.transcribe, str(audio.path))

    if PROVIDER_TYPE in provider_cls_map:
        provider_cls_map[PROVIDER_TYPE].cls_type = KajuLocalSenseVoice
    else:
        register_provider_adapter(PROVIDER_TYPE, "佳树基础：本地 SenseVoice 语音转文字（sherpa-onnx）",
                                  provider_type=ProviderType.SPEECH_TO_TEXT)(KajuLocalSenseVoice)
    return KajuLocalSenseVoice({"id": PROVIDER_ID, "type": PROVIDER_TYPE, "provider_type": "speech_to_text",
                                "enable": True}, {})


async def install(context, sec: dict):
    """加载模型、挂进 AstrBot、（make_default 时）设成默认语音转文字。返回提供商实例；装不上返回 None。"""
    sv = SenseVoice(str(sec.get("model_dir") or ""), str(sec.get("vad_model") or ""),
                    int(sec.get("threads", 4)), float(sec.get("max_seconds", 25)))
    why = sv.check()
    if why:
        logger.warning(f"kaju_basics: 本地语音转文字没装上：{why}")
        return None
    # 模型（约 300 MB 内存）不在这里加载：第一次识别时才加载，闲置 stt.idle_minutes 后由 main._stt_loop 放掉
    inst = make_provider(sv)
    pm = context.provider_manager
    uninstall(context)
    pm.inst_map[PROVIDER_ID] = inst
    pm.stt_provider_insts.append(inst)
    cfg = context.get_config()
    stt = cfg.get("provider_stt_settings")
    if isinstance(stt, dict) and sec.get("make_default", True):
        if stt.get("provider_id") != PROVIDER_ID or not stt.get("enable"):
            old = stt.get("provider_id")
            stt["provider_id"], stt["enable"] = PROVIDER_ID, True
            try:
                cfg.save_config()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"kaju_basics: 保存语音转文字设置失败 {e}")
            logger.info(f"kaju_basics: 默认语音转文字从 {old} 换成本地 SenseVoice")
        pm.curr_stt_provider_inst = inst
    logger.info(f"kaju_basics: 本地语音转文字就绪（SenseVoice int8，{sv.threads} 线程，用到时才加载，{sv.model_dir}）")
    return inst


def uninstall(context) -> None:
    pm = context.provider_manager
    old = pm.inst_map.pop(PROVIDER_ID, None)
    if old is not None:
        pm.stt_provider_insts[:] = [p for p in pm.stt_provider_insts if p is not old]
        if pm.curr_stt_provider_inst is old:
            pm.curr_stt_provider_inst = pm.stt_provider_insts[0] if pm.stt_provider_insts else None
