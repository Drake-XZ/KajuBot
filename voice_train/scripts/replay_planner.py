r"""第二阶段第 1 步：真规划器回放（2026-11-16，AGENT.md）。

线上影子规划器（kaju_core\voice\shadow.py）每一轮都写了一份回复指导（局面 / 要回应的 / 事实 / 背景），只记不发。
这里把指导直接当成写手的卡，和当时真正发出去的那句比：
  A 线上    当时发出去的那句（线上写手 + Gemini 从草稿抽的卡）
  B 线上写手 + 规划器卡
  C 第 3 轮写手（kaju-writer-p4-8b-r3，见过“背景”一行）+ 规划器卡
规划器卡（v5 格式，和第 3 轮训练一样）：
  场合 / 对象 照当时；局面 = 指导的局面 + “要接住的：要回应的”；要说到的 = 事实（没有就“无”）；
  背景 = 指导的背景（没有就不加这一行）；心情 = 当时那张卡的心情行。规划器没见过草稿。

  plan   [--redo 全部用现在的提示词重跑到 replay3\plans_v3\]
         11-13 有主模型输入、但影子规划器还没上线的（群聊“食指”那几轮）补跑一遍规划器 → replay3\plans_offline\
  cards  拼规划器卡 → replay3\cards.json
  write  B、C 各写一遍 → replay3\write.json（要显卡；写时挂 gpu_busy，群里先不回）
  page   三选一盲选页 review\replay3_abc.html（collection votes；对照 replay3\key.json）
用法：python -I -X utf8 scripts\replay_planner.py plan|cards|write|page|all
"""
import argparse
import asyncio
import datetime as dt
import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_train as rt  # noqa: E402  sys.path / KAJU_DATA、write()、lines()

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay3")
STYLE = r"D:\JiashuBot\kaju_data\self\kaju_style"
TZ = dt.timezone(dt.timedelta(hours=8))
NEW = "kaju-writer-p4-8b-r3"
# 11-16 晚加：--dir / --new / --tag 做第 4 次回放（replay4，PLAN v4，第 5 轮写手）。
# PLAN_SUB 不是 plans_v3 时，只用这个目录里重跑出来的指导（整次回放同一版提示词），不和线上存的旧版混。
PLAN_SUB = "plans_v3"
TAG = "rp3"


