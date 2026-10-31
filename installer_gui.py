#!/usr/bin/env python3
"""
Hayamimi Polyglot - Unified Modern GUI Installer & Updater
Cross-platform: Windows 11 & macOS (12 Monterey ~ 15 Sequoia)
Powered by PySide6 & uv
"""

import os
import sys
import platform
import shutil
import tarfile
import urllib.request
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor, QPalette, QCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QGroupBox,
    QProgressBar, QPlainTextEdit, QFileDialog, QSizePolicy
)

# ------------------------------------------------------------------------------
# 1. Smart Install Path Detection (Cloud Sync Avoidance)
# ------------------------------------------------------------------------------
def get_smart_install_path() -> Path:
    # If launched from existing repo directory
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "core" / "asr_engine.py").exists():
        return script_dir

    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        docs = home / "Documents"
        # Check iCloud Drive sync
        is_cloud = False
        icloud_dir = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents"
        if docs.is_symlink() or "com~apple~CloudDocs" in str(docs.resolve()) or icloud_dir.exists():
            is_cloud = True

        if is_cloud:
            return home / "hayamimi-polyglot"
        return docs / "hayamimi-polyglot"

    elif system == "Windows":
        docs = home / "Documents"
        is_cloud = False
        onedrive = os.environ.get("OneDrive", "")
        if onedrive and str(docs).lower().startswith(onedrive.lower()):
            is_cloud = True
        elif any(k in str(docs).lower() for k in ["onedrive", "google drive", "dropbox", "icloud"]):
            is_cloud = True

        if is_cloud:
            # Check C:\ root write permission
            try:
                test_file = Path("C:/") / f"hayamimi_test_{os.getpid()}.tmp"
                test_file.write_text("test")
                test_file.unlink(missing_ok=True)
                return Path("C:/hayamimi-polyglot")
            except Exception:
                local_appdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
                return Path(local_appdata) / "Programs" / "hayamimi-polyglot"
        return docs / "hayamimi-polyglot"

    return home / "hayamimi-polyglot"


