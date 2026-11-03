"""
Hayamimi Polyglot - Intel NPU detection (Windows only).

`openvino` is imported lazily and defensively: with Windows Smart App Control a blocked
DLL surfaces as ImportError/OSError, and that must degrade to CPU mode, never crash the app.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Optional

from . import addons


@dataclass
class NpuInfo:
    available: bool
    name: str = ""
    reason: str = ""  # why it is unavailable (shown in the UI / log)


_lock = threading.Lock()
_cached: Optional[NpuInfo] = None
_core = None


def import_openvino():
    """Import openvino (from addons/packages if needed). Raises on failure."""
    addons.activate_paths()
    import openvino  # noqa: WPS433 - deliberate lazy import
    return openvino


def get_core():
    """Process-wide ov.Core (creating it is slow; it is shared by all NPU recognizers)."""
    global _core
    with _lock:
        if _core is None:
            ov = import_openvino()
            _core = ov.Core()
        return _core


def probe(refresh: bool = False) -> NpuInfo:
    """Detect an Intel NPU. Never raises."""
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return _cached
    info = _probe_uncached()
    with _lock:
        _cached = info
    return info


def _probe_uncached() -> NpuInfo:
    if sys.platform != "win32":
        return NpuInfo(False, reason="NPU モードは Windows (Intel NPU) のみ対応です")
    if addons.STATE.signature_error:
        return NpuInfo(False, reason=addons.STATE.signature_error)
    try:
        core = get_core()
    except ImportError:
        return NpuInfo(False, reason="NPU アドオン (OpenVINO) が未導入です")
    except OSError as exc:
        return NpuInfo(False, reason=f"OpenVINO を読み込めません（セキュリティ機能でブロックされた可能性）: {exc}")
    except Exception as exc:
        return NpuInfo(False, reason=f"OpenVINO の初期化に失敗しました: {exc}")
    try:
        if "NPU" not in core.available_devices:
            return NpuInfo(False, reason="Intel NPU が見つかりません（ドライバ未導入の可能性）")
        try:
            name = str(core.get_property("NPU", "FULL_DEVICE_NAME"))
        except Exception:
            name = "Intel NPU"
        return NpuInfo(True, name=name)
    except Exception as exc:
        return NpuInfo(False, reason=f"NPU の検出に失敗しました: {exc}")


def is_npu_available() -> bool:
    return probe().available
