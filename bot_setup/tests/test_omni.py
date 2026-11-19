r"""全模态这条路（kaju_core/senses/omni.py）：解析、给她的那段话、压小、走不了就退回本地流程、感受在回复前交给心情。
    <venv>\Scripts\python.exe -I tests\test_omni.py
"""
import asyncio
import importlib
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from kaju_core import paths  # noqa: E402
from kaju_core.senses import omni, perceive  # noqa: E402

fails = []


def fresh_health():
    """每一段先清掉成绩：前一段里 relay 挂过会被冷却、挪到最后（2026-11-14 health.py），不清就影响后面的顺序。"""
    from kaju_core.senses import health
    health._state = {"accounts": {}, "slots": {}}
    health._mtime = 0.0
    try:
        os.remove(health._path())
    except OSError:
        pass


def expect(name, got, want):
    if got != want:
        fails.append(name)
        print("FAIL", name, "\n  got ", got, "\n  want", want)


GOOD = json.dumps({"facts": "小狗站起来跳舞", "moments": [
    {"t": "0:06", "what": "狗后腿站起来甩爪子", "feel": "我笑出声了", "emo": "开心", "strength": 3},
    {"t": "0:08", "what": "歌还在唱", "feel": "有点滑稽", "emo": "不存在的感受", "strength": 9}],
    "arc": "从纳闷到笑", "after": "那只狗傻得让人开心", "emotion": "开心", "intensity": 2, "cause": "小狗跳舞太好笑",
    "topic": "小狗的视频", "kind": "", "genre": "搞笑视频", "voice": "我想再看一遍那只狗", "about": "看到小狗跳舞的视频"},
    ensure_ascii=False)


