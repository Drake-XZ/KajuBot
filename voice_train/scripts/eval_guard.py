"""用兄长大人第三轮标注检验重说核对（rewrite.GUARD，读 bot_setup 里的源码）。
data/review3_split.json：style/feeling 应该放行，content 应该拦下。每条跑 N 次（默认 3）。
用法：python -I eval_guard.py [N]   不打印 API key。
"""
import asyncio
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import rewrite  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
sem = asyncio.Semaphore(12)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3

items = {it["id"]: it for it in json.load(open(os.path.join(ROOT, "data", "review3_items.json"), encoding="utf-8"))}
split = json.load(open(os.path.join(ROOT, "data", "review3_split.json"), encoding="utf-8"))
cls = {i: c for c in ("style", "feeling", "content") for i in split[c]}


async def one(it, text):
    async with sem:
        r = await ds.chat.completions.create(model="deepseek-flash", temperature=0.3, messages=[
            {"role": "system", "content": rewrite.GUARD},
            {"role": "user", "content": rewrite.guard_prompt(it["ctx"][-1].split("：", 1)[-1], it["draft"], text, it["to"], it["ctx"])}])
        return rewrite.guard_bad(r.choices[0].message.content)


async def main():
    jobs = []
    for p in glob.glob(os.path.join(ROOT, "data", "review3_labels", "labels", "*.json")):
        i = os.path.basename(p)[:-5]
        raw = json.load(open(p, encoding="utf-8"))
        v = raw.get("data", raw)
        text = re.sub(r"[（(][^）)]*[）)]", "", v.get("text") or "").strip()
        if i in cls and text:
            jobs.append((i, text))
    res = await asyncio.gather(*[asyncio.gather(*[one(items[i], t) for _ in range(N)]) for i, t in jobs])
    tally = {}
    for (i, _), outs in sorted(zip(jobs, res), key=lambda x: (cls[x[0][0]], int(x[0][0][1:]))):
        bad = sum(b for b, _ in outs)
        c = cls[i]
        want_bad = c == "content"
        t = tally.setdefault(c, [0, 0])
        t[0] += (bad if want_bad else N - bad)
        t[1] += N
        mark = "" if (bad > N / 2) == want_bad else "  ← 不对"
        print(f"{c:7} {i:>4} 拦 {bad}/{N}{mark}  {'；'.join(w for b, w in outs if b)[:50]}")
    for c, (ok, n) in tally.items():
        print(f"{c}: {'该拦的拦住' if c == 'content' else '该放的放行'} {ok}/{n} = {ok / n:.0%}")


asyncio.run(main())
