"""盯着 train_v2.py：每 5 分钟把训练过程整理成报告，训完自动关机（2026-11-09 兄长大人要）。

报告：results\\layered_v2\\训练记录.md（过程中一直更新）
  - 各阶段开始/结束时间（status.txt）
  - H、K 的步数、损失曲线（每 100 步一个点）、验证损失、显存峰值、用时（log.txt + run.json）
  - 卡片重抽的条数和花费（data\\layered_v2\\meta.json）
结束：
  - status.txt 出现"全部好了" → 写完报告，shutdown /s /t 300（5 分钟后关机，取消：shutdown /a）
  - 出现"出错" → 写完报告，不关机（留着机器好查问题）
用法：python -I watch_v2.py [--no-shutdown]
"""
import json
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
VT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(VT, "results", "layered_v2")
LOG, STATUS = os.path.join(OUT, "log.txt"), os.path.join(OUT, "status.txt")
REPORT = os.path.join(OUT, "训练记录.md")
STEP = re.compile(r"第 (\d+) 轮 (\d+)/(\d+) 步\s+损失 ([\d.]+)\s+已用 ([\d.]+) 分钟.*?显存峰值 ([\d.]+)GB")


def read(p):
    return open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""


def stages(log):
    """log.txt 按 "阶段 N：" 切成 H（阶段 1）和 K（阶段 2）两段。"""
    out, cur = {}, None
    for line in log.splitlines():
        m = re.search(r"阶段 ([12])：(.*)", line)
        if m:
            cur = {"1": "H", "2": "K"}[m.group(1)]
            out[cur] = {"head": m.group(2).strip(), "steps": [], "eval": []}
        elif cur:
            s = STEP.search(line)
            if s:
                out[cur]["steps"].append(tuple(float(x) for x in s.groups()))
            e = re.search(r"验证损失 ([\d.]+)", line)
            if e:
                out[cur]["eval"].append(float(e.group(1)))
    return out


def report():
    st, log = read(STATUS), read(LOG)
    L = [f"# 第二版卡片写手 kaju-writer-l2a 训练记录", "", f"更新于 {time.strftime('%Y-%m-%d %H:%M:%S')}", "", "## 过程", "", "```", st.strip(), "```", ""]
    mp = os.path.join(VT, "data", "layered_v2", "meta.json")
    if os.path.exists(mp):
        m = json.load(open(mp, encoding="utf-8"))
        L += ["## 卡片重抽", "", f"花费：{m.get('cost')}", "", "| 部分 | 原条数 | 留下 | 抽不出 | 对齐没过丢掉 |", "|---|---|---|---|---|"]
        L += [f"| {k} | {v['rows']} | {v['kept']} | {v['no_card']} | {v['align_drop']} |" for k, v in m["parts"].items()] + [""]
    for name, d in stages(log).items():
        L += [f"## {name} 层", "", d["head"], ""]
        rj = os.path.join(OUT, f"L2_{name}", "run.json")
        if os.path.exists(rj):
            L += [f"结果：`{read(rj).strip()}`", ""]
        if d["steps"]:
            last = d["steps"][-1]
            L += [f"进度：{int(last[1])}/{int(last[2])} 步，已用 {last[4]:.0f} 分钟，显存峰值 {max(s[5] for s in d['steps'])}GB", ""]
            pts = [s for s in d["steps"] if int(s[1]) % 100 == 0 or s is d["steps"][0] or s is last]
            L += ["| 步 | 损失 | 已用分钟 |", "|---|---|---|"] + [f"| {int(s[1])} | {s[3]:.3f} | {s[4]:.0f} |" for s in pts] + [""]
        if d["eval"]:
            L += [f"验证损失：{', '.join(f'{x:.3f}' for x in d['eval'])}", ""]
    open(REPORT, "w", encoding="utf-8").write("\n".join(L))
    return st


def main():
    shutdown = "--no-shutdown" not in sys.argv
    while True:
        st = report()
        if "全部好了" in st:
            report()
            if shutdown:
                subprocess.run(["shutdown", "/s", "/t", "300", "/c", "佳树写手 l2a 训完了，5 分钟后关机（取消：shutdown /a）"])
            return
        if "出错" in st:
            report()
            return
        time.sleep(300)


if __name__ == "__main__":
    main()
