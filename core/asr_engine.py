"""
Hayamimi Polyglot - Core ASR Engine.
Multi-model offline speech recognition engine optimized for standard CPU execution.
In-memory streaming with zero disk recording.

Architecture (Commercial-safe & Non-Chinese models):
  - Japanese (ja): ReazonSpeech INT8 Zipformer (with SudachiPy business dictionary post-processing)
  - English & European (en, fr, de, es): NVIDIA NeMo Parakeet TDT 0.6B v3 INT8
  - Chinese (zh): Moonshine Streaming Tiny Zh INT8 (MIT)
  - Korean (ko): Moonshine Streaming KO (if installed, MIT) -> NVIDIA Nemotron 3.5 ASR Streaming 0.6B (OpenMDW-1.1)

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
from .moonshine_asr import MoonshineStreamingRecognizer


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
        # "npu" (Intel NPU, Windows): supported engines start on CPU and are swapped to NPU
        # once compiled; any problem leaves the engine on CPU (see core/npu).
        self.device: str = device if device in ("cpu", "npu") else "cpu"
        self.npu_cpu_first: bool = npu_cpu_first
        self.device_status: Dict[str, str] = {}
        self._npu_lock = threading.Lock()
        self._npu_gen: Dict[str, int] = {"reazon": 0, "parakeet": 0}
        self._npu_err_counts: Dict[str, int] = {"reazon": 0, "parakeet": 0}

        # Recognizer slots (loaded lazily on demand)
        self.recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # ReazonSpeech (ja)
        self.parakeet_recognizer: Optional[sherpa_onnx.OfflineRecognizer] = None  # en, fr, de, es
        self.zh_recognizer: Optional[MoonshineStreamingRecognizer] = None  # Chinese (Moonshine Streaming)
        self.ko_recognizer: Optional[object] = None  # Korean (Moonshine KO if present, else Nemotron 3.5)
        self.ko_backend: str = ""  # "moonshine_v2" | "moonshine_5g" | "nemotron" | ""

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
            self._unload_zh()
            self._unload_ko()
            return

        # 1. Parakeet TDT v3 (English, French, German, Spanish)
        needs_parakeet = bool(self.active_languages.intersection({"en", "fr", "de", "es"}))
        if needs_parakeet and self.parakeet_recognizer is None:
            self._init_parakeet()
        elif not needs_parakeet and self.parakeet_recognizer is not None:
            self._unload_parakeet()

        # 2. Chinese (Moonshine Streaming Tiny Zh)
        needs_zh = "zh" in self.active_languages
        if needs_zh and self.zh_recognizer is None:
            self._init_zh()
        elif not needs_zh and self.zh_recognizer is not None:
            self._unload_zh()

        # 3. Korean (Moonshine KO Streaming if present, else Nemotron 3.5 ASR Streaming 0.6B)
        needs_ko = "ko" in self.active_languages
        if needs_ko and self.ko_recognizer is None:
            self._init_ko()
        elif not needs_ko and self.ko_recognizer is not None:
            self._unload_ko()

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

    def _create_parakeet_recognizer(self) -> Optional[sherpa_onnx.OfflineRecognizer]:
        """Create a new CPU Parakeet TDT OfflineRecognizer instance."""
        p_candidates = [
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3",
            self.models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2",
        ]
        p_dir = next((c for c in p_candidates if c.is_dir()), None)
        if not p_dir:
            print("[ASR] Parakeet TDT model directory not found.")
            return None

        encoder = _find_file(p_dir, "*encoder*int8*.onnx") or _find_file(p_dir, "*encoder*.onnx")
        decoder = _find_file(p_dir, "*decoder*int8*.onnx") or _find_file(p_dir, "*decoder*.onnx")
        joiner = _find_file(p_dir, "*joiner*int8*.onnx") or _find_file(p_dir, "*joiner*.onnx")
        tokens = p_dir / "tokens.txt"
        if not (encoder and decoder and joiner and tokens.is_file()):
            return None

        try:
            rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=self.threads,
                model_type="nemo_transducer",
                decoding_method="greedy_search",
            )
            print(f"[ASR] [Loaded] Parakeet TDT 0.6B ({p_dir.name}) for English & European languages.")
            return rec
        except Exception as exc:
            print(f"[ASR] Failed to initialize Parakeet recognizer: {exc}")
            return None

    def _init_parakeet(self) -> None:
        """Initialize NVIDIA NeMo Parakeet TDT 0.6B v3 INT8 (English & European languages)."""
        if self.parakeet_recognizer is not None:
            return
        if self._try_npu_sync("parakeet", "parakeet_recognizer"):
            return
        rec = self._create_parakeet_recognizer()
        if rec is not None:
            self.parakeet_recognizer = rec
            self._upgrade_to_npu("parakeet", "parakeet_recognizer")

    def _unload_parakeet(self) -> None:
        """Release Parakeet recognizer from RAM."""
        self._npu_gen["parakeet"] += 1
        self.device_status.pop("parakeet", None)
        if self.parakeet_recognizer is not None:
            self.parakeet_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] Parakeet TDT (freed RAM)")

    def _init_zh(self) -> None:
        """Initialize Moonshine Streaming Tiny Zh INT8 for Chinese."""
        if self.zh_recognizer is not None:
            return
        candidates = [
            self.models_dir / "moonshine-streaming-small-zh-onnx",
            self.models_dir / "moonshine-streaming-tiny-zh-onnx",
        ]
        zh_dir = next((c for c in candidates if MoonshineStreamingRecognizer.is_valid_dir(c)), None)
        if zh_dir is None:
            print("[ASR] Moonshine Chinese streaming model directory not found.")
            return
        try:
            self.zh_recognizer = MoonshineStreamingRecognizer(zh_dir, num_threads=self.threads)
            print(f"[ASR] [Loaded] Moonshine Streaming Zh ({zh_dir.name}) for Chinese ASR.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Moonshine Zh recognizer: {exc}")

    def _unload_zh(self) -> None:
        """Release Moonshine Zh recognizer from RAM."""
        if self.zh_recognizer is not None:
            self.zh_recognizer = None
            gc.collect()
            print("[ASR] [Unloaded] Moonshine Streaming Zh (freed RAM)")

    def _init_ko(self) -> None:
        """
        Initialize Korean ASR.
        Prefers Moonshine Streaming KO (MIT) if/when installed, and falls back to
        NVIDIA Nemotron 3.5 ASR Streaming 0.6B (OpenMDW-1.1).
        """
        if self.ko_recognizer is not None:
            return

        # 1a. Future Moonshine KO via sherpa-onnx v2 format (encoder + decoder + tokens.txt)
        for pattern in ("sherpa-onnx-moonshine-streaming-*-ko*", "sherpa-onnx-moonshine-v2-*-ko*"):
            for ko_dir in sorted(self.models_dir.glob(pattern)):
                enc = _find_file(ko_dir, "*encoder*int8*.onnx") or _find_file(ko_dir, "*encoder*.onnx")
                dec = _find_file(ko_dir, "*decoder*int8*.onnx") or _find_file(ko_dir, "*decoder*.onnx")
                tok = ko_dir / "tokens.txt"
                if enc and dec and tok.is_file():
                    try:
                        self.ko_recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
                            encoder=str(enc),
                            decoder=str(dec),
                            tokens=str(tok),
                            num_threads=self.threads,
                        )
                        self.ko_backend = "moonshine_v2"
                        print(f"[ASR] [Loaded] Moonshine Streaming KO ({ko_dir.name}) for Korean ASR.")
                        return
                    except Exception as exc:
                        print(f"[ASR] Failed to initialize Moonshine v2 KO ({ko_dir.name}): {exc}")

        # 1b. Future Moonshine KO via 5-graph ONNX format
        for pattern in ("moonshine-streaming-small-ko*", "moonshine-streaming-tiny-ko*", "moonshine-streaming-*-ko*"):
            for ko_dir in sorted(self.models_dir.glob(pattern)):
                if MoonshineStreamingRecognizer.is_valid_dir(ko_dir):
                    try:
                        self.ko_recognizer = MoonshineStreamingRecognizer(ko_dir, num_threads=self.threads)
                        self.ko_backend = "moonshine_5g"
                        print(f"[ASR] [Loaded] Moonshine Streaming KO ({ko_dir.name}) for Korean ASR.")
                        return
                    except Exception as exc:
                        print(f"[ASR] Failed to initialize Moonshine 5g KO ({ko_dir.name}): {exc}")

        # 2. Active default: NVIDIA Nemotron 3.5 ASR Streaming 0.6B INT8 (OpenMDW-1.1)
        nem_candidates = [
            self.models_dir / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8",
            self.models_dir / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8",
        ]
        nem_dir = next((c for c in nem_candidates if c.is_dir()), None)
        if not nem_dir:
            print("[ASR] Korean ASR model (Nemotron 3.5 / Moonshine KO) not found.")
            return

        encoder = _find_file(nem_dir, "*encoder*int8*.onnx") or _find_file(nem_dir, "*encoder*.onnx")
        decoder = _find_file(nem_dir, "*decoder*int8*.onnx") or _find_file(nem_dir, "*decoder*.onnx")
        joiner = _find_file(nem_dir, "*joiner*int8*.onnx") or _find_file(nem_dir, "*joiner*.onnx")
        tokens = nem_dir / "tokens.txt"
        if not (encoder and decoder and joiner and tokens.is_file()):
            print(f"[ASR] Incomplete Nemotron 3.5 model files in {nem_dir}")
            return

        try:
            self.ko_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(tokens),
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                num_threads=self.threads,
                feature_dim=128,
            )
            self.ko_backend = "nemotron"
            print(f"[ASR] [Loaded] Nemotron 3.5 ASR Streaming 0.6B ({nem_dir.name}) for Korean ASR.")
        except Exception as exc:
            print(f"[ASR] Failed to initialize Nemotron 3.5 recognizer: {exc}")

    def _unload_ko(self) -> None:
        """Release Korean recognizer from RAM."""
        if self.ko_recognizer is not None:
            self.ko_recognizer = None
            self.ko_backend = ""
            gc.collect()
            print("[ASR] [Unloaded] Korean ASR (freed RAM)")

    # --------------------------------------------------------------------------
    # NPU (Intel AI Boost) support - optional, opt-in, always falls back to CPU
    # --------------------------------------------------------------------------
    def _npu_factory(self, key: str):
        """Return (model_files_present, recognizer_class) for an engine key, importing lazily."""
        from core.npu import parakeet, reazon

        return {
            "reazon": (reazon.model_files_present, reazon.ReazonNpuRecognizer),
            "parakeet": (parakeet.model_files_present, parakeet.ParakeetNpuRecognizer),
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

    def _fallback_npu_to_cpu(self, key: str, attr: str, exc: Exception) -> Optional[object]:
        """Switch a failing NPU engine back to its CPU recognizer for the rest of the session."""
        builders = {
            "reazon": self._create_reazon_recognizer,
            "parakeet": self._create_parakeet_recognizer,
        }
        builder = builders.get(key)
        if builder is None:
            return None
        with self._npu_lock:
            self._npu_gen[key] += 1
            cpu_rec = builder()
            setattr(self, attr, cpu_rec)
            self.device_status[key] = f"cpu (NPU 実行エラーのため切替: {type(exc).__name__})"
        gc.collect()
        print(f"[ASR:NPU] [Fallback] {key} reverted to CPU after runtime errors: {exc}")
        return cpu_rec

    def _decode_online_nemotron(self, rec: sherpa_onnx.OnlineRecognizer, pcm_16k_mono: np.ndarray, lang: str = "ko") -> str:
        """Decode an utterance via Nemotron 3.5 streaming OnlineRecognizer with tail flush padding."""
        s = rec.create_stream()
        s.set_option("language", lang)
        s.accept_waveform(16000, pcm_16k_mono)
        # Flush the 1120ms streaming chunk so trailing syllables are not clipped
        s.accept_waveform(16000, np.zeros(int(16000 * 1.2), dtype=np.float32))
        s.input_finished()
        while rec.is_ready(s):
            rec.decode_stream(s)
        return rec.get_result(s).strip()

    def _decode_slot(self, key: str, attr: str, pcm_16k_mono: np.ndarray, lang_opt: str = "ko") -> str:
        """
        Run a single decode pass on the given recognizer slot.
        If an NPU recognizer raises consecutive runtime errors, automatically revert to CPU.
        """
        rec = getattr(self, attr, None)
        if rec is None:
            return ""
        err_map = getattr(self, "_npu_err_counts", None)
        try:
            if key == "ko" and self.ko_backend == "nemotron":
                return self._decode_online_nemotron(rec, pcm_16k_mono, lang=lang_opt)
            stream = rec.create_stream()
            stream.accept_waveform(16000, pcm_16k_mono)
            rec.decode_stream(stream)
            if err_map is not None and key in err_map:
                err_map[key] = 0
            return stream.result.text.strip()
        except Exception as ex:
            print(f"[ASR:{key}] Decode error: {ex}")
            if self.device_status.get(key) == "npu":
                cnt = (err_map.get(key, 0) + 1) if err_map is not None else 2
                if err_map is not None:
                    err_map[key] = cnt
                if cnt >= 2:
                    cpu_rec = self._fallback_npu_to_cpu(key, attr, ex)
                    if cpu_rec is not None:
                        try:
                            s2 = cpu_rec.create_stream()
                            s2.accept_waveform(16000, pcm_16k_mono)
                            cpu_rec.decode_stream(s2)
                            return s2.result.text.strip()
                        except Exception as cpu_ex:
                            print(f"[ASR:{key}:CPUFallback] Error: {cpu_ex}")
            return ""

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
            for r in (self.recognizer, self.parakeet_recognizer, self.zh_recognizer, self.ko_recognizer)
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
          - Chinese (zh): Moonshine Streaming Tiny Zh INT8
          - Korean (ko): Moonshine KO Streaming (if installed) or Nemotron 3.5 ASR Streaming 0.6B
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
                raw_text = self._decode_slot("parakeet", "parakeet_recognizer", pcm_16k_mono)
                if raw_text:
                    self.last_detected_lang = effective_hint

            elif effective_hint == "zh" and self.zh_recognizer:
                raw_text = self._decode_slot("zh", "zh_recognizer", pcm_16k_mono)
                if raw_text:
                    self.last_detected_lang = "zh"

            elif effective_hint == "ko" and self.ko_recognizer:
                raw_text = self._decode_slot("ko", "ko_recognizer", pcm_16k_mono, lang_opt="ko")
                if raw_text:
                    self.last_detected_lang = "ko"

            elif effective_hint == "ja" and self.recognizer:
                raw_text = self._decode_slot("reazon", "recognizer", pcm_16k_mono)
                if raw_text:
                    self.last_detected_lang = "ja"

        # ----------------------------------------------------------------------
        # Strategy B: Automatic Multi-model Routing (Bilingual / Multilingual)
        # ----------------------------------------------------------------------
        if not raw_text and self.high_accuracy_mode:
            nem_auto_hint: Optional[str] = None

            # 1. Korean (Hangul probe via dedicated ko_recognizer)
            if "ko" in self.active_languages and self.ko_recognizer:
                # In multilingual routing, Nemotron 'auto' avoids forcing non-Korean speech into spurious Hangul
                probe_opt = "auto" if self.ko_backend == "nemotron" else "ko"
                ko_text = self._decode_slot("ko", "ko_recognizer", pcm_16k_mono, lang_opt=probe_opt)
                hangul_chars = re.findall(r"[\uAC00-\uD7AF\u1100-\u11FF]", ko_text)
                hanzi_chars = re.findall(r"[\u4E00-\u9FFF]", ko_text)
                kana_chars = re.findall(r"[\u3040-\u309F\u30A0-\u30FF]", ko_text)
                if ko_text and len(hangul_chars) >= 2 and len(hangul_chars) >= len(hanzi_chars):
                    raw_text = ko_text
                    self.last_detected_lang = "ko"
                elif self.ko_backend == "nemotron" and ko_text:
                    # Reuse Nemotron's multilingual LID signal to route ja vs zh accurately
                    if kana_chars and "ja" in self.active_languages:
                        nem_auto_hint = "ja"
                    elif hanzi_chars and not kana_chars and "zh" in self.active_languages:
                        nem_auto_hint = "zh"

            # 2. Japanese vs Chinese vs European Language Disambiguation
            if not raw_text:
                if nem_auto_hint == "zh" and self.zh_recognizer:
                    zh_text = self._decode_slot("zh", "zh_recognizer", pcm_16k_mono)
                    if zh_text and re.search(r"[\u4E00-\u9FFF]", zh_text):
                        raw_text = zh_text
                        self.last_detected_lang = "zh"

                if not raw_text:
                    t_rz = ""
                    if self.recognizer and "ja" in self.active_languages:
                        t_rz = self._decode_slot("reazon", "recognizer", pcm_16k_mono)

                    has_kana = bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF]", t_rz))
                    latin_cnt = len(re.findall(r"[A-Za-z]", t_rz))
                    cjk_cnt = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", t_rz))

                    if nem_auto_hint == "ja" and t_rz:
                        raw_text = t_rz
                        self.last_detected_lang = "ja"
                    elif t_rz and (has_kana or ("zh" not in self.active_languages and cjk_cnt > 0 and cjk_cnt >= latin_cnt)):
                        # When both ja and zh are active (without Nemotron hint), check Moonshine-zh
                        # if Reazon output is short or ambiguous so Chinese isn't misrouted to ja.
                        if "zh" in self.active_languages and self.zh_recognizer and len(t_rz) < 20:
                            zh_text = self._decode_slot("zh", "zh_recognizer", pcm_16k_mono)
                            zh_hanzi = len(re.findall(r"[\u4E00-\u9FFF]", zh_text))
                            zh_has_kana = bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF]", zh_text))
                            if zh_text and not zh_has_kana and zh_hanzi > len(t_rz):
                                raw_text = zh_text
                                self.last_detected_lang = "zh"
                        if not raw_text:
                            raw_text = t_rz
                            self.last_detected_lang = "ja"
                    elif "zh" in self.active_languages and self.zh_recognizer:
                        zh_text = self._decode_slot("zh", "zh_recognizer", pcm_16k_mono)
                        has_hanzi = bool(re.search(r"[\u4E00-\u9FFF]", zh_text))
                        if zh_text and has_hanzi and not re.search(r"[\u3040-\u309F\u30A0-\u30FF]", zh_text):
                            raw_text = zh_text
                            self.last_detected_lang = "zh"
                        elif t_rz and cjk_cnt > 0 and cjk_cnt >= latin_cnt:
                            raw_text = t_rz
                            self.last_detected_lang = "ja"

                    # European languages via Parakeet TDT v3
                    if not raw_text and any(l in self.active_languages for l in ("en", "fr", "de", "es")) and self.parakeet_recognizer:
                        p_text = self._decode_slot("parakeet", "parakeet_recognizer", pcm_16k_mono)
                        if p_text:
                            raw_text = p_text
                        elif t_rz:
                            raw_text = t_rz
                    elif not raw_text and t_rz:
                        raw_text = t_rz
                        self.last_detected_lang = "ja"

        # ----------------------------------------------------------------------
        # Strategy C: Standard Fallback (ReazonSpeech)
        # ----------------------------------------------------------------------
        if not raw_text and self.recognizer:
            raw_text = self._decode_slot("reazon", "recognizer", pcm_16k_mono)

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
