r"""图片和动图给谁看：DeepSeek（现在看图的）、本地 qwen3-vl（现在看群里动图的）、Gemini（中转平台）。
同一张图 / 同一张动图拼图、同一句提示，各看一遍；Gemini 另外把动图当小视频看一遍。
素材：她自己的表情包（文件夹名就是这张图的意思）+ 那张"鞠躬后比中指"的动图。
    <venv>\Scripts\python.exe -I image_eyes.py <输出目录>
结果写到 <输出目录>\image_eyes.json，拼图存成 <输出目录>\<编号>.jpg 方便人看。
"""
import asyncio
import base64
import glob
import json
import os
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["KAJU_DATA"] = r"D:\JiashuBot\kaju_data"
CORE = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"

from openai import AsyncOpenAI  # noqa: E402

from kaju_core.senses import omni, perceive  # noqa: E402

OUT = sys.argv[1]
PACK = r"D:\JiashuBot\kaju_data\self\meme_manager\packs\kaju_memes\memes"
VIDEO_PROMPT = ("这是一张循环播放的动图（没有声音，这里连着放了两遍）。用中文描述：谁在做什么、动作怎么变、最后停在什么样子，"
                "手势、表情这些细节看清楚再写，看不清就说看不清；能看清的字原样写出来。80 字以内，不用 markdown。")


def gemini(k, mime, data, prompt):
    body = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}, {"text": prompt}]}]}
    req = urllib.request.Request(k["base_url"].rstrip("/") + f"/v1beta/models/{k['model']}:generateContent", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "python-client", "x-goog-api-key": k["api_key"],
                                  "Authorization": "Bearer " + k["api_key"]})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if not p.get("thought")).strip()


async def main():
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(PACK, "*", "*"))) + [os.path.join(HERE, "media", "10_gif_bow.gif")]
    cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
    src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
    key = src.get("key") or src.get("api_key")
    ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"], timeout=120)
    local = AsyncOpenAI(api_key="ollama", base_url="http://127.0.0.1:11435/v1", timeout=300)
    gk = omni.gemini_key()
    tmp = tempfile.mkdtemp()
    done = os.path.join(OUT, "image_eyes.json")
    res = json.load(open(done, encoding="utf-8")) if os.path.exists(done) else []

    async def img(cli, model, b64, mime, prompt):
        r = await cli.chat.completions.create(model=model, messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + b64}}]}])
        return (r.choices[0].message.content or "").strip()

    for n, f in enumerate(files):
        is_gif = f.lower().endswith(".gif")
        label = os.path.basename(os.path.dirname(f)) if PACK in f else "鞠躬后比中指"
        if any(r["n"] == n for r in res):
            continue
        sheet = perceive._gif_sheet(f, 1536, 8) if is_gif else None
        if is_gif and sheet is None:  # 不会动的"动图"：线上也是当普通图看
            import io
            from PIL import Image
            buf = io.BytesIO()
            Image.open(f).convert("RGB").save(buf, "PNG")
            data, mime, prompt, is_gif = buf.getvalue(), "image/png", perceive.IMAGE_PROMPT, False
        elif is_gif:
            data, mime, prompt = sheet, "image/jpeg", perceive.IMAGE_PROMPT + perceive.GIF_NOTE
        else:
            data, mime, prompt = open(f, "rb").read(), "image/png", perceive.IMAGE_PROMPT
        open(os.path.join(OUT, f"{n:02d}.{'jpg' if is_gif else 'png'}"), "wb").write(data)
        b64 = base64.b64encode(data).decode()
        row = {"n": n, "label": label, "gif": is_gif, "file": os.path.basename(f)}
        arms = [("deepseek", lambda: img(ds, "deepseek-flash", b64, mime, prompt)),
                ("local", lambda: img(local, "qwen3-vl:4b-instruct", b64, mime, prompt)),
                ("gemini", lambda: asyncio.to_thread(gemini, gk, mime, data, prompt))]
        if is_gif:
            mp4 = os.path.join(tmp, f"{n}.mp4")
            omni.gif_to_mp4(f, mp4)
            arms.append(("gemini_video", lambda: asyncio.to_thread(gemini, gk, "video/mp4", open(mp4, "rb").read(), VIDEO_PROMPT)))
        for name, fn in arms:
            t = time.time()
            try:
                out = await fn()
            except Exception as e:  # noqa: BLE001
                out = f"ERR {type(e).__name__} {str(e)[:100]}"
            row[name] = {"text": out, "secs": round(time.time() - t, 1)}
        res.append(row)
        json.dump(res, open(os.path.join(OUT, "image_eyes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n#{n:02d} [{label}] {'动图' if is_gif else '图片'}")
        for name, _ in arms:
            print(f"  {name:13s} {row[name]['secs']:5.1f}s  {row[name]['text'][:150]!r}")


asyncio.run(main())
