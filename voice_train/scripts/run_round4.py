r"""第 4 轮（以及之后各轮，--round N）训练和考试一口气跑完（数据先用 prepare_r4.py / prepare_r5.py 准备好）。

全程挂 kaju_core.gpu_busy（群聊先不回；进程结束标记自动失效）。
  1. round_train.py data / train / import / exam --round 4（exam = 现在线上的 v4 卡，上线闸门之一）
  2. exam_p3.py 线上写手 和 第 4 轮 --cards v6（规划器卡的样子；第四阶段线上就换这种）
  3. speech_check.py exam：四份考试输出各量一遍（佳树连用 / 成话 / 接得上 / 念卡，11-16 兄长指出的三个毛病）
  4. data\rounds_v4\r4\exam_both.md 并排
闸门：v4 卡上漏答、编造、硬伤、打转不比线上多；v6 卡上漏答、编造、佳树连用、不成话、接不上比线上写手少。都过了才出盲选页。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\run_round4.py
"""
import json
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
N = int(sys.argv[sys.argv.index("--round") + 1]) if "--round" in sys.argv else 4  # 11-16：第 5 轮也用它（--round 5）


def step(*args):
    gpu_busy.mark(f"训练第 {N} 轮写手")
    print(f"=== {' '.join(os.path.basename(a) for a in args)} {time.strftime('%H:%M:%S')}", flush=True)
    p = subprocess.run([PY, "-I", "-X", "utf8", *args], cwd=rt.VT)
    if p.returncode:
        raise SystemExit(f"=== 失败：{' '.join(args)}")


def speech(name):
    p = os.path.join(rt.VT, "data", "speech", f"exam-{name}.json")
    return json.load(open(p, encoding="utf-8"))["summary"] if os.path.exists(p) else {}


def main():
    live, new = rt.state()["live_model"], rt.model_name(N)
    try:
        for c in ("data", "train", "import", "exam"):
            step(os.path.join(HERE, "round_train.py"), c, "--round", str(N))
        step(os.path.join(HERE, "exam_p3.py"), live, new, "--cards", "v6")
        for m in (live, new, live + "_v6", new + "_v6"):
            step(os.path.join(HERE, "speech_check.py"), "exam", "--model", m)
    finally:
        gpu_busy.clear()
    names = [live, new, live + "_v6", new + "_v6"]
    s = [{**(rt.summary(m) or {}), **{"说人话·" + k: v for k, v in speech(m).items() if k in ("佳树连用≥3", "成话率", "接得上率", "念卡率")}}
         for m in names]
    rows = ["| 项 | 线上 v4 卡 | 第 4 轮 v4 卡 | 线上 v6 卡 | 第 4 轮 v6 卡 |", "|---|---|---|---|---|"]
    for k in (s[1] or {}):
        rows.append(f"| {k} | " + " | ".join(str(x.get(k, "?")) for x in s) + " |")
    rep = os.path.join(rt.rdir(N), "exam_both.md")
    open(rep, "w", encoding="utf-8").write("考试：v4 = 现在线上的卡（上线闸门）；v6 = 规划器卡的样子（局面 + 要接住的 + 背景）\n\n" + "\n".join(rows) + "\n")
    print("\n".join(rows), "\n→", rep, "\n=== ALL DONE", flush=True)


if __name__ == "__main__":
    main()
