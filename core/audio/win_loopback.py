"""
Windows per-application audio capture using WASAPI Application Loopback.

This module captures the audio rendered by one Windows process and its
children, using the Windows Application Loopback API:

    ActivateAudioInterfaceAsync(
        VAD\\Process_Loopback,
        IAudioClient,
        AUDIOCLIENT_ACTIVATION_PARAMS
    )

The captured audio is returned as float32 numpy arrays.

Requirements:
    Windows 10 build 20348 or later
    comtypes
    numpy

The Application Loopback API does not capture a physical output device.
Instead, it creates a virtual process-loopback capture stream which is
filtered by TargetProcessId.

Microsoft documentation:
    https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/
    nf-mmdeviceapi-activateaudiointerfaceasync

    https://learn.microsoft.com/en-us/windows/win32/api/
    audioclientactivationparams/

The official Microsoft Application Loopback sample uses the same API.
"""

from __future__ import annotations

import ctypes
import os
import struct
import threading
import time
from ctypes import POINTER, byref, c_bool, c_float, c_long, c_ulong
from ctypes import c_void_p, cast, sizeof
from dataclasses import dataclass
from typing import Iterator

import numpy as np


if os.name != "nt":
    # Graceful fallback on macOS / non-Windows systems
    @dataclass
    class AudioProcess:
        pid: int
        name: str
        executable: str = ""

    def list_audio_processes() -> list[AudioProcess]:
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
        def chunks(self): return iter(())
        def __enter__(self): return self
        def __exit__(self, *args): pass
else:
    try:
        import comtypes
        from comtypes import GUID, COMMETHOD, STDMETHOD, HRESULT
        from comtypes import IUnknown
        from comtypes import COMObject
    except ImportError as exc:
        raise RuntimeError(
            "windows_audio.py requires the 'comtypes' package. "
            "Install it with: pip install comtypes"
        ) from exc


# ---------------------------------------------------------------------------
# Windows constants
# ---------------------------------------------------------------------------

S_OK = 0x00000000
S_FALSE = 0x00000001

E_FAIL = 0x80004005
E_POINTER = 0x80004003
E_INVALIDARG = 0x80070057
E_NOINTERFACE = 0x80004002
E_ILLEGAL_METHOD_CALL = 0x8000000E

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

AUDCLNT_SHAREMODE_SHARED = 0

AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000

AUDCLNT_BUFFERFLAGS_SILENT = 0x00000002

# The virtual device used by the Windows process loopback API.
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

# AUDIOCLIENT_ACTIVATION_TYPE
AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1

# PROCESS_LOOPBACK_MODE
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

# PROPVARIANT VT_BLOB
VT_BLOB = 65

# WAVE_FORMAT_EXTENSIBLE
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

# Subformat GUIDs.
KSDATAFORMAT_SUBTYPE_PCM = GUID(
    "{00000001-0000-0010-8000-00AA00389B71}"
)

KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID(
    "{00000003-0000-0010-8000-00AA00389B71}"
)


# ---------------------------------------------------------------------------
# GUIDs
# ---------------------------------------------------------------------------

IID_IUnknown = GUID("{00000000-0000-0000-C000-000000000046}")

IID_IAudioClient = GUID(
    "{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}"
)

IID_IAudioCaptureClient = GUID(
    "{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"
)

IID_IActivateAudioInterfaceAsyncOperation = GUID(
    "{72A22D78-CDE4-431D-B8CC-843A71199B6D}"
)

IID_IActivateAudioInterfaceCompletionHandler = GUID(
    "{41D949AB-9862-444A-80F6-C261334DA5EB}"
)

IID_IAgileObject = GUID(
    "{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}"
)


# ---------------------------------------------------------------------------
# ctypes structures
# ---------------------------------------------------------------------------


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", c_ulong),
        ("ProcessLoopbackMode", c_ulong),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [
        ("ActivationType", c_ulong),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class BLOB(ctypes.Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("pBlobData", POINTER(ctypes.c_ubyte)),
    ]


class PROPVARIANT_BLOB(ctypes.Union):
    _fields_ = [
        ("blob", BLOB),
    ]


class PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("value", PROPVARIANT_BLOB),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort),
        ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_ulong),
        ("nAvgBytesPerSec", ctypes.c_ulong),
        ("nBlockAlign", ctypes.c_ushort),
        ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _fields_ = [
        ("Format", WAVEFORMATEX),
        ("Samples", ctypes.c_ushort),
        ("dwChannelMask", ctypes.c_ulong),
        ("SubFormat", GUID),
    ]


