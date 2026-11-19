"""kaju_core.voice.rewrite.tidy_ctx：写手看到的上下文去掉系统文字和空行（2026-11-09）。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_tidy_ctx.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 源码里的 kaju_core
sys.stdout.reconfigure(encoding="utf-8")

from kaju_core.voice import rewrite  # noqa: E402

fails = 0


def expect(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"\n  got  {got!r}\n  want {want!r}")


# 第六批标注里真实出现过的
lines = [
    "佳树：[CronJob] 每晚写说说记录今天: 以温水佳树的身份，调用 post_qzone 发一条说说",
    "兄长大人：Output your last task result below.",
    "佳树：",
    "佳树：哆啦a梦学姐这句会赢的 / 是咒术里五条悟那句吗 / ",
    "兄长大人：[发言人：晴川，QQ 111111111] 我的天哪，这个讲的是什么<system_reminder>Current datetime: 2026-11-07 12:11 (CST), Weekday: Satur",
    "女王大人：[发言人：dy_demo，抖音 2067501187073086] 你记得我吗",
    "兄长大人：[系统记录] 你刚才自己刷B站看到《…》，挺想跟兄长大人说",
    "佳树：成功了就能写进论文 /  / 有空再慢慢补啦 / ",
    "兄长大人：小佳树晚上好呀",
]
expect("tidy", rewrite.tidy_ctx(lines), [
    "佳树：哆啦a梦学姐这句会赢的 / 是咒术里五条悟那句吗",
    "兄长大人：我的天哪，这个讲的是什么",
    "女王大人：你记得我吗",
    "佳树：成功了就能写进论文 / 有空再慢慢补啦",
    "兄长大人：小佳树晚上好呀",
])
expect("closed reminder", rewrite.tidy_ctx(["兄长大人：在吗<system_reminder>x</system_reminder>"]), ["兄长大人：在吗"])
expect("plain kept", rewrite.tidy_ctx(["（没有前文）", "兄长大人：好"]), ["（没有前文）", "兄长大人：好"])
expect("empty", rewrite.tidy_ctx([]), [])

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
