"""Offline tests for kaju_core/voice/card.py（第四版要点卡留下的几个小工具；第一、二版卡 11-20 删了）。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_card.py
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kaju_core", "voice"))  # card.py 现在在 kaju_core\voice
import card  # noqa: E402

failures = []


def expect(label, got, want):
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


expect("fix_formal", card.fix_formal("佳树陪着您呢", "佳树陪着兄长大人", "兄长大人"), "佳树陪着兄长大人呢")
expect("fix_formal group", card.fix_formal("学姐，您说的对", "说得对", "哆啦a梦学姐"), "学姐，哆啦a梦学姐说的对")
expect("fix_formal draft had it", card.fix_formal("您好", "您好呀", "兄长大人"), "您好")
# 写手自己冒出繁体（2026-11-09 "今天也要上課"）：这一遍不算写好；原稿里本来就有的（作品名）不算
expect("trad chars", card.trad_chars("今天也要上課", "今天还有课要上"), "課")
expect("trad: simplified words ok", card.trad_chars("晚饭吃快餐了吗，著名的面馆"), "")
expect("sane_v4 leak", card.sane_v4("要说到的：在\n佳树在哦", "要说到的：在"), False)
expect("sane_v4 ok", card.sane_v4("佳树在哦", "要说到的：在"), True)
expect("sane_v4 trad", card.sane_v4("今天也要上課", "要说到的：上课"), False)
expect("sane_v4 trad in card", card.sane_v4("佳树看过入間人間的书", "要说到的：入間人間的书"), True)
expect("loops", (card.loops("好呀好呀好呀好呀好呀好呀好呀好呀好呀"), card.loops("佳树今天去学校了")), (True, False))

print("ALL OK" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
