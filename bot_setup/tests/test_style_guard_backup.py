"""kaju_style 1.21.0：核对的后备（2026-11-13）。

核对先问 guard_provider_id（gemini_flash38 = aigocode 3.8-flash，抓编的事准），它超时 / 出错就把剩下的时间给
guard_backup_provider_id（gemini = hardysapi，快）；没填后备照旧只问一个。

    <python>\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_guard_backup.py
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.star import Context  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

OK = '{"bad": false, "what": ""}'
BAD = '{"bad": true, "what": "加了草稿没有的事实"}'


class _Prov:
    def __init__(self, pid):
        self.provider_config = {"id": pid}


class _Resp:
    def __init__(self, text):
        self.completion_text, self.role = text, "assistant"


class GuardBackupTests(unittest.IsolatedAsyncioTestCase):
    def make(self, behave, cfg=None):
        """behave: provider id → 回答文字 / 异常 / ("sleep", 秒)。主模型是 gemini、后备 gemini_flash38（和线上一样）。"""
        ctx = Context({"agent_runner": {"config": {"model": {"provider_id": "gemini",
                                                             "fallback_provider_ids": ["gemini_flash38"]}}}})
        ctx.providers = {p: _Prov(p) for p in ("gemini", "gemini_flash38")}
        self.calls = []

        async def llm(chat_provider_id, prompt, system_prompt=""):
            self.calls.append(chat_provider_id)
            b = behave[chat_provider_id]
            if isinstance(b, tuple):
                await asyncio.sleep(b[1])
                return _Resp(OK)
            if isinstance(b, Exception):
                raise b
            return _Resp(b)
        ctx.llm_generate = llm
        return KajuStyle(ctx, {"rewrite": {"enable": True, "guard_provider_id": "gemini_flash38",
                                           "guard_backup_provider_id": "gemini", "guard_timeout": 10, **(cfg or {})}})

    async def test_first_answers(self):
        s = self.make({"gemini_flash38": BAD, "gemini": OK})
        bad, why, _ = await s._guard("中午好", "午饭要好好吃哦", "佳树吃过午饭了", "兄长大人")
        self.assertTrue(bad)
        self.assertEqual(self.calls, ["gemini_flash38"])

    async def test_first_errors_backup_answers(self):
        s = self.make({"gemini_flash38": RuntimeError("502"), "gemini": BAD})
        bad, _, _ = await s._guard("中午好", "午饭要好好吃哦", "佳树吃过午饭了", "兄长大人")
        self.assertTrue(bad)
        self.assertEqual(self.calls, ["gemini_flash38", "gemini"])

    async def test_first_slow_backup_gets_rest(self):
        # 总时限 20 秒、第一个最多 8 秒（max(8, 20×0.4)）：aigocode 卡住 → 8 秒后换 hardysapi
        s = self.make({"gemini_flash38": ("sleep", 60), "gemini": OK}, {"guard_timeout": 20, "guard_first_share": 0.4})
        t = time.time()
        bad, _, _ = await s._guard("中午好", "d", "n", "兄长大人")
        self.assertFalse(bad)
        self.assertEqual(self.calls, ["gemini_flash38", "gemini"])
        self.assertLess(time.time() - t, 12)

    async def test_no_backup_single(self):
        s = self.make({"gemini_flash38": RuntimeError("502"), "gemini": OK}, {"guard_backup_provider_id": ""})
        with self.assertRaises(RuntimeError):
            await s._guard("中午好", "d", "n", "兄长大人")
        self.assertEqual(self.calls, ["gemini_flash38"])

    async def test_backup_same_as_first(self):
        s = self.make({"gemini_flash38": OK, "gemini": OK}, {"guard_provider_id": "gemini"})
        await s._guard("中午好", "d", "n", "兄长大人")
        self.assertEqual(self.calls, ["gemini"])  # 主模型自己的后备链没触发（它答了）


if __name__ == "__main__":
    unittest.main()
