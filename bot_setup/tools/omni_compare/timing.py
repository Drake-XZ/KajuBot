r"""量一下全模态模型现在回一条要多久（用 kaju_core.senses.omni 的提示词）。
    <venv>\Scripts\python.exe -I timing.py media\small\01_mv_jixie.mp4 low [标题]
"""
import asyncio
import base64
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"

from openai import AsyncOpenAI  # noqa: E402

from kaju_core.senses import omni  # noqa: E402


async def main():
    path, effort = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else ""
    k = omni.key()
    cli = AsyncOpenAI(api_key=k["api_key"], base_url=k["base_url"], timeout=600, max_retries=0)
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    extra = {} if effort == "default" else {"reasoning_effort": effort}
    t, first, think_first, text, think, u = time.time(), None, None, "", 0, None
    stream = await cli.chat.completions.create(
        model=k["model"], modalities=["text"], stream=True, stream_options={"include_usage": True},
        messages=[{"role": "user", "content": [{"type": "video_url", "video_url": {"url": "data:;base64," + b64}},
                                               {"type": "text", "text": omni.build_prompt("video", title, "")}]}], **extra)
    async for ch in stream:
        if ch.choices:
            d = ch.choices[0].delta
            r = getattr(d, "reasoning_content", None)
            if r:
                think_first = think_first or time.time() - t
                think += len(r)
            if d.content:
                first = first or time.time() - t
                text += d.content
        if ch.usage:
            u = ch.usage
    print(f"effort={effort}: 总共 {time.time() - t:.1f}s，开始思考 {think_first and round(think_first, 1)}s，"
          f"开始出字 {first and round(first, 1)}s，思考 {think} 字，in {u and u.prompt_tokens} out {u and u.completion_tokens}")
    print(text[:300])

asyncio.run(main())
