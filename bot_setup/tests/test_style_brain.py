"""主模型当大脑（rewrite.main_role = "brain"，2026-11-17 兄长定）。

查这几件事：
- swap_persona 只换人设那一段（扮佳树说话的规矩），技能、别的材料不动；找不到人设就放最前面
- 请求钩子：开着才换、记上 _ks_brain；关着 / 这一轮不重说不动
- 回复：大脑的 JSON → 卡（要说到的里是标签）→ 写手；不再调模型摘卡；表情标记照样接在后面；核对拿“大脑定下的意思”当草稿
- 解析不了 → 当草稿照旧摘卡；群里“不回”：planner_skip=group 才真不说（历史里不留 JSON）
- 问句把关不碰大脑那一轮

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_brain.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]
os.environ["STUB_DATA"] = tempfile.mkdtemp()

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core.senses import omni  # noqa: E402
from kaju_core.voice import brain, card  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

SYS = ("You are running in Safe Mode.\n\n# Persona Instructions\n\n你叫温水佳树，初三。\n1. 默认中文\n\n"
       "## Skills\n\n- documents\n\n【佳树的日记】昨天读了小说")
PLAN = {"回不回": "回", "局面": "兄长大人问她明晚有没有空，轮到她回。", "要接住的": "兄长大人问明晚有没有空",
        "要表达的": ["回答：明晚有空", "反问：找她什么事"], "背景": [], "情绪": "开心"}
V4 = {"enable": True, "card_format": "v4", "card_model": "kaju-writer-p6-8b-r7k", "shadow_plan": False, "main_role": "brain"}
GEM = json.dumps({"局面": "兄长大人在问，轮到佳树回。", "要说到的": ["佳树明晚有空"]}, ensure_ascii=False)


class Pure(unittest.TestCase):
    def test_swap_persona(self):
        s = brain.swap_persona(SYS)
        self.assertNotIn("你叫温水佳树，初三。", s)
        self.assertNotIn("# Persona Instructions", s)
        self.assertTrue(s.startswith("You are running in Safe Mode.\n\n# 你的任务\n\n你是佳树"))
        self.assertIn("在线时你手里有工具", s)
        self.assertIn("## Skills\n\n- documents", s)
        self.assertIn("【佳树的日记】昨天读了小说", s)
        self.assertTrue(brain.swap_persona("只有材料").startswith(brain.PLAN_BRAIN))

    def test_card_and_reference(self):
        c = brain.card_of("私聊", "兄长大人", PLAN, "心情：开心6")
        self.assertIn("局面：兄长大人问她明晚有没有空，轮到她回。要接住的：兄长大人问明晚有没有空\n", c)
        self.assertIn("要说到的：回答：明晚有空；反问：找她什么事\n心情：开心6", c)
        r = brain.reference(PLAN)
        self.assertIn("她要表达的：回答：明晚有空；反问：找她什么事", r)

    def test_parse_quotes(self):
        raw = '```json\n{"回不回": "回", "局面": "兄长大人提醒佳树"逻辑条条"的话题过去了", "要表达的": ["认错：理解错了"]}\n```'
        p = brain.parse(raw)
        self.assertEqual(p["要表达的"], ["认错：理解错了"])
        self.assertIsNone(brain.parse("兄长大人明晚有空哦"))
        self.assertEqual(brain.parse('{"局面": "x", "表情包": "&&affection&&"}')["表情包"], "affection")
        self.assertNotIn("表情包", brain.parse('{"局面": "x", "表情包": "无"}'))
        self.assertNotIn("表情包", brain.parse('{"局面": "x"}'))


class Flow(unittest.IsolatedAsyncioTestCase):
    def make(self, cfg=None, writes=None):
        style = KajuStyle(Context(), {"rewrite": {**V4, **(cfg or {})}})
        self.writes, self.bodies, self.calls, self.guards = list(writes or []), [], [], []

        async def fake_text(system, user, timeout=20, thinking="low"):
            self.calls.append(system)
            return GEM, 1
        self.real_text, omni.text = omni.text, fake_text

        async def local_chat(system, user):
            self.bodies.append((system, user))
            return self.writes.pop(0)

        async def guard(said, draft, new, title="", ctx=None):
            self.guards.append(draft)
            return (False, "", True)
        style._local_chat, style._guard = local_chat, guard
        style._mood_line = lambda: "心情：开心6"
        style._rewrite_on = lambda event: True
        return style

    def tearDown(self):
        omni.text = self.real_text

    async def reply(self, style, text, group=False, brain_turn=True):
        ev = AstrMessageEvent(text="明晚有空吗", group="222222222" if group else "")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：明晚有空吗"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        if brain_turn:
            ev.set_extra("_ks_brain", True)
        resp = LLMResponse(text)
        await style.rewrite_reply(ev, resp)
        return ev, resp.completion_text

    async def test_request_swap(self):
        style = self.make()
        ev = AstrMessageEvent(text="在吗")
        req = SimpleNamespace(system_prompt=SYS)
        await style.brain_request(ev, req)
        self.assertTrue(ev.get_extra("_ks_brain"))
        self.assertIn("# 你的任务", req.system_prompt)
        off = self.make({"main_role": "draft"})
        ev2, req2 = AstrMessageEvent(text="在吗"), SimpleNamespace(system_prompt=SYS)
        await off.brain_request(ev2, req2)
        self.assertFalse(ev2.get_extra("_ks_brain"))
        self.assertEqual(req2.system_prompt, SYS)
        style._rewrite_on = lambda event: False  # 这一轮不重说：不换
        ev3, req3 = AstrMessageEvent(text="在吗"), SimpleNamespace(system_prompt=SYS)
        await style.brain_request(ev3, req3)
        self.assertEqual(req3.system_prompt, SYS)

    async def test_plan_to_writer(self):
        style = self.make(writes=["明晚有空的兄长大人！找佳树有什么事吗？"])
        ev, out = await self.reply(style, json.dumps(PLAN, ensure_ascii=False) + "&&happy&&")
        self.assertEqual(self.calls, [])  # 不再摘卡
        system, user = self.bodies[0]
        self.assertEqual(system, card.SYSTEM_V4)
        self.assertIn("要说到的：回答：明晚有空；反问：找她什么事\n心情：开心6", user)
        self.assertEqual(out, "明晚有空的兄长大人！找佳树有什么事吗？\n&&happy&&")
        self.assertEqual(self.guards, [brain.reference(PLAN)])
        self.assertEqual(ev.get_extra("kaju_style_rewritten")["new"].split("\n")[0], "明晚有空的兄长大人！找佳树有什么事吗？")

    async def test_unparsable_falls_back(self):
        style = self.make(writes=["佳树明晚有空哦"])
        _, out = await self.reply(style, "兄长大人明晚有空哦，找佳树什么事呀")
        self.assertEqual(out, "佳树明晚有空哦")
        self.assertEqual(self.calls, [card.EXTRACT_V4])

    async def test_group_skip(self):
        quiet = json.dumps({**PLAN, "回不回": "不回"}, ensure_ascii=False)
        style = self.make({"planner_skip": "group"}, writes=["x"])
        ev, out = await self.reply(style, quiet, group=True)
        self.assertEqual(out, "")
        self.assertEqual(self.bodies, [])
        self.assertEqual(ev.get_extra("kaju_style_rewritten")["new"], "")
        style = self.make(writes=["佳树明晚有空"])  # 默认 log：照样回
        _, out = await self.reply(style, quiet, group=True)
        self.assertEqual(out, "佳树明晚有空")

    async def test_draft_mode_untouched(self):
        style = self.make({"main_role": "draft"}, writes=["佳树明晚有空哦"])
        _, out = await self.reply(style, "兄长大人明晚有空哦", brain_turn=False)
        self.assertEqual(out, "佳树明晚有空哦")
        self.assertEqual(self.calls, [card.EXTRACT_V4])

    async def test_replyer_api(self):
        """11-18：rewrite.replyer = api → 大脑的指导交给 API 回复器；回复器没写成就退回本地写手；默认 local 不碰回复器。"""
        from kaju_core.voice import replyer
        seen = []

        async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
            seen.append((kind, title, plan["要表达的"], said))
            return self.api_out, {"model": "测试", "secs": 0.1, "examples": [], "errors": []}
        real = replyer.reply
        replyer.reply = fake_reply
        try:
            self.api_out = "明晚有空的兄长大人！是有什么事吗？"
            style = self.make({"replyer": "api"}, writes=["本地写手写的"])
            _, out = await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertEqual(out, "明晚有空的兄长大人！是有什么事吗？")
            self.assertEqual(seen[0], ("私聊", "兄长大人", ["回答：明晚有空", "反问：找她什么事"], "兄长大人：明晚有空吗"))
            self.assertEqual(self.bodies, [])
            self.assertEqual(self.guards, [brain.reference(PLAN)])  # 核对照旧
            self.api_out = ""  # 回复器没写成 → 本地写手
            style = self.make({"replyer": "api"}, writes=["本地写手写的"])
            _, out = await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertEqual(out, "本地写手写的")
            seen.clear()
            style = self.make(writes=["本地写手写的"])  # 默认 local
            _, out = await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertEqual((out, seen), ("本地写手写的", []))
            # 11-18 照 anima：心情底色直接给回复器（rewrite.replyer_mood，默认开）
            plans = []

            async def keep_plan(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
                plans.append(plan)
                return "好呀", {"model": "测试", "secs": 0.1, "examples": [], "errors": []}
            replyer.reply = keep_plan
            style = self.make({"replyer": "api"}, writes=["本地写手写的"])
            style._mood_words = lambda **kw: "心情很低落、有点累"
            await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertEqual(plans[-1].get("底色"), "心情很低落、有点累")
            self.assertNotIn("底色", PLAN)  # 不改大脑原来那份
            style = self.make({"replyer": "api", "replyer_mood": False}, writes=["本地写手写的"])
            style._mood_words = lambda **kw: "心情很低落、有点累"
            await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertNotIn("底色", plans[-1])
            style = self.make({"replyer": "api"}, writes=["本地写手写的"])
            style._mood_words = lambda **kw: ""  # 读不到心情：不加这一行
            await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertNotIn("底色", plans[-1])
            self.assertIn("心情底色：心情很低落", replyer.plan_text({"局面": "x", "要表达的": [], "底色": "心情很低落"}))
            # 11-18 对方需要（anima 的 attunement）：大脑出、回复器看得到；没有就不写这一行
            p = brain.parse('{"局面": "他考砸了", "要接住的": "他说考得不好", "对方需要": "倾听：他考砸了很沮丧", "要表达的": ["安慰：陪着他"]}')
            self.assertEqual(p["对方需要"], "倾听：他考砸了很沮丧")
            self.assertIn("对方需要：倾听：他考砸了很沮丧", replyer.plan_text(p))
            self.assertNotIn("对方需要", replyer.plan_text({"局面": "x", "要表达的": []}))
            self.assertIn("对方需要", brain.PLAN_BRAIN)
            self.assertNotIn("对方需要", brain.PLAN_BRAIN.replace(brain.NEED_PART, "").replace(brain.NEED_KEY, ""))
            self.assertNotIn("心情底色", replyer.plan_text({"局面": "x", "要表达的": []}))
        finally:
            replyer.reply = real

    async def test_emoji_separate(self):
        """11-18：rewrite.emoji = separate → 表情包说明不给大脑；话写好以后单独挑一类放进 found_emotions；骰子没中不挑。"""
        block = ("<!-- meme_manager_prompt:start -->\n[表情图片工具]\n说明\n\n[可用分类：分类键 - 用途]\n"
                 "happy - 开心\n\nsad - 难过\n\n[亲手添加的表情]\n这些分类里有：happy。\n\n[内部选图资料]\n别说\n<!-- meme_manager_prompt:end -->")
        style = self.make({"emoji": "separate"})
        ev, req = AstrMessageEvent(text="在吗"), SimpleNamespace(system_prompt=SYS + "\n\n" + block)
        await style.brain_request(ev, req)
        self.assertNotIn("meme_manager_prompt", req.system_prompt)
        self.assertNotIn(brain.MEME_LINE.strip(), req.system_prompt)
        self.assertEqual(ev.get_extra("_ks_meme_block"), block)
        asked = []

        async def slot_model(slot, model="", who=""):
            return "emoji_model"

        async def generate(pid, prompt, system="", timeout=None):
            asked.append((pid, system, prompt))
            return '{"配": true, "分类": "happy"}'
        style.body.slot_model, style.body.generate = slot_model, generate
        self.writes = ["明晚有空的兄长大人！"]
        ev.set_extra("_ks_rw_ctx", ["兄长大人：明晚有空吗"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        resp = LLMResponse(json.dumps(PLAN, ensure_ascii=False))
        await style.rewrite_reply(ev, resp)
        self.assertEqual(ev.get_extra("found_emotions"), ["happy"])
        self.assertEqual(asked[0][0], "emoji_model")
        self.assertIn("happy - 开心", asked[0][1])
        self.assertIn("她这一句：\n明晚有空的兄长大人！", asked[0][2])
        # 骰子没中：不问模型
        style2 = self.make({"emoji": "separate"}, writes=["佳树明晚有空"])
        style2.body.slot_model, style2.body.generate = slot_model, generate
        ev2 = AstrMessageEvent(text="明晚有空吗")
        for k, v in (("_ks_rw_ctx", ["兄长大人：明晚有空吗"]), ("_ks_rw_title", "兄长大人"), ("_ks_brain", True),
                     ("_ks_meme_block", block), ("meme_manager_legacy_probability_hit", False)):
            ev2.set_extra(k, v)
        n = len(asked)
        await style2.rewrite_reply(ev2, LLMResponse(json.dumps(PLAN, ensure_ascii=False)))
        self.assertEqual((len(asked), ev2.get_extra("found_emotions")), (n, None))
        # 11-19：大脑知道她能发表情包；点名了就算骰子没中也发、不问模型；点名的分类不存在就照常
        self.assertIn("她能发表情包", req.system_prompt)
        self.assertIn("  happy - 开心", req.system_prompt)
        self.assertIn('"表情包": "分类键"', req.system_prompt)
        style3 = self.make({"emoji": "separate"}, writes=["给兄长大人发一张"])
        style3.body.slot_model, style3.body.generate = slot_model, generate
        ev3 = AstrMessageEvent(text="发一张开心的表情包")
        for k, v in (("_ks_rw_ctx", ["兄长大人：发一张开心的表情包"]), ("_ks_rw_title", "兄长大人"), ("_ks_brain", True),
                     ("_ks_meme_block", block), ("meme_manager_legacy_probability_hit", False)):
            ev3.set_extra(k, v)
        n = len(asked)
        await style3.rewrite_reply(ev3, LLMResponse(json.dumps({**PLAN, "表情包": "happy"}, ensure_ascii=False)))
        self.assertEqual(ev3.get_extra("found_emotions"), ["happy"])
        self.assertIs(ev3.get_extra("meme_manager_legacy_probability_hit"), True)
        self.assertEqual(len(asked), n)
        style4 = self.make({"emoji": "separate"}, writes=["给兄长大人发一张"])
        style4.body.slot_model, style4.body.generate = slot_model, generate
        ev4 = AstrMessageEvent(text="发一张")
        for k, v in (("_ks_rw_ctx", ["兄长大人：发一张"]), ("_ks_rw_title", "兄长大人"), ("_ks_brain", True),
                     ("_ks_meme_block", block)):
            ev4.set_extra(k, v)
        await style4.rewrite_reply(ev4, LLMResponse(json.dumps({**PLAN, "表情包": "nope"}, ensure_ascii=False)))
        self.assertEqual(ev4.get_extra("found_emotions"), ["happy"])  # 不认识的点名 → 照常让表情包那一格挑

    async def test_replyer_own_ctx(self):
        """11-18：回复器有自己那份前文（群聊 50 行 / 私聊 20 行）就整份给它；没有就用写手那份、只看最后 10 行。"""
        from kaju_core.voice import replyer
        seen = []

        async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
            seen.append((list(ctx), ctx_lines))
            return "好的兄长大人", {"model": "测试", "secs": 0.1, "examples": [], "errors": []}
        real = replyer.reply
        replyer.reply = fake_reply
        try:
            long_lines = [f"20:{i:02d} 群友{i}：第{i}句" for i in range(50)]
            style = self.make({"replyer": "api"}, writes=["本地"])
            ev = AstrMessageEvent(text="明晚有空吗")
            for k, v in (("_ks_rw_ctx", ["兄长大人：明晚有空吗"]), ("_ks_rw_title", "兄长大人"), ("_ks_brain", True),
                         ("_ks_rw_replyer", long_lines)):
                ev.set_extra(k, v)
            await style.rewrite_reply(ev, LLMResponse(json.dumps(PLAN, ensure_ascii=False)))
            self.assertEqual(seen[0], (long_lines, 0))
            seen.clear()
            style = self.make({"replyer": "api"}, writes=["本地"])
            _, out = await self.reply(style, json.dumps(PLAN, ensure_ascii=False))
            self.assertEqual(seen[0][1], 10)  # 没有自己那份：用写手那份、最后 10 行
        finally:
            replyer.reply = real
        u = replyer.user_prompt("群聊", "兄长大人", [f"第{i}行" for i in range(30)], PLAN, ctx_lines=0)
        self.assertIn("第0行", u)
        u = replyer.user_prompt("群聊", "兄长大人", [f"第{i}行" for i in range(30)], PLAN)
        self.assertNotIn("第0行\n", u)
        self.assertIn("第29行", u)

    async def test_asks_check_skips_brain(self):
        style = self.make()
        ev = AstrMessageEvent(text="明晚有空吗")
        ev.set_extra("_ks_asks", ["兄长大人：明晚有空吗"])
        ev.set_extra("_ks_brain", True)
        resp = LLMResponse(json.dumps(PLAN, ensure_ascii=False))
        before = resp.completion_text
        await style.asks_check(ev, resp)
        self.assertEqual(resp.completion_text, before)




class CharacterBlock(unittest.TestCase):
    def test_character_block(self):
        """11-18：“她是什么样的人”只取第一个 ## 之前的条目，开关关着时不加。"""
        from kaju_core.voice import brain
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "character.md")
            open(f, "w", encoding="utf-8").write("# 标题\n说明\n\n- 爱操心\n- 被夸会得意\n\n## 没放进来的\n- 不该出现\n")
            c = brain.character(f)
            self.assertIn("- 爱操心", c)
            self.assertIn("- 被夸会得意", c)
            self.assertNotIn("不该出现", c)
            self.assertEqual(brain.plan_system(False, f), brain.PLAN_BRAIN)
            self.assertIn("爱操心", brain.plan_system(True, f))
            self.assertEqual(brain.character(os.path.join(d, "没有.md")), "")


