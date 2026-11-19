"""Tests for 听音乐 (kaju_basics music.py + Describer.hear_music / music_file + describe_media).

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_music.py
        离线：认音乐文件/音乐视频/问到歌、挑报告、转 wav、真引擎跑一段合成的钢琴声（约 10 秒）、假模型走一遍接入
    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_music.py --live 歌1.mp3 [歌2.mp4 …]
        真引擎 + 真模型：每首歌的测量摘要、她听到的感觉、她用真人设的回复 3 次、情绪判断（只打印）
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import wave

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, PLUGINS)
sys.path.insert(0, os.path.dirname(os.path.abspath(PLUGINS)))  # 源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

import numpy as np  # noqa: E402

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import File, Plain, Reply, Video  # noqa: E402
from astrbot.api.provider import LLMResponse, ProviderRequest  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from astrbot.core.agent.message import TextPart  # noqa: E402

music = importlib.import_module("kaju_core.senses.music")
describe = importlib.import_module("kaju_basics.describe")
kb = importlib.import_module("kaju_basics.main")
MODELS = r"D:\JiashuBot\models\music"
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


TMP = tempfile.mkdtemp()

# ------------------------------------------------------------------ 认东西
expect("audio exts", [music.is_audio(n) for n in ("歌.MP3", "a.flac", "b.m4a?x=1", "c.wav", "d.mp4", "e.txt", "")],
       [True, True, True, True, False, False, False])
expect("music area", music.is_music_video({"area": "音乐综合", "title": "随便"}), True)
expect("vocaloid area", music.is_music_video({"area": "VOCALOID·UTAU"}), True)
expect("cover title", music.is_music_video({"area": "动画", "title": "【AI高松燈】夜に駆ける / YOASOBI 翻唱"}), True)
expect("piano tag", music.is_music_video({"area": "", "title": "青山绿野", "tags": ["钢琴"]}), True)
expect("not music", [music.is_music_video(i) for i in (
    {"area": "动画综合", "title": "佳树的独特到底在哪？温水佳树的人物解读！", "tags": ["败犬女主太多了", "原创"]},
    {"area": "日常", "title": "原创动画短片", "tags": []},
    {"area": "", "title": "", "tags": []})], [False, False, False])
expect("asks music", [music.asks_music(t) for t in ("这首歌好听吗", "听听这个", "bgm是什么", "这个视频好笑", "")],
       [True, True, True, False, False])
expect("python exe", music.python_exe(""), sys.executable)

REPORT = """[读法] 「推测/候选/可能」=推断；直接报数=测量；没提到=测不出来
[判断] 3 分 39 秒的曲子,速度约 81 拍。
       编曲重心在后半段:越往后越密。
[结构] 声学变化片段 6 个（强边界，±3 秒；不推断主歌/副歌）
       边界 0:25.0 / 0:37.2
[四维] 推测：偏暗 · 偏慢 · 偏弱 · 偏暖（明暗=谱质心）

[依据] 峰值 -0.3 dBFS | 整合 -14.9 LUFS
[可信] beat 0.92 | 调性 0.57
[标签] 模型预测标签(50 类,仅作辅助参考,不等同于流派识别): piano 0.96、slow 0.36、solo 0.26
[能量] ▂█▅▇▇▁  （每格=一个结构段）
[时间线] 动作=推断，括号内=测量
       0:00.0  开场：能量偏低
[钩子] 最可能是钩子的位置：1:37.1–3:27.4（能量在峰值区 / 起音最密）
       说明：这是几个测量同时到峰值的位置，不是已经确认的副歌——段落角色要听过才知道。
