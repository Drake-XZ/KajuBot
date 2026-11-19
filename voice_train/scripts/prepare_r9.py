r"""第 9 轮“人格对子”（2026-11-18 兄长：人格还是交给本地写手、不教记忆，只训人格 / 说话方式；“先做 30 对小试”；AGENT.md 第十节）。

想法：第 8 轮把卡写空、逼写手自己补人格，结果意思和佳树味都掉了。这次同一张卡、同样的意思和事实，
  好的 = 佳树真说的那句（原作原句 / 兄长认可的话，照旧是 K 的答案），
  差的 = 照同一张卡写的“平淡版”（普通人的说法，事实、顺序、长短都一样，只是没有她的口气和态度）
         和少量“演过头版”（满屏自称佳树、夸张撒娇——治 r8 反复自称的毛病）。
偏好训练只学两句之间的差别；事实两边都有，不会被当成要学的东西。差的只当反例，不当答案。
恋爱话题照旧去掉（佳树是初三学生）。

  pair  [--pilot N]   从 r7k 的 K stage2（句子卡）挑，出平淡版 + 演过头版 → data\rounds_v4\r9\pairs.jsonl
                      （跑过的跳过；model_router tasks.card 动态挑；usage_meter 估钱）
  show  [--n N]       打印几条
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r9.py pair --pilot 30 ；show --n 30
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
R9 = os.path.join(VT, "data", "rounds_v4", "r9")
OUT = os.path.join(R9, "pairs.jsonl")
from prepare_r8_pack import romance  # noqa: E402  第 8 轮加宽过的恋爱词表

FLAT = """下面是一段对话的局面、交给写手的卡，和温水佳树（初三女生）在这一轮真正说出口的那句回复。
要做训练用的“对照句”：意思和事实完全一样，只是说法不同。只输出 JSON：
{"平淡": "……", "过头": "……"}

平淡：一个没有特别性格的普通人会这么回——平平常常、礼貌、直接。
- 意思、事实、名字、数字、顺序都和佳树那句一样，不加、不减、不改；长短和佳树那句差不多（多一两成、少一两成都行）；
- 去掉的是她这个人的东西：自称“佳树”改成“我”，“兄长大人”这类称呼改成普通的叫法或不叫，
  不要她的口头禅、语气词、对兄长的态度、小心思、小得意、撒娇；
- 不要写成客服 / AI 助手的腔调，就是普通人的平淡说法；如果佳树那句有好几行（用 / 分开），平淡也分成同样几行。
过头：同样的意思和事实，但模仿过了头——一句里反复自称“佳树”、反复叫“兄长大人”、感叹和撒娇堆得太满，读起来做作。
- 只是兄妹间的撒娇和做作，不写恋爱、亲密的内容；意思和事实同样不加、不减、不改。"""


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def user_of(r):
    return (f"卡：\n{r['card']}\n\n前面最后两行：\n" + "\n".join((r.get("ctx") or [])[-2:]) +
            f"\n\n佳树的回复：\n{r['target']}")


def parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    flat, over = str(v.get("平淡") or "").strip(), str(v.get("过头") or "").strip()
    return (flat, over) if flat and over else None


def pick(pilot):
    rows = [r for r in jl(os.path.join(R7K, "k_data", "stage2.jsonl")) if not romance(r)]
    if not pilot:
        return rows
    rng = random.Random(909)
    by = {}
    for r in rows:
        by.setdefault(r["src"], []).append(r)
    want = {"novel": pilot * 2 // 3, "curated": pilot // 6, "curated_old": pilot - pilot * 2 // 3 - pilot // 6}
    return [r for src, rs in by.items() for r in rng.sample(rs, min(len(rs), want.get(src, 0)))]


async def cmd_pair(pilot):
    import train_keys  # noqa: F401  KAJU_DATA、bot_setup 进 sys.path
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    rows = pick(pilot)
    os.makedirs(R9, exist_ok=True)
    done = {(d["id"], d["src"]) for d in (jl(OUT) if os.path.exists(OUT) else []) if d.get("flat")}
    todo = [r for r in rows if (r["id"], r["src"]) not in done]
    print(f"要出对照句 {len(todo)} 条（出过的 {len(done)}）", flush=True)
    sem = asyncio.Semaphore(4)
    n_ok = [0]

    async def one(r):
        async with sem:
            t0 = time.time()
            try:
                out, k = await omni.text(FLAT, user_of(r), timeout=40)
                v = parse(out)
                row = {"id": r["id"], "src": r["src"], "flat": v and v[0], "over": v and v[1],
                       "raw": None if v else (out or "")[:300], "key": k}
            except Exception as e:  # noqa: BLE001
                row = {"id": r["id"], "src": r["src"], "flat": None, "error": f"{type(e).__name__}: {e}"[:200]}
            row["ms"] = int((time.time() - t0) * 1000)
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_ok[0] += bool(row["flat"])
            if n_ok[0] % 100 == 0 and row["flat"]:
                print(f"  好了 {n_ok[0]}", flush=True)

    await asyncio.gather(*[one(r) for r in todo])
    u = usage_meter.report(os.path.join(R9, f"usage-pair-{time.strftime('%H%M')}.json"))
    print(f"这批好 {n_ok[0]} / {len(todo)}；估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)


def cmd_show(n):
    rows = {(r["id"], r["src"]): r for r in jl(os.path.join(R7K, "k_data", "stage2.jsonl"))}
    ps = [d for d in jl(OUT) if d.get("flat")]
    ratio = [len(d["flat"]) / max(1, len(rows[(d["id"], d["src"])]["target"])) for d in ps]
    print(f"对照句 {len(ps)} 条；平淡版长短 / 原句：中位 {sorted(ratio)[len(ratio) // 2]:.2f}；"
          f"平淡版里还有“佳树”的 {sum('佳树' in d['flat'] for d in ps)}、有“兄长”的 {sum('兄长' in d['flat'] for d in ps)}")
    for d in ps[:n]:
        r = rows[(d["id"], d["src"])]
        print("=====", d["src"], d["id"])
        print("  前文:", " ‖ ".join(r["ctx"][-2:])[:140])
        print("  佳树:", r["target"][:160].replace("\n", " / "))
        print("  平淡:", d["flat"][:160].replace("\n", " / "))
        print("  过头:", d["over"][:160].replace("\n", " / "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pair", "show"])
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "pair":
        asyncio.run(cmd_pair(a.pilot))
    else:
        cmd_show(a.n)


if __name__ == "__main__":
    main()
