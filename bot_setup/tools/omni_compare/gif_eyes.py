r"""动图给谁看更准、更快：DeepSeek（现在线上）、本地 qwen3-vl、全模态（不思考 / low）。各看 3 遍。
    <venv>\Scripts\python.exe -I gif_eyes.py media\10_gif_bow.gif
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"

from openai import AsyncOpenAI  # noqa: E402

from kaju_core.senses import omni, perceive  # noqa: E402

PROMPT = perceive.IMAGE_PROMPT + perceive.GIF_NOTE
VIDEO_PROMPT = ("这是一张循环播放的动图（没有声音，这里连着放了两遍）。用中文描述：谁在做什么、动作怎么变、最后停在什么样子，"
                "手势、表情这些细节看清楚再写，看不清就说看不清；能看清的字原样写出来。80 字以内，不用 markdown。")


async def main():
    gif = sys.argv[1]
    tmp = tempfile.mkdtemp()
    sheet = os.path.join(tmp, "sheet.jpg")
    open(sheet, "wb").write(perceive._gif_sheet(gif, 1536, 8))
    mp4 = os.path.join(tmp, "g.mp4")
    omni.gif_to_mp4(gif, mp4)
    print("sheet:", sheet)
    cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
    local = AsyncOpenAI(api_key="ollama", base_url="http://127.0.0.1:11435/v1", timeout=300)
    b64 = base64.b64encode(open(sheet, "rb").read()).decode()

    async def img(cli, model):
        r = await cli.chat.completions.create(model=model, messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}])
        return (r.choices[0].message.content or "").strip()

    async def om(effort):
        text, _ = await omni.ask(mp4, "video", VIDEO_PROMPT, effort, 120)
        return text.strip()

    for name, fn in (("deepseek 拼图", lambda: img(ds, "deepseek-flash")), ("本地 qwen3-vl 拼图", lambda: img(local, "qwen3-vl:4b-instruct")),
                     ("全模态 不思考", lambda: om("none")), ("全模态 low", lambda: om("low"))):
        for i in range(3):
            t = time.time()
            try:
                out = await fn()
            except Exception as e:  # noqa: BLE001
                out = f"ERR {type(e).__name__} {str(e)[:80]}"
            print(f"[{name}] {time.time() - t:.1f}s 中指={'中指' in out} 食指={'食指' in out} | {out[:110]!r}")

asyncio.run(main())
