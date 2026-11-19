"""规划器（shadow.py）的纯函数：离线回放脚本（replay_planner / replay_brain / compare_plans …）还在用。

线上的“规划器出卡”（B 那条路，rewrite.card_source = "planner"，2026-11-17）11-18 整理时删了（replay6 盲选输了、一直关着）；
这里也查一下：配置里就算还写着 card_source = planner，线上照旧只从草稿摘卡。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_planner.py
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
from kaju_core.senses import omni  # noqa: E402
from kaju_core.voice import card, rewrite, shadow  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

DRAFT = "兄长大人没点辣的呀，是吃不惯辣还是累了没胃口呀"
GEM = json.dumps({"局面": "兄长大人说吃到后面吃不下了，轮到佳树回。", "要说到的": ["佳树问兄长大人是不是累了"]}, ensure_ascii=False)
PLAN = {"回不回": "回", "局面": "兄长大人在回佳树问他吃得怎样，轮到佳树回。", "要回应的": "兄长大人说没点辣的、吃到后面吃不下了",
        "方向": "关心他", "事实": ["佳树记得兄长大人考前说想吃辣犒劳自己"], "背景": ["兄长大人今天考完 Dafny"]}


class Pure(unittest.TestCase):
    def test_card_of_matches_training(self):
        text = shadow.card_of("私聊", "兄长大人", PLAN, "心情：开心4")
        self.assertEqual(text.split("\n"), ["场合：私聊", "对象：兄长大人",
                                            "局面：兄长大人在回佳树问他吃得怎样，轮到佳树回。要接住的：兄长大人说没点辣的、吃到后面吃不下了",
                                            "要说到的：佳树记得兄长大人考前说想吃辣犒劳自己", "背景：兄长大人今天考完 Dafny", "心情：开心4"])
        self.assertIn("要说到的：无", shadow.card_of("群聊", "学姐", {"局面": "x", "事实": []}))
        self.assertNotIn("关心他", text)  # 方向不进卡

    def test_parse_reply_or_not(self):
        p = shadow.parse(json.dumps({**PLAN, "回不回": "不回"}, ensure_ascii=False))
        self.assertEqual(p["回不回"], "不回")
        self.assertEqual(shadow.parse(json.dumps(PLAN, ensure_ascii=False))["回不回"], "回")

    def test_live_prompt_has_draft(self):
        s = shadow.live_prompt({"system_prompt": "人设", "prompt": "最新", "extra": [], "contexts": []}, DRAFT, "卡错了")
        self.assertIn("【主模型写的草稿（只当材料：它查到的、做了的事）】\n" + DRAFT, s)
        self.assertTrue(s.endswith("【上一份指导的问题】\n卡错了"))

    def test_guard_prompt_known(self):
        g = rewrite.guard_prompt("在吗", "草稿", "改写", "兄长大人", ["兄长大人：在吗"], "佳树读到上卷结尾")
        self.assertIn("她确实知道的事", g)
        self.assertIn("佳树读到上卷结尾", g)
        self.assertNotIn("她确实知道的事", rewrite.guard_prompt("在吗", "草稿", "改写"))


class Retired(unittest.IsolatedAsyncioTestCase):
    async def test_card_source_planner_is_ignored(self):
        """配置里残留的 card_source = planner / card_format = v1 都不再起作用：只问一次出卡（EXTRACT_V4），写手照第四版卡写。"""
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "card_format": "v1", "card_source": "planner",
                                                  "planner_skip": "group", "card_model": "kaju-writer-p6-8b-r7k",
                                                  "shadow_plan": False}})
        calls, bodies = [], []

        async def fake_text(system, user, timeout=20, thinking="low"):
            calls.append(system)
            return GEM, 1
        real, omni.text = omni.text, fake_text

        async def local_chat(system, user):
            bodies.append((system, user))
            return "兄长大人是不是累了呀"

        async def guard(said, draft, new, title="", ctx=None):
            return (False, "", True)
        style._local_chat, style._guard = local_chat, guard
        style._mood_line = lambda: "心情：开心4 精神5"
        try:
            ev = AstrMessageEvent(text="没点辣的，吃到后面有点吃不下了", group="222222222")
            ev.set_extra("_ks_rw_ctx", ["兄长大人：已经吃完回来了", "兄长大人：没点辣的，吃到后面有点吃不下了"])
            ev.set_extra("_ks_rw_title", "兄长大人")
            resp = LLMResponse(DRAFT)
            await style.rewrite_reply(ev, resp)
        finally:
            omni.text = real
        self.assertEqual(calls, [card.EXTRACT_V4])
        self.assertEqual(resp.completion_text, "兄长大人是不是累了呀")
        self.assertIn(card.SYSTEM_V4.split("\n")[0], bodies[0][0])  # 写手用第四版的系统提示
        self.assertIn("局面：兄长大人说吃到后面吃不下了", bodies[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
