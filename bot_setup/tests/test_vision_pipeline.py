"""Offline checks for readable video batches and explicit local-provider routing."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from httpx import URL

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]  # HERE.parent：源码里的 kaju_core
os.environ["STUB_DATA"] = tempfile.mkdtemp(prefix="kaju-vision-tests-")

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Video
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context
from kaju_core.senses import media
from kaju_basics import deadline
from kaju_basics.describe import Describer, _temp_dir


def make_clip(path):
    import av
    import numpy as np
    from PIL import Image

    with av.open(str(path), "w") as out:
        video = out.add_stream("mpeg4", rate=2)
        video.width, video.height, video.pix_fmt = 640, 360, "yuv420p"
        audio = out.add_stream("aac", rate=16000, layout="mono")
        for i in range(24):
            image = Image.new("RGB", (640, 360), (30 + i * 8, 120, 160))
            for packet in video.encode(av.VideoFrame.from_image(image)):
                out.mux(packet)
        for packet in video.encode():
            out.mux(packet)
        pcm = (np.sin(2 * np.pi * 440 * np.arange(12 * 16000) / 16000) * 8000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 16000
        for packet in audio.encode(frame):
            out.mux(packet)
        for packet in audio.encode():
            out.mux(packet)


class Vision:
    def __init__(self, fail_at=0):
        self.calls = []
        self.fail_at = fail_at

    async def text_chat(self, prompt="", image_urls=None, **kwargs):
        from PIL import Image

        path = image_urls[0]
        with Image.open(path) as image:
            self.calls.append((prompt, image.size, path))
        if len(self.calls) == self.fail_at:
            raise RuntimeError("local vision unavailable")
        return LLMResponse("画面中的颜色逐渐变化，人物细节看不清")


class STT:
    async def get_text(self, audio_url=""):
        return "这里是一句台词"


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="kaju-vision-clip-")
        cls.clip = Path(cls.folder.name) / "clip.mp4"
        make_clip(cls.clip)
        cls.image = Path(cls.folder.name) / "image.jpg"
        media.grab_frames(str(cls.clip), 1)[0][0][1].save(cls.image)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setup_describer(self, local=None):
        local, cloud = local or Vision(), Vision()
        local.provider_config, cloud.provider_config = {"id": "local"}, {"id": "cloud"}
        context = Context({"provider_ltm_settings": {"image_caption_provider_id": "cloud"}})
        context.providers, context.stt = {"cloud": cloud, "local": local}, STT()
        cfg = {"video_scene_sampling": True, "video_scene_frames": 16, "video_sheet_frames": 4,
               "vision_provider_id": "local", "max_edge": 1536}
        return Describer(context, lambda: cfg), local, cloud, cfg

    async def test_batches_keep_resolution_timestamps_audio_and_cache(self):
        d, local, cloud, _ = self.setup_describer()
        frames = media.grab_frames(str(self.clip), 10)
        event = AstrMessageEvent()
        with patch.object(media, "grab_scene_frames", return_value=frames, create=True):
            text = await d.video(Video.fromFileSystem(str(self.clip)), event)
            again = await d.video(Video.fromFileSystem(str(self.clip)), event)
        self.assertEqual(len(local.calls), 3)
        self.assertEqual(cloud.calls, [])
        self.assertTrue(all(width >= 1280 for _, (width, _), _ in local.calls[:2]))
        self.assertIn("00:00", local.calls[0][0])
        self.assertIn("00:11", local.calls[-1][0])
        self.assertIn("这里是一句台词", text)
        self.assertEqual(text, again)
        self.assertTrue(all(not Path(path).exists() for _, _, path in local.calls))

    async def test_missing_explicit_provider_does_not_call_cloud(self):
        d, _, cloud, cfg = self.setup_describer()
        cfg["vision_provider_id"] = "missing-local"
        with self.assertRaises(RuntimeError):
            await d.caption(str(self.image), "test", "test")
        self.assertEqual(cloud.calls, [])

    async def test_batch_failure_cleans_images_and_reports_unavailable(self):
        d, local, _, _ = self.setup_describer(Vision(fail_at=2))
        frames = media.grab_frames(str(self.clip), 10)
        with patch.object(media, "grab_scene_frames", return_value=frames, create=True):
            with self.assertRaisesRegex(RuntimeError, "local vision unavailable"):
                await d.watch(Video.fromFileSystem(str(self.clip)), AstrMessageEvent())
        self.assertEqual(len(local.calls), 2)
        self.assertEqual(list(Path(_temp_dir()).glob("kaju_video_*.jpg")), [])

    async def test_subtitle_fallback_obeys_missing_local_provider(self):
        d, _, _, cfg = self.setup_describer()
        cfg["vision_provider_id"] = "missing-local"
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs["chat_provider_id"])
            return LLMResponse("视频笔记")

        d.context.llm_generate = generate
        await d._bili_watched({"title": "测试视频", "duration": 275},
                              {"lan": "zh-CN", "lines": [(i, "测试字幕" * 40) for i in range(20)]}, "test")
        self.assertEqual(calls, [])

    async def test_long_local_digest_keeps_tail_with_bounded_requests(self):
        d, _, _, _ = self.setup_describer()
        calls = []
        marker = "尾声出现蓝色小船"

        async def generate(**kwargs):
            calls.append(kwargs)
            return LLMResponse("中间画面保持连续。" + (marker if marker in kwargs["prompt"] else ""))

        d.context.llm_generate = generate
        await d._watch_digest("测试视频", "30分钟", "[00:01] 开头是红色的房屋", "普通内容" * 4000 + marker, "test")
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(c["chat_provider_id"] == "local" for c in calls))
        self.assertTrue(all(len(c["prompt"].encode("utf-8")) < 7000 for c in calls))
        self.assertIn(marker, calls[-1]["prompt"])

    async def test_unavailable_stt_keeps_visual_notes_without_claiming_audio(self):
        d, local, _, _ = self.setup_describer()

        async def unavailable(audio_url=""):
            raise RuntimeError("402 insufficient balance")

        d.context.stt.get_text = unavailable
        frames = media.grab_frames(str(self.clip), 4)
        with patch.object(media, "grab_scene_frames", return_value=frames, create=True):
            text = await d.watch(Video.fromFileSystem(str(self.clip)), AstrMessageEvent())
        self.assertEqual(len(local.calls), 1)
        self.assertIn("没有可用的声音转写", text)
        self.assertIn("颜色逐渐变化", text)

    async def test_local_deadline_allows_model_load_without_relaxing_cloud_limit(self):
        class Completion:
            async def create(self):
                await asyncio.sleep(0.04)
                return "seen"

        deadline.install(lambda: 0.01, lambda text: None, cls=Completion,
                         make_error=lambda client: TimeoutError("deadline"))
        try:
            client = Completion()
            client._client = SimpleNamespace(base_url=URL("http://127.0.0.1:11435/v1"),
                                             timeout=SimpleNamespace(read=0.2))
            try:
                observed = await client.create()
            except TimeoutError:
                observed = "timed out"
            self.assertEqual(observed, "seen")
            client._client.base_url = URL("https://api.deepseek.com/v1")
            with self.assertRaisesRegex(TimeoutError, "deadline"):
                await client.create()
        finally:
            deadline.uninstall(cls=Completion)


if __name__ == "__main__":
    unittest.main()
