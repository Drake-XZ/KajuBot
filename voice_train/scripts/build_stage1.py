"""阶段一训练数据：AI 腔草稿 → 真人原话。

来源：
  - LCCC（清华 thu-coai，MIT，微博对话，已清洗）验证集+测试集：downloads/lccc/*.jsonl.gz
  - 兄长大人和佳树的私聊里他说的话（memorix 的 transcript，只读）
做法：DeepSeek 把每条真人回复"改成 AI 腔"当草稿（意思不变、更长更周到），训练目标是真人原话；
约一成样本草稿 = 原话（教它本来像人的就别动）。
输出 data/stage1.jsonl：{src, ctx:[...], draft, target}
不打印 API key。
用法：python -I build_stage1.py [--lccc 3000] [--limit N]
"""
import argparse
import asyncio
import gzip
import json
import os
import random
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
OWNER = "111111111"

from openai import AsyncOpenAI  # noqa: E402

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"])
sem = asyncio.Semaphore(12)

# 给机器人下指令、或者没法当"聊天回复"学的话
COMMAND = re.compile(r"^/|帮我|帮忙|搜一下|搜搜|查一下|查查|看一眼|看看群|发(一?条)?说说|存(一?下|起来)|记住|提醒我|表情包|能看到|看得到|看得见|"
                     r"重置|测试|test|\[图片\]|\[视频\]|\[文件|http|www\.|<Quoted|\[Image|\[Video|\[File", re.I)
REMIND = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)


def lccc_samples(n, rng):
    rows = []
    for f in ("lccc_base_valid.jsonl.gz", "lccc_base_test.jsonl.gz"):
        with gzip.open(os.path.join(ROOT, "downloads", "lccc", f), "rt", encoding="utf-8") as fh:
            for line in fh:
                d = [t.replace(" ", "") for t in json.loads(line)]
                if len(d) < 2:
                    continue
                reply = d[-1]
                if not (2 <= len(reply) <= 50) or re.search(r"http|@|转发|回复", reply):
                    continue
                rows.append({"src": "lccc", "ctx": [("甲" if (len(d) - 1 - i) % 2 else "乙") + "：" + t[:120]
                                                   for i, t in enumerate(d[:-1])][-4:],
                             "target": reply})
    rng.shuffle(rows)
    return rows[:n]


def owner_samples():
    p = os.path.join(CORE, "data", "plugin_data", "astrbot_plugin_memorix", "scopes", "aiocqhttp", "metadata", "metadata.db")
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    msgs = [(r, REMIND.sub("", c or "").strip()) for r, c in db.execute(
        "select role, content from transcript_messages where session_id=? order by position", (OWNER,))]
    out = []
    for i, (role, text) in enumerate(msgs):
        if role != "user" or i == 0 or msgs[i - 1][0] != "assistant":
            continue
        text = re.sub(r"^\[发言人：[^\]]*\]\s*", "", text).strip()
        if not (2 <= len(text) <= 80) or COMMAND.search(text):
            continue
        ctx = []
        for r, t in msgs[max(0, i - 4):i]:
            t = re.sub(r"^\[发言人：[^\]]*\]\s*", "", t).replace("\n", " / ")
            ctx.append(("佳树" if r == "assistant" else "他") + "：" + t[:120])
        out.append({"src": "owner", "ctx": ctx, "target": text})
    return out


AIFY = """下面是一段聊天的上下文，和某个真人发的一条回复。
请写出一个典型的 AI 聊天机器人在同样位置、想表达同样意思时会怎么回。

要求：
- 意思、立场、事实和真人回复一致，不要加新的事实或新的观点；真人问了什么，草稿也问同样的事
- 但要有 AI 腔：{level}
- 只输出这条 AI 回复本身，不加引号、不解释"""

LEVELS = [
    "稍微有一点：比原话长一些、说得更完整，带一两个“呢/呀/哦”",
    "明显的 AI 腔：长度是原话的两三倍，先接一句对方的话或总结对方的意思，用逗号把几句串起来，句尾爱带“呢/呀/哦”",
    "很重的 AI 腔：长度是原话的三到五倍，解释原因、表示理解、再加一句关心或追问，书面一点、周到一点，用逗号串长句",
]


async def aify(sample, rng):
    level = rng.choice(LEVELS)
    ctx = "\n".join(sample["ctx"])
    async with sem:
        for attempt in range(3):
            try:
                r = await ds.chat.completions.create(
                    model="deepseek-flash", temperature=0.9,
                    messages=[{"role": "system", "content": AIFY.format(level=level)},
                              {"role": "user", "content": f"上下文：\n{ctx}\n\n真人回复：{sample['target']}"}])
                return (r.choices[0].message.content or "").strip()
            except Exception:  # noqa: BLE001
                await asyncio.sleep(3 + attempt * 3)
    return ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lccc", type=int, default=3000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "stage1.jsonl"))
    a = ap.parse_args()
    rng = random.Random(20261103)
    samples = lccc_samples(a.lccc, rng) + owner_samples()
    if a.limit:
        rng.shuffle(samples)
        samples = samples[:a.limit]
    print(f"samples: lccc {sum(s['src']=='lccc' for s in samples)}, owner {sum(s['src']=='owner' for s in samples)}", flush=True)
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