class ReplyerPrompt(unittest.TestCase):
    def test_prompt_and_pick(self):
        from kaju_core.voice import replyer
        plan = {"局面": "兄长问她在不在。", "要接住的": "兄长问她在不在", "要表达的": ["回答：一直都在"], "情绪": "开心"}
        u = replyer.user_prompt("私聊", "兄长大人", ["10:31 兄长大人：中午好", "14:49 兄长大人：小佳树在吗"], plan)
        self.assertIn("这一轮对方说：\n14:49 兄长大人：小佳树在吗", u)
        self.assertIn("要表达的：回答：一直都在", u)
        ex = [{"situation": "哈喽佳树在吗", "line": "在的兄长大人！", "src": "owner"}]
        s = replyer.system_prompt(ex, ["- 爱操心"])
        self.assertIn("她是什么样的人：\n- 爱操心", s)
        self.assertIn("当对方说“哈喽佳树在吗”时，她说：“在的兄长大人！”", s)
        self.assertNotIn("参考她以前", replyer.system_prompt([], []))
        bank = [{"line": f"原作{i}", "src": "novel", "vec": [1, 0]} for i in range(4)] + [{"line": "线上", "src": "curated", "vec": [0.9, 0.1]}]
        got = replyer.pick(bank, [1, 0], k=4)
        self.assertEqual(sum(b["src"] == "novel" for b in got), 2)  # 原作最多 2 句
        # 11-19：太不像的不放；挑例子只拿对方这句，去掉发言人标注和称呼
        far = [{"line": "远的", "src": "curated", "vec": [0, 1]}, {"line": "近的", "src": "curated", "vec": [1, 0]}]
        self.assertEqual([b["line"] for b in replyer.pick(far, [1, 0], k=4, floor=0.5)], ["近的"])
        self.assertEqual(replyer.example_query("[发言人：林一，QQ 111111111] 兄长大人问佳树配置"), "问配置")
        self.assertEqual(replyer.clean("“在的兄长大人！”"), "在的兄长大人！")
        self.assertEqual(replyer.kind_of("场合：群聊\n对象：女王大人"), "群聊")

    def test_group_tone_has_no_clingy_word(self):
        # 11-19：群聊的心情底色不带“想黏人 / 想撒娇”那一维，私聊照旧
        from kaju_core import parts
        snap = type("Heart", (), {"mood_snapshot": lambda self: {"mood": {"joy": 0.85, "energy": 0.6, "stress": 0.1, "warm": 0.8}}})()
        parts.register("test_heart", snap)
        try:
            style = KajuStyle(Context(), {"rewrite": {}})
            self.assertIn("黏人", style._mood_words())
            self.assertNotIn("黏人", style._mood_words(group=True))
            self.assertIn("特别开心", style._mood_words(group=True))
        finally:
            parts.unregister("test_heart", snap)