# ---------------------------------------------------------------------------
# COM interfaces
# ---------------------------------------------------------------------------


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceAsyncOperation

    _methods_ = [
        STDMETHOD(
            HRESULT,
            "GetActivateResult",
            (POINTER(HRESULT), POINTER(c_void_p)),
        ),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler

    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "ActivateCompleted",
            (
                ["in"],
                POINTER(IActivateAudioInterfaceAsyncOperation),
                "activate_operation",
            ),
        ),
    ]


class IAgileObject(IUnknown):
    _iid_ = IID_IAgileObject


class IAudioClient(IUnknown):
    _iid_ = IID_IAudioClient

    _methods_ = [
        STDMETHOD(
            HRESULT,
            "Initialize",
            (
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_ulonglong,
                ctypes.c_ulonglong,
                POINTER(WAVEFORMATEX),
                POINTER(GUID),
            ),
        ),
        STDMETHOD(
            HRESULT,
            "GetBufferSize",
            (POINTER(c_ulong),),
        ),
        STDMETHOD(
            HRESULT,
            "GetStreamLatency",
            (POINTER(ctypes.c_longlong),),
        ),
        STDMETHOD(
            HRESULT,
            "GetCurrentPadding",
            (POINTER(c_ulong),),
        ),
        STDMETHOD(
            HRESULT,
            "IsFormatSupported",
            (
                ctypes.c_ulong,
                POINTER(WAVEFORMATEX),
                POINTER(POINTER(WAVEFORMATEX)),
            ),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetMixFormat",
            (
                ["out"],
                POINTER(POINTER(WAVEFORMATEX)),
                "ppDeviceFormat",
            ),
        ),
        STDMETHOD(
            HRESULT,
            "GetDevicePeriod",
            (POINTER(ctypes.c_longlong), POINTER(ctypes.c_longlong)),
        ),
        STDMETHOD(HRESULT, "Start"),
        STDMETHOD(HRESULT, "Stop"),
        STDMETHOD(HRESULT, "Reset"),
        STDMETHOD(
            HRESULT,
            "SetEventHandle",
            (c_void_p,),
        ),
        STDMETHOD(
            HRESULT,
            "GetService",
            (POINTER(GUID), POINTER(c_void_p)),
        ),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = IID_IAudioCaptureClient

    _methods_ = [
        STDMETHOD(
            HRESULT,
            "GetBuffer",
            (
                POINTER(POINTER(ctypes.c_ubyte)),
                POINTER(c_ulong),
                POINTER(c_ulong),
                POINTER(ctypes.c_ulonglong),
                POINTER(ctypes.c_ulonglong),
            ),
        ),
        STDMETHOD(
            HRESULT,
            "ReleaseBuffer",
            (c_ulong,),
        ),
        STDMETHOD(
            HRESULT,
            "GetNextPacketSize",
            (POINTER(c_ulong),),
        ),
    ]


# ---------------------------------------------------------------------------
# COM completion handler
# ---------------------------------------------------------------------------


class _ActivationHandler:
    """
    Raw COM completion handler for ActivateAudioInterfaceAsync.

    This deliberately does not inherit from comtypes.COMObject.  Windows may
    call IActivateAudioInterfaceCompletionHandler from an RPC/COM worker
    thread, and comtypes.COMObject has to perform a Python QueryInterface on
    that path.  With Python 3.13 this can hit CPython's thread-state attach
    guard and abort the entire process.

    The vtable below is implemented with ctypes callbacks instead.  ctypes
    creates/attaches the Python thread state for the callback without using
    comtypes' COM server machinery.
    """

    def __init__(self):
        self.event = threading.Event()
        self.interface = None
        self.activate_result = None
        self.callback_result = None
        self._exception = None
        self._ref_count = 1
        self._lock = threading.Lock()

        self._query_interface_cb = _QUERY_INTERFACE_CB(self._query_interface)
        self._add_ref_cb = _ADD_REF_CB(self._add_ref)
        self._release_cb = _RELEASE_CB(self._release)
        self._activate_completed_cb = _ACTIVATE_COMPLETED_CB(
            self._activate_completed
        )

        self._vtable = (_VTableEntry * 4)(
            ctypes.cast(self._query_interface_cb, c_void_p),
            ctypes.cast(self._add_ref_cb, c_void_p),
            ctypes.cast(self._release_cb, c_void_p),
            ctypes.cast(self._activate_completed_cb, c_void_p),
        )
        self._instance = _ComInstance(
            ctypes.cast(self._vtable, POINTER(c_void_p))
        )
        self.pointer = ctypes.cast(
            ctypes.pointer(self._instance),
            c_void_p,
        )

    def _query_interface(self, this, riid, ppv):
        if not ppv:
            return E_POINTER

        iid = riid.contents
        if iid == IID_IUnknown or iid == IID_IActivateAudioInterfaceCompletionHandler or iid == IID_IAgileObject:
            ppv[0] = self.pointer
            self._add_ref(this)
            return S_OK

        ppv[0] = None
        return E_NOINTERFACE

    def _add_ref(self, this):
        with self._lock:
            self._ref_count += 1
            return self._ref_count

    def _release(self, this):
        with self._lock:
            if self._ref_count > 0:
                self._ref_count -= 1
            return self._ref_count

    def _activate_completed(self, this, activate_operation):
        try:
            operation = ctypes.cast(
                activate_operation,
                POINTER(IActivateAudioInterfaceAsyncOperation),
            )

            activate_result = HRESULT()
            activated_interface = c_void_p()

            hr = operation.GetActivateResult(
                byref(activate_result),
                byref(activated_interface),
            )

            self.callback_result = int(hr)
            self.activate_result = int(activate_result.value)

            if (
                hr == S_OK
                and activate_result.value == S_OK
                and activated_interface.value
            ):
                self.interface = activated_interface.value

        except Exception as exc:
            self.callback_result = E_FAIL
            self.activate_result = E_FAIL
            self.interface = None
            self._exception = exc
        finally:
            self.event.set()

        return S_OK

    def close(self):
        # Keep callback function objects and the vtable alive until Windows has
        # finished invoking the completion handler.  At this point the caller
        # has already waited for event, so dropping the references is safe.
        self._query_interface_cb = None
        self._add_ref_cb = None
        self._release_cb = None
        self._activate_completed_cb = None
        self._vtable = None
        self._instance = None
        self.pointer = None


# Raw COM ABI for the completion handler.  Using a ctypes vtable avoids
# comtypes.COMObject.QueryInterface on an arbitrary COM callback thread.
_VTableEntry = c_void_p

_QUERY_INTERFACE_CB = ctypes.WINFUNCTYPE(
    HRESULT,
    c_void_p,
    POINTER(GUID),
    POINTER(c_void_p),
)
_ADD_REF_CB = ctypes.WINFUNCTYPE(
    ctypes.c_ulong,
    c_void_p,
)
_RELEASE_CB = ctypes.WINFUNCTYPE(
    ctypes.c_ulong,
    c_void_p,
)
_ACTIVATE_COMPLETED_CB = ctypes.WINFUNCTYPE(
    HRESULT,
    c_void_p,
    POINTER(IActivateAudioInterfaceAsyncOperation),
)


class _ComInstance(ctypes.Structure):
    _fields_ = [
        ("lpVtbl", POINTER(c_void_p)),
    ]


# ---------------------------------------------------------------------------
# Windows DLL bindings
# ---------------------------------------------------------------------------


_mmdevapi = ctypes.windll.mmdevapi
_kernel32 = ctypes.windll.kernel32
_ole32 = ctypes.windll.ole32


_ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
_ActivateAudioInterfaceAsync.argtypes = [
    ctypes.c_wchar_p,
    POINTER(GUID),
    POINTER(PROPVARIANT),
    c_void_p,
    POINTER(c_void_p),
]
_ActivateAudioInterfaceAsync.restype = HRESULT


_CoInitializeEx = _ole32.CoInitializeEx
_CoInitializeEx.argtypes = [
    c_void_p,
    ctypes.c_ulong,
]
_CoInitializeEx.restype = HRESULT


_CoUninitialize = _ole32.CoUninitialize
_CoUninitialize.argtypes = []
_CoUninitialize.restype = None


_CoTaskMemFree = _ole32.CoTaskMemFree
_CoTaskMemFree.argtypes = [c_void_p]
_CoTaskMemFree.restype = None


_CreateEventW = _kernel32.CreateEventW
_CreateEventW.argtypes = [
    c_void_p,
    c_bool,
    c_bool,
    ctypes.c_wchar_p,
]
_CreateEventW.restype = c_void_p


_SetEvent = _kernel32.SetEvent
_SetEvent.argtypes = [c_void_p]
_SetEvent.restype = c_bool


_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [c_void_p]
_CloseHandle.restype = c_bool


_WaitForSingleObject = _kernel32.WaitForSingleObject
_WaitForSingleObject.argtypes = [
    c_void_p,
    ctypes.c_ulong,
]
_WaitForSingleObject.restype = ctypes.c_ulong


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hresult_failed(hr: int) -> bool:
    return ctypes.c_long(hr).value < 0


def _check_hr(hr: int, operation: str) -> None:
    value = int(hr)

    if _hresult_failed(value):
        raise OSError(
            f"{operation} failed with HRESULT "
            f"0x{value & 0xFFFFFFFF:08X}"
        )


def _guid_to_bytes(guid: GUID) -> bytes:
    return bytes(guid)


def _subformat_is_float(guid: GUID) -> bool:
    return _guid_to_bytes(guid) == _guid_to_bytes(
        KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
    )


def _subformat_is_pcm(guid: GUID) -> bool:
    return _guid_to_bytes(guid) == _guid_to_bytes(
        KSDATAFORMAT_SUBTYPE_PCM
    )


def _free_wave_format(ptr) -> None:
    if ptr:
        _CoTaskMemFree(ptr)


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    bits_per_sample: int
    block_align: int
    is_float: bool


def _parse_wave_format(ptr) -> AudioFormat:
    if not ptr:
        raise RuntimeError("Windows returned a null WAVEFORMATEX")

    base = ptr.contents

    if base.wFormatTag == WAVE_FORMAT_EXTENSIBLE:
        ext = ctypes.cast(
            ptr,
            POINTER(WAVEFORMATEXTENSIBLE),
        ).contents

        is_float = _subformat_is_float(ext.SubFormat)

        if not is_float and not _subformat_is_pcm(ext.SubFormat):
            raise RuntimeError(
                f"Unsupported WAVEFORMATEXTENSIBLE subtype: "
                f"{ext.SubFormat}"
            )

        return AudioFormat(
            sample_rate=int(ext.Format.nSamplesPerSec),
            channels=int(ext.Format.nChannels),
            bits_per_sample=int(ext.Format.wBitsPerSample),
            block_align=int(ext.Format.nBlockAlign),
            is_float=is_float,
        )

    if base.wFormatTag == 3:
        is_float = True
    elif base.wFormatTag == 1:
        is_float = False
    else:
        raise RuntimeError(
            f"Unsupported WAVEFORMATEX format tag: "
            f"{base.wFormatTag}"
        )

    return AudioFormat(
        sample_rate=int(base.nSamplesPerSec),
        channels=int(base.nChannels),
        bits_per_sample=int(base.wBitsPerSample),
        block_align=int(base.nBlockAlign),
        is_float=is_float,
    )


# ---------------------------------------------------------------------------
# Application Loopback capture
# ---------------------------------------------------------------------------


class ApplicationLoopbackCapture:
    """
    Capture audio rendered by one Windows process.

    Example:

        capture = ApplicationLoopbackCapture(1234)

        try:
            capture.start()

            for chunk in capture.chunks():
                # chunk is float32 numpy audio
                ...
        finally:
            capture.stop()

    The captured stream includes the target process and its child
    processes.

    The Windows API itself may return a native format such as:

        48000 Hz / stereo / float32

    The `chunks()` method converts it to float32 numpy arrays and
    optionally mixes stereo to mono.
    """

    def __init__(
        self,
        process_id: int,
        *,
        mono: bool = True,
        target_chunk_size: int = 512,
        stop_event: threading.Event | None = None,
    ):
        if process_id <= 0:
            raise ValueError("process_id must be greater than zero")

        self.process_id = int(process_id)
        self.mono = bool(mono)
        self.target_chunk_size = int(target_chunk_size)
        self.stop_event = stop_event

        if self.target_chunk_size <= 0:
            raise ValueError("target_chunk_size must be greater than zero")

        self._client = None
        self._capture_client = None

        self._event_handle = None
        self._started = False
        self._stopped = False

        self._format: AudioFormat | None = None
        self._buffer_size = 0

        self._leftover = np.zeros(
            0,
            dtype=np.float32,
        )

        self._activation_handler = None
        self._activation_operation = None

        self._com_initialized = False

    @property
    def format(self) -> AudioFormat | None:
        return self._format

    @property
    def sample_rate(self) -> int | None:
        if self._format is None:
            return None
        return self._format.sample_rate

    @property
    def channels(self) -> int | None:
        if self._format is None:
            return None
        return self._format.channels

    def start(self) -> None:
        if self._started:
            return

        self._initialize_com()
        self._create_event()

        self._activate_process_loopback()
        self._initialize_audio_client()

        self._started = True
        self._stopped = False

    def stop(self) -> None:
        if self._stopped:
            return

        self._stopped = True
        self._started = False

        if self._client is not None:
            try:
                self._client.Stop()
            except Exception:
                pass

        if self._capture_client is not None:
            self._capture_client = None

        if self._client is not None:
            self._client = None

        if self._event_handle:
            try:
                _CloseHandle(self._event_handle)
            except Exception:
                pass

            self._event_handle = None

        self._activation_handler = None
        self._activation_operation = None

        if self._com_initialized:
            try:
                _CoUninitialize()
            except Exception:
                pass

            self._com_initialized = False

    def __enter__(self) -> "ApplicationLoopbackCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()

    def _initialize_com(self) -> None:
        # COINIT_MULTITHREADED = 0x0
        #
        # pycaw/comtypes may already have initialized COM on this thread
        # (typically as an STA) while enumerating audio sessions. In that
        # case CoInitializeEx(COINIT_MULTITHREADED) returns
        # RPC_E_CHANGED_MODE. The existing COM apartment is still usable,
        # so keep using it and do not call CoUninitialize ourselves.
        try:
            hr = _CoInitializeEx(None, 0)
        except OSError as exc:
            # ctypes converts a failing HRESULT into OSError before returning
            # from the call, so RPC_E_CHANGED_MODE must be handled here.
            if getattr(exc, "winerror", None) == -2147417850:
                self._com_initialized = False
                return
            raise

        # S_OK = newly initialized.
        # S_FALSE = already initialized with the same model.
        if hr in (S_OK, S_FALSE):
            self._com_initialized = True
            return

        # Kept for completeness in case the ctypes binding returns the
        # HRESULT directly instead of raising OSError.
        if ctypes.c_long(hr).value == -2147417850:
            self._com_initialized = False
            return

        _check_hr(hr, "CoInitializeEx")

    def _create_event(self) -> None:
        handle = _CreateEventW(
            None,
            False,
            False,
            None,
        )

        if not handle:
            raise OSError(
                "CreateEventW failed"
            )

        self._event_handle = handle

    def _activate_process_loopback(self) -> None:
        activation = AUDIOCLIENT_ACTIVATION_PARAMS()

        activation.ActivationType = (
            AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
        )

        activation.ProcessLoopbackParams.TargetProcessId = (
            self.process_id
        )

        activation.ProcessLoopbackParams.ProcessLoopbackMode = (
            PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        )

        activation_blob = ctypes.cast(
            ctypes.pointer(activation),
            POINTER(ctypes.c_ubyte),
        )

        prop = PROPVARIANT()
        prop.vt = VT_BLOB
        prop.blob.cbSize = sizeof(activation)
        prop.blob.pBlobData = activation_blob

        handler = _ActivationHandler()
        self._activation_handler = handler

        async_operation = c_void_p()

        hr = _ActivateAudioInterfaceAsync(
            VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            byref(IID_IAudioClient),
            byref(prop),
            handler.pointer,
            byref(async_operation),
        )

        _check_hr(
            hr,
            "ActivateAudioInterfaceAsync",
        )

        self._activation_operation = async_operation

        # Windows invokes the completion handler asynchronously.
        if not handler.event.wait(timeout=10.0):
            raise TimeoutError(
                "Timed out waiting for ActivateAudioInterfaceAsync"
            )

        if handler._exception is not None:
            raise RuntimeError(
                "Application Loopback activation callback failed"
            ) from handler._exception

        if handler.activate_result is None:
            raise RuntimeError(
                "Application Loopback activation returned no result"
            )

        _check_hr(
            handler.activate_result,
            "ActivateAudioInterfaceAsync activation",
        )

        if not handler.interface:
            raise RuntimeError(
                "Application Loopback activation returned no IAudioClient"
            )

        # `interface` is an IUnknown pointer returned by
        # GetActivateResult(). Cast it into IAudioClient.
        self._client = ctypes.cast(
            handler.interface,
            POINTER(IAudioClient),
        )


    def _initialize_audio_client(self) -> None:
        # Process-based Application Loopback does not expose a physical
        # audio endpoint.  Its AudioSes CMixerClient implementation does
        # not implement IAudioClient::GetMixFormat (it returns E_NOTIMPL).
        # Microsoft's official ApplicationLoopback sample therefore uses
        # a fixed 16-bit / 44.1 kHz / stereo PCM capture format.
        capture_format = WAVEFORMATEX()
        capture_format.wFormatTag = 1  # WAVE_FORMAT_PCM
        capture_format.nChannels = 2
        capture_format.nSamplesPerSec = 44100
        capture_format.wBitsPerSample = 16
        capture_format.nBlockAlign = (
            capture_format.nChannels * capture_format.wBitsPerSample // 8
        )
        capture_format.nAvgBytesPerSec = (
            capture_format.nSamplesPerSec * capture_format.nBlockAlign
        )
        capture_format.cbSize = 0

        self._format = AudioFormat(
            sample_rate=44100,
            channels=2,
            bits_per_sample=16,
            block_align=int(capture_format.nBlockAlign),
            is_float=False,
        )

        # 200 ms buffer.
        hns_buffer_duration = 2_000_000

        # The official Microsoft Application Loopback sample uses
        # shared-mode WASAPI and loopback capture. Autoconvert lets the
        # audio engine convert the rendered application audio to the
        # requested PCM format.
        stream_flags = (
            AUDCLNT_STREAMFLAGS_LOOPBACK
            | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
            | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
            | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
        )

        hr = self._client.Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            stream_flags,
            hns_buffer_duration,
            0,
            byref(capture_format),
            None,
        )

        _check_hr(
            hr,
            "IAudioClient.Initialize",
        )

        buffer_size = c_ulong()

        hr = self._client.GetBufferSize(
            byref(buffer_size)
        )

        _check_hr(
            hr,
            "IAudioClient.GetBufferSize",
        )

        self._buffer_size = int(
            buffer_size.value
        )

        hr = self._client.SetEventHandle(
            self._event_handle
        )

        _check_hr(
            hr,
            "IAudioClient.SetEventHandle",
        )

        capture_client_ptr = c_void_p()

        hr = self._client.GetService(
            byref(IID_IAudioCaptureClient),
            byref(capture_client_ptr),
        )

        _check_hr(
            hr,
            "IAudioClient.GetService(IAudioCaptureClient)",
        )

        if not capture_client_ptr.value:
            raise RuntimeError(
                "IAudioClient.GetService returned null IAudioCaptureClient"
            )

        self._capture_client = ctypes.cast(
            capture_client_ptr,
            POINTER(IAudioCaptureClient),
        )

        hr = self._client.Start()

        _check_hr(
            hr,
            "IAudioClient.Start",
        )

    def _wait_for_audio(self) -> bool:
        if self._event_handle is None:
            return False

        result = _WaitForSingleObject(
            self._event_handle,
            100,
        )

        if result == WAIT_OBJECT_0:
            return True

        if result == WAIT_TIMEOUT:
            return False

        raise OSError(
            f"WaitForSingleObject failed: 0x{result:08X}"
        )

    def _read_available_packets(self) -> np.ndarray:
        """
        Read every currently available WASAPI packet.

        Returns an empty array when there is currently no packet.
        """

        if self._capture_client is None:
            return np.zeros(
                0,
                dtype=np.float32,
            )

        output = []

        while True:
            packet_frames = c_ulong()

            hr = self._capture_client.GetNextPacketSize(
                byref(packet_frames)
            )

            _check_hr(
                hr,
                "IAudioCaptureClient.GetNextPacketSize",
            )

            frames = int(packet_frames.value)

            if frames == 0:
                break

            data_ptr = POINTER(
                ctypes.c_ubyte
            )()

            num_frames = c_ulong()
            flags = c_ulong()
            device_position = ctypes.c_ulonglong()
            qpc_position = ctypes.c_ulonglong()

            hr = self._capture_client.GetBuffer(
                byref(data_ptr),
                byref(num_frames),
                byref(flags),
                byref(device_position),
                byref(qpc_position),
            )

            _check_hr(
                hr,
                "IAudioCaptureClient.GetBuffer",
            )

            try:
                frame_count = int(
                    num_frames.value
                )

                if frame_count == 0:
                    continue

                if flags.value & AUDCLNT_BUFFERFLAGS_SILENT:
                    samples = np.zeros(
                        frame_count * self._format.channels,
                        dtype=np.float32,
                    )

                else:
                    samples = self._decode_audio_buffer(
                        data_ptr,
                        frame_count,
                    )

                if self.mono and self._format.channels > 1:
                    samples = samples.reshape(
                        -1,
                        self._format.channels,
                    ).mean(axis=1)

                output.append(
                    samples
                )

            finally:
                hr = self._capture_client.ReleaseBuffer(
                    num_frames
                )

                _check_hr(
                    hr,
                    "IAudioCaptureClient.ReleaseBuffer",
                )

        if not output:
            return np.zeros(
                0,
                dtype=np.float32,
            )

        return np.concatenate(
            output
        ).astype(
            np.float32,
            copy=False,
        )

    def _decode_audio_buffer(
        self,
        data_ptr,
        frame_count: int,
    ) -> np.ndarray:
        channels = self._format.channels
        bits = self._format.bits_per_sample
        total_samples = frame_count * channels

        if self._format.is_float:
            if bits == 32:
                array_type = ctypes.c_float * total_samples
                values = np.ctypeslib.as_array(
                    array_type.from_address(
                        ctypes.addressof(data_ptr.contents)
                    )
                )
                return values.astype(
                    np.float32,
                    copy=True,
                )

            if bits == 64:
                array_type = ctypes.c_double * total_samples
                values = np.ctypeslib.as_array(
                    array_type.from_address(
                        ctypes.addressof(data_ptr.contents)
                    )
                )
                return values.astype(
                    np.float32,
                    copy=True,
                )

            raise RuntimeError(
                f"Unsupported float audio depth: {bits} bits"
            )

        if bits == 16:
            array_type = ctypes.c_int16 * total_samples
            values = np.ctypeslib.as_array(
                array_type.from_address(
                    ctypes.addressof(data_ptr.contents)
                )
            )

            return (
                values.astype(
                    np.float32,
                    copy=True,
                )
                / 32768.0
            )

        if bits == 24:
            raw = ctypes.string_at(
                ctypes.addressof(data_ptr.contents),
                total_samples * 3,
            )

            data = np.frombuffer(
                raw,
                dtype=np.uint8,
            ).reshape(
                -1,
                3,
            )

            values = (
                data[:, 0].astype(np.int32)
                | (data[:, 1].astype(np.int32) << 8)
                | (data[:, 2].astype(np.int32) << 16)
            )

            negative = (
                values & 0x800000
            ) != 0

            values[negative] -= 0x1000000

            return (
                values.astype(np.float32)
                / 8388608.0
            )

        if bits == 32:
            array_type = ctypes.c_int32 * total_samples
            values = np.ctypeslib.as_array(
                array_type.from_address(
                    ctypes.addressof(data_ptr.contents)
                )
            )

            return (
                values.astype(
                    np.float32,
                    copy=True,
                )
                / 2147483648.0
            )

        raise RuntimeError(
            f"Unsupported PCM audio depth: {bits} bits"
        )

    def chunks(self) -> Iterator[np.ndarray]:
        """
        Yield fixed-size float32 chunks.

        The output is mono when `mono=True`.

        Note:
            This function does not resample. The native Windows loopback
            sample rate is exposed through `capture.sample_rate`.
        """

        if not self._started:
            self.start()

        try:
            while not self._stopped:
                if (
                    self.stop_event is not None
                    and self.stop_event.is_set()
                ):
                    break

                self._wait_for_audio()

                if self._stopped:
                    break

                samples = self._read_available_packets()

                if len(samples):
                    self._leftover = np.concatenate(
                        [
                            self._leftover,
                            samples,
                        ]
                    )

                while (
                    len(self._leftover)
                    >= self.target_chunk_size
                ):
                    chunk = self._leftover[
                        :self.target_chunk_size
                    ]

                    self._leftover = self._leftover[
                        self.target_chunk_size:
                    ]

                    yield chunk.astype(
                        np.float32,
                        copy=False,
                    )

        finally:
            self.stop()


