"""
Hayamimi Polyglot - shared pieces of the NPU recognizers.

NPU recognizers expose the same tiny surface as sherpa-onnx's OfflineRecognizer
(`create_stream()` / `accept_waveform()` / `decode_stream()` / `stream.result.text`)
so `BusinessASREngine.transcribe_pcm` does not need to know which device it runs on.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import List

import numpy as np

from . import addons
from .device import get_core

SAMPLE_RATE = 16000


def npu_models_dir(models_dir: Path | str | None = None) -> Path:
    base = Path(models_dir) if models_dir else addons.models_root()
    return base / "npu"


def cache_dir() -> Path:
    d = addons.APP_ROOT / "cache" / "openvino"
    d.mkdir(parents=True, exist_ok=True)
    return d


def compile_npu(model_xml: Path, extra: dict | None = None):
    """Compile an OpenVINO IR on the NPU (compiled blobs are cached on disk)."""
    core = get_core()
    cfg = {"PERFORMANCE_HINT": "LATENCY", "CACHE_DIR": str(cache_dir())}
    if extra:
        cfg.update(extra)
    return core.compile_model(core.read_model(str(model_xml)), "NPU", cfg)


def compile_cpu(model_xml: Path, reshape: dict | None = None):
    core = get_core()
    model = core.read_model(str(model_xml))
    if reshape:
        model.reshape(reshape)
    return core.compile_model(model, "CPU", {"PERFORMANCE_HINT": "LATENCY"})


_SPACE_NOT_BETWEEN_ASCII = re.compile(r"(?<![!-~]) +| +(?![!-~])")


def squeeze_cjk_spaces(text: str) -> str:
    """Drop spaces except those between two printable ASCII characters (sherpa-onnx style for ja/zh)."""
    return _SPACE_NOT_BETWEEN_ASCII.sub("", re.sub(r" +", " ", text.strip()))


def resample_to_16k(a: np.ndarray, sample_rate: int) -> np.ndarray:
    """Band-limited resampling (windowed-sinc low-pass + linear interpolation) without SciPy."""
    if len(a) == 0 or sample_rate == SAMPLE_RATE:
        return a
    if sample_rate > SAMPLE_RATE:
        cutoff = 0.5 * SAMPLE_RATE / sample_rate  # fraction of the input sample rate
        taps = 8 * int(np.ceil(sample_rate / SAMPLE_RATE)) + 1
        n = np.arange(taps) - taps // 2
        h = np.sinc(2 * cutoff * n) * np.hamming(taps)
        h /= h.sum()
        a = np.convolve(a, h, mode="same").astype(np.float32)
    n_out = int(len(a) * SAMPLE_RATE / sample_rate)
    pos = np.arange(n_out) * (sample_rate / SAMPLE_RATE)
    return np.interp(pos, np.arange(len(a)), a).astype(np.float32)


class NpuStream:
    def __init__(self):
        self._chunks: List[np.ndarray] = []
        self.result = SimpleNamespace(text="", tokens=[])

    def accept_waveform(self, sample_rate: int, samples) -> None:
        a = np.asarray(samples, dtype=np.float32).reshape(-1)
        if sample_rate != SAMPLE_RATE:
            a = resample_to_16k(a, sample_rate)
        self._chunks.append(a)

    def waveform(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks) if len(self._chunks) > 1 else self._chunks[0]


def split_windows(pcm: np.ndarray, max_samples: int, search_samples: int = int(1.5 * SAMPLE_RATE)) -> List[np.ndarray]:
    """Split audio longer than the fixed NPU window, cutting at the quietest spot near the limit."""
    if len(pcm) <= max_samples:
        return [pcm]
    parts, start = [], 0
    hop = 160
    search_samples = max(min(search_samples, max_samples // 3), hop * 2)
    while len(pcm) - start > max_samples:
        lo = start + max_samples - search_samples
        seg = pcm[lo:start + max_samples]
        n = len(seg) // hop
        cut = start + max_samples
        if n > 1:
            energy = np.square(seg[: n * hop]).reshape(n, hop).mean(axis=1)
            cut = lo + int(np.argmin(energy)) * hop + hop // 2
        cut = min(max(cut, start + max_samples // 2), start + max_samples)  # always make progress
        parts.append(pcm[start:cut])
        start = cut
    parts.append(pcm[start:])
    return parts


class NpuRecognizerBase:
    """Subclasses implement `_transcribe_window(pcm) -> str` for audio that fits one NPU window."""

    name = "npu"
    window_seconds = 10.0
    joiner = " "

    def __init__(self):
        self._lock = threading.Lock()  # one NPU request at a time (the two audio tracks share it)

    def create_stream(self) -> NpuStream:
        return NpuStream()

    def decode_stream(self, stream: NpuStream) -> None:
        pcm = stream.waveform()
        if len(pcm) < int(0.1 * SAMPLE_RATE):
            stream.result.text = ""
            return
        texts = []
        for part in split_windows(pcm, int(self.window_seconds * SAMPLE_RATE)):
            if len(part) < int(0.1 * SAMPLE_RATE):
                continue
            with self._lock:
                t = self._transcribe_window(part)
            if t:
                texts.append(t)
        stream.result.text = self.joiner.join(texts).strip()

    def _transcribe_window(self, pcm: np.ndarray) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def warmup(self) -> None:
        """Run once on silence so the first real utterance does not pay one-time costs."""
        s = self.create_stream()
        s.accept_waveform(SAMPLE_RATE, np.zeros(SAMPLE_RATE, dtype=np.float32))
        self.decode_stream(s)
