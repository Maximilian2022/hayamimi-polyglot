#!/usr/bin/env python3
"""
Hayamimi Polyglot - Windows Standalone Portable Builder & Verifier
Usable both locally and inside GitHub Actions (windows-latest).
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build_win_portable"
PKG_DIR = BUILD_DIR / "hayamimi-polyglot"
OUTPUT_ZIP = ROOT / "hayamimi-polyglot-v1.0.0-windows-portable.zip"

def ensure_standalone_python() -> Path:
    """Ensure standalone CPython 3.12 is available via uv."""
    print("📦 Locating standalone CPython 3.12 via uv...")
    # Trigger uv python install 3.12 to ensure it is in uv python cache
    subprocess.call(["uv", "python", "install", "3.12"])
    
    appdata = os.environ.get("APPDATA")
    userprofile = os.environ.get("USERPROFILE")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "uv" / "python")
    if userprofile:
        candidates.append(Path(userprofile) / "AppData" / "Roaming" / "uv" / "python")

    for uv_dir in candidates:
        if uv_dir.exists():
            for entry in uv_dir.iterdir():
                if entry.name.startswith("cpython-3.12") and (entry / "python.exe").exists():
                    print(f"  [OK] Found standalone CPython: {entry}")
                    return entry
    raise RuntimeError("Standalone CPython 3.12 could not be found or installed!")

def copy_vc_redist_dlls(dst_dir: Path):
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
        "vcruntime140_1.dll"
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

def main():
    print("=" * 60)
    print("🚀 Building Windows Standalone Portable Package")
    print("=" * 60)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    PKG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Standalone Python Runtime
    src_python = ensure_standalone_python()
    dst_python = PKG_DIR / "python"
    print(f"📦 Copying Standalone Python to {dst_python}...")
    shutil.copytree(src_python, dst_python)

    ext_managed = dst_python / "Lib" / "EXTERNALLY-MANAGED"
    if ext_managed.exists():
        ext_managed.unlink()

    # 2. Bundle VC++ Redistributable DLLs
    copy_vc_redist_dlls(dst_python)

    # 3. Cleanly install requirements
    print("📦 Installing requirements into portable Python environment...")
    py_exe = dst_python / "python.exe"
    req_file = ROOT / "requirements.txt"

    env = os.environ.copy()
    env["UV_SYSTEM_CERTS"] = "true"
    env["PIP_USE_FEATURE"] = "truststore"

    subprocess.check_call([
        "uv", "pip", "install",
        "--python", str(py_exe),
        "--break-system-packages",
        "-r", str(req_file)
    ], env=env)

    # Prune dev-only artifacts
    tcl_dir = dst_python / "tcl"
    if tcl_dir.exists():
        shutil.rmtree(tcl_dir, ignore_errors=True)
    inc_dir = dst_python / "include"
    if inc_dir.exists():
        shutil.rmtree(inc_dir, ignore_errors=True)

    # 4. Copy Application Source & Assets
    items = [
        "core", "ui", "dicts", "main.py", "start.bat",
        "config.default.json", "config.json", "requirements.txt",
        "Third_Party_Notices.md", "LICENSE", "README.md", "version.txt"
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

    # 5. Copy Models (INT8 Only)
    src_models = ROOT / "models"
    dst_models = PKG_DIR / "models"
    dst_models.mkdir(parents=True, exist_ok=True)
    print(f"  -> Packaging INT8 models from {src_models}...")

    # FuguMT & M2M-100
    if (src_models / "mojicast-fugumt-ja-en-ct2").exists():
        shutil.copytree(src_models / "mojicast-fugumt-ja-en-ct2", dst_models / "mojicast-fugumt-ja-en-ct2")
    if (src_models / "mojicast-m2m100-ct2").exists():
        shutil.copytree(src_models / "mojicast-m2m100-ct2", dst_models / "mojicast-m2m100-ct2")
    # Parakeet v3 INT8
    if (src_models / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8").exists():
        shutil.copytree(src_models / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", dst_models / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
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
        for f in ["tokens.txt", "README.md"]:
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
        for root, dirs, files in os.walk(BUILD_DIR):
            for file in files:
                full_path = Path(root) / file
                arc_name = full_path.relative_to(BUILD_DIR)
                zipf.write(full_path, arc_name)
                file_count += 1
                if file_count % 500 == 0:
                    print(f"  ... archived {file_count} files")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n🎉 Package generated: {OUTPUT_ZIP} ({size_mb:.2f} MB)")

    # 7. RIGOROUS SMOKE TEST (Extract to temporary isolated folder & verify execution)
    print("\n🧪 Running Headless Smoke Test on newly generated Portable Package...")
    test_extract_dir = ROOT / "build_test_win_extract"
    if test_extract_dir.exists():
        shutil.rmtree(test_extract_dir)
    test_extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(OUTPUT_ZIP, "r") as zipf:
        zipf.extractall(test_extract_dir)

    isolated_py = test_extract_dir / "hayamimi-polyglot" / "python" / "python.exe"
    smoke_test_cmd = [
        str(isolated_py), "-c",
        (
            "import os, sys; "
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
            "print('  [OK] SessionWorker initialized without error!'); "
            "print('[SUCCESS] ALL PORTABLE SMOKE TESTS PASSED!')"
        )
    ]
    test_env = os.environ.copy()
    test_env["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.check_call(smoke_test_cmd, env=test_env, cwd=str(test_extract_dir / "hayamimi-polyglot"))

    # Clean up test directories
    shutil.rmtree(test_extract_dir)
    shutil.rmtree(BUILD_DIR)
    print("[OK] All build artifacts cleaned. Build & Test Complete!")

if __name__ == "__main__":
    main()

