r"""用真的全模态模型跑一遍 kaju_core.senses 里的新路（源码，不是已部署的那份）。
    <venv>\Scripts\python.exe -I live_core.py media\07_funny_dog.mp4 [标题]
"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"

from kaju_core.senses import music, perceive  # noqa: E402


class NoLocal(perceive.Models):
    async def look(self, image_path, prompt, who):
        return "（本地流程：这里是画面描述）"

    async def think(self, prompt, system, who, model="", timeout=150):
        import json as _j
        from openai import AsyncOpenAI
        cfg = _j.load(open(r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data\cmd_config.json", encoding="utf-8-sig"))
        src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
        key = src.get("key") or src.get("api_key")
        cli = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
        r = await cli.chat.completions.create(model="deepseek-flash", messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return r.choices[0].message.content or ""


async def main():
    path, title = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    s = perceive.Senses(NoLocal(), lambda: {"video_transcribe": False, "music": False})
    s.about_her = lambda: "【她喜欢的】\n- 喜欢：温水佳树相关的二创、V.W.P 的歌\n- 有点感兴趣：搞笑视频"
    if music.is_audio(path):
        async def op(mb):
            return path
        text = await s.music_file(path, os.path.basename(path), op, "live")
    else:
        async def op():
            return path
        text = await s.watch(path, op, "live", title=title)
    print(text)
    for p in s.take_felt("live"):
        print("\n→ 心情：", p["emotion"], p["intensity"], "|", p["cause"], "| topic", p["topic"], p["kind"], p["genre"], p["media"],
              "| voice:", p["voice"], "|", p["secs"], "s", p["usage"])
        print("  moments emo:", [(m["emo"], m["strength"]) for m in p["moments"]])

asyncio.run(main())
