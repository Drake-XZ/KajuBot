"""kaju_style 1.22.0：核对几遍都没过时不再干脆不说话（2026-11-15 兄长：一直不说话会以为哪里坏了）。

- 先改错：核对用的模型只改被拦的那一处（“帮他”→“帮她”），改小了才算，再核对一次，过了就发它
- 改错没成（改不了 / 改多了 / 还没过）：guard_fail=busy 时照卡说一句“这会儿在忙（日程里在做的事），等下再好好回”
- guard_fail=silent：只改错，不行还是不说；send_writer 照旧

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_guard_fail.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core import parts  # noqa: E402
from kaju_core.senses import omni  # noqa: E402
from kaju_core.voice import rewrite  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

DRAFT = "佳树读到上卷第2段啦，哥哥带妹妹回房间帮她补日记，最后两人房间搬到一起了～"
GEM = json.dumps({"局面": "兄长大人问佳树小说读到哪了，轮到佳树回。",
                  "要说到的": ["佳树读到上卷第2段", "哥哥带妹妹回房间帮她补日记", "最后两人房间搬到一起"]},
                 ensure_ascii=False)
BAD_ONCE = "佳树读到上卷第2段，哥哥带妹妹回房间帮他补日记，最后两人房间搬到一起"
FIXED = "佳树读到上卷第2段，哥哥带妹妹回房间帮她补日记，最后两人房间搬到一起"
V4 = {"enable": True, "card_format": "v4", "card_model": "kaju-writer-p4-8b-k", "retry": 1, "recard_after": 0,
      "guard_provider_id": "gemini"}


class _Prov:
    def __init__(self, pid):
        self.provider_config = {"id": pid}


class PureTests(unittest.TestCase):
    def test_small_edit(self):
        self.assertTrue(rewrite.small_edit(BAD_ONCE, FIXED))
        self.assertFalse(rewrite.small_edit(BAD_ONCE, DRAFT + "兄长大人今天累不累呀，要早点休息哦"))
        self.assertFalse(rewrite.small_edit(BAD_ONCE, ""))

    def test_repair_prompt(self):
        p = rewrite.repair_prompt("小佳树读到哪了呀？", DRAFT, BAD_ONCE, "帮她改成帮他", "兄长大人")
        for s in ("回给「兄长大人」", "对方刚说：小佳树读到哪了呀？", "草稿（意思以它为准）：\n" + DRAFT,
                  "佳树要发的话：\n" + BAD_ONCE, "核对说的问题：帮她改成帮他"):
            self.assertIn(s, p)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def make(self, writes, guards, repair_out=None, cfg=None, doing=""):
        ctx = Context({"agent_runner": {"config": {"model": {"provider_id": "gemini", "fallback_provider_ids": []}}}})
        ctx.providers = {"gemini": _Prov("gemini")}
        self.repair_calls = []

        async def llm(chat_provider_id, prompt, system_prompt=""):
            self.repair_calls.append(prompt)
            if isinstance(repair_out, Exception):
                raise repair_out

            class R:
                completion_text, role = repair_out or "", "assistant"
            return R()
        ctx.llm_generate = llm
        style = KajuStyle(ctx, {"rewrite": {**V4, **(cfg or {})}})
        self.writes, self.guards, self.bodies = list(writes), list(guards), []

        async def fake_text(system, user, timeout=20, thinking="low"):
            return GEM, 1
        self.real_text, omni.text = omni.text, fake_text

        async def local_chat(system, user):
            self.bodies.append(user)
            return self.writes.pop(0)

        async def guard(said, draft, new, title="", ctx=None):
            return self.guards.pop(0)

        style._local_chat, style._guard = local_chat, guard
        style._mood_line = lambda: "心情：开心6 精神5 紧绷1 亲近5"

        class Life:
            def doing_now(self):
                return doing
        self.life = Life()
        parts.register("kaju_life_test", self.life)
        return style

    def tearDown(self):
        omni.text = self.real_text
        parts.unregister("kaju_life_test", self.life)

    async def reply(self, style, group="", called=None):
        ev = AstrMessageEvent(text="小佳树读到哪了呀？", group=group)
        if called:
            ev.set_extra("_kaju_called", called)
        ev.set_extra("_ks_rw_ctx", ["兄长大人：小佳树读到哪了呀？"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(ev, resp)
        return ev, resp.completion_text

    BAD = (True, "「帮她」改成「帮他」性别错了", True)
    OK = (False, "", True)

    async def test_repair_fixes_one_word(self):
        s = self.make([BAD_ONCE, BAD_ONCE], [self.BAD, self.BAD, self.OK], repair_out=FIXED)
        ev, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), FIXED)
        self.assertIn("核对说的问题：「帮她」改成「帮他」性别错了", self.repair_calls[0])
        self.assertFalse(ev.get_extra("kaju_style_busy"))

    async def test_repair_rewrote_too_much_then_busy(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "兄长大人，佳树在上课呢，等下课再好好跟兄长大人说"],
                      [self.BAD, self.BAD], repair_out=DRAFT + "兄长大人今天累不累呀，要早点休息哦", doing="第三节数学课")
        guards_before = len(self.guards)
        ev, out = await self.reply(s)
        self.assertEqual(len(self.guards), guards_before - 2)  # 改多了的不再拿去核对
        self.assertEqual(out.replace("\n", ""), "兄长大人，佳树在上课呢，等下课再好好跟兄长大人说")
        self.assertTrue(ev.get_extra("kaju_style_busy"))
        self.assertIn("佳树这会儿在忙（第三节数学课）", self.bodies[-1])  # 在忙什么取日程
        self.assertIn("佳树等一下再好好回兄长大人刚才说的", self.bodies[-1])

    async def test_repair_still_bad_then_busy_without_schedule(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "佳树现在有点忙，等一下再回兄长大人哦"],
                      [self.BAD, self.BAD, (True, "还是不对", True)], repair_out=FIXED)
        ev, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "佳树现在有点忙，等一下再回兄长大人哦")
        self.assertIn("佳树这会儿有点忙", self.bodies[-1])

    async def test_cannot_repair_then_busy(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "佳树有点忙，等下回兄长大人"], [self.BAD, self.BAD], repair_out="[无法修改]")
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "佳树有点忙，等下回兄长大人")

    async def test_unchanged_repair_skips_recheck(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "佳树有点忙，等下回兄长大人"], [self.BAD, self.BAD], repair_out=BAD_ONCE)
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "佳树有点忙，等下回兄长大人")  # 原样返回 = 没改成，不再白核对一次

    async def test_group_name_or_chime_in_stays_silent(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "不该写到这一遍"], [self.BAD, self.BAD], repair_out="[无法修改]")
        ev, out = await self.reply(s, group="222222222")
        self.assertEqual(out, "")  # 群里只提到名字 / 自己插话：全被拦还是不说
        self.assertTrue(ev.is_stopped())
        self.assertEqual(len(self.bodies), 2)

    async def test_group_at_or_poke_says_busy(self):
        for how in ("at", "poke"):
            s = self.make([BAD_ONCE, BAD_ONCE, "佳树有点忙，等下回"], [self.BAD, self.BAD], repair_out="[无法修改]")
            _, out = await self.reply(s, group="222222222", called=how)
            self.assertEqual(out.replace(chr(10), ""), "佳树有点忙，等下回", how)
            self.tearDown()

    async def test_group_name_mention_still_repairs(self):
        s = self.make([BAD_ONCE, BAD_ONCE], [self.BAD, self.BAD, self.OK], repair_out=FIXED)
        _, out = await self.reply(s, group="222222222")
        self.assertEqual(out.replace(chr(10), ""), FIXED)  # 改错不分场合，改好了照发

    async def test_silent_mode_repairs_but_never_busy(self):
        s = self.make([BAD_ONCE, BAD_ONCE], [self.BAD, self.BAD], repair_out="[无法修改]", cfg={"guard_fail": "silent"})
        ev, out = await self.reply(s)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())
        self.assertEqual(len(self.repair_calls), 1)

    async def test_busy_writer_fails_says_nothing(self):
        s = self.make([BAD_ONCE, BAD_ONCE, ""], [self.BAD, self.BAD], repair_out="[无法修改]")
        ev, out = await self.reply(s)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_repair_error_then_busy(self):
        s = self.make([BAD_ONCE, BAD_ONCE, "佳树等一下回兄长大人"], [self.BAD, self.BAD], repair_out=RuntimeError("502"))
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "佳树等一下回兄长大人")


if __name__ == "__main__":
    unittest.main()
