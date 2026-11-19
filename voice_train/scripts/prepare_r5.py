r"""第 5 轮（2026-11-16）：只改第 4 轮的数据，修“丢要点”。

第 4 轮考试：话顺了（成话 0.55→0.72），但漏答两种卡都比线上多。原因：r4 金句的卡上 27% 的要点他没说
（规划器的“事实”他挑着说），写手学成“要说到的可以不说”。第 3 轮金句只有 3%。
修法：卡上“要说到的”= 回复里真说了的；没说的挪进“背景”（可用可不用）。和规划器以后的分工一致：
要说到的 = 这一轮必须说到的，背景 = 用得上就用。

  split  r4 的金句 / KTO 好 全部问 Gemini 哪几条真说了；原作复习里程序粗查（两字片段盖住 < 30%）有没说到的，也问 → r5\
  pairs  同卡对子按新卡重写（prepare_r4 的做法：线上写手写 3 遍，有毛病的优先，每条最多 2 对，权重 2）
  all    split → pairs
之后：round_train.py data --round 5（拼训练集），训练和考试用 run_round4.py 的做法（把 N 改成 5，或照它另写）。
用法（AstrBot 的 Python；pairs 要 Ollama 开着）：python -I -X utf8 scripts\prepare_r5.py split|pairs|all
"""
import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402
import prepare_r4 as p4  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
R4, OUT = rt.rdir(4), rt.rdir(5)

SAID = """下面是交给佳树的材料里“要说到的”几条（编了号），和她真正说出口的话。
逐条判断：她这句话里有没有说到这一条的意思（换了说法、说得简略也算说到；只是沾边、没说出这件事本身不算）。
只输出 JSON：{"说到的": [编号, ...]}"""


def _n(t):
    return re.sub(r"[\s，。！？、,.!?~…；;：:“”\"（）()/]", "", t or "")


def _bg(t):
    t = _n(t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def points(card):
    m = re.search(r"^要说到的：(.*)$", card, re.M)
    v = (m.group(1) if m else "").strip()
    return [] if v in ("", "无") else [p.strip() for p in v.split("；") if p.strip()]


def maybe_unsaid(card, target):
    t = _bg(target)
    return any(_bg(p) and len(_bg(p) & t) / len(_bg(p)) < 0.3 for p in points(card))


def rebuild(card, keep, move):
    out, has_bg = [], False
    for line in card.splitlines():
        if line.startswith("要说到的："):
            line = "要说到的：" + ("；".join(keep) or "无")
        elif line.startswith("背景："):
            has_bg = True
            old = [x for x in line[3:].split("；") if x.strip()]
            line = "背景：" + "；".join(move + old)
        out.append(line)
    if move and not has_bg:  # 背景放在心情行前（没有心情行就放最后）
        i = next((k for k, x in enumerate(out) if x.startswith("心情：")), len(out))
        out.insert(i, "背景：" + "；".join(move))
    return "\n".join(out)


async def split_one(card, text, sem):
    ps = points(card)
    if not ps:
        return card, []
    user = "要说到的：\n" + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(ps)) + "\n\n佳树说的：\n" + text
    v = await p4.ask(SAID, user, "说到的", sem)
    if not isinstance(v, list):
        return card, None  # 判不出来：原样留着
    said = {int(x) for x in v if str(x).strip().isdigit()}
    keep = [p for i, p in enumerate(ps) if i + 1 in said]
    move = [p for i, p in enumerate(ps) if i + 1 not in said]
    return (rebuild(card, keep, move), move) if move else (card, [])


async def do_split():
    import train_keys  # noqa: F401
    sem = asyncio.Semaphore(6)
    os.makedirs(OUT, exist_ok=True)
    stats = {}

    async def run(rows, text_key, name, only_flagged):
        todo = [r for r in rows if not only_flagged or maybe_unsaid(r["card"], r[text_key])]
        res = await asyncio.gather(*[split_one(r["card"], r[text_key], sem) for r in todo])
        moved = fail = 0
        for r, (c, mv) in zip(todo, res):
            if mv is None:
                fail += 1
                continue
            if mv:
                moved += 1
                r["card"], r["moved_to_bg"] = c, mv
        stats[name] = {"条数": len(rows), "问了": len(todo), "挪了": moved, "判不出": fail}
        return rows

    gold = await run(rt.jl(os.path.join(R4, "gold.jsonl")), "target", "金句", False)
    kto = await run(rt.jl(os.path.join(R4, "kto.jsonl")), "text", "KTO好", False)
    extra = await run(rt.jl(os.path.join(R4, "extra_stage2.jsonl")), "target", "原作复习", True)
    for r in extra:
        r["id"] = r["id"].replace("-v6", "-v6s")
    rt.wjl(os.path.join(OUT, "gold.jsonl"), gold)
    rt.wjl(os.path.join(OUT, "kto.jsonl"), kto)
    rt.wjl(os.path.join(OUT, "extra_stage2.jsonl"), extra)
    left = sum(len(points(g["card"])) for g in gold)
    print("挪进背景：", json.dumps(stats, ensure_ascii=False), f"；金句卡上剩要点 {left}", flush=True)
    for g in gold:
        if g.get("moved_to_bg"):
            print("  ", g["id"], "→ 背景：", "；".join(g["moved_to_bg"])[:110], flush=True)


async def do_pairs(samples):
    p4.OUT = OUT  # 用 prepare_r4 的做法，读写 r5
    await p4.do_pairs(samples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["split", "pairs", "all"])
    ap.add_argument("--samples", type=int, default=3)
    a = ap.parse_args()
    if a.cmd in ("split", "all"):
        asyncio.run(do_split())
    if a.cmd in ("pairs", "all"):
        asyncio.run(do_pairs(a.samples))


if __name__ == "__main__":
    main()
