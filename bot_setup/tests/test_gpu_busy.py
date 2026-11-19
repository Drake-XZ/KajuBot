"""显卡在训练时群聊先不回（kaju_core.gpu_busy，2026-11-13）。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_gpu_busy.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from kaju_core import gpu_busy  # noqa: E402


class GpuBusyTests(unittest.TestCase):
    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "training.json")

    def test_mark_busy_clear(self):
        self.assertEqual(gpu_busy.busy(self.p), "")  # 没有标记
        gpu_busy.mark("训练第 1 轮写手", path=self.p)
        self.assertEqual(gpu_busy.busy(self.p), "训练第 1 轮写手")
        gpu_busy.clear(self.p)
        self.assertEqual(gpu_busy.busy(self.p), "")
        gpu_busy.clear(self.p)  # 删两遍不报错

    def test_stale_by_age(self):
        gpu_busy.mark("训练", path=self.p)
        self.assertEqual(gpu_busy.busy(self.p, now=time.time() + gpu_busy.MAX_HOURS * 3600 + 60), "")

    def test_stale_by_dead_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        gpu_busy.mark("训练", pid=p.pid, path=self.p)
        self.assertEqual(gpu_busy.busy(self.p), "")  # 写标记的进程不在了：当没有

    def test_broken_file(self):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write("{坏的")
        self.assertEqual(gpu_busy.busy(self.p), "")
        with open(self.p, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "since": time.time()}, f)
        self.assertEqual(gpu_busy.busy(self.p), "训练")  # 没写 what

    def test_manual_pause(self):
        """控制台手动暂停群聊：不看进程、不过期；quiet_group = 训练中或手动暂停（2026-11-17）。"""
        pp = self.p + ".pause"
        self.assertEqual(gpu_busy.paused(pp), "")
        self.assertEqual(gpu_busy.quiet_group(self.p, pp), "")
        gpu_busy.pause("跑训练", path=pp)
        self.assertEqual(gpu_busy.paused(pp), "跑训练")
        self.assertEqual(gpu_busy.quiet_group(self.p, pp), "跑训练")
        with open(pp, "w", encoding="utf-8") as f:
            json.dump({"since": time.time() - 30 * 86400, "what": "很久以前"}, f)
        self.assertEqual(gpu_busy.paused(pp), "很久以前")  # 不过期
        with open(pp, "w", encoding="utf-8") as f:
            f.write("{坏")
        self.assertTrue(gpu_busy.paused(pp))  # 读不出来也算暂停
        gpu_busy.resume(pp)
        gpu_busy.resume(pp)  # 删两遍不报错
        self.assertEqual(gpu_busy.quiet_group(self.p, pp), "")
        gpu_busy.mark("训练 H 层", path=self.p)
        self.assertEqual(gpu_busy.quiet_group(self.p, pp), "训练 H 层")  # 训练标记也算

    def test_hold(self):
        """训练整段都挂着，出来就删；中间会续上 since，超过 6 小时的长训练也不失效（2026-11-16）。"""
        old = gpu_busy.hold.REFRESH
        gpu_busy.hold.REFRESH = 0.05
        try:
            with gpu_busy.hold("训练 H 层", path=self.p):
                self.assertEqual(gpu_busy.busy(self.p), "训练 H 层")
                since0 = json.load(open(self.p, encoding="utf-8"))["since"]
                time.sleep(0.3)
                since1 = json.load(open(self.p, encoding="utf-8"))["since"]
                self.assertGreater(since1, since0)  # 续上了
            self.assertEqual(gpu_busy.busy(self.p), "")  # 出来删掉
            with self.assertRaises(RuntimeError):  # 训练出错也删
                with gpu_busy.hold("训练", path=self.p):
                    raise RuntimeError("爆显存")
            self.assertEqual(gpu_busy.busy(self.p), "")
        finally:
            gpu_busy.hold.REFRESH = old


if __name__ == "__main__":
    unittest.main()