[听不到] 音符级的旋律、歌词和语言"""
picked = music.pick(REPORT)
expect("pick keeps", [k in picked for k in ("[判断]", "越往后越密", "[四维]", "[标签]", "[能量]", "[钩子]", "[听不到]")],
       [True] * 7)
expect("pick drops", [k in picked for k in ("[读法]", "[结构]", "边界 0:25", "[依据]", "LUFS", "[可信]", "[时间线]", "开场", "说明：")],
       [False] * 9)
expect("tags", music.tags(REPORT), ["piano", "slow", "solo"])
expect("weak tags dropped", ("piano 0.96" in picked, "slow" in picked, "solo" in picked), (True, False, False))
low = REPORT.replace("piano 0.96", "techno 0.43")
expect("all weak → no tag line", ("[标签]" in music.pick(low), "techno" in music.pick(low), "[能量]" in music.pick(low)),
       (False, False, True))
expect("tag_min configurable", "slow 0.36" in music.pick(REPORT, 0.3), True)


# ------------------------------------------------------------------ 转 wav、真引擎
def make_piano(path, seconds=24.0, rate=44100):
    """合成一段"钢琴"：每 0.75 秒弹一个和弦（A-C#-E / F#-A-C# 交替），带衰减。"""
    t = np.arange(int(seconds * rate)) / rate
    y = np.zeros_like(t)
    chords = [(440.0, 554.37, 659.25), (369.99, 440.0, 554.37)]
    for i, start in enumerate(np.arange(0, seconds, 0.75)):
        seg = t >= start
        env = np.exp(-(t[seg] - start) * 3.0)
        for f in chords[(i // 4) % 2]:
            y[seg] += np.sin(2 * np.pi * f * (t[seg] - start)) * env * 0.12
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


src = os.path.join(TMP, "piano.wav")
make_piano(src)
out = os.path.join(TMP, "out.wav")
secs = music.to_wav(src, out, max_seconds=600)
with wave.open(out) as w:
    expect("to_wav format", (w.getnchannels(), w.getframerate(), round(secs)), (2, 44100, 24))
secs = music.to_wav(src, out, max_seconds=10)
with wave.open(out) as w:
    expect("to_wav clamp", (round(secs, 1), round(w.getnframes() / 44100, 1)), (10.0, 10.0))

ENGINE_OK = os.path.isfile(os.path.join(MODELS, "models", "beat_this", "beat-this-final0.onnx"))
if ENGINE_OK:
    t0 = time.time()
    music.to_wav(src, out, 600)
    rep = music.run_engine(out, MODELS, timeout=180)
    took = time.time() - t0
    print(f"（真引擎跑 24 秒合成钢琴：{took:.1f}s）")
    expect("engine report sections", [k in rep for k in ("[判断]", "[标签]")], [True, True])
    expect("engine sees piano-ish", any(x in music.tags(rep) for x in ("piano", "harpsichord", "classical", "solo", "slow")), True)
    try:
        music.run_engine(os.path.join(TMP, "nope.wav"), MODELS, timeout=60)
        expect("engine missing file raises", False, True)
    except RuntimeError as e:
        expect("engine missing file raises", "退出码" in str(e), True)
else:
    print("（没装音乐模型，跳过真引擎测试）")


# ------------------------------------------------------------------ 接进插件（假引擎、假模型）
class FakeSTT:
    def __init__(self, text=""): self.text, self.calls = text, 0

    async def get_text(self, audio_url=""):
        self.calls += 1
        return self.text


def make(stt_text="", answer="很安静的钢琴，慢慢的，后面一点点热闹起来，最后又轻轻收住。", report=REPORT, cfg=None):
    ctx = Context({"timezone": "Asia/Shanghai", "provider_ltm_settings": {}})
    ctx.stars = [type("Meta", (), {"star_cls": FakeWriter()})()]
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}
    ctx.stt = FakeSTT(stt_text)
    prompts = []

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        prompts.append((chat_provider_id, prompt, system_prompt))
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(answer)

    ctx.llm_generate = llm_generate
    b = kb.KajuBasics(ctx, {"media": dict({"music_data_dir": MODELS}, **(cfg or {}))})
    runs = []

    def fake_engine(wav, data_dir, python="", timeout=180, threads=2):
        runs.append((os.path.exists(wav), data_dir))
        if isinstance(report, Exception):
            raise report
        return report

    b._fake_runs = runs
    music.run_engine = fake_engine
    return b, prompts


REAL_ENGINE = music.run_engine


async def plugin_tests():
    b, prompts = make()
    ev = AstrMessageEvent()
    note = await b._describer.hear_music(src, "音乐文件《piano》", ev.unified_msg_origin)
    expect("hear note", note, "很安静的钢琴，慢慢的，后面一点点热闹起来，最后又轻轻收住。")
    expect("engine got wav + dir", b._fake_runs, [(True, MODELS)])
    pid, prompt, system = prompts[0]
    expect("note prompt", (pid, "[判断]" in prompt, "LUFS" in prompt, "《piano》" in prompt, "24秒" in prompt,
                           system == describe.MUSIC_SYSTEM), ("ds", True, False, True, True, True))
    expect("temp wav removed", [n for n in os.listdir(describe._temp_dir()) if n.startswith("kaju_music_")], [])

    b2, _ = make(report=RuntimeError("分析程序退出码 1"))
    expect("engine fails → empty", await b2._describer.hear_music(src, "x", ""), "")
    b3, _ = make(answer=asyncio.TimeoutError())
    expect("llm fails → empty", await b3._describer.hear_music(src, "x", ""), "")

    # 私聊发 mp3：先回一句"听一下"，[File Attachment] 换成听感 + 歌词，系统提示加音乐说明，记进 kaju_docs_read
    mp3 = os.path.join(TMP, "青山绿野.mp3")
    import shutil
    shutil.copy(src, mp3)  # 扩展名是 mp3、内容是 wav：PyAV 按内容认，照样能读
    b, prompts = make(stt_text="")
    comp = File(name="青山绿野.mp3", file=mp3)
    ev = AstrMessageEvent(messages=[comp])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[File Attachment: name 青山绿野.mp3, path x]"))
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("music file part", (len(texts), texts[0].startswith("[Music file: 青山绿野.mp3] 24秒的音频，佳树从头听完了。"),
                               music.LISTEN_MARK in texts[0], "没转写出能用的歌词" in texts[0]), (1, True, True, True))
    expect("music note in prompt", "【关于音乐】" in req.system_prompt, True)
    expect("wait line sent", len(ev.sent) == 1 and any(x in ev.sent[0] for x in ("听", "等我")), True)
    read = ev.get_extra("kaju_docs_read")
    expect("docs_read kind", (read[0]["kind"], read[0]["name"]), ("音乐", "青山绿野.mp3"))
    # 同一个文件再发一次：缓存，不再跑引擎
    await b.describe_media(AstrMessageEvent(messages=[comp]), ProviderRequest("SYS"))
    expect("music file cached", len(b._fake_runs), 1)

    # 有人声：带上转写
    b, _ = make(stt_text="向夜晚奔去 沉溺其中")
    out = await b._describer.music_file(File(name="夜.flac", file=mp3), AstrMessageEvent())
    expect("lyrics included", ("里面的人声（自动转写" in out, "向夜晚奔去" in out), (True, True))
    # 引擎和转写都没成
    b, _ = make(report=RuntimeError("x"))
    out = await b._describer.music_file(File(name="坏.mp3", file=mp3), AstrMessageEvent())
    expect("nothing heard", out.startswith("没听成：听了，但没听出什么"), True)
    out = await b._describer.music_file(File(name="没了.mp3", file=os.path.join(TMP, "gone.mp3")), AstrMessageEvent())
    expect("missing music file", out.startswith("没听成：文件没能下载下来"), True)
    # 关掉音乐：只转写
    b, _ = make(stt_text="一段说话", cfg={"music": False})
    out = await b._describer.music_file(File(name="录音.m4a", file=mp3), AstrMessageEvent())
    expect("music off → speech only", (music.LISTEN_MARK in out, "一段说话" in out, b._fake_runs), (False, True, []))

    # 视频：对方提到歌才听音乐；没提到不跑引擎
    clip = os.path.join(TMP, "clip.mp4")
    make_clip(clip, 8)
    b, _ = make()
    b._describer.senses._video_captions = _fake_captions
    ev = AstrMessageEvent(text="这首歌好听吗", messages=[Video(file=clip, path=clip), Plain("这首歌好听吗")])
    req = ProviderRequest("SYS")
    req.extra_user_content_parts.append(TextPart("[Video Attachment: name clip.mp4, path x]"))
    await b.describe_media(ev, req)
    texts = [p.text for p in req.extra_user_content_parts]
    expect("video + music", (len(b._fake_runs), music.LISTEN_MARK in texts[0], "【关于音乐】" in req.system_prompt),
           (1, True, True))
    b, _ = make()
    b._describer.senses._video_captions = _fake_captions
    ev = AstrMessageEvent(text="哈哈哈", messages=[Video(file=clip, path=clip), Plain("哈哈哈")])
    req = ProviderRequest("SYS")
    await b.describe_media(ev, req)
    expect("video no music", (len(b._fake_runs), "【关于音乐】" in req.system_prompt), (0, False))


async def _fake_captions(frames, duration, umo, title):
    return "一个人在弹钢琴"


def make_clip(path, seconds=8, fps=10):
    """PyAV 现做一段小视频，声音是上面那段合成钢琴。"""
    import av
    from PIL import Image as PILImage

    rate = 44100
    with wave.open(src) as w:
        pcm = np.frombuffer(w.readframes(int(seconds * rate)), dtype=np.int16)
    c = av.open(path, "w")
    vs = c.add_stream("mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 160, 120, "yuv420p"
    aus = c.add_stream("aac", rate=rate, layout="mono")
    for i in range(seconds * fps):
        for p in vs.encode(av.VideoFrame.from_image(PILImage.new("RGB", (160, 120), (40, 40, 40 + i)))):
            c.mux(p)
    for p in vs.encode():
        c.mux(p)
    for k in range(0, len(pcm), 1024):
        fr = av.AudioFrame.from_ndarray(pcm[k:k + 1024].reshape(1, -1), format="s16", layout="mono")
        fr.sample_rate = rate
        for p in aus.encode(fr):
            c.mux(p)
    for p in aus.encode():
        c.mux(p)
    c.close()


asyncio.run(plugin_tests())
music.run_engine = REAL_ENGINE


# ------------------------------------------------------------------ live
async def live(paths):
    """真引擎 + 真模型：她听到的感觉 → 她用真人设回复 3 次 → 情绪判断（只打印）。"""
    from openai import AsyncOpenAI

    appraise = importlib.import_module("kaju_core.heart.appraise")
    core = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
    cfg = json.load(open(os.path.join(core, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src_ = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src_.get("key") or src_.get("api_key")
    cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src_["api_base"])

    async def chat(system, user):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        r = await cli.chat.completions.create(model="deepseek-flash", messages=msgs)
        return r.choices[0].message.content.strip()

    ctx = Context({"timezone": "Asia/Shanghai"})
    ctx.providers = {"ds": type("P", (), {"provider_config": {"id": "ds"}})()}

    async def llm_generate(chat_provider_id, prompt, system_prompt=None):
        return LLMResponse(await chat(system_prompt or "", prompt))

    ctx.llm_generate = llm_generate
    b = kb.KajuBasics(ctx, {"media": {"music_data_dir": MODELS}})
    from kaju_core.senses import localstt  # 跟机器人一样：本地 SenseVoice 听人声
    sv = localstt.SenseVoice(r"D:\JiashuBot\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
                             r"D:\JiashuBot\models\silero_vad.onnx")

    class LiveSTT:
        async def get_text(self, audio_url=""):
            return await asyncio.to_thread(sv.transcribe, audio_url)

    ctx.stt = LiveSTT()
    persona = open(os.path.join(os.environ.get("KAJU_DATA") or r"D:\JiashuBot\kaju_data", "self", "persona", "persona.txt"), encoding="utf-8").read()
    for path in paths:
        name = os.path.basename(path)
        wav = os.path.join(TMP, "live.wav")
        music.to_wav(path, wav, 600)
        t0 = time.time()
        rep = music.run_engine(wav, MODELS)
        print(f"\n######## {name}（引擎 {time.time() - t0:.1f}s）\n--- 给模型看的测量\n{music.pick(rep)}")
        t0 = time.time()
        stem = os.path.splitext(name)[0]
        note = await b._describer.music_file(File(name=stem + ".mp3", file=path), AstrMessageEvent())
        print(f"--- 她拿到的（含引擎、转写共 {time.time() - t0:.1f}s）\n{note}")
        part = f"[Music file: {stem}.mp3] {note}"
        user = f"[发言人：晴川（QQ 111111111）] 听听这首\n{part}\n\n<system_reminder>{kb.MUSIC_NOTE}</system_reminder>"
        for r in await asyncio.gather(*(chat(persona, user) for _ in range(3))):
            print("佳树：", r.replace("\n", " / "))
        prompt = appraise.build_prompt(who="晴川", is_owner=True, level="", place="私聊", context=part,
                                       said="听听这首", reply="", shared=[f"《{name}》（音乐）：{note}"])
        print("--- 情绪判断", appraise.parse(await chat(appraise.system_prompt(), prompt)))


if "--live" in sys.argv:
    asyncio.run(live([a for a in sys.argv[1:] if a != "--live"]))
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
