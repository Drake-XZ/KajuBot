r"""第 7 轮 K 单独重训的数据（2026-11-17，r7 没过之后；AGENT.md 第十节）。

r7 输的主要原因：新卡把“要说到的”压到 ≤2 条（K 里 3 条以上的卡 234 → 39），写手学成“卡上最多两件事”、多的就丢。
这次：r7 的包照用（长聊天、短局面、长聊天里看不到的背景、掺无关背景、心情行、系统提示 v5、恋爱向的不要），
只把出了新卡的样本的“要说到的”那一行换回原来（r6 那张卡）的。H 不动（K 接在 r6 的 H 上训）。
结果：data\rounds_v4\r7k\k_data（stage1 = r7 的 H 包同样换回，阶段二复习用；prefs、system.json 照 r7）、info.json
用法：python -I -X utf8 scripts\prepare_r7k.py
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_r7 as p7  # noqa: E402
import prepare_r7_cards as pc  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
R7K = os.path.join(p7.VT, "data", "rounds_v4", "r7k")
# 恋爱话题的样本不进（r7 只查目标那句；这次连卡和聊天最后一行一起查：原作里兄长交往 / 告白这类场景也不要）
ROMANCE_WIDE = re.compile(pc.ROMANCE.pattern + r"|交往|告白|表白|恋爱|喜欢的人|情侣|吃醋")


def romance(r):
    return bool(ROMANCE_WIDE.search(r["target"] + r["card"] + (r["ctx"][-1] if r.get("ctx") else "")))


def restore(rows, part, old):
    out, n = [], 0
    for r in rows:
        o = old.get((f"{part}:{r['id']}", r["src"]))
        if o is not None:
            line = next((x for x in o.splitlines() if x.startswith("要说到的：")), None)
            if line:
                r = dict(r, card=re.sub(r"^要说到的：.*$", line.replace("\\", "\\\\"), r["card"], count=1, flags=re.M))
                n += 1
        out.append(r)
    return out, n


def pts(card):
    v = pc.line_of(card, "要说到的")
    return 0 if v in ("", "无") else len([x for x in v.split("；") if x.strip()])


def main():
    old = {(d["key"], d["src"]): d["card_r6"] for d in p7.jl(pc.OUT)}
    src = os.path.join(p7.R7, "k_data")
    dst = os.path.join(R7K, "k_data")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    s2, n2 = restore(p7.jl(os.path.join(src, "stage2.jsonl")), "K", old)
    s1, n1 = restore(p7.jl(os.path.join(src, "stage1.jsonl")), "H", old)
    d2, d1 = sum(map(romance, s2)), sum(map(romance, s1))
    s2 = [r for r in s2 if not romance(r)]
    s1 = [r for r in s1 if not romance(r)]
    for name, rows in (("stage2.jsonl", s2), ("stage1.jsonl", s1)):
        with open(os.path.join(dst, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    p = [pts(r["card"]) for r in s2]
    info = {"K stage2": len(s2), "换回原来要点的": n2, "stage1（复习）": len(s1), "stage1 换回的": n1,
            "K 要点数 0/1/2/3+": [p.count(0), p.count(1), p.count(2), sum(x >= 3 for x in p)],
            "前文≥10行": sum(len(r["ctx"]) >= 10 for r in s2), "恋爱话题去掉（K / 复习）": [d2, d1]}
    json.dump(info, open(os.path.join(R7K, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
