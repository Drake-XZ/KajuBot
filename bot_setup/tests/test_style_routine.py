"""kaju_style：发之前查套路（kaju_core\\voice\\routine.py）——只记不拦 / 撞了再写一遍、挑撞得少的。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_routine.py
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
from kaju_core.voice import routine  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

DRAFT = "兄长大人晚安呀 / 佳树也爱兄长大人"
CARD = "场合：私聊\n对象：兄长大人\n情绪：开心\n态度：撒娇\n要点：佳树回晚安；佳树也爱兄长\n问：无"
OLD = "今天的水饺皮好厚呀，佳树只吃了三个就饱了"
SAME = "兄长大人，今天的水饺皮好厚呀，佳树只吃了三个就饱了呢"
FRESH = "晚安兄长大人，佳树也最喜欢兄长大人了"


class RoutineRules(unittest.TestCase):
    def test_same_ignores_titles_and_particles(self):
        self.assertTrue(routine.check(SAME, [OLD])[0].startswith("same:"))
        self.assertEqual(routine.check(FRESH, [OLD]), [])

    def test_short_lines_never_match(self):
        self.assertEqual(routine.check("晚安兄长大人", ["兄长大人晚安", "晚安兄长大人"]), [])

    def test_one_line_of_a_long_reply(self):
        new = "佳树刚刚去看了一下\n今天的水饺皮好厚呀，佳树只吃了三个就饱了\n兄长大人那边呢"
        self.assertTrue(any(h.startswith("same:") for h in routine.check(new, [OLD])))

    def test_opener_three_in_a_row(self):
        a, b = "那佳树先去把作业写完再来", "那佳树先去洗个澡，回来再陪兄长大人聊"
        hits = routine.check("那佳树先去睡一会儿好了", [a, b])
        self.assertEqual([h.split(":")[0] for h in hits], ["opener"])
        self.assertEqual(routine.check("佳树去睡一会儿", [a, b]), [])
        self.assertEqual(routine.check("那佳树先去睡一会儿好了", [b]), [])  # 只连着两次不算

    def test_titles_alone_are_not_an_opener(self):
        old = ["兄长大人，佳树回来啦", "兄长大人，佳树吃过饭了"]
        self.assertEqual(routine.check("兄长大人，佳树想问一件事", old), [])

    def test_soft_needs_two(self):
        self.assertEqual(routine.check("这不是佳树偷懒，而是真的太难了", []), [])
        hits = routine.check("总之这不是佳树偷懒，而是题目本质上就超纲了", [])
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].startswith("soft:"))

    def test_load_sent(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "2026-11-10.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"umo": "a", "final": "第一句 &&happy&&"}, ensure_ascii=False) + "\n")
            f.write("坏行\n")
            f.write(json.dumps({"umo": "a", "final": "第二句"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"umo": "", "final": "没有会话"}, ensure_ascii=False) + "\n")
        self.assertEqual(routine.load_sent(d), {"a": ["第一句", "第二句"]})


class RoutineLive(unittest.IsolatedAsyncioTestCase):
    def make(self, writes, guards=None, cfg=None, sent=(OLD,)):
        style = KajuStyle(Context(), {"rewrite": {"enable": True, **(cfg or {})}})
        self.writes, self.wcalls, self.gcalls = list(writes), [], []
        guards = list(guards or [(False, "", True)] * len(writes))

        async def extract(ctx, draft, kind, title):
            return CARD

        async def local_chat(system, user):
            self.wcalls.append(user)
            return self.writes.pop(0)

        async def guard(said, draft, new, title="", ctx=None):
            self.gcalls.append(new)
            return guards.pop(0)

        style._extract_card, style._local_chat, style._guard = extract, local_chat, guard
        self.ev = AstrMessageEvent(text="晚安小佳树，我爱你")
        mind = getattr(style, "mind", style)
        q = mind._sent_of(self.ev.unified_msg_origin)
        q.clear()  # 别的用例写下的重说记录会被读回来，先清掉
        q.extend(sent)
        return style

    async def reply(self, style):
        self.ev.set_extra("_ks_rw_ctx", ["兄长大人：晚安小佳树，我爱你"])
        self.ev.set_extra("_ks_rw_title", "兄长大人")
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(self.ev, resp)
        return resp.completion_text

    async def test_log_mode_sends_first_and_writes_once(self):
        s = self.make([SAME, FRESH])
        self.assertEqual(await self.reply(s), SAME)  # 默认只记不拦
        self.assertEqual(len(self.wcalls), 1)

    async def test_on_mode_rewrites_once_and_takes_cleaner(self):
        s = self.make([SAME, FRESH], cfg={"routine": "on"})
        self.assertEqual(await self.reply(s), FRESH)
        self.assertEqual((len(self.wcalls), len(self.gcalls)), (2, 2))
        self.assertEqual(self.wcalls[0], self.wcalls[1])  # 同一张卡、同一份提示，不加"换个说法"

    async def test_on_mode_second_fails_guard_keeps_first_not_draft(self):
        s = self.make([SAME, "编了一件事"], guards=[(False, "", True), (True, "编事", True)], cfg={"routine": "on"})
        self.assertEqual(await self.reply(s), SAME)

    async def test_on_mode_both_hit_keeps_first(self):
        s = self.make([SAME, SAME + "哦"], cfg={"routine": "on"})
        self.assertEqual(await self.reply(s), SAME)
        self.assertEqual(len(self.wcalls), 2)  # 最多再写一次

    async def test_on_mode_no_hit_no_extra_call(self):
        s = self.make([FRESH, "不该写到这一遍"], cfg={"routine": "on"})
        self.assertEqual(await self.reply(s), FRESH)
        self.assertEqual(len(self.wcalls), 1)

    async def test_off_mode(self):
        s = self.make([SAME], cfg={"routine": "off"})
        self.assertEqual(await self.reply(s), SAME)

    async def test_guard_retry_then_routine_has_no_tries_left(self):
        s = self.make(["编了一件事", SAME], guards=[(True, "编事", True), (False, "", True)], cfg={"routine": "on"})
        self.assertEqual(await self.reply(s), SAME)  # 重写的机会已经用在核对上了，照发
        self.assertEqual(len(self.wcalls), 2)


if __name__ == "__main__":
    unittest.main()
