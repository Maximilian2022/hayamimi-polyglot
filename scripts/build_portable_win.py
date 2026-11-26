#!/usr/bin/env python3
"""
Hayamimi Polyglot - Windows Standalone Portable Builder & Verifier (Python 3.14)
Usable both locally and inside GitHub Actions (windows-latest).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build_win_portable"
PKG_DIR = BUILD_DIR / "hayamimi-polyglot"
VERSION = (ROOT / "version.txt").read_text(encoding="utf-8").strip() if (ROOT / "version.txt").is_file() else "1.0.1"
OUTPUT_ZIP = ROOT / f"hayamimi-polyglot-v{VERSION}-windows-portable.zip"

# Official Python Software Foundation NuGet package (Digitally signed by Python Software Foundation)
PYTHON_NUGET_URL = "https://api.nuget.org/v3-flatcontainer/python/3.14.10/python.3.14.10.nupkg"


def download_and_extract_python(dst_python: Path) -> None:
    """Download and extract official PSF-signed Python 3.14.10 Windows x86_64 runtime."""
    py_nupkg = BUILD_DIR / "python-3.14.10.zip"
    print(f"⬇️ Downloading official PSF-signed Python 3.14.10: {PYTHON_NUGET_URL} ...")
    req = urllib.request.Request(PYTHON_NUGET_URL, headers={"User-Agent": "Hayamimi-CI-Builder"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(py_nupkg, "wb") as out:
        shutil.copyfileobj(resp, out)

    print("📦 Extracting official Python 3.14 runtime...")
    extract_temp = BUILD_DIR / "_py_extract"
    if extract_temp.exists():
        shutil.rmtree(extract_temp)
    extract_temp.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(py_nupkg, "r") as zipf:
        zipf.extractall(extract_temp)

    tools_dir = extract_temp / "tools"
    if not tools_dir.exists():
        raise RuntimeError("Expected 'tools' folder inside Python NuGet package.")

    if dst_python.exists():
        shutil.rmtree(dst_python)
    shutil.move(str(tools_dir), str(dst_python))

    shutil.rmtree(extract_temp, ignore_errors=True)
    py_nupkg.unlink(missing_ok=True)


def clean_unnecessary_binaries(dst_python: Path) -> None:
    """
    Remove unused CLI launchers, architecture-mismatched DLLs, and test-only unsigned binaries.
    Prevents false-positive Smart App Control (SAC) blocks and reduces package size.
    """
    print("🧹 Cleaning unnecessary unsigned binaries, CLI wrappers, and test modules...")
    removed_count = 0

    # 1. Remove pip executable stubs in python/ (unsigned CLI launcher stubs)
    for stub_name in ["t32.exe", "t64.exe", "t64-arm.exe", "w32.exe", "w64.exe", "w64-arm.exe"]:
        stub_path = dst_python / stub_name
        if stub_path.exists():
            stub_path.unlink()
            removed_count += 1

    # 2. Remove python/Scripts/ entirely (contains ~43 unsigned pip/uv CLI .exe wrappers & duplicate DLLs
    #    like pyside6-designer.exe, ct2-*-converter.exe, sherpa-onnx-cli.exe that the app never uses)
    scripts_dir = dst_python / "Scripts"
    if scripts_dir.exists():
        removed_scripts = sum(1 for _ in scripts_dir.rglob("*") if _.is_file())
        shutil.rmtree(scripts_dir, ignore_errors=True)
        removed_count += removed_scripts
        print(f"     - Removed unused python/Scripts/ directory ({removed_scripts} CLI wrapper files)")

    site_packages = dst_python / "Lib" / "site-packages"
    if not site_packages.exists():
        return

    # 3. Remove pip/wheel/setuptools CLI entrypoints inside site-packages if any .exe stubs exist
    for pip_exe in site_packages.rglob("*.exe"):
        try:
            pip_exe.unlink()
            removed_count += 1
            print(f"     - Removed embedded CLI stub: {pip_exe.relative_to(site_packages)}")
        except Exception:
            pass

    # 4. In _sounddevice_data: keep only 64-bit non-ASIO DLL (libportaudio64bit.dll)
    sd_binaries = site_packages / "_sounddevice_data" / "portaudio-binaries"
    if sd_binaries.exists():
        for dll_file in sd_binaries.glob("*.dll"):
            if dll_file.name != "libportaudio64bit.dll":
                dll_file.unlink()
                removed_count += 1
                print(f"     - Removed unused audio DLL: {dll_file.name}")

    # 5. In numpy: remove test-only C extensions (.pyd) and test suites
    for test_pyd in site_packages.glob("numpy/**/_*tests*.pyd"):
        try:
            test_pyd.unlink()
            removed_count += 1
            print(f"     - Removed numpy test binary: {test_pyd.name}")
        except Exception:
            pass

    for test_dir in site_packages.glob("numpy/**/tests"):
        if test_dir.is_dir():
            shutil.rmtree(test_dir, ignore_errors=True)

    print(f"  [OK] Cleaned {removed_count} unnecessary binary/test items.")


# Packages whose upstream PyPI wheels contain unsigned .dll/.pyd files that have been
# verified to pass Smart App Control (ISG reputation) for the pinned versions in requirements.txt.
_ALLOWED_UNSIGNED_TOP_PACKAGES = {
    "_sounddevice_data",
    "_soundfile_data",
    "ctranslate2",
    "google",
    "numpy",
    "numpy.libs",
    "psutil",
    "pydantic_core",
    "sentencepiece",
    "sherpa_onnx",
    "sudachipy",
    "yaml",
}


def _win_verify_authenticode(path: Path) -> bool:
    """Verify Authenticode signature in-process via WinVerifyTrust (cache-only, zero network)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE),
            ("pgKnownSubject", ctypes.c_void_p),
        ]

    class WINTRUST_DATA(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD),
            ("pPolicyCallbackData", ctypes.c_void_p),
            ("pSIPClientData", ctypes.c_void_p),
            ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD),
            ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
            ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE),
            ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD),
            ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", ctypes.c_void_p),
        ]

    action = GUID(
        0x00AAC56B,
        0xCD44,
        0x11D0,
        (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
    )
    file_info = WINTRUST_FILE_INFO(ctypes.sizeof(WINTRUST_FILE_INFO), str(path), None, None)
    data = WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
    data.dwUIChoice = 2  # WTD_UI_NONE
    data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    data.dwProvFlags = 0x00001000 | 0x00000010  # WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_NONE

    wintrust = ctypes.WinDLL("wintrust")
    wintrust.WinVerifyTrust.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_void_p]
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    try:
        rc = wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
    finally:
        data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
    return rc == 0


