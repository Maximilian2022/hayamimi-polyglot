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
        self.high_accuracy_mode: bool = True  # Default: ON (Parakeet TDT v2 for English, SenseVoice for other languages)

        self.recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # ReazonSpeech fallback
        self.sense_voice_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # Multi-lingual ASR
        self.parakeet_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # High-accuracy English ASR

        self.dictionary = BusinessDictionary()
        self.replacement_rules: Dict[str, str] = {}

        self._init_recognizers()

    def _init_recognizers(self) -> None:
        """Initialize all available sherpa-onnx offline recognizers."""
        self._init_reazon()
        self._init_sense_voice()
        self._init_parakeet()

    def _init_reazon(self) -> None:
        """Initialize sherpa-onnx with ReazonSpeech INT8 model."""
        rz_dir = self.models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
        if not rz_dir.is_dir():
            print(f"[ASR] Warning: ReazonSpeech model directory not found at {rz_dir}")
            return

        encoder = _find_file(rz_dir, "*encoder*int8*.onnx") or _find_file(rz_dir, "*encoder*.onnx")
        decoder = _find_file(rz_dir, "*decoder*int8*.onnx") or _find_file(rz_dir, "*decoder*.onnx")
        joiner = _find_file(rz_dir, "*joiner*int8*.onnx") or _find_file(rz_dir, "*joiner*.onnx")
        tokens = rz_dir / "tokens.txt"

        if not (encoder and decoder and joiner and tokens.is_file()):
            print("[ASR] Incomplete ReazonSpeech model files in", rz_dir)
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
            print("[ASR] ReazonSpeech INT8 Zipformer loaded successfully.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize ReazonSpeech recognizer: {exc}")

    def _init_sense_voice(self) -> None:
        """Initialize SenseVoice Small for multilingual ASR (ja, zh, ko, en, yue)."""
        sv_dir = self.models_dir / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
        if not sv_dir.is_dir():
            return

        model = _find_file(sv_dir, "*model*int8*.onnx") or _find_file(sv_dir, "*model*.onnx")
        tokens = sv_dir / "tokens.txt"

        if not (model and tokens.is_file()):
            return

        try:
            self.sense_voice_recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model),
                tokens=str(tokens),
                num_threads=self.threads,
                language="auto",
                use_itn=True,
            )
            print("[ASR] SenseVoice Small Multilingual ASR loaded successfully.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize SenseVoice recognizer: {exc}")

    def _init_parakeet(self) -> None:
        """Initialize NVIDIA NeMo Parakeet TDT v2 INT8 for ultra-high accuracy English ASR."""
        # Check v2 or v3 candidates
        p_candidates = [
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2",
        ]
        p_dir = None
        for c in p_candidates:
            if c.is_dir():
                p_dir = c
                break

        if not p_dir:
            return

        encoder = _find_file(p_dir, "*encoder*int8*.onnx") or _find_file(p_dir, "*encoder*.onnx")
        decoder = _find_file(p_dir, "*decoder*int8*.onnx") or _find_file(p_dir, "*decoder*.onnx")
        joiner = _find_file(p_dir, "*joiner*int8*.onnx") or _find_file(p_dir, "*joiner*.onnx")
        tokens = p_dir / "tokens.txt"

        if not (encoder and decoder and joiner and tokens.is_file()):
            return

        try:
            self.parakeet_recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=self.threads,
                model_type="nemo_transducer",
                decoding_method="greedy_search",
            )
            print(f"[ASR] Parakeet TDT v2 High-Accuracy English ASR loaded successfully from {p_dir.name}.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Parakeet recognizer: {exc}")

    def update_hotwords(self, hotwords_file: Path | str) -> None:
        """Update hotwords and reload recognizer."""
        self.hotwords_file = Path(hotwords_file)
        self._init_reazon()

    def set_replacements(self, rules: Dict[str, str]) -> None:
        """Set post-decoding word replacement rules (e.g., misheard words to correct terms)."""
        self.replacement_rules = {k.strip(): v.strip() for k, v in rules.items() if k.strip()}

    def transcribe_pcm(self, pcm_16k_mono: np.ndarray, hint_lang: Optional[str] = None) -> str:
        """
        Transcribe a 16kHz float32 mono audio segment.
        Architecture:
          - Japanese (ja): Strictly fixed to ReazonSpeech (Hotwords & Business Dictionary enabled).
          - English (en): Routed to NVIDIA NeMo Parakeet TDT v2 for SOTA accuracy.
          - Chinese (zh) / Korean (ko): Routed to SenseVoice Small.
        """
        if len(pcm_16k_mono) == 0:
            return ""

        import re

        raw_text = ""

        # --- High Accuracy Pipeline ---
        if self.high_accuracy_mode and (self.sense_voice_recognizer or self.parakeet_recognizer):
            # 1. Quick initial probe via SenseVoice to identify language script
            probe_text = ""
            if self.sense_voice_recognizer:
                try:
                    stream = self.sense_voice_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.sense_voice_recognizer.decode_stream(stream)
                    probe_text = stream.result.text.strip()
                except Exception as ex:
                    print(f"[ASR] SenseVoice decode error: {ex}")

            # Check scripts in probe text
            has_japanese = bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF]", probe_text)) or (hint_lang == "ja")
            has_hangul = bool(re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", probe_text)) or (hint_lang == "ko")
            latin_chars = len(re.findall(r"[A-Za-z]", probe_text))
            cjk_chars = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]", probe_text))
            is_english = (latin_chars > 0 and latin_chars >= cjk_chars) or (hint_lang == "en")

            # Route A: Japanese -> Fixed to ReazonSpeech for Hotwords Biasing & Business Dictionary
            if has_japanese and self.recognizer:
                try:
                    rz_stream = self.recognizer.create_stream()
                    rz_stream.accept_waveform(16000, pcm_16k_mono)
                    self.recognizer.decode_stream(rz_stream)
                    raw_text = rz_stream.result.text.strip()
                except Exception as rz_ex:
                    print(f"[ASR] Reazon decode error: {rz_ex}")
                    raw_text = probe_text  # Fallback to probe text

            # Route B: English -> Parakeet TDT v2 for SOTA English accuracy
            elif is_english and self.parakeet_recognizer:
                try:
                    p_stream = self.parakeet_recognizer.create_stream()
                    p_stream.accept_waveform(16000, pcm_16k_mono)
                    self.parakeet_recognizer.decode_stream(p_stream)
                    p_text = p_stream.result.text.strip()
                    raw_text = p_text if p_text else probe_text
                except Exception as p_ex:
                    print(f"[ASR] Parakeet decode error: {p_ex}")
                    raw_text = probe_text

            # Route C: Korean, Chinese or fallback -> SenseVoice
            else:
                raw_text = probe_text

            # Final safety fallback to Reazon if nothing recognized
            if not raw_text and self.recognizer:
                try:
                    rz_stream = self.recognizer.create_stream()
                    rz_stream.accept_waveform(16000, pcm_16k_mono)
                    self.recognizer.decode_stream(rz_stream)
                    raw_text = rz_stream.result.text.strip()
                except Exception:
                    pass

        # --- Standard Fallback Mode (ReazonSpeech) ---
        elif self.recognizer:
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
