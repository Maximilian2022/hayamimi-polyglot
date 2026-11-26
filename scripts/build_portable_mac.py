#!/usr/bin/env python3
"""
Hayamimi Polyglot - macOS Apple Silicon Standalone Portable Builder & Verifier (Python 3.14)
Usable both locally and inside GitHub Actions (macos-latest / macos-14+).
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
BUILD_DIR = ROOT / "build_mac_portable"
PKG_DIR = BUILD_DIR / "hayamimi-polyglot"
VERSION = (ROOT / "version.txt").read_text(encoding="utf-8").strip() if (ROOT / "version.txt").is_file() else "1.0.1"
OUTPUT_ZIP = ROOT / f"hayamimi-polyglot-v{VERSION}-macos-portable.zip"

CPYTHON_MAC_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/"
    "cpython-3.14.10+20261026-aarch64-apple-darwin-install_only_stripped.tar.gz"
)


def download_file(url: str, dst: Path) -> None:
    print(f"⬇️ Downloading: {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-CI-Builder"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dst, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"  ✓ Saved to {dst.name} ({dst.stat().st_size / (1024*1024):.2f} MB)")


def main() -> None:
    print("=" * 60)
    print("🚀 Building macOS Apple Silicon Standalone Portable Package (Python 3.14)")
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
                if f is not None:
                    dst_uv = PKG_DIR / "uv"
                    with open(dst_uv, "wb") as out:
                        out.write(f.read())
                    print("  ✓ Bundled ./uv")
                    break
    uv_tar.unlink(missing_ok=True)

    # 2. Download & Extract Standalone CPython 3.14.10 (stripped) for macOS arm64
    py_tar = BUILD_DIR / "cpython-3.14-apple-darwin.tar.gz"
    download_file(CPYTHON_MAC_URL, py_tar)

    print("📦 Extracting standalone CPython 3.14 runtime...")
    dst_python = PKG_DIR / "python"
    with tarfile.open(py_tar, "r:gz") as tar:
        try:
            tar.extractall(BUILD_DIR, filter="data")
        except TypeError:
            tar.extractall(BUILD_DIR)
        extracted_py = BUILD_DIR / "python"
        if extracted_py != dst_python:
            if dst_python.exists():
                shutil.rmtree(dst_python)
            shutil.move(str(extracted_py), str(dst_python))
    py_tar.unlink(missing_ok=True)

    # Prune dev-only artifacts
    for unused in [
        dst_python / "lib" / "python3.14" / "test",
        dst_python / "lib" / "python3.14" / "tkinter",
        dst_python / "lib" / "python3.14" / "idlelib",
        dst_python / "lib" / "python3.14" / "turtledemo",
        dst_python / "include",
    ]:
        if unused.exists():
            shutil.rmtree(unused, ignore_errors=True)
    for static_lib in dst_python.rglob("libpython*.a"):
        try:
            static_lib.unlink()
        except Exception:
            pass
    print("  ✓ Bundled ./python (CPython 3.14.10 stripped runtime)")

    # 3. Collect macOS arm64 offline wheels for Python 3.14 directly from requirements.txt
    dst_wheels = PKG_DIR / "wheels"
    dst_wheels.mkdir(parents=True, exist_ok=True)
    print("📦 Collecting macOS arm64 offline wheels for Python 3.14 (synced with requirements.txt)...")

    pkgs: list[str] = []
    for raw_line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "sys_platform == 'win32'" in line or 'sys_platform == "win32"' in line:
            continue
        req_spec = line.split(";", 1)[0].strip()
        if req_spec.lower().startswith("sudachidict"):
            print(f"  -> Building wheel for {req_spec}...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(dst_wheels), req_spec
            ])
            continue
        pkgs.append(req_spec)

    for pkg in pkgs:
        cmd = [
            sys.executable, "-m", "pip", "download",
            "--platform", "macosx_14_0_arm64",
            "--only-binary=:all:",
            "--python-version", "3.14",
            "--implementation", "cp",
            "--abi", "cp314",
            "-d", str(dst_wheels),
            pkg,
        ]
        res = subprocess.call(cmd)
        if res != 0:
            cmd_fallback = [
                sys.executable, "-m", "pip", "wheel",
                "--platform", "macosx_14_0_arm64",
                "--python-version", "3.14",
                "-w", str(dst_wheels),
                pkg,
            ]
            subprocess.check_call(cmd_fallback)
    print(f"  ✓ Bundled {len(list(dst_wheels.iterdir()))} offline wheels")

    # 4. Copy Application Source & Assets (exclude local config.json)
    items = [
        "core",
        "ui",
        "dicts",
        "main.py",
        "start.sh",
        "Hayamimi Polyglot.command",
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

    # Normalize shell scripts to Unix LF line endings
    for sh_file in [PKG_DIR / "start.sh", PKG_DIR / "Hayamimi Polyglot.command"]:
        if sh_file.is_file():
            content = sh_file.read_bytes().replace(b"\r\n", b"\n")
            sh_file.write_bytes(content)

    (PKG_DIR / "dicts" / "session_hotwords.txt").unlink(missing_ok=True)

    # 5. Copy Models (INT8 Only, excluding test_wavs)
    src_models = ROOT / "models"
    dst_models = PKG_DIR / "models"
    dst_models.mkdir(parents=True, exist_ok=True)
    print(f"  -> Packaging INT8 models from {src_models}...")

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
    pk_src = src_models / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    if pk_src.exists():
        pk_dst = dst_models / pk_src.name
        pk_dst.mkdir(parents=True, exist_ok=True)
        for f in pk_src.iterdir():
            if f.is_file() and (f.suffix in (".onnx", ".txt", ".md") or f.name == "LICENSE"):
                shutil.copy2(f, pk_dst / f.name)

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

    nem_src = src_models / "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8"
    if nem_src.exists():
        nem_dst = dst_models / nem_src.name
        nem_dst.mkdir(parents=True, exist_ok=True)
        for f in ["tokens.txt", "README.md", "LICENSE"]:
            if (nem_src / f).exists():
                shutil.copy2(nem_src / f, nem_dst / f)
        for f in nem_src.glob("*.int8.onnx"):
            shutil.copy2(f, nem_dst / f.name)

    rz_src = src_models / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
    if rz_src.exists():
        rz_dst = dst_models / rz_src.name
        rz_dst.mkdir(parents=True, exist_ok=True)
        for f in ["tokens.txt", "README.md", "LICENSE"]:
            if (rz_src / f).exists():
                shutil.copy2(rz_src / f, rz_dst / f)
        for f in rz_src.glob("*.int8.onnx"):
            shutil.copy2(f, rz_dst / f.name)

    if (src_models / "silero_vad.onnx").exists():
        shutil.copy2(src_models / "silero_vad.onnx", dst_models / "silero_vad.onnx")

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
    exec_filenames = {"start.sh", "Hayamimi Polyglot.command", "uv", "python", "python3", "python3.14"}

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zipf:
        file_count = 0
        for root, _dirs, files in os.walk(BUILD_DIR):
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
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                with open(full_path, "rb") as f_in:
                    zipf.writestr(zinfo, f_in.read(), compress_type=zipfile.ZIP_DEFLATED)
                file_count += 1
                if file_count % 500 == 0:
                    print(f"  ... archived {file_count} files")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n🎉 Package generated: {OUTPUT_ZIP} ({size_mb:.2f} MB)")

    # 7. Smoke Test on macOS Runner
    if sys.platform == "darwin":
        print("\n🧪 Running Headless Smoke Test on macOS...")
        test_extract_dir = ROOT / "build_test_mac_extract"
        if test_extract_dir.exists():
            shutil.rmtree(test_extract_dir)
        test_extract_dir.mkdir(parents=True, exist_ok=True)

        subprocess.check_call(["unzip", "-q", str(OUTPUT_ZIP), "-d", str(test_extract_dir)])
        pkg_root = test_extract_dir / "hayamimi-polyglot"

        print("  -> Initializing .venv from bundled wheels...")
        test_env = os.environ.copy()
        test_env["QT_QPA_PLATFORM"] = "offscreen"

        subprocess.check_call(["chmod", "+x", str(pkg_root / "start.sh"), str(pkg_root / "uv")])
        subprocess.check_call(["./start.sh", "--dry-run"], cwd=str(pkg_root), env=test_env)

        test_py = pkg_root / ".venv" / "bin" / "python"
        smoke_cmd = [
            str(test_py),
            "-c",
            (
                "import os, sys; "
                "print('  [OK] Python version:', sys.version); "
                "assert sys.version_info[:2] == (3, 14), f'Expected Python 3.14, got {sys.version}'; "
                "os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
                "from PySide6 import QtCore, QtWidgets; "
                "import main; "
                "print('  [OK] [macOS TEST] PySide6 and main.py loaded on Apple Silicon!')"
            ),
        ]
        subprocess.check_call(smoke_cmd, env=test_env, cwd=str(pkg_root))
        shutil.rmtree(test_extract_dir)
        print("🎉 macOS SMOKE TESTS PASSED!")

    shutil.rmtree(BUILD_DIR)
    print("✓ All build artifacts cleaned. Build & Test Complete!")


if __name__ == "__main__":
    main()
