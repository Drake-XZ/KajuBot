r"""H 层学规划器卡：小试（2026-11-16 晚，AGENT.md 第三节第 4 条，兄长定“先修规划器，再小试 H 的规划器卡数据”）。

为什么：replay4 里两个写手都不会用规划器的指导（念背景、“无”卡接不住、主宾说反）。这是“怎么用指导说话”，属于 H（说人话层）；
H 有 5.5 万条真人话，但一条规划器卡都没见过（stage1 里没有“背景 / 要接住的”）。MaiBot 的回复器也是拿大量真人群聊学看指导。

H 的卡原来是 v4（场合 / 对象 / 局面 / 要说到的，要说到的是从真人那句倒着写的 = 他真说了的）。这里补成规划器卡（和 replay_planner.plan_card 同样子）：
  局面 + “。要接住的：…”（最后那句里要接住的是什么事）
  要说到的：照旧（他真说了的，不动）
  背景：0～2 条，从更早的聊天里挑和这一句有关、但他没说的事（教写手背景可以不用）；他用到了、但局面和要说到的里没有的前文的事也写进来（有来路）
  方向：他这句的反应（态度 / 回应动作，一个短语）——兄长定先只记、不进卡（rows 里存着，卡上不写）
不改答案：答案仍是真人原话。不用贴吧（以前把 H 带偏过）。这一步只造小试数据给兄长看，不训练。
造卡走 model_router.json tasks.card 的动态挑选（和线上规划器同一条链：Gemini 6 个 + Claude 3 个），每条记下是谁写的。

  pilot [--n 300]   → data\stage_h_plan\pilot.jsonl、pilot.md
  mood              → 给 pilot.jsonl 补心情行（11-16 晚兄长定“加心情行”）→ pilot.jsonl 原地更新、pilot_mood.md
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_h_plan.py pilot | mood

心情行（11-16 晚）：原来 H“不带心情”（make_train_pack.py），心情只在 K（多是原作），考试里换开心 / 委屈心情判“更开心”只有 0.42～0.50，
心情行基本没起作用（决定 19 担心的“原作腔开关”）。做法照 K 的 label_novel_mood / label_chat_mood：模型只列“我”开口**之前**发生了什么事
（感受表、强度、起因、多久以前），数字用 kaju_heart 线上同一套公式（label_novel_mood.simulate）算，心情行用线上同一个函数（mood_line）拼。
第一版“我”那句话不给它看，结果心情几乎全是“开心6 精神6 紧绷1 亲近5”（开心 10%～90% 只有 0.57～0.70），线上却从开心 0.12 到 0.94；
11-16 晚兄长定“看回话”：第二版（mood_v=2）把那句话也给它看，那句流露的情绪算成 min_ago=0 的一件事，心情行和语气才对得上。
心情行的意思因此是“说这句时”，不是“开口之前”。第一版的读数留在 mood_before。约七成带心情行（make_train_pack.picked，按 id 哈希定）。
背景顺手清两样（小试量出来的）：和局面 / 要说到的重复的（两字片段重合 >60%）、几乎是真人原话的（泄答案）。
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
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import train_keys  # noqa: E402,F401  KAJU_DATA、bot_setup 进 sys.path

sys.stdout.reconfigure(encoding="utf-8")
OUT = os.path.join(rt.VT, "data", "stage_h_plan")
STAGE1 = os.path.join(rt.PACK, "data", "stage1.jsonl")
QUOTA = {"group": 120, "owner": 40, "bili": 60, "lccc": 80}  # 小试 300：真人群聊为主

HPLAN = """下面是一段聊天（“我”是要回话的人）、交给“我”的材料（局面、要说到的），和“我”真正说出口的那句话。
请按规划器的写法补四栏。只输出 JSON：{"要接住的": "...", "要说到的": ["..."], "方向": "...", "背景": ["..."]}