class EmojiPick(unittest.TestCase):
    def test_parse_block(self):
        from kaju_core.voice import emoji
        block = ("<!-- meme_manager_prompt:start -->\n[可用分类：分类键 - 用途]\nhappy - 开心\n\n爱丽丝 - 立绘\n\n"
                 "[亲手添加的表情]\n优先 happy。\n\n[内部]\nx\n<!-- meme_manager_prompt:end -->")
        rest, got = emoji.cut_block("前面\n\n" + block + "\n后面")
        self.assertEqual(rest, "前面\n后面")
        cats = emoji.categories(got)
        self.assertEqual(cats, {"happy": "开心", "爱丽丝": "立绘"})
        self.assertEqual(emoji.own_note(got), "优先 happy。")
        self.assertEqual(emoji.parse('{"配": true, "分类": "happy"}', cats), "happy")
        self.assertEqual(emoji.parse('{"配": true, "分类": "nope"}', cats), "")
        self.assertEqual(emoji.parse('{"配": false}', cats), "")
        self.assertEqual(emoji.cut_block("没有说明"), ("没有说明", ""))


class GroupNotes(unittest.TestCase):
    def test_adapt_group_notes(self):
        """11-18：大脑模式下插话 / 接着聊的长说明换成一行“这一轮怎么来的”；别的材料不动；大脑规则写了谁才算在跟她说。"""
        chime = ("【插话模式】这次没有人叫你，是你自己看到群里在聊天，想插一句。\n- 不要只挑最后一句复述\n"
                 "- 如果你插不上话……就只输出 [SKIP]\n- 哆啦a梦学姐 刚才在跟 李四学长 说话（互相 @ / 引用过），TA 话里的「你」多半指 李四学长。")
        out = brain.adapt_group_notes("材料\n\n" + chime + "\n\n【别的】留着")
        self.assertIn("【这一轮怎么来的】没人叫她", out)
        self.assertIn("哆啦a梦学姐 刚才在跟 李四学长 说话", out)
        self.assertNotIn("[SKIP]", out)
        self.assertTrue(out.endswith("【别的】留着"))
        follow = "【可能在接着跟你聊】你刚才在群里和 哆啦a梦学姐 说过话，TA 现在又发了消息：「和他说听不懂了」，没有 @你。\n- 拿不准时就 [SKIP]。"
        out = brain.adapt_group_notes("材料\n\n" + follow)
        self.assertIn("哆啦a梦学姐 刚才和她说过话，现在又发了「和他说听不懂了」", out)
        self.assertNotIn("[SKIP]", out)
        self.assertEqual(brain.adapt_group_notes("没有这些说明"), "没有这些说明")
        self.assertIn("谁在跟她说（群聊）", brain.PLAN_BRAIN)
        self.assertIn("没叫你", brain.PLAN_BRAIN)


