"""
Hayamimi For Business - Dual Track Audio Capture Manager.
Zero recording to disk. Pure in-memory streaming.
Separates Track 1 (Self / Microphone) and Track 2 (Remote / Zoom / Teams)
with zero computational overhead.
"""

from __future__ import annotations

import os
import platform
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from .win_loopback import (
    ApplicationLoopbackCapture,
    list_audio_processes,
    AudioProcess,
)


def _resample_linear(audio: np.ndarray, orig_sr: int, target_sr: int = 16000) -> np.ndarray:
    """Ultra-fast linear interpolation resampler (zero external dependencies)."""
    if orig_sr == target_sr:
        return audio
    orig_len = len(audio)
    target_len = int(round(orig_len * target_sr / orig_sr))
    if orig_len == 0 or target_len == 0:
        return np.zeros(0, dtype=np.float32)
    x_orig = np.linspace(0, 1, orig_len, endpoint=False)
    x_target = np.linspace(0, 1, target_len, endpoint=False)
    return np.interp(x_target, x_orig, audio).astype(np.float32)


class DualTrackCapture:
    """
    Manages simultaneous capture of:
      - Track 'self': User's physical microphone
      - Track 'remote': Meeting application (Zoom / Teams) or Speaker loopback
    """

    def __init__(
        self,
        on_chunk: Callable[[str, np.ndarray], None],
        mic_device: Optional[int | str] = None,
        remote_pid: Optional[int] = None,
        sample_rate: int = 16000,
        chunk_size: int = 512,
    ):
        self.on_chunk = on_chunk
        self.mic_device = mic_device
        self.remote_pid = remote_pid
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        self.running = False
        self._stop_event = threading.Event()
        self._mic_thread: Optional[threading.Thread] = None
        self._remote_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start both capture tracks."""
        if self.running:
            return
        self.running = True
        self._stop_event.clear()

        # 1. Start Mic thread (Track: self)
        self._mic_thread = threading.Thread(
            target=self._run_mic, name="DualCapture-Mic", daemon=True
        )
        self._mic_thread.start()

        # 2. Start Remote App thread (Track: remote)
        self._remote_thread = threading.Thread(
            target=self._run_remote, name="DualCapture-Remote", daemon=True
        )
        self._remote_thread.start()

    def stop(self) -> None:
        """Stop all capture threads."""
        self.running = False
        self._stop_event.set()
        if self._mic_thread and self._mic_thread.is_alive():
            self._mic_thread.join(timeout=1.0)
        if self._remote_thread and self._remote_thread.is_alive():
            self._remote_thread.join(timeout=1.0)

    def _run_mic(self) -> None:
        """Capture microphone using robust sounddevice streaming."""
        dev_info = None
        is_wasapi = False
        device_name = "Default"
        try:
            if self.mic_device is not None:
                dev_info = sd.query_devices(self.mic_device)
            else:
                default_in = sd.default.device[0]
                if default_in >= 0:
                    dev_info = sd.query_devices(default_in)
            if dev_info:
                device_name = dev_info.get("name", "Unknown")
                hostapi_id = dev_info.get("hostapi", -1)
                if hostapi_id >= 0:
                    api_name = sd.query_hostapis(hostapi_id).get("name", "")
                    is_wasapi = "WASAPI" in api_name
        except Exception as ex:
            print(f"[Audio Mic] Query warning: {ex}")

        print(f"[Audio Mic] Target device: '{device_name}' (ID: {self.mic_device}, WASAPI: {is_wasapi})")

        # Approach 1: Direct 16kHz stream (with auto_convert for WASAPI)
        opened = False
        extra_settings = None
        if is_wasapi and hasattr(sd, "WasapiSettings"):
            try:
                extra_settings = sd.WasapiSettings(auto_convert=True)
            except Exception:
                pass

        try:
            def direct_cb(indata, frames, time_info, status):
                if not self.running:
                    raise sd.CallbackStop()
                mono = indata[:, 0].copy()
                self.on_chunk("self", mono)

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.chunk_size,
                device=self.mic_device,
                extra_settings=extra_settings,
                callback=direct_cb,
            ):
                print(f"[Audio Mic] Direct 16kHz stream successfully started on '{device_name}'.")
                opened = True
                while self.running and not self._stop_event.is_set():
                    self._stop_event.wait(0.1)
        except Exception as exc:
            print(f"[Audio Mic] Direct stream open notice ({exc}). Switching to adaptive native-rate fallback...")

        if opened or not self.running or self._stop_event.is_set():
            return

        # Approach 2: Adaptive native samplerate + channels fallback with software resampler
        try:
            native_sr = int(dev_info.get("default_samplerate", 48000)) if dev_info else 48000
            max_in = int(dev_info.get("max_input_channels", 1)) if dev_info else 1
            native_ch = max(1, min(2, max_in))
            native_block = int(native_sr * 0.032)  # ~32ms

            rem_buf = np.zeros(0, dtype=np.float32)
            rem_lock = threading.Lock()

            def native_cb(indata, frames, time_info, status):
                nonlocal rem_buf
                if not self.running:
                    raise sd.CallbackStop()
                if native_ch > 1:
                    mono = indata.mean(axis=1)
                else:
                    mono = indata[:, 0]
                resampled = _resample_linear(mono, native_sr, self.sample_rate)
                with rem_lock:
                    rem_buf = np.concatenate([rem_buf, resampled])
                    while len(rem_buf) >= self.chunk_size:
                        chunk = rem_buf[:self.chunk_size]
                        rem_buf = rem_buf[self.chunk_size:]
                        self.on_chunk("self", chunk)

            with sd.InputStream(
                samplerate=native_sr,
                channels=native_ch,
                dtype="float32",
                blocksize=native_block,
                device=self.mic_device,
                callback=native_cb,
            ):
                print(f"[Audio Mic] Native fallback stream running ({native_sr}Hz {native_ch}ch -> 16kHz) on '{device_name}'.")
                while self.running and not self._stop_event.is_set():
                    self._stop_event.wait(0.1)
        except Exception as exc2:
            print(f"[Audio Mic] Critical: Both direct and native mic capture failed: {exc2}")

    def _run_remote(self) -> None:
        """Capture Zoom/Teams or Speaker audio."""
        if platform.system() == "Windows":
            self._run_remote_windows()
        else:
            self._run_remote_mac()

    def _run_remote_windows(self) -> None:
        """Windows Application Loopback or Full Speaker capture."""
        try:
            from .win_loopback import (
                app_chunks,
                PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE,
                PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE,
            )

            if self.remote_pid and self.remote_pid > 0:
                # Capture specific application (e.g. Zoom.exe)
                target_pid = self.remote_pid
                mode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
                print(f"[Audio:Remote] Capturing target application PID: {target_pid}")
            else:
                # Capture all speaker audio EXCEPT our own process (Default Loopback)
                target_pid = os.getpid()
                mode = PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE
                print(f"[Audio:Remote] Capturing all speaker audio (excluding self PID: {target_pid})")

            for chunk in app_chunks(
                target_pid,
                output_sample_rate=self.sample_rate,
                chunk_size=self.chunk_size,
                stop_event=self._stop_event,
                loopback_mode=mode,
            ):
                if not self.running or self._stop_event.is_set():
                    break
                self.on_chunk("remote", chunk)
        except Exception as exc:
            print(f"[Audio:Remote] Process Loopback error: {exc}")
            self._run_speaker_fallback()

    def _run_speaker_fallback(self) -> None:
        """Secondary fallback using sounddevice WASAPI loopback device query."""
        try:
            wasapi_hostapi = None
            for idx, h in enumerate(sd.query_hostapis()):
                if "wasapi" in h.get("name", "").lower():
                    wasapi_hostapi = idx
                    break

            wasapi_loopback = None
            if wasapi_hostapi is not None:
                for idx, dev in enumerate(sd.query_devices()):
                    if dev.get("hostapi") == wasapi_hostapi and dev.get("max_input_channels") > 0:
                        if "loopback" in dev.get("name", "").lower():
                            wasapi_loopback = idx
                            break

            if wasapi_loopback is not None:
                def loopback_cb(indata, frames, time_info, status):
                    if not self.running:
                        raise sd.CallbackStop()
                    mono = indata[:, 0].copy()
                    self.on_chunk("remote", mono)

                with sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=self.chunk_size,
                    device=wasapi_loopback,
                    callback=loopback_cb,
                ):
                    while self.running and not self._stop_event.is_set():
                        self._stop_event.wait(0.1)
        except Exception as exc:
            print(f"[Audio:Remote] Speaker fallback error: {exc}")

    def _run_remote_mac(self) -> None:
        """macOS remote audio capture via ScreenCaptureKit / BlackHole."""
        try:
            from .mac_loopback import MacScreenCaptureKitAudio
            capture = MacScreenCaptureKitAudio(
                process_id=self.remote_pid or 0,
                sample_rate=self.sample_rate,
                chunk_size=self.chunk_size,
                stop_event=self._stop_event,
            )
            capture.start()
            for chunk in capture.chunks():
                if not self.running or self._stop_event.is_set():
                    break
                self.on_chunk("remote", chunk)
        except Exception as exc:
            print(f"[Audio:Remote:Mac] Error: {exc}")
            while self.running and not self._stop_event.is_set():
                self._stop_event.wait(0.1)

