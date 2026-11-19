r"""第 3 轮一口气跑完（2026-11-14 兄长：“让她先不回复群聊，然后开始训练”）。

整个过程（拼数据 → 训练 → 导入 → 两种卡考试）都挂着 kaju_core.gpu_busy 标记，机器人开着时群聊先不回
（round_train.train 自己也会标记、训完会删，所以每一步开始前这里重新标一次；这个进程一结束标记自动失效）。
  1. prepare_r3.py（要 Ollama：线上写手在 v5 卡上写“不要的”）
  2. round_train.py data / train / import / exam --round 3（exam = 现在的 v4 卡，上线闸门）
  3. exam_p3.py 线上写手 和 第 3 轮 --cards v5（带背景的卡）
  4. data\rounds_v4\r3\exam_both.md：两种卡的成绩并排
用法（AstrBot 的 Python）：python -I -X utf8 scripts\run_round3.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
from kaju_core import gpu_busy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PY = sys.executable


def step(*args):
    gpu_busy.mark("训练第 3 轮写手")
    print(f"=== {' '.join(args)} {time.strftime('%H:%M:%S')}", flush=True)
    p = subprocess.run([PY, "-I", "-X", "utf8", *args], cwd=rt.VT)
    if p.returncode:
        raise SystemExit(f"=== 失败：{' '.join(args)}")


def main():
    live, new = rt.state()["live_model"], rt.model_name(3)
    try:
        step(os.path.join(HERE, "prepare_r3.py"))
        for c in ("data", "train", "import", "exam"):
            step(os.path.join(HERE, "round_train.py"), c, "--round", "3")
        step(os.path.join(HERE, "exam_p3.py"), live, new, "--cards", "v5")
    finally:
        gpu_busy.clear()
    rows = ["| 项 | 线上 v4 卡 | 第 3 轮 v4 卡 | 线上 v5 卡 | 第 3 轮 v5 卡 |", "|---|---|---|---|---|"]
    s = [rt.summary(live), rt.summary(new), rt.summary(live + "_v5"), rt.summary(new + "_v5")]
    for k in (s[1] or {}):
        rows.append(f"| {k} | " + " | ".join(str((x or {}).get(k, "?")) for x in s) + " |")
    rep = os.path.join(rt.rdir(3), "exam_both.md")
    open(rep, "w", encoding="utf-8").write("考试：两种卡（v4 = 现在线上的卡，是上线闸门；v5 = 带背景的卡）\n\n" + "\n".join(rows) + "\n")
    print("\n".join(rows), "\n→", rep, "\n=== ALL DONE", flush=True)


if __name__ == "__main__":
    main()
