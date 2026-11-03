"""
Hayamimi Polyglot - Parakeet TDT 0.6B v3 (en / fr / de / es ...) on the Intel NPU.

Uses the OpenVINO IR export of NVIDIA's model (FluidInference/parakeet-tdt-0.6b-v3-ov):
mel front-end, decoder and joint run on the CPU plugin, the FastConformer encoder on the NPU
(fixed 15 s window). Token-and-duration transducer (TDT) greedy decoding.

Model: NVIDIA Parakeet TDT 0.6B v3, CC-BY-4.0 (see Third_Party_Notices.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np

from .base import NpuRecognizerBase, SAMPLE_RATE, compile_cpu, compile_npu, npu_models_dir

MODEL_DIRNAME = "parakeet"
WINDOW_SAMPLES = 240000  # 15 s, fixed by the exported mel/encoder graphs
BLANK_ID = 8192
MAX_SYMBOLS_PER_FRAME = 10

_FILES = (
    "parakeet_melspectogram.xml", "parakeet_melspectogram.bin",
    "parakeet_encoder.xml", "parakeet_encoder.bin",
    "parakeet_decoder.xml", "parakeet_decoder.bin",
    "parakeet_joint.xml", "parakeet_joint.bin",
    "parakeet_v3_vocab.json",
)


def model_files_present(models_dir: Path | str | None = None) -> bool:
    d = npu_models_dir(models_dir) / MODEL_DIRNAME
    return all((d / n).is_file() for n in _FILES)


class ParakeetNpuRecognizer(NpuRecognizerBase):
    name = "parakeet"
    window_seconds = WINDOW_SAMPLES / SAMPLE_RATE

    def __init__(self, models_dir: Path | str | None = None):
        super().__init__()
        d = npu_models_dir(models_dir) / MODEL_DIRNAME
        vocab = json.loads((d / "parakeet_v3_vocab.json").read_text(encoding="utf-8"))
        self._vocab = {int(k): v for k, v in vocab.items()}
        self._mel = compile_cpu(d / "parakeet_melspectogram.xml")
        self._decoder = compile_cpu(d / "parakeet_decoder.xml")
        self._joint = compile_cpu(d / "parakeet_joint.xml")
        self._encoder = compile_npu(d / "parakeet_encoder.xml")
        self.warmup()

    def _transcribe_window(self, pcm: np.ndarray) -> str:
        n = min(len(pcm), WINDOW_SAMPLES)
        x = np.zeros((1, WINDOW_SAMPLES), dtype=np.float32)
        x[0, :n] = pcm[:n]
        mel = self._mel({"input_signals": x, "input_length": np.array([n], dtype=np.int64)})
        enc = self._encoder({"melspectogram": mel[0], "melspectogram_length": mel[1].astype(np.int32)})
        frames = enc[0][0].T  # (T, 1024)
        total = int(enc[1][0])

        h = np.zeros((2, 1, 640), dtype=np.float32)
        c = h.copy()
        d = self._decoder({"targets": np.array([[BLANK_ID]], dtype=np.int64), "h_in": h, "c_in": c})
        dec_out, h, c = d[0], d[1], d[2]
        ids: List[int] = []
        t, emitted = 0, 0
        while t < total:
            logits = self._joint({"encoder_outputs": frames[t][None, None], "decoder_outputs": dec_out})[0][0, 0, 0]
            tok = int(logits[: BLANK_ID + 1].argmax())
            dur = int(logits[BLANK_ID + 1:].argmax())
            if tok != BLANK_ID:
                ids.append(tok)
                d = self._decoder({"targets": np.array([[tok]], dtype=np.int64), "h_in": h, "c_in": c})
                dec_out, h, c = d[0], d[1], d[2]
                emitted += 1
            if dur == 0 and (tok == BLANK_ID or emitted >= MAX_SYMBOLS_PER_FRAME):
                dur = 1
            if dur > 0:
                emitted = 0
            t += dur
        return "".join(self._vocab.get(i, "") for i in ids).replace("▁", " ").strip()