class SinceMaiBot(unittest.TestCase):
    """11-18 晚对照 MaiBot 改的三处：重想、回复器的“这一轮怎么来的”、群聊上下文的时钟。"""

    def test_how_came(self):
        self.assertEqual(brain.how_came("材料\n\n【插话模式】这次没有人叫你"), "插话")
        self.assertEqual(brain.how_came(brain.adapt_group_notes("材料\n\n【插话模式】这次没有人叫你")), "插话")
        self.assertEqual(brain.how_came("【可能在接着跟你聊】你刚才在群里和 A 说过话，TA 现在又发了消息：「x」"), "接着聊")
        self.assertEqual(brain.how_came("没有这些"), "")

    def test_fix_clock(self):
        t = "[哆啦a梦(叫TA哆啦a梦学姐)/20:24:14]:  太垃圾了\n[李四/01:10:00]:  x"
        out = brain.fix_clock(t, -3 * 3600)
        self.assertIn("/17:24]:  太垃圾了", out)
        self.assertIn("/22:10]:  x", out)  # 跨零点
        self.assertEqual(brain.fix_clock(out, -3 * 3600), out)  # 存回历史再看到不会再挪
        self.assertEqual(brain.fix_clock(t, 0), t)

    def test_replan_prompt(self):
        p = brain.replan_prompt("[发言人：哆啦a梦] 讲话", [("user", "前面那句"), ("assistant", "她上一句")],
                                ["17:24 哆啦a梦学姐：和他说听不懂了"])
        self.assertIn("【前面的对话】\n群里：前面那句\n佳树（你）：她上一句", p)
        self.assertIn("【这一轮】\n[发言人：哆啦a梦] 讲话", p)
        self.assertIn("【你想的时候群里又来了】\n17:24 哆啦a梦学姐：和他说听不懂了", p)

    def test_replyer_how(self):
        from kaju_core.voice import replyer
        u = replyer.user_prompt("群聊", "哆啦a梦学姐", ["哆啦a梦学姐：讲话"], PLAN, how="插话")
        self.assertIn("引起了她的注意（没人叫她", u)
        self.assertNotIn("这一轮对方说", u)
        self.assertNotIn("对象：", u)
        u = replyer.user_prompt("群聊", "兄长大人", ["兄长大人：佳树在吗"], PLAN)
        self.assertIn("这一轮对方说：\n兄长大人：佳树在吗", u)
        self.assertIn("对象：兄长大人", u)