# ---------------------------------------------------------------------------
# Process enumeration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioProcess:
    """
    A process currently associated with a Windows audio session.
    """

    pid: int
    name: str
    executable: str = ""


def list_audio_processes() -> list[AudioProcess]:
    """
    Return processes which currently have Windows audio sessions.

    This uses pycaw because Windows' Audio Session Manager exposes the
    process association directly through IAudioSessionControl2.

    The function intentionally imports pycaw lazily so the rest of this
    module can still be imported without pycaw until enumeration is needed.
    """

    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise RuntimeError(
            "Listing audio applications requires the 'pycaw' package. "
            "Install it with: pip install pycaw"
        ) from exc

    processes: dict[int, AudioProcess] = {}

    sessions = AudioUtilities.GetAllSessions()

    for session in sessions:
        try:
            process = session.Process
        except Exception:
            process = None

        if process is None:
            continue

        try:
            pid = int(process.pid)
        except Exception:
            continue

        if pid <= 0:
            continue

        try:
            name = process.name()
        except Exception:
            name = f"PID {pid}"

        try:
            executable = process.exe()
        except Exception:
            executable = ""

        processes[pid] = AudioProcess(
            pid=pid,
            name=name,
            executable=executable,
        )

    return sorted(
        processes.values(),
        key=lambda item: (
            item.name.lower(),
            item.pid,
        ),
    )


