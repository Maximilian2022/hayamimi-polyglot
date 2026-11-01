"""
Hayamimi Polyglot - Main Entry Point.
Integrates:
  - PySide6 System Tray + Floating Control Panel
  - Transparent Stealth-protected Subtitle Overlay
  - Localhost (127.0.0.1) Screen Sharing Web View
  - Dual-track Audio Capture (Self Mic + Remote Meeting App Loopback)
  - 4-Stage Audio DSP Chain (Noise Gate, Mid-Range EQ, De-Esser, AGC Compressor)
  - Silero VAD + Multi-model Offline ASR (ReazonSpeech, Parakeet TDT v3, SenseVoice)
  - CTranslate2 Local Multilingual Translation (M2M-100 & FuguMT)
  - In-memory processing with no disk audio recording or external telemetry.
"""

from __future__ import annotations

import collections
import json
import os
import platform
import queue
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Windows: Register DLL directories for portable loading (VC++ runtime & PySide6)
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.isdir(_exe_dir):
        try:
            os.add_dll_directory(_exe_dir)
        except Exception:
            pass

import numpy as np
from PySide6 import QtCore, QtWidgets

# Ensure hayamimi root is on sys.path
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Core imports
from core.asr_engine import BusinessASREngine
from core.audio.dsp import AudioDSPChain
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
        vad_self: Optional[SileroVAD] = None,
        translator: Optional[LocalTranslator] = None,
        vad_remote: Optional[SileroVAD] = None,
        vad: Optional[SileroVAD] = None,
    ):
        super().__init__()
        self.asr_engine = asr_engine
        v_self = vad_self if vad_self is not None else vad
        self.vads: Dict[str, Optional[SileroVAD]] = {
            "self": v_self,
            "remote": vad_remote if vad_remote is not None else v_self,
        }
        self.translator = translator
        self.dsp = AudioDSPChain(sample_rate=16000)

        self.selected_languages: List[str] = ["ja", "en"]
        self._session_id: int = 0

        # Per-track audio buffers & VAD state
        self._buffers: Dict[str, List[np.ndarray]] = {"self": [], "remote": []}
        self._preroll: Dict[str, collections.deque] = {
            "self": collections.deque(maxlen=8),
            "remote": collections.deque(maxlen=8),
        }
        self._silence_frames: Dict[str, int] = {"self": 0, "remote": 0}
        self._speech_frames: Dict[str, int] = {"self": 0, "remote": 0}
        self._is_speaking: Dict[str, bool] = {"self": False, "remote": False}
        self._lock = threading.Lock()

        # Bounded worker queues per track (maxsize=8 keeps latency fresh under load)
        self._queues: Dict[str, queue.Queue] = {
            "self": queue.Queue(maxsize=8),
            "remote": queue.Queue(maxsize=8),
        }
        self._worker_threads = [
            threading.Thread(target=self._worker_loop, args=("self",), daemon=True, name="Worker-Self"),
            threading.Thread(target=self._worker_loop, args=("remote",), daemon=True, name="Worker-Remote"),
        ]
        for w in self._worker_threads:
            w.start()

    def _enqueue_segment(self, track: str, utterance_id: str, segment: np.ndarray) -> None:
        """Enqueue speech segment with freshness priority (drop oldest if full)."""
        q = self._queues[track]
        item = (self._session_id, utterance_id, segment)
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def _worker_loop(self, track: str):
        """Worker thread processing speech segments in chronological order."""
        while True:
            item = self._queues[track].get()
            if item is None:
                self._queues[track].task_done()
                break
            if len(item) == 3:
                seg_session_id, utterance_id, segment = item
            else:
                utterance_id, segment = item
                seg_session_id = self._session_id

            try:
                if seg_session_id == self._session_id:
                    self._process_segment(track, segment, utterance_id, seg_session_id)
            except Exception as e:
                print(f"[Worker:{track}] Segment processing error: {e}")
            finally:
                self._queues[track].task_done()

    def reset_state(self):
        """Reset internal buffers, increment session generation, and purge pending queues."""
        with self._lock:
            self._session_id += 1
            self._buffers = {"self": [], "remote": []}
            self._silence_frames = {"self": 0, "remote": 0}
            self._speech_frames = {"self": 0, "remote": 0}
            self._is_speaking = {"self": False, "remote": False}
            for q in self._preroll.values():
                q.clear()
            for v in self.vads.values():
                if v is not None:
                    v.reset()

        for q in self._queues.values():
            while True:
                try:
                    item = q.get_nowait()
                    q.task_done()
                    if item is None:
                        break
                except queue.Empty:
                    break

    def shutdown(self):
        """Stop worker threads cleanly."""
        self.reset_state()
        for q in self._queues.values():
            try:
                q.put_nowait(None)
            except Exception:
                pass

    def set_selected_languages(self, langs: List[str]):
        self.selected_languages = langs[:5] if langs else ["ja"]
        self.asr_engine.set_active_languages(self.selected_languages)

    def _detect_src_lang(self, track: str, text: str) -> str:
        """
        Detect source language from text characters and script heuristics.
        """
        cleaned = re.sub(r"[\s\d\W_]+", "", text)
        if not cleaned:
            return self.selected_languages[0] if self.selected_languages else "ja"

        # 1. Japanese Kana check (hiragana / katakana) -> Japanese
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
            return "ja"

        # 2. Korean Hangul check -> Korean
        if re.search(r"[\uAC00-\uD7AF\u1100-\u11FF]", text):
            return "ko"

        latin_chars = len(re.findall(r"[A-Za-z\u00C0-\u024F\u1EA0-\u1EF9]", text))
        hanzi_chars = len(re.findall(r"[\u4E00-\u9FFF]", text))
        total_alpha = latin_chars + hanzi_chars

        # 3. Latin alphabet dominant (English, French, German, Spanish)
        if latin_chars > 0 and (total_alpha == 0 or (latin_chars / max(1, total_alpha)) >= 0.5):
            # German unique characters or common function words
            if re.search(r"[äöüÄÖÜß]", text) or (
                "de" in self.selected_languages
                and re.search(r"\b(und|der|die|das|ist|nicht|mit|auf|für|eine|einem|wir|sie|ich)\b", text, re.IGNORECASE)
            ):
                return "de"
            # French unique characters or common function words
            if re.search(r"[çœæÇŒÆùûüÿàâéèêëïîô]", text) or (
                "fr" in self.selected_languages
                and re.search(r"\b(le|la|les|des|une|est|et|pour|dans|qui|que|pas|plus|nous|vous)\b", text, re.IGNORECASE)
            ):
                return "fr"
            # Spanish unique characters or common function words
            if re.search(r"[ñÑ¿¡áéíóúÁÉÍÓÚ]", text) or (
                "es" in self.selected_languages
                and re.search(r"\b(el|la|los|las|una|es|por|para|que|con|del|está|son|como|pero)\b", text, re.IGNORECASE)
            ):
                return "es"

            if "en" in self.selected_languages or not any(l in ("fr", "de", "es") for l in self.selected_languages):
                return "en"
            for l in self.selected_languages:
                if l in ("en", "fr", "de", "es"):
                    return l
            return "en"

        # 4. CJK Ideographs without Kana (Chinese vs Japanese Kanji-only)
        if hanzi_chars > 0:
            if getattr(self.asr_engine, "last_detected_lang", None) in ("zh", "ja"):
                det = self.asr_engine.last_detected_lang
                if det in self.selected_languages:
                    return det
            if "zh" in self.selected_languages:
                return "zh"
            if re.search(r"[的了是我你他在有这那们会说要为和与不个对项进汇报国学体发经]", text):
                return "zh"
            return "ja" if "ja" in self.selected_languages else "zh"

        return self.selected_languages[0] if self.selected_languages else "ja"

    def on_audio_chunk(self, track: str, pcm_512: np.ndarray):
        """Called by DualTrackCapture for every 512-sample (32ms) audio block."""
        vad = self.vads.get(track, self.vads["self"])
        is_speech = vad.is_speech(pcm_512) if vad is not None else False

        with self._lock:
            preroll = self._preroll.setdefault(track, collections.deque(maxlen=8))
            buf = self._buffers.setdefault(track, [])

            if is_speech:
                if not self._is_speaking[track]:
                    self._is_speaking[track] = True
                    self._speech_frames[track] = 0
                    buf.extend(list(preroll))
                buf.append(pcm_512)
                self._speech_frames[track] += 1
                self._silence_frames[track] = 0
            else:
                if self._is_speaking[track]:
                    buf.append(pcm_512)
                    self._silence_frames[track] += 1
                else:
                    preroll.append(pcm_512)

            # End of speech detection: ~12 frames (~380ms of silence)
            if self._is_speaking[track] and self._silence_frames[track] >= 12:
                # Require at least 4 active speech frames (~128ms) and >=12 total frames to filter transient clicks
                if self._speech_frames[track] >= 4 and len(buf) >= 12:
                    segment = np.concatenate(buf).astype(np.float32)
                    utterance_id = uuid.uuid4().hex[:8]
                    self._enqueue_segment(track, utterance_id, segment)

                self._buffers[track] = []
                self._is_speaking[track] = False
                self._silence_frames[track] = 0
                self._speech_frames[track] = 0
                preroll.clear()

            # Split continuous monologues at ~8 seconds (250 frames) for responsive subtitles
            elif len(buf) >= 250:
                if self._speech_frames[track] >= 4:
                    segment = np.concatenate(buf).astype(np.float32)
                    utterance_id = uuid.uuid4().hex[:8]
                    self._enqueue_segment(track, utterance_id, segment)
                self._buffers[track] = list(buf[-6:])
                self._silence_frames[track] = 0
                self._speech_frames[track] = 2

    def _process_segment(
        self,
        track: str,
        segment: np.ndarray,
        utterance_id: str,
        seg_session_id: Optional[int] = None,
    ):
        """Run Audio DSP chain, transcribe, and multicast translate to selected languages."""
        if seg_session_id is not None and seg_session_id != self._session_id:
            return

        dur = len(segment) / 16000.0

        # Apply 4-stage Audio DSP chain (Noise Gate -> Mid-Range EQ -> De-Esser -> AGC Compressor)
        processed_segment = self.dsp.process(segment)

        # Let BusinessASREngine automatically route across active meeting languages
        text = self.asr_engine.transcribe_pcm(processed_segment, hint_lang=None)
        if not text or not text.strip():
            return

        if seg_session_id is not None and seg_session_id != self._session_id:
            return

        src_lang = self._detect_src_lang(track, text)
        print(f"[ASR:{track}] Speech recognized ({dur:.2f}s, {len(text)} chars, src_lang='{src_lang}')")

        self.subtitle_ready.emit(track, text, {}, utterance_id)
        broadcast_event("subtitle", {"id": utterance_id, "track": track, "text": text, "translations": {}})

        target_langs = [l for l in self.selected_languages if l != src_lang]
        if target_langs and self.translator is not None:
            current_gen = self._session_id

            def on_translated(orig: str, trans_dict: Dict[str, str]):
                if current_gen != self._session_id:
                    return
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


