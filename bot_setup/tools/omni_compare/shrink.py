r"""对比小测试第 2 步：云端模型收本地文件要小于约 7 MB，把大的视频压小（480 宽、每秒 5 帧、单声道），只听声音的抽成 mp3。
    <venv>\Scripts\python.exe -I shrink.py        → media\small\
"""
import json, os, shutil, sys
from fractions import Fraction

import av

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA, SMALL = os.path.join(HERE, "media"), os.path.join(HERE, "media", "small")
LIMIT = 6.5e6
os.makedirs(SMALL, exist_ok=True)


def audio_only(src, dst, kbps=64):
    with av.open(src) as i, av.open(dst, "w") as o:
        a = o.add_stream("mp3", rate=44100)
        a.bit_rate, a.layout = kbps * 1000, "stereo"
        rs = av.AudioResampler(format=a.format, layout="stereo", rate=44100)
        for fr in i.decode(audio=0):
            for r in rs.resample(fr):
                for p in a.encode(r):
                    o.mux(p)
        for r in rs.resample(None):
            for p in a.encode(r):
                o.mux(p)
        for p in a.encode():
            o.mux(p)


def video(src, dst, total_bps, fps=5, width=480):
    with av.open(src) as i, av.open(dst, "w") as o:
        vin = i.streams.video[0]
        h = int(round(vin.height * width / vin.width / 2)) * 2
        w = width if vin.width >= vin.height else int(round(vin.width * (width / max(vin.height, 1)) / 2)) * 2
        if vin.width < vin.height:
            h = width
        v = o.add_stream("libx264", rate=fps)
        v.width, v.height, v.pix_fmt = w, h, "yuv420p"
        v.bit_rate = max(40000, int(total_bps - 40000))
        v.options = {"preset": "slow"}
        has_a = bool(i.streams.audio)
        if has_a:
            a = o.add_stream("aac", rate=32000)
            a.bit_rate, a.layout = 40000, "mono"
            rs = av.AudioResampler(format=a.format, layout="mono", rate=32000)
        nxt, n = 0.0, 0
        for pkt in i.demux():
            for fr in pkt.decode():
                if pkt.stream.type == "video":
                    t = float(fr.pts * vin.time_base) if fr.pts is not None else nxt
                    if t + 1e-6 < nxt:
                        continue
                    nxt = max(nxt + 1 / fps, t)
                    f2 = fr.reformat(w, h, "yuv420p")
                    f2.pts, f2.time_base = n, Fraction(1, fps)
                    n += 1
                    for p in v.encode(f2):
                        o.mux(p)
                elif has_a and pkt.stream.type == "audio" and pkt.stream.index == i.streams.audio[0].index:
                    fr.pts = None
                    for r in rs.resample(fr):
                        for p in a.encode(r):
                            o.mux(p)
        for p in v.encode():
            o.mux(p)
        if has_a:
            for p in a.encode():
                o.mux(p)


for s in json.load(open(os.path.join(HERE, "samples.json"), encoding="utf-8")):
    src = os.path.join(MEDIA, s["id"] + s["ext"])
    if s.get("audio_only"):
        dst = os.path.join(SMALL, s["id"] + ".mp3")
        if not os.path.exists(dst):
            audio_only(src, dst)
    else:
        dst = os.path.join(SMALL, s["id"] + s["ext"])
        if not os.path.exists(dst):
            if os.path.getsize(src) <= LIMIT:
                shutil.copy(src, dst)
            else:
                with av.open(src) as c:
                    dur = float(c.duration / av.time_base)
                video(src, dst, LIMIT * 8 / dur * 0.93)
    print(s["id"], round(os.path.getsize(src) / 1e6, 1), "→", round(os.path.getsize(dst) / 1e6, 1), "MB")
