r"""主模型当规划器（“大脑”）回放（2026-11-17 兄长：“Start the trial”；AGENT.md 第十节，方案第 1 步）。

和 replay6 同样那 52 轮真实对话（replay6\items.json：长前文已按线上做法重建），同一个写手 r7k（系统提示 v5、长前文）：
  A  现在线上的卡（从草稿摘的）——直接用 replay6\write.json 里 r7k 已经写好的那句（同卡同写手，不重写）
  B  大脑卡：kaju_core\voice\brain.py 的 PLAN_BRAIN 看主模型这一轮的材料（**没有草稿**、没有原来那份扮演佳树的人设）
     → 标签式“要表达的”（意图：关键信息，不是正文）→ brain.card_of 排成卡
限制：离线重跑不了工具；当时草稿里用了工具查到的东西，B 这边是没有的。走的是出卡那条模型链（model_router tasks.card），不是 AstrBot 主模型那条。

  plan   [--limit N 只跑前 N 条试试]  → replay7\plans.jsonl（跑过的跳过；usage_meter 估钱）
  show   打印几条看看（指导、卡、像不像正文）
  write  B 写一遍（本机显卡，gpu_busy.hold）→ replay7\write.json
  page   盲选页 review\replay7_ab.html（collection votes；答案 replay7\key.json）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\replay_brain.py plan|show|write|page
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import prepare_r7 as p7  # noqa: E402
import replay_b as rb  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay7")
R6 = os.path.join(rt.ROOT, "replay6")


def items():
    return json.load(open(os.path.join(R6, "items.json"), encoding="utf-8"))


async def cmd_plan(limit):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    from kaju_core.voice import brain
    its = items()[:limit] if limit else items()
    snaps = {str(s["t"]): s for s in rb.jl_dir(os.path.join(rb.STYLE, "draft_inputs"))}
    os.makedirs(D, exist_ok=True)
    path = os.path.join(D, "plans.jsonl")
    done = {d["id"] for d in (p7.jl(path) if os.path.exists(path) else []) if d.get("plan")}
    todo = [i for i in its if i["id"] not in done]
    print(f"大脑要跑 {len(todo)} 条（跑过的 {len(done)}）", flush=True)
    sem = asyncio.Semaphore(3)

    async def one(it):
        async with sem:
            t0 = time.time()
            try:
                out, n = await omni.text(brain.PLAN_BRAIN, brain.brain_prompt(snaps[it["id"]]), timeout=60)
                p = brain.parse(out)
                row = {"id": it["id"], "plan": p, "raw": None if p else (out or "")[:500], "key": n}
            except Exception as e:  # noqa: BLE001
                row = {"id": it["id"], "plan": None, "error": f"{type(e).__name__}: {e}"[:200]}
            row["ms"] = int((time.time() - t0) * 1000)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("  ", it["id"], it["kind"], "好" if row.get("plan") else "没出好", row["ms"], flush=True)

    await asyncio.gather(*[one(i) for i in todo])
    u = usage_meter.report(os.path.join(D, f"usage-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)


def plans():
    p = os.path.join(D, "plans.jsonl")
    return {d["id"]: d["plan"] for d in (p7.jl(p) if os.path.exists(p) else []) if d.get("plan")}


def cmd_show(n):
    from kaju_core.voice import brain
    its = {i["id"]: i for i in items()}
    ps = plans()
    flat = [x for p in ps.values() for x in p.get("要表达的") or []]
    print(f"指导 {len(ps)} 份；要表达的共 {len(flat)} 条，像正文的 {sum(map(brain.sentence_like, flat))} 条；"
          f"“无” {sum(not p.get('要表达的') for p in ps.values())} 份；不回 {sum(p.get('回不回') == '不回' for p in ps.values())} 份")
    for k, p in list(ps.items())[:n]:
        it = its[k]
        print("=====", it["kind"], it["title"], "|", it["said"][:60].replace("\n", " / "))
        print(brain.card_of(it["kind"], it["title"], p, it["mood"]))
        print("  情绪:", p.get("情绪"), "| 回不回:", p.get("回不回"))
        bad = [x for x in p.get("要表达的") or [] if brain.sentence_like(x)]
        if bad:
            print("  像正文:", bad)


def cmd_write():
    from kaju_core import gpu_busy
    from kaju_core.voice import brain
    a_rows = {r["id"]: r for r in json.load(open(os.path.join(R6, "write.json"), encoding="utf-8"))}
    ps = plans()
    rows = []
    with gpu_busy.hold("大脑回放（r7k 照大脑卡写）"):
        for i, it in enumerate(items()):
            p = ps.get(it["id"])
            a = a_rows.get(it["id"])
            if not p or not a:
                continue
            card_b = brain.card_of(it["kind"], it["title"], p, it["mood"])
            rows.append(dict(it, plan=p, card_b=card_b, out_a=a["out_a"], out_b=rb.write5(it["long"], card_b, it["draft"], it["title"])))
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}", flush=True)
        rt.ollama_unload()
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写完 {len(rows)} 条；B 空 {sum(not r['out_b'] for r in rows)}", flush=True)


def cmd_page(n_max):
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(201711)
    ab = [r for r in rows if r["out_a"] and r["out_b"] and rt.lines(r["out_a"]) != rt.lines(r["out_b"])]
    rng.shuffle(ab)
    ab = ([r for r in ab if r["kind"] == "群聊"] + [r for r in ab if r["kind"] != "群聊"])[:n_max]
    rng.shuffle(ab)
    page, key = [], {}
    for r in ab:
        order = ["a", "b"]
        rng.shuffle(order)
        iid = f"rp7-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["title"] or "无",
                     "ctx": r["long"][-10:], "draft": r["draft"], "draft_label": "她当时的草稿（只给你参考；大脑卡那边没看过草稿）",
                     "A": {"text": r[f"out_{order[0]}"], "blocked": ""}, "B": {"text": r[f"out_{order[1]}"], "blocked": ""}})
    quiet = [r for r in rows if r["kind"] == "群聊" and r["plan"].get("回不回") == "不回" and r["out_a"]]
    for r in quiet:
        iid = f"rp7q-{len(page) + 1}"
        key[iid] = {"single": "quiet", "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group", "to": r["title"] or "无", "single": True,
                     "ctx": r["long"][-10:], "draft": r["plan"].get("局面") or "", "draft_label": "大脑看到的局面",
                     "A": {"text": r["out_a"], "blocked": ""}})
    json.dump(key, open(os.path.join(D, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    reps = [("同一句话，现在线上的写手写一遍，这一轮本机微调出来的新写手写一遍；两边用同一张卡。",
             "线上真实的轮次，同一个写手（现在线上的 r7k，看长聊天）写两遍：一遍用现在线上的卡（从草稿里摘的），"
             "一遍用“大脑”的卡（大模型不写她的话，只想清楚这一轮要表达什么，写成“回答：…”“立场：…”这种标签）。"),
            ('const SINGLE = [["good", "可以发"], ["meh", "还行"], ["bad", "不好"]];', 'const SINGLE = [["reply", "该回"], ["skip", "不回也行"]];'),
            ('box.querySelector("h2").textContent = "新写手";', 'box.querySelector("h2").textContent = "她会回的话";'),
            ('"看完感想（只看新写手）"', '"大脑说这句可以不回（群聊）"'),
            ("兄长大人发了视频或歌给她、或者问她刚才刷到什么。上面的灰框是你第八批写的那版，只作参考。",
             "群里这一句大脑判“可以不回”。看聊天，你觉得她该回吗？（下面是她不管的话会回的那句）")]
    for a, b in reps:
        if a not in tpl:
            print("模板里没找到：", a[:30])
        tpl = tpl.replace(a, b)
    html = os.path.join(rt.VT, "review", "replay7_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "大脑卡 · 回放盲选").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：对比 {len(ab)} 对（私聊 {sum(r['kind'] != '群聊' for r in ab)}、群聊 {sum(r['kind'] == '群聊' for r in ab)}）"
          f" + 该不该回 {len(quiet)} 条", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "show", "write", "page"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    if a.cmd == "plan":
        asyncio.run(cmd_plan(a.limit))
    elif a.cmd == "show":
        cmd_show(a.n)
    elif a.cmd == "write":
        cmd_write()
    else:
        cmd_page(a.n)


if __name__ == "__main__":
    main()
