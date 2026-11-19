"""Tests for the local speech-to-text (kaju_basics localstt.py + sttprov.py).

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_localstt.py

Uses the real SenseVoice model in D:\\JiashuBot\\models when it is there (skips those checks otherwise).
"""

import asyncio
import importlib
import os
import shutil
import sys
import tempfile
import wave

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core（不然会拿到部署到 AstrBot 的那份）
os.environ["STUB_DATA"] = tempfile.mkdtemp()

localstt = importlib.import_module("kaju_core.senses.localstt")
sttprov = importlib.import_module("kaju_basics.sttprov")
register = importlib.import_module("astrbot.core.provider.register")
failures = []
MODEL = r"D:\JiashuBot\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
VAD = r"D:\JiashuBot\models\silero_vad.onnx"
HAVE_MODEL = os.path.isfile(os.path.join(MODEL, "model.int8.onnx"))


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


# ------------------------------------------------------------------ 纯逻辑
expect("join zh", localstt.join_texts(["你好。", " 我是佳树。", ""]), "你好。我是佳树。")
expect("join en", localstt.join_texts(["Hello there.", "How are you", "fine"]), "Hello there. How are you fine")
expect("join mixed", localstt.join_texts(["今天看了", "MV", "好听"]), "今天看了MV好听")
expect("fixed windows", [len(w) for w in localstt.fixed_windows(np.zeros(16000 * 50, np.float32), 20)],
       [320000, 320000, 160000])
sv0 = localstt.SenseVoice("", "")
expect("check missing model", sv0.check().startswith("找不到"), True)
expect("short audio: one segment", len(sv0.segments(np.zeros(16000 * 10, np.float32))), 1)
expect("empty audio: none", sv0.segments(np.zeros(0, np.float32)), [])
expect("long, no vad: fixed", len(sv0.segments(np.zeros(16000 * 60, np.float32))), 3)


# ------------------------------------------------------------------ 挂进 AstrBot
class FakeConfig(dict):
    saved = 0

    def save_config(self):
        FakeConfig.saved += 1


class FakePM:
    def __init__(self, other):
        self.inst_map = {"siliconflow_stt": other}
        self.stt_provider_insts = [other]
        self.curr_stt_provider_inst = other


class FakeCtx:
    def __init__(self):
        self.provider_manager = FakePM(object())
        self.config = FakeConfig({"provider_stt_settings": {"enable": True, "provider_id": "siliconflow_stt"}})

    def get_config(self, umo=None):
        return self.config


async def provider_tests():
    ctx = FakeCtx()
    expect("not installed without model", await sttprov.install(ctx, {"model_dir": "", "vad_model": ""}), None)
    expect("config untouched", ctx.config["provider_stt_settings"]["provider_id"], "siliconflow_stt")
    if not HAVE_MODEL:
        print("SKIP: 没有模型文件，跳过真识别")
        return
    sec = {"model_dir": MODEL, "vad_model": VAD, "threads": 2}
    inst = await sttprov.install(ctx, sec)
    pm = ctx.provider_manager
    expect("installed", (pm.inst_map.get(sttprov.PROVIDER_ID) is inst, inst in pm.stt_provider_insts,
                         pm.curr_stt_provider_inst is inst), (True, True, True))
    expect("default switched + saved", (ctx.config["provider_stt_settings"], FakeConfig.saved),
           ({"enable": True, "provider_id": sttprov.PROVIDER_ID}, 1))
    expect("type registered", sttprov.PROVIDER_TYPE in register.provider_cls_map, True)
    expect("model not loaded at install (loads on first use)", inst.sv._rec is None, True)
    # 样例语音（模型自带）：中文带标点、阿拉伯数字
    text = await inst.get_text(os.path.join(MODEL, "test_wavs", "zh.wav"))
    expect("zh sample", "早上9点至下午5点" in text, True)
    expect("loaded after use, not idle yet", (inst.sv._rec is not None, inst.sv.release_if_idle(60)), (True, False))
    expect("released when idle", (inst.sv.release_if_idle(0), inst.sv._rec), (True, None))
    text = await inst.get_text(os.path.join(MODEL, "test_wavs", "zh.wav"))
    expect("reloads after release", ("下午5点" in text, inst.sv._rec is not None), (True, True))
    # QQ 语音（silk）走 AstrBot 自己的转换：替身把 x.silk 当成旁边的 x.wav
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(MODEL, "test_wavs", "zh.wav"), os.path.join(tmp, "voice.wav"))
    expect("silk via MediaResolver", "下午5点" in await inst.get_text(os.path.join(tmp, "voice.silk")), True)
    # 长音频（2 分多钟）：按停顿切句再识别
    parts = []
    for n in ("zh", "en", "ja", "yue", "ko") * 5:
        parts += [localstt.read_audio(os.path.join(MODEL, "test_wavs", n + ".wav")), np.zeros(12800, np.float32)]
    big = np.concatenate(parts)
    p = os.path.join(tmp, "long.wav")
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((big * 32767).astype(np.int16).tobytes())
    long_text = await inst.get_text(p)
    expect("long audio split by vad", (len(inst.sv.segments(big)) >= 20, long_text.count("下午5点") >= 4,
                                       long_text.count("50 pieces") >= 4), (True, True, True))
    # 插件重载：再装一次，不重复登记、不重复挂
    inst2 = await sttprov.install(ctx, sec)
    expect("reinstall replaces", (pm.inst_map[sttprov.PROVIDER_ID] is inst2, inst in pm.stt_provider_insts,
                                  sum(1 for x in pm.stt_provider_insts if x is inst2), FakeConfig.saved), (True, False, 1, 1))
    sttprov.uninstall(ctx)
    expect("uninstall", (sttprov.PROVIDER_ID in pm.inst_map, pm.curr_stt_provider_inst is pm.stt_provider_insts[0]),
           (False, True))
    # 不设成默认：只挂上，不改配置
    ctx2 = FakeCtx()
    await sttprov.install(ctx2, {**sec, "make_default": False})
    expect("make_default off", (ctx2.config["provider_stt_settings"]["provider_id"], sttprov.PROVIDER_ID in ctx2.provider_manager.inst_map),
           ("siliconflow_stt", True))


asyncio.run(provider_tests())
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
