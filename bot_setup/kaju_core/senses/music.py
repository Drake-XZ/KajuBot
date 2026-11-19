"""听音乐：把一段音乐交给 soundcheck 引擎量一遍，再翻成佳树自己耳朵听到的感觉。

引擎是 dsh-soundcheck 0.9.10 的 engine/analyze.py（MIT，作者 ALittleLov，放在 soundcheck/；本地改了三处，都标着"kaju_basics 改动"：模型路径、
标签模型分批打分、ONNX 不留内存池——5 分半的歌内存峰值 3.8 GB → 1.3 GB，结果不变）。
它在本机量出速度、能量怎么走、哪段最满、像什么乐器、偏亮偏暗，不上传音频。
在单独的子进程里跑（librosa/numba 加载后要占几百 MB），跑完就退出，机器人本身不多占内存。

这里只放不依赖 AstrBot 的部分：认音乐文件、判断 B 站视频是不是音乐、转 wav、跑引擎、挑出有用的几行。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LISTEN_MARK = "音乐听感（佳树自己从头听下来的）："
ENGINE = os.path.join(HERE, "soundcheck", "analyze.py")
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".ape", ".aiff", ".aif"}

# B 站分区名（tname）里带这些的算音乐视频
MUSIC_AREAS = ("音乐", "翻唱", "演奏", "VOCALOID", "UTAU", "MV", "原创", "乐评", "说唱", "电音", "宅舞")
# 标题、标签里出现这些也算（"原创"单独出现不算：原创动画、原创视频太多）
MUSIC_TITLE = re.compile(
    r"翻唱|演奏|弹奏|弹唱|钢琴|吉他|小提琴|古筝|二胡|琵琶|笛子|伴奏|纯音乐|轻音乐|BGM|OST|原声|主题曲|片尾曲|片头曲|插曲"
    r"|MV|PV|[Cc]over|COVER|[Ll]ive|LIVE|演唱会|音乐|歌曲|单曲|新歌|原创曲|原创歌|作曲|编曲|唱了|唱的|试唱|乐队|合唱|打谱|扒带|琴谱"
    r"|[《「].{1,20}[》」].{0,4}(钢琴|吉他|翻唱|cover)"
)
# 对方说的话里提到歌、音乐：直接发来的视频也听一下音乐
MUSIC_ASK = re.compile(r"歌|曲子|曲儿|音乐|旋律|伴奏|BGM|bgm|配乐|好听|听听|听一下|听下|唱|弹的|演奏|编曲|节奏|调子")


def is_audio(name: str) -> bool:
    ext = os.path.splitext((name or "").split("?", 1)[0])[1].lower()
    return ext in AUDIO_EXTS


def is_music_video(info: dict) -> bool:
    """B 站页面信息 → 是不是音乐视频（分区、标签、标题任一看得出来就算）。"""
    area = str(info.get("area") or "")
    if any(a in area for a in MUSIC_AREAS):
        return True
    text = " ".join([str(info.get("title") or ""), str(info.get("part_title") or "")] + [str(t) for t in info.get("tags") or []])
    return bool(MUSIC_TITLE.search(text))


def asks_music(text: str) -> bool:
    return bool(MUSIC_ASK.search(text or ""))


def to_wav(src: str, dst: str, max_seconds: float = 600, rate: int = 44100) -> float:
    """任意音频/视频 → 44.1kHz 立体声 16 位 wav（引擎用 soundfile 读，读不了 mp3 里的 aac、mp4 这些）。
    最多转前 max_seconds 秒（<=0 = 全部），返回转了多少秒；没有声音返回 0（不写文件）。"""
    import wave

    import av

    limit = int(max_seconds * rate) if max_seconds and max_seconds > 0 else None
    frames = 0
    with av.open(src) as c:
        if not c.streams.audio:
            return 0.0
        rs = av.AudioResampler(format="s16", layout="stereo", rate=rate)
        with wave.open(dst, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)

            def pcm():
                for fr in c.decode(c.streams.audio[0]):
                    yield from rs.resample(fr)
                yield from rs.resample(None)

            for f in pcm():
                data = f.to_ndarray().tobytes()  # packed s16 stereo
                n = len(data) // 4
                if limit is not None and frames + n > limit:
                    n = max(0, limit - frames)
                    data = data[: n * 4]
                w.writeframes(data)
                frames += n
                if limit is not None and frames >= limit:
                    break
    if frames == 0:
        try:
            os.remove(dst)
        except OSError:
            pass
    return frames / rate


def engine_env(data_dir: str, threads: int = 2) -> dict:
    env = dict(os.environ)
    t = str(max(1, int(threads)))
    env.update({
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "DSH_AUDIO_DATA_DIR": data_dir,  # 节拍模型在 <data_dir>\models\beat_this，两个声源模型在 <data_dir>
        "OPENBLAS_NUM_THREADS": t, "OMP_NUM_THREADS": t, "NUMBA_NUM_THREADS": t, "MKL_NUM_THREADS": t,
    })
    return env


def python_exe(configured: str = "") -> str:
    """跑引擎用的 Python：配置里填的，否则就是机器人自己这个（pythonw 换成 python，免得没有输出）。"""
    if configured and os.path.isfile(configured):
        return configured
    exe = sys.executable or "python"
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(alt):
            exe = alt
    return exe


def run_engine(wav: str, data_dir: str, python: str = "", timeout: float = 180, threads: int = 2) -> str:
    """跑一遍 analyze.py，返回它的文字报告；失败抛 RuntimeError（带 stderr 最后几行）。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([python_exe(python), "-I", ENGINE, wav], capture_output=True, timeout=timeout,
                           env=engine_env(data_dir, threads), creationflags=flags)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"分析超过 {timeout:g} 秒没跑完") from None
    out = p.stdout.decode("utf-8", "replace").strip()
    if p.returncode != 0 or not out:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"分析程序退出码 {p.returncode}：{' | '.join(err[-3:])[:300]}")
    return out


