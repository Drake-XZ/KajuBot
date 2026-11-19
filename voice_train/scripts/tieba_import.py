"""贴吧语料 → 写手 H 层（说人话）训练用的样本（2026-11-08，兄长大人在 D:\\JiashuBot\\tieba_data 收的，以后还会继续补）。

    （用 AstrBot 的 venv 跑，和 daily_learn.py 一样）
    python -I tieba_import.py scan            只统计：有多少条、过滤掉多少、为什么（不写任何文件）
    python -I tieba_import.py import          把没导入过的记录做成样本，追加进 data\\daily\\pool.jsonl（src=tieba）
    python -I tieba_import.py status          每条记录现在的去向：导入了 / 过滤掉了（原因）/ 抽了卡 / 第几轮训过
    python -I tieba_import.py cost-test [N]   抽 N 条（默认 20）分别用"关思考 / 开思考"抽卡，比花费和结果（只花几分钱）

记账（兄长大人要求"标注自己用了哪些，避免后期补充新资源时出问题"）：
- data\\daily\\tieba_registry.jsonl：每条贴吧记录一行 {post_id, text_sha256, file, status, sample_id, at}。
  status 是 pool（做成样本进了语料池）或 skip:<原因>。以后再导入，按 post_id 和 text_sha256 跳过已经登记过的，
  所以新分片、重复分片、改了文件名都不会重复用。
- data\\daily\\tieba_imports.json：每次导入的批次：时间、读了哪些文件（大小、行数、sha256）、各种结果的条数。
- 抽卡记在 cards.jsonl，训到哪一轮记在 results\\daily\\rNNN\\new_ids.json（样本 id = tb-<post_id>），status 汇总这三处。
- 只读 tieba_corpus_v2_manifest.json 里列出的 v2 分片（交接文档要求：不要把 final 文件和 backup 目录重复并入）。

怎么做成对话：
- 楼层（level 1，第 2 楼起）：上下文 = 帖子标题（群友A 发帖）+ 前面最多 3 楼，这一楼当回复。
- 楼中楼（level 2）：上下文 = 标题 + 它回的那一楼 + 同一楼里前面最多 3 条，这一条当回复。
- 贴吧不存作者，所以每一楼当作不同的群友。

过滤（跳过的都记原因）：
- 回复太短/太长（2～80 字之外）、脏话戾气广告（daily_learn.TOXIC + B站那套黄段子词）、帖子标题本身就是擦边/黄的。
- 提到"佳树/温水"的：那是网友在聊她这个角色，H 层学了容易让她用第三人称评论自己（K 层只认原作台词）。
- 温水佳树吧、温水和彦吧整吧不用，理由同上。
"""
import argparse
import asyncio
import datetime as dt
import glob
import hashlib
import json
import os
import random
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_learn as dl  # noqa: E402

bl, card, bili = dl.bl, dl.card, dl.bili
TIEBA = r"D:\JiashuBot\tieba_data"
MANIFEST = os.path.join(TIEBA, "tieba_corpus_v2_manifest.json")
REGISTRY = os.path.join(dl.DD, "tieba_registry.jsonl")
IMPORTS = os.path.join(dl.DD, "tieba_imports.json")
SKIP_FORUMS = {"温水佳树", "温水和彦"}
SELF = re.compile(r"佳树|温水")
TITLE_BAD = re.compile(r"SM|色色|涩|瑟|本子|里番|R18|NSFW|福利|擦边|黄油|车|开车|老司机|涩图|色图|ntr|NTR|绿帽|调教|催眠", re.I)


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def part_files():
    m = dl.jload(MANIFEST, {})
    names = []
    for key in ("files", "parts", "shards", "data_files"):
        v = m.get(key)
        if isinstance(v, list):
            for x in v:
                n = x if isinstance(x, str) else (x.get("path") or x.get("file") or x.get("name") or "")
                if n:
                    names.append(os.path.basename(n))
            break
    if not names:
        names = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(TIEBA, "tieba_corpus_v2_part_*.jsonl")))]
    return [os.path.join(TIEBA, n) for n in names if re.fullmatch(r"tieba_corpus_v2_part_\d+\.jsonl", n)]


