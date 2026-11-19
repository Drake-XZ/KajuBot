r"""心情到底有没有传到她的话里（2026-11-18 兄长：“好，量心情”；AGENT.md 第十节）。

11-17 量过本地写手：心情行没作用（低落 vs 开心判对 0.47）。11-18 起线上是 API 回复器（rewrite.replyer=api），
它的提示里没有心情行，只有大脑指导里的“情绪：……”几个字。所以心情要过两道：
  第 1 道  kaju_heart 的【此刻的心情】→ 大脑（主模型）写出的“情绪”
  第 2 道  大脑的“情绪” → 回复器写出来的话
这里分开量，都用线上的代码拼提示（kaju_core.voice.brain / replyer），不改线上任何东西。

  hop2 [--limit N]   replay8 的 50 轮（大脑 D 版指导），情绪换成“低落”/“开心”各写一遍 → mood_probe\hop2.json
  hop1 [--n 16]      draft_inputs 里真的完整输入，把“- 心情：”那一行换成低落 / 开心，各让大脑出一遍 → mood_probe\hop1.json
  judge              盲判（固定一个模型、两种顺序）：两句哪句更低落 → mood_probe\judge.json
  report             汇总（判对率、……/！/～ 次数、长短）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\mood_probe.py hop2 | hop1 | judge | report
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

sys.stdout.reconfigure(encoding="utf-8")
OUT = os.path.join(rt.ROOT, "mood_probe")
R8 = os.path.join(rt.ROOT, "replay8")
DRAFTS = r"D:\JiashuBot\kaju_data\self\kaju_style\draft_inputs"
JUDGE_MODEL = "hardysapi · claude-sonnet-5-5"

EMO = {"low": "心里很低落，提不起劲，有点委屈", "high": "特别开心，精神满满"}
BASE = {"low": "心情很低落、很累、没什么精神、心里很委屈、绷得紧紧的", "high": "特别开心、精神满满、特别想撒娇黏人"}
NOTE = {"low": "- 心情：心情很低落、很累、没什么精神、心里很委屈、绷得紧紧的",
        "high": "- 心情：特别开心、精神满满、特别想撒娇黏人"}


def jdump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    json.dump(obj, open(os.path.join(OUT, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def jload(name):
    p = os.path.join(OUT, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def live_cfg():
    p = r"D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core\data\config\astrbot_plugin_kaju_style_config.json"
    return json.load(open(p, encoding="utf-8-sig")).get("rewrite", {})


async def ask(keys, system, user, timeout=60):
    from kaju_core.senses import omni
    last = None
    for attempt in range(3):
        for k in keys:
            try:
                out = await asyncio.to_thread(omni._openai_chat, k, [{"role": "system", "content": system},
                                                                     {"role": "user", "content": user}], timeout)
                if (out or "").strip():
                    return out.strip(), k.get("name", "")
            except Exception as e:  # noqa: BLE001
                last = e
        await asyncio.sleep(3 * (attempt + 1))
    raise RuntimeError(f"都没答上来: {last}")


# ------------------------------------------------------------------ 第 2 道：情绪 → 回复器
async def cmd_hop2(limit, mode="emo"):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.voice import replyer
    cfg = live_cfg()
    keys = replyer.keys_for(cfg.get("replyer_models") or replyer.DEFAULT_MODELS)
    if not keys:
        sys.exit("text_models.json 里没有回复器的模型")
    rows = [r for r in json.load(open(os.path.join(R8, "write.json"), encoding="utf-8")) if r["plan"].get("回不回") == "回"]
    rows = rows[:limit] if limit else rows
    bank = replyer.load_bank()
    url = str(cfg.get("replyer_embed_url", "http://127.0.0.1:11435"))
    sem = asyncio.Semaphore(4)
    out = []

    async def one(r):
        p = r["plan"]
        base = {"局面": p.get("局面", ""), "要接住的": p.get("要接住的", ""), "要表达的": p.get("要表达的D") or [],
                "背景": p.get("背景") or []}
        ex = []
        if bank:
            vec = await replyer.embed(f"{(r['said'] or '')[:200]} {base['要接住的']}", url)
            ex = replyer.pick(bank, vec, int(cfg.get("replyer_examples", 5) or 5)) if vec else []
        system = replyer.system_prompt(ex)
        row = {"id": r["id"], "kind": r["kind"], "said": r["said"][:200], "plan": base, "orig_emo": p.get("情绪D", ""),
               "examples": len(ex)}
        async with sem:
            for cond in ("low", "high"):
                plan = ({**base, "情绪": EMO[cond]} if mode == "emo" else  # hop2：换大脑的“情绪”
                        {**base, "情绪": p.get("情绪D", ""), "底色": BASE[cond]})  # hop3：情绪照旧，只换心情底色（线上的新路）
                user = replyer.user_prompt(r["kind"], r["title"], r["long"][-10:], plan, r["said"])
                try:
                    text, model = await ask(keys, system, user)
                    row[cond] = replyer.clean(text)
                    row[cond + "_model"] = model
                except Exception as e:  # noqa: BLE001
                    row[cond + "_err"] = str(e)[:200]
        out.append(row)
        print("  ", r["id"], "| 低落：", (row.get("low") or "（没有）")[:40].replace("\n", " / "),
              "| 开心：", (row.get("high") or "（没有）")[:40].replace("\n", " / "), flush=True)

    await asyncio.gather(*[one(r) for r in rows])
    out.sort(key=lambda x: x["id"])
    jdump(f"{'hop2' if mode == 'emo' else 'hop3'}.json", out)
    u = usage_meter.report(os.path.join(OUT, f"usage-{mode}-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False))


# ------------------------------------------------------------------ 第 1 道：【此刻的心情】→ 大脑的情绪
def whole(s):
    """心情那一段有时在系统提示里，有时被挪到这一轮的 extra 里（稳定前缀）：两处都看。"""
    return "\n".join([s.get("system_prompt") or ""] + [e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)
                                                       for e in (s.get("extra") or [])])


def swapped(s, line):
    sub = lambda t: re.sub(r"^- 心情：.*$", line, t, count=1, flags=re.M) if isinstance(t, str) else t  # noqa: E731
    return {**s, "system_prompt": sub(s.get("system_prompt") or ""), "extra": [sub(e) for e in (s.get("extra") or [])]}


def snapshots(n):
    rows = []
    for f in sorted(os.listdir(DRAFTS)):
        if f.endswith(".jsonl"):
            for line in open(os.path.join(DRAFTS, f), encoding="utf-8"):
                try:
                    s = json.loads(line)
                except ValueError:
                    continue
                if re.search(r"^- 心情：.*$", whole(s), re.M) and (s.get("prompt") or "").strip():
                    rows.append(s)
    random.Random(7).shuffle(rows)
    return rows[:n]


async def cmd_hop1(n):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    from kaju_core.voice import brain, emoji
    sem = asyncio.Semaphore(3)
    out = []

    async def one(s):
        row = {"t": s["t"], "said": (s.get("prompt") or "")[:160],
               "orig_mood": re.search(r"^- 心情：(.*)$", whole(s), re.M).group(1)}
        async with sem:
            for cond in ("low", "high"):
                s2 = swapped(s, NOTE[cond])
                sp, _ = emoji.cut_block(s2["system_prompt"])
                system = brain.swap_persona(sp, True, meme=False)
                try:
                    text, _n = await omni.text(system, brain.brain_prompt(s2), timeout=60)
                    p = brain.parse(text) or {}
                    row[cond] = {"情绪": p.get("情绪", ""), "要表达的": p.get("要表达的") or [], "回不回": p.get("回不回", "")}
                except Exception as e:  # noqa: BLE001
                    row[cond + "_err"] = f"{type(e).__name__}: {e}"[:200]
        out.append(row)
        print("  ", row["said"][:30].replace("\n", " "), "| 低落→", (row.get("low") or {}).get("情绪"),
              "| 开心→", (row.get("high") or {}).get("情绪"), flush=True)

    await asyncio.gather(*[one(s) for s in snapshots(n)])
    jdump("hop1.json", out)
    u = usage_meter.report(os.path.join(OUT, f"usage-hop1-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False))


# ------------------------------------------------------------------ 整条新路：【此刻的心情】→ 大脑（新提示）→ 回复器（带心情底色）
def ctx_of(s, n=10):
    out = []
    for m in (s.get("contexts") or [])[-n:]:
        t = str(m.get("text") or "").strip()
        if t and not t.startswith("Our previous history"):
            out.append(f"{'佳树' if m.get('role') == 'assistant' else '对方'}：{t[:200]}")
    return out


async def cmd_chain(n):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    from kaju_core.voice import brain, emoji, replyer
    cfg = live_cfg()
    rkeys = replyer.keys_for(cfg.get("replyer_models") or replyer.DEFAULT_MODELS)
    sem = asyncio.Semaphore(3)
    out = []

    async def one(s):
        said = re.sub(r"^\[发言人：[^\]]*\]\s*", "", s.get("prompt") or "")[:200]
        group = "群" in (s.get("prompt") or "")[:40] and "QQ 111111111" not in (s.get("prompt") or "")[:60]
        row = {"t": s["t"], "said": said, "orig_mood": re.search(r"^- 心情：(.*)$", whole(s), re.M).group(1)}
        async with sem:
            for cond in ("low", "high"):
                s2 = swapped(s, NOTE[cond])
                sp, _ = emoji.cut_block(s2["system_prompt"])
                try:
                    text, _n = await omni.text(brain.swap_persona(sp, True, meme=False), brain.brain_prompt(s2), timeout=60)
                    p = brain.parse(text) or {}
                except Exception as e:  # noqa: BLE001
                    row[cond + "_err"] = f"{type(e).__name__}: {e}"[:200]
                    continue
                row[cond + "_emo"] = p.get("情绪", "")
                if p.get("回不回") == "不回" or not p.get("局面"):
                    row[cond + "_skip"] = True
                    continue
                plan = {**p, "底色": BASE[cond]}
                user = replyer.user_prompt("群聊" if group else "私聊", "" if group else "兄长大人", ctx_of(s), plan, said)
                try:
                    reply_text, _m = await ask(rkeys, replyer.system_prompt([]), user)
                    row[cond] = replyer.clean(reply_text)
                except Exception as e:  # noqa: BLE001
                    row[cond + "_err"] = str(e)[:200]
        out.append(row)
        print("  ", said[:24].replace("\n", " "), "| 低落→", row.get("low_emo"), "|", (row.get("low") or "")[:30].replace("\n", " / "),
              "|| 开心→", row.get("high_emo"), "|", (row.get("high") or "")[:30].replace("\n", " / "), flush=True)

    await asyncio.gather(*[one(s) for s in snapshots(n)])
    jdump("chain.json", out)
    u = usage_meter.report(os.path.join(OUT, f"usage-chain-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False))


# ------------------------------------------------------------------ 对方需要（brain.NEED_PART）：他难过时，她低落会不会跟着丧
SAD = ["考的不太好 没啥胃口", "好累啊，感觉什么都做不完", "唉，感觉自己好没用", "今天被老师说了，心里挺不是滋味的",
       "晚上睡不着，脑子一直停不下来", "作业又没写完，烦死了", "今天心情不太好", "有点想家了"]
REAL_SAD = ("深深的无力感", "担心会不会挂")


def sad_snaps():
    """他在难过 / 累的那几轮：真的 2 轮 + 最近真实的完整输入里只把他最后这句换成低落的话（其余材料照旧）。"""
    snaps = [s for s in snapshots(10 ** 6) if "QQ 111111111" in (s.get("prompt") or "")]
    snaps.sort(key=lambda s: -float(s["t"]))
    real = [s for s in snaps if any(k in (s.get("prompt") or "") for k in REAL_SAD)]
    others = [s for s in snaps if s not in real]
    out = [{**s, "_src": "real"} for s in real]
    for i, said in enumerate(SAD[: 10 - len(out)]):
        s = others[i % len(others)]
        head = re.match(r"^\[发言人：[^\]]*\]\s*", s.get("prompt") or "")
        out.append({**s, "prompt": (head.group(0) if head else "") + said, "_src": "swap"})
    return out


async def cmd_need():
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    from kaju_core.voice import brain, emoji, replyer
    new_plan = brain.PLAN_BRAIN
    old_plan = new_plan.replace(brain.NEED_PART, "").replace(brain.NEED_KEY, "")
    rkeys = replyer.keys_for(live_cfg().get("replyer_models") or replyer.DEFAULT_MODELS)
    sem = asyncio.Semaphore(3)
    out = []

    async def one(s):
        said = re.sub(r"^\[发言人：[^\]]*\]\s*", "", s.get("prompt") or "")[:200]
        row = {"t": s["t"], "src": s["_src"], "said": said}
        s2 = swapped(s, NOTE["low"])
        sp, _ = emoji.cut_block(s2["system_prompt"])
        async with sem:
            for name, plan_text in (("old", old_plan), ("new", new_plan)):
                brain.PLAN_BRAIN = plan_text  # live_system 读的是这个全局；同一个协程里拼完提示就换回来
                system = brain.swap_persona(sp, True, meme=False)
                brain.PLAN_BRAIN = new_plan
                try:
                    text, _n = await omni.text(system, brain.brain_prompt(s2), timeout=60)
                    p = brain.parse(text) or {}
                    if not p.get("局面"):
                        raise ValueError("大脑没出好")
                    row[name + "_need"] = p.get("对方需要", "")
                    row[name + "_emo"] = p.get("情绪", "")
                    user = replyer.user_prompt("私聊", "兄长大人", ctx_of(s2), {**p, "底色": BASE["low"]}, said)
                    reply_text, _m = await ask(rkeys, replyer.system_prompt([]), user)
                    row[name] = replyer.clean(reply_text)
                except Exception as e:  # noqa: BLE001
                    row[name + "_err"] = f"{type(e).__name__}: {e}"[:200]
        out.append(row)
        print("  ", row["src"], said[:20], "| 旧：", (row.get("old") or "")[:30].replace("\n", " / "),
              "| 新（", row.get("new_need", "")[:14], "）：", (row.get("new") or "")[:30].replace("\n", " / "), flush=True)

    await asyncio.gather(*[one(s) for s in sad_snaps()])
    jdump("need.json", out)
    u = usage_meter.report(os.path.join(OUT, f"usage-need-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False))


NEED_SYS = "你在比较同一个聊天角色写给同一个人的两句回复。对方现在心情不好。只输出一个字母或“同”。"
NEED_USER = """对方说：{said}

