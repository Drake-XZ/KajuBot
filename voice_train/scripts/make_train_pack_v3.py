"""把第三版训练数据和一键训练脚本打成压缩包，拿到别人电脑上训练（2026-11-10 兄长大人要的）。

数据：data\\layered_v3 的 stage1.jsonl（原来那批 H）+ stage1_pool.jsonl（语料池里以前没用过的贴吧 / B站）→ data\\stage1.jsonl
      stage2.jsonl（K：原作 + 兄长的样本）、eval_*.jsonl → eval.jsonl、system.json
每条只留训练用得到的字段（src / id / group / ctx / target / card）。
脚本在 voice_train\\train_pack\\kaju_train_pack\\（train.py / run_all.py / merge_stream.py / run.bat / run.sh / 说明.md）。
输出 voice_train\\train_pack\\kaju_train_pack.zip。
用法：python -I make_train_pack.py [--no-zip]
"""
import collections
import glob
import json
import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(VT, "data", "layered_v3")
PACK = os.path.join(VT, "train_pack", "kaju_train_pack")
KEEP = ("src", "id", "group", "ctx", "target", "card")
SKIP_DIRS = {".venv", "out", "out_smoke", "results", "results_smoke", "models", "__pycache__"}


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()] if os.path.exists(path) else []


def dump(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in KEEP if k in r}, ensure_ascii=False) + "\n")


def main():
    data = os.path.join(PACK, "data")
    os.makedirs(data, exist_ok=True)
    s1 = load(os.path.join(SRC, "stage1.jsonl"))
    pool = load(os.path.join(SRC, "stage1_pool.jsonl"))
    seen, h = set(), []
    for r in s1 + pool:
        k = ("|".join(r.get("ctx") or []), r["target"].strip())
        if k not in seen and r.get("card"):
            seen.add(k)
            h.append(r)
    s2 = [r for r in load(os.path.join(SRC, "stage2.jsonl")) if r.get("card")]
    ev = [r for p in sorted(glob.glob(os.path.join(SRC, "eval_*.jsonl"))) for r in load(p) if r.get("card")]
    dump(os.path.join(data, "stage1.jsonl"), h)
    dump(os.path.join(data, "stage2.jsonl"), s2)
    dump(os.path.join(data, "eval.jsonl"), ev)
    open(os.path.join(data, "system.json"), "w", encoding="utf-8").write(open(os.path.join(SRC, "system.json"), encoding="utf-8").read())
    info = {"stage1": dict(collections.Counter(r["src"] for r in h)), "stage1_total": len(h),
            "stage2": dict(collections.Counter(r["src"] for r in s2)), "stage2_total": len(s2), "eval": len(ev),
            "stage1_要说到的为空": sum("要说到的：无" in r["card"] for r in h), "stage2_要说到的为空": sum("要说到的：无" in r["card"] for r in s2)}
    json.dump(info, open(os.path.join(data, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    if "--no-zip" in sys.argv:
        return
    zp = os.path.join(VT, "train_pack", "kaju_train_pack.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(PACK):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith((".log", ".zip", ".pyc")):
                    continue
                p = os.path.join(root, f)
                z.write(p, os.path.join("kaju_train_pack", os.path.relpath(p, PACK)))
    print(f"{zp}  {os.path.getsize(zp) / 2**20:.1f}MB")


if __name__ == "__main__":
    main()