def _read_initial_config() -> tuple[List[str], bool]:
    """Read initial languages and high_accuracy_mode from config before loading heavy ASR models."""
    cfg_path = _HERE / "config.json"
    if not cfg_path.is_file():
        cfg_path = _HERE / "config.default.json"
    langs = ["ja", "en"]
    high_acc = True
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_langs = data.get("audio", {}).get("selected_languages")
            if isinstance(saved_langs, list) and saved_langs:
                langs = [str(x) for x in saved_langs[:5]]
            high_acc = bool(data.get("asr", {}).get("high_accuracy_mode", True))
        except Exception:
            pass
    return langs, high_acc


def main():
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
    print("  Status: Offline / Localhost Bound (127.0.0.1)")
    print("  Security: In-memory processing. Non-admin.")
    print("=======================================================")

    models_dir = find_models_dir()
    print(f"[Init] Using Models Directory: {models_dir}")

    initial_langs, initial_high_acc = _read_initial_config()

    print("[Init] Loading Business Dictionary...")
    dictionary = BusinessDictionary()
    threading.Thread(target=dictionary.warmup, daemon=True, name="SudachiWarmup").start()

    vad_self: Optional[SileroVAD] = None
    vad_remote: Optional[SileroVAD] = None
    try:
        print("[Init] Loading VAD engines (isolated instances for self & remote tracks)...")
        vad_self = SileroVAD(models_dir=models_dir)
        vad_remote = SileroVAD(models_dir=models_dir)
    except Exception as exc:
        print(f"[Init] Warning: Silero VAD model could not be loaded: {exc}")

    print("[Init] Loading ASR engine...")
    asr_engine = BusinessASREngine(
        models_dir=models_dir,
        initial_languages=initial_langs,
        high_accuracy_mode=initial_high_acc,
        dictionary=dictionary,
    )

    print("[Init] Loading Local Translator...")
    translator = LocalTranslator(models_dir=models_dir)

    print("[Init] Starting Local Web Server on 127.0.0.1...")
    web_server = BusinessWebServer(host="127.0.0.1", port=8844)
    web_server.start()

    overlay = OverlayWindow()
    panel = ControlPanel(overlay=overlay)
    panel.browser_url_provider = web_server.get_view_url
    tray = SystemTrayApp(panel=panel)

    if vad_self is None or not asr_engine.has_any_model():
        panel.status_warning.emit("AIモデルが未導入です。「⚙️ モデル追加/更新」を実行してください。")
        QtWidgets.QMessageBox.warning(
            panel,
            "AIモデルが見つかりません",
            "音声認識またはVADモデルが見つかりませんでした。\n"
            "画面右下の「⚙️ モデル追加/更新」または scripts/download_models.py を実行してモデルを取得してください。",
        )

    worker = SessionWorker(
        asr_engine=asr_engine,
        vad_self=vad_self,
        vad_remote=vad_remote,
        translator=translator,
    )
    capture: Optional[DualTrackCapture] = None

    worker.set_selected_languages(panel.get_selected_languages())

    def on_config_changed(cfg: dict):
        if "languages" in cfg:
            worker.set_selected_languages(cfg["languages"])

    panel.config_changed.connect(on_config_changed)

    def on_subtitle_ready(track: str, text: str, translations: dict, utterance_id: str):
        overlay.add_subtitle(track, text, translations, item_id=utterance_id)
        panel.append_transcript_line(track, text, translations, item_id=utterance_id)

    def on_translations_ready(utterance_id: str, translations: dict):
        overlay.update_last_translations(translations, item_id=utterance_id)
        panel.update_transcript_translation(utterance_id, translations)

    worker.subtitle_ready.connect(on_subtitle_ready)
    worker.translations_ready.connect(on_translations_ready)

    def on_high_acc_changed(enabled: bool):
        asr_engine.high_accuracy_mode = enabled
        print(f"[ASR] High Accuracy Mode set to: {enabled}")

    panel.high_accuracy_toggled.connect(on_high_acc_changed)

    def on_start_meeting():
        nonlocal capture
        remote_pid = panel.combo_app.currentData()
        selected_mic = panel.combo_mic.currentData()
        selected_langs = panel.get_selected_languages()
        worker.set_selected_languages(selected_langs)

        print(f"[Meeting] Starting... (Mic: {selected_mic}, Remote PID: {remote_pid}, Languages: {selected_langs})")
        capture = DualTrackCapture(
            on_chunk=worker.on_audio_chunk,
            mic_device=selected_mic,
            remote_pid=remote_pid if remote_pid != 0 else None,
            on_error=lambda _trk, msg: panel.status_warning.emit(msg),
        )
        capture.start()

    def on_stop_meeting():
        nonlocal capture
        print("[Meeting] Stopping and clearing session data...")
        if capture:
            try:
                capture.stop()
            except Exception as e:
                print(f"[Meeting] Capture stop warning: {e}")
            capture = None

        try:
            worker.reset_state()
        except Exception as e:
            print(f"[Meeting] Worker reset warning: {e}")

        try:
            hw_file = _HERE / "dicts" / "session_hotwords.txt"
            if hw_file.exists():
                hw_file.unlink()
            dictionary.clear_instant_hotwords()
        except Exception as e:
            print(f"[Meeting] Hotwords cleanup warning: {e}")

        try:
            web_server.clear_history()
        except Exception as e:
            print(f"[Meeting] WebServer history clear warning: {e}")

        try:
            overlay.history.clear()
            overlay.refresh_display()
        except Exception as e:
            print(f"[Meeting] Overlay clear warning: {e}")

        print("[Meeting] In-memory session buffers cleared.")

    def on_hotwords_submitted(agenda_text: str):
        keywords = dictionary.extract_keywords_from_text(agenda_text)
        dictionary.set_instant_hotwords(keywords)
        print(f"[Hotwords] Activated {len(keywords)} instant hotwords in memory.")

    panel.start_requested.connect(on_start_meeting)
    panel.stop_requested.connect(on_stop_meeting)
    panel.hotwords_submitted.connect(on_hotwords_submitted)

    panel.show()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        try:
            on_stop_meeting()
        except Exception:
            pass
        try:
            worker.shutdown()
        except Exception:
            pass
        try:
            translator.shutdown(wait=False)
        except Exception:
            pass
        try:
            web_server.stop()
        except Exception:
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
