"""Guard ambiguous mentions of the brother in replies to other people."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]  # HERE.parent：源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context
from kaju_style.main import KajuStyle
from kaju_core.voice import rewrite


class TitleGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_guard_without_boolean_verdict_is_failure(self):
        self.assertTrue(rewrite.guard_bad('{}')[0])
        self.assertTrue(rewrite.guard_bad('{"bad": null}')[0])
        self.assertTrue(rewrite.guard_bad('{"bad": "false"}')[0])
        self.assertFalse(rewrite.guard_bad('{"bad": false}')[0])

    async def run_reply(self, text, guard_mode, draft="佳树一直很努力地学哦"):
        # writer_only 关着：查“叫错人 / 核对不过就发原稿”
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "guard": guard_mode != "off", "writer_only": False}})
        calls = []

        async def plan_of(ctx, original, kind, title):
            return {"局面": "学长夸她聪明", "要表达的": ["反应：被夸开心"]}

        async def write(ctx, plan, kind, title, ref=""):
            return text

        async def guard(said, original, new, title, ctx):
            calls.append((said, title, ctx))
            if guard_mode == "error":
                raise TimeoutError()
            return (guard_mode == "reject", "称呼错误", True)

        style._plan_from_draft, style._write, style._guard = plan_of, write, guard
        event = AstrMessageEvent(group="123", text="挺聪明的还")
        event.set_extra("_ks_rw_ctx", ["学长：挺聪明的还", "学长：xzz教得好"])
        event.set_extra("_ks_rw_title", "学长")
        response = LLMResponse(draft)
        await style.rewrite_reply(event, response)
        return response.completion_text, calls

    async def test_third_person_mention_passes_after_context_guard(self):
        text = "兄长大人教得很耐心，佳树一直在努力学哦"
        result, calls = await self.run_reply(text, "ok")
        self.assertEqual(result, text)
        self.assertEqual(calls[0][1:], ("学长", ["学长：挺聪明的还", "学长：xzz教得好"]))

    async def test_address_mistake_rejected_by_guard(self):
        result, calls = await self.run_reply("兄长大人，谢谢夸奖哦", "reject")
        self.assertEqual(result, "佳树一直很努力地学哦")
        self.assertEqual(len(calls), 2)  # 拦下后拿同一份指导再写一遍（retry 默认 1），还被拦就发原稿

    async def test_unavailable_guard_keeps_draft_even_if_draft_mentions_brother(self):
        draft = "兄长大人教佳树学了很多哦"
        for guard_mode in ("off", "error"):
            result, _ = await self.run_reply("兄长大人说得对，谢谢夸奖哦", guard_mode, draft)
            self.assertEqual(result, draft)

    async def test_polish_also_requires_guard(self):
        draft = "佳树一直很努力地学哦"
        new = "兄长大人教得很耐心，佳树一直在努力学哦"
        for mode in ("ok", "off", "reject", "error"):
            style = KajuStyle(Context(), {"rewrite": {"enable": True, "guard": mode != "off", "writer_only": False}})

            async def plan_of(ctx, original, kind, title):
                return {"局面": "学长夸她聪明", "要表达的": ["反应：被夸开心"]}

            async def write(ctx, plan, kind, title, ref=""):
                return new

            async def guard(*args):
                if mode == "error":
                    raise TimeoutError()
                return (mode == "reject", "称呼错误", True)

            style._plan_from_draft, style._write, style._guard = plan_of, write, guard
            out = await style.polish(draft, ["学长：挺聪明的还"], title="学长", kind="群聊", split=False)
            self.assertEqual(out, new if mode == "ok" else draft, mode)


if __name__ == "__main__":
    unittest.main()
