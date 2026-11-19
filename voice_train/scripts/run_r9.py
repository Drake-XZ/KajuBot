r"""第 9 轮：人格对子偏好训练（2026-11-18 兄长：“开始训练”；AGENT.md 第十节）。

  - 不重训 K 的监督那一步：直接接线上 r7k 的 K（r7k\R\last），底子 models\Qwen3-8B-H-r6，用 pref.py 训
  - 数据 data\rounds_v4\r9\k_data（prepare_r9_pack.py）：人格对子 568 对（chosen = 佳树原句，rejected = Claude 写的平淡版 / 过头版）
    + r7k 原来 24 对；复习 stage2 去掉了恋爱 / 亲密；系统提示照旧 v5（兄长：不加身份）
  - 导入 kaju-writer-p8-8b-r9（r6 的 H + 这次的 K）
  - 考试：v9（标签卡，像线上大脑）和 v8（句子卡），r7k、r9 同一时段都考；固定评判重判（限 40 分钟）；量尺；报告 r9\report.md
不关机、不上线。全程 gpu_busy.hold（群里不说话）。
用法（AstrBot 的 Python，独立进程起）：python -I -X utf8 scripts\run_r9.py [--from N]
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
R9 = os.path.join(rt.ROOT, "r9")
VT, PACK = rt.VT, rt.PACK
PY_TRAIN = rt.PY_TRAIN
BASE = rt.BASE
BASE_H6 = os.path.join(VT, "models", "Qwen3-8B-H-r6")
H6 = os.path.join(R6, "H", "best")
K_OLD = os.path.join(R7K, "R", "last")
NAME = "kaju-writer-p8-8b-r9"
LIVE = "kaju-writer-p6-8b-r7k"
ENV = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:128"}


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(R9, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, cwd=None, what="", must=True, timeout=None):
    say(f"开始：{what}")
    t0 = time.time()
    try:
        rc = subprocess.run(cmd, cwd=cwd or VT, env=ENV, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        rc = "超时"
    say(f"{'完成' if rc == 0 else '失败'}：{what}（{(time.time() - t0) / 60:.1f} 分钟，返回 {rc}）")
    if rc != 0 and must:
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

    out = read(os.path.join(R9, "run.out.txt"))
    L = [f"# 第 9 轮（人格对子偏好训练）报告（{time.strftime('%Y-%m-%d %H:%M')} 本机）", "",
         f"结果：{'全部跑完' if ok else '**没跑完，见用时表**'}。写手 `{NAME}`（r6 的 H + r7k 的 K 接着偏好训练），**没上线**（线上 `{LIVE}`）。", "",
         "## 数据", "", "```json", read(os.path.join(R9, "info.json")).strip(), "```", "",
         "## 用时", "", "```", read(os.path.join(R9, "run.log")).strip(), "```", "",
         "## 偏好训练留出题（metrics.json）", "", "```json", read(os.path.join(R9, "R", "metrics.json")).strip()[:4000], "```", "",
         "## 考试自己的评判（对 r003；两个写手同一时段考）", ""]
    L += [f"- {x}" for x in re.findall(r"^kaju-writer-\S+　\d+ 对：.*$", out, re.M)] + [""]
    for cards in ("v9", "v8"):
        f = newest(cards)
        L += [f"## 固定评判重判（{cards}）", "", read(f).split("\n## ")[0].strip() if f else "（没有）", ""]
    for cards in ("v9", "v8"):
        L += [f"## 量尺 {cards}", "", f"| 项 | r7k {cards} | r9 {cards} |", "|---|---|---|"]
        ss = []
        for m in (f"{LIVE}_{cards}", f"{NAME}_{cards}"):
            try:
                ss.append(json.load(open(os.path.join(VT, "data", "speech", f"exam-{m}.json"), encoding="utf-8")).get("summary") or {})
            except (OSError, ValueError):
                ss.append({})
        for k in (ss[1] or ss[0]):
            L.append(f"| {k} | " + " | ".join(str(s.get(k, "")) for s in ss) + " |")
        L.append("")
    path = os.path.join(R9, "report.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=4)
    a = ap.parse_args()
    t0 = time.time()
    r_out = os.path.join(R9, "R")
    ok = False
    try:
        with gpu_busy.hold("第 9 轮人格对子偏好训练"):
            rt.ollama_unload()
            if a.start <= 4:
                run([PY_TRAIN, "-s", os.path.join(PACK, "pref.py"), "--base", BASE_H6, "--init-adapter", K_OLD,
                     "--out", r_out, "--data-dir", os.path.join(R9, "k_data"), "--bits", "4", "--lowmem", "--grad-ckpt", "--lr", "5e-6",
                     "--epochs", "2", "--pairs", "4", "--kto", "0", "--sft", "4"], cwd=PACK, what="4. 偏好训练：人格对子")
            if a.start <= 5:
                sys.argv = sys.argv[:1]
                import daily_learn as dl
                dl.BASE = BASE
                dl.TEMPLATE = os.path.join(VT, "models", "kaju-writer-p3-8b.Modelfile")
                out = os.path.join(R9, "gguf")
                os.makedirs(out, exist_ok=True)
                rt.ollama_unload()
                say("开始：5. 导入 Ollama")
                dl.make_gguf(NAME, out, [H6, os.path.join(r_out, "last")], os.path.join(out, "import.log"))
                say(f"完成：5. 导入 {NAME}")
        with gpu_busy.hold("第 9 轮考试"):
            py = sys.executable
            ex = [py, "-I", "-X", "utf8", os.path.join(HERE, "exam_p3.py")]
            if a.start <= 6:
                for cards in ("v9", "v8"):
                    run([*ex, LIVE, "--cards", cards, "--system", "v5"], what=f"6. 考试 {cards}：线上 r7k")
                    run([*ex, NAME, "--cards", cards, "--system", "v5"], what=f"6. 考试 {cards}：r9")
            if a.start <= 7:  # 中转限流时重判可能判不出来：各限 40 分钟，不挡后面
                for cards in ("v9", "v8"):
                    run([py, "-I", "-X", "utf8", os.path.join(HERE, "rejudge_exam.py"), LIVE, NAME, "--cards", cards],
                        what=f"7. 重判 {cards}", must=False, timeout=40 * 60)
            if a.start <= 8:
                for cards in ("v9", "v8"):
                    for m in (f"{LIVE}_{cards}", f"{NAME}_{cards}"):
                        run([py, "-I", "-X", "utf8", os.path.join(HERE, "speech_check.py"), "exam", "--model", m], what=f"8. 量尺 {m}", must=False)
        ok = True
    finally:
        say("报告 → " + report(t0, ok))


if __name__ == "__main__":
    main()
