"""兄长大人过目后的"关于自己"清单 → 定稿 JSON（以后写进 memorix 当她自己的长期记忆）。

    python -I finalize_self_facts.py [--grade 初三|删]

读 voice_train\\data\\layered_v1\\佳树-关于自己-待过目.md（兄长大人改过的版本），去掉：
- 计数"（N 段提到）"和 ⚠ 标记
- 出戏的说明："（也译作「哥哥」）""（不同译本也作……）"这类——她不该知道自己有译本
- 兄长大人写了「删」的条目
第 14 条（年级说法不一）按 --grade 处理：初三 = 统一成"佳树读初三，正在备考石蕗高中"；删 = 不要。
输出 voice_train\\data\\layered_v1\\self_facts_final.json，并打印定稿。
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
DIR = r"D:\JiashuBot\voice_train\data\layered_v1"
SRC = os.path.join(DIR, "佳树-关于自己-待过目.md")
OUT = os.path.join(DIR, "self_facts_final.json")

META = [
    re.compile(r"（[^（）]*段提到）"),
    re.compile(r"（[^（）]*(译本|译作|也作)[^（）]*）"),
    re.compile(r"\((?:[^()]*(译本|译作|也作)[^()]*)\)"),
]


def clean(text: str) -> str:
    s = text.replace("⚠", "").strip()
    for p in META:
        s = p.sub("", s)
    return re.sub(r"\s+", "", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grade", choices=["初三", "删"], default=None)
    a = ap.parse_args()
    kind, out, pending = "", [], []
    for line in open(SRC, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("## "):
            kind = line[3:].strip()
            continue
        m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        n, body = int(m.group(1)), m.group(2)
        if re.search(r"[「\s]删[」\s]*$|（删）$|\s删$", body):
            continue
        edit = re.search(r"改[:：]\s*(.+)$", body)
        if edit:
            body = edit.group(1)
        if "说法不一" in body and "年级" in body:
            if a.grade == "初三":
                body = "佳树读初三，是学生会副会长，正在备考石蕗高中。"
            elif a.grade == "删":
                continue
            else:
                pending.append(n)
                continue
        if a.grade == "初三" and "即将升上国三" in body:  # 和统一后的年级对上
            body = "佳树读国三，正在准备考高中。"
        fact = clean(body)
        if fact:
            out.append({"n": n, "kind": kind, "fact": fact})
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"定稿 {len(out)} 条 → {OUT}")
    if pending:
        print(f"还没定：第 {pending} 条（年级），用 --grade 初三 或 --grade 删")
    for f in out:
        print(f"{f['n']:>2} [{f['kind']}] {f['fact']}")


if __name__ == "__main__":
    main()