要说到的：把材料里“要说到的”重写一遍（11-17 防照抄：卡上的话和“我”那句字面太像，写手会学成照念卡）。
  只留“我”那句真说了的事；每条一件事、一句短话（二十字以内），写成第三人称的事实（“我明晚有空”“那本书是被气笑了才看完的”），
  **不用“我”那句里的原话和语气词**，不写态度、感受、提问、玩笑；材料里是“无”或者都没真说到，就 []。

要接住的：聊天最后那句（或最后几句）里，需要“我”接住的是哪件事——问了什么、要我做什么、在说什么事。一句话，主语是说话的那个人。
  只写“是什么事”，不写“回应…”“表达…”，不写我该怎么回，不写我要说的内容。
方向：“我”这句话的反应，一个短语（十个字以内）：我对这件事的态度，或者回应动作（“跟着笑”“不服气”“安慰对方”“答应”“好奇地问”“吐槽回去”）。不写句子。
背景：交给“我”的、可以用也可以不用的事，0～2 条，每条一句短话，只从聊天前文来：
  1. “我”那句话里用到了、但局面和要说到的里都没有的前文的事，写进来（让每件事有来路）；
  2. 再挑 0～1 件前文里和最后那句有关、但我没用到的事（教写手背景可以不说）。前文太短、挑不出就不挑。
  不写：对人对事的定性和评价、我该怎么说话的提醒、我的心情和想法、你自己的知识和推算、局面和要说到的里已经有的。没有就 []。"""


MOOD_H = """下面是一段聊天记录，最后一行是“我”说的话。
我要知道：“我”说最后这句的时候，心里是什么状态。前面发生的事要算，最后这句话本身流露出来的情绪也要算
（把它当成 min_ago 为 0 的一件事：最后这句听着开心、委屈、生气、得意、难过、不耐烦……就照它写，强度照语气的轻重）。
请列出：
1. hour：这时大概是几点（0~23 的整数；看不出就按最可能的写）。
2. events：发生在“我”身上、让“我”有感受的事，按先后排，最多 6 件，最后一件是最后这句话流露的情绪；没有就空列表。“我”前面说的话里流露的感受也算。每件：
   - emo：只能从这些里选一个：{emos}
   - i：强度 1~3（1 一点点，2 明显，3 很强烈）。多数日常小事是 1。
   - src："person" 是别人对“我”说了 / 做了什么（或者“我”自己和人聊天时的感受）；"content" 是“我”看的、读的、听的东西本身（分享的视频、图片、文章）让“我”有感受
   - from_brother：一律 false
   - toward_her：是不是冲着“我”来的（别人之间的事、“我”旁观的为 false）
   - cause：起因，20 字以内，第三人称写事实
   - min_ago：离“我”说最后这句大概几分钟前（整数；聊天里一来一回大约 1~2 分钟；最后这句本身是 0）
3. carried：记录里明确看得出、之前就压在“我”心里还没放下的事。一般没有，就空列表。每件：
   - emo：只能从这些里选：{thread_emos}
   - c：现在还有多重，0.5~3
   - hours_ago：大概几小时前开始的
   - from_brother：false
   - cause：20 字以内

只输出一个 JSON 对象，不要别的字：{{"hour": 17, "events": [...], "carried": [...]}}

