"""kaju_style 1.15.0：照卡写被核对拦下（或写出来不像回复）就拿同一张卡再写一次；核对超时、回晚了不重写。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_retry.py
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]  # HERE.parent：源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

DRAFT = "兄长大人晚安呀 / 佳树也爱兄长大人"
CARD = "场合：私聊\n对象：兄长大人\n情绪：开心\n态度：撒娇\n要点：佳树回晚安；佳树也爱兄长\n问：无"


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def make(self, writes, guards, cfg=None):
        # writer_only 关着：查的是“写手两遍都不行就发原稿”那条退路（11-18 删第一版卡前这是默认）
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "writer_only": False, **(cfg or {})}})
        self.writes, self.guards, self.wcalls, self.gcalls = list(writes), list(guards), [], []

        async def extract(ctx, draft, kind, title):
            return CARD

        async def local_chat(system, user):
            self.wcalls.append(user)
            w = self.writes.pop(0)
            if isinstance(w, Exception):
                raise w
            return w

        async def guard(said, draft, new, title="", ctx=None):
            self.gcalls.append(new)
            g = self.guards.pop(0)
            if isinstance(g, Exception):
                raise g
            return g

        style._extract_card, style._local_chat, style._guard = extract, local_chat, guard
        return style

    async def reply(self, style, arrived=None):
        ev = AstrMessageEvent(text="晚安小佳树，我爱你")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：晚安小佳树，我爱你"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        if arrived:
            ev.set_extra("_kaju_quote_t", arrived)
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(ev, resp)
        return resp.completion_text

    async def test_second_try_passes(self):
        s = self.make(["兄长大人不要凶佳树嘛", "晚安兄长大人，佳树也爱兄长大人"],
                      [(True, "加了不要凶", True), (False, "", True)])
        out = await self.reply(s)
        self.assertEqual(out, "晚安兄长大人，佳树也爱兄长大人")
        self.assertEqual((len(self.wcalls), len(self.gcalls)), (2, 2))
        self.assertEqual(self.wcalls[0], self.wcalls[1])  # 同一张卡、同一份提示再写一遍

    async def test_both_rejected_keeps_draft(self):
        s = self.make(["编了一件事", "又编了一件事"], [(True, "编事", True), (True, "编事", True)])
        self.assertEqual(await self.reply(s), DRAFT)
        self.assertEqual(len(self.wcalls), 2)

    async def test_guard_error_no_retry(self):
        s = self.make(["晚安兄长大人", "不该写到这一遍"], [TimeoutError()])
        self.assertEqual(await self.reply(s), DRAFT)
        self.assertEqual(len(self.wcalls), 1)

    async def test_late_no_retry(self):
        s = self.make(["编了一件事", "不该写到这一遍"], [(True, "编事", True)])
        self.assertEqual(await self.reply(s, arrived=time.time() - 26), DRAFT)  # 第一遍前没超时的话这里会跳过整个重说
        self.assertEqual(len(self.wcalls), 0)
        s = self.make(["编了一件事", "不该写到这一遍"], [(True, "编事", True)])
        out = await self.reply(s, arrived=time.time() - 20)
        self.assertEqual(out, DRAFT)

    async def test_unusable_first_then_ok(self):
        s = self.make(["", "晚安兄长大人，佳树也爱兄长大人"], [(False, "", True)])
        self.assertEqual(await self.reply(s), "晚安兄长大人，佳树也爱兄长大人")
        self.assertEqual((len(self.wcalls), len(self.gcalls)), (2, 1))

    async def test_retry_zero(self):
        s = self.make(["编了一件事", "不该写到这一遍"], [(True, "编事", True)], cfg={"retry": 0})
        self.assertEqual(await self.reply(s), DRAFT)
        self.assertEqual(len(self.wcalls), 1)

    async def test_first_ok_no_extra_calls(self):
        s = self.make(["晚安兄长大人，佳树也爱兄长大人"], [(False, "", True)])
        self.assertEqual(await self.reply(s), "晚安兄长大人，佳树也爱兄长大人")
        self.assertEqual((len(self.wcalls), len(self.gcalls)), (1, 1))

    async def test_polish_retries(self):
        s = self.make(["好的兄长大人，佳树现在就去刷", "兄长大人，佳树刷到一只五条悟配琵琶曲的视频"],
                      [(True, "开头答应去刷", True), (False, "", True)])
        out = await s.polish("兄长大人！佳树刷到一条五条悟配琵琶曲", ["兄长大人：在吗"], said="刷到视频", split=False)
        self.assertEqual(out, "兄长大人，佳树刷到一只五条悟配琵琶曲的视频")
        self.assertEqual(len(self.wcalls), 2)

    async def test_polish_both_rejected(self):
        s = self.make(["编了", "又编了"], [(True, "x", True), (True, "x", True)])
        draft = "兄长大人！佳树刷到一条五条悟配琵琶曲"
        self.assertEqual(await s.polish(draft, [], said="", split=False), draft)


if __name__ == "__main__":
    unittest.main()
