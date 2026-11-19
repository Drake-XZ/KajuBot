r"""盯着“中转没钱了”（2026-11-17 兄长：“上游哪家弹出来没钱了，就叫我”）。

从现在的结尾开始跟几个日志（造数据的两个 log、AstrBot 的 stdout.log），只看报错行里带“没钱”字眼的
（余额 / 额度不足 / 欠费 / 充值 / insufficient / quota / balance / credit / 402 / Payment Required / 预扣费 / billing），
认出是哪家（hardysapi / bb-api / daitu / aigocode / aethergate / supergpt / deepseek），每家 30 分钟最多说一次，打一行到标准输出（给 Claude 的 Monitor 当事件）。
普通的 502 / 503 / 超时不算（那是中转不稳，不是没钱）。omni 从 11-17 起把中转回的内容接在报错后面，“余额不足”这种字才看得到。
用法：python -I -X utf8 scripts\watch_money.py 日志1 日志2 ...
"""
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
MONEY = re.compile(r"余额|额度不足|额度已用|欠费|请充值|充值后|insufficient|quota|balance|[Cc]redit|Payment Required|HTTP Error 402|预扣费|billing|arrear", re.I)
ERR = re.compile(r"Error|错误|报错|没答上来|失败|冷却|没回字|exception", re.I)
RELAYS = ["hardysapi", "bb-api", "daitu", "aigocode", "aethergate", "supergpt", "deepseek", "siliconflow"]
QUIET_S = 1800


def relay_of(line):
    low = line.lower()
    return next((r for r in RELAYS if r in low), "不知道哪家")


def main(paths):
    pos = {p: (os.path.getsize(p) if os.path.exists(p) else 0) for p in paths}
    last = {}
    print(f"开始盯：{', '.join(os.path.basename(p) for p in paths)}")
    while True:
        for p in paths:
            if not os.path.exists(p):
                continue
            size = os.path.getsize(p)
            if size < pos[p]:  # 日志被换了
                pos[p] = 0
            if size == pos[p]:
                continue
            with open(p, "rb") as f:
                f.seek(pos[p])
                chunk = f.read(size - pos[p])
            pos[p] = size
            for raw in chunk.decode("utf-8", "replace").splitlines():
                line = re.sub(r"\x1b\[[0-9;]*m", "", raw)
                if not (ERR.search(line) and MONEY.search(line)):
                    continue
                who = relay_of(line)
                now = time.time()
                if now - last.get(who, 0) < QUIET_S:
                    continue
                last[who] = now
                m = MONEY.search(line)
                snip = line[max(0, m.start() - 80): m.end() + 80].strip()
                print(f"【中转没钱了？】{who}（{os.path.basename(p)}）：{snip}")
        time.sleep(3)


if __name__ == "__main__":
    main(sys.argv[1:])