class Replan(unittest.IsolatedAsyncioTestCase):
    def make(self, new, answer):
        style = KajuStyle(Context(), {"rewrite": {**V4, "replyer": "api"}})
        self.asked = []

        async def model_id(model="", who=""):
            return "main"

        async def generate(pid, prompt, system="", timeout=None):
            self.asked.append((pid, prompt, system))
            return answer
        style.body.model_id, style.body.generate = model_id, generate
        style._arrived_since = lambda event: new
        style._address_of = lambda qq, name: name + "学姐"
        return style

    async def test_replan_changes_plan_and_ctx(self):
        from kaju_core.voice import mind as m
        again = {"回不回": "不回", "局面": "哆啦a梦在跟模型说话，不是叫佳树"}
        style = self.make([{"t": "17:24", "u": "2", "n": "哆啦a梦", "x": "和他说听不懂了"}],
                          json.dumps(again, ensure_ascii=False))
        ev = AstrMessageEvent(text="讲话", group="222222222")
        ev.set_extra("_ks_brain_req", SimpleNamespace(system_prompt="大脑", prompt="[发言人：哆啦a梦] 讲话",
                                                      contexts=[], extra_user_content_parts=[]))
        tok = m._REPLYER_CTX.set(["17:24 哆啦a梦学姐：讲话"])
        try:
            plan = await style._replan(ev, PLAN)
            self.assertEqual(plan["回不回"], "不回")
            self.assertEqual(m._REPLYER_CTX.get()[-1], "17:24 哆啦a梦学姐：和他说听不懂了")
        finally:
            m._REPLYER_CTX.reset(tok)
        self.assertEqual(ev.get_extra("_ks_replan_ctx"), ["哆啦a梦学姐：和他说听不懂了"])
        self.assertEqual(self.asked[0][2], "大脑")
        self.assertIn("和他说听不懂了", self.asked[0][1])

    async def test_no_new_or_bad_answer_keeps_plan(self):
        style = self.make([], "{}")
        ev = AstrMessageEvent(text="讲话", group="222222222")
        ev.set_extra("_ks_brain_req", SimpleNamespace(system_prompt="", prompt="", contexts=[]))
        self.assertIs(await style._replan(ev, PLAN), PLAN)
        self.assertEqual(self.asked, [])
        style = self.make([{"t": "17:24", "u": "2", "n": "哆啦a梦", "x": "和他说"}], "不是 JSON")
        ev.set_extra("_ks_brain_req", SimpleNamespace(system_prompt="", prompt="", contexts=[]))
        self.assertIs(await style._replan(ev, PLAN), PLAN)
        private = AstrMessageEvent(text="讲话")
        self.assertIs(await style._replan(private, PLAN), PLAN)  # 私聊不重想

    async def test_request_fixes_clock(self):
        style = KajuStyle(Context(), {"rewrite": {**V4}})
        style._rewrite_on = lambda event: True
        style._clock_shift = lambda: -3 * 3600
        part = SimpleNamespace(text="[哆啦a梦/20:24:14]:  太垃圾了")
        req = SimpleNamespace(system_prompt=SYS + "\n\n【插话模式】这次没有人叫你", extra_user_content_parts=[part],
                              contexts=[{"role": "user", "content": "[李四/19:37:51]:  gpt out"}])
        ev = AstrMessageEvent(text="讲话", group="222222222")
        await style.brain_request(ev, req)
        self.assertEqual(part.text, "[哆啦a梦/17:24]:  太垃圾了")
        self.assertEqual(req.contexts[0]["content"], "[李四/16:37]:  gpt out")
        self.assertEqual(ev.get_extra("_ks_how"), "插话")
        self.assertIs(ev.get_extra("_ks_brain_req"), req)


