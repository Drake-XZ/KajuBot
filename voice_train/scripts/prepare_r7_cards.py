r"""第 7 轮训练卡（2026-11-17，AGENT.md 第十节；兄长点头花约 30～50 元）。

有长前文的样本（prepare_r7.py ctx 的 long_ctx.json：群聊、兄长私聊、金句、旧人工样本、原作，约 2300 条）
按规划器 v6 的样子重出卡——写手看得到十几行聊天了，卡就不复述聊天：
  局面      一两句：谁对谁说、接哪件事、为什么轮到说话人回（不复述聊天）
  要接住的  最后那句里要接住的是什么事
  要说到的  那句话里真说了的、非说不可的事，≤2 条、短、写成事实本身、不用原话；原来是“无”的照旧“无”
  背景      原来的背景里、长聊天里看不到的才留；另外约三成的卡掺一条别的样本的背景（答案没用它）——教写手背景不是都要说
  心情      照原来那张卡的心情行
恋爱向的样本（目标里有“喜欢兄长 / 约会 / 女朋友……”这类词的）不进第 7 轮的数据。
造卡走 model_router.json tasks.card 的动态挑选（和线上规划器同一条链），每条记下是谁写的；usage_meter 估钱。

  python -I -X utf8 scripts\prepare_r7_cards.py run [--limit N]   → data\rounds_v4\r7\cards.jsonl（续跑：做过的跳过）
  python -I -X utf8 scripts\prepare_r7_cards.py report             → cards.md（数、例子）
"""
import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_r7 as p7  # noqa: E402  R6、R7、jl
import train_keys  # noqa: E402,F401  KAJU_DATA、bot_setup 进 sys.path

sys.stdout.reconfigure(encoding="utf-8")
OUT = os.path.join(p7.R7, "cards.jsonl")
ROMANCE = re.compile(r"喜欢兄长|爱兄长|爱你|亲亲|亲一下|抱抱|抱紧|约会|结婚|老婆|老公|恋人|女朋友|男朋友|嫁给")
MIX_RATE = 0.3

R7CARD = """下面是一段聊天（之后要照指导说话的写手也看得到这些）、原来交给说话人的材料，和说话人真正说出口的那句话。
你替规划器写一份“回复指导”的三栏。只输出 JSON：{{"局面": "...", "要接住的": "...", "要说到的": ["..."]}}
说话人在指导里写作“{me}”。

局面：一两句话：最后这句是谁对谁说的、接的是哪件事、为什么轮到{me}回。写手看得到聊天，**不要复述聊天里的话**，不要概括前面聊了什么。每句写出主语，别让人看反。
要接住的：最后那句（或最后几句）里需要{me}接住的是哪件事——问了什么、要{me}做什么、在说什么事。一句话，主语是说话的那个人。只写“是什么事”，不写怎么回。
要说到的：只留{me}那句真说了的、非说不可的事（问题的答案、对要求的答复、自己的事和打算），最多 2 条，每条一句短话（二十字以内），写成事实本身。
  不用那句话里的原话和语气词；不写态度、感受、提问、玩笑、附和；读书进度写成读到哪件事了，不写段号、书名号、引号。
  只是聊天、感叹、附和、撒娇、安慰的时候就 []。材料里“要说到的”是“无”的，一定写 []。"""


def _n(t):
    return re.sub(r"[\s，。！？、,.!?~…；;：:“”\"'‘’（）()/【】《》「」]", "", t or "")


