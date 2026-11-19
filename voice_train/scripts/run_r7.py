r"""第 7 轮训练（2026-11-17，AGENT.md 第十节）：写手多看聊天 + 规划器 v6 样子的卡，H、K 都从 r6 接着训。

和 run_r6.py 一样的几步，不同的地方：
  - 数据 data\rounds_v4\r7\h_data / k_data（prepare_r7_pack.py：长聊天、新卡、掺无关背景、系统提示 v5、恋爱向的不要）
  - H 接 r6 的 H（r6\H\best），合并成 models\Qwen3-8B-H-r7；K 接 r6 最后那版 K（r6\R\last）
  - --max_len 1664（长聊天一条约一千四百个 token；train.py 超长的整条扔掉，768 会把长聊天的全扔了）、bs 1 × accum 16（显存）
  - 考试：v8 卡（长聊天 + 不看答案的局面）为主，r7 用系统提示 v5、线上 r6 照旧；另考 v7（短聊天）对照；固定评判重判；量尺
全程 gpu_busy.hold（她不在群里说话）。不自动上线。
用法（AstrBot 的 Python）：python -I -X utf8 scripts\run_r7.py [--smoke] [--from N]
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round_train as rt  # noqa: E402
import train_keys  # noqa: E402,F401
from kaju_core import gpu_busy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
R6 = os.path.join(rt.ROOT, "r6")
R7 = os.path.join(rt.ROOT, "r7")
VT, PACK = rt.VT, rt.PACK
PY_TRAIN = rt.PY_TRAIN
BASE = rt.BASE
H_OLD = os.path.join(R6, "H", "best")
K_OLD = os.path.join(R6, "R", "last")
BASE_H7 = os.path.join(VT, "models", "Qwen3-8B-H-r7")
NAME = "kaju-writer-p6-8b-r7"
ENV = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R7, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, what=""):
    say(f"开始：{what}")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd or VT, env=ENV)
    say(f"{'完成' if p.returncode == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {p.returncode}）")
    if p.returncode:
        raise SystemExit(f"{what} 失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument(
        "--from", dest="start", type=int, default=1,
        help="从指定步骤续跑。第 3 或 4 步缺少合并后的 H 时会重建。第 5 步从适配器重新导入 Ollama。",
    )
    a = ap.parse_args()
    sfx = "_smoke" if a.smoke else ""
    h_out, k_out, r_out = (os.path.join(R7, x + sfx) for x in ("H", "K", "R"))
    smoke = ["--limit", "64", "--max_steps", "4", "--max_eval", "8"] if a.smoke else []
    common = ["--bits", "4", "--lowmem", "--grad-ckpt", "--bs", "1", "--accum", "16", "--lr", "5e-5", "--epochs", "1",
              "--max_len", "1664", "--evals-per-epoch", "3", "--patience", "3"]
    with gpu_busy.hold(f"训练第 7 轮写手（写手多看聊天）{'·试跑' if a.smoke else ''}"):
        rt.ollama_unload()
        if a.start <= 1:
            run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "1", "--base", BASE, "--init-adapter", H_OLD, "--out", h_out,
                 "--data-dir", os.path.join(R7, "h_data"), "--max_eval", "120", *common, *smoke], cwd=PACK, what="1. 训 H")
        h_best = os.path.join(h_out, "best")
        base_k = BASE_H7 + sfx
        if a.start <= 2 or (a.start <= 4 and not os.path.isdir(base_k)):
            if os.path.lexists(base_k):
                raise FileExistsError(base_k)
            # 合并完整后再将目录放到正式路径，失败后仍可续跑。
            with tempfile.TemporaryDirectory(prefix=".merge-r7-", dir=os.path.dirname(base_k)) as tmp:
                merged = os.path.join(tmp, "model")
                run([PY_TRAIN, "-I", os.path.join(HERE, "merge_stream.py"), BASE, merged, h_best], what="2. 合并新 H")
                os.rename(merged, base_k)
        if a.start <= 3:
            run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "2", "--base", base_k, "--init-adapter", K_OLD, "--out", k_out,
                 "--data-dir", os.path.join(R7, "k_data"), "--curated-repeat", "3", "--replay-ratio", "0.3", "--max_eval", "120",
                 *common, *smoke], cwd=PACK, what="3. 训 K（一）")
        if a.start <= 4:
            run([PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", base_k, "--init-adapter", os.path.join(k_out, "best"), "--out", r_out,
                 "--data-dir", os.path.join(R7, "k_data"), "--bits", "4", "--lowmem", "--grad-ckpt", "--lr", "5e-6", "--epochs", "2",
                 "--pairs", "4", "--kto", "0", "--sft", "4", *(["--max_steps", "3", "--limit", "16"] if a.smoke else [])],
                cwd=PACK, what="4. 训 K（二）：心情对子、毛病对子")
        if a.smoke:
            say("试跑完：看 H_smoke / K_smoke / R_smoke 的 train_log.txt 里每步多久、显存峰值、扔了几条超长的")
            return
        if a.start <= 5:
            sys.argv = sys.argv[:1]
            import daily_learn as dl
            dl.BASE = BASE
            dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")
            out = os.path.join(R7, "gguf")
            os.makedirs(out, exist_ok=True)
            rt.ollama_unload()
            say("开始：5. 导入 Ollama")
            dl.make_gguf(NAME, out, [h_best, os.path.join(r_out, "last")], os.path.join(out, "import.log"))
            say(f"完成：5. 导入 {NAME}")
    with gpu_busy.hold("第 7 轮写手考试"):
        bot_py = sys.executable
        live = rt.state()["live_model"]
        ex = [bot_py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py")]
        if a.start <= 6:
            run([*ex, live, "--cards", "v8"], what="6a. 考试 v8 卡（长聊天）：线上 r6")
            run([*ex, NAME, "--cards", "v8", "--system", "v5"], what="6b. 考试 v8 卡（长聊天）：r7")
            run([*ex, NAME, "--cards", "v7", "--system", "v5"], what="6c. 考试 v7 卡（短聊天）：r7")
            for cards in ("v8", "v7"):
                run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "rejudge_exam.py"), live, NAME, "--cards", cards], what=f"6d. 重判 {cards}")
            for m in (live + "_v8", NAME + "_v8", NAME + "_v7"):
                run([bot_py, "-I", "-X", "utf8", os.path.join(HERE, "speech_check.py"), "exam", "--model", m], what=f"6e. 量尺 {m}")
    say("=== 第 7 轮全部跑完，看 data\\rejudge\\ 最新两份、data\\daily\\reports\\exam-p3*.md、data\\speech\\")


if __name__ == "__main__":
    main()