class RichLog(unittest.TestCase):
    """11-18 晚：聊天记录记引用 / @她 / 图片描述，回复器那份带上、她自己标“佳树(你)”。"""

    def test_marked(self):
        from kaju_core.voice import longctx, replyer
        who = lambda qq, name: {"1": "哆啦a梦学姐", "2": "兄长大人"}.get(qq, name)  # noqa: E731
        r = {"u": "2", "n": "x", "x": "没叫你吧", "q": {"u": "1", "n": "哆啦a梦", "x": "讲话"}}
        self.assertEqual(longctx.marked(r, who), "（回复哆啦a梦学姐：讲话）没叫你吧")
        r = {"u": "1", "x": "[图片]", "cap": ["一只生气的仓鼠表情包"], "am": True}
        self.assertEqual(longctx.marked(r, who), "@佳树 [图片：一只生气的仓鼠表情包]")
        r = {"u": "2", "x": "看这个", "cap": ["游戏截图"], "q": {"u": "self", "n": "佳树", "x": "女王大人怎么了？"}}
        self.assertEqual(longctx.marked(r, who, replyer.ME_LABEL), "（回复佳树(你)：女王大人怎么了？）看这个 [图片：游戏截图]")
        lines = longctx.from_log([{"d": "2026-11-18", "t": "17:24", "u": "self", "x": "女王大人怎么了？"},
                                  {"d": "2026-11-18", "t": "17:25", "u": "1", "x": "[图片]", "cap": ["猫"]}],
                                 who, me=replyer.ME_LABEL, rich=True)
        self.assertEqual(lines, ["【11-18】", "17:24 佳树(你)：女王大人怎么了？", "17:25 哆啦a梦学姐：[图片：猫]"])
        plain = longctx.from_log([{"d": "2026-11-18", "t": "17:25", "u": "1", "x": "[图片]", "cap": ["猫"]}], who)
        self.assertEqual(plain[-1], "17:25 哆啦a梦学姐：[图片]")  # 不开 rich 和原来一样
        u = replyer.user_prompt("群聊", "兄长大人", lines, PLAN, ctx_lines=0)
        self.assertIn("标着“佳树(你)”的是你自己说过的话", u)
        self.assertNotIn("标着", replyer.user_prompt("私聊", "兄长大人", ["兄长大人：在吗"], PLAN))

    def test_diary_records_marks_and_captions(self):
        import logging
        from kaju_core.life import diary as dmod
        d = dmod.Diary(SimpleNamespace(log=logging.getLogger("t")), lambda: {}, tempfile.mkdtemp(),
                       lambda: __import__("datetime").datetime(2026, 11, 18, 17, 25), lambda now=None: "2026-11-18",
                       lambda day: None)
        Reply = type("Reply", (), {})
        At = type("At", (), {})
        q, a = Reply(), At()
        q.sender_id, q.sender_nickname, q.message_str = "42", "佳树小号", "女王大人怎么了？"
        a.qq = "42"
        ev = AstrMessageEvent(text="看这个", group="222222222")
        ev.get_self_id = lambda: "42"
        ev.get_sender_id = lambda: "1"
        ev.get_sender_name = lambda: "哆啦a梦"
        ev.get_messages = lambda: [q, a]

        async def no_group_name(event, gid):
            return None
        d._remember_group_name = no_group_name
        import asyncio
        asyncio.run(d.log_incoming(ev))
        dmod.note_caption(ev, "一只生气的仓鼠")
        r = d.recent("g222222222", 5)[-1]
        self.assertEqual(r["q"], {"u": "self", "n": "佳树", "x": "女王大人怎么了？"})
        self.assertTrue(r["am"])
        self.assertEqual(r["cap"], ["一只生气的仓鼠"])
        self.assertEqual(r["x"], "看这个")

        # 11-19：AstrBot 群聊上下文先描述图、kaju_life 后记这条 → 描述先挂着，记好再写进去
        ev2 = AstrMessageEvent(text="", group="222222222")
        ev2.get_self_id = lambda: "42"
        ev2.get_sender_id = lambda: "1"
        ev2.get_sender_name = lambda: "哆啦a梦"
        ev2.get_messages = lambda: [type("Image", (), {})()]
        dmod.note_caption(ev2, "GTA6 的游戏截图")
        asyncio.run(d.log_incoming(ev2))
        r = d.recent("g222222222", 5)[-1]
        self.assertEqual((r["x"], r["cap"]), ("[图片]", ["GTA6 的游戏截图"]))
        self.assertIsNone(ev2.get_extra(dmod.PENDING_CAPS))


