"""kaju_style：同一张卡写的话被核对拦两遍 → 带着问题回去重新出卡（2026-11-13）。

起因：兄长“中午好小佳树”，草稿“午饭要好好吃哦”被抽成“佳树吃过午饭了”，同一张卡写 4 遍都被拦，这句没说。

查这几件事：
- 第二次被拦才重出（第一次只照原卡再写），只重出一次
- 重出的提示里有上一份材料（不带心情行）、写出来的话、核对说的问题；系统提示还是 EXTRACT_V4
- 卡有错 → 后面几遍用新卡写（心情行照旧）；卡没错 / 看不懂 / Gemini 挂了 → 用原卡接着写
- recard_after = 0 关掉；v1 不重出

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_recard.py
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
from kaju_core.voice import card  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

DRAFT = "兄长大人中午好！\n昨晚聊到那么晚，今天起床有没有揉着眼睛犯困呀？\n午饭要好好吃哦。"
WRONG = json.dumps({"局面": "兄长大人跟佳树打招呼说中午好，轮到佳树回。",
                    "要说到的": ["佳树向兄长大人问好", "佳树吃过午饭了"]}, ensure_ascii=False)
RIGHT = json.dumps({"局面": "兄长大人跟佳树打招呼说中午好，轮到佳树回。",
                    "要说到的": ["佳树向兄长大人问好", "佳树问兄长大人今天困不困", "佳树叮嘱兄长大人好好吃午饭"]},
                   ensure_ascii=False)
FIXED = json.dumps({"逐条": [{"条": "佳树向兄长大人问好", "草稿原句": "兄长大人中午好！", "对不对": "对"},
                            {"条": "佳树吃过午饭了", "草稿原句": "没有", "对不对": "错"}],
                   **json.loads(RIGHT)}, ensure_ascii=False)
FINE = json.dumps({"逐条": [{"条": "佳树向兄长大人问好", "草稿原句": "兄长大人中午好！", "对不对": "对"}],
                  **json.loads(WRONG)}, ensure_ascii=False)
MOOD = "心情：开心6 精神5 紧绷1 亲近5"
V4 = {"enable": True, "card_format": "v4", "card_model": "kaju-writer-p4-8b-k", "retry": 3}


class PureTests(unittest.TestCase):
    def test_parse_recheck(self):
        self.assertEqual(card.parse_recheck_v4("```json\n" + FINE + "\n```"), ("keep", None))
        v, g = card.parse_recheck_v4(FIXED)
        self.assertEqual(v, "new")
        self.assertIn("佳树叮嘱兄长大人好好吃午饭", g["要说到的"])
        # 原句写“没有”但对不对写了“对”：还是算错
        odd = json.dumps({"逐条": [{"条": "佳树吃过午饭了", "草稿原句": "没有", "对不对": "对"}], **json.loads(RIGHT)},
                         ensure_ascii=False)
        self.assertEqual(card.parse_recheck_v4(odd)[0], "new")
        self.assertEqual(card.parse_recheck_v4(RIGHT), ("bad", None))  # 没逐条查 → 不认
        self.assertEqual(card.parse_recheck_v4("看不懂"), ("bad", None))
        broken = json.dumps({"逐条": [{"条": "x", "草稿原句": "没有", "对不对": "错"}], "局面": "", "要说到的": []})
        self.assertEqual(card.parse_recheck_v4(broken), ("bad", None))  # 说有错却没给能用的新卡

    def test_recheck_prompt(self):
        old = card.render_v4("私聊", "兄长大人", card.parse_v4(WRONG), MOOD)
        p = card.recheck_prompt_v4(["兄长大人：中午好小佳树"], DRAFT, "私聊", "兄长大人", old,
                                   "兄长大人中午好呀，佳树吃过午饭了", "加了草稿没有的事实：吃过午饭了", felt=True)
        self.assertTrue(p.startswith(card.extract_prompt_v4(["兄长大人：中午好小佳树"], DRAFT, "私聊", "兄长大人", True)))
        self.assertIn("要说到的：佳树向兄长大人问好；佳树吃过午饭了", p)
        self.assertIn("局面：兄长大人跟佳树打招呼说中午好", p)
        self.assertNotIn("心情：", p)
        self.assertNotIn("场合：私聊\n对象：", p)  # 上一份材料只给局面、要说到的
        self.assertIn("佳树照它写出的话：兄长大人中午好呀，佳树吃过午饭了", p)
        self.assertIn("核对说的问题：加了草稿没有的事实：吃过午饭了", p)
        self.assertIn("草稿原句", p)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def make(self, writes, guards, gems, cfg=None):
        style = KajuStyle(Context(), {"rewrite": {**V4, **(cfg or {})}})
        self.writes, self.guards, self.gems = list(writes), list(guards), list(gems)
        self.bodies, self.gem_calls = [], []

        async def fake_text(system, user, timeout=20, thinking="low"):
            self.gem_calls.append((system, user))
            g = self.gems.pop(0)
            if isinstance(g, Exception):
                raise g
            return g, 1
        self.real_text, omni.text = omni.text, fake_text

        async def local_chat(system, user):
            self.bodies.append(user)
            return self.writes.pop(0)

        async def guard(said, draft, new, title="", ctx=None):
            return self.guards.pop(0)

        style._local_chat, style._guard = local_chat, guard
        style._mood_line = lambda: MOOD
        return style

    def tearDown(self):
        omni.text = self.real_text

    async def reply(self, style):
        ev = AstrMessageEvent(text="中午好小佳树")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：中午好小佳树"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(ev, resp)
        return ev, resp.completion_text

    BAD = (True, "加了草稿没有的事实：佳树吃过午饭了", True)
    OK = (False, "", True)

    async def test_recard_after_second_reject(self):
        s = self.make(["佳树吃过午饭了", "佳树也吃过午饭了", "兄长大人中午好呀，午饭要好好吃哦"],
                      [self.BAD, self.BAD, self.OK], [WRONG, FIXED])
        ev, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "兄长大人中午好呀，午饭要好好吃哦")
        self.assertEqual(len(self.gem_calls), 2)  # 第一次出卡 + 第二次被拦后重出；第一次被拦不重出
        self.assertEqual(self.gem_calls[1][0], card.EXTRACT_V4)
        self.assertIn("佳树照它写出的话：佳树也吃过午饭了", self.gem_calls[1][1])  # 交回去的是第二遍
        self.assertEqual(self.bodies[0], self.bodies[1])  # 第二遍还是原卡
        self.assertIn("佳树叮嘱兄长大人好好吃午饭", self.bodies[2])  # 第三遍换新卡
        self.assertNotIn("佳树吃过午饭了", self.bodies[2].split("材料：")[1])
        self.assertTrue(self.bodies[2].endswith(MOOD))  # 心情行照旧
        self.assertIn("佳树叮嘱兄长大人好好吃午饭", ev.get_extra("kaju_style_card"))

    async def test_recard_only_once(self):
        s = self.make(["编1", "编2", "编3", "编4"], [self.BAD] * 4, [WRONG, FIXED], {"guard_fail": "silent", "guard_repair": False})
        _, out = await self.reply(s)
        self.assertEqual(out, "")  # 都没过还是不说（guard_fail=silent）
        self.assertEqual(len(self.gem_calls), 2)
        self.assertEqual(len(self.bodies), 4)

    async def test_card_fine_keeps_card(self):
        s = self.make(["编1", "编2", "兄长大人中午好呀"], [self.BAD, self.BAD, self.OK],
                      [WRONG, FINE])
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "兄长大人中午好呀")
        self.assertEqual(self.bodies[2], self.bodies[0])

    async def test_gemini_down_keeps_card(self):
        s = self.make(["编1", "编2", "兄长大人中午好呀"], [self.BAD, self.BAD, self.OK],
                      [WRONG, omni.GeminiDown("全挂了")])
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "兄长大人中午好呀")
        self.assertEqual(self.bodies[2], self.bodies[0])

    async def test_unreadable_keeps_card(self):
        s = self.make(["编1", "编2", "兄长大人中午好呀"], [self.BAD, self.BAD, self.OK], [WRONG, "嗯……"])
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "兄长大人中午好呀")
        self.assertEqual(self.bodies[2], self.bodies[0])

    async def test_off(self):
        s = self.make(["编1", "编2", "兄长大人中午好呀"], [self.BAD, self.BAD, self.OK], [WRONG], {"recard_after": 0})
        await self.reply(s)
        self.assertEqual(len(self.gem_calls), 1)

    async def test_guard_error_not_counted(self):
        # 核对出错（超时）：writer_only 下照发这一遍，不算被拦、不重出
        s = self.make(["兄长大人中午好呀"], [(True, "核对失败 TimeoutError", True)], [WRONG])

        async def boom(*a, **k):
            raise TimeoutError()
        s._guard = boom
        _, out = await self.reply(s)
        self.assertEqual(out.replace("\n", ""), "兄长大人中午好呀")
        self.assertEqual(len(self.gem_calls), 1)

    async def test_records_note_recheck(self):
        s = self.make(["编1", "编2", "兄长大人中午好呀"], [self.BAD, self.BAD, self.OK], [WRONG, FIXED])
        cards = []
        rec = getattr(s, "_rec", None) or getattr(getattr(s, "mind", None), "_rec", None)
        if rec is None:
            self.skipTest("这里没有 records")
        real_note = rec.note
        rec.note = lambda key, item: (cards.append(item) if key == "card" else None, real_note(key, item))
        await self.reply(s)
        self.assertTrue(any(c.get("recheck") for c in cards))


if __name__ == "__main__":
    unittest.main()
