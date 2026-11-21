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
from kaju_core.voice import records, replyer  # noqa: E402
from kaju_style.main import KajuStyle  # noqa: E402

FOLDER = os.path.join(DATA, "astrbot_plugin_kaju_style", "rewrites")
PLAN = '{"局面": "兄长大人回来了", "要表达的": ["分享：汤还热着"]}'


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
        # 只写一遍（retry 0）、writer_only 关着（查“没过就发原稿”时记成什么）：草稿整理成指导、回复器、核对都是假的
        style = KajuStyle(Context(), {"rewrite": {"enable": True, "retry": 0, "writer_only": False,
                                                  "shadow_plan": False, **(cfg or {})}})  # 影子规划器只在它自己的测试里开
        self.guard_calls = []
        real = replyer.reply

        async def fake_reply(kind, title, ctx, plan, cfg, said="", log=None, ctx_lines=10, how=""):
            if isinstance(writer, Exception):  # 真的回复器自己接住报错，只在 errors 里写一笔
                return "", {"model": "", "secs": 0.1, "examples": [], "errors": [f"测试: {writer}"]}
            return writer, {"model": "测试", "secs": 0.1, "examples": [], "errors": []}
        replyer.reply = fake_reply
        self.addCleanup(setattr, replyer, "reply", real)

        async def model_id(model="", who=""):
            return model or "main"

        async def generate(pid, prompt, system="", timeout=None):
            return PLAN
        style.body.model_id, style.body.generate = model_id, generate
        style._mood_words = lambda **kw: ""

        async def guard_fn(said, draft, new, title="", ctx=None):
            self.guard_calls.append(new)
            if isinstance(guard, Exception):
                raise guard
            return guard

        style._guard = guard_fn
        style._rec.install()  # 换了假的核对之后重新包一层
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
        w = r["replyer"][0]
        self.assertEqual((w["model"], w["text"]), ("测试", out))
        self.assertEqual(r["from_draft"][0]["plan"]["要表达的"], ["分享：汤还热着"])  # 这一轮没换成大脑：草稿先整理成指导
        self.assertEqual((r["guard"][0]["bad"], r["guard"][0]["new"]), (False, out))
        self.assertNotIn("card_model", r["config"])
        self.assertNotIn("writer", r)
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
        self.assertEqual(r["replyer"][0]["text"], "兄长大人辛苦啦，佳树给你留了热汤哦")

    async def test_guard_error_and_writer_error(self):
        await self.reply(self.make(guard=TimeoutError("慢")))
        await self.reply(self.make(writer=ConnectionError("中转站没开")))
        a, b = rows()
        self.assertEqual(a["outcome"], "guard_error")
        self.assertEqual((b["outcome"], b["final"]), ("writer_error", "兄长大人回来啦，汤还热着。"))
        self.assertIn("中转站没开", b["replyer"][0]["errors"][0])

    async def test_skipped_and_not_rewrite_turn(self):
        style = self.make()
        await self.reply(style, ctx=None)  # 这一轮本来就不重说：不记
        self.assertEqual(rows(), [])
        await self.reply(style, draft="[SKIP]")  # 重说层跳过：记下来是 skipped
        [r] = rows()
        self.assertEqual((r["outcome"], r.get("replyer")), ("skipped", None))

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
        self.assertEqual(len(rows()[0]["guard"]), 1)

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
        self.assertEqual(records.outcome({"replyer": [{"text": "x"}], "guard": []}), "unusable")
        self.assertEqual(records.outcome({"replyer": [{"text": "", "errors": ["502"]}]}), "writer_error")
        self.assertEqual(records.outcome({"guard": []}), "skipped")


if __name__ == "__main__":
    unittest.main()
