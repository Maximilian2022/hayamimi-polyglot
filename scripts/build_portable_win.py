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
    Remove unused, architecture-mismatched, or test-only unsigned binaries.
    Helps prevent false-positive Smart App Control (SAC) blocks and reduces package size.
    """
    print("🧹 Cleaning unnecessary unsigned binaries and test modules...")
    removed_count = 0

    # 1. Remove pip executable stubs in python/ (unsigned CLI launcher stubs)
    for stub_name in ["t32.exe", "t64.exe", "t64-arm.exe", "w32.exe", "w64.exe", "w64-arm.exe"]:
        stub_path = dst_python / stub_name
        if stub_path.exists():
            stub_path.unlink()
            removed_count += 1

    site_packages = dst_python / "Lib" / "site-packages"
    if not site_packages.exists():
        return

    # 2. In _sounddevice_data: keep only 64-bit non-ASIO DLL (libportaudio64bit.dll)
    sd_binaries = site_packages / "_sounddevice_data" / "portaudio-binaries"
    if sd_binaries.exists():
        for dll_file in sd_binaries.glob("*.dll"):
            if dll_file.name != "libportaudio64bit.dll":
                dll_file.unlink()
                removed_count += 1
                print(f"     - Removed unused audio DLL: {dll_file.name}")

    # 3. In numpy: remove test-only C extensions (.pyd) and test suites
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
    # SenseVoice INT8 only
    sv_src = src_models / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    if sv_src.exists():
        sv_dst = dst_models / sv_src.name
        sv_dst.mkdir(parents=True, exist_ok=True)
        for f in ["tokens.txt", "model.int8.onnx", "LICENSE", "README.md"]:
            if (sv_src / f).exists():
                shutil.copy2(sv_src / f, sv_dst / f)
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
