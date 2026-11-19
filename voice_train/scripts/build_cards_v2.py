"""第二版要点卡：把 l1a/r003 用过的全部训练数据按新卡片格式重抽（要点卡改进方案第二步，2026-11-09 兄长大人定）。

新格式见 bot_setup\\kaju_core\\voice\\card.py 的 EXTRACT_V2 / EXTRACT_V2_LIVE（一项里留"但/因为"、自己的事不写主语、可选"背景"）。
输出到 data\\layered_v2\\（不动 layered_v1）：
  stage1.jsonl   H：layered_v1 stage1（LCCC / 群聊 / 兄长私聊）+ 每晚自学 r001～r004 的新语料（群聊 / B站 / 贴吧）
  stage2.jsonl   K：原作台词 + 兄长大人的样本
  eval_*.jsonl   考试题（原来的卡留在 card_v1，新卡在 card）
  system.json    写手的系统提示（第二版），train_writer.py 看到它就用它
  meta.json      各来源条数、对齐没过的条数
卡怎么抽（和原来每条卡的来历一致）：
  - 原来从回复抽的（LCCC、群聊、贴吧、B站、原作 novel-n、gold-s/ab/b/c、第四批）：EXTRACT_V2 从回复抽，一项不漏
  - 原来从 DeepSeek 草稿抽的（原作对齐 al-*、第五批线上卡、第六批改了说法/认可、第七批）：EXTRACT_V2_LIVE 从草稿抽，
    再用 AGREE 看答案算不算照卡；不算：al-* 丢掉（同一句原作另有从回复抽的卡），兄长的样本改成从回复抽
  - 同一句有几张卡的（id 结尾 -0/-1，或同一个 id 重复几行）：温度 0.3 / 0.55 / 0.8 轮着用
可以断了再跑：抽好的卡存在 data\\layered_v2\\cache.jsonl。
用法（AstrBot venv）：python -I build_cards_v2.py [--limit N] [--dry]
  --dry 只数一数要抽多少张、估个价，不调 DeepSeek
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_layered as bl  # noqa: E402

sys.path.insert(0, os.path.join(bl.ROOT, "bot_setup", "kaju_core", "voice"))
import card  # noqa: E402

DATA = os.path.join(bl.VT, "data")
V1 = os.path.join(DATA, "layered_v1")
OUT = os.path.join(DATA, "layered_v2")
CACHE = os.path.join(OUT, "cache.jsonl")
REWRITES = os.path.join(bl.PD, "astrbot_plugin_kaju_style", "rewrites")
TEMPS = (0.3, 0.55, 0.8)
EVALS = ["layered_v1_eval.jsonl", "review4_eval.jsonl", "review5_eval.jsonl", "review6_eval.jsonl", "review7_eval.jsonl",
         "curated_second_batch_holdout.jsonl"]

WRITE_SYSTEM_V2 = {
    1: ("你是写手：照要点卡写出真人在聊天里会发的回复。忠实表达卡上的要点，不编造已经发生的事、做过的事或别人说过的话；"
        "可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。要点里没写是谁的事，就是自己的事；背景只是让你知道的情况，不用复述。"
        "长短、用词、语气像真人随手打的字。只输出回复。"),
    2: ("你是写手：照要点卡写出温水佳树（《败犬女主太多了！》里温水和彦的妹妹）会说的话。忠实表达卡上的要点，"
        "不编造已经发生的事、做过的事或别人说过的话；可以结合上下文表达自己的感受、愿望和有依据但不确定的猜测。"
        "要点里没写是谁的事，就是自己的事；背景只是让你知道的情况，不用复述。"
        "自称佳树，按场合自然使用对象的称呼，不说\"你\"；像她平时说话，也像真人随手打的字。只输出回复。"),
}


def field(card_text, name):
    m = re.search(rf"^{name}：(.*)$", card_text or "", re.M)
    v = m.group(1).strip() if m else ""
    return "" if v == "无" else v


# ---------------------------------------------------------------------- 找当时的草稿
class Drafts:
    def __init__(self):
        self.k = {r["id"]: r for r in bl.load(os.path.join(V1, "k_aligned.jsonl"))}
        self.guard = {str(i["id"]): i for i in json.load(open(os.path.join(bl.VT, "guard_eval", "items.json"), encoding="utf-8"))}
        self.rec = {}
        for p in glob.glob(os.path.join(REWRITES, "*.jsonl")):
            for r in bl.load(p):
                if r.get("draft"):
                    self.rec[str(r["t"])] = r["draft"]
        key = json.load(open(os.path.join(DATA, "ab6_key.json"), encoding="utf-8"))
        rep = {x["id"]: x for x in json.load(open(os.path.join(DATA, "cardlive_replay.json"), encoding="utf-8"))}
        self.ab6 = {iid: rep[v["rec"]]["draft"] for iid, v in key.items()}

    def of(self, row):
        """原来那张卡是从草稿抽的 → 草稿；原来从回复抽的 → None。"""
        if row.get("draft"):  # 考试题（layered_v1_eval）自己带着草稿
            return row["draft"]
        rid, frm = str(row.get("id", "")), row.get("card_from", "")
        if rid.startswith("al-"):
            r = self.k.get(rid[3:])
            return r.get("draft") if r else None
        if rid.startswith("gold-r5-"):
            it = self.guard.get(rid.rsplit("-", 1)[-1])
            return it.get("draft") if it else None
        if rid.startswith("gold-r6-") and frm in ("改了说法", "认可原句"):
            return self.rec.get(rid[len("gold-r6-"):])
        if rid.startswith("gold-r7-"):
            return self.ab6.get(rid[len("gold-r7-"):])
        return None


# ---------------------------------------------------------------------- 抽卡
class Cache:
    def __init__(self):
        os.makedirs(OUT, exist_ok=True)
        self.d = {r["key"]: r for r in bl.load(CACHE)}
        self.f = open(CACHE, "a", encoding="utf-8")

    def put(self, row):
        self.d[row["key"]] = row
        self.f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.f.flush()


def job_of(row, draft, temp, h_like):
    kind = field(row["card"], "场合") or row.get("kind") or "群聊"
    to = "" if h_like else (row.get("to") or field(row["card"], "对象"))
    src_text, live = (draft, True) if draft else (row.get("target", ""), False)
    key = f"{'L' if live else 'T'}|{temp}|{kind}|{to}|{bl.ctx_key(row.get('ctx') or [])}|{src_text.strip()}"
    return {"key": key, "kind": kind, "to": to, "ctx": row.get("ctx") or [], "text": src_text, "live": live,
            "temp": temp, "target": row.get("target", "")}


async def run_job(j, cache):
    if j["key"] in cache.d:
        return cache.d[j["key"]]
    prompt = card.EXTRACT_V2_LIVE if j["live"] else card.EXTRACT_V2
    ct = ""
    for t in (j["temp"], 0.5):
        c = card.parse(await bl.ask(prompt, card.extract_prompt(j["ctx"], j["text"], j["kind"], j["to"]), t))
        if c:
            ct = card.render(c, j["kind"], j["to"])
            break
    ok = True
    if ct and j["live"] and j["target"]:
        m = re.search(r"\{.*\}", await bl.ask(bl.AGREE, f"要点卡：\n{ct}\n\n回复：\n{j['target']}", 0.0) or "", re.S)
        try:
            ok = bool(json.loads(m.group(0)).get("ok")) if m else False
        except ValueError:
            ok = False
    out = {"key": j["key"], "card": ct, "ok": ok}
    cache.put(out)
    return out


def temps_for(rows):
    """同一句的第几张卡 → 温度。id 结尾 -N 用 N；同一个 id 重复几行按出现顺序。"""
    seen, out = {}, []
    for r in rows:
        m = re.search(r"-(\d)$", str(r.get("id", "")))
        n = int(m.group(1)) if m else seen.get(r.get("id"), 0)
        seen[r.get("id")] = seen.get(r.get("id"), 0) + 1
        out.append(TEMPS[min(n, len(TEMPS) - 1)])
    return out


def h_rows():
    rows = bl.load(os.path.join(V1, "stage1.jsonl"))
    for p in sorted(glob.glob(os.path.join(DATA, "daily", "rounds", "r*", "new.jsonl"))):
        rows += bl.load(p)
    return rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每部分只做前 N 条（试跑）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--conc", type=int, default=24)
    a = ap.parse_args()
    bl.SEM = asyncio.Semaphore(a.conc)
    drafts = Drafts()
    parts = {"stage1": h_rows(), "stage2": bl.load(os.path.join(V1, "stage2.jsonl"))}
    for name in EVALS:
        p = os.path.join(DATA, name)
        parts["eval_" + name.replace("_eval", "").replace(".jsonl", "")] = [r for r in bl.load(p) if r.get("card") and (r.get("target") or r.get("draft"))]
    if a.limit:
        parts = {k: v[:a.limit] for k, v in parts.items()}
    plan = {}
    for name, rows in parts.items():
        ts = temps_for(rows)
        plan[name] = [(r, job_of(r, drafts.of(r), t, h_like=(name == "stage1" and field(r["card"], "场合") == "群聊")))
                      for r, t in zip(rows, ts)]
    cache = Cache()
    uniq = {j["key"]: j for jobs in plan.values() for _, j in jobs}
    todo = [j for k, j in uniq.items() if k not in cache.d]
    n_live = sum(j["live"] for j in todo)
    print(f"共 {sum(len(v) for v in plan.values())} 条（" + "，".join(f"{k} {len(v)}" for k, v in plan.items()) +
          f"）；不同的卡 {len(uniq)} 张，已抽 {len(uniq) - len(todo)}，要抽 {len(todo)}（其中从草稿抽 {n_live}，各多一次对齐检查）", flush=True)
    calls = len(todo) + n_live
    print(f"约 {calls} 次 DeepSeek 调用；按第 4 轮的价（31544 次 15.12 元，空闲价）约 {calls / 31544 * 15.12:.0f} 元，高峰 ×2", flush=True)
    if a.dry:
        return
    t0, done = time.time(), [0]

    async def tracked(j):
        r = await run_job(j, cache)
        done[0] += 1
        if done[0] % 1000 == 0:
            el = time.time() - t0
            print(f"  {time.strftime('%H:%M:%S')} {done[0]}/{len(todo)}，已用 {el / 60:.0f} 分钟，"
                  f"预计还要 {el / done[0] * (len(todo) - done[0]) / 60:.0f} 分钟；{bl.cost()}", flush=True)
        return r
    for i in range(0, len(todo), 4000):  # 一块一块交，免得一次挂几万个协程
        await asyncio.gather(*(tracked(j) for j in todo[i:i + 4000]))

    meta = {"built": time.strftime("%Y-%m-%d %H:%M"), "parts": {}}
    for name, jobs in plan.items():
        out, stats = [], {"rows": len(jobs), "kept": 0, "no_card": 0, "align_drop": 0, "align_to_target": 0}
        fallback = []
        for r, j in jobs:
            res = cache.d.get(j["key"]) or {}
            if not res.get("card"):
                stats["no_card"] += 1
                continue
            if j["live"] and not res.get("ok"):
                if str(r.get("id", "")).startswith("al-"):
                    stats["align_drop"] += 1
                    continue
                fallback.append((r, job_of(r, None, j["temp"], False)))  # 兄长的样本：改成从回复抽
                continue
            row = {k: v for k, v in r.items() if k != "card"}
            row["card"], row["card_v1"], row["card_how"] = res["card"], r["card"], "草稿" if j["live"] else "回复"
            out.append(row)
        if fallback:
            fres = await asyncio.gather(*(run_job(j, cache) for _, j in fallback))
            for (r, j), res in zip(fallback, fres):
                if res.get("card"):
                    row = {k: v for k, v in r.items() if k != "card"}
                    row["card"], row["card_v1"], row["card_how"] = res["card"], r["card"], "回复（对齐没过）"
                    out.append(row)
                    stats["align_to_target"] += 1
        stats["kept"] = len(out)
        meta["parts"][name] = stats
        with open(os.path.join(OUT, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{name}: {stats}", flush=True)
    json.dump({str(k): v for k, v in WRITE_SYSTEM_V2.items()}, open(os.path.join(OUT, "system.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    meta["cost"] = bl.cost()
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写好 {OUT}\n{bl.cost()}")


if __name__ == "__main__":
    asyncio.run(main())
