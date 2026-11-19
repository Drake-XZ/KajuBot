r"""第 8 轮：人格进写手，只重训 K（2026-11-17 兄长：“Round 8 persona training”；AGENT.md 第十节）。

  - H 不动：底子 models\Qwen3-8B-H-r6（线上 r7k 的 H 也是它），K 接线上 r7k 的 K（r7k\R\last）
  - 数据 data\rounds_v4\r8\k_data（prepare_r8.py label + prepare_r8_pack.py gold / pack）：要说到的换成标签卡、兄长备注 49 条、
    长前文对不上的换回短的、恋爱话题词表加宽去掉；系统提示照旧 v5（兄长：不加身份，只靠训练）
  - 偏好对子照 r7k
  - 导入 kaju-writer-p7-8b-r8（r6 的 H + 这次的 K）
  - 考试：v9（标签卡、长聊天）线上 r7k 和 r8 都考；固定评判重判；量尺；报告 r8\report.md
不关机、不上线。全程 gpu_busy.hold（群里不说话）。
用法（AstrBot 的 Python，独立进程起）：python -I -X utf8 scripts\run_r8.py [--from N]
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
R8 = os.path.join(rt.ROOT, "r8")
VT, PACK = rt.VT, rt.PACK
PY_TRAIN = rt.PY_TRAIN
BASE = rt.BASE
BASE_H6 = os.path.join(VT, "models", "Qwen3-8B-H-r6")
H6 = os.path.join(R6, "H", "best")
K_OLD = os.path.join(R7K, "R", "last")
NAME = "kaju-writer-p7-8b-r8"
LIVE = "kaju-writer-p6-8b-r7k"
ENV = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R8, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, what="", must=True):
    say(f"开始：{what}")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd or VT, env=ENV)
    say(f"{'完成' if p.returncode == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {p.returncode}）")
    if p.returncode and must:
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

    xs = re.findall(r"验证损失\s*([\d.]+)", read(os.path.join(R8, "K", "train_log.txt")))
    out = read(os.path.join(R8, "run.out.txt"))
    L = [f"# 第 8 轮（人格进写手，只重训 K）报告（{time.strftime('%Y-%m-%d %H:%M')} 本机）", "",
         f"结果：{'全部跑完' if ok else '**没跑完，见用时表**'}。写手 `{NAME}`（r6 的 H + 这次的 K），**没上线**（线上 `{LIVE}`）。", "",
         "## 数据", "", "```json", read(os.path.join(R8, "info.json")).strip(), "```", "",
         "## 用时", "", "```", read(os.path.join(R8, "run.log")).strip(), "```", "",
         f"## K 验证损失：{xs[0] + ' → 最后 ' + xs[-1] if xs else '（没有）'}", "",
         "## 考试自己的评判（v9 标签卡、长聊天；对 r003）", ""]
    L += [f"- {x}" for x in re.findall(r"^kaju-writer-\S+　\d+ 对：.*$", out, re.M)] + [""]
    f = newest("v9")
    L += ["## 固定评判重判（v9）", "", read(f).split("\n## ")[0].strip() if f else "（没有）", ""]
    L += ["## 量尺", "", "| 项 | r7k v9 | r8 v9 |", "|---|---|---|"]
    ss = []
    for m in (LIVE + "_v9", NAME + "_v9"):
        try:
            ss.append(json.load(open(os.path.join(VT, "data", "speech", f"exam-{m}.json"), encoding="utf-8")).get("summary") or {})
        except (OSError, ValueError):
            ss.append({})
    for k in (ss[1] or ss[0]):
        L.append(f"| {k} | " + " | ".join(str(s.get(k, "")) for s in ss) + " |")
    path = os.path.join(R8, "report.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=3)
    a = ap.parse_args()
    t0 = time.time()
    k_out, r_out = os.path.join(R8, "K"), os.path.join(R8, "R")
    common = ["--bits", "4", "--lowmem", "--grad-ckpt", "--bs", "1", "--accum", "16", "--lr", "5e-5", "--epochs", "1",
              "--max_len", "1664", "--evals-per-epoch", "3", "--patience", "3"]
    ok = False
    try:
        with gpu_busy.hold("第 8 轮 K 重训（人格进写手）"):
            rt.ollama_unload()
            if a.start <= 3:
                run([PY_TRAIN, "-s", os.path.join(PACK, "train.py"), "--stage", "2", "--base", BASE_H6, "--init-adapter", K_OLD, "--out", k_out,
                     "--data-dir", os.path.join(R8, "k_data"), "--curated-repeat", "3", "--replay-ratio", "0.3", "--max_eval", "120",
                     *common], cwd=PACK, what="3. 训 K（一）")
            if a.start <= 4:
                run([PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", BASE_H6, "--init-adapter", os.path.join(k_out, "best"),
                     "--out", r_out, "--data-dir", os.path.join(R8, "k_data"), "--bits", "4", "--lowmem", "--grad-ckpt", "--lr", "5e-6",
                     "--epochs", "2", "--pairs", "4", "--kto", "0", "--sft", "4"], cwd=PACK, what="4. 训 K（二）：心情对子、毛病对子")
            if a.start <= 5:
                sys.argv = sys.argv[:1]
                import daily_learn as dl
                dl.BASE = BASE
                dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")
                out = os.path.join(R8, "gguf")
                os.makedirs(out, exist_ok=True)
                rt.ollama_unload()
                say("开始：5. 导入 Ollama")
                dl.make_gguf(NAME, out, [H6, os.path.join(r_out, "last")], os.path.join(out, "import.log"))
                say(f"完成：5. 导入 {NAME}")
        with gpu_busy.hold("第 8 轮考试"):
            py = sys.executable
            ex = [py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py")]
            if a.start <= 6:
                run([*ex, LIVE, "--cards", "v9", "--system", "v5"], what="6a. 考试 v9：线上 r7k")
                run([*ex, NAME, "--cards", "v9", "--system", "v5"], what="6b. 考试 v9：r8")
            if a.start <= 7:  # 中转限流时重判可能判不出来，不挡后面的量尺和报告
                run([py, "-I", "-X", "utf8", os.path.join(HERE, "rejudge_exam.py"), LIVE, NAME, "--cards", "v9"], what="7. 重判 v9", must=False)
            if a.start <= 8:
                for m in (LIVE + "_v9", NAME + "_v9"):
                    run([py, "-I", "-X", "utf8", os.path.join(HERE, "speech_check.py"), "exam", "--model", m], what=f"8. 量尺 {m}", must=False)
        ok = True
    finally:
        say("报告 → " + report(t0, ok))


if __name__ == "__main__":
    main()
