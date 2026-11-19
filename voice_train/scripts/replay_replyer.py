r"""照 MaiBot 的做法试回复器（2026-11-18 兄长：“那按照他们这个思路试试”；AGENT.md 第十节）。

MaiBot：规划器、回复器都是 API 大模型，不训练模型；人格写在配置里，说法靠“表达方式学习”——从聊天里学“什么场合用什么说法”，
每次回复挑几条放进提示（“你可以视情况自由使用以下句式”）。这里照着做：
  - 规划：replay8 里 Claude 当大脑写的 D 版（知道她的性格、通常只说一件事）
  - 回复器：API 大模型（默认 hardysapi claude-sonnet-5-5，text_models.json），提示 = 她是谁 + 她是什么样的人（character.md）
    + 说话方式几句 + 最近 10 条聊天 + 这一轮的话 + 大脑的指导 + 按场合挑出的 5 句她真说过的话（例子库）
  - 例子库：r9\k_data\stage2.jsonl（已去掉恋爱 / 亲密）里兄长认可过的线上回复 + 原作原句；按“她回的是哪句”和这一轮对方的话的意思（bge-m3）挑；
    同一段聊天里的不要（免得把答案当例子）。replay8 的兄长备注是这 50 轮的答案，这次不进例子库。
和线上 A（现在的大脑 + r7k）比盲选。

  bank            建例子库向量 → replay8\bank.json
  show [--n 1]    打一条完整提示看看（不调 API）
  run [--limit N] 调回复器 → write.json 的 out_e（usage_meter 估钱）
  page            盲选页 review\replay8e_ab.html（答案 replay8\key_e.json）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\replay_replyer.py bank | show | run | page
"""
import argparse
import asyncio
import json
import math
import os
import random
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay8")
R9 = os.path.join(rt.ROOT, "r9")
BANK = os.path.join(D, "bank.json")
EMBED = "http://127.0.0.1:11435/api/embed"
CARE = re.compile(r"吃饭|吃过饭|吃饱|休息|别太累|辛苦|早点睡|歇一会|好好睡|注意身体|按时吃")
ASKED = re.compile(r"吃|饭|饿|累|睡|困|躺|熬夜|复习|考试|忙")
MODEL_NAME = "hardysapi · claude-sonnet-5-5"
OUT = "out_e2"  # 第一遍 out_e（11-18 盲选 28:9 赢）；第二遍 out_e2：不顺手叮嘱吃饭休息
ME = "温水佳树，初三，学生会副会长。在 QQ 上和兄长大人（她的哥哥）私聊，也在他和朋友们的群里聊天"

STYLE = """说话方式：
- 写她在 QQ 上会发的话，一条消息一行；通常一两句，事情多才多一点。
- 她自称“佳树”、叫哥哥“兄长大人”，但一句话里不反复自称、不反复叫人。
- 不复述对方刚说的话，不写时间、名字前缀、括号里的动作和心理描写。
- 大脑的指导是这一轮要表达的意思，照着说到，但用她自己的话；指导里没有的事不加（对方没说累、没说吃饭，就不顺手叮嘱吃饭、休息）。"""


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def embed(texts):
    out = []
    for i in range(0, len(texts), 32):
        req = urllib.request.Request(EMBED, data=json.dumps({"model": "bge-m3", "input": texts[i:i + 32]}).encode(),
                                     headers={"Content-Type": "application/json"})
        out += json.load(urllib.request.urlopen(req, timeout=120))["embeddings"]
    return out


def cos(a, b):
    n = sum(x * y for x, y in zip(a, b))
    d = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return n / d if d else 0.0


def strip_line(s):
    return re.sub(r"^\s*(\d\d:\d\d\s*)?[^：:]{1,20}[：:]\s*", "", s or "").strip()