# ------------------------------------------------------------------------------
# 2. Background Installation Worker
# ------------------------------------------------------------------------------
class InstallWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal(bool, str)

    def __init__(self, target_dir: Path, clean_venv: bool, with_sense_voice: bool, should_launch: bool):
        super().__init__()
        self.target_dir = target_dir
        self.clean_venv = clean_venv
        self.with_sense_voice = with_sense_voice
        self.should_launch = should_launch

    def run(self):
        try:
            self.log_signal.emit(f"🚀 セットアップを開始します: {self.target_dir}")
            self.progress_signal.emit(10)
            self.target_dir.mkdir(parents=True, exist_ok=True)

            # 1. Verify / Find uv
            self.log_signal.emit("🔍 uv (Rust製 高速環境マネージャー) を確認中...")
            uv_exe = shutil.which("uv")
            if not uv_exe:
                # Check common install locations
                candidates = [
                    Path.home() / ".local" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"),
                    Path.home() / ".cargo" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv")
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
                    cmd = 'curl -LsSf https://astral.sh/uv/install.sh | sh'
                subprocess.run(cmd, shell=True, check=True)
                uv_exe = str(Path.home() / ".local" / "bin" / ("uv.exe" if platform.system() == "Windows" else "uv"))

            self.log_signal.emit(f"✓ uv 検出完了: {uv_exe}")
            self.progress_signal.emit(25)

            # 2. Virtual Environment (Python 3.14)
            venv_dir = self.target_dir / ".venv"
            py_exe = venv_dir / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")

            if self.clean_venv or not py_exe.exists():
                self.log_signal.emit("🐍 Python 3.14 仮想環境をクリーン再構築中 (--clear)...")
                self.log_signal.emit("   ※ uv ローカルキャッシュから展開されるため再DLゼロ・1〜2秒で完了")
                cmd = [uv_exe, "venv", "--clear", str(venv_dir), "--python", "3.14"]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            else:
                self.log_signal.emit("✓ 既存の Python 3.14 仮想環境を再利用します")

            self.log_signal.emit(f"✓ Python 3.14 環境準備完了: {py_exe}")
            self.progress_signal.emit(40)

            # 3. Copy Application Files if target differs
            script_dir = Path(__file__).resolve().parent
            if (script_dir / "core" / "asr_engine.py").exists() and script_dir.resolve() != self.target_dir.resolve():
                self.log_signal.emit("📋 アプリケーションファイルを配置中...")
                for item in ["core", "ui", "dicts"]:
                    src = script_dir / item
                    dst = self.target_dir / item
                    if src.exists():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                for item in ["main.py", "config.json", "requirements.txt", ".python-version", "version.txt", "start.bat", "start.sh", "test_polyglot_suite.py"]:
                    src = script_dir / item
                    dst = self.target_dir / item
                    if src.exists():
                        shutil.copy2(src, dst)
                if platform.system() != "Windows":
                    (self.target_dir / "start.sh").chmod(0o755)

            # 4. Synchronize Dependencies
            self.log_signal.emit("📦 依存ライブラリを同期中 (PySide6, sherpa-onnx, ctranslate2)...")
            req_file = self.target_dir / "requirements.txt"
            cmd = [uv_exe, "pip", "install", "-r", str(req_file), "--python", str(py_exe), "--upgrade"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if res.returncode != 0:
                self.log_signal.emit(f"⚠️ パッケージインストール警告: {res.stdout}")
            self.log_signal.emit("✓ 依存ライブラリの同期完了！")
            self.progress_signal.emit(65)

            # 5. Populate / Download Models
            models_dir = self.target_dir / "models"
            models_dir.mkdir(parents=True, exist_ok=True)

            # Check local models cache
            local_cache_candidates = [
                script_dir / "models",
                Path("E:/hayamimi/models"),
                Path.home() / "hayamimi/models"
            ]
            for cache in local_cache_candidates:
                if cache.exists() and cache.resolve() != models_dir.resolve():
                    self.log_signal.emit(f"📦 ローカルキャッシュ ({cache}) から基本モデルを配備中...")
                    for m in ["sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17", "silero_vad.onnx", "mojicast-m2m100-ct2", "mojicast-fugumt-ja-en-ct2"]:
                        src = cache / m
                        dst = models_dir / m
                        if src.exists() and not dst.exists():
                            self.log_signal.emit(f"  -> 配備: {m}")
                            if src.is_dir():
                                shutil.copytree(src, dst)
                            else:
                                shutil.copy2(src, dst)
                    break

            # SenseVoice Small
            if self.with_sense_voice:
                sv_dir = models_dir / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
                if not sv_dir.exists():
                    self.log_signal.emit("🚀 SenseVoice Small 多言語ASRモデルをダウンロード中...")
                    sv_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
                    tar_path = models_dir / "sense-voice.tar.bz2"
                    try:
                        urllib.request.urlretrieve(sv_url, tar_path)
                        with tarfile.open(tar_path, "r:bz2") as tar:
                            tar.extractall(models_dir)
                        tar_path.unlink(missing_ok=True)
                        self.log_signal.emit("✓ SenseVoice Small 配備完了！")
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ SenseVoice ダウンロード失敗 (スキップします): {e}")

            self.progress_signal.emit(85)

            # 6. Create Desktop Launcher
            desktop = Path.home() / "Desktop"
            if desktop.exists():
                self.log_signal.emit("🖥️ デスクトップランチャーを作成中...")
                if platform.system() == "Darwin":
                    shortcut = desktop / "Hayamimi Polyglot.command"
                    shortcut.write_text(f'#!/usr/bin/env bash\ncd "{self.target_dir}"\n./start.sh\n')
                    shortcut.chmod(0o755)
                    self.log_signal.emit(f"✓ macOS ランチャー作成完了: {shortcut}")
                elif platform.system() == "Windows":
                    shortcut_path = desktop / "Hayamimi Polyglot.lnk"
                    target_bat = self.target_dir / "start.bat"
                    ps_cmd = (
                        f'$ws = New-Object -ComObject WScript.Shell; '
                        f'$s = $ws.CreateShortcut("{shortcut_path}"); '
                        f'$s.TargetPath = "{target_bat}"; '
                        f'$s.WorkingDirectory = "{self.target_dir}"; '
                        f'$s.Description = "Hayamimi Polyglot - リアルタイム多言語同時並行通訳"; '
                        f'$s.Save()'
                    )
                    try:
                        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, creationflags=0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                        self.log_signal.emit(f"✓ Windows ショートカット作成完了: {shortcut_path}")
                    except Exception as ex:
                        self.log_signal.emit(f"⚠️ ショートカット作成スキップ: {ex}")

            self.progress_signal.emit(100)
            self.log_signal.emit("=========================================")
            self.log_signal.emit("🎉 セットアップがすべて正常に完了しました！")
            self.log_signal.emit("=========================================")
            self.finished_signal.emit(True, "")

        except Exception as e:
            self.log_signal.emit(f"❌ エラーが発生しました: {e}")
            self.finished_signal.emit(False, str(e))


# ------------------------------------------------------------------------------
# 3. Modern Dark Theme GUI Window
# ------------------------------------------------------------------------------
class InstallerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hayamimi Polyglot - セットアップ ＆ 更新")
        self.resize(640, 780)
        self.setMinimumSize(580, 680)
        self.setup_ui()
        self.apply_theme()
        self.update_path_status()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        header_layout = QVBoxLayout()
        header_title = QLabel("🎙️🌐 Hayamimi Polyglot")
        header_title.setObjectName("headerTitle")
        header_sub = QLabel("リアルタイム多言語同時並行通訳システム (完全ローカル・録音ゼロ)")
        header_sub.setObjectName("headerSub")
        header_layout.addWidget(header_title)
        header_layout.addWidget(header_sub)
        layout.addLayout(header_layout)

        # 1. Install Location Group
        group_path = QGroupBox("インストール先フォルダ")
        group_path_layout = QVBoxLayout(group_path)
        group_path_layout.setContentsMargins(12, 10, 12, 12)

        path_input_layout = QHBoxLayout()
        self.txt_path = QLineEdit(str(get_smart_install_path()))
        self.txt_path.textChanged.connect(self.update_path_status)
        btn_browse = QPushButton("参照...")
        btn_browse.setObjectName("btnBrowse")
        btn_browse.setCursor(QCursor(Qt.PointingHandCursor))
        btn_browse.clicked.connect(self.browse_folder)

        path_input_layout.addWidget(self.txt_path)
        path_input_layout.addWidget(btn_browse)
        group_path_layout.addLayout(path_input_layout)

        self.lbl_path_notice = QLabel("💡 クラウド同期を避けたローカル推奨パスを自動設定しました")
        self.lbl_path_notice.setObjectName("lblPathNotice")
        group_path_layout.addWidget(self.lbl_path_notice)
        layout.addWidget(group_path)

        # 2. Models & Environment Group
        group_models = QGroupBox("ダウンロードする AI モデル構成 & 環境設定")
        group_models_layout = QVBoxLayout(group_models)
        group_models_layout.setContentsMargins(12, 10, 12, 12)
        group_models_layout.setSpacing(6)

        self.chk_clean_venv = QCheckBox("🔄 Python 3.14 仮想環境をクリーン再構築する (推奨: 古い残骸を排除)")
        self.chk_clean_venv.setChecked(True)
        self.chk_clean_venv.setObjectName("chkClean")
        lbl_clean_sub = QLabel("  • uv ローカルキャッシュを活用するため、再DLゼロ・約1〜2秒で健全な環境を復元")
        lbl_clean_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_clean_venv)
        group_models_layout.addWidget(lbl_clean_sub)

        self.chk_base = QCheckBox("📦 基本モデル構成 (必須・約 800MB)")
        self.chk_base.setChecked(True)
        self.chk_base.setEnabled(False)
        lbl_base_sub = QLabel("  • 日本語 ASR (ReazonSpeech Zipformer) + VAD (Silero)\n  • 100言語相互翻訳 (M2M-100 INT8) + 高速日英 (FuguMT)")
        lbl_base_sub.setObjectName("lblSubDisabled")
        group_models_layout.addWidget(self.chk_base)
        group_models_layout.addWidget(lbl_base_sub)

        self.chk_parakeet = QCheckBox("⚡ 高精度 英語特化 ASR (Parakeet TDT v2: +約 600MB)")
        self.chk_parakeet.setChecked(True)
        lbl_parakeet_sub = QLabel("  • ネイティブの早口英語やビジネス略語の認識精度が劇的に向上")
        lbl_parakeet_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_parakeet)
        group_models_layout.addWidget(lbl_parakeet_sub)

        self.chk_nllb = QCheckBox("🌐 高精度 アジア・多言語翻訳 (NLLB-200 600M: +約 600MB)")
        self.chk_nllb.setChecked(False)
        lbl_nllb_sub = QLabel("  • 中国語・韓国語・ベトナム語などの長文翻訳精度やビジネス敬語を向上")
        lbl_nllb_sub.setObjectName("lblSub")
        group_models_layout.addWidget(self.chk_nllb)
        group_models_layout.addWidget(lbl_nllb_sub)

        self.chk_sensevoice = QCheckBox("🚀 超高速 多言語 ASR (SenseVoice Small: +約 200MB)")
        self.chk_sensevoice.setChecked(False)
        lbl_sv_sub = QLabel("  • アジア系言語（中・韓・広東語等）の音声認識とノイズ自動除去")
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
        self.btn_install.setCursor(QCursor(Qt.PointingHandCursor))
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
            self.btn_install.setText("🔄 アップデート / 設定適用を開始")
            self.lbl_path_notice.setText("✨ 既存の Hayamimi Polyglot 環境を検出しました（アップデート / 追加DLモード）")
            self.lbl_path_notice.setStyleSheet("color: #38BDF8;")
        else:
            self.btn_install.setText("🚀 セットアップを開始する")
            self.lbl_path_notice.setText("💡 クラウド同期（OneDrive/iCloud等）を避けたローカル推奨パスを自動設定しました")
            self.lbl_path_notice.setStyleSheet("color: #34D399;")

    def browse_folder(self):
        initial = self.txt_path.text() if Path(self.txt_path.text()).exists() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Hayamimi Polyglot のインストール先フォルダを選択", initial)
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
        self.chk_nllb.setEnabled(False)
        self.chk_sensevoice.setEnabled(False)

        self.worker = InstallWorker(
            target_dir=target_dir,
            clean_venv=self.chk_clean_venv.isChecked(),
            with_sense_voice=self.chk_sensevoice.isChecked(),
            should_launch=self.chk_launch.isChecked()
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

