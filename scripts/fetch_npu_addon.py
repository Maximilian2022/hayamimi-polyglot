"""
Hayamimi Polyglot - download the NPU add-on ZIPs into `addons/` (optional, needs internet once).

Used by `setup.ps1 -WithNpu`. The app extracts what lands in `addons/` by itself on its next start,
so nothing else has to be done. Each download is checked against the SHA-256 that this app
version pins in core/npu/addons_known.json before it is kept.

    python scripts/fetch_npu_addon.py            # core (ja, zh, ko) + euro (en, fr, de, es)
    python scripts/fetch_npu_addon.py --core-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Maximilian2022/hayamimi-polyglot"
KNOWN = ROOT / "core" / "npu" / "addons_known.json"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-NPU-Fetch", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url: str, dst: Path) -> str:
    h = hashlib.sha256()
    tmp = dst.with_suffix(dst.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-NPU-Fetch"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1024 ** 2:.0f} / {total / 1024 ** 2:.0f} MB", end="", flush=True)
    print()
    return h.hexdigest(), tmp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core-only", action="store_true", help="skip the Parakeet (en/fr/de/es) pack")
    ap.add_argument("--tag", help="release tag to read assets from (default: tag recorded in addons_known.json)")
    args = ap.parse_args()

    known = json.loads(KNOWN.read_text(encoding="utf-8")) if KNOWN.is_file() else {}
    if not known:
        print("This app version does not list any NPU add-on yet.")
        return 1
    wanted = {k: v for k, v in known.items() if not (args.core_only and "euro" in k)}
    tag = args.tag or next(iter(v.get("tag") for v in wanted.values() if v.get("tag")), None)
    releases = [_get_json(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")] if tag else _get_json(f"https://api.github.com/repos/{REPO}/releases?per_page=20")
    assets = {a["name"]: a["browser_download_url"] for rel in releases for a in rel.get("assets", [])}

    out = ROOT / "addons"
    out.mkdir(exist_ok=True)
    rc = 0
    for key, info in wanted.items():
        name = info.get("zip")
        if not name or name not in assets:
            print(f"[skip] {key}: {name} is not published")
            rc = 1
            continue
        if (out / name).is_file():
            print(f"[have] {name}")
            continue
        print(f"[download] {name}")
        digest, tmp = _download(assets[name], out / name)
        if info.get("zip_sha256") and digest != info["zip_sha256"]:
            tmp.unlink(missing_ok=True)
            print(f"[error] {name}: checksum mismatch, download discarded")
            rc = 1
            continue
        tmp.replace(out / name)
        print(f"[ok] {name} -> addons/  (it is installed automatically the next time the app starts)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