def cmd_bank():
    rows = jl(os.path.join(R9, "k_data", "stage2.jsonl"))
    sys.path.insert(0, HERE)
    from prepare_r8_pack import romance
    from prepare_r9_claude import CLOSE
    more = re.compile(r"平安夜|那位|女生|女性|女朋友|约会|情人节|巧克力")
    bank, seen = [], set()
    for r in rows:
        sit = strip_line((r.get("ctx") or [""])[-1])
        if not sit or len(r["target"]) > 120 or sit[:20] in seen:
            continue
        if r["src"] == "novel" and "「" not in sit and "」" not in sit:  # 原作里她接的是旁白的，不当例子
            continue
        if romance({"target": r["target"], "card": "", "ctx": [sit]}) or CLOSE.search(r["target"] + sit) or more.search(r["target"]):
            continue
        if CARE.search(r["target"]) and not ASKED.search(sit):  # 11-18 兄长：太刻意说吃饭、休息——对方没提的叮嘱不当例子
            continue
        seen.add(sit[:20])
        bank.append({"id": r["id"], "src": r["src"], "situation": sit[:120], "line": r["target"].replace("\n", " / "),
                     "ctx_keys": [strip_line(c)[:40] for c in (r.get("ctx") or [])[-6:]]})
    vecs = embed([b["situation"] for b in bank])
    for b, v in zip(bank, vecs):
        b["vec"] = v
    json.dump(bank, open(BANK, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"例子库 {len(bank)} 句（认可过的 {sum(b['src'] != 'novel' for b in bank)}、原作 {sum(b['src'] == 'novel' for b in bank)}）")


ALL_NEAR = None


def all_near():
    """这 50 轮所在的那几段聊天里出现过的每一行：例子库里出自这些聊天的不要（免得把同一段聊天里后来的事当例子）。"""
    global ALL_NEAR
    if ALL_NEAR is None:
        rows = json.load(open(os.path.join(rt.ROOT, "replay6", "items.json"), encoding="utf-8"))
        ALL_NEAR = {strip_line(c)[:40] for r in rows for c in (r.get("long") or []) + [r["said"]]}
    return ALL_NEAR


def pick(bank, turn_vec, row, k=5):
    near = all_near()
    scored = []
    for b in bank:
        if near & set(b["ctx_keys"]) or b["line"][:30] in (row.get("draft") or ""):  # 同一段聊天的不要
            continue
        scored.append((cos(turn_vec, b["vec"]), b))
    scored.sort(key=lambda x: -x[0])
    out, seen, n_novel = [], set(), 0
    for _s, b in scored:  # 以兄长认可过的线上回复为主，原作最多 2 句
        key = b["line"][:12]
        if key in seen or (b["src"] == "novel" and n_novel >= 2):
            continue
        seen.add(key)
        n_novel += b["src"] == "novel"
        out.append(b)
        if len(out) >= k:
            break
    return out


def plan_text(d):
    lines = [f"局面：{d.get('局面', '')}", f"要接住的：{d.get('要接住的', '')}",
             "要表达的：" + ("；".join(d.get("要表达的D") or []) or "（随口接一句）")]
    if d.get("背景"):
        lines.append("背景：" + "；".join(d["背景"]))
    if d.get("情绪D"):
        lines.append(f"情绪：{d['情绪D']}")
    return "\n".join(lines)


def build(row, examples):
    sys.path.insert(0, r"D:\JiashuBot\bot_setup")
    os.environ.setdefault("KAJU_DATA", r"D:\JiashuBot\kaju_data")
    from kaju_core.voice import brain
    system = (f"你是{ME}。\n" + brain.character().replace("你替她挑“要表达什么”时用", "这是她的性格")
              + "\n\n" + STYLE + "\n\n你可以视情况参考她以前在类似场合说过的话（只学说法和语气，内容照这一轮的指导，不要照抄）：\n"
              + "\n".join(f"- 当对方说“{b['situation'][:60]}”时，她说：“{b['line'][:100]}”" for b in examples))
    chat = "\n".join(row["long"][-10:])
    user = (f"场合：{row['kind']}，对象：{row['title'] or '无'}\n\n最近的聊天：\n{chat}\n\n这一轮对方说：\n{row['said']}\n\n"
            f"大脑的指导：\n{plan_text(row['plan'])}\n\n只输出她要发的话。")
    return system, user


def load():
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    bank = json.load(open(BANK, encoding="utf-8"))
    todo = [r for r in rows if r["plan"].get("回不回") != "不回" and r["plan"].get("要表达的D")]
    vecs = embed([f"{r['said'][:200]} {r['plan'].get('要接住的', '')}" for r in todo])
    return rows, bank, list(zip(todo, vecs))


def cmd_show(n):
    rows, bank, pairs = load()
    for r, v in pairs[:n]:
        s, u = build(r, pick(bank, v, r))
        print("===== system\n" + s + "\n===== user\n" + u)
        print(f"\n（这一条约 {len(s) + len(u)} 字）")


async def cmd_run(limit):
    import train_keys  # noqa: F401
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    ks = [k for k in omni.text_keys() if k.get("name", "").startswith(MODEL_NAME)]
    if not ks:
        sys.exit(f"text_models.json 里没有 {MODEL_NAME}")
    k = ks[0]
    rows, bank, pairs = load()
    pairs = pairs[:limit] if limit else pairs
    sem = asyncio.Semaphore(4)

    async def one(r, v):
        ex = pick(bank, v, r)
        s, u = build(r, ex)
        async with sem:
            t0 = time.time()
            for attempt in range(3):
                try:
                    out = await asyncio.to_thread(omni._openai_chat, k, [{"role": "system", "content": s}, {"role": "user", "content": u}], 60)
                    r[OUT] = (out or "").strip()
                    break
                except Exception as e:  # noqa: BLE001
                    r["out_e_err"] = f"{type(e).__name__}: {e}"[:200]
                    await asyncio.sleep(3 * (attempt + 1))
            r["e_examples"] = [b["line"] for b in ex]
            r["e_secs"] = round(time.time() - t0, 1)
            print("  ", r["id"], r.get("e_secs"), (r.get("out_e") or "（没写出来）")[:60].replace("\n", " / "), flush=True)

    await asyncio.gather(*[one(r, v) for r, v in pairs])
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    u = usage_meter.report(os.path.join(D, f"usage-replyer-{time.strftime('%H%M')}.json"))
    secs = sorted(r["e_secs"] for r, _ in pairs if r.get("e_secs"))
    print(f"写完 {sum(bool(r.get(OUT)) for r, _ in pairs)} / {len(pairs)}；用时中位 {secs[len(secs) // 2] if secs else 0} 秒；估钱",
          json.dumps({k2: u.get(k2) for k2 in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)


def cmd_page():
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random(201814)
    ab = [r for r in rows if r["plan"].get("回不回") != "不回" and r["out_a"] and r.get("out_e") and rt.lines(r["out_a"]) != rt.lines(r["out_e"])]
    rng.shuffle(ab)
    page, key = [], {}
    for r in ab:
        order = ["a", "e"]
        rng.shuffle(order)
        iid = f"rp8e-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["title"] or "无",
                     "ctx": r["long"][-10:], "draft": r["draft"], "draft_label": "她当时的草稿（只给你参考）",
                     "A": {"text": r[f"out_{order[0]}"], "blocked": ""}, "B": {"text": r[f"out_{order[1]}"], "blocked": ""}})
    json.dump(key, open(os.path.join(D, "key_e.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    a = "同一句话，现在线上的写手写一遍，这一轮本机微调出来的新写手写一遍；两边用同一张卡。"
    if a not in tpl:
        print("模板里没找到说明那句")
    tpl = tpl.replace(a, "线上真实的轮次，两种写法：一边是现在线上（大脑出卡 + 本地写手 r7k）；"
                         "一边照 MaiBot 的做法（大脑知道她的性格 + 大模型当回复器，提示里放几句她以前说过的话当例子）。看哪句更像佳树会说的话。")
    html = os.path.join(rt.VT, "review", "replay8e_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", "回复器盲选").replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：对比 {len(ab)} 对", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["bank", "show", "run", "page"])
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "bank":
        cmd_bank()
    elif a.cmd == "show":
        cmd_show(a.n)
    elif a.cmd == "run":
        asyncio.run(cmd_run(a.limit))
    else:
        cmd_page()


if __name__ == "__main__":
    main()