def verify_portable_signatures(dst_python: Path) -> None:
    """
    Enforce Smart App Control (SAC) binary hygiene before packaging:
      1. ZERO unsigned .exe files anywhere in python/.
      2. Core runtime (python/*.exe, python/*.dll, python/DLLs/*, PySide6/*, shiboken6/*, onnxruntime/*)
         must carry a VALID Authenticode signature.
      3. Any unsigned .dll/.pyd in site-packages must belong strictly to the known SAC-verified allowlist.
    """
    if os.name != "nt":
        return

    bins = sorted(
        p for p in dst_python.rglob("*")
        if p.is_file() and p.suffix.lower() in (".exe", ".dll", ".pyd", ".sys")
    )
    if not bins:
        raise RuntimeError("No native binaries found in portable Python directory.")

    print(f"🛡️ Verifying Authenticode signatures across {len(bins)} native binaries via WinVerifyTrust...")
    site_packages = (dst_python / "Lib" / "site-packages").resolve()
    must_be_signed_pkgs = {"PySide6", "shiboken6", "onnxruntime"}
    signed_count = 0
    known_unsigned_count = 0
    violations: list[str] = []

    for p in bins:
        p_res = p.resolve()
        rel_py = p_res.relative_to(dst_python.resolve())

        if _win_verify_authenticode(p_res):
            signed_count += 1
            continue

        # Rule 1: Never ship an unsigned .exe
        if p_res.suffix.lower() == ".exe":
            violations.append(f"Unsigned executable forbidden: {rel_py}")
            continue

        # Rule 2: Everything outside site-packages (python root & DLLs/) must be signed
        try:
            rel_sp = p_res.relative_to(site_packages)
        except ValueError:
            violations.append(f"Core Python/VC++ binary must be signed: {rel_py}")
            continue

        top_pkg = rel_sp.parts[0]
        # Rule 3: Signed vendor packages (Qt, Microsoft ONNX Runtime) must never lose their signatures
        if top_pkg in must_be_signed_pkgs:
            violations.append(f"Expected vendor-signed binary in {top_pkg}: {rel_sp}")
            continue

        # Rule 4: Only allow pinned, SAC-verified packages to have unsigned .pyd/.dll
        is_cffi_root = len(rel_sp.parts) == 1 and rel_sp.name.startswith("_cffi_backend")
        if top_pkg in _ALLOWED_UNSIGNED_TOP_PACKAGES or is_cffi_root:
            known_unsigned_count += 1
        else:
            violations.append(f"Unapproved unsigned binary introduced: {rel_sp}")

    if violations:
        raise RuntimeError(
            "Smart App Control signature check failed:\n  - " + "\n  - ".join(violations[:25])
        )
    print(
        f"  [OK] Signature audit passed: {signed_count} validly signed binaries, "
        f"0 unsigned .exe, {known_unsigned_count} pinned SAC-verified extensions."
    )


