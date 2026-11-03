"""
Hayamimi Polyglot - Core ASR Engine.
Multi-model offline speech recognition engine optimized for standard CPU execution.
In-memory streaming with zero disk recording.

Architecture:
  - Japanese (ja): ReazonSpeech INT8 Zipformer (with SudachiPy business dictionary post-processing)
  - English & European (en, fr, de, es): NVIDIA NeMo Parakeet TDT 0.6B v3 INT8
  - Asian languages (zh, ko): SenseVoice Small (Chinese/Korean & script probe)

Lazy Loading / On-demand Activation:
  - Models for non-selected languages are not loaded into RAM.
"""

from __future__ import annotations

import gc
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

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
    Runs on CPU and supports lazy loading based on active meeting languages.
    """

    def __init__(
        self,
        models_dir: Path | str | None = None,
        hotwords_file: Path | str | None = None,
        threads: int = 2,
        initial_languages: Optional[List[str]] = None,
        high_accuracy_mode: bool = True,
        dictionary: Optional[BusinessDictionary] = None,
        device: str = "cpu",
        npu_cpu_first: bool = True,
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
        self._high_accuracy_mode: bool = high_accuracy_mode

        # Inference device. "cpu" is the default and behaves exactly as before.
        # "npu" (Intel NPU, Windows): every engine starts on CPU and is swapped to its NPU build
        # once that has been compiled; any problem leaves the engine on CPU (see core/npu).
        self.device: str = device if device in ("cpu", "npu") else "cpu"
        self.npu_cpu_first: bool = npu_cpu_first
        self.device_status: Dict[str, str] = {}
        self._npu_lock = threading.Lock()
        self._npu_gen: Dict[str, int] = {"reazon": 0, "parakeet": 0, "sensevoice": 0}

        # Recognizer slots (loaded lazily on demand)
        self.recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # ReazonSpeech (Japanese & ja/en probe)
        self.sense_voice_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # Chinese, Korean, LID probe
        self.parakeet_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # English, French, German, Spanish

        # Shared Business post-decoding dictionary
        self.dictionary: BusinessDictionary = dictionary if dictionary is not None else BusinessDictionary()
        self.replacement_rules: Dict[str, str] = {}
        self.last_detected_lang: Optional[str] = None

        # Active meeting languages
        self.active_languages: Set[str] = set(initial_languages) if initial_languages else {"ja", "en"}

        # Initialize baseline Japanese ASR
        self._init_reazon()

        # Synchronize model loading with active languages
        self.sync_active_models()

    @property
    def high_accuracy_mode(self) -> bool:
        return self._high_accuracy_mode

    @high_accuracy_mode.setter
    def high_accuracy_mode(self, value: bool) -> None:
        if self._high_accuracy_mode != value:
            self._high_accuracy_mode = value
            self.sync_active_models()

    def set_active_languages(self, langs: List[str]) -> None:
        """
        Update active meeting languages and trigger lazy-load / unload of models.
        Keeps RAM usage minimal by releasing models not in use.
        """
        new_langs = set(langs) if langs else {"ja"}
        if new_langs != self.active_languages:
            print(f"[ASR] Updating active languages: {sorted(list(new_langs))}")
            self.active_languages = new_langs
            self.sync_active_models()

    def sync_active_models(self) -> None:
        """Load required recognizers and unload unused ones according to active_languages."""
        if not self.high_accuracy_mode:
            self._unload_parakeet()
            self._unload_sense_voice()
            return

        # 1. Parakeet TDT v3 (English, French, German, Spanish)
        needs_parakeet = bool(self.active_languages.intersection({"en", "fr", "de", "es"}))
        if needs_parakeet and self.parakeet_recognizer is None:
            self._init_parakeet()
        elif not needs_parakeet and self.parakeet_recognizer is not None:
            self._unload_parakeet()

        # 2. SenseVoice Small (Chinese, Korean)
        needs_sense_voice = bool(self.active_languages.intersection({"zh", "ko"}))
        if needs_sense_voice and self.sense_voice_recognizer is None:
            self._init_sense_voice()
        elif not needs_sense_voice and self.sense_voice_recognizer is not None:
            self._unload_sense_voice()

    # --------------------------------------------------------------------------
    # Initializers & Unloaders
    # --------------------------------------------------------------------------
    def _create_reazon_recognizer(self) -> Optional[sherpa_onnx.OfflineRecognizer]:
        """Create a new ReazonSpeech OfflineRecognizer instance."""
        rz_dir = self.models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
        if not rz_dir.is_dir():
            print(f"[ASR] Warning: ReazonSpeech model directory not found at {rz_dir}")
            return None

        encoder = _find_file(rz_dir, "*encoder*int8*.onnx") or _find_file(rz_dir, "*encoder*.onnx")
        decoder = _find_file(rz_dir, "*decoder*int8*.onnx") or _find_file(rz_dir, "*decoder*.onnx")
        joiner = _find_file(rz_dir, "*joiner*int8*.onnx") or _find_file(rz_dir, "*joiner*.onnx")
        tokens = rz_dir / "tokens.txt"

        if not (encoder and decoder and joiner and tokens.is_file()):
            print("[ASR] Incomplete ReazonSpeech model files in", rz_dir)
            return None

        try:
            return sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=self.threads,
                model_type="",
                decoding_method="greedy_search",
            )
        except Exception as exc:
            print(f"[ASR] Failed to initialize ReazonSpeech recognizer: {exc}")
            return None

    def _init_reazon(self) -> None:
        """Initialize sherpa-onnx with ReazonSpeech INT8 model for Japanese."""
        if self.recognizer is not None:
            return
        if self._try_npu_sync("reazon", "recognizer"):
            return
        rec = self._create_reazon_recognizer()
        if rec is not None:
            self.recognizer = rec
            print("[ASR] [Loaded] ReazonSpeech INT8 Zipformer (Japanese)")
            self._upgrade_to_npu("reazon", "recognizer")

    def _init_parakeet(self) -> None:
        """Initialize NVIDIA NeMo Parakeet TDT 0.6B v3 INT8 (English & European languages)."""
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

        if self._try_npu_sync("parakeet", "parakeet_recognizer"):
            return

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
            self._upgrade_to_npu("parakeet", "parakeet_recognizer")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Parakeet recognizer: {exc}")

    def _unload_parakeet(self) -> None:
        """Release Parakeet recognizer from RAM."""
        self._npu_gen["parakeet"] += 1
        self.device_status.pop("parakeet", None)
        if self.parakeet_recognizer is not None:
            self.parakeet_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] Parakeet TDT (freed RAM)")

    def _init_sense_voice(self) -> None:
        """Initialize SenseVoice Small for Asian languages (Chinese, Korean)."""
        if self.sense_voice_recognizer is not None:
            return

        if self._try_npu_sync("sensevoice", "sense_voice_recognizer"):
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
            self._upgrade_to_npu("sensevoice", "sense_voice_recognizer")
        except Exception as exc:
            print(f"[ASR] Failed to initialize SenseVoice recognizer: {exc}")

    def _unload_sense_voice(self) -> None:
        """Release SenseVoice recognizer from RAM."""
        self._npu_gen["sensevoice"] += 1
        self.device_status.pop("sensevoice", None)
        if self.sense_voice_recognizer is not None:
            self.sense_voice_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] SenseVoice Small (freed RAM)")

    # --------------------------------------------------------------------------
    # NPU (Intel AI Boost) support - optional, opt-in, always falls back to CPU
    # --------------------------------------------------------------------------
    def _npu_factory(self, key: str):
        """Return (model_files_present, recognizer_class) for an engine key, importing lazily."""
        from core.npu import parakeet, reazon, sensevoice

        return {
            "reazon": (reazon.model_files_present, reazon.ReazonNpuRecognizer),
            "parakeet": (parakeet.model_files_present, parakeet.ParakeetNpuRecognizer),
            "sensevoice": (sensevoice.model_files_present, sensevoice.SenseVoiceNpuRecognizer),
        }[key]

    def _build_npu(self, key: str):
        """Build the NPU recognizer for `key`. Returns (recognizer | None, reason)."""
        try:
            from core.npu import addons, device

            addons.wait_until_ready()
            info = device.probe()
            if not info.available:
                return None, info.reason
            present, cls = self._npu_factory(key)
            if not present(self.models_dir):
                return None, "NPU 用モデルが未導入です"
            return cls(self.models_dir), ""
        except Exception as exc:  # compile failures, driver problems, blocked DLLs ...
            return None, f"{type(exc).__name__}: {exc}"

    def _try_npu_sync(self, key: str, attr: str) -> bool:
        """NPU-first loading (only when npu_cpu_first is disabled). True if the NPU engine is in place."""
        if self.device != "npu" or self.npu_cpu_first:
            return False
        self.device_status[key] = "npu-compiling"
        rec, reason = self._build_npu(key)
        if rec is None:
            self.device_status[key] = f"cpu ({reason})"
            print(f"[ASR:NPU] {key}: CPU を使用します - {reason}")
            return False
        setattr(self, attr, rec)
        self.device_status[key] = "npu"
        print(f"[ASR:NPU] [Loaded] {key} on NPU")
        return True

    def _upgrade_to_npu(self, key: str, attr: str) -> None:
        """CPU-first: keep working on CPU, compile the NPU build in the background, then swap."""
        if self.device != "npu" or not self.npu_cpu_first:
            return
        gen = self._npu_gen[key]
        self.device_status[key] = "cpu (NPU を準備中)"

        def work():
            rec, reason = self._build_npu(key)
            with self._npu_lock:
                if self._npu_gen[key] != gen or getattr(self, attr) is None:
                    return  # the engine was unloaded / replaced while compiling
                if rec is None:
                    self.device_status[key] = f"cpu ({reason})"
                    print(f"[ASR:NPU] {key}: CPU のまま継続します - {reason}")
                    return
                setattr(self, attr, rec)  # atomic swap; in-flight CPU decodes finish on the old object
                self.device_status[key] = "npu"
            gc.collect()
            print(f"[ASR:NPU] [Switched] {key} now runs on the NPU")

        threading.Thread(target=work, daemon=True, name=f"NpuUpgrade-{key}").start()

    def get_device_summary(self) -> Dict[str, str]:
        """Per-engine device state for the UI: e.g. {'reazon': 'npu', 'parakeet': 'cpu (...)'}."""
        return dict(self.device_status)

    def update_hotwords(self, hotwords_file: Optional[Path | str] = None) -> None:
        """
        Update hotword state in-memory without reloading ONNX weights.
        Hotword corrections are applied instantaneously via BusinessDictionary.
        """
        self.hotwords_file = Path(hotwords_file) if hotwords_file else None
        print("[ASR] [Updated] Instant Hotwords active in post-processing dictionary.")

    def set_replacements(self, rules: Dict[str, str]) -> None:
        """Set post-decoding word replacement rules."""
        self.replacement_rules = {k.strip(): v.strip() for k, v in rules.items() if k.strip()}

    def has_any_model(self) -> bool:
        """Return True if at least one recognizer is loaded and ready."""
        return any(
            r is not None
            for r in (self.recognizer, self.parakeet_recognizer, self.sense_voice_recognizer)
        )

    # --------------------------------------------------------------------------
    # Audio Transcription Pipeline
    # --------------------------------------------------------------------------
    def transcribe_pcm(self, pcm_16k_mono: np.ndarray, hint_lang: Optional[str] = None) -> str:
        """
        Transcribe a 16kHz float32 mono audio segment.
        Routing Architecture:
          - Japanese (ja): ReazonSpeech INT8 Zipformer (Dictionary enabled)
          - European languages (en, fr, de, es): Parakeet TDT 0.6B v3 INT8
          - Asian languages (zh, ko): SenseVoice Small
        """
        if len(pcm_16k_mono) == 0:
            return ""

        raw_text = ""
        self.last_detected_lang = None

        # Ensure mono 1D float32
        if pcm_16k_mono.ndim > 1:
            pcm_16k_mono = pcm_16k_mono[:, 0]
        pcm_16k_mono = np.ascontiguousarray(pcm_16k_mono, dtype=np.float32)

        # If only a single language is active in the meeting and no explicit hint is given,
        # route directly to that single language model without multi-model probing.
        effective_hint = hint_lang
        if not effective_hint and len(self.active_languages) == 1:
            effective_hint = next(iter(self.active_languages))

        # ----------------------------------------------------------------------
        # Strategy A: Direct Hint-based / Single-language Routing
        # ----------------------------------------------------------------------
        if effective_hint:
            if effective_hint in ("en", "fr", "de", "es") and self.parakeet_recognizer:
                try:
                    stream = self.parakeet_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.parakeet_recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                    if raw_text:
                        self.last_detected_lang = effective_hint
                except Exception as ex:
                    print(f"[ASR:Hint:{effective_hint}] Decode error: {ex}")

            elif effective_hint in ("zh", "ko") and self.sense_voice_recognizer:
                try:
                    stream = self.sense_voice_recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.sense_voice_recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                    if raw_text:
                        self.last_detected_lang = effective_hint
                except Exception as ex:
                    print(f"[ASR:Hint:{effective_hint}] Decode error: {ex}")

            elif effective_hint == "ja" and self.recognizer:
                try:
                    stream = self.recognizer.create_stream()
                    stream.accept_waveform(16000, pcm_16k_mono)
                    self.recognizer.decode_stream(stream)
                    raw_text = stream.result.text.strip()
                    if raw_text:
                        self.last_detected_lang = "ja"
                except Exception as ex:
                    print(f"[ASR:Hint:ja] Decode error: {ex}")

        # ----------------------------------------------------------------------
        # Strategy B: Automatic Multi-model Routing (Bilingual / Multilingual)
        # ----------------------------------------------------------------------
        if not raw_text and self.high_accuracy_mode:
            # 1. Asian Languages (Korean / Chinese) via SenseVoice when active
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
                        self.last_detected_lang = "ko"
                    elif has_hanzi and not has_kana and "zh" in self.active_languages:
                        raw_text = sv_text
                        self.last_detected_lang = "zh"
                except Exception as ex:
                    print(f"[ASR:AsianProbe] Error: {ex}")

            # 2. Japanese vs European Language Disambiguation
            if not raw_text:
                t_rz = ""
                if self.recognizer and "ja" in self.active_languages:
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

                # If kana is present or CJK characters dominate -> Japanese
                if t_rz and (has_kana or (cjk_cnt > 0 and cjk_cnt >= latin_cnt)):
                    raw_text = t_rz
                    self.last_detected_lang = "ja"

                # Otherwise if European languages are active -> Parakeet TDT v3
                elif any(l in self.active_languages for l in ("en", "fr", "de", "es")) and self.parakeet_recognizer:
                    try:
                        p_s = self.parakeet_recognizer.create_stream()
                        p_s.accept_waveform(16000, pcm_16k_mono)
                        self.parakeet_recognizer.decode_stream(p_s)
                        p_text = p_s.result.text.strip()
                        if p_text:
                            raw_text = p_text
                        else:
                            raw_text = t_rz
                    except Exception as p_ex:
                        print(f"[ASR:Parakeet] Error: {p_ex}")
                        raw_text = t_rz
                else:
                    raw_text = t_rz
                    if raw_text:
                        self.last_detected_lang = "ja"

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

        if hasattr(self, "dictionary") and self.dictionary:
            normalized_text = self.dictionary.apply_replacements(normalized_text)

        return normalized_text
