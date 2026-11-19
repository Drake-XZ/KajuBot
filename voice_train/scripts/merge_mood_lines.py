r"""把训练数据里旧格式的心情行改成合并后的写法（2026-11-16 晚兄长定“合并重复项”，线上和训练一起改）。

线上从 11-16 晚起用 kaju_core.heart.mood_line 的新写法（挨着的一样的“×次数”、心事同种同来路合一个）。这里把以后训练 / 考试会读到的
文件里的心情行用 mood_line.normalize 转一遍（纯文字转换，结果和对同一份读数调 mood_line 一样），别的内容不动。
改之前把要改的文件原样打包到 D:\JiashuBot\_backup\mood-merge-<时间>.zip（过去各轮训练时的样子可以从这里找回）。
不动：考试输出（exam_*）、投票（votes / ab_votes）、state.json、key.json、cache。线上记录（kaju_data\...\rewrites）不改，读的时候转（round_pick / replay_planner）。

    python -I -X utf8 scripts\merge_mood_lines.py          （先只数一数，不改）
    python -I -X utf8 scripts\merge_mood_lines.py --write  （备份后改）
"""
import json
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train_keys  # noqa: E402,F401  bot_setup 进 sys.path
from kaju_core.heart.mood_line import normalize  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(HERE)
ROOTS = [os.path.join(VT, "train_pack", "kaju_train_pack", "data"), os.path.join(VT, "data", "rounds_v4"),
         os.path.join(VT, "data", "stage2bg"), os.path.join(VT, "data", "stage_h_plan")]
SKIP_PARTS = ("votes", "ab_votes", "cache", "_tmp")
SKIP_NAMES = ("state.json", "key.json", "ab_key.json")


def walk(x):
    if isinstance(x, str):
        return normalize(x)
    if isinstance(x, list):
        return [walk(v) for v in x]
    if isinstance(x, dict):
        return {k: walk(v) for k, v in x.items()}
    return x


def files():
    for root in ROOTS:
        for dp, dn, fn in os.walk(root):
            if any(p in dp.replace("\\", "/").split("/") for p in SKIP_PARTS):
                continue
            for f in fn:
                if f.endswith((".jsonl", ".json")) and f not in SKIP_NAMES and not f.startswith("exam_p3"):
                    yield os.path.join(dp, f)


def convert(path):
    raw = open(path, encoding="utf-8").read()
    if "心情：" not in raw:
        return None, 0
    if path.endswith(".jsonl"):
        out, n = [], 0
        for line in raw.splitlines():
            if line.strip() and "心情：" in line:
                new = json.dumps(walk(json.loads(line)), ensure_ascii=False)
                n += new != line and json.loads(new) != json.loads(line)
                out.append(new if json.loads(new) != json.loads(line) else line)
            else:
                out.append(line)
        text = "\n".join(out) + ("\n" if raw.endswith("\n") else "")
    else:
        d = json.loads(raw)
        nd = walk(d)
        n = int(nd != d)
        text = json.dumps(nd, ensure_ascii=False, indent=1) if n else raw
    return (text if n else None), n


def main():
    write = "--write" in sys.argv
    todo = []
    for p in files():
        text, n = convert(p)
        if text is not None:
            todo.append((p, text, n))
    total = sum(n for _, _, n in todo)
    print(f"要改的文件 {len(todo)} 个、{total} 处（jsonl 按行数）", flush=True)
    for p, _, n in todo[:80]:
        print(f"  {n:5d}  {os.path.relpath(p, VT)}")
    if not write:
        print("只数了一下，加 --write 才改")
        return
    bk = os.path.join(os.path.dirname(VT), "_backup", f"mood-merge-{time.strftime('%Y%m%d-%H%M')}.zip")
    os.makedirs(os.path.dirname(bk), exist_ok=True)
    with zipfile.ZipFile(bk, "w", zipfile.ZIP_DEFLATED) as z:
        for p, _, _ in todo:
            z.write(p, os.path.relpath(p, os.path.dirname(VT)))
    for p, text, _ in todo:
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(f"改好了；原样备份在 {bk}", flush=True)


if __name__ == "__main__":
    main()
