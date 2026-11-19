r"""对比小测试第 3 步：同一条素材，两边各出"她看完留下的东西"，再用同一个写回复的办法各回一句。

    <venv>\Scripts\python.exe -I run.py old     旧流程（现在线上的：截帧描述 + 声音转写 + 音乐测量）→ results\old.json
    <venv>\Scripts\python.exe -I run.py new     全模态模型（画面和声音一起进）→ results\new.json
    <venv>\Scripts\python.exe -I run.py reply   两边各写回复 → results\replies.json

旧流程：她当时看过并存下来的就直接用（记忆轻重的珍藏），当时没真看的（只看了页面）或没存的，用现在的感官重看一遍。
全模态的密钥：D:\JiashuBot\kaju_data\accounts\omni.json（兄长自己填，脚本不打印）。
两边写回复用的是同一份人设、同一句提醒，只有"她看完留下的东西"不一样。回复是 DeepSeek 直接写的，没过线上的要点卡和本地写手，只用来比素材。
"""
import asyncio
import base64
import json
import os
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SETUP)
os.environ.setdefault("STUB_DATA", tempfile.mkdtemp())
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
MEDIA, SMALL, OUT = os.path.join(HERE, "media"), os.path.join(HERE, "media", "small"), os.path.join(HERE, "results")
KEYFILE = r"D:\JiashuBot\kaju_data\accounts\omni.json"
SAMPLES = json.load(open(os.path.join(HERE, "samples.json"), encoding="utf-8"))
if len(sys.argv) > 2:  # run.py new 07 → 只跑 id 以 07 开头的
    SAMPLES = [s for s in SAMPLES if s["id"].startswith(tuple(sys.argv[2:]))]
os.makedirs(OUT, exist_ok=True)

from openai import AsyncOpenAI  # noqa: E402


def load(name):
    p = os.path.join(OUT, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save(name, data):
    json.dump(data, open(os.path.join(OUT, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def deepseek():
    cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    return AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])


def shelf():
    s = json.load(open(r"D:\JiashuBot\kaju_data\self\memory_weight\state.json", encoding="utf-8"))["shelf"]
    return list(s.values()) if isinstance(s, dict) else s


def persona() -> str:
    db = sqlite3.connect("file:" + os.path.join(CORE, "data", "data_v4.db") + "?mode=ro", uri=True)
    return db.execute("select system_prompt from personas where persona_id='default'").fetchone()[0]


# ------------------------------------------------------------ 旧流程
async def run_old():
    from kaju_core.senses import localstt, perceive

    ds = deepseek()
    media_cfg = json.load(open(os.path.join(CORE, "data", "config", "astrbot_plugin_kaju_basics_config.json"),
                               encoding="utf-8-sig")).get("media", {})
    sv = localstt.SenseVoice(r"D:\JiashuBot\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
                             r"D:\JiashuBot\models\silero_vad.onnx")

    async def see(client, model, path, prompt):
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        r = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}])
        return (r.choices[0].message.content or "").strip()

    local = AsyncOpenAI(api_key="ollama", base_url="http://127.0.0.1:11435/v1", timeout=300)

    class Live(perceive.Models):  # 跟线上一样：视频画面本地 qwen3-vl，图片动图 DeepSeek，动脑子 DeepSeek，耳朵本地 SenseVoice
        async def look(self, image_path, prompt, who):
            return await see(local, "qwen3-vl:4b-instruct", image_path, prompt)

        async def look_image(self, image_path, prompt, who):
            return await see(ds, "deepseek-flash", image_path, prompt)

        async def think(self, prompt, system, who, model="", timeout=150):
            r = await ds.chat.completions.create(model="deepseek-flash", messages=[
                {"role": "system", "content": system}, {"role": "user", "content": prompt}])
            return (r.choices[0].message.content or "").strip()

        def ears(self, who):
            async def hear(wav):
                return await asyncio.to_thread(sv.transcribe, wav)
            return None if sv.check() else hear

    senses = perceive.Senses(Live(), lambda: media_cfg)
    items, res = shelf(), load("old.json")
    for s in SAMPLES:
        if s["id"] in res:
            continue
        it = items[s["shelf"]] if "shelf" in s else {}
        content = str(it.get("content") or "")
        watched = "的视频。" in content or "看完了" in content  # 当时真看了（不是只看了页面）
        if watched and not s.get("audio_only"):
            res[s["id"]] = {"source": "当时存下的", "text": content, "said": it.get("said") or "",
                            "reply_then": it.get("reply") or "", "feeling_then": it.get("feeling") or ""}
        else:
            src = os.path.join(SMALL if s.get("audio_only") else MEDIA, s["id"] + (".mp3" if s.get("audio_only") else s["ext"]))
            p = await senses.perceive(src, "test", listen_music=True)
            head = content.split("标签：")[0] if content else ""
            res[s["id"]] = {"source": "现在的感官重看", "text": (head + " " + p.facts).strip(), "said": it.get("said") or "",
                            "reply_then": it.get("reply") or "", "feeling_then": it.get("feeling") or ""}
        save("old.json", res)
        print(s["id"], res[s["id"]]["source"], len(res[s["id"]]["text"]), "字")


