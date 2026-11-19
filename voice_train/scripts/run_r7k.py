r"""第 7 轮 K 单独重训（2026-11-17 兄长：“Yes, retrain K”；AGENT.md 第十节）。

r7 输了，主要因为新卡把“要说到的”压到 ≤2 条。这次：
  - H 不动：K 接在 r6 的 H 上（models\Qwen3-8B-H-r6），从 r6 最后那版 K（r6\R\last）接着训
  - 数据 data\rounds_v4\r7k\k_data（prepare_r7k.py）：r7 的包，要说到的换回原来的；长聊天、短局面、掺背景、系统提示 v5 照留；
    恋爱话题的样本（目标、卡、聊天最后一行里有那类词）不进
  - 偏好对子照 r7（心情对子、毛病对子）
  - 导入 kaju-writer-p6-8b-r7k（r6 的 H + 这次的 K）
  - 考试：v8（长聊天）线上 r6 和 r7k 都考、v7（短聊天）考 r7k；固定评判重判；量尺；报告 r7k\report.md
不关机、不上线。全程 gpu_busy.hold（群里不说话）。
用法（AstrBot 的 Python，独立进程起）：python -I -X utf8 scripts\run_r7k.py [--from N]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import train_keys  # noqa: E402,F401
from kaju_core import gpu_busy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
R6 = os.path.join(rt.ROOT, "r6")
R7K = os.path.join(rt.ROOT, "r7k")
VT, PACK = rt.VT, rt.PACK
PY_TRAIN = rt.PY_TRAIN
BASE = rt.BASE
BASE_H6 = os.path.join(VT, "models", "Qwen3-8B-H-r6")
H6 = os.path.join(R6, "H", "best")
K_OLD = os.path.join(R6, "R", "last")
NAME = "kaju-writer-p6-8b-r7k"
LIVE = "kaju-writer-p5-8b-r6"
ENV = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R7K, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, what=""):
    say(f"开始：{what}")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd or VT, env=ENV)
    say(f"{'完成' if p.returncode == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {p.returncode}）")
    if p.returncode:
        raise SystemExit(f"{what} 失败")


def read(p):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return ""


def report(t0, ok):
    def newest(cards):
        fs = [f for f in glob.glob(os.path.join(VT, "data", "rejudge", f"*_{cards}.md")) if os.path.getmtime(f) >= t0]
        return max(fs, key=os.path.getmtime) if fs else None

    xs = re.findall(r"验证损失\s*([\d.]+)", read(os.path.join(R7K, "K", "train_log.txt")))
    L = [f"# 第 7 轮 K 单独重训报告（{time.strftime('%Y-%m-%d %H:%M')} 本机）", "",
         f"结果：{'全部跑完' if ok else '**没跑完，见用时表**'}。写手 `{NAME}`（r6 的 H + 这次的 K），**没上线**。", "",
         "## 数据", "", "```json", read(os.path.join(R7K, "info.json")).strip(), "```", "",
         "## 用时", "", "```", read(os.path.join(R7K, "run.log")).strip(), "```", "",
         f"## K 验证损失：{xs[0] + ' → 最后 ' + xs[-1] if xs else '（没有）'}", ""]
    for cards in ("v8", "v7"):
        f = newest(cards)
        L += [f"## 固定评判重判（{cards}）", "", read(f).split("\n## ")[0].strip() if f else "（没有）", ""]
    L += ["## 量尺", "", "| 项 | r6 v8 | r7k v8 | r7k v7 |", "|---|---|---|---|"]
    ss = []
    for m in (LIVE + "_v8", NAME + "_v8", NAME + "_v7"):
        try:
            ss.append(json.load(open(os.path.join(VT, "data", "speech", f"exam-{m}.json"), encoding="utf-8")).get("summary") or {})
        except (OSError, ValueError):
            ss.append({})
    for k in (ss[1] or ss[0]):
        L.append(f"| {k} | " + " | ".join(str(s.get(k, "")) for s in ss) + " |")
    path = os.path.join(R7K, "report.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=3)
    a = ap.parse_args()
    t0 = time.time()
    k_out, r_out = os.path.join(R7K, "K"), os.path.join(R7K, "R")
    common = ["--bits", "4", "--lowmem", "--grad-ckpt", "--bs", "1", "--accum", "16", "--lr", "5e-5", "--epochs", "1",
              "--max_len", "1664", "--evals-per-epoch", "3", "--patience", "3"]
    ok = False
    try:
        with gpu_busy.hold("第 7 轮 K 单独重训"):
            rt.ollama_unload()
            if a.start <= 3:
                run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "2", "--base", BASE_H6, "--init-adapter", K_OLD, "--out", k_out,
                     "--data-dir", os.path.join(R7K, "k_data"), "--curated-repeat", "3", "--replay-ratio", "0.3", "--max_eval", "120",
                     *common], cwd=PACK, what="3. 训 K（一）")
            if a.start <= 4:
                run([PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", BASE_H6, "--init-adapter", os.path.join(k_out, "best"),
                     "--out", r_out, "--data-dir", os.path.join(R7K, "k_data"), "--bits", "4", "--lowmem", "--grad-ckpt", "--lr", "5e-6",
                     "--epochs", "2", "--pairs", "4", "--kto", "0", "--sft", "4"], cwd=PACK, what="4. 训 K（二）：心情对子、毛病对子")
            if a.start <= 5:
                sys.argv = sys.argv[:1]
                import daily_learn as dl
                dl.BASE = BASE
                dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")
                out = os.path.join(R7K, "gguf")
                os.makedirs(out, exist_ok=True)
                rt.ollama_unload()
                say("开始：5. 导入 Ollama")
                dl.make_gguf(NAME, out, [H6, os.path.join(r_out, "last")], os.path.join(out, "import.log"))
                say(f"完成：5. 导入 {NAME}")
        with gpu_busy.hold("第 7 轮 K 重训考试"):
            py = sys.executable
            ex = [py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py")]
            if a.start <= 6:
                run([*ex, LIVE, "--cards", "v8"], what="6a. 考试 v8（长聊天）：线上 r6")
                run([*ex, NAME, "--cards", "v8", "--system", "v5"], what="6b. 考试 v8（长聊天）：r7k")
                run([*ex, NAME, "--cards", "v7", "--system", "v5"], what="6c. 考试 v7（短聊天）：r7k")
                for cards in ("v8", "v7"):
                    run([py, "-I", "-X", "utf8", os.path.join(HERE, "rejudge_exam.py"), LIVE, NAME, "--cards", cards], what=f"6d. 重判 {cards}")
                for m in (LIVE + "_v8", NAME + "_v8", NAME + "_v7"):
                    run([py, "-I", "-X", "utf8", os.path.join(HERE, "speech_check.py"), "exam", "--model", m], what=f"6e. 量尺 {m}")
        ok = True
    finally:
        say("报告 → " + report(t0, ok))


if __name__ == "__main__":
    main()
