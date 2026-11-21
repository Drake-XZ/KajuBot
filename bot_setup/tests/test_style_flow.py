"""kaju_style：她的话只由回复器照大脑的指导写（2026-11-21 起没有第四版要点卡、没有本地写手）。

查这几件事：
- 大脑给了 JSON → 回复器照指导写，不再问模型
- 大脑直接写了她的话（11-21 兄长喊她“妈妈”那两次）→ 同一份材料再问一遍、叮嘱只输出 JSON，用第二遍的指导
- 再问也不行：私聊照日程说一句在忙；群里不说
- 这一轮没换成大脑（回来的是草稿）→ 先整理成指导；草稿是 [SKIP] 就不说
- 写出来打转 / 漏出指导的格式 → 这一遍不算，再写
- 只发回复器的话（writer_only）：核对都没过按 guard_fail；回复器出错不说；回晚了也照写；关掉才照发原话
- 主模型全挂：AstrBot 的报错不发，DeepSeek 告诉兄长（30 分钟一次）
- 主动的话（polish）：草稿 → 指导 → 回复器；插件给要点（say_from_card）直接拼成指导

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_flow.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core.voice import brain, replyer  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

PLAN = {"回不回": "回", "局面": "兄长大人做完事了，想让她陪着聊点轻松的", "要接住的": "他让她陪着聊轻松的",
        "要表达的": ["答应：陪他聊轻松的", "反问：想聊什么"], "背景": [], "情绪": "开心"}
PLAN_JSON = json.dumps(PLAN, ensure_ascii=False)
TALK = "兄长大人又喊佳树妈妈啦wwww\n这次一定要吃够本"  # 大脑没出指导，直接用她的口吻写了
DRAFT = "兄长大人！佳树刚刷到一只小猫第一次见到雪，踩来踩去的好可爱"
DRAFT_PLAN = json.dumps({"局面": "她刚刷到一个视频，想分享给兄长大人", "要接住的": "",
                         "要表达的": ["分享：小猫第一次见到雪，踩来踩去"], "背景": [], "情绪": "觉得可爱"}, ensure_ascii=False)


class Pure(unittest.TestCase):
    def test_sane(self):
        loop = "佳树刚才刷到一个搞笑动画，" * 5
        self.assertTrue(replyer.loops(loop))
        self.assertTrue(replyer.loops("兄长大人晚安\n佳树也爱你哦\n兄长大人晚安"))
        self.assertFalse(replyer.loops("兄长大人晚安，佳树也最爱兄长大人了～兄长大人快去睡吧"))  # 称呼出现几次不算
        self.assertTrue(replyer.sane("".join(f"第{i}件事" for i in range(150))))  # 不按字数卡
        self.assertFalse(replyer.sane("局面：他想聊天\n好呀"))
        self.assertFalse(replyer.sane("要表达的：答应\n好呀"))
        self.assertFalse(replyer.sane(loop))
        self.assertFalse(replyer.sane("今天也要上課", "上课"))
        self.assertTrue(replyer.sane("佳树看过入間人間的书", "分享：入間人間的书"))
        self.assertEqual(replyer.trad_chars("晚饭吃快餐了吗，著名的面馆"), "")

    def test_parse_and_prompts(self):
        p = brain.parse('```json\n{"局面": "兄长大人突然喊了一声"妈妈"，说明天去吃烤肉", "要表达的": ["反应：被叫妈妈"]}\n```')
        self.assertEqual(p["局面"], "兄长大人突然喊了一声“妈妈”，说明天去吃烤肉")  # 中文里夹英文引号也认
        hist = [("user", "晚安"), ("assistant", "晚安呀")]
        r = brain.rethink_prompt("妈妈！", hist, TALK)
        self.assertIn("对方：晚安", r)
        self.assertIn("直接写成了她要说的话", r)
        self.assertIn(TALK.splitlines()[0], r)
        self.assertTrue(r.rstrip().endswith("只输出 JSON。"))
        self.assertIn("群里：晚安", brain.rethink_prompt("x", hist, "{坏", group=True))
        self.assertIn("格式不对", brain.rethink_prompt("x", hist, "{坏"))
        self.assertIn("群里：晚安", brain.replan_prompt("x", hist, ["新来的"]))  # 重想照旧
        u = brain.from_draft_prompt("私聊", "兄长大人", ["兄长大人：在吗"], DRAFT)
        self.assertIn("场合：私聊，对兄长大人说", u)
        self.assertTrue(u.endswith("草稿：\n" + DRAFT))
        self.assertIn("QQ 空间的说说", brain.from_draft_prompt("说说", "", [], "今天烤了松饼"))
        self.assertFalse(hasattr(brain, "card_of"))


class Flow(unittest.IsolatedAsyncioTestCase):
    def make(self, cfg=None, writes=None, gen=None, guard_bad=False):
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "action_judge": False, "replan": False, **(cfg or {})}})
        self.writes, self.plans, self.gens = list(writes or []), [], []
        real = replyer.reply

        async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
            self.plans.append((kind, title, dict(plan)))
            w = self.writes.pop(0) if self.writes else ""
            if isinstance(w, Exception):
                raise w
            return w, {"model": "测试", "secs": 0.1, "examples": [], "errors": [] if w else ["没写出来"]}
        replyer.reply = fake_reply
        self.addCleanup(setattr, replyer, "reply", real)
        answers = list(gen or [])

        async def model_id(model="", who=""):
            return model or "main"

        async def generate(pid, prompt, system="", timeout=None):
            self.gens.append((pid, prompt, system))
            a = answers.pop(0) if answers else ""
            if isinstance(a, Exception):
                raise a
            return a
        style.body.model_id, style.body.generate = model_id, generate

        async def guard(said, draft, new, title="", ctx=None):
            return (guard_bad, "编了事" if guard_bad else "", True)
        style._guard = guard
        style._mood_words = lambda group=False: ""
        style._doing_now = lambda: "在写作业"
        return style

    async def reply(self, style, text, group=False, brain_turn=True, req=True, late=False):
        ev = AstrMessageEvent(text="先陪我随便聊点轻松的吧", group="222222222" if group else "")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：今天的事情终于做完了", "兄长大人：先陪我随便聊点轻松的吧"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        if late:
            ev.set_extra("_kaju_quote_t", time.time() - 100)
        if brain_turn:
            ev.set_extra("_ks_brain", True)
            if req:
                ev.set_extra("_ks_brain_req", SimpleNamespace(
                    system_prompt="大脑的要求", prompt="先陪我随便聊点轻松的吧", extra_user_content_parts=[],
                    contexts=[{"role": "user", "content": "今天的事情终于做完了"}, {"role": "assistant", "content": "辛苦啦"}]))
        resp = LLMResponse(text)
        await style.rewrite_reply(ev, resp)
        return ev, resp.completion_text

    async def test_brain_plan_goes_to_replyer(self):
        style = self.make(writes=["好呀，兄长大人想聊什么呢"])
        ev, out = await self.reply(style, PLAN_JSON)
        self.assertIn("想聊什么", out.replace("\n", ""))
        self.assertEqual(self.plans[0][2]["要表达的"], PLAN["要表达的"])
        self.assertEqual(self.gens, [])  # 不再问模型
        self.assertEqual(ev.get_extra("_ks_plan")["局面"], PLAN["局面"])

    async def test_brain_talked_asks_again(self):
        style = self.make(writes=["佳树是妹妹啦wwww，兄长大人明天吃够本哦"], gen=[PLAN_JSON])
        ev, out = await self.reply(style, TALK)
        self.assertIn("吃够本", out.replace("\n", ""))
        self.assertEqual(len(self.gens), 1)
        pid, prompt, system = self.gens[0]
        self.assertEqual((pid, system), ("main", "大脑的要求"))  # 同一份材料，走主模型（挑模型、后备）
        self.assertIn("【前面的对话】", prompt)
        self.assertIn("【上一遍没按要求】", prompt)
        self.assertIn("妈妈", prompt)
        self.assertEqual(self.plans[0][2]["局面"], PLAN["局面"])
        self.assertEqual(ev.get_extra("_ks_plan")["要表达的"], PLAN["要表达的"])

    async def test_asks_again_fails_private_says_busy(self):
        style = self.make(writes=["佳树在写作业呢，等下再好好回兄长大人"], gen=["兄长大人又喊佳树妈妈啦"])
        ev, out = await self.reply(style, TALK)
        self.assertIn("写作业", out)
        self.assertTrue(ev.get_extra("kaju_style_busy"))
        said = self.plans[0][2]["要表达的"]
        self.assertTrue(said[0].startswith("解释：") and "在写作业" in said[0])
        self.assertIn("兄长大人刚才说的", said[1])

    async def test_asks_again_fails_group_silent(self):
        style = self.make(writes=["不该写"], gen=["{坏的"])
        ev, out = await self.reply(style, TALK, group=True)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())
        self.assertEqual(self.plans, [])
        self.assertEqual(ev.get_extra("kaju_style_rewritten")["new"], "")  # 历史里别留下它写的

    async def test_private_no_reply_only_counts_as_failed(self):
        style = self.make(writes=["好呀"], gen=[PLAN_JSON])
        await self.reply(style, '{"回不回": "不回"}')
        self.assertEqual(len(self.gens), 1)  # 私聊一律回：只写了“不回”也再问

    async def test_no_saved_request_private_busy(self):
        style = self.make(writes=["佳树这会儿有点忙，等下回兄长大人"])
        ev, out = await self.reply(style, TALK, req=False)
        self.assertEqual(self.gens, [])
        self.assertTrue(ev.get_extra("kaju_style_busy"))

    async def test_draft_turn_planned_first(self):
        style = self.make(writes=["兄长大人！佳树刷到小猫踩雪了"], gen=[DRAFT_PLAN])
        _, out = await self.reply(style, DRAFT, brain_turn=False)
        self.assertIn("小猫", out)
        self.assertEqual(self.gens[0][2], brain.FROM_DRAFT)
        self.assertIn("草稿：\n" + DRAFT, self.gens[0][1])

    async def test_skip_draft_turn_says_nothing(self):
        style = self.make(writes=["不该写"])
        ev, out = await self.reply(style, "[SKIP]", brain_turn=False)
        self.assertEqual((out, self.plans, self.gens), ("", [], []))
        self.assertTrue(ev.is_stopped())

    async def test_loop_and_leak_written_again(self):
        loop = "佳树刚才刷到一个搞笑动画，" * 5
        style = self.make(writes=[loop, "好呀兄长大人，聊什么都行"])
        _, out = await self.reply(style, PLAN_JSON)
        self.assertEqual(len(self.plans), 2)
        self.assertIn("聊什么都行", out.replace("\n", ""))
        style = self.make(writes=["局面：他想聊\n好呀", "好呀，想聊什么"])
        _, out = await self.reply(style, PLAN_JSON)
        self.assertEqual(len(self.plans), 2)
        self.assertNotIn("局面", out)

    async def test_guard_fails_silent(self):
        # 11-13 兄长：核对拦下的不照发；固定成 silent、不改错
        style = self.make(cfg={"guard_fail": "silent", "guard_repair": False}, writes=["第一遍", "第二遍"], guard_bad=True)
        ev, out = await self.reply(style, PLAN_JSON)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_guard_fails_send_writer(self):
        style = self.make(cfg={"guard_fail": "send_writer"}, writes=["佳树第一遍", "佳树第二遍"], guard_bad=True)
        _, out = await self.reply(style, PLAN_JSON)
        self.assertEqual(out.replace("\n", ""), "佳树第二遍")

    async def test_replyer_error_says_nothing(self):
        style = self.make(writes=[RuntimeError("中转站 502")])
        ev, out = await self.reply(style, PLAN_JSON)
        self.assertEqual(out, "")
        self.assertTrue(ev.is_stopped())

    async def test_late_still_writes(self):
        style = self.make(cfg={"skip_when_late": 5}, writes=["好啊兄长大人，聊什么都行"])
        _, out = await self.reply(style, PLAN_JSON, late=True)
        self.assertIn("聊什么都行", out.replace("\n", ""))

    async def test_writer_only_off_keeps_original(self):
        style = self.make(cfg={"writer_only": False}, gen=["还是不是 JSON"])
        _, out = await self.reply(style, TALK)
        self.assertEqual(out, TALK)

    def watch_notice(self, style):
        """主模型全挂时的通知：DeepSeek 写、QQ 私聊 + 抖音私信发给兄长（假的 body / kaju_dm / 身份表）。"""
        from kaju_core import people
        self.sent, self.prompts = [], []

        async def model_id(model="", who=""):
            return model

        async def generate(pid, prompt, system="", timeout=None):
            self.prompts.append((pid, prompt))
            return "兄长大人，佳树这边写回复的模型都没答上来，帮佳树看看嘛"

        async def send(where, text="", image=""):
            self.sent.append(("qq", where, text))
            return True

        class Dm:
            async def tell_owner_dm(dm_self, text, sites=("douyin",)):
                self.sent.append(("dm", sites, text))
                return ["抖音"]

        style.body.model_id, style.body.generate, style.body.send = model_id, generate, send
        style.body.private_chat_id = lambda uid, like="": f"aiocqhttp:FriendMessage:{uid}"
        style.body.find = lambda attr: Dm() if attr == "tell_owner_dm" else None
        real_owner, people.owner = people.owner, (lambda: "111111111")
        self.addCleanup(setattr, people, "owner", real_owner)

    async def test_main_model_error_hushed_and_told(self):
        import asyncio
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
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual([x[0] for x in self.sent], ["qq", "dm"])  # 只说一次
        self.assertEqual(self.prompts[0][0], "deepseek")
        ok = AstrMessageEvent(text="在吗")
        ok.set_result(Result("佳树在呢", llm=True))
        await style.hush_model_error(ok)
        self.assertIsNotNone(ok.get_result())
        resp = LLMResponse("LLM 响应错误: x")
        resp.role = "err"
        ev = AstrMessageEvent(text="在吗")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：在吗"])
        await style.rewrite_reply(ev, resp)
        self.assertEqual(self.plans, [])  # 报错不拿去写

    async def test_polish_draft_to_plan(self):
        style = self.make(writes=["兄长大人！佳树刚刷到小猫第一次见到雪"], gen=[DRAFT_PLAN])
        out = await style.polish(DRAFT, ["兄长大人：在吗"], said="刷到视频")
        self.assertIn("小猫", out)
        self.assertEqual(self.gens[0][2], brain.FROM_DRAFT)
        self.assertEqual(self.plans[0][2]["要表达的"], ["分享：小猫第一次见到雪，踩来踩去"])
        self.assertEqual(self.plans[0][0], "私聊")

    async def test_polish_no_plan_or_writer_says_nothing(self):
        style = self.make(gen=["看不懂"])
        self.assertEqual(await style.polish(DRAFT, ["兄长大人：在吗"], said="刷到视频"), "")
        self.assertEqual(self.plans, [])
        style = self.make(gen=[DRAFT_PLAN], writes=[RuntimeError("502")])
        self.assertEqual(await style.polish(DRAFT, ["兄长大人：在吗"], said="刷到视频"), "")

    async def test_say_from_card_points(self):
        style = self.make(writes=["好的兄长大人，佳树这就去看"])
        ev = AstrMessageEvent(text="[分享了一个视频]")
        out = await style.say_from_card(ev, points=["分享：佳树先去看视频"], said="[分享了一个视频]")
        self.assertTrue(out)
        self.assertEqual(self.gens, [])  # 不用主模型起草
        plan = self.plans[0][2]
        self.assertEqual(plan["要表达的"], ["分享：佳树先去看视频"])
        self.assertIn("说了上面这句", plan["局面"])
        off = KajuStyle(Context(), {"rewrite": {"enable": False}})
        self.assertEqual(await off.say_from_card(ev, points=["x"]), "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
