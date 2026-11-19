r"""大脑加“她是什么样的人”回放（2026-11-18 兄长：“可以，接进去”；“直接你自己来吧，别调api了，太慢了”；AGENT.md 第十节）。

replay6 那 52 轮真实对话（replay6\items.json，长前文已按线上重建），同一个写手 r7k（系统提示 v5、长前文）写两遍：
  A  大脑照现在线上的要求（只知道一句身份）
  B  大脑 + 她是什么样的人（kaju_data\self\persona\character.md）
大脑这次由 Claude 在会话里当（兄长说别调 API）：两边共用局面 / 要接住的 / 背景 / 回不回，只分开写“要表达的”和“情绪”。
所以这次测的是“大脑知道她的性格，写出来是不是更像她”这个想法本身；线上的大脑是 gemini-3.8-flash，开了以后还要在真实消息上看。

  dump --batch N   打印第 N 批（每批 13 轮）：场合、对象、心情、最近 12 行聊天、这一轮的话 → Claude 写
  add FILE         Claude 写好的一批（jsonl）并进 replay8\plans.jsonl
  write            两边各写一遍（本机显卡，gpu_busy.hold）→ replay8\write.json
  page             盲选页 review\replay8_ab.html（答案 replay8\key.json）
用法（AstrBot 的 Python）：python -I -X utf8 scripts\replay_char.py dump --batch 1 | add 文件 | write | page
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import replay_b as rb  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
D = os.path.join(rt.ROOT, "replay8")
R6 = os.path.join(rt.ROOT, "replay6")
PLANS = os.path.join(D, "plans.jsonl")
BATCH = 13


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def items():
    return json.load(open(os.path.join(R6, "items.json"), encoding="utf-8"))


def cmd_dump(n):
    its = items()[(n - 1) * BATCH: n * BATCH]
    for k, it in enumerate(its, (n - 1) * BATCH + 1):
        print(f"### {k:02d} {it['id']}（{it['kind']}，对象 {it['title'] or '无'}）")
        print(f"心情：{it['mood']}")
        for c in (it.get("long") or it.get("ctx") or [])[-12:]:
            print("  " + c[:160].replace("\n", " / "))
        print(f"这一轮：{it['said'][:300]}\n")


def cmd_add(path):
    os.makedirs(D, exist_ok=True)
    have = {d["id"]: d for d in (jl(PLANS) if os.path.exists(PLANS) else [])}
    for d in jl(path):
        have[d["id"]] = d
    with open(PLANS, "w", encoding="utf-8") as f:
        for d in have.values():
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"现在 {len(have)} 条")


def plan_of(d, side):
    p = {k: d.get(k) for k in ("回不回", "局面", "要接住的", "背景")}
    p["要表达的"] = d.get(f"要表达的{side}") or []
    p["情绪"] = d.get(f"情绪{side}") or ""
    return p


def cmd_write_c(side="C"):
    """第二轮 C（11-18 兄长：“再做一轮”：性格只用来挑说哪件，条数和 A 一样）；第三轮 D（“再试一轮”：性格 + 通常只说一件事）。
    只写这一边，并进 write.json 的 out_c / out_d。"""
    from kaju_core import gpu_busy
    from kaju_core.voice import brain
    ps = {d["id"]: d for d in jl(PLANS)}
    path = os.path.join(D, "write.json")
    rows = json.load(open(path, encoding="utf-8"))
    with gpu_busy.hold(f"大脑加性格回放（r7k 照 {side} 卡写）"):
        for i, row in enumerate(rows):
            d = ps.get(row["id"])
            if not d or not d.get(f"要表达的{side}"):
                continue
            row["plan"] = d
            card = brain.card_of(row["kind"], row["title"], plan_of(d, side), row["mood"])
            row[f"card_{side.lower()}"] = card
            row[f"out_{side.lower()}"] = rb.write5(row["long"], card, row["draft"], row["title"])
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}", flush=True)
        rt.ollama_unload()
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写完 {side} {sum(bool(r.get('out_' + side.lower())) for r in rows)} 条", flush=True)


def cmd_write():
    from kaju_core import gpu_busy
    from kaju_core.voice import brain
    ps = {d["id"]: d for d in jl(PLANS)}
    rows = []
    with gpu_busy.hold("大脑加性格回放（r7k 照两种大脑卡写）"):
        for i, it in enumerate(items()):
            d = ps.get(it["id"])
            if not d:
                continue
            row = dict(it, plan=d)
            for side in ("A", "B"):
                card = brain.card_of(it["kind"], it["title"], plan_of(d, side), it["mood"])
                row[f"card_{side.lower()}"] = card
                row[f"out_{side.lower()}"] = rb.write5(it["long"], card, it["draft"], it["title"])
            rows.append(row)
            if (i + 1) % 10 == 0:
                print(f"  写了 {i + 1}", flush=True)
        rt.ollama_unload()
    json.dump(rows, open(os.path.join(D, "write.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"写完 {len(rows)} 条；A 空 {sum(not r['out_a'] for r in rows)}、B 空 {sum(not r['out_b'] for r in rows)}", flush=True)


def cmd_page(other="b"):
    """other = b：第一轮（加性格、多加了条）；c：第二轮（性格只挑说哪件、条数一样）→ replay8c_ab.html / key_c.json。"""
    rows = json.load(open(os.path.join(D, "write.json"), encoding="utf-8"))
    rng = random.Random({"b": 201811, "c": 201812, "d": 201813}[other])
    ab = [r for r in rows if r["plan"].get("回不回") != "不回" and r["out_a"] and r.get(f"out_{other}")
          and rt.lines(r["out_a"]) != rt.lines(r[f"out_{other}"])]
    rng.shuffle(ab)
    page, key = [], {}
    for r in ab:
        order = ["a", other]
        rng.shuffle(order)
        iid = f"rp8{'' if other == 'b' else other}-{len(page) + 1}"
        key[iid] = {"A": order[0], "B": order[1], "src": r["id"]}
        page.append({"id": iid, "n": len(page) + 1, "src": "group" if r["kind"] == "群聊" else "private", "to": r["title"] or "无",
                     "ctx": r["long"][-10:], "draft": r["draft"], "draft_label": "她当时的草稿（只给你参考；两边的大脑都没看过草稿）",
                     "A": {"text": r[f"out_{order[0]}"], "blocked": ""}, "B": {"text": r[f"out_{order[1]}"], "blocked": ""}})
    json.dump(key, open(os.path.join(D, "key.json" if other == "b" else f"key_{other}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(rt.VT, "review", "round_ab.template.html"), encoding="utf-8").read()
    reps = [("同一句话，现在线上的写手写一遍，这一轮本机微调出来的新写手写一遍；两边用同一张卡。",
             "线上真实的轮次，同一个写手（现在线上的 r7k）写两遍，两边的“大脑”只差一件事："
             "一边只知道她叫什么、几年级（现在线上这样），一边还知道她是什么样的人（爱操心兄长、被夸会得意……）。看哪句更像佳树会说的话。")]
    for a, b in reps:
        if a not in tpl:
            print("模板里没找到：", a[:30])
        tpl = tpl.replace(a, b)
    html = os.path.join(rt.VT, "review", "replay8_ab.html" if other == "b" else f"replay8{other}_ab.html")
    open(html, "w", encoding="utf-8", newline="\n").write(
        tpl.replace("/*TITLE*/", {"b": "大脑性格盲选", "c": "大脑性格盲选二", "d": "大脑性格盲选三"}[other]).replace("__ITEMS__", json.dumps(page, ensure_ascii=False).replace("</", "<\\/")))
    print(f"盲选页 {html}：对比 {len(ab)} 对（私聊 {sum(r['kind'] != '群聊' for r in ab)}、群聊 {sum(r['kind'] == '群聊' for r in ab)}）", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "add", "write", "write_c", "write_d", "page"])
    ap.add_argument("--vs", default="b", choices=["b", "c", "d"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--batch", type=int, default=1)
    a = ap.parse_args()
    if a.cmd == "dump":
        cmd_dump(a.batch)
    elif a.cmd == "add":
        cmd_add(a.arg)
    elif a.cmd == "write":
        cmd_write()
    elif a.cmd == "write_c":
        cmd_write_c("C")
    elif a.cmd == "write_d":
        cmd_write_c("D")
    else:
        cmd_page(a.vs)


if __name__ == "__main__":
    main()