def load_records():
    recs = []
    for p in part_files():
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["_file"] = os.path.basename(p)
                    recs.append(r)
    return recs


def clean(text):
    t = re.sub(r"https?://\S+", "", text or "")
    t = dl.BILI_EMOJI.sub("", t)
    return " / ".join(x.strip() for x in t.splitlines() if x.strip()).strip()


# 贴吧比 B 站评论更荤、更冲（抽卡试跑里漏过了"黑萤h真的给我看爽了""张嘴就喷fen"）
TB_BAD = re.compile(r"(?<![a-zA-Z])[hH](?![a-zA-Z])|h场景|h线|酥服|爽死|喷粪|喷fen|喷子|nmsl|[cC][nN][mM]|tmd|妈的|"
                    r"色情|做爱|黄油|本子|涩|瑟瑟|奶子|屁股|裸|内衣|性癖|xp|NTR|ntr|绿帽|后宫|开车|车速|调教|催眠|"
                    r"孝子|典中典|急了|赢麻|洗地|带节奏|(?<![a-zA-Z])nt(?![a-zA-Z])|(?<![a-zA-Z])[sS][bB](?![a-zA-Z])|脑瘫|弱智|狗东西|狗叫|畜生|人渣")


def bad_text(t):
    return bool(dl.TOXIC.search(t) or bili._CRUDE.search(t) or TB_BAD.search(t))


def build(recs):
    """→ (样本列表, {post_id: 跳过原因})"""
    by_thread = {}
    for r in recs:
        by_thread.setdefault(r["thread_id"], []).append(r)
    samples, skip = [], {}
    for tid, rs in by_thread.items():
        title = clean(rs[0].get("thread_title", ""))[:60]
        forum = rs[0].get("forum", "")
        if forum in SKIP_FORUMS:
            for r in rs:
                skip[r["post_id"]] = "她自己的吧"
            continue
        if TITLE_BAD.search(title) or bad_text(title):
            for r in rs:
                skip[r["post_id"]] = "标题擦边或脏"
            continue
        if SELF.search(title):
            for r in rs:
                skip[r["post_id"]] = "标题在聊佳树/温水"
            continue
        floors = sorted([r for r in rs if r.get("level") == 1], key=lambda r: int(r.get("floor") or 0))
        by_pid = {r["post_id"]: r for r in rs}
        subs = {}
        for r in rs:
            if r.get("level") == 2:
                subs.setdefault(r.get("parent_post_id"), []).append(r)
        opener = f"群友A：[发帖]{title}"

        def check(r):
            t = clean(r.get("text", ""))
            if not 2 <= len(t) <= 80:
                return None, "太短或太长"
            if bad_text(t):
                return None, "脏话戾气广告"
            if SELF.search(t):
                return None, "提到佳树/温水"
            if re.fullmatch(r"[\W\d_a-zA-Z]*", t):
                return None, "纯符号英文"
            return t, ""
        for i, r in enumerate(floors):
            if int(r.get("floor") or 0) <= 1:
                skip[r["post_id"]] = "一楼（发帖正文）"
                continue
            t, why = check(r)
            if not t:
                skip[r["post_id"]] = why
                continue
            prev = [clean(q.get("text", ""))[:120] for q in floors[max(0, i - 3):i] if int(q.get("floor") or 0) > 1]
            ctx = [opener] + [f"群友{'BCD'[k]}：{x}" for k, x in enumerate(prev) if x]
            samples.append({"src": "tieba", "id": f"tb-{r['post_id']}", "kind": "群聊", "ctx": ctx, "target": t[:200],
                            "group": f"tieba-{tid}", "from": "floor", "forum": forum, "post_id": r["post_id"],
                            "sha": r.get("text_sha256", ""), "file": r["_file"]})
        for pid, lst in subs.items():
            lst = sorted(lst, key=lambda r: r.get("posted_at") or "")
            parent = by_pid.get(pid)
            ptext = clean(parent.get("text", ""))[:120] if parent else ""
            for j, r in enumerate(lst):
                t, why = check(r)
                if not t:
                    skip[r["post_id"]] = why
                    continue
                if parent is None:
                    skip[r["post_id"]] = "找不到它回的那一楼"
                    continue
                if SELF.search(ptext):
                    skip[r["post_id"]] = "回的那一楼在聊佳树/温水"
                    continue
                prev = [clean(q.get("text", ""))[:120] for q in lst[max(0, j - 3):j]]
                ctx = [opener, f"群友B：{ptext}"] + [f"群友{'CDE'[k]}：{x}" for k, x in enumerate(prev) if x]
                samples.append({"src": "tieba", "id": f"tb-{r['post_id']}", "kind": "群聊", "ctx": ctx, "target": t[:200],
                                "group": f"tieba-{tid}", "from": "lzl", "forum": forum, "post_id": r["post_id"],
                                "sha": r.get("text_sha256", ""), "file": r["_file"]})
    # 同一句话只要一次
    seen, out = set(), []
    for s in samples:
        k = bili._norm(s["target"])
        if k in seen:
            skip[s["post_id"]] = "和别的回复重复"
            continue
        seen.add(k)
        out.append(s)
    return out, skip


