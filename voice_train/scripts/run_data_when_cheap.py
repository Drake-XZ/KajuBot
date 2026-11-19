r"""等 bb-api 好了再造 H / K 的数据（2026-11-17 兄长：“等 bb-api 好了再跑”）。后台一直跑，跑完自己停。

每 15 分钟用一句短话试一下 bb-api 的 Gemini（relay_pin.probe，几乎不花钱）；通了就一批一批做：
  先 H（prepare_h_plan.py full --limit 300 --pin bb-api），做完再 K（prepare_k_plan.py run --limit 200 --pin bb-api）。
一批里没出好的超过三成（bb-api 又不稳了）就回去等。两个脚本都能续跑，停在哪接着哪。
**花钱上限**：每批脚本自己估的钱加起来超过 BUDGET 元就停下、不再跑（估的是 13 元左右，上限给到 30），等兄长看。
群聊暂停照旧开着（控制台「群聊暂停」）；这一步不用显卡。
日志：voice_train\data\run_cheap.log（北京时间不换算，本机时间）。
用法（AstrBot 的 Python，后台）：python -I -X utf8 scripts\run_data_when_cheap.py
停：建空文件 voice_train\data\run_cheap.stop（等的时候 30 秒内停；一批跑到一半会跑完这批再停）。
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train_keys  # noqa: E402,F401
import relay_pin  # noqa: E402

VT = os.path.dirname(HERE)
LOG = os.path.join(VT, "data", "run_cheap.log")
STOP = os.path.join(VT, "data", "run_cheap.stop")  # 建一个这个名字的空文件，等的时候下一轮就停（一批跑到一半不打断）
H_DONE = os.path.join(VT, "data", "stage_h_plan", "full.jsonl")
K_DONE = os.path.join(VT, "data", "stage_k_plan", "novel.jsonl")
H_TOTAL, K_TOTAL = 4640, 2668
BUDGET = 30.0
WAIT = 900


def say(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def done(path):
    return sum(1 for _ in open(path, encoding="utf-8")) if os.path.exists(path) else 0


def batch(args):
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", *args], cwd=VT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    rmb = float((re.search(r"这批估 ([\d.]+) 元", out) or [0, 0])[1])
    bad = sum(int(x) for x in re.findall(r"没出好'?[ ：:/]*(\d+)", out))  # H：“没出好 3”；K：“'卡没出好': 3”
    good = sum(int(x) for x in re.findall(r"好 (\d+) /", out)) or int((re.search(r"'好': (\d+)", out) or [0, 0])[1])
    return p.returncode, rmb, good, bad, out[-600:]


def main():
    spent = 0.0
    say(f"开始等 bb-api：H 已做 {done(H_DONE)}/{H_TOTAL}，K 已做 {done(K_DONE)}/{K_TOTAL}，花钱上限 {BUDGET} 元")
    while True:
        if os.path.exists(STOP):
            os.remove(STOP)
            say("看到停止文件 run_cheap.stop，停下")
            return
        h, k = done(H_DONE), done(K_DONE)
        if h >= H_TOTAL and k >= K_TOTAL:
            say(f"都做完了：H {h}、K {k}；这次一共估 {spent:.2f} 元")
            return
        if spent >= BUDGET:
            say(f"估的钱到了上限（{spent:.2f} ≥ {BUDGET} 元），停下来等兄长看；H {h}/{H_TOTAL}、K {k}/{K_TOTAL}")
            return
        ok, msg = relay_pin.probe("bb-api")
        if not ok:
            say(f"bb-api 还不通（{msg}），{WAIT // 60} 分钟后再试")
            for _ in range(WAIT // 30):  # 等的时候每 30 秒看一眼停止文件
                if os.path.exists(STOP):
                    break
                time.sleep(30)
            continue
        if h < H_TOTAL:
            args, what = [os.path.join(HERE, "prepare_h_plan.py"), "full", "--limit", "300", "--pin", "bb-api"], "H"
        else:
            args, what = [os.path.join(HERE, "prepare_k_plan.py"), "run", "--limit", "200", "--pin", "bb-api"], "K"
        rc, rmb, good, bad, tail = batch(args)
        spent += rmb
        say(f"{what} 一批：返回 {rc}，好 {good}、没出好 {bad}，估 {rmb:.2f} 元（累计 {spent:.2f}）；H {done(H_DONE)}/{H_TOTAL}、K {done(K_DONE)}/{K_TOTAL}")
        if rc != 0:
            say(f"脚本出错了，停下：{tail}")
            return
        if bad > 0.3 * max(1, good + bad):
            say(f"这批没出好的太多（bb-api 不稳），{WAIT // 60} 分钟后再试")
            time.sleep(WAIT)


if __name__ == "__main__":
    main()