# ------------------------------------------------------------ 全模态
FEEL_PROMPT = """有人给一个叫佳树的初三女生发了这个{what}。请你当她，像一个人坐下来从头{verb}到尾那样——画面和声音是一起进来的——
然后写下{verb}的时候心里发生了什么，而不是把内容讲一遍。
只输出一个 JSON 对象，不要别的字：
{{
 "facts": "这是什么、大概发生了什么。150 字以内。只在别人问到细节时才用得上。",
 "moments": [{{"t": "分:秒", "what": "这一刻画面和声音合在一起是什么（一句）", "feel": "{verb}到这里心里的感觉（一句大白话，用“我”）", "strength": 1}}],
 "arc": "从头到尾心情是怎么走的（一句）",
 "after": "{verb}完心里留下的那点东西（一两句大白话，用“我”，不要复述内容）",
 "mood": {{"valence": 0, "energy": 0}}
}}
说明：strength 是 1 到 3；valence（高不高兴）和 energy（激不激动）是 -2 到 2。
要求：
- 感觉是对内容本身的：画面、动作、声音、音乐、里面的人和事让你怎么样。不要写“谁发给我”“他为什么发”“我要怎么回他”这些，也不要编她做了什么（存下来、再放一遍之类）。
- 每条素材的感觉应该不一样：好笑就是好笑，难过就是难过，吵就是吵，看不懂就是看不懂，没什么感觉就老实说没什么感觉。不要每条都写害羞、脸热。
- moments 只挑真正有感觉的 2 到 6 个时刻，没感觉的地方不要硬写。
- 没看到、没听到的不要编；声音说听起来的感觉，不用术语；不要写“截图”“帧”这类词。{extra}"""


async def run_new():
    k = json.load(open(KEYFILE, encoding="utf-8")) if os.path.exists(KEYFILE) else {}
    if not (k.get("api_key") and k.get("base_url")):
        sys.exit(f"还没有全模态模型的密钥：请在 {KEYFILE} 里填 api_key 和 base_url")
    cli = AsyncOpenAI(api_key=k["api_key"], base_url=k["base_url"], timeout=600)
    model = k.get("model") or "qwen3.8-omni-flash"
    res = load("new.json")
    for s in SAMPLES:
        if s["id"] in res:
            continue
        audio = bool(s.get("audio_only"))
        path = os.path.join(SMALL, s["id"] + (".mp3" if audio else s["ext"]))
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        if audio:
            part = {"type": "input_audio", "input_audio": {"data": "data:;base64," + b64, "format": "mp3"}}
            what, verb, extra = "一首歌", "听", ""
        elif s["ext"] == ".gif":  # 动图当成一段无声小视频给（转成了 mp4；直接给 gif 它只看第一帧）
            b64 = base64.b64encode(open(os.path.join(SMALL, s["id"] + ".mp4"), "rb").read()).decode()
            part = {"type": "video_url", "video_url": {"url": "data:;base64," + b64}}
            what, verb, extra = "动图", "看", "\n这是一张循环播放的动图，没有声音（这里连着放了两遍）。"
        else:
            part = {"type": "video_url", "video_url": {"url": "data:;base64," + b64}}
            what, verb, extra = "视频", "看", ""
        text, usage = "", None
        try:
            stream = await cli.chat.completions.create(
                model=model, modalities=["text"], stream=True, stream_options={"include_usage": True},
                messages=[{"role": "user", "content": [
                    part, {"type": "text", "text": FEEL_PROMPT.format(what=what, verb=verb, extra=extra)}]}])
            async for ch in stream:
                if ch.choices and ch.choices[0].delta.content:
                    text += ch.choices[0].delta.content
                if ch.usage:
                    usage = ch.usage.model_dump()
        except Exception as e:  # noqa: BLE001
            print("FAIL", s["id"], type(e).__name__, str(e)[:300])
            continue
        raw = text[text.find("{"):text.rfind("}") + 1]
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            data = {"raw": text}
        res[s["id"]] = {"percept": data, "usage": usage}
        save("new.json", res)
        print(s["id"], "ok", (usage or {}).get("prompt_tokens"), "→", (usage or {}).get("completion_tokens"), "tokens")


# ------------------------------------------------------------ 回复
REMIND = "回他的时候说你自己看完的感受，像平时聊天那样两三句，不要把内容讲一遍。"


def felt_text(p: dict) -> str:
    if "raw" in p:
        return p["raw"]
    ms = "\n".join(f"- {m.get('t', '')} {m.get('what', '')}：{m.get('feel', '')}" for m in p.get("moments") or [])
    return (f"你看的时候心里的感觉：\n{ms}\n整个下来：{p.get('arc', '')}\n看完心里留下的：{p.get('after', '')}\n"
            f"（备忘，他问到细节才用：{p.get('facts', '')}）")


async def run_reply():
    ds, sys_prompt = deepseek(), persona()
    old, new, res = load("old.json"), load("new.json"), load("replies.json")
    for s in SAMPLES:
        sid = s["id"]
        if sid in res or sid not in old or sid not in new:
            continue
        said = old[sid]["said"] or "佳树看看这个"
        kind = "动图" if s["ext"] == ".gif" else ("歌" if s.get("audio_only") else "视频")
        out = {}
        for side, material in (("old", f"[你刚看完的{kind}: {old[sid]['text']}]"),
                               ("new", f"[你刚看完的{kind}] {felt_text(new[sid]['percept'])}")):
            user = f"{said}\n<system_reminder>\n兄长大人发来一个{kind}。{material}\n{REMIND}\n</system_reminder>"
            out[side] = []
            for _ in range(2):
                r = await ds.chat.completions.create(model="deepseek-flash", messages=[
                    {"role": "system", "content": sys_prompt}, {"role": "user", "content": user}])
                out[side].append((r.choices[0].message.content or "").strip())
        res[sid] = out
        save("replies.json", res)
        print(sid, "ok")


if __name__ == "__main__":
    asyncio.run({"old": run_old, "new": run_new, "reply": run_reply}[sys.argv[1]]())
