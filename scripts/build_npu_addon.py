"""
Hayamimi Polyglot - package the NPU add-on ZIPs (release tool, run on a build machine).

Creates two ZIPs that users drop into the app's `addons/` folder (no manual unzip needed):

    hayamimi-polyglot-npu-addon-core-<ver>-windows.zip   OpenVINO runtime + ReazonSpeech + SenseVoice  (ja, zh, ko)
    hayamimi-polyglot-npu-addon-euro-<ver>-windows.zip   Parakeet TDT v3                              (en, fr, de, es)

Safety rules enforced here (docs/npu_design.md section 8.5, Windows Smart App Control):
  * every native binary (.dll/.pyd/.exe/.sys) must carry a VALID Authenticode signature from an
    allowed publisher (Intel Corporation) - otherwise the build fails;
  * only the `openvino/` package is shipped (pip's unsigned `bin/*.exe` launchers are left out);
  * each ZIP stays below GitHub's 2 GiB release-asset limit;
  * the manifest SHA-256 of each ZIP is written to core/npu/addons_known.json, which the app
    uses to recognise (and only then install) the add-on.

Typical use:
    python scripts/build_npu_models.py --out models/npu --with-parakeet
    python -m pip install --no-deps --target addons/packages openvino==2026.4.1   # same Python as the app
    python scripts/build_npu_addon.py        # version comes from core/npu/addon_version.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
KNOWN_FILE = ROOT / "core" / "npu" / "addons_known.json"
BINARY_SUFFIXES = (".dll", ".pyd", ".exe", ".sys")
ALLOWED_PUBLISHERS = ("Intel Corporation",)
MAX_ZIP_BYTES = int(1.95 * 1024 ** 3)  # GitHub release assets are limited to 2 GiB
STORED_SUFFIXES = (".bin",)             # fp16 weights barely compress; storing them is much faster


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_signatures(files: List[Path]) -> None:
    """Fail unless every native binary is validly signed by an allowed publisher (uses PowerShell)."""
    bins = [p for p in files if p.suffix.lower() in BINARY_SUFFIXES]
    if not bins:
        return
    listing = "\n".join(str(p) for p in bins)
    ps = (
        "$ErrorActionPreference='Stop';"
        "Get-Content -LiteralPath $env:HAY_LIST -Encoding UTF8 | ForEach-Object {"
        " $s = Get-AuthenticodeSignature -LiteralPath $_;"
        " $subj = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' };"
        " \"$($s.Status)`t$subj`t$_\" }"
    )
    import os
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(listing)
        list_path = tf.name
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", env={**os.environ, "HAY_LIST": list_path}, check=True,
        ).stdout
    finally:
        os.unlink(list_path)
    bad = []
    for line in out.splitlines():
        status, subject, path = (line.split("\t") + ["", "", ""])[:3]
        if status != "Valid" or not any(pub in subject for pub in ALLOWED_PUBLISHERS):
            bad.append(f"{path} ({status}; {subject or 'no signer'})")
    if bad:
        raise SystemExit("Refusing to package binaries that are not validly signed by an allowed publisher:\n  "
                         + "\n  ".join(bad[:20]))
    print(f"  signature check OK: {len(bins)} native binaries, all signed by {', '.join(ALLOWED_PUBLISHERS)}")


def collect(base: Path, prefix: str, patterns: Tuple[str, ...] | None = None) -> Dict[str, Path]:
    """Map manifest path -> file for everything below `base` (skipping caches)."""
    files: Dict[str, Path] = {}
    for p in sorted(base.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        files[f"{prefix}/{p.relative_to(base).as_posix()}"] = p
    return files


def build_zip(name: str, version: str, files: Dict[str, Path], out_dir: Path, min_app: str, suffix: str) -> Tuple[Path, str]:
    check_signatures(list(files.values()))
    manifest = {
        "format": 1,
        "name": name,
        "version": version,
        "min_app_version": min_app,
        "total_bytes": sum(p.stat().st_size for p in files.values()),
        "files": {rel: sha256_file(p) for rel, p in files.items()},
    }
    mbytes = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"hayamimi-polyglot-{name}-{version}-{suffix}.zip"
    (out_dir / f"{name}.manifest.json").write_bytes(mbytes)  # small; lets CI diagnose reproducibility drift
    print(f"  writing {zip_path.name} ({len(files)} files, {manifest['total_bytes'] / 1024 ** 2:.0f} MB uncompressed) ...")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", mbytes, compress_type=zipfile.ZIP_DEFLATED)
        for rel, p in files.items():
            ctype = zipfile.ZIP_STORED if p.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            zf.write(p, rel, compress_type=ctype)
    size = zip_path.stat().st_size
    if size > MAX_ZIP_BYTES:
        raise SystemExit(f"{zip_path.name} is {size / 1024 ** 3:.2f} GiB; GitHub assets are limited to 2 GiB")
    print(f"  -> {size / 1024 ** 2:.0f} MB")
    return zip_path, hashlib.sha256(mbytes).hexdigest()


def update_known(entries: Dict[str, dict]) -> None:
    try:
        known = json.loads(KNOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        known = {}
    known.update(entries)
    KNOWN_FILE.write_text(json.dumps(known, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--addon-version", default=(ROOT / "core" / "npu" / "addon_version.txt").read_text(encoding="utf-8").strip(),
                    help="add-on version (default: core/npu/addon_version.txt)")
    ap.add_argument("--check", action="store_true",
                    help="CI mode: do not touch addons_known.json; fail if the built manifests differ from the pinned ones")
    ap.add_argument("--min-app-version", default=(ROOT / "version.txt").read_text(encoding="utf-8").strip().lstrip("vV") if (ROOT / "version.txt").is_file() else "1.0.0")
    ap.add_argument("--packages", type=Path, default=ROOT / "addons" / "packages")
    ap.add_argument("--models", type=Path, default=ROOT / "models" / "npu")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--suffix", default="windows")
    ap.add_argument("--release-tag", help="GitHub release tag the ZIPs will be attached to (recorded for fetch_npu_addon.py)")
    args = ap.parse_args()

    ov = args.packages / "openvino"
    if not (ov / "__init__.py").is_file():
        raise SystemExit(f"OpenVINO package not found in {args.packages} (see the usage in this file's docstring)")
    for needed in ("reazon", "sensevoice", "parakeet"):
        if not (args.models / needed / ("meta.json" if needed != "parakeet" else "parakeet_encoder.xml")).is_file():
            raise SystemExit(f"NPU model set '{needed}' not found in {args.models}; run scripts/build_npu_models.py first")

    core_files: Dict[str, Path] = {}
    core_files.update(collect(ov, "packages/openvino"))
    for dist_info in sorted(args.packages.glob("openvino-*.dist-info")):
        core_files.update(collect(dist_info, f"packages/{dist_info.name}"))
    core_files.update(collect(args.models / "reazon", "models/npu/reazon"))
    core_files.update(collect(args.models / "sensevoice", "models/npu/sensevoice"))
    euro_files = collect(args.models / "parakeet", "models/npu/parakeet")

    known: Dict[str, dict] = {}
    for name, files in (("npu-addon-core", core_files), ("npu-addon-euro", euro_files)):
        print(f"[{name}]")
        zip_path, mhash = build_zip(name, args.addon_version, files, args.out, args.min_app_version, args.suffix)
        known[f"{name}-{args.addon_version}"] = {
            "manifest_sha256": mhash,
            "zip": zip_path.name,
            "zip_sha256": sha256_file(zip_path),
        }
        if args.release_tag:
            known[f"{name}-{args.addon_version}"]["tag"] = args.release_tag
    if args.check:
        pinned = json.loads(KNOWN_FILE.read_text(encoding="utf-8")) if KNOWN_FILE.is_file() else {}
        bad = [k for k, v in known.items() if pinned.get(k, {}).get("manifest_sha256") != v["manifest_sha256"]]
        for k, v in known.items():
            print(f"  {k}: built={v['manifest_sha256']}  pinned={pinned.get(k, {}).get('manifest_sha256')}")
        if bad:
            raise SystemExit(
                "\nThe add-on built here does not match the hashes pinned in core/npu/addons_known.json:\n  "
                + "\n  ".join(bad)
                + "\nIf the models or OpenVINO changed on purpose, run scripts/build_npu_addon.py locally and commit the updated "
                  "addons_known.json together with the change. Otherwise the build is not reproducible - investigate before releasing."
            )
        print("\nPinned hashes match the freshly built add-on.")
        return 0
    update_known(known)
    print(f"\nUpdated {KNOWN_FILE.relative_to(ROOT)} - commit it together with the app release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
