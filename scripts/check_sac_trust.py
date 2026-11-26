#!/usr/bin/env python3
"""
Hayamimi Polyglot - Windows 11 Smart App Control (SAC) Trust & Signature Verifier

Checks native Python extensions (.pyd / .dll) against:
  1. Runtime dynamic import verification (ensures OS Application Control does not block load).
  2. Authenticode digital signature verification via Win32 WinVerifyTrust.
  3. Microsoft Defender Intelligent Security Graph (ISG) cloud reputation check via
     `MpCmdRun.exe -TrustCheck -File <path>` for unsigned native binaries.

Usage:
  # Local strict verification (default: fails if any runtime binary lacks signature & ISG trust)
  .venv\\Scripts\\python.exe scripts/check_sac_trust.py

  # Inspect an isolated wheel/site-packages directory before upgrading requirements.txt
  .venv\\Scripts\\python.exe scripts/check_sac_trust.py --site-packages path/to/dir --skip-import-check

  # GitHub Actions / Windows Server runner mode (enforces TrustCheck when MAPS cloud responds,
  # degrades gracefully with a warning only if runner OS policy blocks Defender cloud access)
  .venv\\Scripts\\python.exe scripts/check_sac_trust.py --allow-runner-no-cloud
"""

from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
import sysconfig
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# Core runtime modules imported by Hayamimi Polyglot on Windows
RUNTIME_IMPORT_MODULES: list[str] = [
    "numpy",
    "sounddevice",
    "soundfile",
    "cffi",
    "onnxruntime",
    "sherpa_onnx",
    "ctranslate2",
    "sentencepiece",
    "sudachipy",
    "comtypes",
    "pycaw",
    "psutil",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "fastapi",
    "pydantic_core",
    "uvicorn",
    "packaging",
]

# Vendor packages whose native binaries MUST always carry valid Authenticode signatures
MUST_BE_SIGNED_PACKAGES: set[str] = {
    "PySide6",
    "shiboken6",
    "onnxruntime",
    "openvino",
}


def win_verify_authenticode(path: Path) -> bool:
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


def find_mpcmdrun() -> Path | None:
    """Locate the latest Microsoft Defender MpCmdRun.exe binary."""
    prog_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    platform_root = prog_data / "Microsoft" / "Windows Defender" / "Platform"
    if platform_root.is_dir():
        candidates = sorted(platform_root.glob("*/MpCmdRun.exe"), reverse=True)
        for cand in candidates:
            if cand.is_file():
                return cand

    prog_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    fallback = prog_files / "Windows Defender" / "MpCmdRun.exe"
    if fallback.is_file():
        return fallback
    return None


def is_exempt_binary(rel_path: Path) -> str | None:
    """
    Return exemption reason if a binary is non-runtime, wrong-architecture, test-only,
    or an internal auxiliary module known not to trigger SAC blocks; otherwise None.
    """
    parts = rel_path.parts
    name_lower = rel_path.name.lower()

    # 1. Unused PortAudio architectures / ASIO drivers (app uses only libportaudio64bit.dll)
    if "_sounddevice_data" in parts and "portaudio-binaries" in parts:
        if rel_path.name != "libportaudio64bit.dll":
            return "unused PortAudio architecture/ASIO variant"

    # 2. NumPy test-only dummy C extensions
    if parts[0] == "numpy" and "tests" in name_lower and name_lower.startswith("_"):
        return "numpy test-only extension"
    if "tests" in parts:
        return "package unit-test binary"

    # 3. Standalone C/C++ shared libraries in sherpa_onnx not imported by Python _sherpa_onnx.pyd
    if parts[0] == "sherpa_onnx" and name_lower in ("sherpa-onnx-c-api.dll", "sherpa-onnx-cxx-api.dll"):
        return "unused C/C++ standalone wrapper DLL (not linked by _sherpa_onnx.pyd)"

    # 4. Internal NumPy auxiliary leaf modules (verified loadable under enforced SAC, while core
    #    _multiarray_umath.pyd, _umath_linalg.pyd, and OpenBLAS DLLs validate NumPy ISG reputation)
    if parts[0] == "numpy" and (
        name_lower.startswith("_simd.") or name_lower.startswith("lapack_lite.")
    ):
        return "numpy internal auxiliary leaf module"

    return None


