#!/usr/bin/env python3
"""
Hayamimi Polyglot - macOS Apple Silicon Standalone Portable Builder & Verifier
Usable both locally and inside GitHub Actions (macos-14).
"""

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
BUILD_DIR = ROOT / "build_mac_portable"
PKG_DIR = BUILD_DIR / "hayamimi-polyglot"
OUTPUT_ZIP = ROOT / "hayamimi-polyglot-v1.0.0-macos-portable.zip"

def download_file(url: str, dst: Path):
    print(f"⬇️ Downloading: {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-CI-Builder"})
    with urllib.request.urlopen(req) as resp, open(dst, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"  ✓ Saved to {dst.name} ({dst.stat().st_size / (1024*1024):.2f} MB)")

def main():
    print("=" * 60)
    print("🚀 Building macOS Apple Silicon Standalone Portable Package")
    print("=" * 60)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    PKG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Download & Extract Standalone uv for macOS arm64
    uv_tar = BUILD_DIR / "uv-aarch64-apple-darwin.tar.gz"
    uv_url = "https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-apple-darwin.tar.gz"
    download_file(uv_url, uv_tar)

    print("📦 Extracting standalone uv binary...")
    with tarfile.open(uv_tar, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith("/uv") or member.name == "uv":
                f = tar.extractfile(member)
                dst_uv = PKG_DIR / "uv"
                with open(dst_uv, "wb") as out:
                    out.write(f.read())
                print("  ✓ Bundled ./uv")
                break

    # 2. Download & Extract Standalone CPython 3.12 for macOS arm64
    py_tar = BUILD_DIR / "cpython-3.12-apple-darwin.tar.gz"
    py_url = "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16+20261026-aarch64-apple-darwin-install_only.tar.gz"
    download_file(py_url, py_tar)

    print("📦 Extracting standalone CPython runtime...")
    dst_python = PKG_DIR / "python"
    with tarfile.open(py_tar, "r:gz") as tar:
        tar.extractall(BUILD_DIR)
        extracted_py = BUILD_DIR / "python"
        if extracted_py != dst_python:
            if dst_python.exists():
                shutil.rmtree(dst_python)
            shutil.move(extracted_py, dst_python)

    # Prune dev-only artifacts (~100MB saved)
    test_dir = dst_python / "lib" / "python3.12" / "test"
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
    inc_dir = dst_python / "include"
    if inc_dir.exists():
        shutil.rmtree(inc_dir, ignore_errors=True)
    static_lib = dst_python / "lib" / "libpython3.12.a"
    if static_lib.exists():
        static_lib.unlink()
    print("  ✓ Bundled ./python runtime (pruned dev artifacts)")

    # 3. Collect macOS arm64 offline wheels
    dst_wheels = PKG_DIR / "wheels"
    dst_wheels.mkdir(parents=True, exist_ok=True)
    print("📦 Collecting macOS arm64 offline wheels via pip...")

    # Build pure wheel for sudachidict-full first (sdist -> py3-none-any wheel)
    print("  -> Building wheel for sudachidict-full>=20261015...")
    subprocess.check_call([
        "pip", "wheel", "--no-deps", "-w", str(dst_wheels), "sudachidict-full>=20261015"
    ])

    pkgs = [
        "numpy>=2.5.4",
        "sounddevice>=0.5.6",
        "soundfile>=0.14.0",
        "onnxruntime>=1.19.0,<1.20.0",
        "sherpa-onnx>=2.0.1",
        "ctranslate2>=4.8.4",
        "sentencepiece>=0.2.2",
        "sudachipy>=0.7.0",
        "PySide6-Essentials>=6.9.0,<6.10.0",
        "fastapi>=0.162.0",
        "uvicorn>=0.54.0",
    ]
    for pkg in pkgs:
        cmd = [
            "pip", "download",
            "--platform", "macosx_12_0_arm64",
            "--only-binary=:all:",
            "--python-version", "3.12",
            "--implementation", "cp",
            "--abi", "cp312",
            "-d", str(dst_wheels),
            pkg
        ]
        res = subprocess.call(cmd)
        if res != 0:
            cmd_fallback = [
                "pip", "wheel",
                "--platform", "macosx_12_0_arm64",
                "--python-version", "3.12",
                "-w", str(dst_wheels),
                pkg
            ]
            subprocess.check_call(cmd_fallback)
    print(f"  ✓ Bundled {len(list(dst_wheels.iterdir()))} offline wheels")

    # 4. Copy Application Source & Assets
    items = [
        "core", "ui", "dicts", "main.py", "start.sh", "Hayamimi Polyglot.command",
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

    # 6. Compress into ZIP with Unix 0o755 execution permissions
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    print(f"\n📦 Compressing into {OUTPUT_ZIP.name} with Unix executable attributes...")
    exec_filenames = {"start.sh", "Hayamimi Polyglot.command", "uv", "python", "python3", "python3.12"}

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        file_count = 0
        for root, dirs, files in os.walk(BUILD_DIR):
            for file in files:
                full_path = Path(root) / file
                arc_name = full_path.relative_to(BUILD_DIR)
                zinfo = zipfile.ZipInfo.from_file(full_path, str(arc_name))
                is_executable = (
                    file in exec_filenames
                    or "/bin/" in str(arc_name).replace("\\", "/")
                    or file.endswith(".sh")
                    or file.endswith(".command")
                )
                if is_executable:
                    zinfo.external_attr = 0o100755 << 16
                else:
                    zinfo.external_attr = 0o100644 << 16
                with open(full_path, "rb") as f_in:
                    zipf.writestr(zinfo, f_in.read())
                file_count += 1
                if file_count % 500 == 0:
                    print(f"  ... archived {file_count} files")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n🎉 Package generated: {OUTPUT_ZIP} ({size_mb:.2f} MB)")

    # 7. SMOKE TEST ON MACOS RUNNER
    if sys.platform == "darwin":
        print("\n🧪 Running Headless Smoke Test on macOS...")
        test_extract_dir = ROOT / "build_test_mac_extract"
        if test_extract_dir.exists():
            shutil.rmtree(test_extract_dir)
        test_extract_dir.mkdir(parents=True, exist_ok=True)

        subprocess.check_call(["unzip", "-q", str(OUTPUT_ZIP), "-d", str(test_extract_dir)])
        pkg_root = test_extract_dir / "hayamimi-polyglot"

        # Execute start.sh in headless mode to initialize .venv from bundled wheels
        print("  -> Initializing .venv from bundled wheels...")
        test_env = os.environ.copy()
        test_env["QT_QPA_PLATFORM"] = "offscreen"

        subprocess.check_call(["chmod", "+x", str(pkg_root / "start.sh"), str(pkg_root / "uv")])
        subprocess.check_call(["./start.sh", "--dry-run"], cwd=str(pkg_root), env=test_env)
        
        # Test imports from created .venv
        test_py = pkg_root / ".venv" / "bin" / "python"
        smoke_cmd = [
            str(test_py), "-c",
            (
                "import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
                "from PySide6 import QtCore, QtWidgets; "
                "import main; "
                "print('  [OK] [macOS TEST] PySide6 and main.py loaded perfectly on Apple Silicon!')"
            )
        ]
        subprocess.check_call(smoke_cmd, env=test_env, cwd=str(pkg_root))
        shutil.rmtree(test_extract_dir)
        print("🎉 macOS SMOKE TESTS PASSED!")

    shutil.rmtree(BUILD_DIR)
    print("✓ All build artifacts cleaned. Build & Test Complete!")

if __name__ == "__main__":
    main()

