"""动图拆帧（kaju_basics/animation.py）：按时间取样、停住的合一格、不动的当普通图、按长宽比排版、换掉 AstrBot 自带的。"""

import io
import sys
import types
import unittest
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "stubs"), str(HERE.parent / "plugins"), str(HERE.parent)]  # HERE.parent：kaju_core

from PIL import Image, ImageDraw  # noqa: E402

from kaju_basics import gifpatch  # noqa: E402
from kaju_core.senses import animation  # noqa: E402

COLORS = [(230, 40, 40), (40, 200, 40), (40, 40, 230), (230, 200, 30), (200, 40, 200), (30, 200, 200),
          (120, 60, 10), (250, 140, 0), (90, 90, 90), (0, 0, 0)]


def frames(n, size=(120, 120), still=False):
    out = []
    for i in range(n):
        im = Image.new("RGB", size, (255, 255, 255))
        d = ImageDraw.Draw(im)
        c = COLORS[0 if still else i % len(COLORS)]
        x = 0 if still else (i * 7) % max(1, size[0] - 30)
        d.rectangle((x, 10, x + 30, 40), fill=c)
        out.append(im)
    return out


def encode(imgs, durations, fmt="GIF", **kw):
    buf = io.BytesIO()
    imgs[0].save(buf, fmt, save_all=True, append_images=imgs[1:], duration=durations, loop=0, **kw)
    return buf.getvalue()


def opened(data):
    return Image.open(io.BytesIO(data))


class Timeline(unittest.TestCase):
    def test_tiny_delays_count_as_100ms(self):
        with opened(encode(frames(3), [0, 10, 50])) as im:
            durs, first = animation.timeline(im)
        self.assertEqual(first, 0)
        self.assertEqual(durs, [100, 100, 50])

    def test_samples_by_time_not_index(self):
        # 第 0 帧停 1 秒，后面 10 帧各 0.1 秒：按时间取一半样本落在第 0 帧
        durs = [1000] + [100] * 10
        picks = animation.sample_times(durs, 8)
        self.assertEqual(picks[0], 0)
        self.assertEqual(picks[-1], 10)
        self.assertLessEqual(len([p for p in picks if p > 0]), 6)

    def test_sample_includes_last(self):
        self.assertEqual(animation.sample_times([100] * 5, 2)[-1], 4)


class Build(unittest.TestCase):
    def test_still_gif_is_plain_image(self):
        with opened(encode(frames(6, still=True), 100)) as im:
            img, animated = animation.build(im, 1280, 8)
        self.assertFalse(animated)
        self.assertEqual(img.size, (120, 120))

    def test_hold_merged_and_labelled(self):
        last = frames(5)[4]
        holds = []
        for k in range(6):  # 最后一个样子停 6 帧（每帧差一个像素，GIF 编码器才不会自己合并）
            im = last.copy()
            im.putpixel((119, 119 - k), (250, 250, 250))
            holds.append(im)
        imgs = frames(4) + holds
        with opened(encode(imgs, [100] * 10)) as im:
            cells, info = animation.pick_cells(im, 8)
        self.assertEqual(info["frames"], 10)
        self.assertEqual(info["total_ms"], 1000)
        self.assertEqual(len(cells), 5)
        idx, start, end, _ = cells[-1]
        self.assertEqual(start, 400)
        self.assertEqual(end, 1000)

    def test_cap_and_fill_grid(self):
        with opened(encode(frames(40, size=(200, 200)), 50)) as im:
            img, animated = animation.build(im, 1280, 8)
        self.assertTrue(animated)
        self.assertLessEqual(max(img.size), 1280)
        # 方图 8 格排成 3×3，空位补上第 9 格
        cells_w = img.size[0] // 3
        self.assertGreater(cells_w, 200)  # 小图放大了

    def test_layout_follows_aspect(self):
        cols, rows, _ = animation.layout(8, 300, 1000, 1280)  # 手机竖图：排成一行或两行
        self.assertGreaterEqual(cols, 4)
        cols, rows, _ = animation.layout(8, 1000, 200, 1280)  # 很宽的横图：一列
        self.assertLessEqual(cols, 2)

    def test_wide_gif_fits(self):
        with opened(encode(frames(12, size=(600, 120)), 80)) as im:
            img, animated = animation.build(im, 1024, 8)
        self.assertTrue(animated)
        self.assertLessEqual(max(img.size), 1024)

    def test_webp_animated(self):
        with opened(encode(frames(10), 80, "WEBP", lossless=True)) as im:
            img, animated = animation.build(im, 1280, 6)
        self.assertTrue(animated)

    def test_apng(self):
        with opened(encode(frames(6), 100, "PNG")) as im:
            self.assertGreater(im.n_frames, 1)
            img, animated = animation.build(im, 1280, 6)
        self.assertTrue(animated)


class Install(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def orig(source_bytes, max_size):
            self.calls.append(max_size)
            return b"orig", False

        def encode_frame(image, max_size=None):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, "JPEG")
            return buf.getvalue()

        self.mod = types.SimpleNamespace(_prepare_model_image_sync=orig, _encode_image_frame_bytes=encode_frame)
        self.agent = types.SimpleNamespace(ANIMATION_CAPTION_NOTICE="old {indices}")
        self.opts = {"enable": True, "max_frames": 8}
        self.logs = []
        gifpatch.install(lambda: self.opts, self.logs.append, mod=self.mod, agent=self.agent)

    def tearDown(self):
        gifpatch.uninstall(mod=self.mod, agent=self.agent)

    def test_animated_goes_through_ours(self):
        out, montage = self.mod._prepare_model_image_sync(encode(frames(10), 100), 1280)
        self.assertTrue(montage)
        self.assertTrue(out.startswith(b"\xff\xd8"))
        self.assertEqual(self.calls, [])
        self.assertIn("{indices}", self.agent.ANIMATION_CAPTION_NOTICE)
        self.assertIn("停住", self.agent.ANIMATION_CAPTION_NOTICE)

    def test_still_gif_not_montage(self):
        out, montage = self.mod._prepare_model_image_sync(encode(frames(5, still=True), 100), 1280)
        self.assertFalse(montage)

    def test_png_and_broken_go_to_builtin(self):
        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, "PNG")
        self.assertEqual(self.mod._prepare_model_image_sync(buf.getvalue(), 1280), (b"orig", False))
        self.assertEqual(self.mod._prepare_model_image_sync(b"GIF89a broken", 1280), (b"orig", False))

    def test_disabled(self):
        self.opts["enable"] = False
        self.assertEqual(self.mod._prepare_model_image_sync(encode(frames(10), 100), 1280), (b"orig", False))

    def test_reinstall_and_uninstall_restore(self):
        first = self.mod.__dict__[gifpatch.ORIG_ATTR]
        gifpatch.install(lambda: self.opts, self.logs.append, mod=self.mod, agent=self.agent)
        self.assertIs(self.mod.__dict__[gifpatch.ORIG_ATTR], first)
        gifpatch.uninstall(mod=self.mod, agent=self.agent)
        self.assertIs(self.mod._prepare_model_image_sync, first)
        self.assertEqual(self.agent.ANIMATION_CAPTION_NOTICE, "old {indices}")


if __name__ == "__main__":
    unittest.main()