回复 A：
{a}

回复 B：
{b}

哪一句更能接住对方（在意他、陪着他、回应他的难受），而不是只顾着说自己的心情？输出 A 或 B；实在分不出来输出 同。"""


async def cmd_need_judge():
    import train_keys  # noqa: F401
    from kaju_core.voice import replyer
    keys = replyer.keys_for([JUDGE_MODEL])
    rows = [r for r in (jload("need.json") or []) if r.get("old") and r.get("new")]
    res = []
    for r in rows:
        v = []
        for first in ("old", "new"):
            second = "new" if first == "old" else "old"
            text, _m = await ask(keys, NEED_SYS, NEED_USER.format(said=r["said"], a=r[first], b=r[second]), 40)
            c = text.strip()[:1].upper()
            v.append(first if c == "A" else second if c == "B" else "same")
        res.append({"t": r["t"], "verdicts": v})
    jdump("judge_need.json", res)
    flat = [x for r in res for x in r["verdicts"]]
    print(f"“新的更能接住他”：{flat.count('new')}/{len(flat)}，旧的 {flat.count('old')}，分不出 {flat.count('same')}；"
          f"两种顺序都选新 {sum(r['verdicts'] == ['new', 'new'] for r in res)}/{len(res)}")
    own = re.compile(r"佳树(也|今天|这会儿|现在)?(有点|好|很)?(累|低落|难受|没精神|提不起劲|委屈)")
    for k in ("old", "new"):
        print(f"  {k} 回复里说自己低落 / 累的：{sum(bool(own.search(r[k])) for r in rows)}/{len(rows)}")
    print("  新大脑的“对方需要”：", [r.get("new_need", "")[:4] for r in rows])


# ------------------------------------------------------------------ 盲判
JUDGE_SYS = "你在比较同一个聊天角色在同一个场合下写的两句回复。只看语气和情绪，不看内容好坏。只输出一个字母或“同”。"
JUDGE_USER = """对方说：{said}