# 报告里给模型看的段：[判断] 已经是人话；[状态][四维] 是推测的快慢明暗；[标签] 是模型猜的；
# [能量] 那一行小方块是每段多满；[钩子] 是最满最密的位置；[听不到] 提醒测不出什么。
# 不要的：[依据][可信]（分贝、LUFS、置信分数）、[结构]（一串边界时间）、[时间线]（分频段 dB 明细）、[读法]。
KEEP = ("判断", "状态", "四维", "标签", "能量", "钩子", "听不到")


def pick(report: str, tag_min: float = 0.5) -> str:
    """从引擎的文字报告里挑出给模型看的几段（续行跟着它的段走）。
    [标签] 只留分数 >= tag_min 的：2026-11-04 实测钢琴曲 piano 0.96 很准，
    而 YOASOBI 的翻唱和摇滚现场被标成 techno 0.43 / 0.25，她就说成"偏电子"。"""
    out, keep = [], False
    for line in report.splitlines():
        m = re.match(r"\s*\[([^\]]+)\]", line)
        if m:
            keep = m.group(1) in KEEP
            if m.group(1) == "标签":
                strong = [f"{t} {s}" for t, s in re.findall(r"([A-Za-z][A-Za-z ]+?)\s+(\d+(?:\.\d+)?)", line)
                          if float(s) >= tag_min]
                if not strong:
                    keep = False
                    continue
                line = "[标签] 模型预测的英文标签（只留了把握大的）：" + "、".join(strong)
        if keep and line.strip():
            if line.lstrip().startswith("说明："):
                continue
            out.append(line.rstrip())
    return "\n".join(out)


def tags(report: str) -> list[str]:
    """[标签] 行里的英文标签（给日志看）。"""
    m = re.search(r"\[标签\][^:：]*[:：]\s*(.+)", report)
    return re.findall(r"([A-Za-z][A-Za-z ]+?)\s+\d", m.group(1)) if m else []
