r"""考试重判：同一个评判、同一批题，把几个写手已经写好的考试输出重新判一遍（不重新写）。

为什么（11-16 第 5 轮）：exam_p3 的评判走 omni.text，几个 key 叠着问、谁先答用谁（Gemini 3 / 3.8 / 4-argon / 3.5-lite，慢了还会落到 Claude），
不同时间考的成绩评判不一样：线上写手同一份 v6 卡上午判漏答 3、下午判 16。线上 v4 卡的成绩还是 11-13 判的。
这里固定评判模型（默认 gemini-3.8-flash），key 照兄长的动态挑选（model_router.json tasks.card + model_health.json）现排、
只用这个模型的那几个 key（bb-api 哈基米3 / 4、aigocode），挂了自动换下一家；几个写手交错着判，评判条件一样，才能当闸门比。
没判出来的对（几家都不行）所有写手都不算。每次评判的原始回答存 data\rejudge\cache.jsonl，断了重跑接着来。
只判 自然 / 佳树 / 意思 / 漏答 / 编造（和 exam_v2.judge 同一个提示词、两种顺序都判才算），不判“要说到的”覆盖。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\rejudge_exam.py kaju-writer-p4-8b-k kaju-writer-p4-8b-r5 [--cards v6] [--judge-model gemini-3.8-flash] [--reps 1]
结果：data\rejudge\<时间>_<cards>.json 和 .md
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
import exam_v2 as ev  # noqa: E402
import train_keys  # noqa: E402,F401  设好 KAJU_DATA、把 bot_setup 放进 sys.path

bl = ev.bl
rp = ev.rp
sys.stdout.reconfigure(encoding="utf-8")
CALLS = {"n": 0, "fail": 0, "cached": 0}
CACHE_FILE = os.path.join(bl.VT, "data", "rejudge", "cache.jsonl")  # 每次评判的原始回答，断了重跑接着来（键含评判 key、题、两句话）
CACHE = {}


def judge_keys(model):
    """兄长 11-14 的动态挑选（model_router.json tasks.card + model_health.json）现排的顺序里，只留这个模型的 key。
    固定的是评判模型，不是某一个 key：同一个模型换哪家中转都算同一个评判，哪家挂了自动跳过。"""
    from kaju_core.senses import omni
    return [k for k, _ in omni.plan("card", omni.gemini_keys()) if k.get("model") == model]


def pin_judge(model):
    from kaju_core.senses import omni
    if not judge_keys(model):
        sys.exit(f"出卡的挑选表里没有 {model} 的 key")
    sem = asyncio.Semaphore(6)
    name = model
    USED = CALLS.setdefault("by_key", {})

    def _note(ok, k, secs, why=""):  # 成没成记进和机器人共用的成绩（model_health.json），机器人挑 key 也跟着准
        omni._note(k, ok, secs, False, why)
    if os.path.exists(CACHE_FILE):
        for line in open(CACHE_FILE, encoding="utf-8"):
            try:
                r = json.loads(line)
                CACHE[r["k"]] = r["out"]
            except (ValueError, KeyError):
                pass

    async def ask(system, user, temperature=0.3):  # 换掉 build_layered.ask：只问这一个 key；失败返回 None（不当“没毛病”算）
        ck = json.dumps([name, system[:200], user], ensure_ascii=False)
        if ck in CACHE:
            CALLS["cached"] += 1
            return CACHE[ck]
        err = ""
        async with sem:
            for attempt in range(3):
                for k in judge_keys(model):  # 每次现排，跟着健康状况走
                    t0 = time.monotonic()
                    try:
                        out = await asyncio.wait_for(asyncio.to_thread(omni._gemini_text, k, system, user, "low", 40), 45)
                        CALLS["n"] += 1
                        if out and re.search(r"\{.*\}", out, re.S):
                            _note(True, k, time.monotonic() - t0)
                            USED[k.get("name")] = USED.get(k.get("name"), 0) + 1
                            CACHE[ck] = out
                            with open(CACHE_FILE, "a", encoding="utf-8") as f:
                                f.write(json.dumps({"k": ck, "out": out, "by": k.get("name")}, ensure_ascii=False) + "\n")
                            return out
                        err = "没回 JSON"
                    except Exception as e:  # noqa: BLE001
                        err = f"{k.get('name', '')[:12]} {type(e).__name__}: {str(e)[:50]}"
                        _note(False, k, time.monotonic() - t0, type(e).__name__)
                await asyncio.sleep(10 * (attempt + 1))
            CALLS["fail"] += 1
            print(f"  评判失败（几个 key 各试 3 轮都不行）{err}", flush=True)
            return None
    bl.ask = ask
    return name


async def judge(it, old, new):
    """和 exam_v2.judge 一样（同一个提示词、两种顺序、不一致算平、漏答编造两次都判才算），只是有一次没判出来就返回 None。"""
    jp = rp.JUDGE if it["ref_is"] == "草稿" else rp.JUDGE.replace("一份回复草稿（回复的人本来想说的意思）", "一条参考回复（回复的人本来想说的意思）") \
        .replace("草稿常常写得太满，A、B 不用把草稿每件事都说到", "A、B 不用和参考回复一字一样").replace("草稿和聊天里都没有", "参考回复和聊天里都没有")
    res = []
    for first in ("old", "new"):
        A, B = (old, new) if first == "old" else (new, old)
        u = (f"聊天：\n{chr(10).join(it['ctx'][-6:]) or '（没有前文）'}\n\n{it['ref_is']}：\n{it['ref']}\n\n"
             f"回复 A：\n{A or '（没写出来）'}\n\n回复 B：\n{B or '（没写出来）'}")
        txt = await bl.ask(jp, u, 0.1)
        if txt is None:
            return None
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            v = json.loads(m.group(0)) if m else None
        except ValueError:
            v = None
        if not isinstance(v, dict):
            return None
        flip = {"A": "old", "B": "new"} if first == "old" else {"A": "new", "B": "old"}
        so, sn = ("A", "B") if first == "old" else ("B", "A")
        res.append({**{x: flip.get(v.get(x), "一样") for x in ("自然", "佳树", "意思")},
                    "old漏答": v.get(f"{so}漏答") is True, "new漏答": v.get(f"{sn}漏答") is True,
                    "old编造": v.get(f"{so}编造") is True, "new编造": v.get(f"{sn}编造") is True})
    out = {x: (res[0][x] if res[0][x] == res[1][x] else "一样") for x in ("自然", "佳树", "意思")}
    for x in ("old漏答", "new漏答", "old编造", "new编造"):
        out[x] = res[0][x] and res[1][x]
    return out


def load(model, suffix):
    p = os.path.join(bl.VT, "data", f"exam_p3_{model}{suffix}.json")
    return {it["id"]: it for it in json.load(open(p, encoding="utf-8")) if it.get("old_card")}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--cards", default="v4", choices=["v4", "v6", "v7", "v8", "v9"])
    ap.add_argument("--judge-model", default="gemini-3.8-flash")
    ap.add_argument("--reps", type=int, default=1, help="每对判几遍（看评判自己的抖动）")
    a = ap.parse_args()
    suffix = "" if a.cards == "v4" else "_" + a.cards
    judge_name = pin_judge(a.judge_model)
    excl = os.path.join(bl.VT, "data", "rounds_v4", "exam_exclude.json")
    skip = set(json.load(open(excl, encoding="utf-8")).get("ids") or []) if os.path.exists(excl) else set()
    data = {m: load(m, suffix) for m in a.models}
    ids = sorted(set.intersection(*(set(d) for d in data.values())) - skip)
    print(f"评判固定为 {judge_name}；{a.cards} 卡；共同题 {len(ids)} 道；{len(a.models)} 个写手 × {a.reps} 遍", flush=True)
    jobs = []  # 交错着排，几个写手赶上的评判状态一样
    for iid in ids:
        for j in range(3):
            for r in range(a.reps):
                for m in a.models:
                    it = data[m][iid]
                    if j < len(it["new"]) and j < len(it["old"]):
                        jobs.append((m, iid, j, r))
    t0 = time.time()
    res = await asyncio.gather(*(judge(data[m][iid], data[m][iid]["old"][j], data[m][iid]["new"][j]) for m, iid, j, r in jobs))
    # 某一对（题、第几遍）有一个写手没判出来，所有写手的这一对都不算，免得两边评判条件不一样
    bad = {(iid, j, r) for (m, iid, j, r), v in zip(jobs, res) if v is None}
    keep = [(job, v) for job, v in zip(jobs, res) if (job[1], job[2], job[3]) not in bad]
    print(f"没判出来、各写手都去掉的对：{len(bad)}", flush=True)
    out = {m: {"对数": 0, "漏答": 0, "编造": 0, "r003漏答": 0, "r003编造": 0, "自然赢": 0, "自然输": 0, "佳树赢": 0, "佳树输": 0,
               "意思赢": 0, "意思输": 0, "漏答题": {}} for m in a.models}
    rows = []
    for (m, iid, j, r), v in keep:
        s = out[m]
        s["对数"] += 1
        s["漏答"] += v["new漏答"]
        s["编造"] += v["new编造"]
        s["r003漏答"] += v["old漏答"]
        s["r003编造"] += v["old编造"]
        for k in ("自然", "佳树", "意思"):
            s[k + "赢"] += v[k] == "new"
            s[k + "输"] += v[k] == "old"
        if v["new漏答"]:
            s["漏答题"][iid] = s["漏答题"].get(iid, 0) + 1
        rows.append({"model": m, "id": iid, "j": j, "rep": r, "new": data[m][iid]["new"][j], **v})
    # 卡上“要说到的：无”的题单独数（第 5 轮漏答大多在这种卡上）
    for m in a.models:
        s = out[m]
        wu = {iid for iid in ids if re.search(r"要说到的：\s*无\s*(?:$|\n|｜)", data[m][iid]["new_card"])}
        s["其中无卡漏答"] = sum(c for iid, c in s["漏答题"].items() if iid in wu)
        s["无卡题数"] = len(wu)
    stamp = time.strftime("%Y%m%d-%H%M")
    od = os.path.join(bl.VT, "data", "rejudge")
    os.makedirs(od, exist_ok=True)
    base = os.path.join(od, f"{stamp}_{a.cards}")
    json.dump({"judge": judge_name, "cards": a.cards, "ids": ids, "summary": out, "rows": rows,
               "calls": CALLS}, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    keys = ["对数", "漏答", "其中无卡漏答", "编造", "r003漏答", "r003编造", "自然赢", "自然输", "佳树赢", "佳树输", "意思赢", "意思输"]
    md = [f"# 重判（{stamp}，{a.cards} 卡，评判固定 {judge_name}，{len(ids)} 题 × 3 遍 × {a.reps}）", "",
          "都对 r003 同一份输出判；“r003漏答/编造”两边应该差不多，差得多说明评判在抖。", "",
          "| 项 | " + " | ".join(a.models) + " |", "|---|" + "---|" * len(a.models)]
    for k in keys:
        md.append(f"| {k} | " + " | ".join(str(out[m][k]) for m in a.models) + " |")
    md.append(f"| 无卡题数 | " + " | ".join(str(out[m]["无卡题数"]) for m in a.models) + " |")
    md += ["", f"调用 {CALLS['n']} 次（另有 {CALLS['cached']} 次用了缓存）、失败 {CALLS['fail']}，没判出来去掉的对 {len(bad)}，"
               f"用时 {(time.time() - t0) / 60:.1f} 分钟", f"各家答了几次：{json.dumps(CALLS.get('by_key', {}), ensure_ascii=False)}"]
    open(base + ".md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md), "\n→", base + ".md", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
