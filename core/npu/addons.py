"""
Hayamimi Polyglot - NPU add-on installer.

The user only has to drop the downloaded add-on ZIP into the `addons/` folder.
On the next start this module extracts it by itself, so the user never depends on
how their unzip tool lays out folders.

Design notes (see docs/npu_design.md section 8):
  * The extractor is ours (zipfile), with zip-slip protection; the layout of the
    ZIP (top-level folder or not) does not matter. `manifest.json` is found at the
    ZIP root or one directory below it.
  * An add-on contains code (DLLs), so it is only installed when the SHA-256 of its
    manifest is pinned in `addons_known.json` (shipped inside the app), and every
    file must match the SHA-256 listed in that manifest.
  * Windows Smart App Control: every native binary that was extracted is verified with
    WinVerifyTrust before it is ever imported. Anything not validly signed disables
    NPU mode (CPU keeps working) instead of being loaded.
  * Files are extracted into `addons/.staging/` first and moved into place only after
    verification, so an interrupted run never leaves a half-installed add-on.
  * Nothing here touches the network (revocation checks are cache-only).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional

APP_ROOT = Path(__file__).resolve().parent.parent.parent
_KNOWN_FILE = Path(__file__).resolve().parent / "addons_known.json"

MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1
# Where manifest paths may point to (first path component -> destination root)
_ALLOWED_TOP = ("packages", "models")
_BINARY_SUFFIXES = (".dll", ".pyd", ".exe", ".sys")
_INCOMPLETE_SUFFIXES = (".crdownload", ".part", ".tmp", ".partial", ".download")
_SETTLE_SECONDS = 3.0

LogFn = Callable[[str], None]


def _default_log(msg: str) -> None:
    print(msg)


@dataclass
class AddonResult:
    source: str
    name: str = ""
    version: str = ""
    status: str = "skipped"  # installed | skipped | deferred | error
    message: str = ""


@dataclass
class AddonState:
    """Process-wide state shared with the UI / ASR engine."""

    done: threading.Event = field(default_factory=threading.Event)
    running: bool = False
    results: List[AddonResult] = field(default_factory=list)
    signature_error: str = ""


STATE = AddonState()


# ------------------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------------------
def addons_dir(root: Optional[Path] = None) -> Path:
    return (root or APP_ROOT) / "addons"


def packages_dir(root: Optional[Path] = None) -> Path:
    return addons_dir(root) / "packages"


def models_root(root: Optional[Path] = None) -> Path:
    return (root or APP_ROOT) / "models"


def installed_file(root: Optional[Path] = None) -> Path:
    return addons_dir(root) / "installed.json"


def activate_paths(root: Optional[Path] = None) -> bool:
    """Make `addons/packages` importable (openvino lives there). Idempotent."""
    pkg = packages_dir(root)
    if not pkg.is_dir():
        return False
    p = str(pkg)
    if p not in sys.path:
        sys.path.insert(1, p)
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        # openvino registers its own DLL directories on import; the package dir itself
        # is added too so that sibling DLL lookups keep working in portable layouts.
        try:
            os.add_dll_directory(p)
        except Exception:
            pass
    return True


def load_known(path: Optional[Path] = None) -> Dict[str, dict]:
    try:
        data = json.loads((path or _KNOWN_FILE).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


# ------------------------------------------------------------------------------
# Safe path handling
# ------------------------------------------------------------------------------
class AddonError(Exception):
    pass


def _clean_rel(name: str) -> PurePosixPath:
    """Normalise a ZIP / manifest path and reject anything that could escape."""
    if "\\" in name or ":" in name or name.startswith("/"):
        raise AddonError(f"unsafe path in add-on: {name!r}")
    p = PurePosixPath(name)
    if not p.parts or any(part in ("", ".", "..") for part in p.parts):
        raise AddonError(f"unsafe path in add-on: {name!r}")
    return p


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------------------
# Authenticode verification (Windows only, no network)
# ------------------------------------------------------------------------------
def verify_signature(path: Path) -> bool:
    """True if `path` carries a valid Authenticode signature (cache-only, no revocation fetch)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.c_void_p),
        ]

    class WINTRUST_DATA(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
            ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)), ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", ctypes.c_void_p),
        ]

    WTD_UI_NONE = 2
    WTD_REVOKE_NONE = 0
    WTD_CHOICE_FILE = 1
    WTD_STATEACTION_VERIFY = 1
    WTD_STATEACTION_CLOSE = 2
    WTD_CACHE_ONLY_URL_RETRIEVAL = 0x00001000  # never go to the network
    WTD_REVOCATION_CHECK_NONE = 0x00000010
    action = GUID(0x00AAC56B, 0xCD44, 0x11D0, (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))

    file_info = WINTRUST_FILE_INFO(ctypes.sizeof(WINTRUST_FILE_INFO), str(path), None, None)
    data = WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
    data.dwUIChoice = WTD_UI_NONE
    data.fdwRevocationChecks = WTD_REVOKE_NONE
    data.dwUnionChoice = WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = WTD_STATEACTION_VERIFY
    data.dwProvFlags = WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_NONE

    wintrust = ctypes.WinDLL("wintrust")
    wintrust.WinVerifyTrust.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_void_p]
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    try:
        rc = wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
    finally:
        data.dwStateAction = WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
    return rc == 0


