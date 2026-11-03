"""
Hayamimi Polyglot - SenseVoice Small (zh / ko / ...) on the Intel NPU.

The whole network runs on the NPU in a fixed 15 s window. Its LayerNorm blocks were
rescaled when the model was built (see scripts/build_npu_models.py) because the original
overflows fp16, which NPUs use. CTC output is decoded greedily on the CPU.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

import numpy as np

from .base import NpuRecognizerBase, compile_npu, npu_models_dir, squeeze_cjk_spaces
from .features import kaldi_fbank, lfr_cmvn

MODEL_DIRNAME = "sensevoice"
SPECIAL_PREFIX = 4  # language / event / emotion / text-norm tokens at the start of the output
_HANGUL = re.compile(r"[ᄀ-ᇿ가-힯]")


def model_files_present(models_dir: Path | str | None = None) -> bool:
    d = npu_models_dir(models_dir) / MODEL_DIRNAME
    return all((d / n).is_file() for n in ("model.xml", "model.bin", "tokens.txt", "meta.json"))


def ctc_greedy(logits: np.ndarray, valid: int) -> List[int]:
    ids = logits[SPECIAL_PREFIX: SPECIAL_PREFIX + valid].argmax(-1)
    out, prev = [], -1
    for i in ids:
        i = int(i)
        if i != prev and i != 0:
            out.append(i)
        prev = i
    return out


class SenseVoiceNpuRecognizer(NpuRecognizerBase):
    name = "sensevoice"

    def __init__(self, models_dir: Path | str | None = None):
        super().__init__()
        d = npu_models_dir(models_dir) / MODEL_DIRNAME
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.lfr_frames = int(meta["lfr_frames"])
        self._neg_mean = np.asarray(meta["neg_mean"], dtype=np.float32)
        self._inv_std = np.asarray(meta["inv_stddev"], dtype=np.float32)
        self._lang_auto = int(meta.get("lang_auto", 0))
        self._with_itn = int(meta.get("with_itn", 14))
        # a window of N seconds has N*100 fbank frames; LFR divides that by 6
        self.window_seconds = (self.lfr_frames * 6 + 6) / 100.0 - 0.1
        self._tokens: List[str] = []
        for line in (d / "tokens.txt").read_text(encoding="utf-8").splitlines():
            self._tokens.append(line.rsplit(" ", 1)[0])
        self._model = compile_npu(d / "model.xml")
        self.warmup()

    def _transcribe_window(self, pcm: np.ndarray) -> str:
        fb = kaldi_fbank(pcm, window="hamming", low_freq=20.0, high_freq=0.0, scale=32768.0)
        feats = lfr_cmvn(fb, self._neg_mean, self._inv_std)
        n = min(len(feats), self.lfr_frames)
        if n == 0:
            return ""
        x = np.zeros((1, self.lfr_frames, 560), dtype=np.float32)
        x[0, :n] = feats[:n]
        logits = self._model({
            "x": x,
            "language": np.array([self._lang_auto], dtype=np.int32),
            "text_norm": np.array([self._with_itn], dtype=np.int32),
        })[0][0]
        ids = ctc_greedy(logits, n)
        text = "".join(self._tokens[i] for i in ids).replace("▁", " ").strip()
        # Korean keeps its word spaces; everything else (zh / ja) is written without them.
        return text if _HANGUL.search(text) else squeeze_cjk_spaces(text)