class JudgeAndLocalOff(unittest.IsolatedAsyncioTestCase):
    def make(self, cfg, judge_out="", replies=()):
        style = KajuStyle(Context(), {"rewrite": {**V4, "replyer": "api", **cfg}})
        self.gen, self.local, self.replies = [], [], list(replies)

        async def model_id(model="", who=""):
            return "fast"

        async def generate(pid, prompt, system="", timeout=None):
            self.gen.append(prompt)
            return judge_out
        style.body.model_id, style.body.generate = model_id, generate

        async def local_chat(system, user):
            self.local.append(user)
            return "本地写手的话"
        style._local_chat = local_chat
        return style

    async def test_judge_says_no(self):
        style = self.make({}, '{"回不回": "不回", "为什么": "哆啦a梦在跟 AI 说话"}')
        ev = AstrMessageEvent(text="讲话", group="222222222")
        ev.set_extra("_ks_how", "插话")
        plan = await style._action_judge(ev, PLAN, ["哆啦a梦学姐：讲话"])
        self.assertEqual(plan["回不回"], "不回")
        self.assertIn("把关：哆啦a梦在跟 AI 说话", plan["局面"])
        self.assertIn("没人叫她", self.gen[0])
        called = AstrMessageEvent(text="佳树在吗", group="222222222")  # 被叫到的不问
        self.assertIs(await style._action_judge(called, PLAN, []), PLAN)
        self.assertEqual(len(self.gen), 1)
        ok = self.make({}, '{"回不回": "回", "为什么": "在聊她知道的"}')
        self.assertIs(await ok._action_judge(ev, PLAN, []), PLAN)
        off = self.make({"action_judge": False}, '{"回不回": "不回"}')
        self.assertIs(await off._action_judge(ev, PLAN, []), PLAN)

    def test_judge_parse_and_rules(self):
        # 11-19：模型把键写成形近字，原来认不出来就照常回
        self.assertEqual(brain.parse_judge('{"囘丕囘": "回", "为什么": "接话自然"}'), ("回", "接话自然"))
        self.assertEqual(brain.parse_judge('{"回不回": "丕囘", "为什么": "只是附和"}'), ("不回", "只是附和"))
        self.assertEqual(brain.parse_judge('{"回不回": "不回"}'), ("不回", ""))
        self.assertEqual(brain.parse_judge('{"为什么": "回"}'), ("", "回"))
        self.assertEqual(brain.parse_judge("看不懂"), ("", ""))
        # 插话没自己的东西（附和 / 复述 / 不知道）→ 不回：大脑和把关都写着
        self.assertIn("只是附和", brain.judge_prompt("插话", [], ""))
        self.assertIn("她自己插话（没人叫她）", brain.PLAN_BRAIN)

    async def test_local_writer_off(self):
        from kaju_core.voice import replyer
        seen = []

        async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
            seen.append(plan)
            return ("回复器写的", {"errors": []}) if self.replies.pop(0) else ("", {"errors": ["都挂了"]})
        real = replyer.reply
        replyer.reply = fake_reply
        try:
            card_text = card.render_v4("私聊", "兄长大人", {"局面": "兄长大人在吃饭。要接住的：他问她吃了没", "要说到的": ["回答：吃过了"]})
            style = self.make({"local_writer": False}, replies=[True, False])
            self.assertEqual(await style._write_from_card(["兄长大人：吃了没"], card_text, "", "兄长大人"), "回复器写的")
            self.assertEqual(seen[0]["要表达的"], ["回答：吃过了"])
            self.assertEqual(seen[0]["要接住的"], "他问她吃了没")
            self.assertEqual(await style._write_from_card(["兄长大人：吃了没"], card_text, "", "兄长大人"), "")
            self.assertEqual(self.local, [])  # 本地写手一次也没叫
            on = self.make({}, replies=[])
            self.assertEqual(await on._write_from_card(["兄长大人：吃了没"], card_text, "", "兄长大人"), "本地写手的话")
        finally:
            replyer.reply = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