def jl_dir(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
        out += rt.jl(p)
    return out


def records(any_model=False):
    """线上发出去了的、卡是 v4 的记录（t → 记录）。any_model：不管当时是哪个写手写的（11-17 r6 上线后，
    以前 p4-8b-k 写的那些就不算“线上写手”的了，规划器对比 / 造数据要的是全部）。"""
    model = rt.state()["live_model"]
    out = {}
    for d in jl_dir(os.path.join(STYLE, "rewrites")):
        if (not any_model and (d.get("config") or {}).get("card_model") != model) or d.get("outcome") != "used" or not d.get("final"):
            continue
        card = ((d.get("card") or [{}])[-1].get("card") or "")
        if "局面：" in card:
            out[str(d["t"])] = d
    return out


def plans():
    """线上影子规划器的 + 补跑的；有用现在的提示词重跑过的（plans_v3）就用重跑的。"""
    out = {}
    src = (jl_dir(os.path.join(STYLE, "plans")) + jl_dir(os.path.join(D, "plans_offline")) + jl_dir(os.path.join(D, "plans_v3"))
           if PLAN_SUB == "plans_v3" else jl_dir(os.path.join(D, PLAN_SUB)))
    for d in src:
        if d.get("plan"):
            out[str(d["t"])] = d["plan"]
    return out


async def do_plan(redo=False):
    import train_keys  # noqa: F401  KAJU_DATA、bot_setup 进 sys.path（omni.text 用 gemini_keys.json）
    from kaju_core.voice import shadow
    recs, have = records(), plans()
    if redo:  # 全部用现在的 shadow.PLAN 重跑一遍（这一轮回放都用同一版提示词）
        done = {str(d["t"]) for d in jl_dir(os.path.join(D, PLAN_SUB)) if d.get("plan")}
        have = done
    todo = [s for s in jl_dir(os.path.join(STYLE, "draft_inputs"))
            if str(s["t"]) in recs and str(s["t"]) not in have and (s.get("system_prompt") or s.get("contexts"))]
    print(f"补跑规划器 {len(todo)} 条", flush=True)
    sem = asyncio.Semaphore(3)

    async def one(s):
        async with sem:
            rec = recs[str(s["t"])]
            row = await shadow.run(s, rec, os.path.join(D, PLAN_SUB if redo else "plans_offline"), TZ, 60, print)
            print("  ", s["t"], "好" if row.get("plan") else ("没出好 " + str(row.get("error") or row.get("raw"))[:80]), flush=True)

    await asyncio.gather(*[one(s) for s in todo])


def mood_of(card):
    from kaju_core.heart.mood_line import normalize  # 11-16 晚以前的记录是旧写法，转成合并后的
    return normalize(next((x for x in card.splitlines() if x.startswith("心情：")), ""))


def plan_card(rec, p):
    jm = p["局面"].rstrip("。")
    if p.get("要回应的"):
        jm += "。要接住的：" + p["要回应的"].rstrip("。")
    lines = [f"场合：{rec.get('kind') or '私聊'}", f"对象：{rec.get('title') or '无'}", f"局面：{jm}",
             "要说到的：" + ("；".join(x.rstrip("。；;") for x in p.get("事实") or []) or "无")]
    if p.get("背景"):
        lines.append("背景：" + "；".join(x.rstrip("。；;") for x in p["背景"][:3]))
    m = mood_of(((rec.get("card") or [{}])[-1].get("card") or ""))
    if m:
        lines.append(m)
    return "\n".join(lines)


def do_cards():
    recs, ps = records(), plans()
    rows = []
    for t, p in ps.items():
        rec = recs.get(t)
        if not rec:
            continue
        rows.append({"id": t, "kind": rec.get("kind") or "私聊", "to": rec.get("title") or "", "ctx": rec.get("ctx") or [],
                     "draft": rec.get("draft") or "", "card_a": (rec.get("card") or [{}])[-1].get("card") or "",
                     "plan": p, "card_p": plan_card(rec, p), "out_a": rec["final"]})
    rows.sort(key=lambda r: float(r["id"]))
    os.makedirs(D, exist_ok=True)
    json.dump(rows, open(os.path.join(D, "cards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_f = sum(1 for r in rows if r["plan"].get("事实"))
    n_b = sum(1 for r in rows if r["plan"].get("背景"))
    print(f"规划器卡 {len(rows)} 张（私聊 {sum(r['kind'] != '群聊' for r in rows)}、群聊 {sum(r['kind'] == '群聊' for r in rows)}）；"
          f"有事实 {n_f}、有背景 {n_b}", flush=True)


def do_write():
    from kaju_core import gpu_busy
    rows = json.load(open(os.path.join(D, "cards.json"), encoding="utf-8"))
    live = rt.state()["live_model"]
    gpu_busy.mark("规划器回放（写手各写一遍）")
    try:
        for model, k in ((live, "b"), (NEW, "c")):  # 一个模型写完再换下一个，少来回加载
            for i, r in enumerate(rows):
                r[f"out_{k}"] = rt.write(model, r["ctx"], r["card_p"])
                if (i + 1) % 10 == 0:
                    print(f"  {k.upper()} 写了 {i + 1}/{len(rows)}", flush=True)
        rt.ollama_unload()
    finally:
        gpu_busy.clear()
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写完 {len(rows)} 条；B 空 {sum(not r['out_b'] for r in rows)}、C 空 {sum(not r['out_c'] for r in rows)}", flush=True)


def guide_text(r):
    p = r["plan"]
    s = [f"局面：{p['局面']}"]
    if p.get("要回应的"):
        s.append(f"要接住的：{p['要回应的']}")
    s.append("事实：" + ("；".join(p.get("事实") or []) or "无"))
    if p.get("背景"):
        s.append("背景：" + "；".join(p["背景"][:3]))
    return "\n".join(s)


def do_page(n_max):
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(20261116)
    rows = [r for r in rows if r["out_a"] and r["out_b"] and r["out_c"]
            and len({rt.lines(r["out_a"]), rt.lines(r["out_b"]), rt.lines(r["out_c"])}) == 3]
    grp = [r for r in rows if r["kind"] == "群聊"]
    prv = [r for r in rows if r["kind"] != "群聊"]
    rng.shuffle(prv)
    pick = (grp + prv)[:n_max]
    rng.shuffle(pick)
    page, key = [], {}
    for r in pick:
        order = ["a", "b", "c"]
        rng.shuffle(order)
        iid = f"{TAG}-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "C": order[2], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["to"] or "无",
                     "ctx": r["ctx"][-6:] or ["（没有前文）"], "draft": guide_text(r),
                     **{s: {"text": r[f"out_{order[i]}"]} for i, s in enumerate("ABC")}})
    json.dump(key, open(os.path.join(D, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "abc.template.html"), encoding="utf-8").read()
    tpl = (tpl.replace("<title>三种卡盲选</title>", "<title>规划器回放三选一</title>")
              .replace("<h1>三种卡盲选</h1>", "<h1>规划器回放三选一</h1>")
              .replace("同一句话、同一个线上写手，只是交给她的卡不一样，写出三句。",
                       "同一句话的三种回法：一句是当时线上真的发出去的，两句是写手只看规划器的指导写的（规划器没看草稿）。")
              .replace("灰框里是她当时的草稿（三张卡都从它来），想看再点开。", "灰框里是规划器写的指导，想看再点开。")
              .replace('"她当时的草稿"', '"规划器的指导"'))
    html = os.path.join(rt.VT, "review", f"{os.path.basename(D)}_abc.html")
    open(html, "w", encoding="utf-8", newline="\n").write(tpl.replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：{len(page)} 条（私聊 {sum(p['src'] == 'private' for p in page)}、群聊 {sum(p['src'] == 'group' for p in page)}；"
          f"三句都不同的 {len(rows)} 条里挑）", flush=True)


def main():
    global D, NEW, PLAN_SUB, TAG
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "cards", "write", "page", "all"])
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--redo", action="store_true", help="plan：全部用现在的提示词重跑到 plans_v3（或 --plans-sub）")
    ap.add_argument("--dir", default="replay3", help="data\\rounds_v4 下的目录")
    ap.add_argument("--new", default=NEW, help="C 那句用哪个写手")
    ap.add_argument("--plans-sub", default="plans_v3")
    ap.add_argument("--tag", default="rp3", help="盲选页每条的编号前缀")
    a = ap.parse_args()
    D, NEW, PLAN_SUB, TAG = os.path.join(rt.ROOT, a.dir), a.new, a.plans_sub, a.tag
    if a.cmd in ("plan", "all"):
        asyncio.run(do_plan(a.redo))
    if a.cmd in ("cards", "all"):
        do_cards()
    if a.cmd in ("write", "all"):
        do_write()
    if a.cmd in ("page", "all"):
        do_page(a.n)


if __name__ == "__main__":
    main()