def _bi(t):
    t = _n(t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def cover(part, text):
    a = _bi(part)
    return len(a & _bi(text)) / len(a) if a else 0.0


def line_of(card, key):
    m = re.search(rf"^{key}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def items(v):
    return [x.strip() for x in re.split("[；;]", v or "") if x.strip() and x.strip() != "无"]


def hashed(key, rate):
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < rate


def samples():
    """有长前文、目标不是恋爱向的样本（H：r6 的 stage1；K：r6 的 stage2）。"""
    long = json.load(open(os.path.join(p7.R7, "long_ctx.json"), encoding="utf-8"))
    out = []
    for part, f in (("H", os.path.join(p7.R6, "h_data", "stage1.jsonl")), ("K", os.path.join(p7.R6, "k_data", "stage2.jsonl"))):
        for r in p7.jl(f):
            key = f"{part}:{r['id']}"
            if key in long and not ROMANCE.search(r["target"]):
                out.append({**r, "part": part, "key": key, "long": long[key]})
    seen, uniq = set(), []
    for r in out:  # 同一个 id 在 H 里有新旧两份（h6_group 和 group）：都留，卡各出各的
        k = (r["key"], r["src"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def bg_pool(rows):
    """掺进去的背景从哪来：各样本原来卡上的背景（同一部分 H / K，按来源分）。"""
    pool = {}
    for r in rows:
        for b in items(line_of(r["card"], "背景")):
            pool.setdefault((r["part"], r["src"].replace("h6_", "")), []).append((r.get("group") or r["id"], b))
    return pool


def render(r, v, pool):
    old = r["card"]
    me = "佳树" if r["part"] == "K" else "我"
    jm = str(v["局面"]).strip().rstrip("。")
    catch = str(v.get("要接住的") or "").strip().rstrip("。")
    if catch:
        jm += "。要接住的：" + catch
    must = [str(x).strip().rstrip("。；;") for x in (v.get("要说到的") or []) if str(x).strip()][:2]
    if line_of(old, "要说到的") in ("", "无"):
        must = []
    text = "\n".join(r["long"])
    bg = [b for b in items(line_of(old, "背景")) if cover(b, text) < 0.5][:2]  # 长聊天里看得到的不留
    mixed = ""
    cands = [b for g, b in pool.get((r["part"], r["src"].replace("h6_", "")), []) if g != (r.get("group") or r["id"])]
    if cands and len(bg) < 2 and hashed("mix:" + r["key"] + r["src"], MIX_RATE):
        rng = random.Random(r["key"] + r["src"])
        for _ in range(10):
            b = rng.choice(cands)
            if cover(b, r["target"]) < 0.2 and cover(b, text) < 0.3:
                mixed = b
                break
    if mixed:
        bg.append(mixed)
    lines = [x for x in old.splitlines() if x.startswith(("场合：", "对象："))]
    lines += [f"局面：{jm}", "要说到的：" + ("；".join(must) or "无")]
    if bg:
        lines.append("背景：" + "；".join(bg))
    mood = next((x for x in old.splitlines() if x.startswith("心情：")), "")
    if mood:
        lines.append(mood)
    _ = me
    return "\n".join(lines), must, bg, mixed


async def make(todo, pool):
    from kaju_core.senses import omni
    sem = asyncio.Semaphore(6)
    st = {"好": 0, "没出好": 0, "by": {}}

    async def one(r):
        me = "佳树" if r["part"] == "K" else "我"
        u = f"聊天：\n{chr(10).join(r['long'])}\n\n原来交给{me}的材料：\n{r['card']}\n\n{me}说出口的话：\n{r['target']}"
        async with sem:
            for attempt in range(3):
                try:
                    out, n = await omni.text(R7CARD.format(me=me), u, timeout=40)
                    m = re.search(r"\{.*\}", out or "", re.S)
                    v = json.loads(m.group(0)) if m else None
                    if isinstance(v, dict) and str(v.get("局面") or "").strip():
                        card, must, bg, mixed = render(r, v, pool)
                        names = omni.plan_names("card")
                        by = names[n - 1] if 0 < n <= len(names) else str(n)
                        st["好"] += 1
                        st["by"][by] = st["by"].get(by, 0) + 1
                        return {"part": r["part"], "key": r["key"], "src": r["src"], "id": r["id"], "group": r.get("group"),
                                "ctx": r["long"], "target": r["target"], "card": card, "card_r6": r["card"],
                                "must": must, "bg": bg, "mixed_bg": mixed, "plan": v, "by": by}
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(5 * (attempt + 1))
            st["没出好"] += 1
            return None

    res = await asyncio.gather(*(one(r) for r in todo))
    return [x for x in res if x], st


def run(limit):
    import usage_meter
    usage_meter.patch()
    rows = samples()
    pool = bg_pool(rows)
    done = {(d["key"], d["src"]) for d in p7.jl(OUT)} if os.path.exists(OUT) else set()
    rng = random.Random(20261117)
    order = rows[:]
    rng.shuffle(order)  # 小批也各种来源都有
    todo = [r for r in order if (r["key"], r["src"]) not in done]
    batch = todo[:limit] if limit else todo
    print(f"要出卡 {len(rows)} 条，已做 {len(done)}，这次 {len(batch)}", flush=True)
    got, st = asyncio.run(make(batch, pool))
    with open(OUT, "a", encoding="utf-8") as f:
        for d in got:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    scale = len(rows) / max(1, len(batch))
    u = usage_meter.report(os.path.join(p7.R7, f"usage-{time.strftime('%H%M')}.json"), scale)
    print(f"出卡 好 {st['好']} / 没出好 {st['没出好']}；这批估 {u['rmb']} 元，按比例全量约 {u['rmb_full']} 元", flush=True)
    for who, x in u["by"].items():
        print(f"  {who}：{x['calls']} 次，约 {x['rmb']} 元", flush=True)


def report():
    import statistics
    rows = p7.jl(OUT)
    L = [f"# 第 7 轮训练卡（{len(rows)} 条）", ""]
    by = {}
    for d in rows:
        by.setdefault(f"{d['part']}:{d['src']}", []).append(d)
    L += ["| 来源 | 条数 | 要点 0 / 1 / 2 | 局面字数中位（原来 → 现在） | 有背景 | 掺了背景 | 要点照搬目标≥0.6 |", "|---|---|---|---|---|---|---|"]
    for k, ds in sorted(by.items()):
        m = [len(d["must"]) for d in ds]
        jm_old = statistics.median(len(line_of(d["card_r6"], "局面")) for d in ds)
        jm_new = statistics.median(len(line_of(d["card"], "局面")) for d in ds)
        copy = sum(any(cover(x, d["target"]) >= 0.6 for x in d["must"]) for d in ds)
        L.append(f"| {k} | {len(ds)} | {m.count(0)} / {m.count(1)} / {m.count(2)} | {jm_old:.0f} → {jm_new:.0f} | "
                 f"{sum(bool(d['bg']) for d in ds)} | {sum(bool(d['mixed_bg']) for d in ds)} | {copy} |")
    L += ["", "## 例子（每种来源两条）", ""]
    for k, ds in sorted(by.items()):
        for d in ds[:2]:
            L += [f"### {k} {d['id']}", "", "原来的卡：", "```", d["card_r6"], "```", "新卡：", "```", d["card"], "```",
                  f"目标：{d['target']}", ""]
    open(os.path.join(p7.R7, "cards.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:len(by) + 4]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.limit)
    report()


if __name__ == "__main__":
    main()