def registry():
    rows = bl.load(REGISTRY)
    return {r["post_id"] for r in rows}, {r["text_sha256"] for r in rows if r.get("text_sha256")}


def scan(write=False):
    recs = load_records()
    have_pid, have_sha = registry()
    new_recs = [r for r in recs if r["post_id"] not in have_pid and r.get("text_sha256") not in have_sha]
    samples, skip = build(recs)  # 用全部记录做上下文（新旧楼层会互相当上下文），只输出新的
    samples = [s for s in samples if s["post_id"] not in have_pid and s["sha"] not in have_sha]
    new_pids = {r["post_id"] for r in new_recs}
    skip = {k: v for k, v in skip.items() if k in new_pids}
    reasons = {}
    for v in skip.values():
        reasons[v] = reasons.get(v, 0) + 1
    by_from = {}
    for s in samples:
        by_from[s["from"]] = by_from.get(s["from"], 0) + 1
    print(f"分片 {len(part_files())} 个，记录 {len(recs)} 条，其中没登记过的 {len(new_recs)} 条")
    print(f"能用 {len(samples)} 条 {by_from}，跳过 {len(skip)} 条：")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {k} {v}")
    if not write:
        return samples, skip
    t = now()
    rec_by_pid = {r["post_id"]: r for r in new_recs}
    reg = []
    for s in samples:
        reg.append({"post_id": s["post_id"], "text_sha256": s["sha"], "file": s["file"], "status": "pool",
                    "sample_id": s["id"], "at": t})
    for pid, why in skip.items():
        r = rec_by_pid.get(pid, {})
        reg.append({"post_id": pid, "text_sha256": r.get("text_sha256", ""), "file": r.get("_file", ""),
                    "status": "skip:" + why, "sample_id": "", "at": t})
    # 没被做成样本、也没记跳过原因的（理论上没有），也登记，免得下次再看
    done = {x["post_id"] for x in reg}
    for pid, r in rec_by_pid.items():
        if pid not in done:
            reg.append({"post_id": pid, "text_sha256": r.get("text_sha256", ""), "file": r["_file"],
                        "status": "skip:未归类", "sample_id": "", "at": t})
    pool_rows = [{k: v for k, v in s.items() if k not in ("sha", "file")} | {"got": t} for s in samples]
    bl.append(dl.POOL, pool_rows)
    bl.append(REGISTRY, reg)
    log = dl.jload(IMPORTS, [])
    log.append({"at": t, "files": [{"file": os.path.basename(p), "bytes": os.path.getsize(p),
                                    "lines": sum(1 for _ in open(p, encoding="utf-8")), "sha256": sha_file(p)}
                                   for p in part_files()],
                "records_seen": len(recs), "new_records": len(new_recs), "to_pool": len(samples),
                "skipped": reasons})
    dl.jsave(IMPORTS, log)
    print(f"写进语料池 {len(samples)} 条，登记 {len(reg)} 条 → {REGISTRY}")
    return samples, skip


