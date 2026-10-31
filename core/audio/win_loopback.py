"""
Windows per-application audio capture wrapper.
On Windows (os.name == 'nt'): loads full WASAPI loopback implementation from _win_loopback_impl.
On other OS (macOS, Linux): provides safe fallback stubs without import errors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, List

if os.name == "nt":
    from ._win_loopback_impl import *
else:
    @dataclass
    class AudioProcess:
        pid: int
        name: str
        executable: str = ""

    def list_audio_processes() -> List[AudioProcess]:
        return []

    def choose_audio_process() -> AudioProcess:
        return AudioProcess(pid=0, name="Default")

    def app_chunks(*args, **kwargs):
        return iter(())

    class ApplicationLoopbackCapture:
        def __init__(self, *args, **kwargs):
            pass
        def start(self): pass
        def stop(self): pass
        def chunks(self) -> Iterator: return iter(())
        def __enter__(self): return self
        def __exit__(self, *args): pass
