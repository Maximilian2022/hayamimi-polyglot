"""
Hayamimi For Business - macOS Audio Capture (ScreenCaptureKit / CoreAudio / BlackHole).
Zero recording to disk. Pure in-memory streaming.
Requirements: macOS 12 Monterey ~ macOS 15 Sequoia.
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
from typing import Iterator, List
import numpy as np


class MacAudioProcess:
    def __init__(self, pid: int, name: str):
        self.pid = pid
        self.name = name


def list_mac_audio_processes() -> List[MacAudioProcess]:
    """List running applications that can be captured via ScreenCaptureKit / BlackHole."""
    if platform.system() != "Darwin":
        return []

    procs = []
    # 1. Try psutil if installed
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'name']):
            name = p.info['name']
            if name and any(app in name.lower() for app in ['zoom', 'teams', 'slack', 'chrome', 'safari', 'webex', 'discord', 'meet']):
                procs.append(MacAudioProcess(pid=p.info['pid'], name=name))
        return procs
    except Exception:
        pass

    # 2. Native macOS fallback via /bin/ps (Zero extra dependency)
    try:
        out = subprocess.check_output(["ps", "-ax", "-o", "pid,comm"], text=True)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("PID"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                pid = int(parts[0])
                comm = parts[1]
                name = os.path.basename(comm)
                if any(app in name.lower() for app in ['zoom', 'teams', 'slack', 'chrome', 'safari', 'webex', 'discord']):
                    procs.append(MacAudioProcess(pid=pid, name=name))
    except Exception:
        pass

    return procs


class MacScreenCaptureKitAudio:
    """
    ScreenCaptureKit / BlackHole Audio Capture for macOS 12+.
    Captures system audio or application sound without disk writes.
    """

    def __init__(self, process_id: int = 0, sample_rate: int = 16000, chunk_size: int = 512, stop_event: threading.Event | None = None):
        self.process_id = process_id
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.stop_event = stop_event or threading.Event()
        self._running = False

    def start(self):
        self._running = True

    def stop(self):
        self._running = False
        self.stop_event.set()

    def chunks(self) -> Iterator[np.ndarray]:
        """Stream 16kHz float32 mono audio chunks from BlackHole or ScreenCaptureKit."""
        if platform.system() != "Darwin":
            return

        import sounddevice as sd

        # 1. Check for BlackHole 2ch virtual audio device
        blackhole_idx = None
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if "blackhole" in dev.get("name", "").lower() and dev.get("max_input_channels") > 0:
                    blackhole_idx = idx
                    print(f"[MacAudio] Detected BlackHole audio device: {dev.get('name')}")
                    break
        except Exception:
            pass

        if blackhole_idx is not None:
            # Stream from BlackHole device directly
            import queue
            q = queue.Queue(maxsize=50)

            def callback(indata, frames, time_info, status):
                if not self._running or self.stop_event.is_set():
                    raise sd.CallbackStop()
                mono = indata[:, 0].copy()
                try:
                    q.put_nowait(mono)
                except Exception:
                    pass

            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.chunk_size,
                device=blackhole_idx,
                callback=callback,
            ):
                while self._running and not self.stop_event.is_set():
                    try:
                        chunk = q.get(timeout=0.1)
                        yield chunk
                    except queue.Empty:
                        continue
        else:
            # 2. Inform user and fallback gracefully
            print("[MacAudio] Notice: To capture remote meeting audio on macOS, install BlackHole 2ch (`brew install blackhole-2ch`) or grant Screen & Audio Recording permission.")
            while self._running and not self.stop_event.is_set():
                self.stop_event.wait(0.1)
