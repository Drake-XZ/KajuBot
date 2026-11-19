r"""第 9 轮人格对子由 Claude（会话里）自己写（2026-11-18 兄长：“这个出题能不能你来出”“你来写 500 对”；AGENT.md 第十节）。

  pick            从 r7k 的 K stage2 挑人格明显的约 500 句（小试 30 句里写过的算进去）→ r9\claude_todo.jsonl（带批号）
  dump --batch N  打印第 N 批给 Claude 写：编号 | 对象 | 前面两行 | 佳树原句
  add FILE        把 Claude 写好的一批（jsonl：id / flat / over / skip）并进 r9\pairs_claude.jsonl（同 id 覆盖）
  check           自动查：平淡版不许有“佳树 / 兄长”、行数要和原句一样、不能和原句几乎一样；过头版里的人名不能多出原句没有的
用法：python -I -X utf8 scripts\prepare_r9_claude.py pick ；dump --batch 1 ；add 文件 ；check
"""
import argparse
import difflib
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
from prepare_r8_pack import romance  # noqa: E402  恋爱词表（11-18 补了“月色”）

R7K = os.path.join(VT, "data", "rounds_v4", "r7k")
R9 = os.path.join(VT, "data", "rounds_v4", "r9")
TODO = os.path.join(R9, "claude_todo.jsonl")
MINE = os.path.join(R9, "pairs_claude.jsonl")
MARK = re.compile(r"兄长|佳树|呢|喔|嘛|说$|～|诶嘿|呀|哦|啦")
NAMES = ["兄长", "小权", "小鞠", "八奈见", "橘", "温水", "学姐", "学长", "学妹", "老师", "女王", "妈妈", "爸爸", "小温", "聪"]
BATCH = 48
# 恋爱词表之外再挡：身体亲密、兄长的恋爱对象、对她的下流话（佳树是初三学生）
CLOSE = re.compile(r"抱住|抱紧|抱抱|大腿|牵手|牵着|黏着|挚爱|这就是爱|女友|男友|桃花|喜欢的对象|更好的人|勾八|睡在一起|一起睡")
SEP = re.compile(r"\n| / ")


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def wjl(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def stage2():
    return {r["id"]: r for r in jl(os.path.join(R7K, "k_data", "stage2.jsonl"))}


def line_of(card, name):
    m = re.search(rf"^{name}：(.*)$", card or "", re.M)
    return m.group(1).strip() if m else ""


def cmd_pick():
    rows, seen = [], set()
    for r in stage2().values():
        ctx = " ".join((r.get("ctx") or [])[-2:])
        if romance(r) or len(r["target"]) > 100 or CLOSE.search(r["target"] + ctx) or r["target"] in seen:
            continue
        seen.add(r["target"])
        rows.append(r)
    done = {d["id"] for d in jl(MINE)} if os.path.exists(MINE) else set()
    rng = random.Random(918)
    rng.shuffle(rows)
    sc = lambda r: len(MARK.findall(r["target"]))  # noqa: E731
    novel = sorted([r for r in rows if r["src"] == "novel" and sc(r) >= 2], key=sc, reverse=True)[:300]
    cur = sorted([r for r in rows if r["src"] != "novel" and sc(r) >= 3], key=sc, reverse=True)[:176]
    pick = [r for r in novel + cur if r["id"] not in done]
    rng.shuffle(pick)
    out = [{"id": r["id"], "src": r["src"], "batch": i // BATCH + 1} for i, r in enumerate(pick)]
    wjl(TODO, out)
    print(f"挑了 {len(out)} 句（原作 {sum(r['src'] == 'novel' for r in pick)}、认可过的 {sum(r['src'] != 'novel' for r in pick)}），"
          f"加上小试写过的 {len(done)}；分 {out[-1]['batch']} 批")


def cmd_dump(n):
    s2 = stage2()
    done = {d["id"] for d in jl(MINE)} if os.path.exists(MINE) else set()
    for t in jl(TODO):
        if t["batch"] != n or t["id"] in done:
            continue
        r = s2[t["id"]]
        ctx = " ‖ ".join(x[:70] for x in (r.get("ctx") or [])[-2:])
        print(f"{t['id']} | {line_of(r['card'], '对象')} | {ctx} | {r['target'].replace(chr(10), ' / ')}")


def cmd_add(path):
    mine = {d["id"]: d for d in jl(MINE)} if os.path.exists(MINE) else {}
    new = jl(path)
    s2 = stage2()
    for d in new:
        d.setdefault("by", "claude-opus-5-5")
        if "\n" in s2[d["id"]]["target"]:  # Claude 写的时候用 " / " 分行，存成和原句一样的换行
            for k in ("flat", "over"):
                if d.get(k):
                    d[k] = d[k].replace(" / ", "\n")
        mine[d["id"]] = d
    wjl(MINE, list(mine.values()))
    print(f"并进 {len(new)} 条，现在共 {len(mine)} 条（写了 {sum(bool(d.get('flat')) for d in mine.values())}）")


def cmd_check():
    s2 = stage2()
    bad = []
    mine = jl(MINE)
    for d in mine:
        if not d.get("flat"):
            continue
        t = s2[d["id"]]["target"]
        fl, ov = d["flat"], d["over"]
        if re.search(r"佳树|兄长", fl.replace("温水佳树", "")):  # 报全名是事实，不算
            bad.append((d["id"], "平淡版里有佳树 / 兄长"))
        if len([x for x in SEP.split(t) if x.strip()]) != len([x for x in SEP.split(fl) if x.strip()]):
            bad.append((d["id"], "平淡版行数和原句不一样"))
        if difflib.SequenceMatcher(None, t, fl).ratio() >= 0.85:
            bad.append((d["id"], "平淡版和原句几乎一样"))
        extra = [n for n in NAMES if n in ov and n not in t and n != "兄长"]
        if extra:
            bad.append((d["id"], f"过头版多了原句没有的人：{'、'.join(extra)}"))
        if romance({"target": ov, "card": "", "ctx": []}) or romance({"target": fl, "card": "", "ctx": []}):
            bad.append((d["id"], "对照句里有恋爱话题词"))
    n = sum(bool(d.get("flat")) for d in mine)
    print(f"写了 {n} 对、跳过 {sum(bool(d.get('skip')) for d in mine)}；自动查出 {len(bad)} 处")
    for i, why in bad:
        print(" ", i, why)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pick", "dump", "add", "check"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--batch", type=int, default=1)
    a = ap.parse_args()
    if a.cmd == "pick":
        cmd_pick()
    elif a.cmd == "dump":
        cmd_dump(a.batch)
    elif a.cmd == "add":
        cmd_add(a.arg)
    else:
        cmd_check()


if __name__ == "__main__":
    main()
