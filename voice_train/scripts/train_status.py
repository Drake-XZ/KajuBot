"""看现在的训练进度和表现（每晚自学 / retrain_k.py 都能看）。只读，不碰训练。

    python scripts\\train_status.py          看一次
    python scripts\\train_status.py 30       每 30 秒刷新一次（Ctrl+C 退出）
"""

import glob
import os
import re
import subprocess
import sys
import time

VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(VT, "results", "daily")
DD = os.path.join(VT, "data", "daily")
STEP = re.compile(r"第 (\d+) 轮 (\d+)/(\d+) 步\s+损失 ([\d.]+)\s+已用 ([\d.]+) 分钟，预计还要 (\S+) 分钟\s+显存峰值 (\S+)")
EVAL = re.compile(r"(验证|eval)[^\n]*?损失[^\d]*([\d.]+)|eval_loss['\"]?:\s*([\d.]+)")


def tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().replace("\r", "\n").splitlines()[-n:]
    except OSError:
        return []


def lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [x for x in f.read().replace("\r", "\n").splitlines() if x.strip()]
    except OSError:
        return []


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()
        u, used, total, t = [x.strip() for x in out.split(",")]
        return f"显卡 占用 {u}%  显存 {int(used) / 1024:.1f}/{int(total) / 1024:.1f} GB  {t}°C"
    except Exception:  # noqa: BLE001
        return "显卡：nvidia-smi 没读到"


def show():
    logs = sorted(glob.glob(os.path.join(RES, "r*", "log*.txt")), key=os.path.getmtime)
    print(time.strftime("==== %m-%d %H:%M:%S"), "  ", gpu())
    if not logs:
        print("还没有训练日志")
        return
    log = logs[-1]
    ls = lines(log)
    age = time.time() - os.path.getmtime(log)
    print(f"日志：{os.path.relpath(log, VT)}（{age / 60:.0f} 分钟前更新{'，多半已经停了' if age > 600 else ''}）")
    # 现在在哪一步：最后一条命令
    cmds = [x for x in ls if x.startswith("==== ")]
    if cmds:
        c = cmds[-1]
        what = ("训 H（说人话层）" if "--stage 1" in c else "训 K（佳树口吻层）" if "--stage 2" in c else
                "合并" if "merge_stream" in c else "转 GGUF" if "convert_hf" in c else "量化" if "quantize" in c else
                "导入 Ollama" if "ollama" in c else c[:80])
        print(f"当前：{what}（{c[5:24]} 开始）")
    # 这一段训练的损失
    seg = ls[max(i for i, x in enumerate(ls) if x.startswith("==== ")) if cmds else 0:]
    steps = [m for x in seg if (m := STEP.search(x))]
    if steps:
        last = steps[-1]
        _, s, total, loss, used, left, vram = last.groups()
        s, total = int(s), int(total)
        bar = "#" * int(30 * s / total) + "-" * (30 - int(30 * s / total))
        print(f"进度：[{bar}] {s}/{total} 步  已用 {used} 分钟，还要约 {left} 分钟  显存峰值 {vram}")
        losses = [float(m.group(4)) for m in steps]
        k = max(1, len(losses) // 4)
        print(f"损失：现在 {losses[-1]:.3f}  最低 {min(losses):.3f}  开头 {sum(losses[:k]) / k:.3f} → 最近 {sum(losses[-k:]) / k:.3f}"
              f"（{len(losses)} 个点）")
        print("      " + " ".join(f"{x:.2f}" for x in losses[-12:]))
    evals = [m for x in seg if (m := EVAL.search(x))]
    if evals:
        print("验证损失：" + " ".join((m.group(2) or m.group(3)) for m in evals[-8:]))
    # 流程日志（每晚 / 重训 K）最后几行
    for name in ("retrain_k.log", "nightly.log"):
        p = os.path.join(DD, name)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 12 * 3600:
            print(f"--- {name}")
            for x in tail(p, 4):
                print("  " + x[:160])
    # 最新的考试结果
    reps = sorted(glob.glob(os.path.join(DD, "reports", "*.md")), key=os.path.getmtime)
    if reps:
        head = tail(reps[-1], 10**6)[:3]
        verdict = next((x for x in head if x.startswith("**")), "")
        print(f"最新考试：{os.path.basename(reps[-1])}  {verdict}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    every = float(sys.argv[1]) if len(sys.argv) > 1 else 0
    while True:
        if every:
            os.system("cls" if os.name == "nt" else "clear")
        show()
        if not every:
            break
        time.sleep(every)