聊天记录（最后一行是“我”说的话）：
{text}
"""


def _n(t):
    return re.sub(r"[\s，。！？、,.!?~…；;：:“”\"'‘’（）()/【】《》]", "", t or "")


def _bi(t):
    t = _n(t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def clean_bg(r):
    """背景去掉：和局面 / 要说到的重复的、几乎是真人原话的（小试 300 条里各 32、2 条）。"""
    m = re.search(r"^局面：(.*)$", r["card"], re.M)
    jm = (m.group(1) if m else "") + r.get("catch", "")
    m = re.search(r"^要说到的：(.*)$", r["card"], re.M)
    ref = _bi(jm + (m.group(1) if m else ""))
    tg = _bi(r["target"])
    keep = []
    for b in r.get("bg") or []:
        s = _bi(b)
        if not s:
            continue
        if len(s & ref) / len(s) > 0.6:
            continue
        if len(_n(r["target"])) >= 6 and len(s & tg) / max(1, len(tg)) > 0.6:
            continue
        keep.append(b)
    return keep


def render(r):
    """规划器卡（背景已清）+ 心情行（有读数、且这一条按哈希被挑中才带）。"""
    import make_train_pack as mp
    from kaju_core.heart.mood_line import mood_line
    card = card_with(r["card"], r.get("catch", ""), r.get("bg_clean", r.get("bg") or []), r.get("must"))
    if r.get("mood_snap") and mp.picked("h:" + r["id"]):
        line = mood_line(r["mood_snap"])
        if line:
            card += "\n" + line
    return card


async def add_mood(rows):
    import label_novel_mood as L
    from kaju_core.senses import omni
    sem = asyncio.Semaphore(6)
    st = {"好": 0, "没出好": 0, "by": {}}

    async def one(r):
        if r.get("mood_snap") and r.get("mood_v") == 2:
            return
        if r.get("mood_snap") and "mood_before" not in r:  # 第一版（只看开口之前）留着对比
            r["mood_before"] = {"label": r.get("mood_label"), "snap": r["mood_snap"], "by": r.get("mood_by")}
        text = "\n".join(r["ctx"][-12:] + ["我：" + r["target"].replace("\n", " / ")])
        prompt = MOOD_H.format(emos=L.EMOS, thread_emos=L.THREAD_EMOS, text=text)
        async with sem:
            for attempt in range(3):
                try:
                    out, n = await omni.text("", prompt, timeout=40)
                    lab = L.parse(out or "")
                    if lab is not None:
                        names = omni.plan_names("card")
                        by = names[n - 1] if 0 < n <= len(names) else str(n)
                        r["mood_label"], r["mood_snap"], r["mood_by"], r["mood_v"] = lab, L.simulate(lab), by, 2
                        st["好"] += 1
                        st["by"][by] = st["by"].get(by, 0) + 1
                        return
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(5 * (attempt + 1))
            st["没出好"] += 1

    await asyncio.gather(*(one(r) for r in rows))
    return st


def pick(n_scale):
    rows = [json.loads(line) for line in open(STAGE1, encoding="utf-8")]
    rng = random.Random(20261116)
    out = []
    for src, q in QUOTA.items():
        pool = [r for r in rows if r["src"] == src and len(r.get("ctx") or []) >= 3]  # 前文太短挑不出背景
        rng.shuffle(pool)
        out += pool[:max(1, round(q * n_scale))]
    return out


def card_with(card, catch, bg, must=None):
    """must 不是 None 时（11-17 全量起）：要说到的换成防照抄改写过的那几条。"""
    lines = []
    for line in card.splitlines():
        if line.startswith("局面：") and catch and "要接住的：" not in line:
            line = line.rstrip("。") + "。要接住的：" + catch.rstrip("。")
        if line.startswith("要说到的：") and must is not None:
            line = "要说到的：" + ("；".join(x.rstrip("。；;") for x in must) or "无")
        lines.append(line)
        if line.startswith("要说到的：") and bg:
            lines.append("背景：" + "；".join(x.rstrip("。；;") for x in bg[:2]))
    return "\n".join(lines)


async def make(rows):
    from kaju_core.senses import omni
    sem = asyncio.Semaphore(6)
    stats = {"好": 0, "没出好": 0, "by": {}}

    async def one(r):
        u = f"聊天：\n{chr(10).join(r['ctx'][-12:])}\n\n交给“我”的材料：\n{r['card']}\n\n“我”说出口的话：\n{r['target']}"
        async with sem:
            for attempt in range(3):
                try:
                    out, n = await omni.text(HPLAN, u, timeout=40)
                    m = re.search(r"\{.*\}", out or "", re.S)
                    v = json.loads(m.group(0)) if m else None
                    if isinstance(v, dict) and str(v.get("要接住的") or "").strip():
                        bg = [str(x).strip() for x in (v.get("背景") or []) if str(x).strip()][:2]
                        names = omni.plan_names("card")
                        by = names[n - 1] if 0 < n <= len(names) else str(n)
                        stats["好"] += 1
                        stats["by"][by] = stats["by"].get(by, 0) + 1
                        must = [str(x).strip() for x in (v.get("要说到的") or []) if str(x).strip()][:4] if "要说到的" in v else None
                        if must is not None and re.search(r"^要说到的：\s*无\s*$", r["card"], re.M):
                            must = []  # 原来是“无”的照旧“无”（小试 49 条“无”里 12 条被改写硬加了要点，“无”卡是教她接住情绪的，不能少）
                        return {**r, "catch": str(v["要接住的"]).strip(), "direction": str(v.get("方向") or "").strip(), "bg": bg,
                                "must": must, "card_plan": card_with(r["card"], str(v["要接住的"]).strip(), bg, must), "by": by}
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {str(e)[:60]}"
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
            stats["没出好"] += 1
            return None

    res = await asyncio.gather(*(one(r) for r in rows))
    return [x for x in res if x], stats


def report(rows, stats):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "pilot.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_src = {}
    for r in rows:
        s = by_src.setdefault(r["src"], {"条数": 0, "有背景": 0, "要说到的是无": 0})
        s["条数"] += 1
        s["有背景"] += bool(r["bg"])
        s["要说到的是无"] += "要说到的：无" in r["card"]
    L = ["# H 层规划器卡小试", "", f"出成 {stats['好']}、没出好 {stats['没出好']}；谁写的：{json.dumps(stats['by'], ensure_ascii=False)}", "",
         "| 来源 | 条数 | 有背景 | 要说到的是无 |", "|---|---|---|---|"]
    for s, v in by_src.items():
        L.append(f"| {s} | {v['条数']} | {v['有背景']} | {v['要说到的是无']} |")
    L += ["", "## 例子（每个来源几条）", ""]
    for src in QUOTA:
        for r in [x for x in rows if x["src"] == src][:6]:
            L += [f"### {r['id']}（{src}）", "```", *r["ctx"][-6:], "```", "卡：", "```", r["card_plan"], "```",
                  f"方向（只记不进卡）：{r['direction']}", f"真人那句：{r['target']}", ""]
    open(os.path.join(OUT, "pilot.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:12]), "\n→", os.path.join(OUT, "pilot.md"), flush=True)


def mood_report(rows, st):
    path = os.path.join(OUT, "pilot.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    have = [r for r in rows if r.get("mood_snap")]
    with_line = [r for r in have if "\n心情：" in r["card_final"]]
    j = sorted(r["mood_snap"]["mood"]["joy"] for r in have) or [0]
    s = sorted(r["mood_snap"]["mood"]["stress"] for r in have) or [0]
    q = lambda v: f"{v[len(v) // 10]:.2f} / {v[len(v) // 2]:.2f} / {v[len(v) * 9 // 10]:.2f}"  # noqa: E731
    bg0 = sum(len(r.get("bg") or []) for r in rows)
    bg1 = sum(len(r.get("bg_clean") or []) for r in rows)
    L = ["# H 层规划器卡小试：加心情行", "",
         f"估心情：出成 {st['好']}、没出好 {st['没出好']}；谁估的：{json.dumps(st['by'], ensure_ascii=False)}",
         f"带心情行的卡 {len(with_line)}/{len(rows)}（按 id 哈希挑约七成）；开心 10%/中位/90%：{q(j)}；紧绷：{q(s)}",
         f"背景清理：{bg0} → {bg1} 条（去掉和卡上重复的、几乎是真人原话的）", "",
         "## 例子：先列心情最低落 / 最紧绷的几条，再随机几条", ""]
    low = sorted(with_line, key=lambda r: r["mood_snap"]["mood"]["joy"] - r["mood_snap"]["mood"]["stress"])[:8]
    rng = random.Random(7)
    rest = [r for r in with_line if r not in low]
    rng.shuffle(rest)
    for r in low + rest[:8]:
        ev = "；".join(f"{e['emo']}{e['i']}（{e['cause']}）" for e in r["mood_label"]["events"]) or "没有"
        L += [f"### {r['id']}（{r['src']}）", "```", *r["ctx"][-6:], "```", "卡：", "```", r["card_final"], "```",
              f"估心情时列的事（只看开口之前）：{ev}", f"真人那句：{r['target']}", ""]
    open(os.path.join(OUT, "pilot_mood.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:6]), "\n→", os.path.join(OUT, "pilot_mood.md"), flush=True)


FULL_LCCC = 3000


def pick_full():
    """全量：群聊、B 站、兄长私聊全用（前文 ≥ 2 行），lccc 挑 3000 条（前文 ≥ 3 行）；不用贴吧。顺序固定，可以分批续跑。"""
    rows = [json.loads(line) for line in open(STAGE1, encoding="utf-8")]
    rng = random.Random(20261117)
    out = []
    for src in ("group", "owner", "bili"):
        out += [r for r in rows if r["src"] == src and len(r.get("ctx") or []) >= 2]
    lc = [r for r in rows if r["src"] == "lccc" and len(r.get("ctx") or []) >= 3]
    rng.shuffle(lc)
    out += lc[:FULL_LCCC]
    rng.shuffle(out)
    return out


def run_full(limit, pin_to=""):
    import usage_meter
    if pin_to:  # 只用这一家的 Gemini（11-17 兄长：等 bb-api 好了再跑，便宜十几倍）
        import relay_pin
        relay_pin.pin(pin_to)
    usage_meter.patch()
    path = os.path.join(OUT, "full.jsonl")
    os.makedirs(OUT, exist_ok=True)
    done = {json.loads(line)["id"] for line in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    allrows = pick_full()
    todo = [r for r in allrows if r["id"] not in done]
    batch = todo[:limit] if limit else todo
    print(f"全量 {len(allrows)} 条（{ {s: sum(r['src'] == s for r in allrows) for s in QUOTA} }），已做 {len(done)}，这次 {len(batch)}", flush=True)
    rows, st = asyncio.run(make(batch))
    st2 = asyncio.run(add_mood(rows))
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            r["bg_clean"] = clean_bg(r)
            r["card_final"] = render(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    scale = len(allrows) / max(1, len(batch))
    u = usage_meter.report(os.path.join(OUT, f"usage-{time.strftime('%H%M')}.json"), scale)
    print(f"出卡 好 {st['好']} / 没出好 {st['没出好']}；估心情 好 {st2['好']} / 没出好 {st2['没出好']}", flush=True)
    print(f"这批估 {u['rmb']} 元，按比例全量（×{scale:.1f}）约 {u['rmb_full']} 元；各家：", flush=True)
    for who, x in u["by"].items():
        print(f"  {who}：{x['calls']} 次，进 {x['in_chars']} 字、出 {x['out_chars']} 字，价格倍数 {x['price']}，约 {x['rmb']} 元", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pilot", "mood", "full"])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--limit", type=int, default=0, help="full：这次最多做几条（0 = 剩下的全做）")
    ap.add_argument("--pin", default="", help="full：只用这一家中转的 Gemini（比如 bb-api），不落到别家")
    a = ap.parse_args()
    if a.cmd == "full":
        run_full(a.limit, a.pin)
        return
    if a.cmd == "mood":
        rows = [json.loads(line) for line in open(os.path.join(OUT, "pilot.jsonl"), encoding="utf-8")]
        st = asyncio.run(add_mood(rows))
        for r in rows:
            r["bg_clean"] = clean_bg(r)
            r["card_final"] = render(r)
        mood_report(rows, st)
        return
    rows = pick(a.n / sum(QUOTA.values()))
    print(f"小试 {len(rows)} 条：{ {s: sum(r['src'] == s for r in rows) for s in QUOTA} }", flush=True)
    done, stats = asyncio.run(make(rows))
    report(done, stats)


if __name__ == "__main__":
    main()
