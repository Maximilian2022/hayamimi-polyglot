"""
Hayamimi For Business (hayamimi4b) - Main Entry Point.
Integrates:
  - PySide6 System Tray + Floating Control Panel
  - Transparent Stealth-protected Subtitle Overlay
  - Localhost (127.0.0.1:8844) Screen Sharing Web View
  - Dual-track Audio Capture (Self Mic + Remote Zoom/Teams Loopback)
  - Silero VAD + ReazonSpeech INT8 ASR
  - CTranslate2 Local Translation (ja->en, en->ja)
  - Zero disk audio recording. Zero external telemetry.
"""

from __future__ import annotations

import collections
import os
import platform
import sys
import threading
import time
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

    subtitle_ready = QtCore.Signal(str, str, dict)  # (track, text, translations_dict)
    translations_ready = QtCore.Signal(dict)        # (translations_dict)

    def __init__(
        self,
        asr_engine: BusinessASREngine,
        vad: SileroVAD,
        translator: LocalTranslator,
    ):
        super().__init__()
        self.asr_engine = asr_engine
        self.vad = vad
        self.translator = translator

        self.selected_languages: List[str] = ["ja", "en"]

        # Per-track audio buffers & VAD state
        self._buffers: Dict[str, List[np.ndarray]] = {"self": [], "remote": []}
        self._silence_frames: Dict[str, int] = {"self": 0, "remote": 0}
        self._is_speaking: Dict[str, bool] = {"self": False, "remote": False}
        self._lock = threading.Lock()

    def set_selected_languages(self, langs: List[str]):
        self.selected_languages = langs[:5]

    def _detect_src_lang(self, track: str, text: str) -> str:
        """Detect source language from text characters and audio track."""
        import re
        # Check Japanese Hiragana / Katakana
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
            return "ja"
        # Check Korean Hangul
        if re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", text):
            return "ko"
        # Check Chinese Hanzi (when no hiragana/katakana)
        if re.search(r"[\u4E00-\u9FFF]", text):
            return "zh"
        # Default: if Track is self -> ja, else en
        return "ja" if track == "self" else "en"

    def on_audio_chunk(self, track: str, pcm_512: np.ndarray):
        """Called by DualTrackCapture for every 512-sample (32ms) audio block."""
        is_speech = self.vad.is_speech(pcm_512)

        with self._lock:
            buf = self._buffers.setdefault(track, [])
            buf.append(pcm_512)

            if is_speech:
                self._is_speaking[track] = True
                self._silence_frames[track] = 0
            else:
                if self._is_speaking[track]:
                    self._silence_frames[track] += 1

            # End of speech detection: ~12 frames (approx 380ms of silence)
            if self._is_speaking[track] and self._silence_frames[track] >= 12:
                if len(buf) >= 15:  # At least ~0.5s of audio
                    segment = np.concatenate(buf).astype(np.float32)
                    threading.Thread(
                        target=self._process_segment,
                        args=(track, segment),
                        daemon=True,
                    ).start()

                # Reset track state
                self._buffers[track] = []
                self._is_speaking[track] = False
                self._silence_frames[track] = 0

            # Guard against infinite monologue buffer without pause (split at ~15s)
            elif len(buf) > 480:
                segment = np.concatenate(buf).astype(np.float32)
                threading.Thread(
                    target=self._process_segment,
                    args=(track, segment),
                    daemon=True,
                ).start()
                self._buffers[track] = []

    def _process_segment(self, track: str, segment: np.ndarray):
        """Transcribe and multicast translate to all other selected languages."""
        text = self.asr_engine.transcribe_pcm(segment)
        if not text:
            return

        # Emit raw subtitle immediately
        self.subtitle_ready.emit(track, text, {})
        broadcast_event("subtitle", {"track": track, "text": text, "translations": {}})

        src_lang = self._detect_src_lang(track, text)
        target_langs = [l for l in self.selected_languages if l != src_lang]

        if target_langs:
            def on_translated(orig: str, trans_dict: Dict[str, str]):
                if trans_dict:
                    self.translations_ready.emit(trans_dict)
                    broadcast_event("subtitle", {"track": track, "text": orig, "translations": trans_dict})

            self.translator.translate_multicast_async(text, src_lang, target_langs, on_translated)


def find_models_dir() -> Path:
    candidates = [
        _HERE / "models",
        Path("models"),
        _HERE.parent / "models",
        Path("E:/hayamimi/models"),
        Path.home() / "hayamimi/models",
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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hayamimi.Business.1.0")
        except Exception:
            pass

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("=======================================================")
    print("  Hayamimi For Business (hayamimi4b)")
    print("  Status: 100% Offline / Localhost Bound (127.0.0.1:8844)")
    print("  Security: Zero audio recording to disk. Non-admin.")
    print("=======================================================")

    # 1. Initialize Core Engines
    models_dir = find_models_dir()
    print(f"[Init] Using Models Directory: {models_dir}")

    print("[Init] Loading VAD engine...")
    vad = SileroVAD(models_dir=models_dir)

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

    worker = SessionWorker(asr_engine=asr_engine, vad=vad, translator=translator)
    capture: Optional[DualTrackCapture] = None

    # Connect Signals
    def on_subtitle_ready(track: str, text: str, translations: dict):
        overlay.add_subtitle(track, text, translations)
        panel.append_transcript_line(track, text, translations)

    def on_translations_ready(translations: dict):
        overlay.update_last_translations(translations)

    worker.subtitle_ready.connect(on_subtitle_ready)
    worker.translations_ready.connect(on_translations_ready)

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
        print("[Meeting] Stopping...")
        if capture:
            capture.stop()
            capture = None

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

    # Cleanup
    if capture:
        capture.stop()
    web_server.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
