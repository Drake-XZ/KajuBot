"""Offline scene sampling checks using real, temporary PyAV videos."""

import os
import sys
import tempfile
from unittest.mock import patch

import av
import cv2
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))
sys.path.insert(0, os.path.dirname(HERE))  # kaju_core
from kaju_core.senses import media  # noqa: E402

failures = []
checks = 0


def expect(label, got, want):
    global checks
    checks += 1
    if got != want:
        failures.append(label)
        print(f"FAIL {label}\n  got:  {got!r}\n  want: {want!r}")


def picture(color):
    pixels = np.full((96, 160, 3), color, dtype=np.uint8)
    pixels[::8, :, :] = 230
    pixels[:, ::8, :] = 230
    return Image.fromarray(pixels)


def video(path, images, fps=10, audio=False):
    with av.open(path, "w") as out:
        stream = out.add_stream("ffv1", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 160, 96, "bgr0"
        sound = out.add_stream("pcm_s16le", rate=16000) if audio else None
        for i, image in enumerate(images):
            frame = av.VideoFrame.from_image(image)
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
        if sound:
            samples = np.full((1, int(len(images) / fps * 16000)), 600, dtype=np.int16)
            frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
            frame.sample_rate, frame.pts = 16000, 0
            for packet in sound.encode(frame):
                out.mux(packet)
            for packet in sound.encode():
                out.mux(packet)


def sharpness(image):
    return cv2.Laplacian(np.array(image.convert("L")), cv2.CV_64F).var()


def run():
    expect("scene sampler exists", callable(getattr(media, "grab_scene_frames", None)), True)
    if not hasattr(media, "grab_scene_frames"):
        return
    red, green, blue = (picture(c) for c in ((190, 30, 30), (30, 190, 30), (30, 30, 190)))
    with tempfile.TemporaryDirectory(prefix="kaju_scene_test_") as folder:
        clip = os.path.join(folder, "cuts.mkv")
        # A short middle scene is missed by the old uniform two-frame sampler.
        video(clip, [red] * 40 + [green] * 6 + [blue] * 74, audio=True)
        frames, duration, audio = media.grab_scene_frames(clip, 3)
        colors = [int(np.array(image)[3, 3].argmax()) for _, image in frames]
        expect("each scene represented, including short cut", colors, [0, 1, 2])
        expect("duration preserved", abs(duration - 12) < 0.1, True)
        expect("audio metadata preserved", audio, True)
        expect("ordered scene timestamps", [t for t, _ in frames], sorted(t for t, _ in frames))
        expect("frame budget", len(frames) <= 3, True)

        clip = os.path.join(folder, "static.mkv")
        video(clip, [red] * 240)
        frames, duration, audio = media.grab_scene_frames(clip, 8)
        times = [t for t, _ in frames]
        expect("static span uses a few coverage frames, not the whole budget", 2 <= len(times) < 8, True)
        expect("static span includes beginning and end", times[0] < 3 and times[-1] > 21, True)
        expect("static span has no large temporal hole", max(b - a for a, b in zip(times, times[1:])) <= 6.1, True)
        expect("static timestamps unique", len(set(times)), len(times))
        expect("silent metadata preserved", audio, False)

        collapsed, spans = media.collapse_repeats(frames)
        expect("static frames collapse into one cell", len(collapsed), 1)
        expect("collapsed span covers the whole still", spans[0][0] < 3 and spans[0][1] > 21, True)
        expect("span label drawn on sheet", len(media.montage(collapsed, 640, spans=spans)) > 0, True)

        seen = []
        original = media.scan_video

        def tracked(*args, **kwargs):
            out = original(*args, **kwargs)
            seen.append(len(out[0]))
            return out

        with patch.object(media, "scan_video", tracked):
            frames, _, _ = media.grab_scene_frames(clip, 8, max_scan_frames=40)
        expect("scan stays bounded", len(seen) == 1 and 1 < seen[0] <= 40, True)
        expect("bounded scan still covers late video", frames[-1][0] > 21, True)

        clip = os.path.join(folder, "early_cuts.mkv")
        video(clip, [red] * 10 + [green] * 10 + [blue] * 10 + [red] * 10 + [green] * 10 + [blue] * 150)
        frames, _, _ = media.grab_scene_frames(clip, 4)
        expect("many early cuts preserve the long static ending", frames[0][0] <= 2.5 and frames[-1][0] >= 17.5, True)

        black = Image.new("RGB", (160, 96))
        clip = os.path.join(folder, "flashes.mkv")
        images = [red] * 120
        for i in (0, 1, 14, 15, 44, 45, 59, 60, 74, 75, 104, 105, 118, 119):
            images[i] = black
        video(clip, images)
        frames, _, _ = media.grab_scene_frames(clip, 8)
        expect("near-black candidates replaced by readable neighbors",
               all(np.array(image).mean() > 20 for _, image in frames), True)

        clip = os.path.join(folder, "blur.mkv")
        blurred = red.filter(ImageFilter.GaussianBlur(8))
        images = [red] * 120
        for i in range(52, 68):
            images[i] = blurred
        video(clip, images)
        frames, _, _ = media.grab_scene_frames(clip, 8)
        expect("very blurry candidates replaced when readable frames exist",
               all(sharpness(image) > 8 for _, image in frames), True)

        with patch.object(media, "scan_video", side_effect=RuntimeError("scan unavailable")), \
                patch.object(media, "grab_frames", wraps=media.grab_frames) as fallback:
            actual, duration, audio = media.grab_scene_frames(clip, 4)
        expected, expected_duration, expected_audio = media.grab_frames(clip, 4)
        expect("detector failure uses original sampler", fallback.call_args.args, (clip, 4))
        expect("fallback preserves metadata", (duration, audio), (expected_duration, expected_audio))
        expect("fallback preserves frames", [(t, image.tobytes()) for t, image in actual],
               [(t, image.tobytes()) for t, image in expected])

        # A→B→A keeps all three cells; only neighbours that look the same merge
        aba = [(0.0, red), (1.0, red), (2.0, green), (3.0, red)]
        cells, spans = media.collapse_repeats(aba)
        expect("only adjacent repeats merge", [t for t, _ in cells], [0.0, 2.0, 3.0])
        expect("merged span recorded", spans[0], (0.0, 1.0))

        # a new subtitle/lyric line over the same still picture is a real change
        from PIL import ImageDraw
        still = Image.fromarray(np.random.default_rng(1).integers(0, 255, (360, 640, 3), dtype=np.uint8))
        lines = []
        for text in ("夜空中最亮的星", "夜空中最亮的星", "能否听清"):
            img = still.copy()
            ImageDraw.Draw(img).text((120, 315), text, fill=(255, 255, 255), font=media._font(26))
            lines.append(img)
        cells, _ = media.collapse_repeats([(0.0, lines[0]), (5.0, lines[1]), (10.0, lines[2])])
        expect("same line merges, new line kept", [t for t, _ in cells], [0.0, 10.0])

        # one long shot that keeps moving gets extra frames where it moves
        clip = os.path.join(folder, "pan.mkv")
        base = np.array(picture((120, 80, 40)).resize((320, 96)))
        moving = [Image.fromarray(np.ascontiguousarray(np.roll(base, i * 3, axis=1)[:, :160])) for i in range(80)]
        video(clip, [red] * 160 + moving)
        frames, _, _ = media.grab_scene_frames(clip, 12)
        times = [t for t, _ in frames]
        print("  pan frames:", [round(t, 1) for t in times])
        expect("moving part sampled more densely than the still part",
               sum(t >= 16 for t in times) / 8 > sum(t < 16 for t in times) / 16, True)

        clip = os.path.join(folder, "dark.mkv")
        video(clip, [black] * 10)
        expect("all-dark video still produces frames", bool(media.grab_scene_frames(clip, 3)[0]), True)
        for kwargs in ({"count": 0}, {"max_scan_frames": 0}):
            try:
                media.grab_scene_frames(clip, **kwargs)
            except ValueError:
                expect(f"reject invalid budget {kwargs}", True, True)
            else:
                expect(f"reject invalid budget {kwargs}", False, True)


run()
print(f"ALL OK ({checks} checks)" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
