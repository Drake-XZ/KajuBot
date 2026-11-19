r"""B 那条路回放（2026-11-17，兄长：“Start route B”；AGENT.md 第十节）。

线上记下来的真实轮次（rewrites + draft_inputs），同一个写手 r7k（系统提示 v5、长前文）各写一遍：
  A  现在线上的卡：当时 Gemini 从草稿摘的那张（卡照当时记下的；心情行转成现在的写法）
  B  规划器卡：shadow.LIVE_PLAN（PLAN v7）看主模型的完整输入 + 草稿（只当材料）出指导 → shadow.card_of 排成卡
长前文：照线上 mind._long_ctx 的做法从 kaju_life 聊天记录重建（这一句之前、带时间日期，longctx.from_log）。
群聊里规划器说“不回”的，盲选页另问一句“该回 / 不回也行”。

  prep   挑轮次、重建长前文 → data\rounds_v4\replay6\items.json（不花钱）
  plan   规划器出指导（花钱：model_router tasks.card 动态挑；usage_meter 估）→ replay6\plans.jsonl（跑过的跳过）
  write  A、B 各写一遍（本机显卡；gpu_busy.hold，群里不说话）→ replay6\write.json
  page   盲选页 review\replay6_ab.html（collection votes；答案 replay6\key.json）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\replay_b.py prep|plan|write|page [--limit N]
"""
import argparse
import asyncio
import datetime as dt
import glob
import json
import os
import random
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402  sys.path（bot_setup）、KAJU_DATA、lines()、ollama_unload()
import prepare_r7 as p7  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay6")
STYLE = r"D:\JiashuBot\kaju_data\self\kaju_style"
TZ = dt.timezone(dt.timedelta(hours=8))
MODEL = "kaju-writer-p6-8b-r7k"
OLLAMA = "http://127.0.0.1:11435"