def make_clip(path, seconds=3, fps=10):
    import av
    import numpy as np
    from PIL import Image

    c = av.open(path, "w")
    vs = c.add_stream("mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 320, 240, "yuv420p"
    aus = c.add_stream("aac", rate=16000, layout="mono")
    for i in range(seconds * fps):
        img = Image.new("RGB", (320, 240), (int(255 * i / (seconds * fps)), 40, 40))
        for p in vs.encode(av.VideoFrame.from_image(img)):
            c.mux(p)
    for p in vs.encode():
        c.mux(p)
    pcm = (np.sin(2 * np.pi * 440 * np.arange(seconds * 16000) / 16000) * 8000).astype(np.int16)
    for k in range(0, len(pcm), 1024):
        fr = av.AudioFrame.from_ndarray(pcm[k:k + 1024].reshape(1, -1), format="s16", layout="mono")
        fr.sample_rate = 16000
        for p in aus.encode(fr):
            c.mux(p)
    for p in aus.encode():
        c.mux(p)
    c.close()


class Models(perceive.Models):
    def __init__(self):
        self.looks = 0

    async def look(self, image_path, prompt, who):
        self.looks += 1
        return "红色越来越深的画面"

    async def think(self, prompt, system, who, model="", timeout=150):
        return "笔记"


async def main():
    # 解析：乱七八糟的回答不要；数字夹到 0–3
    expect("parse junk", omni.parse("我看完了，很好笑"), None)
    p = omni.parse("好的：\n" + GOOD + "\n以上")
    expect("parse fields", (p["emotion"], p["intensity"], len(p["moments"]), p["moments"][1]["strength"]), ("开心", 2, 2, 3))
    text = omni.render({**p}, "9秒", "video")
    expect("render keeps only the strongest moment", ("我笑出声了" in omni.render({**p}, "9秒", "video", 1),
                                                     "有点滑稽" in omni.render({**p}, "9秒", "video", 1)), (True, False))
    expect("render order", (text.index("最有感觉的地方") < text.index("看完心里留下的") < text.index("备忘"),
                            "画面和声音是一起的" in text), (True, True))
    expect("shift times", (omni._shift("1:05", 360, 720), omni._shift("8:24", 480, 722), omni._shift("乱写", 360, 720),
                           omni._shift("30:00", 360, 720)), ("7:05", "8:24", "6:00", "6:00"))
    expect("render audio", omni.render({**p}, "3分", "audio").startswith("3分的音频，佳树从头听完了。"), True)
    prompt = omni.build_prompt("video", "小狗做饭", "- 喜欢：猫的视频")
    expect("prompt has title/tastes/emotions",
           ("《小狗做饭》" in prompt, "猫的视频" in prompt, "开心" in prompt, "{what}" in prompt), (True, True, True, False))

    # 没填密钥：这条路不开
    expect("no key", (omni.key(), omni.available({})), ({}, False))
    tmp = tempfile.mkdtemp()
    clip = os.path.join(tmp, "clip.mp4")
    make_clip(clip)
    models = Models()
    cfg = {"video_grid": 2, "video_transcribe": False}
    s = perceive.Senses(models, lambda: cfg)

    async def opener():
        return clip

    old = await s.watch("k1", opener, "chat1")
    expect("no key → local flow", ("红色越来越深" in old, models.looks > 0, s.take_felt("chat1")), (True, True, []))

    # 填了密钥：先走全模态，感受记一份等心情来取；同一个视频不重复问
    json.dump({"api_key": "sk-test", "base_url": "http://x/v1"}, open(paths.account("omni.json"), "w"))
    omni._key_cache = (0.0, {})
    expect("key loaded", (omni.key().get("model"), omni.available({}), omni.available({"omni": False})),
           ("qwen3.8-omni-flash", True, False))

    # 两家：先问 Gemini，它出错或超时就问 qwen；gemini.json 里 "enabled": false = 只用 qwen
    real_ask, asked = omni.ask, []

    async def gem_ok(k, file_path, kind, prompt, timeout, thinking=""):
        asked.append(("gem", k["model"]))
        return GOOD, {"in": 7, "out": 3}

    async def gem_bad(k, file_path, kind, prompt, timeout, thinking=""):
        asked.append(("gem", k["model"]))
        raise asyncio.TimeoutError()

    async def qwen_ok(k, file_path, kind, prompt, effort, timeout):
        asked.append(("qwen", k["model"], effort))
        return GOOD, {"in": 9, "out": 4}

    omni._ask_openai = qwen_ok
    expect("only qwen filled", ([k["api"] for k in omni.keys()], (await omni.ask(clip, "video", "p"))[1]["by"]), (["openai"], "qwen3.8-omni-flash"))
    gem_file = paths.account("gemini.json")
    json.dump({"api_key": "sk-g", "base_url": "http://relay", "model": ""}, open(gem_file, "w"))
    omni._gemini_cache = (0.0, {})
    asked.clear()
    omni._ask_gemini = gem_ok
    fresh_health()
    expect("gemini first", ([k["api"] for k in omni.keys()], (await omni.ask(clip, "video", "p"))[1], asked),
           (["gemini", "openai"], {"in": 7, "out": 3, "by": "gemini-3.8-flash"}, [("gem", "gemini-3.8-flash")]))
    asked.clear()
    omni._ask_gemini = gem_bad
    fresh_health()
    expect("gemini fails → qwen", ((await omni.ask(clip, "video", "p", "low"))[1]["by"], asked),
           ("qwen3.8-omni-flash", [("gem", "gemini-3.8-flash"), ("qwen", "qwen3.8-omni-flash", "low")]))
    # 备用中转（2026-11-12）：主中转 → 备用中转 → qwen；地址带 /v1beta 的去掉
    bak_file = paths.account("gemini_backup.json")
    json.dump({"api_key": "sk-b", "base_url": "https://backup/v1beta/", "model": "gemini-3.8-flash-high"}, open(bak_file, "w"))
    omni._backup_cache = (0.0, {})
    expect("backup in order", [(k["api"], k["model"], k["base_url"]) for k in omni.keys()],
           [("gemini", "gemini-3.8-flash", "http://relay"), ("gemini", "gemini-3.8-flash-high", "https://backup"), ("openai", "qwen3.8-omni-flash", omni.key()["base_url"])])
    asked.clear()

    async def gem_main_bad(k, file_path, kind, prompt, timeout, thinking=""):
        asked.append(("gem", k["model"]))
        if k["base_url"] == "http://relay":
            raise RuntimeError("All available accounts exhausted")
        return GOOD, {"in": 5, "out": 2}
    omni._ask_gemini = gem_main_bad
    fresh_health()
    expect("main relay fails → backup relay", ((await omni.ask(clip, "video", "p"))[1]["by"], asked),
           ("gemini-3.8-flash-high", [("gem", "gemini-3.8-flash"), ("gem", "gemini-3.8-flash-high")]))
    looked, real_gl = [], omni._gemini_look

    def gl(k, mime, data, prompt, timeout, thinking=""):
        looked.append(k["base_url"])
        if k["base_url"] == "http://relay":
            raise RuntimeError("502")
        return "一张图"
    omni._gemini_look = gl
    fresh_health()
    img = os.path.join(os.environ["STUB_DATA"], "dot.png")
    from PIL import Image
    Image.new("RGB", (4, 4)).save(img)
    expect("look: main relay fails → backup relay", (await omni.look(img, "p"), looked), ("一张图", ["http://relay", "https://backup"]))
    omni._gemini_look = real_gl
    # 11-13：一条 key 可以写自己的 timeout（hardysapi 15 秒），只比默认短时才用
    expect("key timeout", [omni.key_timeout({"timeout": 15}, 20), omni.key_timeout({"timeout": 15}, 10),
                           omni.key_timeout({}, 20), omni.key_timeout({"timeout": "x"}, 20)], [15.0, 10, 20, 20])
    e = omni._entry({"api_key": "k", "base_url": "https://h", "format": "openai", "timeout": 15, "look_last": True}, "m", "gemini")
    expect("entry keeps timeout / look_last", (e.get("timeout"), e.get("look_last")), (15, True))
    real_gk = omni.gemini_keys
    omni.gemini_keys = lambda: [{"name": "hardys", "look_last": True}, {"name": "aigo"}, {"name": "daitu"}]
    expect("look order: look_last goes last", [k["name"] for k in omni.look_keys()], ["aigo", "daitu", "hardys"])
    omni.gemini_keys = real_gk
    os.remove(bak_file)
    omni._backup_cache = (0.0, {})
    # 一个文件放所有 key（2026-11-12 起 gemini_keys.json）：有它就只看它，从上往下；空的、关掉的跳过
    lst = paths.account("gemini_keys.json")
    json.dump({"keys": [{"name": "a", "api_key": "sk-1", "base_url": "https://one/v1beta", "model": ""},
                        {"name": "空的", "api_key": "", "base_url": "", "model": ""},
                        {"name": "关掉", "api_key": "sk-x", "base_url": "https://off", "enabled": False},
                        {"name": "c", "api_key": "sk-3", "base_url": "https://three/", "model": "gemini-4-argon-low"}]}, open(lst, "w"))
    omni._list_cache = (0.0, [])
    expect("list file wins, in order", [(k["base_url"], k["model"]) for k in omni.gemini_keys()],
           [("https://one", "gemini-3.8-flash"), ("https://three", "gemini-4-argon-low")])
    expect("gemini_key = first of list", omni.gemini_key()["api_key"], "sk-1")
    expect("keys(): list then qwen", [k["api"] for k in omni.keys()], ["gemini", "gemini", "openai"])
    json.dump({"enabled": False, "keys": [{"api_key": "sk-1", "base_url": "https://one"}]}, open(lst, "w"))
    os.utime(lst, (2, 2))
    expect("whole list switched off", omni.gemini_keys(), [])
    # "format": "openai"（只认 OpenAI 格式的中转）：出卡、看图用它，看视频听歌跳过它
    json.dump({"keys": [{"name": "o", "api_key": "sk-o", "base_url": "https://oa/v1", "model": "gemini-3-flash", "format": "openai"},
                        {"name": "n", "api_key": "sk-n", "base_url": "https://na", "model": ""}]}, open(lst, "w"))
    os.utime(lst, (3, 3))
    expect("openai entry kept for text/look", [(k["base_url"], k["fmt"]) for k in omni.gemini_keys()],
           [("https://oa", "openai"), ("https://na", "native")])
    expect("openai entry skipped for video/audio", [k["base_url"] for k in omni.keys()], ["https://na", omni.key()["base_url"]])
    sent = {}

    def fake_chat(k, messages, timeout, extra=None):
        sent.update(k=k["base_url"], messages=messages, extra=extra)
        return "好"
    real_oc, omni._openai_chat = omni._openai_chat, fake_chat
    expect("openai text call", (omni._gemini_text(omni.gemini_keys()[0], "sys", "u", "low", 5), sent["messages"][0]["role"], sent["extra"]),
           ("好", "system", {"reasoning_effort": "low"}))
    omni._gemini_look(omni.gemini_keys()[0], "image/png", b"\x89PNG", "看图", 5)
    expect("openai look call", sent["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"), True)
    omni._openai_chat = real_oc
    os.remove(lst)
    omni._list_cache = (0.0, [])
    expect("no list file → old gemini.json", [k["base_url"] for k in omni.gemini_keys()], ["http://relay"])
    json.dump({"api_key": "sk-g", "base_url": "http://relay", "enabled": False}, open(gem_file, "w"))
    os.utime(gem_file, (1, 1))
    expect("gemini switched off", [k["api"] for k in omni.keys()], ["openai"])
    os.remove(gem_file)
    omni._gemini_cache = (0.0, {})
    sound = omni.parse(GOOD.replace('"arc"', '"sound": "鼓点一下一下的，我听着想跟着晃", "arc"', 1))
    expect("sound kept and shown", (sound["sound"], "声音听起来的感觉：鼓点" in omni.render(sound, "9秒", "video"), p["sound"],
                                     "声音听起来的感觉" in omni.render({**p}, "9秒", "video")), ("鼓点一下一下的，我听着想跟着晃", True, "", False))
    omni.ask = real_ask

    # 图片、动图：填了 gemini.json 就先给 Gemini 看；它没看成换原来的眼睛；fallback=False 时没看成就抛出去
    from PIL import Image as PILImage
    png, gif2 = os.path.join(tmp, "p.png"), os.path.join(tmp, "g.gif")
    PILImage.new("RGB", (64, 48), (200, 30, 30)).save(png)
    frames = [PILImage.new("RGB", (64, 48), (40 * i, 0, 255 - 40 * i)) for i in range(6)]
    frames[0].save(gif2, save_all=True, append_images=frames[1:], duration=120, loop=0)
    expect("image bytes", (omni._image_bytes(png)[0], omni._image_bytes(gif2)[0]), ("image/png", "image/jpeg"))
    seen, real_look = [], omni.look

    async def gem_look(path, prompt, timeout=40, task="image"):
        seen.append((path.endswith(".jpg"), "动图" in prompt))
        return "Gemini 看到的"

    async def gem_blind(path, prompt, timeout=40, task="image"):
        raise asyncio.TimeoutError()

    omni.look = gem_look
    before = models.looks
    expect("no gemini key → old eyes", (await s.image(png, "c"), models.looks - before, seen), ("红色越来越深的画面", 1, []))
    try:
        await s.image(png, "c", fallback=False)
        expect("gemini only without key raises", "no raise", "raise")
    except RuntimeError:
        pass
    json.dump({"api_key": "sk-g", "base_url": "http://relay"}, open(gem_file, "w"))
    omni._gemini_cache = (0.0, {})
    before = models.looks
    expect("gemini sees still and gif", (await s.image(png, "c"), await s.image(gif2, "c"), seen, models.looks - before),
           ("Gemini 看到的", "Gemini 看到的", [(False, False), (True, True)], 0))
    cfg["gemini_eyes"] = False
    expect("switched off in settings", await s.image(png, "c"), "红色越来越深的画面")
    cfg.pop("gemini_eyes")
    omni.look = gem_blind
    gif_eyes = []

    async def special(p, pr):
        gif_eyes.append("动图" in pr)
        return "专门看动图的"

    expect("gemini fails → gif model, then the usual eyes", (await s.image(gif2, "c", look_gif=special), await s.image(png, "c", look_gif=special), gif_eyes),
           ("专门看动图的", "红色越来越深的画面", [True]))
    try:
        await s.image(png, "c", fallback=False)
        expect("gemini only raises on failure", "no raise", "raise")
    except asyncio.TimeoutError:
        pass
    omni.look = real_look
    os.remove(gem_file)
    omni._gemini_cache = (0.0, {})
    calls = []

    async def fake_ask(file_path, kind, prompt, effort="low", timeout=150):
        calls.append((os.path.exists(file_path), kind, effort))
        return GOOD, {"in": 100, "out": 50}

    omni.ask = fake_ask
    s.about_her = lambda: "- 喜欢：猫的视频"
    before = models.looks
    got = await s.watch("k2", opener, "chat1", title="小狗做饭")
    expect("omni text", ("我笑出声了" in got, "备忘" in got, models.looks == before, calls),
           (True, True, True, [(True, "video", "low")]))
    await s.watch("k2", opener, "chat1", title="小狗做饭")
    expect("cached, asked once", len(calls), 1)
    felt = s.take_felt("chat1")
    expect("felt queued once", (len(felt), felt[0]["title"], s.take_felt("chat1")), (1, "小狗做饭", []))
    seen = await s.perceive(clip, "chat2")
    expect("perceive goes the same way", (seen.ok, "最有感觉的地方" in seen.facts), (True, True))

    # 模型出错 / 回答没法用 / 太长：退回本地流程
    async def boom(*a, **k):
        raise RuntimeError("503")

    omni.ask = boom
    got = await s.watch("k3", opener, "chat3")
    expect("error → local flow", ("红色越来越深" in got, s.take_felt("chat3")), (True, []))

    async def junk(*a, **k):
        return "抱歉我看不了", {}

    omni.ask = junk
    expect("junk → local flow", "红色越来越深" in await s.watch("k4", opener, "chat3"), True)
    efforts = []

    async def slow_then_quick(file_path, kind, prompt, effort="low", timeout=150):
        efforts.append(effort)
        if effort != "none":
            raise asyncio.TimeoutError()
        return GOOD, {"in": 1, "out": 1}

    omni.ask = slow_then_quick
    got = await s.watch("k6", opener, "chat4")
    expect("timeout → ask again without thinking", (efforts, "我笑出声了" in got, s.take_felt("chat4")[0]["effort"]),
           (["low", "none"], True, "none"))
    omni.ask = fake_ask
    # 长视频：分段看，各段的时刻换成整条里的时间，整体感受再合成一次；段数太多才退回本地流程
    cfg.update(omni_max_minutes=0.01, omni_segment_minutes=0.03)
    notes = []

    async def seg_ask(file_path, kind, prompt, effort="low", timeout=150):
        import av
        with av.open(file_path) as c:
            notes.append((round(c.duration / av.time_base, 1), "第 1 段" in prompt, "第 2 段" in prompt))
        return GOOD, {"in": 10, "out": 5}

    async def merge(prompt, system, who, model="", timeout=150):
        return '{"arc": "先笑后静", "after": "整条看完还想笑", "emotion": "开心", "intensity": 3, "cause": "狗", "voice": "", "about": ""}'

    omni.ask = seg_ask
    models.think = merge
    got = await s.watch("k5", opener, "chat5")
    felt = s.take_felt("chat5")[0]
    expect("long video in 2 segments", (len(notes), all(1.2 <= n[0] <= 1.9 for n in notes), felt["segments"], felt["after"], felt["intensity"]),
           (2, True, "2/2", "整条看完还想笑", 3))
    expect("moment times shifted", ([m["t"] for m in felt["moments"]], "整条看完还想笑" in got),
           (["0:00", "0:00", "0:01", "0:01"], True))  # 段里写的时间超出这一段的长度：按这一段的开头算
    cfg["omni_max_segments"] = 1
    omni.ask = fake_ask
    expect("too many segments → local flow", "红色越来越深" in await s.watch("k5b", opener, "chat3"), True)
    cfg.update(omni_max_minutes=10, omni_segment_minutes=6, omni_max_segments=6)

    # 压小：大文件压到限制以内，声音还在
    import av
    big = omni.LIMIT_BYTES
    omni.LIMIT_BYTES = 30_000
    try:
        send, temp = omni.prepare(clip, "video", tmp, 600)
        with av.open(send) as c:
            expect("shrunk", (temp, os.path.getsize(send) < os.path.getsize(clip), len(c.streams.audio)), (True, True, 1))
        os.remove(send)
        mp3, temp = omni.prepare(clip, "audio", tmp, 600)
        expect("audio → mp3", (temp, mp3.endswith(".mp3"), os.path.getsize(mp3) > 0), (True, True, True))
        omni.LIMIT_BYTES = 200
        try:
            omni.prepare(clip, "video", tmp, 600)
            expect("too big raises", "no raise", "TooBig")
        except omni.TooBig:
            pass
    finally:
        omni.LIMIT_BYTES = big
    from PIL import Image
    gif = os.path.join(tmp, "a.gif")
    shots = [Image.new("RGB", (121, 91), (40 * i, 0, 0)) for i in range(5)]
    shots[0].save(gif, save_all=True, append_images=shots[1:], duration=100, loop=0)
    omni.gif_to_mp4(gif, os.path.join(tmp, "a.mp4"))
    with av.open(os.path.join(tmp, "a.mp4")) as c:
        n = sum(1 for _ in c.decode(video=0))
        expect("gif → mp4 two loops", (n, c.streams.video[0].width), (10, 120))

    # 心情：看的时候的那几下先推动心情，整体感受进事件；这一轮的事后判断不再算内容
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.star import Context
    kh = importlib.import_module("kaju_heart.main")
    cls = next(v for k, v in vars(kh).items()
               if isinstance(v, type) and hasattr(v, "feel_watched") and v.__module__ == kh.__name__)
    h = cls(Context({"timezone": "Asia/Shanghai"}), {"inner": {"store_memorix": False}})
    m0 = dict(h.mood_now())
    ev = AstrMessageEvent(sender="111111111", messages=[])
    out = await h.feel_watched({**p, "title": "小狗做饭", "media": "video"}, ev)
    m1 = h.mood_now()
    expect("mood moved before reply", (out["emotion"], m1["joy"] > m0["joy"], ev.get_extra("_kaju_felt")), ("开心", True, True))
    expect("event logged as content", h._state["events"][-1]["src"], "content")
    await h.terminate()

    print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
    sys.exit(1 if fails else 0)


asyncio.run(main())