def status():
    reg = bl.load(REGISTRY)
    carded = {r["id"] for r in bl.load(dl.CARDS) if r.get("src") == "tieba"}
    trained = {}
    for p in glob.glob(os.path.join(dl.RES, "r*", "new_ids.json")):
        tag = os.path.basename(os.path.dirname(p))
        for i in dl.jload(p, []):
            if str(i).startswith("tb-"):
                trained[i] = tag
    st = {}
    for r in reg:
        k = r["status"]
        if k == "pool":
            k = f"训过（{trained[r['sample_id']]}）" if r["sample_id"] in trained else ("抽了卡、还没训" if r["sample_id"] in carded else "进了语料池、还没抽卡")
        st[k] = st.get(k, 0) + 1
    print(f"登记过的贴吧记录 {len(reg)} 条：")
    for k, v in sorted(st.items(), key=lambda x: -x[1]):
        print(f"  {k} {v}")
    for b in dl.jload(IMPORTS, []):
        print(f"导入批次 {b['at']}：新记录 {b['new_records']}，进语料池 {b['to_pool']}")


async def cost_test(n):
    samples, _ = scan(False)
    random.seed(11)
    pick = random.sample(samples, min(n, len(samples)))
    out = {}
    for mode, extra in (("关思考", {"thinking": {"type": "disabled"}}), ("开思考", {"thinking": {"type": "enabled"}})):
        use = {"in": 0, "cached": 0, "out": 0, "calls": 0}
        t0 = time.time()

        async def one(s):
            r = await bl.ds.chat.completions.create(model=bl.MODEL, temperature=0.3, extra_body=extra,
                                                    messages=[{"role": "system", "content": card.EXTRACT},
                                                              {"role": "user", "content": card.extract_prompt(s["ctx"], s["target"], "群聊", "")}])
            u = r.usage
            use["calls"] += 1
            use["in"] += u.prompt_tokens or 0
            use["out"] += u.completion_tokens or 0
            use["cached"] += getattr(u, "prompt_cache_hit_tokens", 0) or 0
            return card.parse(r.choices[0].message.content or "")
        cards = await asyncio.gather(*(one(s) for s in pick))
        miss = use["in"] - use["cached"]
        yuan_idle = miss / 1e6 * 1 + use["cached"] / 1e6 * 0.02 + use["out"] / 1e6 * 4
        out[mode] = {"cards": cards, "use": use, "yuan_idle": yuan_idle, "sec": time.time() - t0,
                     "ok": sum(1 for c in cards if c)}
        print(f"{mode}：{use['calls']} 次，输入 {use['in']}（缓存 {use['cached']}），输出 {use['out']}，"
              f"约 {yuan_idle:.4f} 元（空闲价，高峰 ×2），{out[mode]['sec']:.0f} 秒，解析成功 {out[mode]['ok']}/{len(pick)}")
    path = os.path.join(dl.DD, "tieba_cost_test.md")
    lines = ["# 贴吧抽卡：关思考 vs 开思考", ""]
    for s, a, b in zip(pick, out["关思考"]["cards"], out["开思考"]["cards"]):
        lines += [f"## {s['id']}", "", "上下文：" + " / ".join(s["ctx"]), "", f"回复：{s['target']}", "",
                  "关思考：", "```", card.render(a, "群聊", "") if a else "（没解析出来）", "```",
                  "开思考：", "```", card.render(b, "群聊", "") if b else "（没解析出来）", "```", ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"对照：{path}")
    return out, len(samples)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "import", "status", "cost-test"])
    ap.add_argument("n", nargs="?", type=int, default=20)
    a = ap.parse_args()
    if a.cmd == "scan":
        scan(False)
    elif a.cmd == "import":
        scan(True)
    elif a.cmd == "status":
        status()
    else:
        await cost_test(a.n)


if __name__ == "__main__":
    asyncio.run(main())