def jl_dir(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
        out += p7.jl(p)
    return out


def mood_of(card_text):
    from kaju_core.heart.mood_line import normalize  # 11-16 晚以前的记录是旧写法
    return normalize(next((x for x in card_text.splitlines() if x.startswith("心情：")), ""))


def addr_maker():
    by_uid, groups, addr = p7.scrub_names()
    os.environ.setdefault("KAJU_DATA", os.path.dirname(p7.SELF))
    from kaju_core import people
    owner = people.owner()
    assert owner, "身份表里没认出兄长"
    folks = json.load(open(os.path.join(p7.SELF, "address_book", "people.json"), encoding="utf-8"))

    def addr_of(uid, name):  # 和 prepare_r7.cmd_ctx 的一样（= 线上称呼簿 address_of）
        uid = str(uid or "")
        if uid == "self":
            return "佳树"
        if uid == owner:
            return "兄长大人"
        v = addr.get(uid) or {}
        if v.get("address") and "兄长" not in v["address"]:
            return v["address"]
        p = folks.get(uid) or {}
        known = [re.sub(r"\s+", "", n) for n in (name, p.get("name"), v.get("nickname")) if n and re.sub(r"\s+", "", n) != uid]
        return (known[0] if known else "") + ("学姐" if p.get("sex") == "female" else "学长")
    return addr_of


def long_ctx(rec, chats, addr_of):
    """照线上 _long_ctx：这个聊天里、这一句（rec 的 said）之前的记录 → longctx.from_log。对不上返回 None。"""
    from kaju_core.voice import longctx
    umo = str(rec.get("umo") or "")
    parts = umo.split(":")
    if len(parts) < 3:
        return None
    chat = ("g" if "Group" in parts[1] else "p") + parts[-1]
    t = float(rec["t"])
    rs = []
    for day, _, r in chats.get(chat, []):
        try:
            ts = dt.datetime.strptime(f"{day} {r.get('t')}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()
        except (TypeError, ValueError):
            continue
        if ts <= t + 59:
            rs.append(dict(r, d=day))
    if not rs:
        return None
    rs = rs[-(longctx.MAX_LINES + 20):]
    now = (rec.get("said") or "").strip()

    def same(x):
        x = x.strip()
        return bool(x) and (x == now or x in now or (len(now) >= 6 and now[:30] in x))
    end = next((i for i in range(len(rs) - 1, -1, -1) if str(rs[i].get("u")) != "self" and same(str(rs[i].get("x") or ""))), None)
    if end is None:
        return None
    uid = str(rs[end].get("u"))
    while end > 0 and str(rs[end - 1].get("u")) == uid and str(rs[end - 1].get("x") or "").strip() \
            and str(rs[end - 1].get("x")).strip() in now:  # 连发合并：退到这一串的第一条（和线上 mind._ctx_end 一样）
        end -= 1
    hit = rs[end]
    last = (rec.get("ctx") or [""])[-1]
    who, cur = (last.split("：", 1) + [""])[:2] if "：" in last else (rec.get("title") or "", now)
    return longctx.from_log(rs[:end], addr_of, current=(hit.get("d"), hit.get("t"), rec.get("title") or who, cur))


def cmd_prep(limit):
    snaps = {str(s["t"]): s for s in jl_dir(os.path.join(STYLE, "draft_inputs"))}
    addr_of = addr_maker()
    chats = p7.by_chat(p7.logs())
    items, miss = [], {"没输入": 0, "长前文对不上": 0}
    for r in jl_dir(os.path.join(STYLE, "rewrites")):
        card_a = ((r.get("card") or [{}])[-1].get("card") or "")
        if r.get("src") != "reply" or r.get("outcome") != "used" or not r.get("final") or "局面：" not in card_a:
            continue
        if str(r["t"]) not in snaps:
            miss["没输入"] += 1
            continue
        lc = long_ctx(r, chats, addr_of)
        if not lc:
            miss["长前文对不上"] += 1
            continue
        m = mood_of(card_a)
        card_a = "\n".join([x for x in card_a.splitlines() if not x.startswith("心情：")] + ([m] if m else []))
        items.append({"id": str(r["t"]), "kind": r.get("kind") or "私聊", "title": r.get("title") or "", "said": r.get("said") or "",
                      "ctx": r.get("ctx") or [], "long": lc, "draft": r.get("draft") or "", "card_a": card_a, "mood": m,
                      "live_final": r.get("final"), "live_model": (r.get("config") or {}).get("card_model")})
    items.sort(key=lambda x: float(x["id"]))
    if limit:
        items = items[-limit:]
    os.makedirs(D, exist_ok=True)
    json.dump(items, open(os.path.join(D, "items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chars = [len(json.dumps(snaps[i["id"]], ensure_ascii=False)) for i in items]
    print(f"轮次 {len(items)}（私聊 {sum(i['kind'] != '群聊' for i in items)}、群聊 {sum(i['kind'] == '群聊' for i in items)}）；跳过 {miss}；"
          f"规划器输入字数中位 {sorted(chars)[len(chars) // 2] if chars else 0}", flush=True)


async def cmd_plan():
    import train_keys  # noqa: F401  KAJU_DATA、bot_setup 进 sys.path（omni.text 用 gemini_keys.json）
    import usage_meter
    usage_meter.patch()
    from kaju_core.voice import shadow
    items = json.load(open(os.path.join(D, "items.json"), encoding="utf-8"))
    snaps = {str(s["t"]): s for s in jl_dir(os.path.join(STYLE, "draft_inputs"))}
    path = os.path.join(D, "plans.jsonl")
    done = {d["id"] for d in (p7.jl(path) if os.path.exists(path) else []) if d.get("plan")}
    todo = [i for i in items if i["id"] not in done]
    print(f"规划器要跑 {len(todo)} 条（跑过的 {len(done)}）", flush=True)
    sem = asyncio.Semaphore(3)

    async def one(it):
        async with sem:
            s = dict(snaps[it["id"]])
            t0 = time.time()
            try:
                p, out, n = await shadow.plan_live(s, it["draft"], 60)
                row = {"id": it["id"], "plan": p, "raw": None if p else out[:500], "key": n}
            except Exception as e:  # noqa: BLE001
                row = {"id": it["id"], "plan": None, "error": f"{type(e).__name__}: {e}"[:200]}
            row["ms"] = int((time.time() - t0) * 1000)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("  ", it["id"], it["kind"], "好" if row.get("plan") else "没出好", (row.get("plan") or {}).get("回不回", ""), row["ms"], flush=True)

    await asyncio.gather(*[one(i) for i in todo])
    u = usage_meter.report(os.path.join(D, f"usage-{time.strftime('%H%M')}.json"))
    print("估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)


def write5(ctx, card_text, draft, title):
    from kaju_core.voice import card, rewrite
    body = {"model": MODEL, "temperature": 0.7, "top_p": 0.9, "max_tokens": 1024, "reasoning_effort": "none",
            "messages": [{"role": "system", "content": card.SYSTEM_V5}, {"role": "user", "content": card.write_prompt_v4(ctx, card_text)}]}
    req = urllib.request.Request(OLLAMA + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = rewrite.clean_output(json.load(r)["choices"][0]["message"]["content"]).strip()
            out = card.fix_formal(out, draft, title)
            if out and not card.loops(out):
                return out
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return ""


def cmd_write():
    from kaju_core import gpu_busy
    from kaju_core.voice import shadow
    items = json.load(open(os.path.join(D, "items.json"), encoding="utf-8"))
    plans = {d["id"]: d["plan"] for d in p7.jl(os.path.join(D, "plans.jsonl")) if d.get("plan")}
    rows = []
    with gpu_busy.hold("规划器回放（B 那条路，r7k 各写一遍）"):
        for i, it in enumerate(items):
            p = plans.get(it["id"])
            if not p:
                continue
            card_b = shadow.card_of(it["kind"], it["title"], p, it["mood"])
            rows.append(dict(it, plan=p, card_b=card_b, out_a=write5(it["long"], it["card_a"], it["draft"], it["title"]),
                             out_b=write5(it["long"], card_b, it["draft"], it["title"])))
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}/{len(items)}", flush=True)
        rt.ollama_unload()
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写完 {len(rows)} 条；A 空 {sum(not r['out_a'] for r in rows)}、B 空 {sum(not r['out_b'] for r in rows)}；"
          f"群里规划器说不回 {sum(r['kind'] == '群聊' and r['plan'].get('回不回') == '不回' for r in rows)}", flush=True)


def cmd_page(n_max):
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(20261117)
    ab = [r for r in rows if r["out_a"] and r["out_b"] and rt.lines(r["out_a"]) != rt.lines(r["out_b"])]
    rng.shuffle(ab)
    ab = ([r for r in ab if r["kind"] == "群聊"] + [r for r in ab if r["kind"] != "群聊"])[:n_max]  # 群聊少，全放
    rng.shuffle(ab)
    page, key = [], {}
    for r in ab:
        order = ["a", "b"]
        rng.shuffle(order)
        iid = f"rp6-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["title"] or "无",
                     "ctx": r["long"][-10:], "draft": r["draft"], "draft_label": "她当时的草稿（主模型写的；两边的卡都从这一轮来）",
                     "A": {"text": r[f"out_{order[0]}"], "blocked": ""}, "B": {"text": r[f"out_{order[1]}"], "blocked": ""}})
    quiet = [r for r in rows if r["kind"] == "群聊" and r["plan"].get("回不回") == "不回" and r["out_a"]]
    for r in quiet:
        iid = f"rp6q-{len(page) + 1}"
        key[iid] = {"single": "quiet", "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group", "to": r["title"] or "无", "single": True,
                     "ctx": r["long"][-10:], "draft": r["plan"].get("局面") or "", "draft_label": "规划器看到的局面",
                     "A": {"text": r["out_a"], "blocked": ""}})
    json.dump(key, open(os.path.join(D, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    reps = [("同一句话，现在线上的写手写一遍，这一轮本机微调出来的新写手写一遍；两边用同一张卡。",
             "线上真实的轮次，同一个写手（现在线上的 r7k，看长聊天）写两遍：一遍用现在线上的卡（从草稿里摘的），一遍用规划器出的卡（规划器看她这一轮的全部材料，草稿只当材料）。"),
            ('const SINGLE = [["good", "可以发"], ["meh", "还行"], ["bad", "不好"]];',
             'const SINGLE = [["reply", "该回"], ["skip", "不回也行"]];'),
            ('box.querySelector("h2").textContent = "新写手";', 'box.querySelector("h2").textContent = "她会回的话";'),
            ('"看完感想（只看新写手）"', '"规划器说这句可以不回（群聊）"'),
            ("兄长大人发了视频或歌给她、或者问她刚才刷到什么。上面的灰框是你第八批写的那版，只作参考。",
             "群里这一句规划器判“可以不回”。看聊天，你觉得她该回吗？（下面是她不管的话会回的那句）"),
            ("felt: \"看完感想\"", "felt: \"看完感想\"")]
    for a, b in reps:
        if a not in tpl:
            print("模板里没找到：", a[:30])
        tpl = tpl.replace(a, b)
    html = os.path.join(rt.VT, "review", "replay6_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "卡怎么来 · 回放盲选").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：对比 {len(ab)} 对（私聊 {sum(r['kind'] != '群聊' for r in ab)}、群聊 {sum(r['kind'] == '群聊' for r in ab)}）"
          f" + 该不该回 {len(quiet)} 条；两句不一样的共 {len([r for r in rows if r['out_a'] and r['out_b'] and rt.lines(r['out_a']) != rt.lines(r['out_b'])])}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "plan", "write", "page"])
    ap.add_argument("--limit", type=int, default=0, help="prep：只留最近 N 条")
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    if a.cmd == "prep":
        cmd_prep(a.limit)
    elif a.cmd == "plan":
        asyncio.run(cmd_plan())
    elif a.cmd == "write":
        cmd_write()
    else:
        cmd_page(a.n)


if __name__ == "__main__":
    main()
