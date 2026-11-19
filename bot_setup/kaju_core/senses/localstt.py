"""本地语音转文字：sherpa-onnx + SenseVoiceSmall（int8，CPU 跑），代替要钱的硅基流动接口（2026-11-01 欠费 402）。

- 模型：k2-fsa/sherpa-onnx 官方 release 的 sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
  （中/英/日/韩/粤，带标点；2025-09-09 那版在样例上把所有语言都认成粤语，不用）。
- 长音频：先用 silero VAD 按停顿切成一句句（每句最多 max_seconds 秒）再识别，SenseVoice 一次吃太长会变差；
  VAD 一句都没切出来（比如整段是音乐）就按固定长度硬切。
- 同一时间只跑一个识别（CPU 吃满了并行也不快），这里不依赖 AstrBot，方便离线测试。
"""

from __future__ import annotations

import os
import threading
import time

import numpy as np

RATE = 16000


def read_audio(path: str, rate: int = RATE) -> np.ndarray:
    """任何 PyAV 能打开的音频/视频 → 16kHz 单声道 float32（-1~1）。"""
    import av

    out = []
    with av.open(path) as c:
        if not c.streams.audio:
            return np.zeros(0, dtype=np.float32)
        rs = av.AudioResampler(format="s16", layout="mono", rate=rate)
        for frame in c.decode(c.streams.audio[0]):
            for f in rs.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


def fixed_windows(samples: np.ndarray, seconds: float, rate: int = RATE) -> list[np.ndarray]:
    n = max(1, int(seconds * rate))
    return [samples[i:i + n] for i in range(0, len(samples), n)]


def join_texts(texts: list[str]) -> str:
    """一句句接起来：中日文直接连，英文之类的中间加空格。"""
    out = ""
    for t in (x.strip() for x in texts):
        if not t:
            continue
        if out and out[-1].isascii() and (out[-1].isalnum() or out[-1] in ".,!?;:") and t[0].isascii() and t[0].isalnum():
            out += " "
        out += t
    return out


class SenseVoice:
    def __init__(self, model_dir: str, vad_model: str = "", threads: int = 4, max_seconds: float = 25):
        self.model_dir, self.vad_model = model_dir, vad_model
        self.threads, self.max_seconds = max(1, int(threads)), float(max_seconds)
        self._rec = None
        self._lock = threading.Lock()
        self._last = 0.0  # 上次识别完的时间（闲置太久就把模型放掉，约 300 MB 内存）

    def check(self) -> str:
        """模型文件齐不齐，缺了返回原因。"""
        for name in ("model.int8.onnx", "tokens.txt"):
            if not os.path.isfile(os.path.join(self.model_dir, name)):
                return f"找不到 {os.path.join(self.model_dir, name)}"
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return "没装 sherpa-onnx（pip install sherpa-onnx）"
        return ""

    def load(self) -> None:
        import sherpa_onnx

        with self._lock:
            self._last = time.time()  # 刚加载的不算闲置（免得刚加载完就被 release_if_idle 放掉）
            if self._rec is None:
                self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=os.path.join(self.model_dir, "model.int8.onnx"),
                    tokens=os.path.join(self.model_dir, "tokens.txt"),
                    num_threads=self.threads, use_itn=True, language="auto")

    def segments(self, samples: np.ndarray) -> list[np.ndarray]:
        """短的整段；长的用 VAD 按停顿切句，切不出来就按固定长度切。"""
        if len(samples) <= self.max_seconds * RATE:
            return [samples] if len(samples) else []
        if not self.vad_model or not os.path.isfile(self.vad_model):
            return fixed_windows(samples, self.max_seconds)
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = self.vad_model
        cfg.silero_vad.min_silence_duration = 0.3
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.max_speech_duration = self.max_seconds
        cfg.sample_rate = RATE
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=len(samples) / RATE + 10)
        w = cfg.silero_vad.window_size
        out = []
        for i in range(0, len(samples), w):
            vad.accept_waveform(samples[i:i + w])
            while not vad.empty():
                out.append(np.array(vad.front.samples, dtype=np.float32))
                vad.pop()
        vad.flush()
        while not vad.empty():
            out.append(np.array(vad.front.samples, dtype=np.float32))
            vad.pop()
        return out or fixed_windows(samples, self.max_seconds)

    def transcribe_samples(self, samples: np.ndarray) -> str:
        texts = []
        for seg in self.segments(samples):
            self.load()
            with self._lock:
                s = self._rec.create_stream()
                s.accept_waveform(RATE, seg)
                self._rec.decode_stream(s)
                texts.append(s.result.text)
                self._last = time.time()
        return join_texts(texts)

    def release_if_idle(self, idle_seconds: float) -> bool:
        """Drop the loaded model if nothing was transcribed for idle_seconds (it reloads on next use).

        Returns:
            True when the model was released just now.
        """
        with self._lock:
            if self._rec is None or time.time() - self._last < idle_seconds:
                return False
            self._rec = None
            return True

    def transcribe(self, path: str) -> str:
        return self.transcribe_samples(read_audio(path))