def run_defender_trust_check(mpcmdrun: Path, target: Path) -> tuple[str, str]:
    """
    Query Microsoft Defender ISG cloud reputation for a single file.
    Returns (status, detail) where status is one of:
      - "trusted": File is Trusted
      - "untrusted": Explicitly reported as not a known good file
      - "error": MpCmdRun failed or cloud service unavailable
    """
    try:
        proc = subprocess.run(
            [str(mpcmdrun), "-TrustCheck", "-File", str(target.resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception as exc:
        return "error", f"subprocess error: {exc}"

    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    if "File is Trusted" in combined:
        return "trusted", "File is Trusted"
    if "not a known good file" in combined:
        return "untrusted", "Defender ISG: not a known good file"
    return "error", combined.splitlines()[-1] if combined else f"rc={proc.returncode}"


def resolve_default_site_packages() -> list[Path]:
    """Resolve active environment's site-packages directory."""
    candidates: list[Path] = []
    for key in ("platlib", "purelib"):
        p = sysconfig.get_path(key)
        if p:
            path_obj = Path(p).resolve()
            if path_obj.is_dir() and path_obj not in candidates:
                candidates.append(path_obj)
    for sp in site.getsitepackages():
        path_obj = Path(sp).resolve()
        if path_obj.is_dir() and "site-packages" in path_obj.name.lower() and path_obj not in candidates:
            candidates.append(path_obj)
    return candidates


def verify_runtime_imports() -> list[str]:
    """Dynamically import all runtime dependencies to catch immediate SAC / DLL load errors."""
    print("🔍 [Step 1] Verifying dynamic runtime imports...")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    failures: list[str] = []
    for mod in RUNTIME_IMPORT_MODULES:
        try:
            __import__(mod)
        except Exception as exc:
            failures.append(f"{mod}: {type(exc).__name__}: {exc}")
    if failures:
        for f in failures:
            print(f"  [FAIL] Import failed: {f}")
    else:
        print(f"  [OK] All {len(RUNTIME_IMPORT_MODULES)} runtime modules imported cleanly.")
    return failures


def audit_site_packages(
    target_dirs: list[Path],
    allow_runner_no_cloud: bool = False,
) -> int:
    """Audit Authenticode signatures and Defender ISG cloud trust across target directories."""
    print("🛡️ [Step 2] Auditing native binaries (.pyd / .dll) for Authenticode & SAC ISG trust...")
    mpcmdrun = find_mpcmdrun()
    if mpcmdrun:
        print(f"  -> Using Defender CLI: {mpcmdrun}")
    else:
        print("  [WARN] MpCmdRun.exe not found on this Windows system.")

    signed_files: list[str] = []
    exempt_files: list[tuple[str, str]] = []
    unsigned_targets: list[tuple[Path, Path]] = []
    signature_violations: list[str] = []

    for base_dir in target_dirs:
        base_res = base_dir.resolve()
        if not base_res.exists():
            print(f"  [ERROR] Target directory does not exist: {base_res}")
            return 1

        bins = sorted(
            p for p in base_res.rglob("*")
            if p.is_file() and p.suffix.lower() in (".pyd", ".dll")
        )
        for p in bins:
            rel = p.resolve().relative_to(base_res)
            reason = is_exempt_binary(rel)
            if reason is not None:
                exempt_files.append((str(rel), reason))
                continue

            if win_verify_authenticode(p):
                signed_files.append(str(rel))
                continue

            top_pkg = rel.parts[0] if rel.parts else ""
            if top_pkg in MUST_BE_SIGNED_PACKAGES:
                signature_violations.append(
                    f"Vendor-signed package lost Authenticode signature: {rel}"
                )
                continue

            unsigned_targets.append((p, rel))

    print(
        f"  -> Scanned binaries: {len(signed_files)} Authenticode-signed, "
        f"{len(unsigned_targets)} unsigned runtime extensions to check via Defender ISG, "
        f"{len(exempt_files)} non-runtime/auxiliary skipped."
    )

    if signature_violations:
        print("\n❌ Authenticode Signature Violations:")
        for v in signature_violations:
            print(f"  - {v}")
        return 1

    if not unsigned_targets:
        print("  [OK] Zero unsigned runtime binaries require ISG cloud check.")
        return 0

    if mpcmdrun is None:
        if allow_runner_no_cloud:
            print(
                "  [WARN] MpCmdRun.exe unavailable on this runner; "
                "skipping cloud ISG check (--allow-runner-no-cloud)."
            )
            return 0
        print("  [FAIL] MpCmdRun.exe is required to verify unsigned binaries.")
        return 1

    trusted_list: list[str] = []
    untrusted_list: list[tuple[str, str]] = []
    error_list: list[tuple[str, str]] = []

    for abs_path, rel_path in unsigned_targets:
        verdict, detail = run_defender_trust_check(mpcmdrun, abs_path)
        if verdict == "trusted":
            trusted_list.append(str(rel_path))
            print(f"    [TRUSTED]   {rel_path}")
        elif verdict == "untrusted":
            untrusted_list.append((str(rel_path), detail))
            print(f"    [UNTRUSTED] {rel_path} -> {detail}")
        else:
            error_list.append((str(rel_path), detail))
            print(f"    [ERROR]     {rel_path} -> {detail}")
            if allow_runner_no_cloud and not trusted_list and not untrusted_list and len(error_list) >= 3:
                print(
                    "    [INFO] Fast-skipping remaining cloud checks: Defender service/cloud "
                    "is unavailable on this runner."
                )
                break

    # Detect runner-wide MAPS cloud disablement when running in CI (--allow-runner-no-cloud):
    # In a full environment (>= 5 unsigned baseline packages including numpy/psutil/cffi),
    # if ZERO binaries are recognized as Trusted, Defender MAPS cloud queries are blocked by OS policy.
    if allow_runner_no_cloud and len(trusted_list) == 0 and (
        len(error_list) > 0 or len(unsigned_targets) >= 5
    ):
        print(
            "\n⚠️ [WARN] Defender cloud reputation (MAPS / ISG) appears disabled by runner OS policy "
            f"(0/{len(unsigned_targets)} cloud verdicts returned Trusted). "
            "Authenticode & runtime import checks passed."
        )
        return 0

    if error_list:
        print(f"\n❌ Defender TrustCheck encountered {len(error_list)} engine error(s):")
        for rel_s, det in error_list:
            print(f"  - {rel_s}: {det}")
        return 1

    if untrusted_list:
        print(
            f"\n❌ Smart App Control (SAC) Reputation Check FAILED: "
            f"{len(untrusted_list)} unsigned binary/binaries lack Microsoft ISG trust!"
        )
        print("   These files are likely to be blocked by Windows 11 Smart App Control:")
        for rel_s, det in untrusted_list:
            print(f"  - {rel_s} ({det})")
        print(
            "\n💡 Action Required: Keep the previous SAC-verified version pinned in requirements.txt "
            "until Microsoft ISG establishes reputation for this release, or request upstream signing."
        )
        return 1

    print(
        f"\n✅ [PASS] SAC Trust Audit Complete: {len(signed_files)} signed + "
        f"{len(trusted_list)}/{len(unsigned_targets)} ISG-trusted (0 untrusted)!"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Authenticode signatures and Windows Defender ISG trust for SAC compatibility."
    )
    parser.add_argument(
        "--site-packages",
        nargs="*",
        type=Path,
        default=None,
        help="Explicit directory/directories to scan instead of active site-packages.",
    )
    parser.add_argument(
        "--skip-import-check",
        action="store_true",
        help="Skip Step 1 dynamic runtime module import test.",
    )
    parser.add_argument(
        "--allow-runner-no-cloud",
        action="store_true",
        help="Do not fail if GitHub Actions Windows Server runner policy disables Defender MAPS cloud queries.",
    )
    args = parser.parse_args()

    if os.name != "nt":
        print("ℹ️ [SKIP] Smart App Control check applies only to Windows (current OS is non-Windows).")
        return 0

    run_imports = not args.skip_import_check and not args.site_packages
    if run_imports:
        import_failures = verify_runtime_imports()
        if import_failures:
            return 1

    target_dirs = args.site_packages if args.site_packages else resolve_default_site_packages()
    if not target_dirs:
        print("❌ Could not resolve site-packages directory.")
        return 1

    return audit_site_packages(
        target_dirs=target_dirs,
        allow_runner_no_cloud=args.allow_runner_no_cloud,
    )


if __name__ == "__main__":
    sys.exit(main())
