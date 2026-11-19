"""第二版要点卡的写手 kaju-writer-l2a：重抽卡 → 从头训 H（0～23 层）→ 合并 → 训 K（24～35 层）→ GGUF → 导入 Ollama。
（2026-11-09 兄长大人定：全量重训；每晚自学 KajuNightlyLearn 已暂停，训完、考完再决定要不要开回来。）

和 l1a 同样的配方（results\\layered_v1\\L1_H / L1_K 的 run.json）：H 1 轮、K 1 轮人工样本 ×3，lr 默认 2e-4，每步 16 条。
不换上线：训完只导入 Ollama 为 kaju-writer-l2a，要先考试 + 兄长盲选。
可以断了再跑：卡片有缓存；H / K 已经训好（目录里有 run.json）就跳过。
用法（AstrBot venv，后台）：python -I train_v2.py   日志 results\\layered_v2\\log.txt，进度 results\\layered_v2\\status.txt
"""
import asyncio
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = sys.argv[:1]
import daily_learn as dl  # noqa: E402  (run, make_gguf, free_gpu, PY, BASE)

dl.say = lambda m: print(m, flush=True)  # 别写进每晚自学的 nightly.log

OUT = os.path.join(dl.VT, "results", "layered_v2")
DATA = os.path.join(dl.VT, "data", "layered_v2")
LOG = os.path.join(OUT, "log.txt")
STATUS = os.path.join(OUT, "status.txt")
NAME = "kaju-writer-l2a"


def status(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(STATUS, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def done(d):
    return os.path.exists(os.path.join(d, "run.json"))


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    status("开始：重抽卡")
    dl.run([dl.BOT_PY, "-I", os.path.join(HERE, "build_cards_v2.py")], LOG)
    meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
    status(f"卡抽好了：{json.dumps(meta['parts'], ensure_ascii=False)}；{meta.get('cost')}")

    h, hm, k = os.path.join(OUT, "L2_H"), os.path.join(OUT, "L2_H-merged"), os.path.join(OUT, "L2_K")
    if not done(h):
        shutil.rmtree(h, ignore_errors=True)
        status("训 H（第 0～23 层，从原模型开始，1 轮）")
        dl.free_gpu()
        dl.run([dl.PY, "-I", os.path.join(HERE, "train_writer.py"), "--stage", "1", "--base", dl.BASE, "--data-dir", DATA,
                "--out", h, "--layers", "0-23", "--bs", "2", "--accum", "8"], LOG)
    status(f"H 好了：{json.load(open(os.path.join(h, 'run.json'), encoding='utf-8'))}")
    if not done(k):
        shutil.rmtree(k, ignore_errors=True)
        if not os.path.exists(os.path.join(hm, "config.json")):
            shutil.rmtree(hm, ignore_errors=True)
            dl.run([dl.PY, "-I", os.path.join(HERE, "merge_stream.py"), dl.BASE, hm, h], LOG)
        status("训 K（第 24～35 层，人工样本 ×3，1 轮）")
        dl.free_gpu()
        dl.run([dl.PY, "-I", os.path.join(HERE, "train_writer.py"), "--stage", "2", "--base", hm, "--data-dir", DATA,
                "--out", k, "--layers", "24-35", "--bs", "2", "--accum", "8", "--curated-repeat", "3"], LOG)
    shutil.rmtree(hm, ignore_errors=True)
    status(f"K 好了：{json.load(open(os.path.join(k, 'run.json'), encoding='utf-8'))}")
    status("做 GGUF、导入 Ollama")
    dl.make_gguf(NAME, OUT, [h, k], LOG)
    status(f"全部好了：Ollama 里是 {NAME}（没换上线），共 {(time.time() - t0) / 3600:.1f} 小时")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        status(f"出错：{type(e).__name__}: {e}")
        raise
