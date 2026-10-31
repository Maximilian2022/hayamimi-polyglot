"""
Hayamimi For Business - Core ASR Engine.
Uses ReazonSpeech INT8 Zipformer via sherpa-onnx.
Zero recording to disk. Pure in-memory streaming.
Includes both Hotwords bias and post-decoding business dictionary replacement.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import sherpa_onnx

from .dictionary import BusinessDictionary


def _find_file(directory: Path, pattern: str) -> Optional[Path]:
    matches = list(directory.glob(pattern))
    return matches[0] if matches else None


class BusinessASREngine:
    """
    Offline/Segmented ASR Engine for Business meetings.
    Optimized for 3-5 year old corporate laptops (Core i5 / Ryzen 5 CPU only).
    """

    def __init__(
        self,
        models_dir: Path | str | None = None,
        hotwords_file: Path | str | None = None,
        threads: int = 2,
    ):
        if models_dir is None:
            candidates = [
                Path(__file__).resolve().parent.parent / "models",
                Path(__file__).resolve().parent.parent.parent / "models",
                Path("models"),
            ]
            for c in candidates:
                if c.is_dir() and (c / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17").is_dir():
                    models_dir = c
                    break

        self.models_dir = Path(models_dir) if models_dir else Path("models")
        self.threads = threads
        self.hotwords_file = Path(hotwords_file) if hotwords_file else None

        self.recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None
        self.dictionary = BusinessDictionary()
        self.replacement_rules: Dict[str, str] = {}

        self._init_recognizer()

    def _init_recognizer(self) -> None:
        """Initialize sherpa-onnx offline recognizer with ReazonSpeech INT8 model."""
        rz_dir = self.models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
        if not rz_dir.is_dir():
            print(f"[ASR] Warning: ReazonSpeech model directory not found at {rz_dir}")
            return

        encoder = _find_file(rz_dir, "*encoder*int8*.onnx") or _find_file(rz_dir, "*encoder*.onnx")
        decoder = _find_file(rz_dir, "*decoder*int8*.onnx") or _find_file(rz_dir, "*decoder*.onnx")
        joiner = _find_file(rz_dir, "*joiner*int8*.onnx") or _find_file(rz_dir, "*joiner*.onnx")
        tokens = rz_dir / "tokens.txt"

        if not (encoder and decoder and joiner and tokens.is_file()):
            print("[ASR] Incomplete model files in", rz_dir)
            return

        hw_file_str = str(self.hotwords_file) if (self.hotwords_file and self.hotwords_file.is_file()) else ""

        try:
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=self.threads,
                model_type="",
                decoding_method="modified_beam_search",
                hotwords_file=hw_file_str,
                hotwords_score=2.0,
                modeling_unit="cjkchar",
            )
        except Exception as exc:
            print(f"[ASR] Failed to initialize sherpa-onnx recognizer: {exc}")

    def update_hotwords(self, hotwords_file: Path | str) -> None:
        """Update hotwords and reload recognizer."""
        self.hotwords_file = Path(hotwords_file)
        self._init_recognizer()

    def set_replacements(self, rules: Dict[str, str]) -> None:
        """Set post-decoding word replacement rules (e.g., misheard words to correct terms)."""
        self.replacement_rules = {k.strip(): v.strip() for k, v in rules.items() if k.strip()}

    def transcribe_pcm(self, pcm_16k_mono: np.ndarray) -> str:
        """
        Transcribe a 16kHz float32 mono audio segment.
        Returns final text with business dictionary normalization applied.
        """
        if self.recognizer is None or len(pcm_16k_mono) == 0:
            return ""

        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, pcm_16k_mono)
        self.recognizer.decode_stream(stream)
        raw_text = stream.result.text.strip()

        if not raw_text:
            return ""

        # Post-decoding dictionary replacement / normalization
        normalized_text = raw_text
        for misheard, correct in self.replacement_rules.items():
            if misheard in normalized_text:
                normalized_text = normalized_text.replace(misheard, correct)

        return normalized_text
