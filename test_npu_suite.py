"""
Hayamimi Polyglot - NPU mode test suite.

Run:  python test_npu_suite.py

Sections 1-6 need neither an NPU nor OpenVINO and run anywhere (CI included).
Section 7 runs the real Intel NPU engines and is skipped, with a clear message, when no NPU,
OpenVINO add-on or NPU model set is present on the machine.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import numpy as np
import soundfile as sf

# Importing the main suite also fixes the Windows console encoding (UTF-8) once.
from test_polyglot_suite import network_isolation_guard

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

MODELS = _HERE / "models"


class Skip(Exception):
    pass


def expect_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


# ------------------------------------------------------------------------------
# 1. CPU mode must not know OpenVINO exists
# ------------------------------------------------------------------------------
def test_cpu_mode_does_not_touch_openvino():
    print("\n[NPU 1/7] CPU mode never loads OpenVINO ...")
    from core.asr_engine import BusinessASREngine

    already = "openvino" in sys.modules
    eng = BusinessASREngine(models_dir=MODELS, initial_languages=["ja", "en"])
    assert eng.device == "cpu" and eng.get_device_summary() == {}, "CPU engine must have no NPU state"
    assert already or "openvino" not in sys.modules, "CPU mode imported openvino"
    assert "core.npu.reazon" not in sys.modules or already, "CPU mode imported NPU engine modules"
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 2. Front-ends and helpers
# ------------------------------------------------------------------------------
def test_features_match_kaldi():
    print("\n[NPU 2/7] NumPy fbank matches the Kaldi reference ...")
    from core.npu.features import kaldi_fbank

    rng = np.random.default_rng(1234)
    t = np.arange(24000) / 16000.0
    sig = (0.3 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 1330 * t) * np.sin(2 * np.pi * 3 * t)
           + 0.02 * rng.standard_normal(len(t))).astype(np.float32)
    gold = np.load(_HERE / "tests_data" / "npu_fbank_golden.npz")
    zip_ = kaldi_fbank(sig, window="povey", low_freq=20.0, high_freq=-400.0)
    sv = kaldi_fbank(sig, window="hamming", low_freq=20.0, high_freq=0.0, scale=32768.0)
    assert zip_.shape == gold["zipformer"].shape and sv.shape == gold["sensevoice"].shape
    d1 = float(np.abs(zip_ - gold["zipformer"]).max())
    d2 = float(np.abs(sv - gold["sensevoice"]).max())
    assert d1 < 5e-3 and d2 < 5e-3, f"fbank mismatch: {d1}, {d2}"
    assert kaldi_fbank(np.zeros(0, dtype=np.float32)).shape == (0, 80)
    print(f"  max |diff| zipformer={d1:.2e} sensevoice={d2:.2e}")
    print("  [PASS]")


def test_text_and_window_helpers():
    print("\n[NPU 3/7] Decoding / windowing helpers ...")
    from core.npu.base import NpuRecognizerBase, resample_to_16k, split_windows, squeeze_cjk_spaces
    from core.npu.reazon import decode_byte_bpe, encoder_out_len
    from core.npu.sensevoice import ctc_greedy

    assert squeeze_cjk_spaces("うち の 中学 は 50 円") == "うちの中学は50円"
    assert squeeze_cjk_spaces("TO STOP すな るほど") == "TO STOPすなるほど"
    assert squeeze_cjk_spaces("Hello  world") == "Hello world"
    assert squeeze_cjk_spaces("  ") == ""

    # byte-level BPE: three tokens' worth of bytes for one kanji
    assert decode_byte_bpe("\u018d\u013a\u014b") == "日"
    assert decode_byte_bpe("IN") == "IN"
    assert encoder_out_len(100) == 23 and encoder_out_len(1000) == 248 and encoder_out_len(3) == 0

    # CTC: collapse repeats, drop blanks, skip the 4 special positions
    logits = np.zeros((10, 6), dtype=np.float32)
    for i, k in enumerate([3, 3, 3, 3, 2, 2, 0, 2, 4, 4]):
        logits[i, k] = 1.0
    assert ctc_greedy(logits, 6) == [2, 2, 4]

    pcm = np.random.default_rng(0).standard_normal(16000 * 25).astype(np.float32) * 0.1
    pcm[16000 * 9: 16000 * 9 + 800] = 0.0  # a quiet spot just before the 10 s limit
    parts = split_windows(pcm, 16000 * 10)
    assert sum(len(p) for p in parts) == len(pcm) and all(len(p) <= 16000 * 10 for p in parts)
    assert abs(len(parts[0]) - (16000 * 9 + 400)) < 1600, "cut should land in the quiet spot"
    assert len(split_windows(pcm[:16000], 16000 * 10)) == 1

    x48 = np.sin(2 * np.pi * 300 * np.arange(48000) / 48000).astype(np.float32)
    y = resample_to_16k(x48, 48000)
    assert abs(len(y) - 16000) <= 1 and 0.6 < float(np.abs(y[200:-200]).max()) < 1.1

    class Dummy(NpuRecognizerBase):
        window_seconds = 1.0

        def _transcribe_window(self, pcm):
            return f"{len(pcm)}"

    d = Dummy()
    s = d.create_stream()
    s.accept_waveform(16000, np.zeros(16000 * 2 + 8000, dtype=np.float32))
    d.decode_stream(s)
    sizes = [int(x) for x in s.result.text.split()]
    assert sum(sizes) == 16000 * 2 + 8000 and max(sizes) <= 16000 and len(sizes) >= 3, sizes
    s = d.create_stream()
    s.accept_waveform(16000, np.zeros(100, dtype=np.float32))
    d.decode_stream(s)
    assert s.result.text == "", "audio shorter than 0.1 s is ignored"
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 3. Add-on installer
# ------------------------------------------------------------------------------
def _make_addon(payload: dict, *, name="npu-test", version="1.0.0", min_app="1.0.0", wrap=None, bad_hash_for=None, extra_manifest=None):
    """Returns (zip bytes, manifest sha256)."""
    files = {k: hashlib.sha256(v).hexdigest() for k, v in payload.items()}
    if bad_hash_for:
        files[bad_hash_for] = "0" * 64
    manifest = {"format": 1, "name": name, "version": version, "min_app_version": min_app, "files": files}
    manifest.update(extra_manifest or {})
    mbytes = json.dumps(manifest).encode("utf-8")
    buf = io.BytesIO()
    prefix = f"{wrap}/" if wrap else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + "manifest.json", mbytes)
        for k, v in payload.items():
            zf.writestr(prefix + k, v)
    return buf.getvalue(), hashlib.sha256(mbytes).hexdigest()


def _drop(root: Path, fname: str, data: bytes, age: float = 30.0) -> Path:
    d = root / "addons"
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_bytes(data)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_addon_installer():
    print("\n[NPU 4/7] Add-on drop-in installer ...")
    from core.npu import addons

    ok_sig = lambda p: True
    payload = {"packages/pkg/lib.dll": b"MZ-fake-binary", "packages/pkg/__init__.py": b"x = 1\n", "models/npu/m/model.bin": b"\x00" * 64}

    def fresh():
        return Path(tempfile.mkdtemp(prefix="hayamimi_addon_"))

    # a) plain ZIP, manifest at the root
    root = fresh()
    data, mh = _make_addon(payload)
    z = _drop(root, "a.zip", data)
    assert addons.has_pending(root)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert [r.status for r in res] == ["installed"], res
    assert (root / "addons/packages/pkg/lib.dll").read_bytes() == b"MZ-fake-binary"
    assert (root / "models/npu/m/model.bin").is_file() and not z.exists(), "ZIP must be removed after install"
    assert "npu-test" in addons.installed_addons(root) and not (root / "addons/.staging/npu-test").exists()
    assert not addons.has_pending(root)

    # b) the same content wrapped in a folder (what many unzip tools / zippers produce)
    root = fresh()
    data, mh = _make_addon(payload, wrap="npu-test-1.0.0")
    _drop(root, "b.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "installed" and (root / "addons/packages/pkg/lib.dll").is_file()

    # c) manifest hash not pinned in the app -> refused, nothing extracted
    root = fresh()
    data, _ = _make_addon(payload)
    z = _drop(root, "c.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": "f" * 64}}, verifier=ok_sig)
    assert res[0].status == "error" and z.exists() and not (root / "addons/packages").exists()

    # d) corrupted file (hash mismatch) -> nothing is promoted, staging cleaned
    root = fresh()
    data, mh = _make_addon(payload, bad_hash_for="models/npu/m/model.bin")
    _drop(root, "d.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "error"
    assert not (root / "addons/packages").exists() and not (root / "models").exists()
    assert not (root / "addons/.staging/npu-test").exists()

    # e) Smart App Control: an unsigned native binary is never installed
    root = fresh()
    data, mh = _make_addon(payload)
    _drop(root, "e.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=lambda p: False)
    assert res[0].status == "error" and "署名" in res[0].message
    assert not (root / "addons/packages").exists()

    # f) path traversal in the manifest -> refused, nothing written outside
    root = fresh()
    evil = {"packages/../../escape.txt": b"boom"}
    data, mh = _make_addon(evil)
    _drop(root, "f.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "error" and not (root.parent / "escape.txt").exists() and not (root / "escape.txt").exists()
    for bad in ("/abs/x", "packages\\x.dll", "C:/x", "models/../x", "other/x"):
        d2, m2 = _make_addon({bad: b"1"})
        r2 = fresh()
        _drop(r2, "g.zip", d2)
        rs = addons.process_pending(r2, log=lambda m: None, known={"t": {"manifest_sha256": m2}}, verifier=ok_sig)
        assert rs and rs[0].status == "error", f"{bad!r} must be refused"

    # g) downloads in progress / unreadable ZIPs are deferred, unrelated ZIPs are left alone
    root = fresh()
    _drop(root, "h.zip.crdownload", b"partial")
    _drop(root, "broken.zip", b"PK\x03\x04 not really a zip")
    data, mh = _make_addon(payload)
    _drop(root, "fresh.zip", data, age=0.0)  # modified just now: still being written
    zp = io.BytesIO()
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("readme.txt", "hello")
    other = _drop(root, "photos.zip", zp.getvalue())
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    statuses = sorted(r.status for r in res)
    assert statuses == ["deferred", "deferred"], statuses
    assert other.exists() and (root / "addons/broken.zip").exists() and (root / "addons/fresh.zip").exists()
    assert not (root / "addons/packages").exists()

    # h) the user unzipped it by hand into addons/ -> accepted too
    root = fresh()
    data, mh = _make_addon(payload)
    folder = root / "addons" / "my-unzipped-copy"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(folder)
    assert addons.has_pending(root)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "installed" and not folder.exists()

    # i) upgrade: files of the old version that the new one does not ship are removed
    root = fresh()
    v1, m1 = _make_addon({"models/npu/m/old.bin": b"old", "models/npu/m/keep.bin": b"k1"}, version="1.0.0")
    v2, m2 = _make_addon({"models/npu/m/keep.bin": b"k2", "models/npu/m/new.bin": b"new"}, version="1.1.0")
    known = {"1": {"manifest_sha256": m1}, "2": {"manifest_sha256": m2}}
    _drop(root, "v1.zip", v1)
    addons.process_pending(root, log=lambda m: None, known=known, verifier=ok_sig)
    _drop(root, "v2.zip", v2)
    addons.process_pending(root, log=lambda m: None, known=known, verifier=ok_sig)
    m = root / "models/npu/m"
    assert not (m / "old.bin").exists() and (m / "new.bin").read_bytes() == b"new" and (m / "keep.bin").read_bytes() == b"k2"

    # j) needs a newer app
    root = fresh()
    data, mh = _make_addon(payload, min_app="99.0.0")
    _drop(root, "j.zip", data)
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "error" and "99.0.0" in res[0].message

    # k) re-verification of what is installed (cached by size+mtime), SAC fallback state
    root = fresh()
    (root / "addons/packages/pkg").mkdir(parents=True)
    (root / "addons/packages/pkg/a.dll").write_bytes(b"MZ")
    calls = []
    assert addons.check_installed_signatures(root, log=lambda m: None, verifier=lambda p: calls.append(p) or True)
    assert addons.check_installed_signatures(root, log=lambda m: None, verifier=lambda p: calls.append(p) or True)
    assert len(calls) == 1, "second start must use the verification cache"
    (root / "addons/packages/pkg/a.dll").write_bytes(b"MZ-tampered")
    assert not addons.check_installed_signatures(root, log=lambda m: None, verifier=lambda p: False)
    assert "署名" in addons.STATE.signature_error
    addons.STATE.signature_error = ""

    # l) zip-slip inside the archive itself is irrelevant: only manifest-listed files are read
    root = fresh()
    data, mh = _make_addon({"models/npu/m/ok.bin": b"ok"})
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("../../evil.txt", b"boom")
    _drop(root, "l.zip", buf.getvalue())
    res = addons.process_pending(root, log=lambda m: None, known={"t": {"manifest_sha256": mh}}, verifier=ok_sig)
    assert res[0].status == "installed" and not (root.parent / "evil.txt").exists()
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 4. Real Windows signature check (the same call SAC-protected startup uses)
# ------------------------------------------------------------------------------
def test_signature_verifier_on_real_files():
    print("\n[NPU 5/7] WinVerifyTrust on real files ...")
    if sys.platform != "win32":
        raise Skip("Windows only")
    from core.npu import addons

    kernel32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "kernel32.dll"
    assert addons.verify_signature(kernel32), "a Microsoft-signed system DLL must verify"
    tmp = Path(tempfile.mkdtemp()) / "unsigned.dll"
    tmp.write_bytes(b"MZ not signed")
    assert not addons.verify_signature(tmp), "an unsigned file must not verify"
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 5. ASR engine: CPU-first -> NPU swap and every fallback path
# ------------------------------------------------------------------------------
class _FakeStream:
    def __init__(self):
        self.result = type("R", (), {"text": ""})()

    def accept_waveform(self, sr, pcm):
        pass


class _FakeRecognizer:
    def __init__(self, text):
        self.text = text

    def create_stream(self):
        return _FakeStream()

    def decode_stream(self, stream):
        stream.result.text = self.text


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_engine_npu_fallbacks_and_swap():
    print("\n[NPU 6/7] ASR engine: fallback and CPU->NPU swap ...")
    from core.asr_engine import BusinessASREngine
    from core.npu import device

    ja = _HERE / "models" / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17" / "test_wavs" / "test_ja_2.wav"
    if not ja.is_file():
        raise Skip("test audio unavailable")
    from core.npu.base import resample_to_16k

    pcm, sr = sf.read(str(ja), dtype="float32")
    pcm = resample_to_16k(pcm if pcm.ndim == 1 else pcm[:, 0], sr)

    # (1) NPU requested but unusable -> keeps working on CPU, with a reason for the UI
    orig_probe = device.probe
    device.probe = lambda refresh=False: device.NpuInfo(False, reason="テスト: NPU なし")
    try:
        eng = BusinessASREngine(models_dir=MODELS, initial_languages=["ja"], device="npu")
        assert _wait(lambda: str(eng.get_device_summary().get("reazon", "")).startswith("cpu (テスト"))
        assert eng.transcribe_pcm(pcm[:16000 * 8], hint_lang="ja")
    finally:
        device.probe = orig_probe

    from contextlib import contextmanager

    @contextmanager
    def patched_build(fn):
        """Replace the NPU build step on the class BEFORE engines are created (no race with real builds)."""
        orig = BusinessASREngine._build_npu
        BusinessASREngine._build_npu = lambda self, key: fn(key)
        try:
            yield
        finally:
            BusinessASREngine._build_npu = orig

    # (2) the NPU build is swapped in once ready; until then the CPU engine keeps serving
    gate = threading.Event()
    with patched_build(lambda key: ((_FakeRecognizer("NPU-TEXT") if gate.wait(5) else None), "") if key == "reazon" else (None, "n/a")):
        eng = BusinessASREngine(models_dir=MODELS, initial_languages=["ja"], device="npu")
        assert eng.recognizer is not None and "準備中" in eng.get_device_summary()["reazon"]
        assert "NPU-TEXT" not in eng.transcribe_pcm(pcm[:16000 * 8], hint_lang="ja"), "must run on CPU until the NPU is ready"
        gate.set()
        assert _wait(lambda: eng.get_device_summary().get("reazon") == "npu"), eng.get_device_summary()
        assert eng.transcribe_pcm(pcm[:16000 * 8], hint_lang="ja") == "NPU-TEXT"

    # (3) a failed NPU compile leaves the CPU engine in place
    with patched_build(lambda key: (None, "RuntimeError: compile failed")):
        eng2 = BusinessASREngine(models_dir=MODELS, initial_languages=["ja"], device="npu")
        assert _wait(lambda: "compile failed" in eng2.get_device_summary().get("reazon", ""))
        assert eng2.recognizer is not None and eng2.transcribe_pcm(pcm[:16000 * 8], hint_lang="ja")

    # (4) an engine unloaded while its NPU build compiles is not resurrected
    release = threading.Event()
    with patched_build(lambda key: ((_FakeRecognizer("X") if release.wait(5) else None), "") if key == "parakeet" else (None, "n/a")):
        eng3 = BusinessASREngine(models_dir=MODELS, initial_languages=["ja", "en"], device="npu")
        if eng3.parakeet_recognizer is not None:
            eng3.set_active_languages(["ja"])  # unloads Parakeet while its NPU build is pending
            release.set()
            time.sleep(0.5)
            assert eng3.parakeet_recognizer is None, "unloaded engine must not be revived by a late NPU build"
        else:
            release.set()
            print("  (Parakeet CPU model not installed: unload-race check skipped)")

    # (5) NPU-first mode (npu_cpu_first=False) falls back synchronously
    eng4 = BusinessASREngine.__new__(BusinessASREngine)
    eng4.device, eng4.npu_cpu_first, eng4.device_status = "npu", False, {}
    eng4.models_dir = MODELS
    eng4.recognizer = None
    eng4._build_npu = lambda key: (None, "no npu")
    assert eng4._try_npu_sync("reazon", "recognizer") is False and eng4.device_status["reazon"].startswith("cpu")
    eng4._build_npu = lambda key: (_FakeRecognizer("S"), "")
    assert eng4._try_npu_sync("reazon", "recognizer") is True and eng4.recognizer.text == "S"
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 6. Config / CLI plumbing
# ------------------------------------------------------------------------------
def test_default_device_is_cpu():
    print("\n[NPU 7a/7] Default device is CPU ...")
    cfg = json.loads((_HERE / "config.default.json").read_text(encoding="utf-8"))
    assert cfg["asr"].get("device") == "cpu", "config.default.json must default to CPU"
    src = (_HERE / "main.py").read_text(encoding="utf-8")
    assert '"--device"' in src and "_read_device_config" in src
    print("  [PASS]")


# ------------------------------------------------------------------------------
# 7. Real NPU engines (skipped when the machine has no NPU / add-on / models)
# ------------------------------------------------------------------------------
def _hardware_ready():
    from core.npu import addons, device

    if addons.has_pending():  # same step the app performs on start-up: extract dropped-in ZIPs
        addons.run_startup(background=False)
    addons.activate_paths()
    info = device.probe()
    if not info.available:
        raise Skip(info.reason)
    return info


def _transcribe(rec, path):
    w, sr = sf.read(str(path), dtype="float32")
    w = w if w.ndim == 1 else w[:, 0]
    s = rec.create_stream()
    s.accept_waveform(sr, w)
    rec.decode_stream(s)
    return s.result.text


def test_real_npu_engines():
    print("\n[NPU 7/7] Real Intel NPU engines ...")
    info = _hardware_ready()
    from core.npu import parakeet, reazon, sensevoice

    print(f"  NPU: {info.name}")
    checks = []
    with network_isolation_guard():
        if reazon.model_files_present(MODELS):
            rec = reazon.ReazonNpuRecognizer(MODELS)
            t = _transcribe(rec, MODELS / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17/test_wavs/test_ja_2.wav")
            assert "日本語" in t, t
            checks.append(("ja", t))
        if sensevoice.model_files_present(MODELS):
            rec = sensevoice.SenseVoiceNpuRecognizer(MODELS)
            sv = MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs"
            t = _transcribe(rec, sv / "zh.wav")
            assert "开放时间" in t, t
            checks.append(("zh", t))
            t = _transcribe(rec, sv / "ko.wav")
            assert "생각" in t, t
            checks.append(("ko", t))
        if parakeet.model_files_present(MODELS):
            rec = parakeet.ParakeetNpuRecognizer(MODELS)
            pk = MODELS / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/test_wavs"
            for lang, needle in (("en", "country"), ("fr", "pays"), ("de", "Wurst"), ("es", "país")):
                t = _transcribe(rec, pk / f"{lang}.wav")
                assert needle in t, (lang, t)
                checks.append((lang, t))
    if not checks:
        raise Skip("no NPU model set installed")
    for lang, t in checks:
        print(f"  {lang}: {t[:70]}")
    print("  [PASS]")


TESTS = [
    test_cpu_mode_does_not_touch_openvino,
    test_features_match_kaldi,
    test_text_and_window_helpers,
    test_addon_installer,
    test_signature_verifier_on_real_files,
    test_engine_npu_fallbacks_and_swap,
    test_default_device_is_cpu,
    test_real_npu_engines,
]


def main() -> int:
    print("=======================================================")
    print("  Hayamimi Polyglot - NPU Mode Test Suite")
    print("=======================================================")
    failed = skipped = 0
    for t in TESTS:
        try:
            t()
        except Skip as s:
            skipped += 1
            print(f"  [SKIP] {t.__name__}: {s}")
        except Exception as exc:
            failed += 1
            import traceback

            traceback.print_exc()
            print(f"  [FAIL] {t.__name__}: {exc}")
    print("\n=======================================================")
    print(f"  passed={len(TESTS) - failed - skipped} skipped={skipped} failed={failed}")
    print("=======================================================")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
