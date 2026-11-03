"""
Hayamimi Polyglot - optional Intel NPU backend (Windows only).

Importing this package never imports OpenVINO. Everything heavy happens lazily, so CPU mode
is completely unaffected when the NPU add-on is absent.
"""

from . import addons  # noqa: F401
from .device import NpuInfo, is_npu_available, probe  # noqa: F401
