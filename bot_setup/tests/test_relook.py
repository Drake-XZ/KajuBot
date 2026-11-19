"""补看（relook.py + Describer.relook）：认出问的是视频哪一段，回到原文件截那一段再看。"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE), str(HERE.parent)]  # HERE：用 -I 跑也能 import test_vision_pipeline
os.environ["STUB_DATA"] = tempfile.mkdtemp(prefix="kaju-relook-tests-")

from astrbot.api.event import AstrMessageEvent  # noqa: E402
from astrbot.api.message_components import Video  # noqa: E402
from astrbot.api.provider import LLMResponse  # noqa: E402
from astrbot.api.star import Context  # noqa: E402
from kaju_core.senses import relook  # noqa: E402
from kaju_basics.describe import Describer, SkipVideo  # noqa: E402
from test_vision_pipeline import make_clip  # noqa: E402


class Parse(unittest.TestCase):
    def test_moments(self):
        cases = {
            "2:10那里他拿的是什么": (130, 130),
            "2分10秒的时候是谁": (130, 130),
            "第三十秒那里写的啥": (30, 30),
            "1分半左右那个画面": (90, 90),
            "两分钟那里在干嘛": (120, 120),
            "1:00到1:20在干嘛": (60, 80),
            "开头那里是谁啊": (0, 6),
            "结尾最后几秒写了什么": (234, 240),
        }
        for text, want in cases.items():
            self.assertEqual(relook.parse_moment(text, 240), want, text)

    def test_not_a_question_about_the_video(self):
        for text in ("明天2:10见", "我30岁了吗", "视频真好看", "开头好好笑", "10:30的时候是什么", "30秒那个好好笑"):
            self.assertIsNone(relook.parse_moment(text, 240), text)

    def test_cn_numbers(self):
        self.assertEqual([relook.cn_number(x) for x in ("十", "十五", "二十", "二十五", "两", "12")], [10, 15, 20, 25, 2, 12])

    def test_window(self):
        self.assertEqual(relook.window(130, 130, 240), [128.0, 129.33, 130.67, 132.0])
        self.assertEqual(relook.window(0, 0, 240)[0], 0.0)
        self.assertLess(relook.window(240, 240, 240)[-1], 240)
        self.assertEqual(len(relook.window(60, 80, 240, 6)), 6)


class Vision:
    def __init__(self):
        self.calls = []

    async def text_chat(self, prompt="", image_urls=None, **kwargs):
        from PIL import Image

        with Image.open(image_urls[0]) as image:
            self.calls.append((prompt, image.size))
        return LLMResponse("画面里一个人举着蓝色的牌子，上面写着「你好」")


class STT:
    async def get_text(self, audio_url=""):
        return "这里是一句台词"


class Rewatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.mkdtemp(prefix="kaju-relook-clip-")
        self.clip = Path(self.folder) / "clip.mp4"
        make_clip(self.clip)
        self.vision = Vision()
        self.vision.provider_config = {"id": "local"}
        context = Context({"provider_ltm_settings": {}})
        context.providers, context.stt = {"local": self.vision}, STT()
        cfg = {"video_scene_sampling": True, "video_scene_frames": 16, "video_sheet_frames": 4,
               "vision_provider_id": "local", "max_edge": 1536}
        self.d = Describer(context, lambda: cfg)

    async def asyncTearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    async def test_rewatch_a_moment_of_the_last_video(self):
        event = AstrMessageEvent()
        await self.d.watch(Video.fromFileSystem(str(self.clip)), event)
        self.assertIsNone(self.d.last_video("someone-else", 60))
        meta = self.d.last_video(event.unified_msg_origin, 60)
        self.assertEqual(meta["path"], str(self.clip))
        before = len(self.vision.calls)
        note = await self.d.relook(meta, 6, 6, "6秒那里举的牌子写的什么", event.unified_msg_origin)
        self.assertIn("你好", note)
        prompt, size = self.vision.calls[before]
        self.assertIn("6秒那里举的牌子写的什么", prompt)
        self.assertIn("00:04", prompt)
        self.assertIn("00:08", prompt)
        self.assertGreaterEqual(size[0], 1280)
        again = await self.d.relook(meta, 6, 6, "6秒那里举的牌子写的什么", event.unified_msg_origin)
        self.assertEqual(again, note)
        self.assertEqual(len(self.vision.calls), before + 1)
        self.assertEqual(list(Path(os.environ.get("TEMP", self.folder)).glob("kaju_relook_*.jpg")), [])

    async def test_file_gone(self):
        event = AstrMessageEvent()
        await self.d.watch(Video.fromFileSystem(str(self.clip)), event)
        meta = dict(self.d.last_video(event.unified_msg_origin, 60))
        meta["path"] = str(Path(self.folder) / "deleted.mp4")
        with self.assertRaises(SkipVideo):
            await self.d.relook(meta, 3, 3, "3秒那里是什么", event.unified_msg_origin)

    async def test_too_long_ago(self):
        event = AstrMessageEvent()
        await self.d.watch(Video.fromFileSystem(str(self.clip)), event)
        self.d.senses._last_watch[event.unified_msg_origin]["at"] -= 3 * 3600
        self.assertIsNone(self.d.last_video(event.unified_msg_origin, 60))


if __name__ == "__main__":
    unittest.main()