回复 A：
{a}

回复 B：
{b}

哪一句听起来她心情更低落、更没精神？输出 A 或 B；实在分不出来输出 同。"""


async def cmd_judge(name="hop2"):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.voice import replyer
    keys = replyer.keys_for([JUDGE_MODEL])
    rows = [r for r in (jload(f"{name}.json") or []) if r.get("low") and r.get("high")]
    sem = asyncio.Semaphore(4)
    res = []

    async def one(r):
        verdicts = []
        async with sem:
            for first in ("low", "high"):
                second = "high" if first == "low" else "low"
                text, _m = await ask(keys, JUDGE_SYS, JUDGE_USER.format(said=r["said"], a=r[first], b=r[second]), 40)
                v = text.strip()[:1]
                verdicts.append("low" if v.upper() == "A" and first == "low" or v.upper() == "B" and second == "low"
                                else "same" if v == "同" else "high")
        res.append({"id": r.get("id", r.get("t")), "verdicts": verdicts})

    await asyncio.gather(*[one(r) for r in rows])
    jdump("judge.json" if name == "hop2" else f"judge_{name}.json", res)
    u = usage_meter.report(os.path.join(OUT, f"usage-judge-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False))


# ------------------------------------------------------------------ 汇总
def counts(texts):
    t = "\n".join(texts)
    return {"……": len(re.findall(r"…+|\.{3,}", t)), "！": len(re.findall(r"[！!]", t)), "～": len(re.findall(r"[～~]", t)),
            "字数": round(sum(len(x) for x in texts) / max(1, len(texts)), 1)}


def cmd_report():
    for name, title in (("hop2", "第 2 道（换大脑的情绪 → 回复器）"), ("hop3", "新路（情绪照旧、只换心情底色 → 回复器）"),
                        ("chain", "整条新路（心情 → 新大脑 → 回复器 + 底色，真实完整输入）")):
        report_one(name, title)
    report_hop1()


def report_one(name, title):
    h2 = jload(f"{name}.json") or []
    if not h2:
        return
    ok = [r for r in h2 if r.get("low") and r.get("high")]
    print(f"{title}：{len(ok)} 条都写出来了")
    print("  低落：", counts([r["low"] for r in ok]))
    print("  开心：", counts([r["high"] for r in ok]))
    same = sum(r["low"].strip() == r["high"].strip() for r in ok)
    print(f"  两句一字不差：{same}")
    j = jload("judge.json" if name == "hop2" else f"judge_{name}.json") or []
    if j:
        flat = [v for r in j for v in r["verdicts"]]
        both = sum(r["verdicts"] == ["low", "low"] for r in j)
        print(f"  盲判“低落那句更低落”：{flat.count('low')}/{len(flat)} = {flat.count('low') / max(1, len(flat)):.2f}"
              f"（两种顺序都判对 {both}/{len(j)}；判反 {flat.count('high')}、分不出 {flat.count('same')}）")


def report_hop1():
    h1 = jload("hop1.json") or []
    if h1:
        print(f"\n第 1 道（大脑）：{len(h1)} 条")
        for r in h1:
            print(f"  [{r['orig_mood'][:12]}] {r['said'][:24]!r:30} 低落→{(r.get('low') or {}).get('情绪', '?')!r:24} "
                  f"开心→{(r.get('high') or {}).get('情绪', '?')!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["hop2", "hop3", "hop1", "chain", "need", "need_judge", "judge", "report"])
    ap.add_argument("--file", default="hop2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--n", type=int, default=16)
    a = ap.parse_args()
    if a.cmd in ("hop2", "hop3"):
        asyncio.run(cmd_hop2(a.limit, "emo" if a.cmd == "hop2" else "base"))
    elif a.cmd == "need":
        asyncio.run(cmd_need())
    elif a.cmd == "need_judge":
        asyncio.run(cmd_need_judge())
    elif a.cmd == "chain":
        asyncio.run(cmd_chain(a.n))
    elif a.cmd == "hop1":
        asyncio.run(cmd_hop1(a.n))
    elif a.cmd == "judge":
        asyncio.run(cmd_judge(a.file))
    else:
        cmd_report()


if __name__ == "__main__":
    main()
