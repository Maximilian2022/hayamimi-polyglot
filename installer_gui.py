#!/usr/bin/env python3
"""
Hayamimi Polyglot - Unified GUI Installer & Updater
Cross-platform: Windows 11 & macOS (14 Sonoma / 15 Sequoia)
Powered by PySide6 & uv
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ------------------------------------------------------------------------------
# 1. Smart Install Path Detection (Cloud Sync Avoidance) & True Desktop Path
# ------------------------------------------------------------------------------
def get_desktop_dir() -> Path:
    if platform.system() == "Windows":
        try:
            import ctypes.wintypes
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            # CSIDL_DESKTOPDIRECTORY = 0x0010 (handles OneDrive / Roaming redirection)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            if buf.value and Path(buf.value).exists():
                return Path(buf.value)
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            ).strip()
            if out and Path(out).exists():
                return Path(out)
        except Exception:
            pass
    return Path.home() / "Desktop"


def get_smart_install_path() -> Path:
    """
    Return a clean, user-visible install directory outside OneDrive/iCloud sync.
    Uninstallation requires only deleting this folder.
    """
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "core" / "asr_engine.py").exists():
        return script_dir

    system = platform.system()
    home = Path.home()
    docs = home / "Documents"

    if system == "Darwin":
        icloud_dir = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents"
        is_cloud = (
            docs.is_symlink()
            or "com~apple~CloudDocs" in str(docs.resolve())
            or icloud_dir.exists()
        )
        return (home / "hayamimi-polyglot") if is_cloud else (docs / "hayamimi-polyglot")

    if system == "Windows":
        try:
            real_docs_out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            ).strip()
            if real_docs_out:
                docs = Path(real_docs_out)
        except Exception:
            pass

        onedrive = os.environ.get("OneDrive", "")
        docs_lower = str(docs).lower()
        is_cloud = bool(
            (onedrive and docs_lower.startswith(onedrive.lower()))
            or any(k in docs_lower for k in ("onedrive", "google drive", "dropbox", "icloud"))
        )
        # Use user home directory (C:\Users\<User>\hayamimi-polyglot) when Documents is cloud-synced:
        # visible in Explorer, never synced by OneDrive, and cleanly removable by deleting the folder.
        return (home / "hayamimi-polyglot") if is_cloud else (docs / "hayamimi-polyglot")

    return home / "hayamimi-polyglot"


def _safe_extract_tar(tar_path: Path, dst_dir: Path) -> None:
    with tarfile.open(tar_path, "r:bz2") as tar:
        try:
            tar.extractall(path=dst_dir, filter="data")
        except TypeError:
            tar.extractall(path=dst_dir)


def _download_url(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-Installer"})
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dst)


def _copy_dicts_preserving_extensions(src_dicts: Path, dst_dicts: Path) -> None:
    """Update built-in dictionary files while preserving user extension dictionaries."""
    ext_backup: dict[str, bytes] = {}
    ext_dir = dst_dicts / "extensions"
    if ext_dir.is_dir():
        for f in ext_dir.glob("*.txt"):
            try:
                ext_backup[f.name] = f.read_bytes()
            except Exception:
                pass

    if dst_dicts.exists():
        shutil.rmtree(dst_dicts)
    shutil.copytree(src_dicts, dst_dicts)

    new_ext_dir = dst_dicts / "extensions"
    new_ext_dir.mkdir(parents=True, exist_ok=True)
    for name, content in ext_backup.items():
        target_f = new_ext_dir / name
        if not target_f.exists():
            target_f.write_bytes(content)


# ------------------------------------------------------------------------------
# 2. Background Installation Worker
# ------------------------------------------------------------------------------
class InstallWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)

    def __init__(
        self,
        target_dir: Path,
        clean_venv: bool,
        with_parakeet: bool,
        with_sense_voice: bool,
        with_zipformer_vi: bool = False,
        should_launch: bool = True,
    ):
        super().__init__()
        self.target_dir = target_dir
        self.clean_venv = clean_venv
        self.with_parakeet = with_parakeet
        self.with_sense_voice = with_sense_voice
        self.should_launch = should_launch

    def run(self):
        try:
            self.log_signal.emit(f"🚀 セットアップを開始します: {self.target_dir}")
            self.progress_signal.emit(10)
            self.target_dir.mkdir(parents=True, exist_ok=True)

            # 1. Verify / Find uv
            self.log_signal.emit("🔍 uv (Python環境マネージャー) を確認中...")
            uv_exe = shutil.which("uv")
            if not uv_exe:
                candidates = [
                    Path.home() / ".local" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"),
                    Path.home() / ".cargo" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"),
                ]
                for c in candidates:
                    if c.exists():
                        uv_exe = str(c)
                        break

            if not uv_exe:
                self.log_signal.emit("⬇️ uv をダウンロードしてセットアップしています...")
                if platform.system() == "Windows":
                    cmd = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"'
                else:
                    cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"
                subprocess.run(cmd, shell=True, check=True)
                uv_exe = str(Path.home() / ".local" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"))

            self.log_signal.emit(f"✓ uv 検出完了: {uv_exe}")
            self.progress_signal.emit(20)

            # 2. Virtual Environment (Python 3.14)
            venv_dir = self.target_dir / ".venv"
            py_exe = venv_dir / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")

            venv_ready = False
            if self.clean_venv:
                self.log_signal.emit("🐍 Python 3.14 仮想環境をクリーン構築中 (--clear)...")
                cmd = [uv_exe, "venv", "--clear", str(venv_dir), "--python", "3.14"]
                try:
                    subprocess.run(
                        cmd,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    venv_ready = True
                    self.log_signal.emit("✓ 仮想環境の構築が完了しました")
                except Exception:
                    self.log_signal.emit("⚠️ 既存の仮想環境を更新モードで利用します")

            if not venv_ready:
                if not py_exe.exists():
                    self.log_signal.emit("🐍 Python 3.14 仮想環境を新規作成中...")
                    cmd = [uv_exe, "venv", str(venv_dir), "--python", "3.14"]
                    subprocess.run(
                        cmd,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                else:
                    self.log_signal.emit("✓ 既存の Python 3.14 仮想環境を再利用します")

            self.progress_signal.emit(35)

            # 3. Deploy / Synchronize Application Files
            script_dir = Path(__file__).resolve().parent
            is_same_dir = script_dir.resolve() == self.target_dir.resolve()
            git_dir = self.target_dir / ".git"
            has_git = bool(shutil.which("git") and git_dir.is_dir())

            if has_git:
                self.log_signal.emit("🔄 Git リポジトリを検出: 最新コードを取得中 (git pull)...")
                try:
                    res = subprocess.run(
                        ["git", "pull", "origin", "main"],
                        cwd=str(self.target_dir),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                    )
                    if res.returncode == 0:
                        self.log_signal.emit(f"✓ 同期完了:\n  {res.stdout.strip()}")
                    else:
                        self.log_signal.emit(f"⚠️ git pull 通知: {res.stdout.strip()}")
                except Exception as g_err:
                    self.log_signal.emit(f"⚠️ git pull 例外: {g_err}")

            elif (script_dir / "core" / "asr_engine.py").exists() and not is_same_dir:
                self.log_signal.emit("📋 ローカルからアプリケーションファイルを配置中...")
                for item in ["core", "ui", "scripts"]:
                    src = script_dir / item
                    dst = self.target_dir / item
                    if src.exists():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                if (script_dir / "dicts").exists():
                    _copy_dicts_preserving_extensions(script_dir / "dicts", self.target_dir / "dicts")

                for item in [
                    "main.py",
                    "config.default.json",
                    "requirements.txt",
                    ".python-version",
                    "version.txt",
                    "start.bat",
                    "start.sh",
                    "setup.ps1",
                    "setup.sh",
                    "installer_gui.py",
                    "test_polyglot_suite.py",
                    "Third_Party_Notices.md",
                ]:
                    src = script_dir / item
                    dst = self.target_dir / item
                    if src.exists():
                        shutil.copy2(src, dst)
                if platform.system() != "Windows" and (self.target_dir / "start.sh").exists():
                    (self.target_dir / "start.sh").chmod(0o755)

            elif not is_same_dir or not (self.target_dir / "main.py").exists():
                self.log_signal.emit("🌐 GitHub からプログラムファイルをダウンロード中...")
                repo_zip_url = os.environ.get(
                    "HAYAMIMI_REPO_ZIP",
                    "https://github.com/Maximilian2022/hayamimi-polyglot/archive/refs/heads/main.zip",
                )
                zip_path = self.target_dir / "repo_download.zip"
                deployed_ok = False
                try:
                    import zipfile
                    _download_url(repo_zip_url, zip_path)

                    self.log_signal.emit("📦 プログラムファイルを展開中...")
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        extract_temp = self.target_dir / "_temp_extract"
                        zip_ref.extractall(extract_temp)
                        extracted_root = next(extract_temp.glob("hayamimi-polyglot*"), extract_temp)
                        for item in extracted_root.iterdir():
                            dst = self.target_dir / item.name
                            if item.name in ("config.json", "models", ".venv"):
                                continue
                            if item.name == "dicts" and item.is_dir():
                                _copy_dicts_preserving_extensions(item, dst)
                                continue
                            if dst.exists():
                                if dst.is_dir():
                                    shutil.rmtree(dst)
                                else:
                                    dst.unlink()
                            shutil.move(str(item), str(dst))
                        shutil.rmtree(extract_temp, ignore_errors=True)
                    zip_path.unlink(missing_ok=True)
                    self.log_signal.emit("✓ プログラムファイルの展開が完了しました")
                    if platform.system() != "Windows" and (self.target_dir / "start.sh").exists():
                        (self.target_dir / "start.sh").chmod(0o755)
                    deployed_ok = True
                except Exception as ex:
                    self.log_signal.emit(f"⚠️ ZIP取得失敗 ({ex})。git clone を試行中...")

                if not deployed_ok and shutil.which("git"):
                    try:
                        subprocess.run(
                            ["git", "clone", "https://github.com/Maximilian2022/hayamimi-polyglot.git", str(self.target_dir)],
                            check=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                        self.log_signal.emit("✓ git clone による配置が完了しました")
                    except Exception as g_ex:
                        self.log_signal.emit(f"❌ ファイル取得に失敗しました: {g_ex}")

            # 4. Synchronize Dependencies
            self.log_signal.emit("📦 依存ライブラリを同期中 (PySide6, sherpa-onnx, ctranslate2, sudachipy)...")
            req_file = self.target_dir / "requirements.txt"
            cmd = [uv_exe, "pip", "install", "-r", str(req_file), "--python", str(py_exe), "--upgrade"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                self.log_signal.emit(f"⚠️ パッケージインストール通知: {res.stdout}")
            self.log_signal.emit("✓ 依存ライブラリの同期完了")
            self.progress_signal.emit(55)

            # 5. Populate / Download All Required Models
            models_dir = self.target_dir / "models"
            models_dir.mkdir(parents=True, exist_ok=True)

            # Copy from local script_dir/models if running from an extracted archive
            local_cache = script_dir / "models"
            if local_cache.is_dir() and local_cache.resolve() != models_dir.resolve():
                self.log_signal.emit(f"📦 ローカルモデル ({local_cache}) を確認中...")
                for m in [
                    "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17",
                    "silero_vad.onnx",
                    "mojicast-m2m100-ct2",
                    "mojicast-fugumt-ja-en-ct2",
                    "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
                    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
                ]:
                    src = local_cache / m
                    dst = models_dir / m
                    if src.exists() and not dst.exists():
                        self.log_signal.emit(f"  -> コピー: {m}")
                        if src.is_dir():
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)

            # 5-1. Silero VAD (Required)
            vad_file = models_dir / "silero_vad.onnx"
            if not vad_file.is_file():
                self.log_signal.emit("⬇️ Silero VAD 音声区間検出モデルをダウンロード中...")
                _download_url(
                    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
                    vad_file,
                )
                self.log_signal.emit("✓ Silero VAD 配備完了")

            # 5-2. ReazonSpeech INT8 Zipformer (Required)
            rz_dir = models_dir / "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17"
            if not (rz_dir.is_dir() and (rz_dir / "tokens.txt").is_file()):
                self.log_signal.emit("⬇️ ReazonSpeech 日本語ASRモデル (INT8) をダウンロード中...")
                rz_tar = models_dir / "reazonspeech.tar.bz2"
                _download_url(
                    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17.tar.bz2",
                    rz_tar,
                )
                _safe_extract_tar(rz_tar, models_dir)
                rz_tar.unlink(missing_ok=True)
                self.log_signal.emit("✓ ReazonSpeech 配備完了")

            self.progress_signal.emit(68)

            # 5-3. M2M-100 & FuguMT Translation Models (Required)
            m2m_dir = models_dir / "mojicast-m2m100-ct2"
            m2m_dir.mkdir(parents=True, exist_ok=True)
            for fname in ["model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.model"]:
                dst_f = m2m_dir / fname
                if not dst_f.is_file() or dst_f.stat().st_size == 0:
                    self.log_signal.emit(f"⬇️ 多言語翻訳モデル M2M-100 ({fname}) をダウンロード中...")
                    _download_url(f"https://huggingface.co/ishiki-emo/mojicast-m2m100-ct2/resolve/main/{fname}", dst_f)

            fugu_dir = models_dir / "mojicast-fugumt-ja-en-ct2"
            fugu_dir.mkdir(parents=True, exist_ok=True)
            for fname in ["model.bin", "config.json", "shared_vocabulary.json", "source.spm", "target.spm"]:
                dst_f = fugu_dir / fname
                if not dst_f.is_file() or dst_f.stat().st_size == 0:
                    self.log_signal.emit(f"⬇️ 日英翻訳モデル FuguMT ({fname}) をダウンロード中...")
                    _download_url(f"https://huggingface.co/ishiki-emo/mojicast-fugumt-ja-en-ct2/resolve/main/{fname}", dst_f)

            self.progress_signal.emit(78)

            # 5-4. Parakeet TDT v3 (English & European ASR)
            if self.with_parakeet:
                p_dir_v3 = models_dir / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
                if not (p_dir_v3.is_dir() and (p_dir_v3 / "tokens.txt").is_file()):
                    self.log_signal.emit("⬇️ Parakeet TDT v3 英語・欧州言語ASRモデルをダウンロード中...")
                    p_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
                    tar_path = models_dir / "parakeet.tar.bz2"
                    try:
                        _download_url(p_url, tar_path)
                        _safe_extract_tar(tar_path, models_dir)
                        tar_path.unlink(missing_ok=True)
                        self.log_signal.emit("✓ Parakeet TDT v3 配備完了")
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ Parakeet ダウンロード失敗: {e}")

            # 5-5. SenseVoice Small (Chinese & Korean ASR)
            if self.with_sense_voice:
                sv_dir = models_dir / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
                if not (sv_dir.is_dir() and (sv_dir / "tokens.txt").is_file()):
                    self.log_signal.emit("⬇️ SenseVoice Small 中国語・韓国語ASRモデルをダウンロード中...")
                    sv_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
                    tar_path = models_dir / "sense-voice.tar.bz2"
                    try:
                        _download_url(sv_url, tar_path)
                        _safe_extract_tar(tar_path, models_dir)
                        tar_path.unlink(missing_ok=True)
                        self.log_signal.emit("✓ SenseVoice Small 配備完了")
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ SenseVoice ダウンロード失敗: {e}")

            self.progress_signal.emit(90)

            # 6. Create Desktop Launcher
            desktop = get_desktop_dir()
            self.log_signal.emit(f"🖥️ デスクトップショートカットを作成中... ({desktop})")
            if desktop.exists():
                if platform.system() == "Darwin":
                    shortcut = desktop / "Hayamimi Polyglot.command"
                    shortcut.write_text(f'#!/usr/bin/env bash\ncd "{self.target_dir}"\n./start.sh\n', encoding="utf-8")
                    shortcut.chmod(0o755)
                    self.log_signal.emit(f"✓ macOS ランチャー作成完了: {shortcut}")
                elif platform.system() == "Windows":
                    shortcut_path = desktop / "Hayamimi Polyglot.lnk"
                    target_bat = (self.target_dir / "start.bat").resolve()
                    ps_cmd = (
                        f"$ws = New-Object -ComObject WScript.Shell; "
                        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
                        f"$s.TargetPath = '{target_bat}'; "
                        f"$s.WorkingDirectory = '{self.target_dir.resolve()}'; "
                        f"$s.Description = 'Hayamimi Polyglot - リアルタイム多言語字幕・翻訳ツール'; "
                        f"$s.Save()"
                    )
                    try:
                        subprocess.run(
                            ["powershell", "-NoProfile", "-Command", ps_cmd],
                            check=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                        )
                        self.log_signal.emit(f"✓ Windows ショートカット作成完了: {shortcut_path}")
                    except Exception as ex:
                        self.log_signal.emit(f"⚠️ ショートカット作成エラー: {ex}")

            self.progress_signal.emit(100)
            self.log_signal.emit("=========================================")
            self.log_signal.emit("🎉 セットアップが正常に完了しました。")
            self.log_signal.emit("=========================================")
            self.finished_signal.emit(True, "")

        except Exception as e:
            self.log_signal.emit(f"❌ エラーが発生しました: {e}")
            self.finished_signal.emit(False, str(e))


# ------------------------------------------------------------------------------
# 3. Dark Theme GUI Window
# ------------------------------------------------------------------------------
class InstallerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hayamimi Polyglot - セットアップ ＆ 更新")
        self.resize(640, 740)
        self.setMinimumSize(580, 640)
        self.setup_ui()
        self.apply_theme()
        self.update_path_status()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_layout = QVBoxLayout()
        header_title = QLabel("🎙️🌐 Hayamimi Polyglot")
        header_title.setObjectName("headerTitle")
        header_sub = QLabel("リアルタイム多言語字幕・翻訳ツール (ローカル実行・音声保存なし)")
        header_sub.setObjectName("headerSub")
        header_layout.addWidget(header_title)
        header_layout.addWidget(header_sub)
        layout.addLayout(header_layout)

        # 1. Install Location Group
        group_path = QGroupBox("インストール先フォルダ（アンインストール時はこのフォルダを削除するだけです）")
        group_path_layout = QVBoxLayout(group_path)
        group_path_layout.setContentsMargins(12, 10, 12, 12)

        path_input_layout = QHBoxLayout()
        self.txt_path = QLineEdit(str(get_smart_install_path()))
        self.txt_path.textChanged.connect(self.update_path_status)
        btn_browse = QPushButton("参照...")
        btn_browse.setObjectName("btnBrowse")
        btn_browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_browse.clicked.connect(self.browse_folder)

        path_input_layout.addWidget(self.txt_path)
        path_input_layout.addWidget(btn_browse)
        group_path_layout.addLayout(path_input_layout)

        self.lbl_path_notice = QLabel("💡 クラウド同期（OneDrive / iCloud）を避けたローカルフォルダを自動選択しました")
        self.lbl_path_notice.setObjectName("lblPathNotice")
        group_path_layout.addWidget(self.lbl_path_notice)
        layout.addWidget(group_path)

        # 2. Models & Environment Group
        group_models = QGroupBox("導入する AI モデル構成 & 環境設定")
        group_models_layout = QVBoxLayout(group_models)
        group_models_layout.setContentsMargins(12, 10, 12, 12)
        group_models_layout.setSpacing(6)

        self.chk_clean_venv = QCheckBox("🔄 Python 3.14 仮想環境をクリーン再構築する (推奨)")
        self.chk_clean_venv.setChecked(True)
        self.chk_clean_venv.setObjectName("chkClean")
        lbl_clean_sub = QLabel("  • uv のローカルキャッシュを利用して迅速に仮想環境を整えます")
        lbl_clean_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_clean_venv)
        group_models_layout.addWidget(lbl_clean_sub)

        self.chk_base = QCheckBox("📦 基本モデル構成 (必須・約 800MB)")
        self.chk_base.setChecked(True)
        self.chk_base.setEnabled(False)
        lbl_base_sub = QLabel("  • 日本語 ASR (ReazonSpeech Zipformer) + 音声区間検出 (Silero VAD)\n  • 多言語翻訳 (M2M-100 INT8) + 日英翻訳 (FuguMT)")
        lbl_base_sub.setObjectName("lblSubDisabled")
        group_models_layout.addWidget(self.chk_base)
        group_models_layout.addWidget(lbl_base_sub)

        self.chk_parakeet = QCheckBox("⚡ 英語・欧州言語 ASR (Parakeet TDT v3: 約 640MB)")
        self.chk_parakeet.setChecked(True)
        self.chk_parakeet.setEnabled(True)
        lbl_parakeet_sub = QLabel("  • 英語・フランス語・ドイツ語・スペイン語の音声認識モデル (CPU INT8)")
        lbl_parakeet_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_parakeet)
        group_models_layout.addWidget(lbl_parakeet_sub)

        self.chk_sensevoice = QCheckBox("🚀 中国語・韓国語 ASR (SenseVoice Small: 約 240MB)")
        self.chk_sensevoice.setChecked(True)
        self.chk_sensevoice.setEnabled(True)
        lbl_sv_sub = QLabel("  • 中国語・韓国語に対応する音声認識モデル (CPU INT8)")
        lbl_sv_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_sensevoice)
        group_models_layout.addWidget(lbl_sv_sub)

        layout.addWidget(group_models)

        # 3. Log & Progress Area
        log_layout = QVBoxLayout()
        log_layout.setSpacing(6)

        self.prg_bar = QProgressBar()
        self.prg_bar.setFixedHeight(6)
        self.prg_bar.setTextVisible(False)
        self.prg_bar.setRange(0, 100)
        self.prg_bar.setValue(0)
        log_layout.addWidget(self.prg_bar)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(140)
        self.txt_log.setFont(QFont("Menlo" if platform.system() == "Darwin" else "Consolas", 10))
        log_layout.addWidget(self.txt_log, stretch=1)

        layout.addLayout(log_layout, stretch=1)

        # 4. Bottom Actions
        bottom_layout = QHBoxLayout()
        self.chk_launch = QCheckBox("完了後に今すぐ起動する")
        self.chk_launch.setChecked(True)

        self.btn_install = QPushButton("🚀 セットアップを開始する")
        self.btn_install.setObjectName("btnInstall")
        self.btn_install.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_install.clicked.connect(self.start_installation)

        bottom_layout.addWidget(self.chk_launch)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_install)
        layout.addLayout(bottom_layout)

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0F172A;
            }
            QWidget {
                color: #F8FAFC;
                font-family: 'Segoe UI', 'Meiryo', -apple-system, BlinkMacSystemFont;
            }
            #headerTitle {
                font-size: 20px;
                font-weight: bold;
                color: #38BDF8;
            }
            #headerSub {
                font-size: 12px;
                color: #94A3B8;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 6px;
                margin-top: 10px;
                font-weight: 600;
                color: #94A3B8;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }
            QLineEdit {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 7px;
                font-size: 13px;
                color: #F8FAFC;
            }
            QLineEdit:focus {
                border-color: #38BDF8;
            }
            #btnBrowse {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 7px 16px;
                font-size: 12px;
                font-weight: 600;
                color: #F8FAFC;
            }
            #btnBrowse:hover {
                background-color: #475569;
            }
            #lblPathNotice {
                font-size: 11px;
                color: #34D399;
                margin-top: 4px;
            }
            QCheckBox {
                font-size: 13px;
                color: #E2E8F0;
                spacing: 6px;
            }
            #chkClean {
                color: #38BDF8;
                font-weight: 600;
            }
            #lblSub {
                font-size: 11px;
                color: #94A3B8;
                margin-left: 20px;
                margin-bottom: 2px;
            }
            #lblSubDisabled {
                font-size: 11px;
                color: #64748B;
                margin-left: 20px;
                margin-bottom: 2px;
            }
            QProgressBar {
                background-color: #1E293B;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #38BDF8;
                border-radius: 3px;
            }
            QPlainTextEdit {
                background-color: #020617;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #94A3B8;
                padding: 6px;
            }
            #btnInstall {
                background-color: #10B981;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: bold;
                color: #FFFFFF;
            }
            #btnInstall:hover {
                background-color: #059669;
            }
            #btnInstall:disabled {
                background-color: #334155;
                color: #64748B;
            }
        """)

    def update_path_status(self):
        path = Path(self.txt_path.text().strip())
        if (path / "main.py").exists():
            self.btn_install.setText("🔄 アップデート / モデル確認を開始")
            self.lbl_path_notice.setText("✨ 既存の Hayamimi Polyglot 環境を検出しました（更新・モデル確認モード）")
            self.lbl_path_notice.setStyleSheet("color: #38BDF8;")
        else:
            self.btn_install.setText("🚀 セットアップを開始する")
            self.lbl_path_notice.setText("💡 クラウド同期（OneDrive / iCloud）を避けたローカルフォルダを自動設定しました")
            self.lbl_path_notice.setStyleSheet("color: #34D399;")

    def browse_folder(self):
        initial = self.txt_path.text() if Path(self.txt_path.text()).exists() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "インストール先フォルダを選択", initial)
        if selected:
            self.txt_path.setText(selected)

    def append_log(self, text: str):
        self.txt_log.appendPlainText(text)
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    def start_installation(self):
        target_dir = Path(self.txt_path.text().strip())
        if not target_dir:
            return

        self.btn_install.setEnabled(False)
        self.txt_path.setEnabled(False)
        self.chk_clean_venv.setEnabled(False)
        self.chk_parakeet.setEnabled(False)
        self.chk_sensevoice.setEnabled(False)

        self.worker = InstallWorker(
            target_dir=target_dir,
            clean_venv=self.chk_clean_venv.isChecked(),
            with_parakeet=self.chk_parakeet.isChecked(),
            with_sense_voice=self.chk_sensevoice.isChecked(),
            should_launch=self.chk_launch.isChecked(),
        )
        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.prg_bar.setValue)
        self.worker.finished_signal.connect(self.installation_finished)
        self.worker.start()

    def installation_finished(self, success: bool, error_msg: str):
        if success:
            self.btn_install.setText("✓ 完了")
            self.btn_install.setStyleSheet("background-color: #0284C7; color: white;")
            self.btn_install.setEnabled(True)
            self.btn_install.clicked.disconnect()
            self.btn_install.clicked.connect(self.on_complete_click)
        else:
            self.btn_install.setText("再試行")
            self.btn_install.setEnabled(True)

    def on_complete_click(self):
        target_dir = Path(self.txt_path.text().strip())
        if self.chk_launch.isChecked():
            start_script = target_dir / ("start.bat" if platform.system() == "Windows" else "start.sh")
            if start_script.exists():
                if platform.system() == "Windows":
                    os.startfile(str(start_script))
                else:
                    subprocess.Popen([str(start_script)], cwd=str(target_dir))
        self.close()


def main():
    app = QApplication(sys.argv)
    window = InstallerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
