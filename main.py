"""
Hayamimi Polyglot - Main Entry Point.
Integrates:
  - PySide6 System Tray + Floating Control Panel
  - Transparent Stealth-protected Subtitle Overlay
  - Localhost (127.0.0.1:8844) Screen Sharing Web View
  - Dual-track Audio Capture (Self Mic + Remote Zoom/Teams Loopback)
  - Silero VAD + ReazonSpeech INT8 ASR
  - CTranslate2 Local Multilingual Translation (M2M-100 & FuguMT)
  - Zero disk audio recording. Zero external telemetry.
"""

from __future__ import annotations

import collections
import os
import platform
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PySide6 import QtCore, QtWidgets

# Ensure hayamimi4b root is on sys.path
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Core imports
from core.asr_engine import BusinessASREngine
from core.audio.dual_capture import DualTrackCapture
from core.dictionary import BusinessDictionary
from core.translator import LocalTranslator
from core.vad import SileroVAD
from ui.control_panel import ControlPanel, SystemTrayApp
from ui.overlay_window import OverlayWindow
from ui.web_server import BusinessWebServer, broadcast_event


class SessionWorker(QtCore.QObject):
    """Bridge between audio threads and Qt UI thread via Qt Signals."""

    subtitle_ready = QtCore.Signal(str, str, dict, str)  # (track, text, translations_dict, utterance_id)
    translations_ready = QtCore.Signal(str, dict)        # (utterance_id, translations_dict)

    def __init__(
        self,
        asr_engine: BusinessASREngine,
        vad: SileroVAD,
        translator: LocalTranslator,
        vad_remote: Optional[SileroVAD] = None,
    ):
        super().__init__()
        self.asr_engine = asr_engine
        self.vads: Dict[str, SileroVAD] = {
            "self": vad,
            "remote": vad_remote if vad_remote is not None else vad,
        }
        self.translator = translator

        self.selected_languages: List[str] = ["ja", "en"]

        # Per-track audio buffers & VAD state
        self._buffers: Dict[str, List[np.ndarray]] = {"self": [], "remote": []}
        self._preroll: Dict[str, collections.deque] = {
            "self": collections.deque(maxlen=8),
            "remote": collections.deque(maxlen=8),
        }
        self._silence_frames: Dict[str, int] = {"self": 0, "remote": 0}
        self._is_speaking: Dict[str, bool] = {"self": False, "remote": False}
        self._lock = threading.Lock()

        # Dedicated worker queue per track (P1: Prevents unbounded thread spawning and out-of-order subtitles)
        self._queues: Dict[str, queue.Queue] = {
            "self": queue.Queue(),
            "remote": queue.Queue(),
        }
        self._worker_threads = [
            threading.Thread(target=self._worker_loop, args=("self",), daemon=True, name="Worker-Self"),
            threading.Thread(target=self._worker_loop, args=("remote",), daemon=True, name="Worker-Remote"),
        ]
        for w in self._worker_threads:
            w.start()

    def _worker_loop(self, track: str):
        """Worker thread processing speech segments in strict chronological order."""
        while True:
            item = self._queues[track].get()
            if item is None:
                break
            utterance_id, segment = item
            try:
                self._process_segment(track, segment, utterance_id)
            except Exception as e:
                print(f"[Worker:{track}] Segment processing error: {e}")
            finally:
                self._queues[track].task_done()

    def reset_state(self):
        """Reset internal buffers and VAD states on meeting end or pause."""
        with self._lock:
            self._buffers = {"self": [], "remote": []}
            self._silence_frames = {"self": 0, "remote": 0}
            self._is_speaking = {"self": False, "remote": False}
            for q in self._preroll.values():
                q.clear()
            for v in self.vads.values():
                v.reset()

    def set_selected_languages(self, langs: List[str]):
        self.selected_languages = langs[:5]
        # Synchronize ASR models with active meeting languages (Lazy Loading)
        self.asr_engine.set_active_languages(self.selected_languages)

    def _detect_src_lang(self, track: str, text: str) -> str:
        """
        Detect source language from text characters with high precision.
        Never blindly defaults to track origin; accurately distinguishes Japanese, English,
        Korean, Chinese, and other European languages based on Unicode scripts.
        """
        import re

        cleaned = re.sub(r"[\s\d\W_]+", "", text)
        if not cleaned:
            return self.selected_languages[0] if self.selected_languages else ("ja" if track == "self" else "en")

        # 1. Japanese Kana check (hiragana / katakana) - 100% Japanese
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
            return "ja"

        # 2. Korean Hangul check - 100% Korean
        if re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", text):
            return "ko"

        # Count character categories
        latin_chars = len(re.findall(r"[A-Za-z\u00C0-\u024F\u1EA0-\u1EF9]", text))
        hanzi_chars = len(re.findall(r"[\u4E00-\u9FFF]", text))
        total_alpha = latin_chars + hanzi_chars

        # 3. Latin alphabet dominant (English, French, German, Spanish, etc.)
        if latin_chars > 0 and (total_alpha == 0 or (latin_chars / max(1, total_alpha)) >= 0.5):
            # German unique letters
            if re.search(r"[äöüÄÖÜß]", text):
                return "de"
            # French unique letters or characteristic stop words
            if re.search(r"[çœÇŒ]", text) or ("fr" in self.selected_languages and re.search(r"\b(le|la|les|des|un|une|est|et|pour|dans|qui|que)\b", text, re.IGNORECASE)):
                return "fr"
            # Spanish unique letters or characteristic stop words
            if re.search(r"[ñÑ¿¡]", text) or ("es" in self.selected_languages and re.search(r"\b(el|la|los|las|un|una|es|y|por|para|que|en)\b", text, re.IGNORECASE)):
                return "es"

            # If English is selected or no specific Latin language markers found
            if "en" in self.selected_languages or not any(l in ("fr", "de", "es") for l in self.selected_languages):
                return "en"
            # Fallback to the first latin language in selected_languages
            for l in self.selected_languages:
                if l in ("en", "fr", "de", "es"):
                    return l
            return "en"

        # 4. Chinese Hanzi (without Kana)
        if hanzi_chars > 0:
            if "zh" in self.selected_languages and "ja" not in self.selected_languages:
                return "zh"
            if "ja" in self.selected_languages and "zh" not in self.selected_languages:
                return "ja"
            # Check characteristic Chinese particles
            if re.search(r"[的了是我你他在有这那们会说要为和与]", text):
                return "zh"
            return "zh" if "zh" in self.selected_languages else "ja"

        # Fallback to the first selected language
        return self.selected_languages[0] if self.selected_languages else "ja"

    def on_audio_chunk(self, track: str, pcm_512: np.ndarray):
        """Called by DualTrackCapture for every 512-sample (32ms) audio block."""
        vad = self.vads.get(track, self.vads["self"])
        is_speech = vad.is_speech(pcm_512)

        with self._lock:
            preroll = self._preroll.setdefault(track, collections.deque(maxlen=8))
            buf = self._buffers.setdefault(track, [])

            if is_speech:
                if not self._is_speaking[track]:
                    self._is_speaking[track] = True
                    # Prepend pre-roll audio (~256ms) to avoid cutting off first consonant
                    buf.extend(list(preroll))
                    print(f"[VAD:{track}] Speech started...")
                buf.append(pcm_512)
                self._silence_frames[track] = 0
            else:
                if self._is_speaking[track]:
                    buf.append(pcm_512)
                    self._silence_frames[track] += 1
                else:
                    # Keep recent audio as preroll while silent
                    preroll.append(pcm_512)

            # End of speech detection: ~12 frames (approx 380ms of silence)
            if self._is_speaking[track] and self._silence_frames[track] >= 12:
                if len(buf) >= 12:  # At least ~0.38s of audio
                    segment = np.concatenate(buf).astype(np.float32)
                    utterance_id = uuid.uuid4().hex[:8]
                    self._queues[track].put((utterance_id, segment))

                # Reset track state
                self._buffers[track] = []
                self._is_speaking[track] = False
                self._silence_frames[track] = 0
                preroll.clear()

            # Guard against infinite monologue buffer without pause (split at ~12s)
            elif len(buf) > 375:
                segment = np.concatenate(buf).astype(np.float32)
                utterance_id = uuid.uuid4().hex[:8]
                self._queues[track].put((utterance_id, segment))
                # Keep small overlap (~8 frames / 256ms) to avoid cutting words
                self._buffers[track] = list(buf[-8:])
                self._silence_frames[track] = 0

    def _process_segment(self, track: str, segment: np.ndarray, utterance_id: str):
        """Transcribe and multicast translate to all other selected languages."""
        dur = len(segment) / 16000.0

        # Smart hint: If remote track and only one non-Japanese target language is active
        hint_lang = None
        if track == "remote":
            non_ja = [l for l in self.selected_languages if l != "ja"]
            if len(non_ja) == 1:
                hint_lang = non_ja[0]

        text = self.asr_engine.transcribe_pcm(segment, hint_lang=hint_lang)
        if not text or not text.strip():
            return

        src_lang = self._detect_src_lang(track, text)
        print(f"[ASR:{track}] Speech recognized ({dur:.2f}s, {len(text)} chars, src_lang='{src_lang}')")

        # Emit raw subtitle immediately with unique utterance_id
        self.subtitle_ready.emit(track, text, {}, utterance_id)
        broadcast_event("subtitle", {"id": utterance_id, "track": track, "text": text, "translations": {}})

        target_langs = [l for l in self.selected_languages if l != src_lang]
        if target_langs:
            def on_translated(orig: str, trans_dict: Dict[str, str]):
                if trans_dict:
                    print(f"[Translate:{track}] Translated to {list(trans_dict.keys())}")
                    self.translations_ready.emit(utterance_id, trans_dict)
                    broadcast_event("translation", {"id": utterance_id, "translations": trans_dict})

            self.translator.translate_multicast_async(text, src_lang, target_langs, on_translated)


