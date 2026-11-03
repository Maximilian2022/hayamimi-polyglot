"""
Hayamimi Polyglot - NumPy-only audio front-ends for the NPU backends.

Why NumPy only: the NPU add-on must not introduce any new native (.pyd/.dll)
dependency. Windows Smart App Control (SAC) blocks unsigned binaries it has no
reputation for, so feature extraction is implemented here with NumPy instead of
kaldi-native-fbank. The results are numerically compatible with Kaldi fbank
(snip_edges=False), which is what the models were trained/exported with.
"""

from __future__ import annotations

import numpy as np

_EPSILON = float(np.finfo(np.float32).eps)


def _mel_scale(freq):
    return 1127.0 * np.log(1.0 + freq / 700.0)


def _mel_banks(num_bins: int, fft_size: int, sample_rate: int, low_freq: float, high_freq: float) -> np.ndarray:
    """Kaldi triangular mel filter bank, shape (num_bins, fft_size // 2 + 1)."""
    nyquist = 0.5 * sample_rate
    if high_freq <= 0.0:
        high_freq += nyquist
    num_fft_bins = fft_size // 2
    fft_bin_width = sample_rate / fft_size
    mel_low, mel_high = _mel_scale(low_freq), _mel_scale(high_freq)
    delta = (mel_high - mel_low) / (num_bins + 1)

    freqs = fft_bin_width * np.arange(num_fft_bins)
    mel = _mel_scale(freqs)[None, :]
    b = np.arange(num_bins)[:, None]
    left = mel_low + b * delta
    center = mel_low + (b + 1.0) * delta
    right = mel_low + (b + 2.0) * delta
    up = (mel - left) / (center - left)
    down = (right - mel) / (right - center)
    banks = np.maximum(0.0, np.minimum(up, down))
    out = np.zeros((num_bins, fft_size // 2 + 1), dtype=np.float64)
    out[:, :num_fft_bins] = banks
    return out


_BANK_CACHE: dict = {}
_WINDOW_CACHE: dict = {}


def _get_bank(num_bins, fft_size, sample_rate, low_freq, high_freq):
    key = (num_bins, fft_size, sample_rate, low_freq, high_freq)
    if key not in _BANK_CACHE:
        _BANK_CACHE[key] = _mel_banks(num_bins, fft_size, sample_rate, low_freq, high_freq)
    return _BANK_CACHE[key]


def _get_window(kind: str, n: int) -> np.ndarray:
    key = (kind, n)
    if key not in _WINDOW_CACHE:
        i = np.arange(n, dtype=np.float64)
        if kind == "hamming":
            w = 0.54 - 0.46 * np.cos(2 * np.pi * i / (n - 1))
        elif kind == "povey":
            w = (0.5 - 0.5 * np.cos(2 * np.pi * i / (n - 1))) ** 0.85
        else:
            raise ValueError(f"unsupported window type: {kind}")
        _WINDOW_CACHE[key] = w
    return _WINDOW_CACHE[key]


def kaldi_fbank(
    samples: np.ndarray,
    *,
    sample_rate: int = 16000,
    num_bins: int = 80,
    window: str = "povey",
    low_freq: float = 20.0,
    high_freq: float = -400.0,
    frame_length_ms: float = 25.0,
    frame_shift_ms: float = 10.0,
    preemphasis: float = 0.97,
    scale: float = 1.0,
) -> np.ndarray:
    """
    Kaldi-compatible log-mel filterbank (snip_edges=False, dither=0, power spectrum).

    Args:
        samples: float32/float64 mono waveform. Multiplied by `scale` first
                 (SenseVoice expects 16-bit scale, i.e. scale=32768).
    Returns:
        (num_frames, num_bins) float32.
    """
    x = np.asarray(samples, dtype=np.float64) * scale
    n = len(x)
    frame_len = int(sample_rate * frame_length_ms / 1000.0)
    frame_shift = int(sample_rate * frame_shift_ms / 1000.0)
    num_frames = (n + frame_shift // 2) // frame_shift
    if num_frames <= 0:
        return np.zeros((0, num_bins), dtype=np.float32)

    # Frame start positions with Kaldi's centred framing + reflection at the edges.
    starts = np.arange(num_frames) * frame_shift + frame_shift // 2 - frame_len // 2
    idx = starts[:, None] + np.arange(frame_len)[None, :]
    idx = np.where(idx < 0, -idx - 1, idx)
    idx = np.where(idx >= n, 2 * n - 1 - idx, idx)
    idx = np.clip(idx, 0, n - 1)
    frames = x[idx]

    frames = frames - frames.mean(axis=1, keepdims=True)  # remove DC offset
    if preemphasis != 0.0:
        prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
        frames = frames - preemphasis * prev
    frames = frames * _get_window(window, frame_len)[None, :]

    fft_size = 1
    while fft_size < frame_len:
        fft_size <<= 1
    spec = np.fft.rfft(frames, n=fft_size, axis=1)
    power = spec.real ** 2 + spec.imag ** 2
    bank = _get_bank(num_bins, fft_size, sample_rate, low_freq, high_freq)
    mel = power @ bank.T
    return np.log(np.maximum(mel, _EPSILON)).astype(np.float32)


def lfr_cmvn(
    fbank: np.ndarray,
    neg_mean: np.ndarray,
    inv_stddev: np.ndarray,
    window_size: int = 7,
    window_shift: int = 6,
) -> np.ndarray:
    """
    SenseVoice front-end tail: low-frame-rate stacking followed by CMVN.

    Mirrors sherpa-onnx's SenseVoice feature path: frames are stacked in groups
    of `window_size` every `window_shift`; the last group is padded by repeating
    the final frame, then (x + neg_mean) * inv_stddev is applied.
    """
    t = fbank.shape[0]
    if t == 0:
        return np.zeros((0, fbank.shape[1] * window_size), dtype=np.float32)
    out_len = (t - window_size) // window_shift + 1 if t >= window_size else 1
    rows = []
    for i in range(out_len):
        chunk = fbank[i * window_shift: i * window_shift + window_size]
        if len(chunk) < window_size:
            chunk = np.concatenate([chunk, np.repeat(chunk[-1:], window_size - len(chunk), axis=0)], axis=0)
        rows.append(chunk.reshape(-1))
    feats = np.stack(rows).astype(np.float32)
    return ((feats + neg_mean) * inv_stddev).astype(np.float32)
