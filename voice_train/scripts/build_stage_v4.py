"""v4 训练数据：好的成品文字 → DeepSeek 从成品里抽要点卡 → 训练"卡片 → 成品"。

成品文字只用不带 AI 腔的来源（DeepSeek 写的理想回复不再当答案）：
  lccc   LCCC 真人聊天 26000（pick_lccc_v4.py 挑的）              阶段一
  owner  兄长大人自己发的私聊 320（旧 stage1 里的，他=我）           阶段一
  novel  原作佳树台词 940，每句抽 2 张不同的卡                     阶段二
  gold   兄长大人亲手挑过 / 改过的 102 条，每条抽 3 张不同的卡      阶段二
抽卡用 bot_setup\\plugins\\kaju_style\\card.py 的提示词和格式（线上抽卡用的是同一份）。
可以断点续跑：已经抽过的 (src, id, n) 跳过。
用法：python -I build_stage_v4.py [--only lccc,owner,novel,gold] [--limit N] [--conc 16]
      → data/v4_cards.jsonl  {src, id, n, kind, to, ctx, target, card, copy}
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time

from openai import AsyncOpenAI

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "v4_cards.jsonl")
CORE = r"C:\Users\18525\.astrbot_launcher\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core"
sys.path.insert(0, r"D:\JiashuBot\bot_setup\kaju_core\voice")
import card  # noqa: E402

cfg = json.load(open(os.path.join(CORE, "data", "cmd_config.json"), encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = src.get("key")
ds = AsyncOpenAI(api_key=key[0] if isinstance(key, list) else key, base_url=src["api_base"], timeout=60)
MEME = re.compile(r"&&[^&\n]*&&")
TEMPS = [0.3, 0.8, 1.0]  # 第 n 张卡的温度：同一句话抽出来的卡措辞不一样


def load(name):
    return [json.loads(l) for l in open(os.path.join(DATA, name), encoding="utf-8") if l.strip()]


def tidy(t):
    t = MEME.sub("", t or "").replace(" / ", "\n")
    return "\n".join(ln.strip() for ln in t.split("\n") if ln.strip())


def jobs(only):
    out = []
    if "lccc" in only:
        for r in load("v4_lccc_pick.jsonl"):
            out.append({"src": "lccc", "id": r["id"], "n": 0, "kind": "聊天", "to": "对方", "ctx": r["ctx"], "target": r["target"]})
    if "owner" in only:
        for i, r in enumerate(x for x in load("stage1.jsonl") if x["src"] == "owner"):
            ctx = [re.sub(r"^他：", "我：", c) for c in r["ctx"]]
            out.append({"src": "owner", "id": f"o{i + 1}", "n": 0, "kind": "私聊", "to": "佳树", "ctx": ctx[-6:],
                        "target": tidy(r["target"])})
    if "novel" in only:
        for i, r in enumerate(load("stage2.jsonl")):
            for n in range(2):
                out.append({"src": "novel", "id": f"n{i + 1}", "n": n, "kind": "当面", "to": "", "ctx": r["ctx"][-4:],
                            "target": tidy(r["target"])})
    if "gold" in only:
        for r in load("stage2b_gold.jsonl"):
            kind = {"group": "群聊", "novel": "当面"}.get(r["src"], "私聊")
            last = r["ctx"][-1] if r["ctx"] else ""
            to = "" if kind == "当面" else (last.split("：", 1)[0] if "：" in last else "兄长大人")
            if to == "佳树":
                to = ""
            for n in range(3):
                out.append({"src": "gold", "id": r["id"], "n": n, "kind": kind, "to": to, "ctx": r["ctx"][-6:],
                            "target": tidy(r["target"])})
    return out


async def extract(job, sem):
    msgs = [{"role": "system", "content": card.EXTRACT},
            {"role": "user", "content": card.extract_prompt(job["ctx"], job["target"], job["kind"], job["to"])}]
    async with sem:
        for attempt in range(4):
            try:
                # 不让 flash 先思考：思考每张卡要 1000～2000 token，卡片本身只有 50 个左右，质量一样
                r = await ds.chat.completions.create(model="deepseek-flash", temperature=TEMPS[job["n"]], messages=msgs,
                                                     extra_body={"thinking": {"type": "disabled"}})
                c = card.parse(r.choices[0].message.content)
                if c:
                    return c
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    print("  失败", job["src"], job["id"], type(e).__name__, str(e)[:60])
                await asyncio.sleep(2 + 4 * attempt)
    return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="lccc,owner,novel,gold")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--conc", type=int, default=16)
    a = ap.parse_args()
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                done.add((r["src"], r["id"], r["n"]))
    todo = [j for j in jobs(a.only.split(",")) if (j["src"], j["id"], j["n"]) not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"已有 {len(done)}，这次要抽 {len(todo)} 张卡")
    sem = asyncio.Semaphore(a.conc)
    t0, n_ok, n_bad = time.time(), 0, 0
    with open(OUT, "a", encoding="utf-8") as f:
        async def one(job):
            nonlocal n_ok, n_bad
            c = await extract(job, sem)
            if not c:
                n_bad += 1
                return
            text = card.render(c, job["kind"], job["to"])
            row = dict(job, card=text, copy=round(card.copy_ratio(job["target"], text), 2))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_ok += 1
            if n_ok % 200 == 0:
                f.flush()
                el = time.time() - t0
                print(f"  {n_ok}/{len(todo)}  {el / 60:.1f} 分钟，预计还要 {el / n_ok * (len(todo) - n_ok) / 60:.0f} 分钟，失败 {n_bad}")
        await asyncio.gather(*(one(j) for j in todo))
    print(f"完成 {n_ok}，失败 {n_bad}，用了 {(time.time() - t0) / 60:.1f} 分钟 -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