def find_models_dir() -> Path:
    candidates = [
        _HERE / "models",
        Path("models"),
        _HERE.parent / "models",
    ]
    for c in candidates:
        if c.is_dir() and (c / "silero_vad.onnx").exists():
            return c
    return _HERE / "models"


def main():
    # Set Windows App ID for proper taskbar/tray behavior
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hayamimi.Polyglot.1.0")
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("=======================================================")
    print("  🎙️🌐 Hayamimi Polyglot")
    print("  Status: 100% Offline / Localhost Bound (127.0.0.1:8844)")
    print("  Security: Zero audio recording to disk. Non-admin.")
    print("=======================================================")

    # 1. Initialize Core Engines
    models_dir = find_models_dir()
    print(f"[Init] Using Models Directory: {models_dir}")

    print("[Init] Loading VAD engines (isolated instances for self & remote tracks)...")
    vad_self = SileroVAD(models_dir=models_dir)
    vad_remote = SileroVAD(models_dir=models_dir)

    print("[Init] Loading ReazonSpeech ASR engine...")
    asr_engine = BusinessASREngine(models_dir=models_dir)

    print("[Init] Loading Local Translator...")
    translator = LocalTranslator(models_dir=models_dir)

    print("[Init] Loading Business Dictionary...")
    dictionary = BusinessDictionary()

    # 2. Start Local Web Server (127.0.0.1:8844)
    print("[Init] Starting Local Web Server on 127.0.0.1:8844...")
    web_server = BusinessWebServer(host="127.0.0.1", port=8844)
    web_server.start()

    # 3. Create UI
    overlay = OverlayWindow()
    panel = ControlPanel(overlay=overlay)
    tray = SystemTrayApp(panel=panel)

    worker = SessionWorker(
        asr_engine=asr_engine,
        vad_self=vad_self,
        vad_remote=vad_remote,
        translator=translator,
    )
    capture: Optional[DualTrackCapture] = None

    # Sync initial languages and listen for changes
    initial_langs = panel.get_selected_languages()
    worker.set_selected_languages(initial_langs)

    def on_config_changed(cfg: dict):
        if "languages" in cfg:
            worker.set_selected_languages(cfg["languages"])
    panel.config_changed.connect(on_config_changed)

    # Connect Signals with Utterance ID matching (B6, B8, B9)
    def on_subtitle_ready(track: str, text: str, translations: dict, utterance_id: str):
        overlay.add_subtitle(track, text, translations, item_id=utterance_id)
        panel.append_transcript_line(track, text, translations, item_id=utterance_id)

    def on_translations_ready(utterance_id: str, translations: dict):
        overlay.update_last_translations(translations, item_id=utterance_id)
        panel.update_transcript_translation(utterance_id, translations)

    worker.subtitle_ready.connect(on_subtitle_ready)
    worker.translations_ready.connect(on_translations_ready)

    # High Accuracy Mode Sync
    asr_engine.high_accuracy_mode = panel.chk_high_acc.isChecked()
    def on_high_acc_changed(enabled: bool):
        asr_engine.high_accuracy_mode = enabled
        print(f"[ASR] High Accuracy Mode set to: {enabled}")
    panel.high_accuracy_toggled.connect(on_high_acc_changed)

    # Start meeting callback
    def on_start_meeting():
        nonlocal capture
        # Read selected remote app
        remote_pid = panel.combo_app.currentData()
        # Read selected microphone
        selected_mic = panel.combo_mic.currentData()
        # Read selected languages (Max 5)
        selected_langs = panel.get_selected_languages()
        worker.set_selected_languages(selected_langs)

        print(f"[Meeting] Starting... (Mic: {selected_mic}, Remote PID: {remote_pid}, Languages: {selected_langs})")
        capture = DualTrackCapture(
            on_chunk=worker.on_audio_chunk,
            mic_device=selected_mic,
            remote_pid=remote_pid if remote_pid != 0 else None,
        )
        capture.start()

    def on_stop_meeting():
        nonlocal capture
        print("[Meeting] Stopping and sanitizing session data...")
        if capture:
            capture.stop()
            capture = None

        # Data Hygiene & Zero Telemetry (S8, S9, M4):
        # 1. Clean temporary agenda hotwords file from disk and memory
        hw_file = Path(__file__).resolve().parent / "dicts" / "session_hotwords.txt"
        if hw_file.exists():
            try:
                hw_file.unlink()
                print("[Meeting] Temporary hotwords file deleted.")
            except Exception:
                pass
        dictionary.clear_instant_hotwords()
        asr_engine.update_hotwords(None)

        # 2. Clear in-memory transcript from web server and overlay
        web_server.clear_history()
        overlay.history.clear()
        overlay.refresh_display()
        worker.reset_state()
        print("[Meeting] In-memory transcript buffers completely cleared.")

    def on_hotwords_submitted(agenda_text: str):
        keywords = dictionary.extract_keywords_from_text(agenda_text)
        dictionary.set_instant_hotwords(keywords)
        hw_file = Path(__file__).resolve().parent / "dicts" / "session_hotwords.txt"
        dictionary.generate_hotwords_file(hw_file)
        asr_engine.update_hotwords(hw_file)
        print(f"[Hotwords] Extracted {len(keywords)} keywords from agenda (sanitized).")

    panel.start_requested.connect(on_start_meeting)
    panel.stop_requested.connect(on_stop_meeting)
    panel.hotwords_submitted.connect(on_hotwords_submitted)

    # Initial show
    panel.show()

    # Run Qt Event Loop
    exit_code = app.exec()

    # Final Application Cleanup (M4)
    on_stop_meeting()
    web_server.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
