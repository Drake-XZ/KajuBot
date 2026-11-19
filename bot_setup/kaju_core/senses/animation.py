"""动图（GIF / 动态 WebP / APNG）怎么交给看图模型。

AstrBot 自带的做法（media_utils._prepare_model_image_sync）：不管多长，按帧序号均匀取 9 帧拼成 3×3，
格子不标时间，模型不知道一共几帧、播多久，也不知道哪里停住了。表情包里四分之一的帧时长不均匀
（最后停一下、某个表情多停一会儿），按序号取会偏；宽图、窄图也硬塞 3×3，没用满的格子留白。

这里换成（思路参考 NeoHotaru/dsh-read-animation，MIT；代码是自己写的）：
- 按时间取样：读每帧的时长，在一轮播放的时间轴上均匀取点，停得久的画面自然多占样本。
- 前后几乎一样的格子合成一格，标「停住」，空出来的位置留给别的瞬间；整张其实不动就当普通图片。
- 按动图的长宽比排格子（手机竖图排成一行），小表情放大一点，字才看得清。
- 每格上方标序号和时间，最上面一行写一轮多长、一共几帧、取了几格。

这里只管把动图变成一张拼图（不认识 AstrBot）；换掉 AstrBot 自带拆帧的那一步在 kaju_basics/gifpatch.py。
"""

from __future__ import annotations

import bisect
import math

MAX_TIMELINE_FRAMES = 600  # 再长的动图不逐帧读时长，按第一帧的时长估
MIN_DELAY_MS = 11  # 浏览器把 10ms 及以下的帧时长当成 100ms
DEFAULT_DELAY_MS = 100
_CJK_FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", "NotoSansCJK-Regular.ttc",
              r"C:\Windows\Fonts\arial.ttf", "DejaVuSans.ttf"]

# 主流程里给看图模型的提示（替换 astr_main_agent.ANIMATION_CAPTION_NOTICE，{indices} 是第几张图）
CAPTION_NOTICE = (
    "\n<system_notice>\n"
    "第 {indices} 张图是动图（比如动态表情包），已经按时间顺序截成几格拼在一起："
    "从左到右、从上到下是时间顺序，最上面一行写着一轮多长、一共几帧，每格上方是序号和时间，"
    "标「停住」的格子表示那段时间画面没变。格与格之间还有没画出来的帧，别把没看到的动作当成事实。"
    "当作一个动图来描述：谁在做什么、动作怎么变、最后停在什么样子，能看清的字原样写出来。"
    "不要逐格罗列，连起来用几句话说清动作过程；不要提拼图、格子、截图、帧数。\n"
    "</system_notice>"
)


def _font(size: int):
    from PIL import ImageFont

    for p in _CJK_FONTS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


# ------------------------------------------------------------ 时间轴
def timeline(im) -> tuple[list[int], int]:
    """每帧显示多少毫秒，和第一帧是第几帧（APNG 可以带一张不参与播放的封面）。"""
    n = getattr(im, "n_frames", 1)
    first = 1 if im.info.get("default_image") else 0
    count = n - first
    if count <= 0:
        return [DEFAULT_DELAY_MS], 0

    def delay() -> int:
        d = im.info.get("duration") or 0
        try:
            d = int(d)
        except (TypeError, ValueError):
            d = 0
        return d if d >= MIN_DELAY_MS else DEFAULT_DELAY_MS

    if count > MAX_TIMELINE_FRAMES:
        im.seek(first)
        return [delay()] * count, first
    durs = []
    for i in range(first, n):
        im.seek(i)
        durs.append(delay())
    return durs, first


def sample_times(durs: list[int], count: int) -> list[int]:
    """在一轮播放的时间轴上均匀取 count 个点，返回那时正在显示的帧（相对第一帧的序号，升序去重，含最后一帧）。"""
    starts, t = [], 0
    for d in durs:
        starts.append(t)
        t += d
    total = t
    count = max(1, count)
    picks = {bisect.bisect_right(starts, total * k / count) - 1 for k in range(count)}
    picks.add(len(durs) - 1)
    return sorted(p for p in picks if 0 <= p < len(durs))


def _flat(im, bg=(255, 255, 255)):
    from PIL import Image

    rgba = im.convert("RGBA")
    out = Image.new("RGB", rgba.size, bg)
    out.paste(rgba, mask=rgba.getchannel("A"))
    return out


def _same(a, b, mean_diff: float, block_diff: float) -> bool:
    import numpy as np

    d = np.abs(a - b)
    return d.mean() <= mean_diff and d.reshape(8, 8, 8, 8).mean(axis=(1, 3)).max() <= block_diff


def pick_cells(im, max_frames: int = 8, mean_diff: float = 1.0, block_diff: float = 2.5):
    """取出画面有变化的格子（最多 max_frames×2 个，还没挑）。返回 (cells, info)：
    cells = [(序号, 开始毫秒, 结束毫秒, RGB 图)]，info = {total_ms, frames}。只剩一格说明这张动图其实不动。"""
    import numpy as np

    durs, first = timeline(im)
    starts = [0]
    for d in durs[:-1]:
        starts.append(starts[-1] + d)
    total = starts[-1] + durs[-1]
    cand = sample_times(durs, max(2, max_frames) * 2)
    cells, last = [], None  # [idx, start, end, img]
    for idx in cand:
        im.seek(first + idx)
        img = _flat(im)
        g = np.asarray(img.convert("L").resize((64, 64)), dtype=np.float32)
        end = starts[idx] + durs[idx]
        if last is not None and _same(g, last, mean_diff, block_diff):
            cells[-1][2] = end
            img.close()
            continue
        cells.append([idx, starts[idx], end, img])
        last = g
    return [tuple(c) for c in cells], {"total_ms": total, "frames": len(durs)}


