r"""第 6 轮：H、K 一起重训，一口气跑完（2026-11-17，voice_train\H和K重训方案-20261117.md 第 4 步；数据先用 prepare_r6.py 准备好）。

全程 gpu_busy.hold：她不在群里说话（私聊照常）；训练 / 合并 / 导入前卸掉 Ollama 里的写手。
  1. H：train_pack\train.py --stage 1，接着 p4 的 H 训（原模型 Qwen3-8B，4bit），数据 r6\h_data（新规划器卡 + 旧 H）
  2. 合并：Qwen3-8B + 新 H → models\Qwen3-8B-H-r6（K 的底子）
  3. K（一）：train.py --stage 2，接着 p4 的 K 在新底子上训（重适配 + 学规划器卡、心情、兄长的写法），数据 r6\k_data
  4. K（二）：pref.py，心情对子 + 毛病对子（少，只是推一下）
  5. 导入 Ollama：kaju-writer-p5-8b-r6（Qwen3-8B → 新 H → 新 K）
  6. 考试：exam_p3 新写手 v4 卡（线上现在的卡）；线上写手 + 新写手 v7 卡（规划器卡）；rejudge_exam 固定评判模型重判；speech_check
--smoke：每段只跑几步，量速度和显存（不导入、不考试）
用法（AstrBot 的 Python，后台）：python -I -X utf8 scripts\run_r6.py [--smoke] [--from 步骤号]
"""
import argparse
import json
import os
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
VT, PACK = rt.VT, rt.PACK
PY_TRAIN = rt.PY_TRAIN
BASE = rt.BASE
H_OLD = rt.H_ADAPTER
K_OLD = os.path.join(VT, "train_pack", "results_v4", "results", "8b-A", "K")
BASE_H6 = os.path.join(VT, "models", "Qwen3-8B-H-r6")
NAME = "kaju-writer-p5-8b-r6"
ENV = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R6, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, env=None, what=""):
    say(f"开始：{what}")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd or VT, env=env or ENV)
    say(f"{'完成' if p.returncode == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {p.returncode}）")
    if p.returncode:
        raise SystemExit(f"{what} 失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=1)
    a = ap.parse_args()
    sfx = "_smoke" if a.smoke else ""
    h_out, k_out, r_out = (os.path.join(R6, x + sfx) for x in ("H", "K", "R"))
    smoke = ["--limit", "96", "--max_steps", "6", "--max_eval", "16"] if a.smoke else []
    common = ["--bits", "4", "--lowmem", "--grad-ckpt", "--bs", "2", "--accum", "8", "--lr", "5e-5", "--epochs", "1", "--max_len", "768",
              "--evals-per-epoch", "3", "--patience", "3"]
    with gpu_busy.hold(f"训练第 6 轮写手（H、K 一起）{'·试跑' if a.smoke else ''}"):
        rt.ollama_unload()
        if a.start <= 1:
            run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "1", "--base", BASE, "--init-adapter", H_OLD, "--out", h_out,
                 "--data-dir", os.path.join(R6, "h_data"), "--max_eval", "120", *common, *smoke], cwd=PACK, what="1. 训 H")
        h_best = os.path.join(h_out, "best")
        base_k = BASE_H6 + sfx
        if a.start <= 2:
            run([PY_TRAIN, "-I", os.path.join(HERE, "merge_stream.py"), BASE, base_k, h_best], what="2. 合并新 H")
        if a.start <= 3:
            run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "2", "--base", base_k, "--init-adapter", K_OLD, "--out", k_out,
                 "--data-dir", os.path.join(R6, "k_data"), "--curated-repeat", "3", "--replay-ratio", "0.3", "--max_eval", "120",
                 *common, *smoke], cwd=PACK, what="3. 训 K（一）")
        if a.start <= 4:
            run([PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", base_k, "--init-adapter", os.path.join(k_out, "best"), "--out", r_out,
                 "--data-dir", os.path.join(R6, "k_data"), "--bits", "4", "--lowmem", "--grad-ckpt", "--lr", "5e-6", "--epochs", "2",
                 "--pairs", "4", "--kto", "0", "--sft", "4", *(["--max_steps", "3", "--limit", "16"] if a.smoke else [])],
                cwd=PACK, what="4. 训 K（二）：心情对子、毛病对子")
        if a.smoke:
            say("试跑完：看 H_smoke / K_smoke / R_smoke 的 train_log.txt 里每步多久、显存峰值")
            return
        if a.start <= 5:
            sys.argv = sys.argv[:1]
            import daily_learn as dl
            dl.BASE = BASE
            dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")
            out = os.path.join(R6, "gguf")
            os.makedirs(out, exist_ok=True)
            rt.ollama_unload()
            say("开始：5. 导入 Ollama")
            dl.make_gguf(NAME, out, [h_best, os.path.join(r_out, "last")], os.path.join(out, "import.log"))
            say(f"完成：5. 导入 {NAME}")
    # 考试不占训练显存太久，但写手要在 Ollama 里跑：照旧挂着
    with gpu_busy.hold("第 6 轮写手考试"):
        bot_py = sys.executable
        live = rt.state()["live_model"]
        if a.start <= 6:
            run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py"), NAME], what="6a. 考试 v4 卡（线上现在的卡）")
            run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py"), live, NAME, "--cards", "v7"], what="6b. 考试 v7 卡（规划器卡）")
            for cards, models in (("v4", [live, NAME]), ("v7", [live, NAME])):
                run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "rejudge_exam.py"), *models, "--cards", cards], what=f"6c. 重判 {cards}")
            for m in (live, NAME, NAME + "_v7", live + "_v7"):
                run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "speech_check.py"), "exam", "--model", m], what=f"6d. 量尺 {m}")
    say("=== 第 6 轮全部跑完，看 data\\rejudge\\ 最新两份、data\\daily\\reports\\exam-p3*.md、data\\speech\\")


if __name__ == "__main__":
    main()
