"""kaju_style 1.17.0：第四版卡 + 新写手（kaju-writer-p4-8b-k，2026-11-12 上线）。

查这几件事：
- 写手的系统提示 / 用户消息和训练包一字不差（train.py 的 prompt_of、data\\system.json 的 "2"）；卡的样子和 make_train_pack 拼的一样
- 调写手带 reasoning_effort none、max_tokens 只是兜底（1024）；v1 照旧（220、不带）
- Gemini 出卡：解析、渲染（有心情就在最后加一行）、空的“要说到的”算没出好
- 写手打转 → 这一遍不算，拿同一张卡再写；不按字数卡长短
- Gemini 全挂了（11-13 兄长）：群里、私聊都不说话，DeepSeek 用 QQ 和抖音私信告诉兄长；主动的话（polish）把 GeminiDown 交给调用的地方
- 只发写手的话（writer_only，11-13）：核对都没过发写手最后一遍、写手出错不说、回晚了也过写手；关掉才退回原稿

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_v4.py
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

PACK = Path(r"D:\JiashuBot\voice_train\train_pack\kaju_train_pack")
DRAFT = "好呀兄长大人，佳树也正好累了，兄长大人想聊点什么呢？"
GEM = json.dumps({"局面": "兄长大人说做完事了脑子转不动，让佳树陪他聊点轻松的，轮到佳树回。",
                  "要说到的": ["佳树答应陪兄长大人聊轻松的", "佳树问兄长大人想聊什么"]}, ensure_ascii=False)
V4 = {"enable": True, "card_format": "v4", "card_model": "kaju-writer-p4-8b-k"}


class PureTests(unittest.TestCase):
    def test_same_as_training(self):
        if (PACK / "data" / "system.json").exists():
            self.assertEqual(card.SYSTEM_V4, json.load(open(PACK / "data" / "system.json", encoding="utf-8"))["2"])
        sample = {"ctx": ["兄长大人：在吗"], "card": "场合：私聊"}
        self.assertEqual(card.write_prompt_v4(sample["ctx"], sample["card"]), "聊天：\n兄长大人：在吗\n\n材料：\n场合：私聊")
        self.assertEqual(card.write_prompt_v4([], "x"), "聊天：\n（没有前文）\n\n材料：\nx")
        if (PACK / "train.py").exists():  # 训练包里 prompt_of 的那一行
            src = (PACK / "train.py").read_text(encoding="utf-8")
            self.assertIn('return f"聊天：\\n{ctx}\\n\\n材料：\\n{sample[\'card\']}"', src)

    def test_parse_render(self):
        g = card.parse_v4("```json\n" + GEM + "\n```")
        self.assertEqual(g["要说到的"], ["佳树答应陪兄长大人聊轻松的", "佳树问兄长大人想聊什么"])
        self.assertIsNone(card.parse_v4('{"局面": "轮到佳树回。", "要说到的": []}'))  # 空的不算
        self.assertIsNone(card.parse_v4('{"局面": "轮到佳树回。", "要说到的": ["无"]}'))
        self.assertIsNone(card.parse_v4("不是 JSON"))
        text = card.render_v4("私聊", "兄长大人", g, "心情：开心6 精神6 紧绷1 亲近5")
        self.assertEqual(text.split("\n"), ["场合：私聊", "对象：兄长大人", "局面：" + g["局面"],
                                            "要说到的：佳树答应陪兄长大人聊轻松的；佳树问兄长大人想聊什么", "心情：开心6 精神6 紧绷1 亲近5"])
        self.assertNotIn("长短", text)
        self.assertNotIn("心情", card.render_v4("私聊", "兄长大人", g, ""))

    def test_loops_and_sane(self):
        loop = "佳树刚才刷到一个《快干活！》搞笑动画，" * 4
        self.assertTrue(card.loops(loop))
        self.assertTrue(card.loops("兄长大人晚安\n佳树也爱你哦\n兄长大人晚安"))
        self.assertFalse(card.loops("兄长大人晚安，佳树也最爱兄长大人了～兄长大人快去睡吧"))  # 称呼出现几次不算
        long_ok = "前半段真的很好笑，后半段氛围超级治愈。" + "佳树看完以后整个人都放松下来了，" + "今天在学校上了一整天课的疲惫全都没了。" * 1
        self.assertTrue(card.sane_v4(long_ok * 1, "场合：私聊", ""))  # 不按字数卡
        self.assertFalse(card.sane_v4("要说到的：佳树答应", "场合：私聊"))
        self.assertFalse(card.sane_v4(loop, "场合：私聊"))
        self.assertFalse(card.sane_v4("今天也要上課", "场合：私聊", "今天也要上课"))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def make(self, cfg=None, writes=None, gem=None, guard_bad=False):
        style = KajuStyle(Context(), {"rewrite": {**V4, **(cfg or {})}})
        self.writes, self.bodies, self.gem_calls = list(writes or []), [], []

        async def fake_text(system, user, timeout=20, thinking="low"):
            self.gem_calls.append((system, user, timeout))
            if isinstance(gem, Exception):
                raise gem
            return (gem if gem is not None else GEM), 1
        self.real_text, omni.text = omni.text, fake_text

        async def local_chat(system, user):
            self.bodies.append((system, user))
            w = self.writes.pop(0)
            if isinstance(w, Exception):
                raise w
            return w

        async def guard(said, draft, new, title="", ctx=None):
            return (guard_bad, "", True)

        style._local_chat, style._guard = local_chat, guard
        style._mood_line = lambda: "心情：开心6 精神6 紧绷1 亲近5"
        return style

    def tearDown(self):
        if hasattr(self, "real_text"):
            omni.text = self.real_text

    async def reply(self, style, group=False, felt=False):
        ev = AstrMessageEvent(text="先陪我随便聊点轻松的吧", group="222222222" if group else "")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：今天的事情终于做完了，脑子转不动了。", "兄长大人：先陪我随便聊点轻松的吧"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        if felt:
            ev.set_extra("_kaju_felt", True)
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(ev, resp)
        return ev, resp.completion_text

    async def test_card_and_prompt(self):
        style = self.make(writes=["好啊好啊兄长大人，佳树正好也累了，兄长大人想聊点什么呢？"])
        ev, out = await self.reply(style)
        self.assertEqual(out.replace("\n", ""), "好啊好啊兄长大人，佳树正好也累了，兄长大人想聊点什么呢？".replace("\n", "") or out)
        system, user = self.bodies[0]
        self.assertEqual(system, card.SYSTEM_V4)
        self.assertTrue(user.startswith("聊天：\n兄长大人：今天的事情终于做完了"))
        self.assertIn("\n\n材料：\n场合：私聊\n对象：兄长大人\n局面：", user)
        self.assertTrue(user.endswith("要说到的：佳树答应陪兄长大人聊轻松的；佳树问兄长大人想聊什么\n心情：开心6 精神6 紧绷1 亲近5"))
        self.assertIn("草稿：\n" + DRAFT, self.gem_calls[0][1])
        self.assertEqual(self.gem_calls[0][0], card.EXTRACT_V4)
        self.assertEqual(self.gem_calls[0][2], 20.0)

    async def test_felt_flag_reaches_gemini(self):
        style = self.make(writes=["佳树看完啦，仙人掌扭着学说话，又魔性又好笑"])
        await self.reply(style, felt=True)
        self.assertIn("这一轮佳树刚看完", self.gem_calls[0][1])

    async def test_loop_rewritten(self):
        loop = "佳树刚才刷到一个搞笑动画，" * 5
        style = self.make(writes=[loop, "佳树刚才刷到一个搞笑动画，笑得停不下来呢"])
        _, out = await self.reply(style)
        self.assertEqual(len(self.bodies), 2)
        self.assertNotIn(loop, out)
        self.assertIn("笑得停不下来", out.replace("\n", ""))

    async def test_gemini_down_group_silent(self):
        style = self.make(gem=omni.GeminiDown("全挂了"))
        ev, out = await self.reply(style, group=True)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())
        self.assertEqual(self.bodies, [])

    def watch_notice(self, style, dy_ok=True):
        """Gemini 挂了时的通知：DeepSeek 写、QQ 私聊 + 抖音私信发给兄长（假的 body / kaju_dm / 身份表）。"""
        from kaju_core import people
        self.sent, self.prompts = [], []

        async def model_id(model="", who=""):
            return model

        async def generate(pid, prompt, system="", timeout=None):
            self.prompts.append((pid, prompt))
            return "兄长大人，佳树这边的 Gemini 全都连不上了，先没法好好说话，帮佳树看看 key 嘛"

        async def send(where, text="", image=""):
            self.sent.append(("qq", where, text))
            return True

        class Dm:
            async def tell_owner_dm(dm_self, text, sites=("douyin",)):
                self.sent.append(("dm", sites, text))
                return ["抖音"] if dy_ok else []

        style.body.model_id, style.body.generate, style.body.send = model_id, generate, send
        style.body.private_chat_id = lambda uid, like="": f"aiocqhttp:FriendMessage:{uid}"
        style.body.find = lambda attr: Dm() if attr == "tell_owner_dm" else None
        self.real_owner, people.owner = people.owner, (lambda: "111111111")
        self.addCleanup(setattr, people, "owner", self.real_owner)

    async def settle(self):
        import asyncio
        for _ in range(5):
            await asyncio.sleep(0)

    async def test_gemini_down_private_silent_and_deepseek_tells_owner(self):
        style = self.make(gem=omni.GeminiDown("全挂了 https://relay.example/v1 key...aaa8"))
        self.watch_notice(style)
        ev, out = await self.reply(style)
        await self.settle()
        self.assertEqual(out, "")  # 这一句不发（也不发 DeepSeek 的草稿）
        self.assertTrue(ev.is_stopped())
        self.assertEqual(self.bodies, [])  # 写手也不替她说
        self.assertEqual([x[0] for x in self.sent], ["qq", "dm"])
        self.assertEqual(self.sent[0][1], "aiocqhttp:FriendMessage:111111111")
        self.assertEqual(self.sent[1][1], ("douyin",))
        self.assertEqual(self.prompts[0][0], "deepseek")
        self.assertNotIn("relay.example", self.prompts[0][1])  # 报错原文不给 DeepSeek
        # 30 分钟内再挂只说一次
        ev2, out2 = await self.reply(style, group=True)
        await self.settle()
        self.assertEqual(out2, "")
        self.assertEqual(len(self.sent), 2)

    async def test_writer_only_guard_fails_says_nothing(self):
        # 11-13 兄长：核对拦下的（编了“兄长大人好帅”）不照发，也不发草稿 → 这句不说
        # 11-15 起默认是 busy（先改错、再说在忙），这里固定成 silent、不改错
        style = self.make(cfg={"guard_fail": "silent", "guard_repair": False}, writes=["佳树第一遍", "佳树第二遍"],
                          guard_bad=True)
        ev, out = await self.reply(style)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_writer_only_guard_fails_send_writer_mode(self):
        style = self.make(cfg={"guard_fail": "send_writer"}, writes=["佳树第一遍", "佳树第二遍"], guard_bad=True)
        _, out = await self.reply(style)
        self.assertEqual(out.replace("\n", ""), "佳树第二遍")
        self.assertNotIn("想聊点什么", out)

    async def test_writer_only_writer_error_says_nothing(self):
        style = self.make(writes=[RuntimeError("ollama down")])
        ev, out = await self.reply(style)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_writer_only_late_still_writer(self):
        import time
        style = self.make(cfg={"skip_when_late": 5}, writes=["好啊兄长大人，聊什么都行"])
        ev = AstrMessageEvent(text="先陪我随便聊点轻松的吧")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：先陪我随便聊点轻松的吧"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        ev.set_extra("_kaju_quote_t", time.time() - 100)
        resp = LLMResponse(DRAFT)
        await style.rewrite_reply(ev, resp)
        self.assertIn("聊什么都行", resp.completion_text.replace("\n", ""))

    async def test_writer_only_off_falls_back_to_draft(self):
        style = self.make(cfg={"writer_only": False}, writes=["佳树第一遍", "佳树第二遍"], guard_bad=True)
        _, out = await self.reply(style)
        self.assertEqual(out, DRAFT)

    async def test_main_model_error_hushed_and_told(self):
        from astrbot.api.message_components import Plain

        class Result:
            def __init__(self, text, llm=False):
                self.chain, self.llm = [Plain(text)], llm

            def is_llm_result(self):
                return self.llm

        style = self.make()
        self.watch_notice(style)
        for text in ("LLM 响应错误: All chat models failed: APIError 503", "Error occurred during AI execution.\nError Type: X"):
            ev = AstrMessageEvent(text="在吗")
            ev.set_result(Result(text))
            await style.hush_model_error(ev)
            self.assertIsNone(ev.get_result())
            self.assertTrue(ev.is_stopped())
        await self.settle()
        self.assertEqual([x[0] for x in self.sent], ["qq", "dm"])  # 只说一次
        ok = AstrMessageEvent(text="在吗")
        ok.set_result(Result("佳树在呢", llm=True))
        await style.hush_model_error(ok)
        self.assertIsNotNone(ok.get_result())
        resp = LLMResponse("LLM 响应错误: x")
        resp.role = "err"
        ev = AstrMessageEvent(text="在吗")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：在吗"])
        await style.rewrite_reply(ev, resp)
        self.assertEqual(self.gem_calls, [])  # 报错不拿去出卡

    async def test_polish_writer_only_no_draft(self):
        style = self.make(writes=[RuntimeError("ollama down")])
        out = await style.polish("兄长大人，佳树刚刷到一个好玩的视频", ["兄长大人：在吗"], said="刷到视频")
        self.assertEqual(out, "")

    async def test_gemini_down_private_writer_fails_says_nothing(self):
        style = self.make(gem=omni.GeminiDown("全挂了"), writes=[RuntimeError("ollama down")])
        self.watch_notice(style)
        ev, out = await self.reply(style)
        await self.settle()
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_polish_raises_gemini_down(self):
        style = self.make(gem=omni.GeminiDown("全挂了"))
        with self.assertRaises(omni.GeminiDown):
            await style.polish("兄长大人，佳树刚刷到一个好玩的视频", ["兄长大人：在吗"], said="刷到视频")

    async def test_writer_call_options(self):
        style = KajuStyle(Context(), {"rewrite": {**V4}})
        seen = {}

        class R:
            def raise_for_status(self):
                pass

            async def json(self):
                return {"choices": [{"message": {"content": "好的"}}]}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class S:
            def __init__(self, *a, **k):
                pass

            def post(self, url, json=None, headers=None):
                seen.update(json)
                return R()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass
        import aiohttp
        real = aiohttp.ClientSession
        aiohttp.ClientSession = S
        try:
            await style._local_chat("s", "u")
            self.assertEqual((seen["reasoning_effort"], seen["max_tokens"], seen["model"]), ("none", 1024, "kaju-writer-p4-8b-k"))
            seen.clear()  # 第一版卡（不关思考、220 字）11-18 删了：配置里没写 card_format 也照第四版发
            plain = KajuStyle(Context(), {"rewrite": {"enable": True, "card_model": "kaju-writer-p6-8b-r7k"}})
            await plain._local_chat("s", "u")
            self.assertEqual((seen.get("reasoning_effort"), seen["max_tokens"]), ("none", 1024))
        finally:
            aiohttp.ClientSession = real

    async def test_say_from_card_v4(self):
        style = self.make(writes=["好的兄长大人，佳树这就去看"])
        ev = AstrMessageEvent(text="[分享了一个视频]")
        out = await style.say_from_card(ev, points=["佳树去看视频"], said="[分享了一个视频]")
        self.assertTrue(out)
        user = self.bodies[0][1]
        self.assertIn("局面：", user)
        self.assertIn("要说到的：佳树去看视频", user)
        self.assertNotIn("情绪：", user)


if __name__ == "__main__":
    unittest.main(verbosity=1)
