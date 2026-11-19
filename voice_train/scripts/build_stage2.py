"""阶段二训练数据：模仿佳树的 AI 草稿 → 原作里佳树真正说的话。

来源：D:\\Persona\\Kaju\\out\\kaju_all.jsonl（941 句，台版 01–08 + SSS + 8.5/09），
上下文取小说原文里这句前面最近的 3 行（src = 文件:行号，已核对 300/300 对得上）。
草稿：DeepSeek 写"一个模仿温水佳树的 AI 聊天机器人会怎么说同样的意思"（自称佳树、叫兄长大人，但 AI 腔）；
约一成样本草稿 = 原话。输出 data/stage2.jsonl：{src, ctx, draft, target, emotion}
不打印 API key。
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
KAJU = r"D:\Persona\Kaju"

from openai import AsyncOpenAI  # noqa: E402

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
sem = asyncio.Semaphore(12)

AIFY = """下面是小说《败犬女主太多了！》里的一段前文，和温水佳树（温水和彦的妹妹）接着说的一句原话。
请写出一个"模仿温水佳树的 AI 聊天机器人"在同样位置、想表达同样意思时会怎么说。

要求：
- 意思、立场、称呼和原话一致（原话叫谁就叫谁，自称佳树），不要加新的事实；原话问了什么，草稿也问同样的事
- 但要有 AI 腔：{level}
- 只输出这句话本身，不加引号、不加动作描写、不解释"""

LEVELS = [
    "稍微有一点：比原话长一些、说得更完整，句尾带“哦/呀/呢”",
    "明显的 AI 腔：长度是原话的两三倍，几乎每句末尾都带“哦/呀/呢/啦”，用逗号把几句串起来，先接一句对方的话",
    "很重的 AI 腔：长度是原话的三到五倍，解释原因、表示理解、再加一句关心或追问，用逗号串长句，每句都带语气词",
]


def context(lines, n, k=3):
    out = []
    i = n - 2  # n is 1-based; the line itself is lines[n-1]
    while i >= 0 and len(out) < k:
        t = lines[i].strip()
        if t:
            out.append(t[:100])
        i -= 1
    return list(reversed(out))


async def aify(sample, rng):
    level = rng.choice(LEVELS)
    ctx = "\n".join(sample["ctx"])
    async with sem:
        for attempt in range(3):
            try:
                r = await ds.chat.completions.create(
                    model="deepseek-flash", temperature=0.9,
                    messages=[{"role": "system", "content": AIFY.format(level=level)},
                              {"role": "user", "content": f"前文：\n{ctx}\n\n佳树的原话：{sample['target']}"}])
                return (r.choices[0].message.content or "").strip().strip("「」“”\"")
            except Exception:  # noqa: BLE001
                await asyncio.sleep(3 + attempt * 3)
    return ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "stage2.jsonl"))
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(KAJU, "out", "kaju_all.jsonl"), encoding="utf-8")]
    cache = {}
    samples = []
    for r in rows:
        f, n = r["src"].rsplit(":", 1)
        p = os.path.join(KAJU, "txt", f)
        if p not in cache:
            cache[p] = open(p, encoding="utf-8").read().split("\n")
        line = re.sub(r"\s+", " ", r["line"]).strip()
        if len(line) < 2:
            continue
        samples.append({"src": "kaju", "ctx": context(cache[p], int(n)), "target": line, "emotion": r.get("emotion", "")})
    rng = random.Random(20261103)
    if a.limit:
        rng.shuffle(samples)
        samples = samples[:a.limit]
    keep = [rng.random() < 0.1 for _ in samples]
    drafts = await asyncio.gather(*(aify(s, random.Random(i)) if not k else asyncio.sleep(0, result=None)
                                    for i, (s, k) in enumerate(zip(samples, keep))))
    n = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for s, k, d in zip(samples, keep, drafts):
            if k:
                d = s["target"]
            if not d:
                continue
            f.write(json.dumps(dict(s, draft=d, same=bool(k)), ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} -> {a.out}")


asyncio.run(main())
