"""Video helpers using PyAV/Pillow/OpenCV.

- grab_frames / montage：把视频按时间均匀截几帧，拼成一张图（左上角标时间），交给能看图的模型描述。
- grab_scene_frames：一遍低清扫描算画面变化，按时间铺开 + 换镜头/一直在动的地方补帧；collapse_repeats 合并没变的画面。
- extract_wav：把视频的声音转成 16kHz 单声道 wav，交给语音转文字。
- extract_wav_chunks：长视频的声音切成几段 wav（每段默认 5 分钟），分段转文字。
"""

from __future__ import annotations

import math
import os
import wave

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".3gp"}

_FONT_PATHS = [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\msyh.ttc", "DejaVuSans.ttf"]


def file_kind(name: str) -> str | None:
    """按扩展名猜文件是图片还是视频。"""
    ext = os.path.splitext((name or "").split("?", 1)[0])[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def merge_av(video_path: str, audio_path: str, output_path: str) -> None:
    """Combine separate DASH tracks into an MP4 without re-encoding."""
    import av

    with av.open(video_path) as video, av.open(audio_path) as audio, av.open(output_path, "w", format="mp4") as out:
        inputs = [(video, video.streams.video[0]), (audio, audio.streams.audio[0])]
        targets = [out.add_stream_from_template(stream) for _, stream in inputs]
        for (source, stream), target in zip(inputs, targets):
            for packet in source.demux(stream):
                if packet.dts is not None:
                    packet.stream = target
                    out.mux(packet)


def fmt_ts(sec: float, short: bool = False) -> str:
    if short:  # 一分钟以内的视频：精确到 0.1 秒，不然相邻两帧会标成同一秒
        return f"{max(0.0, sec):.1f}s"
    sec = max(0, int(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_duration(sec: float | None) -> str:
    if not sec or sec <= 0:
        return "一段"
    sec = max(1, round(sec))
    if sec < 60:
        return f"{sec}秒"
    m, s = divmod(sec, 60)
    return f"{m}分{s:02d}秒" if m < 60 else f"{m // 60}小时{m % 60:02d}分"


def _to_image(frame):
    img = frame.to_image()
    rot = getattr(frame, "rotation", 0) or 0  # 手机竖拍的视频常带旋转信息，不转的话画面是横躺的
    if rot:
        img = img.rotate(rot, expand=True)
    return img


def _frame_at(container, stream, t: float, max_decode: int = 3000):
    """跳到 t 秒附近，取第一帧 >= t 的画面（到结尾都没有就用最后一帧）。"""
    start = stream.start_time or 0
    container.seek(start + int(t / stream.time_base), stream=stream, backward=True, any_frame=False)
    last = None
    for i, frame in enumerate(container.decode(stream)):
        last = frame
        ft = frame.time
        if ft is None or ft - float(start * stream.time_base) >= t - 1e-3 or i >= max_decode:
            return _to_image(frame)
    return _to_image(last) if last is not None else None


def _sequential(path: str, count: int, cap: int = 900):
    """时长读不出来或跳转失败时：从头解码（最多 cap 帧），均匀挑 count 帧。"""
    import av

    thumbs = []
    with av.open(path) as c:
        vs = c.streams.video[0]
        for frame in c.decode(vs):
            img = _to_image(frame)
            img.thumbnail((640, 640))
            thumbs.append((frame.time or len(thumbs) / 25, img))
            if len(thumbs) >= cap:
                break
    if not thumbs:
        return []
    if len(thumbs) <= count:
        return thumbs
    step = len(thumbs) / count
    return [thumbs[int(step * (i + 0.5))] for i in range(count)]


def grab_frames(path: str, count: int = 9):
    """返回 (frames, 时长秒数或 None, 有没有声音)。frames = [(秒, PIL.Image), ...]，按时间顺序。"""
    import av

    with av.open(path) as c:
        vs = c.streams.video[0] if c.streams.video else None
        if vs is None:
            raise ValueError("文件里没有画面")
        has_audio = bool(c.streams.audio)
        vs.thread_type = "AUTO"
        dur = None
        if vs.duration and vs.time_base:
            dur = float(vs.duration * vs.time_base)
        elif c.duration:
            dur = c.duration / av.time_base
        frames = []
        if dur and dur > 0:
            for i in range(count):
                t = dur * (i + 0.5) / count
                try:
                    img = _frame_at(c, vs, t)
                except Exception:  # noqa: BLE001  个别格式不能跳转，下面换成从头解码
                    frames = []
                    break
                if img is not None:
                    frames.append((t, img))
    if len(frames) < min(count, 2):
        frames = _sequential(path, count)
    if not frames:
        raise ValueError("一帧画面也没解出来")
    return frames, dur, has_audio


def scan_video(path: str, max_samples: int = 900, rate: float = 4.0):
    """一遍从头解码，每秒取 2~4 个小灰度图打变化分（不再一帧帧跳着找，长视频也只要几秒）。
    返回 (samples, 时长, 有没有声音)。samples = [{t, grid(36×64), ok(亮度够、不糊), score}]，
    score 是和上一个样本比画面变了多少（0~1，取整体和 4×4 分块里变得最多那块的较大值）。"""
    import av
    import cv2
    import numpy as np

    with av.open(path) as c:
        if not c.streams.video:
            raise ValueError("文件里没有画面")
        vs = c.streams.video[0]
        has_audio = bool(c.streams.audio)
        dur = float(vs.duration * vs.time_base) if vs.duration and vs.time_base else (c.duration or 0) / av.time_base
        if not dur or dur <= 0:
            raise ValueError("读不出时长")
        vs.thread_type = "AUTO"
        if dur > 300:
            vs.codec_context.skip_frame = "NONREF"  # 长视频跳过不被参考的帧，解码量少一半多
        step = 1.0 / min(rate, max(max_samples / dur, 1e-3))
        start = float((vs.start_time or 0) * vs.time_base)
        fps = float(vs.average_rate or 25)
        samples, nxt, prev = [], 0.0, None
        for i, frame in enumerate(c.decode(vs)):
            t = max(0.0, frame.time - start) if frame.time is not None else i / fps
            if t + 1e-6 < nxt:
                continue
            nxt += step * max(1, math.floor((t - nxt) / step) + 1)
            small = frame.reformat(width=160, height=90, format="gray").to_ndarray()
            grid = cv2.resize(small, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)
            ok = (float(small.mean()) >= 12, float(cv2.Laplacian(small, cv2.CV_64F).var()) >= 8)
            score = 0.0
            if prev is not None:
                d = np.abs(grid - prev)
                score = float(max(d.mean(), d.reshape(4, 9, 4, 16).mean(axis=(1, 3)).max()) / 255)
            samples.append({"t": t, "grid": grid, "ok": ok, "score": score})
            prev = grid
            if len(samples) >= max_samples:
                break
    if not samples:
        raise ValueError("一帧画面也没解出来")
    return samples, dur, has_audio


def _cuts(samples, floor: float = 0.08, hard: float = 0.25, spike: float = 2.5) -> list[int]:
    """哪些样本是换镜头：变化分特别大，或者够大而且比前后都高出一截（尖峰）。"""
    s = [x["score"] for x in samples]
    out = []
    for i in range(1, len(s)):
        around = max(s[i - 1], s[i + 1] if i + 1 < len(s) else 0.0, 0.01)
        if s[i] >= hard or (s[i] >= floor and s[i] >= spike * around):
            out.append(i)
    return out


def _motion(samples, cuts, need: float = 1.0) -> list[tuple[int, float]]:
    """一镜到底但一直在动的地方：把变化分攒起来，攒够一份就记一个点（攒得越快越靠前）。"""
    cut_set, out, acc, began = set(cuts), [], 0.0, 0
    for i, x in enumerate(samples):
        if i in cut_set:
            acc, began = 0.0, i
            continue
        acc += x["score"]
        if acc >= need:
            out.append((i, acc / max(1, i - began)))
            acc, began = 0.0, i
    return out


def pick_scene_frames(samples, dur: float, count: int) -> list[int]:
    """挑哪几个样本：先按时间铺开（含开头结尾），再给没被铺到的镜头各一张，再给动得多的地方，
    最多 count 张。画面不怎么变的视频就少挑几张（静止的画面几乎不花钱）。"""
    n = len(samples)
    if n <= count:
        return list(range(n))
    times = [x["t"] for x in samples]
    cuts = _cuts(samples)
    cut_set = set(cuts)
    seg = [0] * n
    for i in range(1, n):
        seg[i] = seg[i - 1] + (1 if i in cut_set else 0)
    bounds = [0, *cuts, n]
    radius = max(dur / count, 0.5)

    def best(target: float, within: int) -> int:
        same = [i for i in range(n) if seg[i] == within]
        pool = [i for i in same if abs(times[i] - target) <= radius] or [min(same, key=lambda i: abs(times[i] - target))]
        if not any(all(samples[i]["ok"]) for i in pool):  # 这一段全是黑屏/糊的：到附近找能看清的
            pool = [i for i in range(n) if abs(times[i] - target) <= radius] or pool
        return max(pool, key=lambda i: (samples[i]["ok"], -abs(times[i] - target)))

    def nearest(target: float) -> int:
        return min(range(n), key=lambda i: abs(times[i] - target))

    chosen: set[int] = set()
    floor_sec = max(4.0, dur / 24)
    cover = 1 if count == 1 else min(max(2, math.ceil(count * 2 / 3)), math.ceil(dur / floor_sec) + 1)
    first, last = times[0], times[-1]
    for k in range(cover):
        target = first + (last - first) * k / max(1, cover - 1) if cover > 1 else (first + last) / 2
        chosen.add(best(target, seg[nearest(target)]))
    # 没被铺到的镜头：换得越猛越先给（短短一闪的镜头也不漏）
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if a >= b or any(seg[i] == seg[a] for i in chosen):
            continue
        if not any(all(samples[i]["ok"]) for i in range(a, b)):
            continue  # 整段黑屏/糊的闪帧不单独给
        shots.append((samples[a]["score"], (times[a] + times[b - 1]) / 2, seg[a]))
    gap = max(0.6, radius / 3)  # 转场时连着好几刀的，只给一张
    for _, mid, s in sorted(shots, reverse=True):
        if len(chosen) >= count:
            break
        i = best(mid, s)
        if all(abs(times[i] - times[j]) >= gap for j in chosen):
            chosen.add(i)
    for i, _ in sorted(_motion(samples, cuts), key=lambda m: -m[1]):
        if len(chosen) >= count:
            break
        if all(abs(times[i] - times[j]) >= radius / 2 for j in chosen):
            chosen.add(best(times[i], seg[i]))
    return sorted(chosen)


def grab_scene_frames(path: str, count: int = 32, max_scan_frames: int = 900):
    """按画面变化挑代表画面，格式同 grab_frames。做法参考 bili-vision / see-now 两个 DSH 插件：
    一遍低清扫描算变化分 → 换镜头（尖峰）+ 一直在动（积分）→ 时间铺开为主、变化处补帧。出错就退回均匀截帧。"""
    if count < 1 or max_scan_frames < 1:
        raise ValueError("Frame budgets must be positive")
    try:
        import av

        samples, dur, has_audio = scan_video(path, max_scan_frames)
        frames = []
        with av.open(path) as c:
            vs = c.streams.video[0]
            vs.thread_type = "AUTO"
            for i in pick_scene_frames(samples, dur, count):
                image = _frame_at(c, vs, samples[i]["t"])
                if image is not None:
                    frames.append((samples[i]["t"], image))
        if not frames:
            raise ValueError("No scene representatives could be decoded")
        return frames, dur, has_audio
    except Exception:  # noqa: BLE001  扫描是锦上添花，失败就用原来的均匀截帧
        return grab_frames(path, count)


def collapse_repeats(frames, mean_diff: float = 1.0, block_diff: float = 2.0):
    """前后两帧几乎一模一样（静止画面、PPT 停在同一页）就合成一格，省一份看图的工夫。
    在 160×90 上按 10×10 小块比，换一行字幕/歌词也算变了。
    返回 (frames, spans)：spans[i] = (这格画面从第几秒, 到第几秒)。只合并相邻的，A→B→A 不合。"""
    import numpy as np

    def small(img):
        return np.asarray(img.convert("L").resize((160, 90)), dtype=np.float32)

    out, spans, last = [], [], None
    for t, img in frames:
        g = small(img)
        if last is not None:
            d = np.abs(g - last)
            if d.mean() <= mean_diff and d.reshape(9, 10, 16, 10).mean(axis=(1, 3)).max() <= block_diff:
                spans[-1] = (spans[-1][0], t)
                continue
        out.append((t, img))
        spans.append((t, t))
        last = g
    return out, spans


def grab_at(path: str, times) -> list:
    """补看用：在指定的几个时间点各截一帧（原画质），[(秒, PIL.Image)]；截不到的跳过。"""
    import av

    frames = []
    with av.open(path) as c:
        if not c.streams.video:
            raise ValueError("文件里没有画面")
        vs = c.streams.video[0]
        vs.thread_type = "AUTO"
        for t in times:
            try:
                img = _frame_at(c, vs, float(t))
            except Exception:  # noqa: BLE001
                continue
            if img is not None:
                frames.append((float(t), img))
    return frames


def probe(path: str) -> tuple[float | None, bool]:
    """(时长秒数或 None, 有没有声音)，不解码。"""
    import av

    with av.open(path) as c:
        vs = c.streams.video[0] if c.streams.video else None
        dur = None
        if vs is not None and vs.duration and vs.time_base:
            dur = float(vs.duration * vs.time_base)
        elif c.duration:
            dur = c.duration / av.time_base
        return dur, bool(c.streams.audio)


def _font(size: int):
    from PIL import ImageFont

    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def montage(frames, max_edge: int = 1280, quality: int = 85, spans=None) -> bytes:
    """把几帧拼成一张 JPEG：从左到右、从上到下是时间顺序，每格上面一条黑边写着时间（不挡画面）。
    spans（collapse_repeats 给的）：某格画面停了一段时间的，标成「起–止」。"""
    import io

    from PIL import Image, ImageDraw

    n = len(frames)
    cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
    rows = math.ceil(n / cols)
    w, h = frames[0][1].size
    band_ratio = 0.09
    scale = min(max_edge / (cols * w), max_edge / (rows * h * (1 + band_ratio)), 1.0)
    cw, ch = max(1, int(w * scale)), max(1, int(h * scale))
    band = max(14, int(ch * band_ratio))
    sheet = Image.new("RGB", (cols * cw, rows * (ch + band)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    font = _font(max(11, int(band * 0.75)))
    short = frames[-1][0] < 60
    for i, (t, img) in enumerate(frames):
        x, y = (i % cols) * cw, (i // cols) * (ch + band)
        cell = img.convert("RGB")
        cell.thumbnail((cw, ch))
        sheet.paste(cell, (x + (cw - cell.width) // 2, y + band + (ch - cell.height) // 2))
        label = fmt_ts(t, short)
        if spans and spans[i][1] - spans[i][0] >= 1:
            label = f"{fmt_ts(spans[i][0], short)}–{fmt_ts(spans[i][1], short)}"
        draw.text((x + 4, y + band // 2), label, fill=(255, 255, 255), font=font, anchor="lm")
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def extract_wav_chunks(path: str, out_dir: str, chunk_seconds: float = 300, max_seconds: float = 1800,
                       rate: int = 16000, silence_peak: int = 400) -> tuple[list[tuple[float, str]], float]:
    """把视频的声音切成每段 chunk_seconds 秒的 16kHz 单声道 wav（长视频一整段太大，语音转文字吃不下）。
    返回 ([(这段从第几秒开始, wav 路径), ...], 一共读了多少秒)。几乎没声音的段不写；max_seconds<=0 表示全部。"""
    import uuid

    import av
    import numpy as np

    chunk_bytes = max(1, int(chunk_seconds * rate)) * 2
    limit = int(max_seconds * rate) * 2 if max_seconds and max_seconds > 0 else None
    tag = uuid.uuid4().hex[:8]
    chunks: list[tuple[float, str]] = []
    total = 0

    def flush(data: bytes, start: float) -> None:
        pcm = np.frombuffer(data, dtype=np.int16)
        if pcm.size < rate // 2 or int(np.abs(pcm.astype(np.int32)).max()) < silence_peak:
            return
        p = os.path.join(out_dir, f"kaju_audio_{tag}_{len(chunks):03d}.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(data)
        chunks.append((start, p))

    buf, start = bytearray(), 0.0
    with av.open(path) as c:
        if not c.streams.audio:
            return [], 0.0
        astream = c.streams.audio[0]
        rs = av.AudioResampler(format="s16", layout="mono", rate=rate)

        def pcm_frames():
            for frame in c.decode(astream):
                yield from rs.resample(frame)
            yield from rs.resample(None)

        for f in pcm_frames():
            data = f.to_ndarray().tobytes()
            if limit is not None:
                data = data[: max(0, limit - total)]
            buf += data
            total += len(data)
            while len(buf) >= chunk_bytes:
                flush(bytes(buf[:chunk_bytes]), start)
                del buf[:chunk_bytes]
                start += chunk_seconds
            if limit is not None and total >= limit:
                break
    if buf:
        flush(bytes(buf), start)
    return chunks, total / 2 / rate