def verify_binaries(root_dir: Path, log: LogFn = _default_log, verifier: Callable[[Path], bool] = verify_signature) -> List[str]:
    """Return the list of native binaries below `root_dir` that are NOT validly signed."""
    bad: List[str] = []
    if not root_dir.is_dir():
        return bad
    for p in sorted(root_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in _BINARY_SUFFIXES:
            try:
                ok = verifier(p)
            except Exception as exc:  # pragma: no cover - defensive
                log(f"[Addon] signature check failed for {p.name}: {exc}")
                ok = False
            if not ok:
                bad.append(str(p.relative_to(root_dir)))
    return bad


def check_installed_signatures(root: Optional[Path] = None, log: LogFn = _default_log,
                               verifier: Callable[[Path], bool] = verify_signature) -> bool:
    """
    Verify (with a size/mtime cache) that every native binary in addons/packages is signed.
    On failure NPU mode must stay disabled: STATE.signature_error carries the reason.
    """
    pkg = packages_dir(root)
    if not pkg.is_dir():
        return True
    cache_path = addons_dir(root) / "verified.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    new_cache: Dict[str, list] = {}
    bad: List[str] = []
    for p in sorted(pkg.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in _BINARY_SUFFIXES):
            continue
        st = p.stat()
        key = str(p.relative_to(pkg))
        sig = [st.st_size, int(st.st_mtime)]
        if cache.get(key) == sig:
            new_cache[key] = sig
            continue
        try:
            ok = verifier(p)
        except Exception:
            ok = False
        if ok:
            new_cache[key] = sig
        else:
            bad.append(key)
    try:
        cache_path.write_text(json.dumps(new_cache), encoding="utf-8")
    except Exception:
        pass
    if bad:
        STATE.signature_error = (
            f"署名を確認できないファイルがあるため NPU を無効にしました: {', '.join(bad[:3])}"
            + (" ほか" if len(bad) > 3 else "")
        )
        log(f"[Addon] {STATE.signature_error}")
        return False
    STATE.signature_error = ""
    return True


# ------------------------------------------------------------------------------
# Source abstraction: ZIP file or already-extracted folder
# ------------------------------------------------------------------------------
class _ZipSource:
    def __init__(self, path: Path):
        self.path = path
        self.zf = zipfile.ZipFile(path)
        self.prefix = ""
        self.manifest_bytes = self._find_manifest()

    def _find_manifest(self) -> bytes:
        candidates = []
        for info in self.zf.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if parts and parts[-1] == MANIFEST_NAME and len(parts) <= 2:
                candidates.append((len(parts), info.filename))
        if not candidates:
            raise AddonError("manifest.json not found")
        candidates.sort()
        name = candidates[0][1].replace("\\", "/")
        self.prefix = name[: -len(MANIFEST_NAME)]
        return self.zf.read(candidates[0][1])

    def open(self, rel: str):
        return self.zf.open(self.prefix + rel)

    def exists(self, rel: str) -> bool:
        try:
            self.zf.getinfo(self.prefix + rel)
            return True
        except KeyError:
            try:
                self.zf.getinfo((self.prefix + rel).replace("/", "\\"))
                return True
            except KeyError:
                return False

    def close(self):
        self.zf.close()


class _DirSource:
    def __init__(self, path: Path):
        self.path = path
        base = path
        mf = base / MANIFEST_NAME
        if not mf.is_file():
            subs = [d for d in path.iterdir() if d.is_dir() and (d / MANIFEST_NAME).is_file()]
            if len(subs) != 1:
                raise AddonError("manifest.json not found")
            base = subs[0]
            mf = base / MANIFEST_NAME
        self.base = base
        self.manifest_bytes = mf.read_bytes()

    def open(self, rel: str):
        return open(self.base / rel, "rb")

    def exists(self, rel: str) -> bool:
        return (self.base / rel).is_file()

    def close(self):
        pass


# ------------------------------------------------------------------------------
# Installation
# ------------------------------------------------------------------------------
def _parse_manifest(raw: bytes) -> dict:
    try:
        m = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise AddonError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(m, dict) or m.get("format") != MANIFEST_FORMAT:
        raise AddonError("unsupported manifest format")
    for key in ("name", "version", "files"):
        if key not in m:
            raise AddonError(f"manifest.json lacks '{key}'")
    if not isinstance(m["files"], dict) or not m["files"]:
        raise AddonError("manifest.json lists no files")
    return m


def _version_tuple(v: str) -> tuple:
    out = []
    for part in str(v).split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def current_app_version() -> str:
    try:
        return (APP_ROOT / "version.txt").read_text(encoding="utf-8").strip().lstrip("vV")
    except Exception:
        return "0.0.0"


def _install_one(src, source_name: str, root: Path, known: Dict[str, dict], allow_unknown: bool,
                 verifier: Callable[[Path], bool], log: LogFn) -> AddonResult:
    manifest = _parse_manifest(src.manifest_bytes)
    name, version = str(manifest["name"]), str(manifest["version"])
    res = AddonResult(source=source_name, name=name, version=version)

    # 1. trust: manifest hash must be pinned in the app (the manifest pins every file's hash)
    mhash = hashlib.sha256(src.manifest_bytes).hexdigest()
    pinned = {v.get("manifest_sha256") for v in known.values()}
    if mhash not in pinned and not allow_unknown:
        raise AddonError("このアドオンはこのバージョンのアプリでは認識できません（未登録のハッシュ）")

    # 2. compatibility
    min_app = str(manifest.get("min_app_version", "0"))
    if _version_tuple(current_app_version()) < _version_tuple(min_app):
        raise AddonError(f"アプリ {min_app} 以上が必要です")

    # 3. validate the file list
    files: Dict[PurePosixPath, str] = {}
    total = 0
    for rel, sha in manifest["files"].items():
        p = _clean_rel(rel)
        if p.parts[0] not in _ALLOWED_TOP:
            raise AddonError(f"unsupported install location: {rel}")
        if not isinstance(sha, str) or len(sha) != 64:
            raise AddonError(f"bad hash for {rel}")
        if not src.exists(str(p)):
            raise AddonError(f"file missing in add-on: {rel}")
        files[p] = sha.lower()

    # 4. disk space (extracted size is unknown for folders; use the manifest hint when present)
    need = int(manifest.get("total_bytes", 0))
    if need:
        free = shutil.disk_usage(addons_dir(root)).free
        if free < need * 1.1:
            raise AddonError(f"ディスクの空き容量が不足しています（必要 約{need // (1024 * 1024)}MB）")

    # 5. extract to staging with on-the-fly hashing
    staging = addons_dir(root) / ".staging" / name
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for rel, sha in files.items():
            dest = staging.joinpath(*rel.parts)
            if not _within(staging, dest):
                raise AddonError(f"unsafe path in add-on: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with src.open(str(rel)) as fin, open(dest, "wb") as fout:
                for chunk in iter(lambda: fin.read(1024 * 1024), b""):
                    h.update(chunk)
                    fout.write(chunk)
            if h.hexdigest() != sha:
                raise AddonError(f"ハッシュが一致しません（ファイルが壊れています）: {rel}")

        # 6. every native binary must be validly signed before it can be used (SAC)
        bad = verify_binaries(staging, log=log, verifier=verifier)
        if bad:
            raise AddonError("署名を確認できないバイナリが含まれています: " + ", ".join(bad[:3]))

        # 7. move into place (replace older versions of the same add-on)
        _promote(staging, root, name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _record_installed(root, name, version, [str(p) for p in files])
    res.status = "installed"
    res.message = f"{name} {version} を導入しました"
    return res


def _promote(staging: Path, root: Path, name: str) -> None:
    dest_for = {"packages": packages_dir(root), "models": models_root(root)}
    # remove what the previous version of this add-on installed
    prev = _read_installed(root).get(name, {}).get("files", [])
    for rel in prev:
        try:
            p = _clean_rel(rel)
            target = dest_for[p.parts[0]].joinpath(*p.parts[1:])
            if target.is_file():
                target.unlink()
        except Exception:
            continue
    # Files that make a component "present" (package __init__, model IR/meta) go last, so an
    # interrupted run never leaves something that looks complete.
    def order(path: Path):
        late = path.name in ("__init__.py", "meta.json") or path.suffix == ".xml"
        return (late, str(path))

    for top in _ALLOWED_TOP:
        src_top = staging / top
        if not src_top.is_dir():
            continue
        dest_top = dest_for[top]
        dest_top.mkdir(parents=True, exist_ok=True)
        for item in sorted((f for f in src_top.rglob("*") if f.is_file()), key=order):
            target = dest_top / item.relative_to(src_top)
            target.parent.mkdir(parents=True, exist_ok=True)
            _move_file(item, target)


def _move_file(src: Path, dst: Path) -> None:
    """Rename when possible; copy+delete when the destination is on another volume (e.g. a linked models/)."""
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copy2(src, dst)
        try:
            src.unlink()
        except OSError:
            pass


def _read_installed(root: Optional[Path]) -> dict:
    try:
        return json.loads(installed_file(root).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _record_installed(root: Path, name: str, version: str, files: List[str]) -> None:
    data = _read_installed(root)
    data[name] = {"version": version, "files": files, "installed_at": int(time.time())}
    tmp = installed_file(root).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, installed_file(root))


def installed_addons(root: Optional[Path] = None) -> Dict[str, dict]:
    return _read_installed(root)


def _candidates(root: Path) -> List[Path]:
    """ZIPs / folders that might be add-ons: addons/ first, then the app root (lenient)."""
    found: List[Path] = []
    for base in (addons_dir(root), root):
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.name.startswith(".") or p.name in ("packages", "models"):
                continue
            if p.is_file() and p.suffix.lower() == ".zip":
                found.append(p)
            elif p.is_dir() and base == addons_dir(root) and (
                (p / MANIFEST_NAME).is_file() or any((d / MANIFEST_NAME).is_file() for d in p.iterdir() if d.is_dir())
            ):
                found.append(p)
    return found


def _is_settled(p: Path) -> bool:
    if p.suffix.lower() in _INCOMPLETE_SUFFIXES:
        return False
    try:
        return (time.time() - p.stat().st_mtime) >= _SETTLE_SECONDS
    except OSError:
        return False


def has_pending(root: Optional[Path] = None) -> bool:
    root = root or APP_ROOT
    for p in _candidates(root):
        try:
            if p.is_dir():
                return True
            with zipfile.ZipFile(p) as zf:
                if any(PurePosixPath(n.replace("\\", "/")).name == MANIFEST_NAME for n in zf.namelist()):
                    return True
        except Exception:
            continue
    return False


def process_pending(
    root: Optional[Path] = None,
    log: LogFn = _default_log,
    known: Optional[Dict[str, dict]] = None,
    verifier: Callable[[Path], bool] = verify_signature,
    keep_zip: bool = False,
) -> List[AddonResult]:
    """Install every add-on that was dropped into addons/. Never raises."""
    root = root or APP_ROOT
    known = known if known is not None else load_known()
    allow_unknown = os.environ.get("HAYAMIMI_ADDON_ALLOW_UNKNOWN") == "1"
    results: List[AddonResult] = []
    addons_dir(root).mkdir(parents=True, exist_ok=True)

    for cand in _candidates(root):
        r = AddonResult(source=cand.name)
        src = None
        try:
            if cand.is_file():
                if not _is_settled(cand):
                    r.status, r.message = "deferred", "ダウンロード中のため次回起動時に処理します"
                    results.append(r)
                    continue
                try:
                    src = _ZipSource(cand)
                except zipfile.BadZipFile:
                    r.status, r.message = "deferred", "ZIP を読めません（ダウンロード途中の可能性）。次回起動時に再試行します"
                    results.append(r)
                    continue
                except AddonError:
                    continue  # an unrelated ZIP: leave it alone, silently
            else:
                try:
                    src = _DirSource(cand)
                except AddonError:
                    continue
            log(f"[Addon] 展開中: {cand.name}")
            r = _install_one(src, cand.name, root, known, allow_unknown, verifier, log)
            if cand.is_file() and not keep_zip:
                try:
                    src.close()
                    src = None
                    cand.unlink()
                except OSError as exc:
                    log(f"[Addon] ZIP を削除できませんでした: {exc}")
            elif cand.is_dir() and not keep_zip:
                shutil.rmtree(cand, ignore_errors=True)
            log(f"[Addon] {r.message}")
        except AddonError as exc:
            r.status, r.message = "error", str(exc)
            log(f"[Addon] {cand.name}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            r.status, r.message = "error", f"{type(exc).__name__}: {exc}"
            log(f"[Addon] {cand.name}: {r.message}")
        finally:
            if src is not None:
                try:
                    src.close()
                except Exception:
                    pass
        results.append(r)
    return results


def run_startup(root: Optional[Path] = None, log: LogFn = _default_log, background: bool = True,
                on_done: Optional[Callable[[List[AddonResult]], None]] = None) -> None:
    """
    Entry point used by main.py: extract pending add-ons (in a thread by default so the UI and
    CPU mode are never blocked), then verify signatures of whatever is installed.
    """
    root = root or APP_ROOT

    def work():
        STATE.running = True
        try:
            res = process_pending(root, log=log) if has_pending(root) else []
            STATE.results = res
            activate_paths(root)
            check_installed_signatures(root, log=log)
            if on_done:
                try:
                    on_done(res)
                except Exception:
                    pass
        except Exception as exc:  # pragma: no cover - defensive
            log(f"[Addon] startup processing failed: {exc}")
        finally:
            STATE.running = False
            STATE.done.set()

    STATE.done.clear()
    if background:
        threading.Thread(target=work, daemon=True, name="AddonInstaller").start()
    else:
        work()


def wait_until_ready(timeout: Optional[float] = None) -> bool:
    """Block while the start-up add-on installer is still extracting (no-op if it never ran)."""
    if not STATE.running:
        return True
    return STATE.done.wait(timeout)
