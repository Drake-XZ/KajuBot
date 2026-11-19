"""每个有后台循环的插件外壳都要自己写 terminate（2026-11-15）。

AstrBot 热重载时只在 "terminate" in 插件类.__dict__ 时才调它（star_manager._terminate_plugin），继承来的不算：
外壳不写，旧实例的后台循环（读书、整理、心声……）就一直跑，和新实例各干一遍。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_terminate.py
"""

import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.star import Context  # noqa: E402

SHELLS = {"kaju_dm": "KajuDm", "kaju_heart": "KajuHeart", "kaju_learn": "KajuLearn", "kaju_life": "KajuLife",
          "kaju_style": "KajuStyle", "memory_weight": "MemoryWeight", "kaju_basics": "KajuBasics",
          "qzone_post": None, "address_book": None}
bad = []
for mod, cls_name in SHELLS.items():
    m = importlib.import_module(f"{mod}.main")
    cls = getattr(m, cls_name) if cls_name else next(
        v for v in vars(m).values() if isinstance(v, type) and v.__module__ == m.__name__ and hasattr(v, "terminate"))
    if "terminate" not in cls.__dict__:
        bad.append(f"{mod}.{cls.__name__}")
if bad:
    print("FAIL 外壳没自己写 terminate（热重载停不掉旧循环）:", bad)
    sys.exit(1)


async def learn_loops_stop():
    """kaju_learn：调外壳的 terminate 真能把读书 / 整理两个循环停掉。"""
    from kaju_learn.main import KajuLearn
    k = KajuLearn(Context(), {"enable": True})
    tasks = [t for t in (k._task, k._rtask) if t]
    assert tasks, "测试里循环没起来"
    await KajuLearn.__dict__["terminate"](k)
    await asyncio.sleep(0)
    assert all(t.cancelled() or t.done() for t in tasks), "terminate 之后循环还在跑"

asyncio.run(learn_loops_stop())
print("ALL OK")
