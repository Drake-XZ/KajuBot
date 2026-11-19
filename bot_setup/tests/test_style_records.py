"""kaju_style 线上重说记录（records.py）：每次重说原样记一行，不改重说的行为。

    <venv>\\Scripts\\python.exe -I D:\\JiashuBot\\bot_setup\\tests\\test_style_records.py
"""

import glob
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]  # HERE.parent：源码里的 kaju_core
DATA = tempfile.mkdtemp()
os.environ["STUB_DATA"] = DATA

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core.voice import card  # noqa: E402
from kaju_core.voice import records  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

FOLDER = os.path.join(DATA, "astrbot_plugin_kaju_style", "rewrites")
CARD = "要点卡：\n场合：私聊\n对象：兄长大人\n回哪句：我回来了\n情绪：开心\n要点：汤还热着"


def rows():
    out = []
    for p in sorted(glob.glob(os.path.join(FOLDER, "*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            out += [json.loads(x) for x in f if x.strip()]
    return out


def clear():
    for p in glob.glob(os.path.join(FOLDER, "*.jsonl")) + glob.glob(os.path.join(os.path.dirname(FOLDER), "plans", "*.jsonl")):
        os.remove(p)


class RecordTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear()

    def make(self, writer="兄长大人辛苦啦，佳树给你留了热汤哦", guard=(False, "", True), cfg=None):
        # 只写一遍（retry 0）、writer_only 关着（查“没过就发原稿”时记成什么）：抽卡换成假的，写手、核对也是假的
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "card_model": "kaju-writer-p6-8b-r7k", "retry": 0,
                                                  "writer_only": False,
                                                  "shadow_plan": False, **(cfg or {})}})  # 影子规划器只在它自己的测试里开
        self.guard_calls = []

        async def local_chat(system, user):
            if isinstance(writer, Exception):
                raise writer
            return writer

        async def guard_fn(said, draft, new, title="", ctx=None):
            self.guard_calls.append(new)
            if isinstance(guard, Exception):
                raise guard
            return guard

        async def extract(ctx, draft, kind, title, **k):
            return CARD

        style._local_chat, style._extract_card, style._guard = local_chat, extract, guard_fn
        style._rec.install()  # 换了假的写手/核对之后重新包一层
        return style

    async def reply(self, style, draft="兄长大人回来啦，汤还热着。", ctx=("兄长大人：我回来了",), group=""):
        ev = AstrMessageEvent(text="我回来了", group=group)
        if ctx is not None:
            ev.set_extra("_ks_rw_ctx", list(ctx))
            ev.set_extra("_ks_rw_title", "兄长大人")
        resp = LLMResponse(draft)
        await style.rewrite_reply(ev, resp)
        return resp.completion_text

    async def test_used(self):
        out = await self.reply(self.make())
        self.assertEqual(out, "兄长大人辛苦啦，佳树给你留了热汤哦")
        [r] = rows()
        self.assertEqual((r["src"], r["kind"], r["outcome"], r["used"]), ("reply", "私聊", "used", True))
        self.assertEqual((r["draft"], r["final"], r["ctx"], r["said"]),
                         ("兄长大人回来啦，汤还热着。", out, ["兄长大人：我回来了"], "我回来了"))
        w = r["writer"][0]
        self.assertEqual(w["user"], card.write_prompt_v4(["兄长大人：我回来了"], CARD))
        self.assertEqual(w["system_sha"], records._sha(card.SYSTEM_V4))
        self.assertEqual((w["model"], w["out"]), ("kaju-writer-p6-8b-r7k", out))
        self.assertEqual(r["card"][0]["card"], CARD)
        self.assertEqual((r["guard"][0]["bad"], r["guard"][0]["new"]), (False, out))
        self.assertEqual(r["config"]["card_model"], "kaju-writer-p6-8b-r7k")
        self.assertNotIn("_token", r)

    async def test_draft_input_recorded(self):
        """草稿是照什么写的（11-13）：主模型的完整输入存进 draft_inputs，rewrites 那行只记字数和加了哪些提醒。"""
        class Req:
            system_prompt = "你是佳树。\n\n【说具体、说连贯】这一轮在聊作品。\n\n【先回应，别当解说员】先接住。"
            prompt = "我回来了"
            extra_user_content_parts = [type("P", (), {"text": "[Video: 12秒]"})()]
            contexts = [{"role": "user", "content": "在吗"},
                        {"role": "assistant", "content": [{"type": "text", "text": "在的"}, {"type": "image_url"}]}]
            image_urls = ["a.jpg"]
            model = "gemini-3-flash"
            func_tool = None

        ev = AstrMessageEvent(text="我回来了")
        ev.set_extra("_ks_rw_ctx", ["兄长大人：我回来了"])
        ev.set_extra("_ks_rw_title", "兄长大人")
        ev.set_extra("provider_request", type("Bare", (), {"system_prompt": "", "prompt": "插话那条路的那份"})())
        await self.make().draft_request_ref(ev, Req())  # 请求钩子最后记下的那份优先
        await self.make().rewrite_reply(ev, LLMResponse("兄长大人回来啦，汤还热着。"))
        await self.reply(self.make())  # 没有 provider_request：不记这一栏
        r, r2 = rows()
        self.assertEqual(r["draft_input"]["notes"], ["说具体、说连贯", "先回应，别当解说员"])
        self.assertGreater(r["draft_input"]["chars"], 20)
        self.assertNotIn("_draft_in", r)
        self.assertNotIn("draft_input", r2)
        [d] = [json.loads(x) for p in glob.glob(os.path.join(os.path.dirname(FOLDER), "draft_inputs", "*.jsonl"))
               for x in open(p, encoding="utf-8") if x.strip()]
        self.assertEqual(d["t"], r["t"])
        self.assertEqual((d["prompt"], d["extra"], d["images"], d["model"]), ("我回来了", ["[Video: 12秒]"], 1, "gemini-3-flash"))
        self.assertEqual(d["contexts"], [{"role": "user", "text": "在吗"}, {"role": "assistant", "text": "在的[image_url]"}])
        self.assertIn("【说具体、说连贯】", d["system_prompt"])

    async def test_shadow_plan(self):
        """影子规划器（11-14）：有主模型输入就在后台写一份指导存进 plans，只记不发；关掉就不跑。"""
        import asyncio
        from kaju_core.senses import omni
        from kaju_core.voice import shadow
        calls = []

        async def fake_text(system, user, timeout=0):
            calls.append((system, user))
            return '{"局面": "兄长大人说他回来了，轮到佳树回。", "要回应的": "他回来了", "事实": [], "背景": ["汤还热着"]}', 1

        class Req:
            system_prompt = "你是佳树。"
            prompt = "我回来了"
            extra_user_content_parts, contexts, image_urls, model, func_tool = [], [{"role": "user", "content": "在吗"}], [], "", None

        old = omni.text
        omni.text = fake_text
        try:
            for on in (True, False):
                ev = AstrMessageEvent(text="我回来了")
                ev.set_extra("_ks_rw_ctx", ["兄长大人：我回来了"])
                ev.set_extra("_ks_rw_title", "兄长大人")
                ev.set_extra("_ks_draft_req", Req())
                resp = LLMResponse("兄长大人回来啦，汤还热着。")
                await self.make(cfg={"shadow_plan": on}).rewrite_reply(ev, resp)
                await asyncio.sleep(0.05)
                self.assertEqual(resp.completion_text, "兄长大人辛苦啦，佳树给你留了热汤哦")  # 发出去的不受影响
        finally:
            omni.text = old
        self.assertEqual(len(calls), 1)
        self.assertIn("我回来了", calls[0][1])
        folder = shadow.folder_of(FOLDER)
        [p] = [json.loads(x) for f in glob.glob(os.path.join(folder, "*.jsonl")) for x in open(f, encoding="utf-8") if x.strip()]
        self.assertEqual((p["plan"]["要回应的"], p["plan"]["背景"], p["final"]), ("他回来了", ["汤还热着"], "兄长大人辛苦啦，佳树给你留了热汤哦"))
        self.assertEqual(shadow.parse('{"局面": "x", "事实": "无"}'), {"局面": "x", "要回应的": "", "事实": [], "背景": []})
        self.assertIsNone(shadow.parse("不是 JSON"))

    async def test_mood_recorded(self):
        from kaju_core import parts

        snap = {"mood": {"joy": 0.71, "energy": 0.5, "stress": 0.2, "warm": 0.64},
                "recent": [{"emo": "感动", "i": 2, "src": "content", "cause": "视频", "ago": 30}], "threads": []}

        class Heart:
            def mood_snapshot(self):
                return snap

        class Broken:
            def mood_snapshot(self):
                raise RuntimeError("坏了")

        await self.reply(self.make())  # 心情那部分不在：不记这一栏
        h = Heart()
        parts.register("test_heart", h)
        try:
            await self.reply(self.make())
        finally:
            parts.unregister("test_heart", h)
        b = Broken()
        parts.register("test_heart", b)
        try:
            out = await self.reply(self.make())  # 读心情出错：不影响重说，也不记这一栏
        finally:
            parts.unregister("test_heart", b)
        r0, r1, r2 = rows()
        self.assertNotIn("mood", r0)
        self.assertEqual(r1["mood"], snap)
        self.assertNotIn("mood", r2)
        self.assertEqual((out, r2["outcome"]), ("兄长大人辛苦啦，佳树给你留了热汤哦", "used"))

    async def test_guard_rejected_keeps_draft(self):
        out = await self.reply(self.make(guard=(True, "编了没说过的事", True)))
        self.assertEqual(out, "兄长大人回来啦，汤还热着。")
        [r] = rows()
        self.assertEqual((r["outcome"], r["used"], r["guard"][0]["why"]), ("guard_rejected", False, "编了没说过的事"))
        self.assertEqual(r["writer"][0]["out"], "兄长大人辛苦啦，佳树给你留了热汤哦")

    async def test_guard_error_and_writer_error(self):
        await self.reply(self.make(guard=TimeoutError("慢")))
        await self.reply(self.make(writer=ConnectionError("ollama 没开")))
        a, b = rows()
        self.assertEqual(a["outcome"], "guard_error")
        self.assertEqual((b["outcome"], b["final"]), ("writer_error", "兄长大人回来啦，汤还热着。"))
        self.assertIn("ollama 没开", b["writer"][0]["error"])

    async def test_skipped_and_not_rewrite_turn(self):
        style = self.make()
        await self.reply(style, ctx=None)  # 这一轮本来就不重说：不记
        self.assertEqual(rows(), [])
        await self.reply(style, draft="[SKIP]")  # 重说层跳过：记下来是 skipped
        [r] = rows()
        self.assertEqual((r["outcome"], r["writer"]), ("skipped", []))

    async def test_group_kind(self):
        await self.reply(self.make(), group="123")
        self.assertEqual(rows()[0]["kind"], "群聊")

    async def test_record_off(self):
        out = await self.reply(self.make(cfg={"record": False}))
        self.assertEqual(out, "兄长大人辛苦啦，佳树给你留了热汤哦")
        self.assertEqual(rows(), [])

    async def test_polish_recorded(self):
        style = self.make(writer="兄长大人，佳树刷到一只小猫踩雪呢")
        out = await style.polish("佳树刚才刷到小猫踩雪了", ["兄长大人：在忙"], said="刷到小猫", split=False)
        self.assertEqual(out, "兄长大人，佳树刷到一只小猫踩雪呢")
        [r] = rows()
        self.assertEqual((r["src"], r["outcome"], r["draft"], r["said"], r["final"]),
                         ("polish", "used", "佳树刚才刷到小猫踩雪了", "刷到小猫", out))

    async def test_install_twice_wraps_once(self):
        style = self.make()
        style._rec.install()
        await self.reply(style)
        self.assertEqual(len(rows()[0]["writer"]), 1)

    async def test_recorder_failure_does_not_break_reply(self):
        style = self.make()
        style._rec._write = lambda rec: (_ for _ in ()).throw(OSError("磁盘满"))
        out = await self.reply(style)
        self.assertEqual(out, "兄长大人辛苦啦，佳树给你留了热汤哦")

    def test_prune(self):
        os.makedirs(FOLDER, exist_ok=True)
        for day in ("2026-08-01", "2026-11-01"):
            open(os.path.join(FOLDER, day + ".jsonl"), "w").close()
        style = self.make()
        style._rec._prune("2026-11-07")
        self.assertEqual(sorted(os.listdir(FOLDER)), ["2026-11-01.jsonl"])

    def test_outcome_unusable(self):
        self.assertEqual(records.outcome({"writer": [{"out": "x"}], "guard": []}), "unusable")


if __name__ == "__main__":
    unittest.main()
