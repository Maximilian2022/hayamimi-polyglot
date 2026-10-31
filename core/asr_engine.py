"""
Hayamimi Polyglot - Core ASR Engine.
Multi-model offline speech recognition engine optimized for standard CPU execution.
Zero recording to disk. Pure in-memory streaming.

Architecture:
  - Japanese (ja): ReazonSpeech INT8 Zipformer (Fixed for instant hotwords bias & business dictionary)
  - English & European (en, fr, de, es): NVIDIA NeMo Parakeet TDT 0.6B v3 INT8 (European 25-lang SOTA)
  - Asian languages (zh, ko): SenseVoice Small (Native Chinese/Korean, fast script probe)
  - Vietnamese (vi): Zipformer-vi 30M INT8 (Dedicated 6-tone acoustics)

Lazy Loading / On-demand Activation:
  - Models for non-selected languages are never loaded into RAM.
"""

from __future__ import annotations

import gc
import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import sherpa_onnx

from .dictionary import BusinessDictionary


def _find_file(directory: Path, pattern: str) -> Optional[Path]:
    """Find the first matching file for a glob pattern in a directory."""
    if not directory.is_dir():
        return None
    matches = list(directory.glob(pattern))
    return matches[0] if matches else None


class BusinessASREngine:
    """
    Offline Multi-model ASR Engine for Hayamimi Polyglot.
    Strictly runs on CPU only (Intel Core i5 / AMD Ryzen, no GPU required).
    Supports lazy loading based on active meeting languages.
    """

    def __init__(
        self,
        models_dir: Path | str | None = None,
        hotwords_file: Path | str | None = None,
        threads: int = 2,
        initial_languages: Optional[List[str]] = None,
    ):
        if models_dir is None:
            candidates = [
                Path(__file__).resolve().parent.parent / "models",
                Path(__file__).resolve().parent.parent.parent / "models",
                Path("models"),
                Path("D:/hayamimi4b/models"),
            ]
            for c in candidates:
                if c.is_dir() and (c / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17").is_dir():
                    models_dir = c
                    break

        self.models_dir = Path(models_dir) if models_dir else Path("models")
        self.threads = threads
        self.hotwords_file = Path(hotwords_file) if hotwords_file else None
        self.high_accuracy_mode: bool = True  # High-accuracy routing enabled by default

        # Recognizer slots (loaded lazily on demand)
        self.recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # ReazonSpeech (Japanese & fallback)
        self.sense_voice_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # Chinese, Korean, LID probe
        self.parakeet_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # English, French, German, Spanish
        self.zipformer_vi_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # Vietnamese

        # Business post-decoding dictionary
        self.dictionary = BusinessDictionary()
        self.replacement_rules: Dict[str, str] = {}

        # Active meeting languages
        self.active_languages: Set[str] = set(initial_languages) if initial_languages else {"ja", "en"}

        # Always initialize Japanese ASR (ReazonSpeech) as the baseline
        self._init_reazon()

        # Synchronize model loading with active languages
        self.sync_active_models()

    def set_active_languages(self, langs: List[str]) -> None:
        """
        Update active meeting languages and trigger lazy-load / unload of models.
        Keeps RAM usage minimal by releasing models not in use.
        """
        new_langs = set(langs)
        if new_langs != self.active_languages:
            print(f"[ASR] Updating active languages: {sorted(list(new_langs))}")
            self.active_languages = new_langs
            self.sync_active_models()

    def sync_active_models(self) -> None:
        """Load required recognizers and unload unused ones according to active_languages."""
        if not self.high_accuracy_mode:
            # High-accuracy mode OFF: keep only ReazonSpeech, release others
            self._unload_parakeet()
            self._unload_sense_voice()
            self._unload_zipformer_vi()
            return

        # 1. Parakeet TDT v3 (English, French, German, Spanish)
        needs_parakeet = bool(self.active_languages.intersection({"en", "fr", "de", "es"}))
        if needs_parakeet and self.parakeet_recognizer is None:
            self._init_parakeet()
        elif not needs_parakeet and self.parakeet_recognizer is not None:
            self._unload_parakeet()

        # 2. SenseVoice Small (Chinese, Korean, and fast LID probe)
        needs_sense_voice = bool(self.active_languages.intersection({"zh", "ko"}))
        if needs_sense_voice and self.sense_voice_recognizer is None:
            self._init_sense_voice()
        elif not needs_sense_voice and self.sense_voice_recognizer is not None:
            self._unload_sense_voice()

        # 3. Zipformer-vi (Vietnamese)
        needs_vi = "vi" in self.active_languages
        if needs_vi and self.zipformer_vi_recognizer is None:
            self._init_zipformer_vi()
        elif not needs_vi and self.zipformer_vi_recognizer is not None:
            self._unload_zipformer_vi()

    # --------------------------------------------------------------------------
    # Initializers & Unloaders
    # --------------------------------------------------------------------------
    def _init_reazon(self) -> None:
        """Initialize sherpa-onnx with ReazonSpeech INT8 model for Japanese."""
        if self.recognizer is not None:
            return

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
            print("[ASR] [Loaded] ReazonSpeech INT8 Zipformer (Japanese & Hotwords)")
        except Exception as exc:
            print(f"[ASR] Failed to initialize ReazonSpeech recognizer: {exc}")

    def _init_parakeet(self) -> None:
        """Initialize NVIDIA NeMo Parakeet TDT 0.6B v3 INT8 (English & European 25 langs)."""
        if self.parakeet_recognizer is not None:
            return

        p_candidates = [
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2",
        ]
        p_dir = None
        for c in p_candidates:
            if c.is_dir():
                p_dir = c
                break

        if not p_dir:
            print("[ASR] Parakeet TDT model directory not found.")
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
            print(f"[ASR] [Loaded] Parakeet TDT 0.6B ({p_dir.name}) for English & European languages.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Parakeet recognizer: {exc}")

    def _unload_parakeet(self) -> None:
        """Release Parakeet recognizer from RAM."""
        if self.parakeet_recognizer is not None:
            self.parakeet_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] Parakeet TDT (freed RAM)")

    def _init_sense_voice(self) -> None:
        """Initialize SenseVoice Small for Asian languages (Chinese, Korean) and fast LID."""
        if self.sense_voice_recognizer is not None:
            return

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
            print("[ASR] [Loaded] SenseVoice Small for Asian multilingual ASR.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize SenseVoice recognizer: {exc}")

    def _unload_sense_voice(self) -> None:
        """Release SenseVoice recognizer from RAM."""
        if self.sense_voice_recognizer is not None:
            self.sense_voice_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] SenseVoice Small (freed RAM)")

    def _init_zipformer_vi(self) -> None:
        """Initialize sherpa-onnx Zipformer-vi 30M INT8 for Vietnamese ASR."""
        if self.zipformer_vi_recognizer is not None:
            return

        vi_dir = self.models_dir / "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"
        if not vi_dir.is_dir():
            print(f"[ASR] Warning: Zipformer-vi directory not found at {vi_dir}")
            return

        encoder = _find_file(vi_dir, "*encoder*int8*.onnx") or _find_file(vi_dir, "*encoder*.onnx")
        decoder = _find_file(vi_dir, "*decoder*.onnx")
        joiner = _find_file(vi_dir, "*joiner*int8*.onnx") or _find_file(vi_dir, "*joiner*.onnx")
        tokens = vi_dir / "tokens.txt"

        if not (encoder and decoder and joiner and tokens.is_file()):
            print("[ASR] Incomplete Zipformer-vi model files in", vi_dir)
            return

        try:
            self.zipformer_vi_recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=self.threads,
                model_type="",
                decoding_method="greedy_search",
            )
            print("[ASR] [Loaded] Zipformer-vi 30M INT8 for Vietnamese ASR.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Zipformer-vi recognizer: {exc}")

    def _unload_zipformer_vi(self) -> None:
        """Release Zipformer-vi recognizer from RAM."""
        if self.zipformer_vi_recognizer is not None:
            self.zipformer_vi_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] Zipformer-vi (freed RAM)")

    def update_hotwords(self, hotwords_file: Path | str) -> None:
        """Update hotwords and reload ReazonSpeech recognizer."""
        self.hotwords_file = Path(hotwords_file)
        self.recognizer = None
        self._init_reazon()

    def set_replacements(self, rules: Dict[str, str]) -> None:
        """Set post-decoding word replacement rules."""
        self.replacement_rules = {k.strip(): v.strip() for k, v in rules.items() if k.strip()}

    # --------------------------------------------------------------------------
    # Audio Transcription Pipeline
    # --------------------------------------------------------------------------
    def transcribe_pcm(self, pcm_16k_mono: np.ndarray, hint_lang: Optional[str] = None) -> str:
        """
        Transcribe a 16kHz float32 mono audio segment.
        Routing Architecture:
          - Japanese (ja): ReazonSpeech INT8 Zipformer (Hotwords & Dictionary enabled)
          - European languages (en, fr, de, es): Parakeet TDT 0.6B v3 INT8
          - Asian languages (zh, ko): SenseVoice Small
          - Vietnamese (vi): Zipformer-vi 30M INT8
        """
        if len(pcm_16k_mono) == 0:
            return ""

        raw_text = ""

        # Ensure mono 1D float32
        if pcm_16k_mono.ndim > 1:
            pcm_16k_mono = pcm_16k_mono[:, 0]
        pcm_16k_mono = np.ascontiguousarray(pcm_16k_mono, dtype=np.float32)

        # ----------------------------------------------------------------------
        # Strategy A: Direct Hint-based Routing
        # ----------------------------------------------------------------------
        if hint_lang:
            if hint_lang == "vi" and self.zipformer_vi_recognizer:
                try:
                    stream = self.zipformer_vi_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.zipformer_vi_recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                except Exception as ex:
                    print(f"[ASR:Hint:vi] Decode error: {ex}")

            elif hint_lang in ("en", "fr", "de", "es") and self.parakeet_recognizer:
                try:
                    stream = self.parakeet_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.parakeet_recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                except Exception as ex:
                    print(f"[ASR:Hint:{hint_lang}] Decode error: {ex}")

            elif hint_lang in ("zh", "ko") and self.sense_voice_recognizer:
                try:
                    stream = self.sense_voice_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.sense_voice_recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                except Exception as ex:
                    print(f"[ASR:Hint:{hint_lang}] Decode error: {ex}")

            elif hint_lang == "ja" and self.recognizer:
                try:
                    stream = self.recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                except Exception as ex:
                    print(f"[ASR:Hint:ja] Decode error: {ex}")

        # ----------------------------------------------------------------------
        # Strategy B: Automatic Multi-model Routing
        # ----------------------------------------------------------------------
        if not raw_text and self.high_accuracy_mode:
            # 1. Asian Languages (Korean / Chinese) via SenseVoice
            if ("ko" in self.active_languages or "zh" in self.active_languages) and self.sense_voice_recognizer:
                try:
                    sv_s = self.sense_voice_recognizer.create_stream()
                    sv_s.accept_waveform(16000, pcm_16k_mono)
                    self.sense_voice_recognizer.decode_stream(sv_s)
                    sv_text = sv_s.result.text.strip()

                    has_hangul = bool(re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", sv_text))
                    has_hanzi = bool(re.search(r"[\u4E00-\u9FFF]", sv_text))
                    has_kana = bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF]", sv_text))

                    if has_hangul and "ko" in self.active_languages:
                        raw_text = sv_text
                    elif has_hanzi and not has_kana and "zh" in self.active_languages:
                        raw_text = sv_text
                except Exception as ex:
                    print(f"[ASR:AsianProbe] Error: {ex}")

            # 2. Vietnamese via Zipformer-vi (if vi active and not yet resolved)
            if not raw_text and "vi" in self.active_languages and self.zipformer_vi_recognizer:
                # If only vi and ja are active, or if likely Vietnamese
                if not any(l in self.active_languages for l in ("en", "fr", "de", "es")):
                    try:
                        vi_s = self.zipformer_vi_recognizer.create_stream()
                        vi_s.accept_waveform(16000, pcm_16k_mono)
                        self.zipformer_vi_recognizer.decode_stream(vi_s)
                        vi_text = vi_s.result.text.strip()
                        if vi_text:
                            raw_text = vi_text
                    except Exception as vi_ex:
                        print(f"[ASR:Vietnamese] Error: {vi_ex}")

            # 3. Japanese vs European Language Disambiguation
            if not raw_text:
                t_rz = ""
                if self.recognizer:
                    try:
                        rz_s = self.recognizer.create_stream()
                        rz_s.accept_waveform(16000, pcm_16k_mono)
                        self.recognizer.decode_stream(rz_s)
                        t_rz = rz_s.result.text.strip()
                    except Exception:
                        pass

                has_kana = bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF]", t_rz))
                latin_cnt = len(re.findall(r"[A-Za-z]", t_rz))
                cjk_cnt = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", t_rz))

                # If kana is present or CJK characters dominate -> Japanese!
                if has_kana or (cjk_cnt > 0 and cjk_cnt >= latin_cnt):
                    raw_text = t_rz

                # If Latin characters dominate and European languages are active -> Parakeet TDT v3!
                elif any(l in self.active_languages for l in ("en", "fr", "de", "es")) and self.parakeet_recognizer:
                    try:
                        p_s = self.parakeet_recognizer.create_stream()
                        p_s.accept_waveform(16000, pcm_16k_mono)
                        self.parakeet_recognizer.decode_stream(p_s)
                        p_text = p_s.result.text.strip()
                        raw_text = p_text if p_text else t_rz
                    except Exception as p_ex:
                        print(f"[ASR:Parakeet] Error: {p_ex}")
                        raw_text = t_rz
                elif "vi" in self.active_languages and self.zipformer_vi_recognizer:
                    try:
                        vi_s = self.zipformer_vi_recognizer.create_stream()
                        vi_s.accept_waveform(16000, pcm_16k_mono)
                        self.zipformer_vi_recognizer.decode_stream(vi_s)
                        raw_text = vi_s.result.text.strip() or t_rz
                    except Exception:
                        raw_text = t_rz
                else:
                    raw_text = t_rz

        # ----------------------------------------------------------------------
        # Strategy C: Standard Fallback (ReazonSpeech)
        # ----------------------------------------------------------------------
        if not raw_text and self.recognizer:
            try:
                stream = self.recognizer.create_stream()
                stream.accept_waveform(16000, pcm_16k_mono)
                self.recognizer.decode_stream(stream)
                raw_text = stream.result.text.strip()
            except Exception:
                pass

        if not raw_text:
            return ""

        # Post-decoding dictionary replacement / normalization
        normalized_text = raw_text
        for misheard, correct in self.replacement_rules.items():
            if misheard in normalized_text:
                normalized_text = normalized_text.replace(misheard, correct)

        return normalized_text
