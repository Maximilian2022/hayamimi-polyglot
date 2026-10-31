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
        """Capture microphone using sounddevice."""
        try:
            def callback(indata, frames, time_info, status):
                if status:
                    pass
                if not self.running:
                    raise sd.CallbackStop()
                # Mono float32 16kHz
                mono = indata[:, 0].copy()
                self.on_chunk("self", mono)

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.chunk_size,
                device=self.mic_device,
                callback=callback,
            ):
                while self.running and not self._stop_event.is_set():
                    self._stop_event.wait(0.1)
        except Exception as exc:
            pass

    def _run_remote(self) -> None:
        """Capture Zoom/Teams or Speaker audio."""
        if platform.system() == "Windows":
            self._run_remote_windows()
        else:
            self._run_remote_mac()

    def _run_remote_windows(self) -> None:
        """Windows Application Loopback or Speaker capture."""
        if self.remote_pid and self.remote_pid > 0:
            # Capture specific application (e.g. Zoom.exe)
            try:
                from .win_loopback import app_chunks
                for chunk in app_chunks(
                    self.remote_pid,
                    output_sample_rate=self.sample_rate,
                    chunk_size=self.chunk_size,
                    stop_event=self._stop_event,
                ):
                    if not self.running or self._stop_event.is_set():
                        break
                    self.on_chunk("remote", chunk)
            except Exception as exc:
                # Fallback to speaker if PID fails
                self._run_speaker_fallback()
        else:
            self._run_speaker_fallback()

    def _run_speaker_fallback(self) -> None:
        """Fallback to standard WASAPI loopback (default output device)."""
        try:
            # sounddevice WASAPI loopback device
            wasapi_loopback = None
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("hostapi") == 1:  # WASAPI
                    if dev.get("max_input_channels") > 0 and "loopback" in dev.get("name", "").lower():
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
        except Exception:
            pass

    def _run_remote_mac(self) -> None:
        """macOS capture stub."""
        while self.running and not self._stop_event.is_set():
            self._stop_event.wait(0.1)

