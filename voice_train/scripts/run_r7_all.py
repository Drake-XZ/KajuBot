r"""第 7 轮一条龙（2026-11-17 兄长：“开始训练，记录训练用的数据、训练完后的结果，然后自动关机”）。

1. 跑 run_r7.py（训 H → 合并 → 训 K → 偏好对子 → 导入 Ollama → 考试 v8 / v7 → 固定评判重判 → 量尺）
2. 写报告 data\rounds_v4\r7\report.md：训练用的数据（info.json、卡怎么来的、花了多少）、每步用时、验证损失、重判表、量尺
3. 往 AGENT.md 第十节最上面加一条（结果摘要 + 报告位置）
4. 关机（shutdown /s /t 120；成功失败都关，失败的话报告里写清楚停在哪一步）。要取消：cmd 里 shutdown /a
不上线：线上写手照旧 r6，群聊暂停照旧开着（兄长自己恢复）。
用法（AstrBot 的 Python，独立进程起）：python -I -X utf8 scripts\run_r7_all.py [--no-shutdown]
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
VT = os.path.dirname(HERE)
R7 = os.path.join(VT, "data", "rounds_v4", "r7")
AGENT = r"D:\JiashuBot\AGENT.md"
NAME = "kaju-writer-p6-8b-r7"
LIVE = "kaju-writer-p5-8b-r6"
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def read(p, default=""):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return default


def losses(d):
    """train_log.txt 里的验证损失（训练前、各次、最好）。"""
    txt = read(os.path.join(R7, d, "train_log.txt"))
    xs = re.findall(r"验证损失\s*([\d.]+)", txt)
    return f"{xs[0]} → 最后 {xs[-1]}，最低 {min(xs, key=float)}（共量 {len(xs)} 次）" if xs else "（没有记录）"


def newest(pattern, since):
    fs = [f for f in glob.glob(pattern) if os.path.getmtime(f) >= since]
    return max(fs, key=os.path.getmtime) if fs else None


def speech(model):
    p = os.path.join(VT, "data", "speech", f"exam-{model}.json")
    try:
        return json.load(open(p, encoding="utf-8")).get("summary") or {}
    except (OSError, ValueError):
        return {}


def report(t0, rc):
    info = json.loads(read(os.path.join(R7, "info.json"), "{}") or "{}")
    cost = re.findall(r"这批估 ([\d.]+) 元", read(os.path.join(R7, "cards_full.log")))
    L = [f"# 第 7 轮训练报告（{time.strftime('%Y-%m-%d %H:%M')} 本机）", "",
         f"结果：{'全部跑完' if rc == 0 else f'**没跑完（返回 {rc}），停在哪一步见下面的用时表**'}。写手 `{NAME}`，**没上线**（线上照旧 `{LIVE}`）。", "",
         "## 训练用的数据", "",
         "- 底子：r6 的训练包（`r6\\h_data`、`r6\\k_data`）。H 接 r6 的 H（`r6\\H\\best`）训，合并成 `models\\Qwen3-8B-H-r7`；K 接 r6 最后那版 K（`r6\\R\\last`）。",
         "- **长聊天**：群聊、兄长私聊、金句、旧人工样本从 kaju_life 聊天记录重建，原作从原文往前取段落（`prepare_r7.py ctx` → `long_ctx.json`）；"
         "上限 12 行 / 1000 字（`longctx.MAX_LINES / MAX_CHARS`，和线上同一个），每行“时:分 称呼：话”，换天插日期行；lccc、B 站评论没有更长的、照旧。",
         "- **新卡**（`prepare_r7_cards.py` → `cards.jsonl`）：规划器 v6 的样子——局面不复述聊天、要接住的、要说到的 ≤2 条短事实（原来“无”的照旧）、"
         "背景只留长聊天里看不到的、约三成掺一条别的样本的背景（答案没用它）、心情行照旧。"
         f"出卡花费约 {round(0.4035 + sum(map(float, cost)), 2)} 元。",
         "- 恋爱向的样本（目标里有那类词）不进；系统提示 v5（去掉“不说你”，`card.SYSTEM_V5`）。",
         "- 训练参数：4bit、--lowmem、bs 1 × accum 16、lr 5e-5、1 轮、max_len 1664；K 金句重复 3 遍、复习 30%；偏好对子 lr 5e-6、2 轮。", "",
         "```json", json.dumps(info, ensure_ascii=False, indent=1), "```", "",
         "## 每步用时", "", "```", read(os.path.join(R7, "run.log")).strip()[-4000:], "```", "",
         "## 验证损失", "", f"- H：{losses('H')}", f"- K：{losses('K')}", ""]
    for cards in ("v8", "v7"):
        f = newest(os.path.join(VT, "data", "rejudge", f"*_{cards}.md"), t0)
        L += [f"## 固定评判重判（{cards} 卡{'，长聊天' if cards == 'v8' else '，短聊天'}）", ""]
        if f:
            body = read(f)
            L += [f"文件：`{f}`", "", body.split("\n## ")[0].strip(), ""]
        else:
            L += ["（没有这一份）", ""]
    L += ["## 量尺（说人话）", "", "| 项 | " + " | ".join([LIVE + " v8", NAME + " v8", NAME + " v7"]) + " |", "|---|---|---|---|"]
    ss = [speech(LIVE + "_v8"), speech(NAME + "_v8"), speech(NAME + "_v7")]
    for k in (ss[1] or ss[0] or {}):
        L.append(f"| {k} | " + " | ".join(str(s.get(k, "")) for s in ss) + " |")
    L += ["", "考试逐题：`data\\daily\\reports\\exam-p3*.md`、`data\\exam_p3_<写手>_v8.json`；量尺：`data\\speech\\`。",
          "", "下一步（兄长回来后）：看这份报告 → 出盲选页（v8 卡 + 长聊天，r6 vs r7）→ 兄长点头 → 备份 → 一起换：",
          "`rewrite.card_model=kaju-writer-p6-8b-r7`、`rewrite.writer_system=v5`、`rewrite.long_ctx=true`、出卡改 PLAN v6（B 那条路，还没写）；"
          "回滚三项改回去。"]
    path = os.path.join(R7, "report.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return path, info


def agent_entry(rc, path):
    v8 = newest(os.path.join(VT, "data", "rejudge", "*_v8.md"), 0)
    table = ""
    if v8:
        rows = [x for x in read(v8).splitlines() if x.startswith("| 漏答 |") or x.startswith("| 编造 |") or x.startswith("| 自然")
                or x.startswith("| 佳树") or x.startswith("| 意思")]
        table = "；".join(x.strip("| ").replace(" | ", " ") for x in rows)
    head = "每条写：日期、当前目标、做了什么 / 改了哪些文件和配置、结果、没做完的。第二节同时改成最新状态。\n"
    entry = (f"\n### 本机 {time.strftime('%m-%d %H:%M')}（`run_r7_all.py` 自动写的）第 7 轮训练{'跑完' if rc == 0 else f'没跑完（返回 {rc}）'}\n"
             f"- 写手 `{NAME}` 在 Ollama 里，**没上线**；报告（训练用的数据、用时、损失、重判、量尺）：`{path}`。\n"
             f"- v8 卡（长聊天）重判，{LIVE} 对 {NAME}：{table or '（没有重判结果）'}。\n"
             "- 跑完按兄长说的自动关机了；群聊暂停照旧开着。机器人、Ollama 开机后都要手动起，小号 QQ 要兄长手动登。\n")
    s = read(AGENT)
    if head in s:
        open(AGENT, "w", encoding="utf-8").write(s.replace(head, head + entry, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-shutdown", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    rc = -1
    try:
        rc = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "run_r7.py")], cwd=VT).returncode
    except Exception as e:  # noqa: BLE001
        print("run_r7 起不来", e, flush=True)
    try:
        path, _ = report(t0, rc)
        agent_entry(rc, path)
        print("报告 →", path, flush=True)
    except Exception as e:  # noqa: BLE001  报告写坏了也要关机
        print("写报告出错", type(e).__name__, e, flush=True)
    if not a.no_shutdown:
        subprocess.run(["shutdown", "/s", "/t", "120", "/c", "佳树第 7 轮训练跑完了，2 分钟后关机（取消：shutdown /a）"])


if __name__ == "__main__":
    main()