def copy_vc_redist_dlls(dst_dir: Path) -> None:
    """Bundle Visual C++ Redistributable DLLs into python/ directory."""
    system32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
    vc_dll_patterns = [
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll",
        "vcomp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ]
    print("  -> Bundling VC++ Redistributable DLLs into python/ ...")
    copied = 0
    for dll_name in vc_dll_patterns:
        src = system32 / dll_name
        if src.exists():
            shutil.copy2(src, dst_dir / dll_name)
            copied += 1
            print(f"     + {dll_name}")
    print(f"  [OK] Bundled {copied} VC++ DLLs.")


def main() -> None:
    print("=" * 60)
    print("🚀 Building Windows Standalone Portable Package (Python 3.14)")
    print("=" * 60)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    PKG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Standalone Python 3.14 Runtime (stripped)
    dst_python = PKG_DIR / "python"
    download_and_extract_python(dst_python)

    ext_managed = dst_python / "Lib" / "EXTERNALLY-MANAGED"
    if ext_managed.exists():
        ext_managed.unlink()

    # 2. Bundle VC++ Redistributable DLLs
    copy_vc_redist_dlls(dst_python)

    # 3. Cleanly install requirements
    print("📦 Installing requirements into portable Python 3.14 environment...")
    py_exe = dst_python / "python.exe"
    req_file = ROOT / "requirements.txt"

    env = os.environ.copy()
    env["UV_SYSTEM_CERTS"] = "true"
    env["PIP_USE_FEATURE"] = "truststore"

    subprocess.check_call(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(py_exe),
            "--break-system-packages",
            "-r",
            str(req_file),
        ],
        env=env,
    )

    # Prune non-runtime directories to keep ZIP well under 2GB
    for unused_dir in [
        dst_python / "tcl",
        dst_python / "include",
        dst_python / "libs",
        dst_python / "Lib" / "test",
        dst_python / "Lib" / "tkinter",
        dst_python / "Lib" / "idlelib",
        dst_python / "Lib" / "turtledemo",
    ]:
        if unused_dir.exists():
            shutil.rmtree(unused_dir, ignore_errors=True)

    # Remove unused architecture binaries and test .pyd files (Smart App Control false-positive prevention)
    clean_unnecessary_binaries(dst_python)

    # Audit Authenticode signatures and ensure zero unapproved unsigned binaries
    verify_portable_signatures(dst_python)

    # Audit Microsoft Defender ISG cloud reputation for unsigned runtime extensions
    from check_sac_trust import audit_site_packages

    if audit_site_packages([dst_python / "Lib" / "site-packages"], allow_runner_no_cloud=True) != 0:
        raise RuntimeError("Smart App Control ISG reputation check failed during portable build.")

    # 4. Copy Application Source & Assets (exclude local config.json)
    items = [
        "core",
        "ui",
        "dicts",
        "main.py",
        "start.bat",
        "config.default.json",
        "requirements.txt",
        ".python-version",
        "Third_Party_Notices.md",
        "LICENSE",
        "README.md",
        "version.txt",
    ]
    for item in items:
        src = ROOT / item
        dst = PKG_DIR / item
        if not src.exists():
            continue
        print(f"  -> Copying {item}...")
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # addons/ is where users drop the optional NPU add-on ZIPs (extracted automatically on next start)
    addons_dir = PKG_DIR / "addons"
    addons_dir.mkdir(exist_ok=True)
    (addons_dir / "README.txt").write_text(
        "NPU アドオン置き場\r\n"
        "==================\r\n"
        "Intel NPU (Core Ultra) 搭載 PC で NPU モードを使う場合は、\r\n"
        "配布ページからダウンロードした次の ZIP を、解凍せずにこのフォルダへ入れてください。\r\n"
        "  hayamimi-polyglot-npu-addon-core-*.zip   日本語・中国語・韓国語\r\n"
        "  hayamimi-polyglot-npu-addon-euro-*.zip   英語・フランス語・ドイツ語・スペイン語\r\n"
        "次回の起動時に自動で展開されます（展開後に ZIP は削除されます）。\r\n"
        "NPU を使わない場合は何もする必要はありません（従来どおり CPU で動作します）。\r\n",
        encoding="utf-8",
    )

    # Remove any temporary session_hotwords.txt if present
    (PKG_DIR / "dicts" / "session_hotwords.txt").unlink(missing_ok=True)

    # 5. Copy Models (INT8 Only, excluding test_wavs to save space)
    src_models = ROOT / "models"
    dst_models = PKG_DIR / "models"
    dst_models.mkdir(parents=True, exist_ok=True)
    print(f"  -> Packaging INT8 models from {src_models}...")

    # FuguMT & M2M-100
    if (src_models / "mojicast-fugumt-ja-en-ct2").exists():
        shutil.copytree(
            src_models / "mojicast-fugumt-ja-en-ct2",
            dst_models / "mojicast-fugumt-ja-en-ct2",
        )
    if (src_models / "mojicast-m2m100-ct2").exists():
        shutil.copytree(
            src_models / "mojicast-m2m100-ct2",
            dst_models / "mojicast-m2m100-ct2",
        )
    # Parakeet v3 INT8 (only runtime files, skip test_wavs)
    pk_src = src_models / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    if pk_src.exists():
        pk_dst = dst_models / pk_src.name
        pk_dst.mkdir(parents=True, exist_ok=True)
        for f in pk_src.iterdir():
            if f.is_file() and (f.suffix in (".onnx", ".txt", ".md") or f.name == "LICENSE"):
                shutil.copy2(f, pk_dst / f.name)
    # Moonshine Streaming Tiny Zh INT8
    ms_src = src_models / "moonshine-streaming-tiny-zh-onnx"
    if ms_src.exists():
        ms_dst = dst_models / ms_src.name
        ms_dst.mkdir(parents=True, exist_ok=True)
        for f in ms_src.iterdir():
            if f.is_file() and (
                f.name in ("LICENSE", "README.md", "frontend.onnx")
                or f.suffix == ".json"
                or "_int8.onnx" in f.name
            ):
                shutil.copy2(f, ms_dst / f.name)
    # Nemotron 3.5 ASR Streaming 0.6B INT8 (skip test_wavs)
    nem_src = src_models / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8"
    if nem_src.exists():
        nem_dst = dst_models / nem_src.name
        nem_dst.mkdir(parents=True, exist_ok=True)
        for f in ["tokens.txt", "README.md", "LICENSE"]:
            if (nem_src / f).exists():
                shutil.copy2(nem_src / f, nem_dst / f)
        for f in nem_src.glob("*.int8.onnx"):
            shutil.copy2(f, nem_dst / f.name)
    # ReazonSpeech INT8 only
    rz_src = src_models / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
    if rz_src.exists():
        rz_dst = dst_models / rz_src.name
        rz_dst.mkdir(parents=True, exist_ok=True)
        for f in ["tokens.txt", "README.md", "LICENSE"]:
            if (rz_src / f).exists():
                shutil.copy2(rz_src / f, rz_dst / f)
        for f in rz_src.glob("*.int8.onnx"):
            shutil.copy2(f, rz_dst / f.name)
    # Silero VAD
    if (src_models / "silero_vad.onnx").exists():
        shutil.copy2(src_models / "silero_vad.onnx", dst_models / "silero_vad.onnx")

    # Clean pycache
    for p in BUILD_DIR.rglob("__pycache__"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    for p in BUILD_DIR.rglob("*.pyc"):
        try:
            p.unlink()
        except Exception:
            pass

    # 6. Compress into ZIP
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    print(f"\n📦 Compressing into {OUTPUT_ZIP.name}...")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        file_count = 0
        for root, _dirs, files in os.walk(BUILD_DIR):
            for file in files:
                full_path = Path(root) / file
                arc_name = full_path.relative_to(BUILD_DIR)
                zipf.write(full_path, arc_name)
                file_count += 1
                if file_count % 500 == 0:
                    print(f"  ... archived {file_count} files")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n🎉 Package generated: {OUTPUT_ZIP} ({size_mb:.2f} MB)")

    # 7. Headless Smoke Test
    print("\n🧪 Running Headless Smoke Test on newly generated Portable Package...")
    test_extract_dir = ROOT / "build_test_win_extract"
    if test_extract_dir.exists():
        shutil.rmtree(test_extract_dir)
    test_extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(OUTPUT_ZIP, "r") as zipf:
        zipf.extractall(test_extract_dir)

    isolated_py = test_extract_dir / "hayamimi-polyglot" / "python" / "python.exe"
    smoke_test_cmd = [
        str(isolated_py),
        "-c",
        (
            "import os, sys; "
            "print('  [OK] Python version:', sys.version); "
            "assert sys.version_info[:2] == (3, 14), f'Expected Python 3.14, got {sys.version}'; "
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
            "from PySide6 import QtCore, QtWidgets, QtGui; "
            "print('  [OK] QtCore and QtWidgets loaded!'); "
            "import main; "
            "print('  [OK] main.py imported successfully!'); "
            "from main import SessionWorker, find_models_dir; "
            "from core.vad import SileroVAD; "
            "from core.asr_engine import BusinessASREngine; "
            "from core.translator import LocalTranslator; "
            "m_dir = find_models_dir(); "
            "v_s = SileroVAD(models_dir=m_dir); "
            "v_r = SileroVAD(models_dir=m_dir); "
            "asr = BusinessASREngine(models_dir=m_dir); "
            "tr = LocalTranslator(models_dir=m_dir); "
            "w = SessionWorker(asr_engine=asr, vad_self=v_s, vad_remote=v_r, translator=tr); "
            "w.shutdown(); tr.shutdown(); "
            "print('  [OK] SessionWorker initialized without error!'); "
            "print('[SUCCESS] ALL PORTABLE SMOKE TESTS PASSED!')"
        ),
    ]
    test_env = os.environ.copy()
    test_env["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.check_call(smoke_test_cmd, env=test_env, cwd=str(test_extract_dir / "hayamimi-polyglot"))

    shutil.rmtree(test_extract_dir)
    shutil.rmtree(BUILD_DIR)
    print("[OK] All build artifacts cleaned. Build & Test Complete!")


if __name__ == "__main__":
    main()
