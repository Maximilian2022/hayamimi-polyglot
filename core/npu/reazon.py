"""
Hayamimi Polyglot - ReazonSpeech (Japanese / English) on the Intel NPU.

Zipformer2 transducer. The encoder (fixed 15 s window, fp16) runs on the NPU; the tiny
decoder/joiner run on the OpenVINO CPU plugin. Tokens are byte-level BPE, so the
byte <-> character mapping of the training recipe is reproduced here.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Dict, List

import numpy as np

from .base import NpuRecognizerBase, compile_cpu, compile_npu, npu_models_dir, squeeze_cjk_spaces
from .features import kaldi_fbank

MODEL_DIRNAME = "reazon"
BLANK_ID = 0
CONTEXT_SIZE = 2
MAX_SYMBOLS_PER_FRAME = 3


def _build_byte_table() -> Dict[str, int]:
    # bytes 128..255 map, in order, to the first 128 NFKC-stable letters from U+0121 upward
    cps = [c for c in range(289, 900)
           if unicodedata.normalize("NFKC", chr(c)) == chr(c) and unicodedata.category(chr(c)).startswith("L")][:128]
    return {chr(c): 128 + i for i, c in enumerate(cps)}


_BYTE_OF_CHAR = _build_byte_table()


def decode_byte_bpe(text: str) -> str:
    b = bytearray()
    for ch in text:
        if ch in _BYTE_OF_CHAR:
            b.append(_BYTE_OF_CHAR[ch])
        elif ord(ch) < 128:
            b.append(ord(ch))
        else:
            b += ch.encode("utf-8")
    return b.decode("utf-8", errors="replace")


def encoder_out_len(num_frames: int) -> int:
    """Number of encoder output frames for `num_frames` fbank frames (zipformer2 subsampling)."""
    return max(((num_frames - 7) // 2 + 1) // 2, 0)


def model_files_present(models_dir: Path | str | None = None) -> bool:
    d = npu_models_dir(models_dir) / MODEL_DIRNAME
    return all((d / n).is_file() for n in ("encoder.xml", "encoder.bin", "decoder.xml", "joiner.xml", "tokens.txt", "meta.json"))


class ReazonNpuRecognizer(NpuRecognizerBase):
    name = "reazon"
    joiner = ""

    def __init__(self, models_dir: Path | str | None = None):
        super().__init__()
        d = npu_models_dir(models_dir) / MODEL_DIRNAME
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.frames = int(meta["frames"])
        self.window_seconds = self.frames / 100.0 - 0.01
        self._tokens: List[str] = []
        for line in (d / "tokens.txt").read_text(encoding="utf-8").splitlines():
            self._tokens.append(line.rsplit(" ", 1)[0])
        self._decoder = compile_cpu(d / "decoder.xml")
        self._joiner = compile_cpu(d / "joiner.xml")
        self._encoder = compile_npu(d / "encoder.xml")
        self.warmup()

    # -- transducer greedy search ---------------------------------------------
    def _greedy(self, enc: np.ndarray) -> List[int]:
        ctx = [BLANK_ID] * CONTEXT_SIZE
        out: List[int] = []
        dec_out = self._decoder({"y": np.array([ctx], dtype=np.int64)})[0]
        for e in enc:
            for _ in range(MAX_SYMBOLS_PER_FRAME):
                logits = self._joiner({"encoder_out": e[None], "decoder_out": dec_out})[0][0]
                k = int(logits.argmax())
                if k == BLANK_ID:
                    break
                out.append(k)
                ctx = ctx[1:] + [k]
                dec_out = self._decoder({"y": np.array([ctx], dtype=np.int64)})[0]
        return out

    def _transcribe_window(self, pcm: np.ndarray) -> str:
        fb = kaldi_fbank(pcm, window="povey", low_freq=20.0, high_freq=-400.0)
        n = min(len(fb), self.frames)
        x = np.full((1, self.frames, 80), fb.min() if len(fb) else 0.0, dtype=np.float32)
        x[0, :n] = fb[:n]
        enc = self._encoder({"x": x})[0][0]
        ids = self._greedy(enc[: encoder_out_len(n)])
        pieces = "".join(self._tokens[i] for i in ids).replace("▁", " ")
        return squeeze_cjk_spaces(decode_byte_bpe(pieces))
