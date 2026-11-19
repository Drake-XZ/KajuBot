"""偏好训练跑一趟（2026-11-10）：接着线上写手的 K 层做 DPO + KTO。不换上线、不改 state.json。

    <bot venv>\\Scripts\\python.exe -I scripts\\run_pref.py train p1 [train_pref.py 的其它参数…]
        合并线上那轮的 H → 在上面接着线上的 K 训 → results\\prefs\\p1\\ep1、ep2…（每轮一份，带留出题成绩）
    <bot venv>\\Scripts\\python.exe -I scripts\\run_pref.py gguf p1 ep2
        挑一轮做成 GGUF 导入 Ollama，名字 <线上写手>-p1（不上线），顺手删掉合并出来的 H（8GB）
"""
import os
import shutil
import sys
import time

ARGS = sys.argv[1:]
sys.argv = sys.argv[:1]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_learn as d  # noqa: E402

RES = os.path.join(d.VT, "results", "prefs")


def main():
    what, tag, rest = ARGS[0], ARGS[1], ARGS[2:]
    cur = d.state()["current"]
    out = os.path.join(RES, tag)
    hm = os.path.join(RES, f"H-merged-r{cur['round']:03d}")
    log = os.path.join(RES, f"log-{tag}.txt")
    os.makedirs(RES, exist_ok=True)
    if os.path.exists(d.LOCK) and time.time() - os.path.getmtime(d.LOCK) < 6 * 3600:
        raise SystemExit("每晚自学还在跑，等它跑完")
    open(d.LOCK, "w").write(d.now())
    t0 = time.time()
    try:
        if what == "train":
            d.say(f"偏好训练 {tag}：起点 {cur['name']}（H {cur['h']}，K {cur['k']}）")
            d.free_gpu()
            if not os.path.isdir(hm):
                d.run([d.PY, "-I", os.path.join(HERE, "merge_stream.py"), d.BASE, hm, cur["h"]], log)
                d.say(f"  H 合并好了（{(time.time() - t0) / 60:.1f} 分钟）")
            d.free_gpu()
            d.run([d.PY, "-I", os.path.join(HERE, "train_pref.py"), "--base", hm, "--init-adapter", cur["k"], "--out", out] + rest, log)
            d.say(f"训完了，共 {(time.time() - t0) / 60:.1f} 分钟 → {out}")
        elif what == "gguf":
            k = os.path.join(out, rest[0])
            assert os.path.isdir(k), f"没有 {k}"
            name = f"{cur['name']}-{tag}"
            d.free_gpu()
            d.make_gguf(name, out, [cur["h"], k], log)
            shutil.rmtree(hm, ignore_errors=True)
            d.say(f"{name} 已导入 Ollama（没上线），共 {(time.time() - t0) / 60:.1f} 分钟")
    finally:
        if os.path.exists(d.LOCK):
            os.remove(d.LOCK)


if __name__ == "__main__":
    main()