def choose_audio_process() -> AudioProcess:
    """
    Show a simple terminal selection menu and return one audio process.

    This is intended for the initial CLI implementation. The main
    application can later replace this with a GUI/web UI without changing
    ApplicationLoopbackCapture.
    """

    processes = list_audio_processes()

    if not processes:
        raise RuntimeError(
            "No active Windows audio applications were found."
        )

    print()
    print("Available audio applications:")
    print()

    for index, process in enumerate(processes, start=1):
        print(
            f"[{index}] {process.name} "
            f"(PID {process.pid})"
        )

    print()

    while True:
        answer = input(
            "Select application number: "
        ).strip()

        try:
            index = int(answer)
        except ValueError:
            print("Please enter a number.")
            continue

        if 1 <= index <= len(processes):
            return processes[index - 1]

        print(
            f"Please enter a number from 1 to {len(processes)}."
        )


# ---------------------------------------------------------------------------
# Convenience generator
# ---------------------------------------------------------------------------


def resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear-interpolation resample to dst_rate."""
    if src_rate == dst_rate:
        return samples
    duration = len(samples) / src_rate
    dst_n = int(round(duration * dst_rate))
    if dst_n <= 0:
        return np.zeros(0, dtype=np.float32)
    src_x = np.arange(len(samples)) / src_rate
    dst_x = np.arange(dst_n) / dst_rate
    return np.interp(dst_x, src_x, samples).astype(np.float32)


def app_chunks(
    process_id: int,
    *,
    output_sample_rate: int = 16000,
    chunk_size: int = 512,
    stop_event: threading.Event | None = None,
) -> Iterator[np.ndarray]:
    """
    Capture one application and yield 16 kHz mono float32 chunks.

    This is the adapter that realtime_transcribe.py will use.

    Windows Application Loopback normally produces 48 kHz audio. The
    existing hayamimi pipeline expects SAMPLE_RATE=16000, so this function
    performs the final resampling before yielding chunks.
    """

    # Imported lazily to avoid making scipy mandatory merely for importing
    # this module. hayamimi already has its own resampling helper, but
    # realtime_transcribe.py will eventually be able to pass that helper
    # here. For now scipy provides a safe standalone fallback.
    # Standalone linear resampler used

    with ApplicationLoopbackCapture(
        process_id,
        mono=True,
        target_chunk_size=chunk_size,
        stop_event=stop_event,
    ) as capture:

        source_rate = capture.sample_rate

        if source_rate is None:
            raise RuntimeError(
                "Application Loopback did not expose a sample rate."
            )

        leftover = np.zeros(
            0,
            dtype=np.float32,
        )

        for chunk in capture.chunks():
            if (
                source_rate != output_sample_rate
            ):
                chunk = resample_linear(
                    chunk,
                    source_rate,
                    output_sample_rate,
                )

            leftover = np.concatenate(
                [
                    leftover,
                    chunk,
                ]
            )

            while len(leftover) >= chunk_size:
                output = leftover[
                    :chunk_size
                ]

                leftover = leftover[
                    chunk_size:
                ]

                yield output.astype(
                    np.float32,
                    copy=False,
                )
