r"""规划器提示词对比（2026-11-16 晚，AGENT.md 第十节）：同一批存下的主模型输入，两版 PLAN 各写一遍指导，固定同一个模型。

为什么固定模型：线上规划器走 model_router.json tasks.card（9 个候选，Gemini + Claude，谁先答用谁），
比两版提示词时要是这次换了一家答，就分不清是提示词的功劳还是模型的。默认按兄长的动态挑选问第一版，答上来的那家再写第二版
（每一对同一家同一个模型；11-16 晚 gemini-3.8-flash 几家对 3 万字的输入全超时，固定单一模型跑不动）；--model 只用某个模型。
输入：data\rounds_v4\replay4\cards.json 里的 46 轮（11-13～15 线上发出去了的，有主模型输入快照）。
输出：data\rounds_v4\replay4\plans_cmp\<版本>.jsonl，和 compare.md（条数、长度、漏进分析 / 指示 / 定性的条数、例子）。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\compare_plans.py [--model gemini-3.8-flash] [--versions v4,v5]
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replay_planner as rp  # noqa: E402  jl_dir、records、STYLE、TZ
import train_keys  # noqa: E402,F401  KAJU_DATA、bot_setup 进 sys.path

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rp.rt.ROOT, "replay4")
OUT = os.path.join(D, "plans_cmp")
USED = {}

# 写手会照念的东西（11-16 replay4 里看到的几种）：规划器自己的分析、给写手的指示、对她上一句的解释、定性和评价
LEAK = {
    "分析": r"材料里|记忆检索|检索|日记里没|没有.{0,6}记录|命中",
    "指示": r"不能说|不能编|不用再|不用重复|不要再|别编|要按|这条不用|注意|应该",
    "解释": r"指的是|意思是|说的是指",
    "定性": r"属于|不属于|骚扰|恶意|比较冲|玩笑而已|算是",
    "后台": r"第\s*\d+\s*/\s*\d+\s*段|共\s*\d+\s*段|工具|调用|reading_pace|时区",
}


def make_ask(model, pinned):
    """model 给了：只用这个模型的 key；没给（默认）：按兄长的动态挑选（tasks.card 9 个候选）从上往下问。
    pinned（dict，键 = 这一轮的 t）：同一轮第一版谁答上来的，第二版只问它——每一对两版同一个模型写，哪家挂了只丢那一对。"""
    from kaju_core.senses import omni

    def cands(t):
        if t in pinned:
            return [pinned[t]]
        ks = [k for k, _ in omni.plan("card", omni.gemini_keys())]
        return [k for k in ks if k.get("model") == model] if model else ks

    def make(t):
        async def ask(system, user, timeout=60):
            err = ""
            for attempt in range(3):
                for i, k in enumerate(cands(t)):
                    t0 = time.monotonic()
                    try:
                        out = await asyncio.wait_for(asyncio.to_thread(omni._gemini_text, k, system, user, "low", 90), 100)
                        omni._note(k, bool(out), time.monotonic() - t0, False, "" if out else "空")
                        if out:
                            pinned.setdefault(t, k)
                            nm = f"{k.get('name', '')[:24]} {k.get('model', '')}"
                            USED[nm] = USED.get(nm, 0) + 1
                            return out, i + 1
                    except Exception as e:  # noqa: BLE001
                        err = f"{type(e).__name__}: {str(e)[:60]}"
                        omni._note(k, False, time.monotonic() - t0, False, type(e).__name__)
                await asyncio.sleep(10 * (attempt + 1))
            raise RuntimeError(f"几家都没答上来：{err}")
        return ask
    return make


async def run_all(versions, model):
    from kaju_core.voice import shadow
    prompts = {"v4": shadow.PLAN_V4, "v5": shadow.PLAN_V5, "v6": shadow.PLAN_V6}
    ids = [str(r["id"]) for r in json.load(open(os.path.join(D, "cards.json"), encoding="utf-8"))]
    recs = rp.records(any_model=True)
    snaps = {str(s["t"]): s for s in rp.jl_dir(os.path.join(rp.STYLE, "draft_inputs")) if str(s["t"]) in ids}
    pinned = {}
    make = make_ask(model, pinned)
    sem = asyncio.Semaphore(4)
    os.makedirs(OUT, exist_ok=True)
    prev = {v: {str(d["t"]): d for d in (rp.rt.jl(os.path.join(OUT, v + ".jsonl")) if os.path.exists(os.path.join(OUT, v + ".jsonl")) else [])
                if d.get("plan")} for v in versions}
    todo = [t for t in ids if t in snaps and t in recs and not all(t in prev[v] for v in versions)]
    print(f"模型：{model or '动态挑选（每一对两版同一家同一个模型）'}；{len(ids)} 轮 × {versions}，要跑 {len(todo)} 轮", flush=True)
    tmp = os.path.join(OUT, "_tmp")

    async def one(t):
        async with sem:
            rows = []
            for v in versions:  # 第一版谁答的，第二版就只问它
                row = await shadow.run(snaps[t], recs[t], os.path.join(tmp, v), rp.TZ, 60, print, plan=prompts[v], ask=make(t))
                k = pinned.get(t) or {}
                row["version"], row["model"], row["by"] = v, k.get("model"), k.get("name")
                rows.append(row)
                if not row.get("plan"):
                    break
            if all(r.get("plan") for r in rows) and len(rows) == len(versions):
                for v, row in zip(versions, rows):
                    with open(os.path.join(OUT, v + ".jsonl"), "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"  {t} 好（{rows[0]['by']}）", flush=True)
            else:
                bad = next(r for r in rows if not r.get("plan"))
                print(f"  {t} 没出好 {bad['version']} {str(bad.get('error') or bad.get('raw'))[:70]}", flush=True)

    await asyncio.gather(*(one(t) for t in todo))


def report(versions):
    rows = {v: {str(d["t"]): d["plan"] for d in rp.rt.jl(os.path.join(OUT, v + ".jsonl")) if d.get("plan")} for v in versions}
    common = sorted(set.intersection(*(set(x) for x in rows.values())), key=float)
    L = [f"# 规划器提示词对比（{time.strftime('%Y-%m-%d %H:%M')}，同一批 {len(common)} 轮，模型固定）", "",
         "漏进 = 事实 / 背景里有规划器自己的分析、给写手的指示、对她上一句的解释、定性评价、后台编号（正则粗数，按条算）。", "",
         "| 项 | " + " | ".join(versions) + " |", "|---|" + "---|" * len(versions)]

    def stats(v):
        ps = [rows[v][t] for t in common]
        f = [len(p.get("事实") or []) for p in ps]
        b = [len(p.get("背景") or []) for p in ps]
        fl = sorted(len(x) for p in ps for x in p.get("事实") or []) or [0]
        bl = sorted(len(x) for p in ps for x in p.get("背景") or []) or [0]
        leak = {k: sum(bool(re.search(rx, x)) for p in ps for x in (p.get("事实") or []) + (p.get("背景") or [])) for k, rx in LEAK.items()}
        return {"事实 0 条的": sum(x == 0 for x in f), "事实 ≥3 条的": sum(x >= 3 for x in f), "事实共几条": sum(f),
                "事实每条字数中位": fl[len(fl) // 2], "背景共几条": sum(b), "背景每条字数中位": bl[len(bl) // 2],
                **{"漏进·" + k: n for k, n in leak.items()}, "有方向的": sum(bool(p.get("方向")) for p in ps)}
    st = {v: stats(v) for v in versions}
    for k in st[versions[0]]:
        L.append(f"| {k} | " + " | ".join(str(st[v][k]) for v in versions) + " |")
    if USED:
        L += ["", f"这次各家答了几次：{json.dumps(USED, ensure_ascii=False)}"]
    L += ["", "## 逐条（只列两版不一样的地方多的）", ""]
    for t in common:
        L.append(f"### {t}")
        for v in versions:
            p = rows[v][t]
            L.append(f"- **{v}** 要回应的：{p.get('要回应的', '')}" + (f"｜方向：{p['方向']}" if p.get("方向") else ""))
            L.append(f"  - 事实：{'；'.join(p.get('事实') or []) or '无'}")
            L.append(f"  - 背景：{'；'.join(p.get('背景') or []) or '无'}")
        L.append("")
    path = os.path.join(OUT, "compare.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:len(st[versions[0]]) + 8]), "\n→", path, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="", help="只用这个模型的 key；不填 = 动态挑选、每一对同一家")
    ap.add_argument("--versions", default="v4,v5")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--out-sub", default="plans_cmp", help="结果放 replay4 下的哪个目录（11-17 v5 / v6 对比放 plans_cmp6，不动第 6 轮用过的 plans_cmp）")
    a = ap.parse_args()
    global OUT
    OUT = os.path.join(D, a.out_sub)
    versions = a.versions.split(",")
    if not a.report_only:
        asyncio.run(run_all(versions, a.model))
    report(versions)


if __name__ == "__main__":
    main()
