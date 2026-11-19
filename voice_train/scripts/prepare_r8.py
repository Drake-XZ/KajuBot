r"""第 8 轮（人格进写手，2026-11-17 兄长：“Round 8 persona training”、“No, training only”；AGENT.md 第十节）。

想法：训练卡上的“要说到的”换成大脑那样的标签（“回答：他坐的电车比她早”“反应：被他关心很开心”），
只写意思、不写她怎么说；答案照旧是原作原句 / 兄长认可的话。写手要写对答案，就得自己把她的称呼、亲昵、性格补上——人格这样才进到写手里。
线上大脑出的也是这种卡（kaju_core\voice\brain.py）。

  label  [--pilot N]  K 的 stage2（r7k 那份）每条只重出“要说到的”那一行（场合 / 对象 / 局面 / 背景 / 心情照旧）
                       → data\rounds_v4\r8\labels.jsonl（跑过的跳过；model_router tasks.card 动态挑；usage_meter 估钱）
  show   [--n N]      打印几条：原卡要说到的 / 标签 / 答案
用法（AstrBot 的 Python）：python -I -X utf8 scripts\prepare_r8.py label --pilot 30 ；show --n 30
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
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
R8 = os.path.join(VT, "data", "rounds_v4", "r8")
OUT = os.path.join(R8, "labels.jsonl")

LABEL = """下面是一段对话的局面，和佳树（温水佳树）在这一轮真正说出口的那句回复。
把这句回复的**意思**整理成交给写手的“要表达的”。写手看不到这句回复，要照你写的意思、用佳树自己的口吻把话重新说出来。只输出 JSON：
{"要表达的": ["类别：内容"]}

每条写成“类别：内容”，类别从这些里挑：回答、立场、反应、反问、答应、拒绝、认错、安慰、分享、提醒、道谢。
- 回复里说到的每件事（事实、答案、她的看法和决定、要问回去的事、答应或拒绝的事）都要有一条对应，按回复里的顺序，最多 4 条；
  只是撒娇、称呼、语气、客套的部分不算一件事，不单独写。整句只是接话、没有具体内容的，写一条“反应：……”说明她是什么反应。
- 内容只写意思和关键信息（名字、数字、地点、读到哪了这类照写），十几个字以内的短语。
- **内容不能是正文的样子**：不抄回复里的词句，不写称呼（兄长大人、学姐、小权）、语气词、感叹、口头禅，
  不写撒娇、亲昵、夸张的说法（“最喜欢兄长大人了”只写成“反应：表达很喜欢他”），不写“佳树觉得…”“佳树想…”这种她会说出口的句子。
- 提到人写明是谁，用 他 / 她 / 名字（“反问：他怎么知道是因为哥哥”“分享：她刚做完午饭”），不写“对方”。
- 只写回复里有的意思，不加回复里没有的。"""

LINE = re.compile(r"^要说到的：.*$", re.M)


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def line_of(card, name):
    m = re.search(rf"^{name}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def user_of(r):
    jm = line_of(r["card"], "局面")
    return (f"场合：{line_of(r['card'], '场合')}\n对象：{line_of(r['card'], '对象')}\n局面：{jm}\n\n"
            f"前面最后两行：\n" + "\n".join((r.get("ctx") or [])[-2:]) + f"\n\n佳树的回复：\n{r['target']}")


def parse(out):
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    xs = [str(x).strip().rstrip("。；;") for x in ((v or {}).get("要表达的") or []) if str(x).strip()]
    return xs[:4] or None


async def cmd_label(pilot):
    import train_keys  # noqa: F401  KAJU_DATA、bot_setup 进 sys.path
    import usage_meter
    usage_meter.patch()
    from kaju_core.senses import omni
    rows = jl(os.path.join(R7K, "k_data", "stage2.jsonl"))
    if pilot:  # 各来源都挑一些
        rng = random.Random(808)
        by = {}
        for r in rows:
            by.setdefault(r["src"], []).append(r)
        rows = [r for src, rs in by.items() for r in rng.sample(rs, min(len(rs), max(4, pilot * len(rs) // 1440)))][:pilot]
    os.makedirs(R8, exist_ok=True)
    done = {(d["id"], d["src"]) for d in (jl(OUT) if os.path.exists(OUT) else []) if d.get("labels")}
    todo = [r for r in rows if (r["id"], r["src"]) not in done]
    print(f"要出标签 {len(todo)} 条（出过的 {len(done)}）", flush=True)
    sem = asyncio.Semaphore(4)
    n_ok = [0]

    async def one(r):
        async with sem:
            t0 = time.time()
            try:
                out, k = await omni.text(LABEL, user_of(r), timeout=40)
                labels = parse(out)
                row = {"id": r["id"], "src": r["src"], "labels": labels, "raw": None if labels else (out or "")[:300], "key": k}
            except Exception as e:  # noqa: BLE001
                row = {"id": r["id"], "src": r["src"], "labels": None, "error": f"{type(e).__name__}: {e}"[:200]}
            row["ms"] = int((time.time() - t0) * 1000)
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_ok[0] += bool(row["labels"])
            if n_ok[0] % 100 == 0 and row["labels"]:
                print(f"  好了 {n_ok[0]}", flush=True)

    await asyncio.gather(*[one(r) for r in todo])
    u = usage_meter.report(os.path.join(R8, f"usage-label-{time.strftime('%H%M')}.json"))
    print(f"这批好 {n_ok[0]} / {len(todo)}；估钱", json.dumps({k: u.get(k) for k in ("rmb", "rmb_full")}, ensure_ascii=False), flush=True)


def cmd_show(n):
    sys.path.insert(0, r"D:\JiashuBot\bot_setup")
    from kaju_core.voice import brain
    rows = {(r["id"], r["src"]): r for r in jl(os.path.join(R7K, "k_data", "stage2.jsonl"))}
    ls = [d for d in jl(OUT) if d.get("labels")]
    flat = [x for d in ls for x in d["labels"]]
    print(f"标签 {len(ls)} 份、{len(flat)} 条；像正文的 {sum(map(brain.sentence_like, flat))} 条")
    for d in ls[:n]:
        r = rows[(d["id"], d["src"])]
        print("=====", d["src"], d["id"])
        print("  前文:", " ‖ ".join(r["ctx"][-2:])[:140])
        print("  原卡要说到的:", line_of(r["card"], "要说到的"))
        print("  标签:", "；".join(d["labels"]))
        print("  答案:", r["target"][:140].replace("\n", " / "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["label", "show"])
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "label":
        asyncio.run(cmd_label(a.pilot))
    else:
        cmd_show(a.n)


if __name__ == "__main__":
    main()