# ------------------------------------------------------------ 排版
def _secs(ms: float, total: float = 0) -> str:
    if total and total < 1000:  # 不到一秒的小动图，0.1 秒分不开
        return f"{ms / 1000:.2f}s"
    return f"{ms / 1000:.1f}s" if ms < 10000 else f"{ms / 1000:.0f}s"


def layout(n: int, w: int, h: int, max_edge: int, band_ratio: float = 0.1, head: int = 0):
    """n 格、每格 w×h，放进 max_edge×max_edge：选让格子最大的列数（一样大就少留空格）。返回 (cols, rows, scale)。"""
    best = None
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        scale = min(max_edge / (cols * w), (max_edge - head) / (rows * h * (1 + band_ratio)))
        key = (round(scale, 4), -(cols * rows - n))
        if best is None or key > best[0]:
            best = (key, cols, rows, scale)
    return best[1], best[2], best[3]


def render(cells, info, max_edge: int = 1280, min_cell: int = 320, max_up: float = 2.0):
    """把格子拼成一张图（RGB），最上面一行写总时长和帧数，每格上方写序号和时间。"""
    from PIL import Image, ImageDraw

    n = len(cells)
    w, h = cells[0][3].size
    head = max(20, int(max_edge * 0.025))
    cols, rows, scale = layout(n, w, h, max_edge, head=head)
    up = min(max_up, max(1.0, min_cell / max(w, h)))  # 小表情放大一点，不超过 2 倍
    scale = min(scale, up)
    for _ in range(3):  # 标签条有最小高度，很扁的图加上它会超出上限：再缩一点
        cw, ch = max(1, int(w * scale)), max(1, int(h * scale))
        band = max(16, int(ch * 0.1))
        over = max(cols * cw, head + rows * (ch + band)) / max_edge
        if over <= 1:
            break
        scale /= over * 1.01
    width = cols * cw
    sheet = Image.new("RGB", (width, head + rows * (ch + band)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)

    total = info["total_ms"]
    title = f"动图 · 一轮{_secs(total)} · 共{info['frames']}帧 · 按时间取了{n}格"
    size = max(12, int(head * 0.7))
    font = _font(size)
    while size > 9 and draw.textlength(title, font=font) > width - 8:
        size -= 1
        font = _font(size)
    draw.rectangle((0, 0, width, head - 1), fill=(40, 40, 40))
    draw.text((4, head // 2), title, fill=(255, 255, 255), font=font, anchor="lm")

    lab_size = max(11, int(band * 0.72))
    lab_font = _font(lab_size)
    for i, (_idx, s, e, img) in enumerate(cells):
        x, y = (i % cols) * cw, head + (i // cols) * (ch + band)
        cell = img if img.size == (cw, ch) else img.resize((cw, ch), Image.Resampling.LANCZOS)
        sheet.paste(cell, (x, y + band))
        if cell is not img:
            cell.close()
        held = e - s
        label = f"{i + 1} · {_secs(s, total)}"
        if n > 1 and held >= max(400, total * 0.2):
            label = f"{i + 1} · {_secs(s, total)}–{_secs(e, total)} 停住"
        lf, ls = lab_font, lab_size
        while ls > 9 and draw.textlength(label, font=lf) > cw - 6:
            ls -= 1
            lf = _font(ls)
        draw.text((x + 4, y + band // 2), label, fill=(255, 255, 255), font=lf, anchor="lm")
    return sheet


def thin(cells, keep_n: int):
    """格子太多：均匀挑 keep_n 个，头尾都留。没挑上的图 close 掉。"""
    if len(cells) <= keep_n:
        return cells
    keep = {round(i * (len(cells) - 1) / (keep_n - 1)) for i in range(keep_n)} if keep_n > 1 else {0}
    for i, c in enumerate(cells):
        if i not in keep:
            c[3].close()
    return [c for i, c in enumerate(cells) if i in keep]


def build(im, max_edge: int = 1280, max_frames: int = 8):
    """返回 (图, 是不是动图)。其实不动的动图返回第一格当普通图片。调用方负责 close。"""
    cells, info = pick_cells(im, max_frames)
    if len(cells) == 1:
        return cells[0][3], False
    if len(cells) > max_frames:  # 排出来的格子有空位就多放一两格，不留黑块
        w, h = cells[0][3].size
        cols, rows, _ = layout(max_frames, w, h, max_edge, head=max(20, int(max_edge * 0.025)))
        cells = thin(cells, min(len(cells), cols * rows))
    try:
        return render(cells, info, max_edge), True
    finally:
        for c in cells:
            c[3].close()


# ------------------------------------------------------------ 换掉 AstrBot 自带的
