r"""第三版格式（局面 / 要说到的 / 长短）的写手，对线上 kaju-writer-l1a-r003 的考试（2026-11-11，训练包带回来的 4b-A / 4b-B / 8b-A / 8b-B）。

两边各用自己上线时会用的输入：
  旧：第一版要点卡（data\layered_v2\eval_*.jsonl 的 card_v1）+ card.WRITE_SYSTEM[2]，用户消息 "上下文：… 要点卡：…"
  新：训练包 data\eval.jsonl 的卡 + data\system.json 的 "2"，用户消息 "聊天：… 材料：…"（和 train.py 的 prompt_of 一字不差）
题：训练包的 53 道考试题（都没进训练）。每题各写 SAMPLES 遍。
判：和 exam_v2 一样，评判模型（2026-11-13 起默认 Gemini，`--judge deepseek` 是以前那样）对着草稿 / 参考回复判 自然 / 佳树 / 意思，两种顺序各判一次，不一致算平；漏答、编造两次都判才算。
另外给新写手数一遍"要说到的"漏了几条（闸门一）。
输出 data\exam_p3_<新写手>.json（盲选页从这里挑；routine_stats.py exam 也读它）+ data\daily\reports\exam-p3.md
用法（AstrBot venv）：python -I exam_p3.py kaju-writer-p3-4b-a kaju-writer-p3-4b-b [--old kaju-writer-l1a-r003] [--samples 3]

2026-11-12 第四版训练包加的（旧版留在 exam_p3_v1.py）：
  - 第八批留出的 8 道“看完感想”题（旧写手没有对应的卡，只考新写手，不做两两比较）。
  - 照念卡片：回复里有几成是“要说到的”原字（4 字以上的原样片段盖住的比例），和参考答案对比。
  - “我 / 哥”：自称“我”、私聊里叫“哥”的次数（兄长改得最多的两样）。
  - 长短随内容：要点条数和回复字数的相关系数（不再给“长短”那一行，要靠内容自己拉开）。
  - 心情对比：12 道题各换上“开心”和“委屈”两种心情行再写，DeepSeek 盲判哪句更开心；同时看换心情会不会多漏要点。
  --dry：不调写手、不判，拿参考答案当回复，只检查流程。
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, r"D:\JiashuBot\bot_setup")
from kaju_core.heart.mood_line import mood_line  # noqa: E402  线上和训练同一个函数

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exam_v2 as ev  # noqa: E402  (write、judge)

dl, bl, card = ev.dl, ev.bl, ev.card
PACK = os.path.join(bl.VT, "train_pack", "kaju_train_pack", "data")
SYS3 = json.load(open(os.path.join(PACK, "system.json"), encoding="utf-8"))["2"]
REPORT = os.path.join(bl.VT, "data", "daily", "reports", "exam-p3.md")
OLD_FILE = os.path.join(bl.VT, "data", "exam_p3_old.json")

COVER = """下面是一张材料卡里"要说到的"几件事，和一句回复。数一数：这几件事里，回复没说到的有几件，说错的有几件。
意思说到了就算说到，不要求原话；卡上写"无"或空的就都是 0。只输出 JSON：{"漏": 0, "错": 0}"""


def write3(model, ctx, card_text):
    # reasoning_effort none：8B 带思考开关，训练时是关着的（助手开头后有一段空的 <think></think>）。
    # 不带这个参数 Ollama 不加那一段，8B 会写出"句尾用…""***…***"这类乱话（2026-11-11 第一次考 8B 就这么废了）。
    # 4B 没有思考开关，带上也不受影响（试过）。线上要用 8B 的话，调用写手的地方也得带这个参数。
    body = {"model": model, "temperature": 0.7, "top_p": 0.9, "max_tokens": 220, "reasoning_effort": "none", "messages": [
        {"role": "system", "content": SYS3},
        {"role": "user", "content": "聊天：\n" + ("\n".join(ctx) or "（没有前文）") + "\n\n材料：\n" + card_text}]}
    req = urllib.request.Request(dl.OLLAMA_URL + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer local"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return dl.live_rw.clean_output(json.load(r)["choices"][0]["message"]["content"]).strip()
        except Exception:  # noqa: BLE001
            time.sleep(3)
    return ""


def items():
    old = {}
    for p in glob.glob(os.path.join(bl.VT, "data", "layered_v2", "eval_*.jsonl")):
        for r in bl.load(p):
            old[r["id"]] = (r, os.path.basename(p)[5:-6])
    out = []
    excl = os.path.join(bl.VT, "data", "rounds_v4", "exam_exclude.json")  # 11-14：兄长写法进了训练的题，不再考
    skip = set(json.load(open(excl, encoding="utf-8")).get("ids") or []) if os.path.exists(excl) else set()
    for r in bl.load(os.path.join(PACK, "eval.jsonl")):
        if r["id"] in skip:
            continue
        if r["id"] not in old:  # 第八批“看完感想”：旧写手没有这种卡，只考新的
            pts = re.search(r"^要说到的：(.*)$", r["card"], re.M)
            out.append({"id": r["id"], "set": r.get("scene") or "新题", "kind": "私聊", "title": "兄长大人", "ctx": r.get("ctx") or [],
                        "ref": r["target"], "ref_is": "参考回复", "old_card": None, "new_card": r["card"], "draft": "",
                        "must": pts.group(1) if pts else ""})
            continue
        o, name = old[r["id"]]
        m = re.search(r"^场合：(.*)$", r["card"], re.M)
        t = re.search(r"^对象：(.*)$", r["card"], re.M)
        pts = re.search(r"^要说到的：(.*)$", r["card"], re.M)
        out.append({"id": r["id"], "set": name, "kind": m.group(1) if m else "私聊", "title": o.get("to") or (t.group(1) if t else ""),
                    "ctx": r.get("ctx") or [], "ref": o.get("draft") or r["target"], "ref_is": "草稿" if o.get("draft") else "参考回复",
                    "old_card": o["card_v1"], "new_card": r["card"], "draft": o.get("draft", ""), "must": pts.group(1) if pts else ""})
    return out


async def cover(it, text):
    if not it["must"] or it["must"] in ("无", "（无）") or not text:
        return {"漏": 0, "错": 0}
    m = re.search(r"\{.*\}", await bl.ask(COVER, f"要说到的：{it['must']}\n\n回复：\n{text}", 0.0) or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    return {"漏": int(v.get("漏") or 0), "错": int(v.get("错") or 0)}


MOODS = {
    "开心": {"mood": {"joy": 0.88, "energy": 0.78, "stress": 0.06, "warm": 0.72},
             "recent": [{"emo": "开心", "i": 2, "src": "person"}, {"emo": "得意", "i": 1, "src": "person"}], "threads": []},
    "委屈": {"mood": {"joy": 0.34, "energy": 0.4, "stress": 0.46, "warm": 0.42},
             "recent": [{"emo": "委屈", "i": 2, "src": "person"}, {"emo": "失落", "i": 1, "src": "person"}],
             "threads": [{"emo": "委屈", "c": 1.6, "kind": "person"}]},
}
MOOD_JUDGE = """下面是同一段聊天里，同一个女孩的两句回复（甲、乙）。只看语气和情绪，哪一句听起来更开心、更有精神？
只输出 JSON：{"更开心": "甲"} 或 {"更开心": "乙"}，实在分不出就 {"更开心": "一样"}。"""


def set_mood(card_text, name):
    base = "\n".join(x for x in card_text.split("\n") if not x.startswith("心情："))
    return base + "\n" + mood_line(MOODS[name])


def points_of(card_text):
    m = re.search(r"^要说到的：(.*)$", card_text, re.M)
    if not m or m.group(1).strip() in ("", "无"):
        return []
    return [re.sub(r"（[^）]*）$", "", x).strip() for x in m.group(1).split("；") if len(x.strip()) >= 4]


def cover_ratio(card_text, text, n=4):
    """回复里有几成是“要说到的”原字：每条要点被 4 字以上原样片段盖住的比例，取平均。"""
    pts = points_of(card_text)
    if not pts or not text:
        return None

    def one(p):
        hit = [False] * len(p)
        for i in range(len(p) - n + 1):
            if p[i:i + n] in text:
                for j in range(i, i + n):
                    hit[j] = True
        return sum(hit) / len(p)
    return sum(one(p) for p in pts) / len(pts)


def wo_ge(text, kind):
    t = re.sub(r"[“「『\"][^”」』\"]*[”」』\"]", "", text or "")
    return len(re.findall(r"我", t)), (len(re.findall(r"哥", t.replace("兄长", ""))) if kind == "私聊" else 0)


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (vx * vy) if vx and vy else 0.0


def extra_stats(its):
    """新加的几项（只看新写手）。"""
    cov, cov_ref, wo, ge, npts, lens = [], [], 0, 0, [], []
    you = total = 0  # 11-17：说“你”的句子占几成（兄长定贴近原作：原作 3.8%；不再算硬伤）
    for it in its:
        r = cover_ratio(it["new_card"], it["ref"])
        for x in it["new"]:
            total += 1
            you += bool(re.search(r"你(?!们)", re.sub(r"[“「『\"][^”」』\"]*[”」』\"]", "", x or "")))
            c = cover_ratio(it["new_card"], x)
            if c is not None:
                cov.append(c)
                if r is not None:
                    cov_ref.append(r)
            w, g = wo_ge(x, it["kind"])
            wo += w
            ge += g
            npts.append(len(points_of(it["new_card"])))
            lens.append(len(x))
    felt = [it for it in its if it["set"] == "看完感想"]
    flens = sorted(len(x) for it in felt for x in it["new"])
    return {"照念卡片": round(sum(cov) / max(1, len(cov)), 2), "参考答案的照念": round(sum(cov_ref) / max(1, len(cov_ref)), 2),
            "我": wo, "哥": ge, "说你的句子比例": round(you / max(1, total), 3), "要点数和字数的相关": round(corr(npts, lens), 2),
            "看完感想题数": len(felt), "看完感想字数中位": flens[len(flens) // 2] if flens else 0,
            "看完感想漏点句数": sum(c["漏"] > 0 for it in felt for c in it.get("cover", []))}


async def mood_check(model, its, dry):
    """12 道带要点的题，换上开心 / 委屈两种心情行各写一遍：DeepSeek 盲判哪句更开心；看漏点有没有变多。"""
    pick = [it for it in its if points_of(it["new_card"])][:12]
    out = []
    for it in pick:
        w = {}
        for name in MOODS:
            w[name] = it["ref"] if dry else write3(model, it.get("ctx_new") or it["ctx"], set_mood(it["new_card"], name))
        out.append({"id": it["id"], "开心": w["开心"], "委屈": w["委屈"]})
    if dry:
        return {"题数": len(out), "开心那句更开心": None, "漏点_开心": None, "漏点_委屈": None}
    wins = 0
    for k, o in enumerate(out):  # 甲乙顺序轮换，免得判的人偏向一边
        a_, b_ = (o["开心"], o["委屈"]) if k % 2 == 0 else (o["委屈"], o["开心"])
        m = re.search(r"\{.*\}", await bl.ask(MOOD_JUDGE, f"甲：{a_}\n\n乙：{b_}", 0.0) or "", re.S)
        try:
            v = (json.loads(m.group(0)).get("更开心") if m else "") or ""
        except ValueError:
            v = ""
        happy_is = "甲" if k % 2 == 0 else "乙"
        wins += 1 if v == happy_is else 0.5 if v == "一样" else 0
    miss = {name: 0 for name in MOODS}
    for it, o in zip(pick, out):
        for name in MOODS:
            miss[name] += (await cover(it, o[name]))["漏"] > 0
    return {"题数": len(out), "开心那句更开心": round(wins / max(1, len(out)), 2),
            "漏点_开心": miss["开心"], "漏点_委屈": miss["委屈"], "句子": out}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("new", nargs="+")
    ap.add_argument("--old", default="kaju-writer-l1a-r003")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--system", default="pack", choices=["pack", "v5"],
                    help="写手的系统提示：pack = 训练包 system.json 的 \"2\"（r6 及以前）；v5 = card.SYSTEM_V5（第 7 轮起，去掉“不说你”）")
    ap.add_argument("--judge", default="gemini", choices=["gemini", "deepseek"],
                    help="评判用谁（2026-11-13 兄长：换 Gemini；deepseek = 以前那样）")
    ap.add_argument("--cards", default="v4", choices=["v4", "v5", "v6", "v7", "v8", "v9"],  # v7：11-17 第 6 轮，规划器卡 + 要说到的改写成短事实
                    help="v5 = 换成带“背景”的卡（data\\stage2bg\\exam_v5.json，11-14 第二阶段）；结果存 exam_p3_<model>_v5.json；"
                         "v6 = 规划器卡的样子（v5 + 局面后接“要接住的”，exam_v6.json，11-16 第 4 轮 prepare_r4.py）")
    a = ap.parse_args()
    if a.system == "v5":
        global SYS3
        SYS3 = card.SYSTEM_V5
    if a.judge == "gemini":
        bl.use_gemini()
    base = items()
    suffix = ""
    if a.cards in ("v5", "v6", "v7", "v8", "v9"):
        vx = json.load(open(os.path.join(bl.VT, "data", "stage2bg", f"exam_{a.cards}.json"), encoding="utf-8"))
        for it in base:
            if it["id"] in vx:
                it["new_card"] = vx[it["id"]]["card_" + a.cards]
                if a.cards in ("v8", "v9"):  # 11-17 第 7 轮：新写手看长聊天（旧写手 r003 照旧短的）；v9 = 第 8 轮标签卡
                    it["ctx_new"] = vx[it["id"]]["ctx_" + a.cards]
        if a.cards in ("v8", "v9"):  # 没进 v8 / v9 的题（恋爱向、没出好）不考
            base = [it for it in base if it["id"] in vx]
        suffix = "_" + a.cards
    n = a.samples
    if a.dry:
        its = [dict(it, new=[it["ref"]] * n) for it in base]
        for it in its:
            it["cover"] = [{"漏": 0, "错": 0}] * n
        print(json.dumps(extra_stats(its), ensure_ascii=False))
        print(json.dumps(await mood_check(None, its, True), ensure_ascii=False))
        print("看完感想题", sum(it["set"] == "看完感想" for it in its), "／共", len(its), "；有旧卡的", sum(bool(it["old_card"]) for it in its))
        print("心情行示例：", mood_line(MOODS["开心"]), "｜", mood_line(MOODS["委屈"]))
        print("改心情行示例：", set_mood(its[0]["new_card"], "委屈").replace("\n", " ｜ "))
        return
    # 旧写手只写一遍，几个新写手都和同一份比
    cache = dl.jload(OLD_FILE, {})
    if cache.get("model") != a.old or cache.get("samples") != n:
        dl.ollama_unload([x for x in dl.ollama_loaded() if x.startswith("kaju-writer")])
        cache = {"model": a.old, "samples": n, "wrote": {
            it["id"]: [ev.write(a.old, card.WRITE_SYSTEM[2], it["ctx"], it["old_card"], it["draft"], it["title"]) for _ in range(n)]
            for it in base if it["old_card"]}}
        json.dump(cache, open(OLD_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {a.old} 写完", flush=True)
    L = [f"# 考试：第三版格式的新写手 对 {a.old}（{time.strftime('%Y-%m-%d %H:%M')}）", "",
         f"{len(base)} 题 × {n} 遍。两边各用自己上线时会用的卡和系统提示；DeepSeek 两种顺序各判一次，不一致算平；漏答 / 编造两次都判才算。", ""]
    lines = []
    for model in a.new:
        its = [dict(it) for it in base]
        dl.ollama_unload([x for x in dl.ollama_loaded() if x.startswith("kaju-writer")])
        for it in its:
            it["old"] = cache["wrote"].get(it["id"]) or [""] * n
            it["new"] = [write3(model, it.get("ctx_new") or it["ctx"], it["new_card"]) for _ in range(n)]
        mood = await mood_check(model, its, False)
        print(f"  {model} 写完", flush=True)
        dl.ollama_unload([model])
        only_new = [(it, j) for it in its for j in range(n) if not it["old_card"]]
        for (it, j), c in zip(only_new, await asyncio.gather(*(cover(it, it["new"][j]) for it, j in only_new))):
            it.setdefault("cover", []).append(c)
        its_pair = [it for it in its if it["old_card"]]
        pairs = [(it, j) for it in its_pair for j in range(n)]
        verdicts = await asyncio.gather(*(ev.judge(it, it["old"][j], it["new"][j]) for it, j in pairs))
        covers = await asyncio.gather(*(cover(it, it["new"][j]) for it, j in pairs))
        score = {k: {"old": 0, "new": 0, "一样": 0} for k in ("自然", "佳树", "意思")}
        flags = {k: 0 for k in ("old漏答", "new漏答", "old编造", "new编造")}
        hard = {"old": 0, "new": 0}
        miss = wrong = empty = 0
        for (it, j), v, c in zip(pairs, verdicts, covers):
            it.setdefault("verdicts", []).append(v)
            it.setdefault("cover", []).append(c)
            it.setdefault("flags_new", []).append(dl.hard_flags(it["new"][j], []))
            it.setdefault("flags_old", []).append(dl.hard_flags(it["old"][j], []))
            for k in score:
                score[k][v[k]] += 1
            for k in flags:
                flags[k] += v[k]
            hard["old"] += bool(it["flags_old"][j])
            hard["new"] += bool(it["flags_new"][j])
            miss += c["漏"] > 0
            wrong += c["错"] > 0
            empty += not it["new"][j]
        xs = extra_stats(its)
        json.dump(its, open(os.path.join(bl.VT, "data", f"exam_p3_{model}{suffix}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump({"extra": xs, "mood": mood, "judge": bl.JUDGE["by"]}, open(os.path.join(bl.VT, "data", f"exam_p3_{model}{suffix}_extra.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        fmt = lambda d: f"新{d['new']}:旧{d['old']}（平{d['一样']}）"  # noqa: E731
        lens = sorted(len(x) for it in its_pair for x in it["new"]) or [0]
        olens = sorted(len(x) for it in its_pair for x in it["old"]) or [0]
        s = (f"{model}　{len(pairs)} 对：自然 {fmt(score['自然'])}，佳树 {fmt(score['佳树'])}，意思 {fmt(score['意思'])}，"
             f"漏答 新{flags['new漏答']}/旧{flags['old漏答']}，编造 新{flags['new编造']}/旧{flags['old编造']}，硬伤 新{hard['new']}/旧{hard['old']}；"
             f"“要说到的”有漏的 {miss}、有说错的 {wrong}、没写出来 {empty}；字数中位 新{lens[len(lens) // 2]}/旧{olens[len(olens) // 2]}；"
             f"照念卡片 {xs['照念卡片']}（参考答案 {xs['参考答案的照念']}），我 {xs['我']}、哥 {xs['哥']}，要点数和字数相关 {xs['要点数和字数的相关']}；"
             f"看完感想 {xs['看完感想题数']} 题字数中位 {xs['看完感想字数中位']}、漏点 {xs['看完感想漏点句数']} 句；"
             f"心情对比 {mood['题数']} 题：开心那句判得更开心 {mood['开心那句更开心']}，漏点 开心{mood['漏点_开心']}/委屈{mood['漏点_委屈']}")
        print(s, flush=True)
        lines.append(s)
        L += [f"## {model}", "", s, ""]
        for it in its_pair:
            L += [f"### {it['id']}（{it['set']}，{it['kind']}）", "", "```", *(it["ctx"][-4:] or ["（无）"]), "```", f"{it['ref_is']}：{it['ref']}", "",
                  f"新卡：{it['new_card'].replace(chr(10), ' ｜ ')}", ""]
            for j, v in enumerate(it["verdicts"]):
                tag = "　".join(f"{k}→{v[k]}" for k in ("自然", "佳树", "意思")) + "".join(f"　{k}" for k in flags if v[k])
                c = it["cover"][j]
                L += [f"- 第 {j + 1} 遍　{tag}" + (f"　要说到的：漏{c['漏']} 错{c['错']}" if c["漏"] or c["错"] else ""),
                      f"  - 旧：{it['old'][j]}", f"  - 新：{it['new'][j]}"]
            L.append("")
    L[3:3] = ["## 总表", "", *[f"- {x}" for x in lines], ""]
    rep = REPORT.replace(".md", f"{suffix}.md")
    open(rep, "w", encoding="utf-8").write("\n".join(L))
    print(f"{bl.cost()}\n报告 {rep}")


if __name__ == "__main__":
    asyncio.run(main())
