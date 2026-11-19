r"""第 8 轮一条龙：等标签出完 → 补跑没出好的 → 打包 → 训练 + 考试（run_r8.py）。不关机、不上线。
用法（AstrBot 的 Python，独立进程起）：python -I -X utf8 scripts\run_r8_all.py --wait-pid <出标签那个进程>
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VT = os.path.dirname(HERE)
R8 = os.path.join(VT, "data", "rounds_v4", "r8")
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R8, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def alive(pid):
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in (r.stdout or "")


def step(args, what):
    say(f"开始：{what}")
    t0 = time.time()
    rc = subprocess.run([sys.executable, "-I", "-X", "utf8", *args], cwd=VT).returncode
    say(f"{'完成' if rc == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {rc}）")
    if rc:
        raise SystemExit(rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-pid", type=int, default=0)
    a = ap.parse_args()
    if a.wait_pid:
        say(f"等出标签的进程 {a.wait_pid} 跑完")
        while alive(a.wait_pid):
            time.sleep(30)
    step([os.path.join(HERE, "prepare_r8.py"), "label"], "1. 标签补跑（没出好的再出一次）")
    step([os.path.join(HERE, "prepare_r8_pack.py"), "pack"], "2. 打包 r8\\k_data")
    step([os.path.join(HERE, "run_r8.py")], "3. 训练 + 考试（run_r8.py）")


if __name__ == "__main__":
    main()
