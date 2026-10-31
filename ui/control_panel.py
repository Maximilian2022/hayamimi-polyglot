"""
Hayamimi For Business - Hybrid Control Panel (System Tray + Mini Popup + Floating).
Features:
  - System Tray Resident + Mini Popup
  - Pin button (📌) to detach into a small floating panel
  - One-click Start / Stop meeting
  - Audio source selection (Mic + Zoom/Teams/Speaker)
  - Translation mode (ja->en, en->ja, OFF)
  - Instant Hotwords input (Paste meeting agenda)
  - Stealth Mode toggle (Default: ON / hidden from screen share)
  - Click-through toggle for overlay
  - Quick open browser view (127.0.0.1:8844/view)
  - Quick copy transcript to clipboard
"""

from __future__ import annotations

import os
import platform
import webbrowser
from typing import Callable, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPoint, Signal

try:
    from .overlay_window import OverlayWindow, set_stealth_mode
    from core.audio.win_loopback import list_audio_processes, AudioProcess
except Exception:
    from ui.overlay_window import OverlayWindow, set_stealth_mode
    from core.audio.win_loopback import list_audio_processes, AudioProcess


class ControlPanel(QtWidgets.QWidget):
    """
    Main Business Control Panel.
    Can run as a floating window or attach to the system tray.
    """

    start_requested = Signal()
    stop_requested = Signal()
    config_changed = Signal(dict)
    hotwords_submitted = Signal(str)

    def __init__(self, overlay: OverlayWindow, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.is_pinned = False
        self.is_running = False
        self.meeting_lines: List[str] = []

        self._drag_pos = QPoint()

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Hayamimi Business - コントロールパネル")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: #94A3B8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                color: #F8FAFC;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton#btnStart {
                background-color: #10B981;
                border: none;
                color: white;
                font-size: 14px;
                padding: 10px;
            }
            QPushButton#btnStart:hover {
                background-color: #059669;
            }
            QPushButton#btnStop {
                background-color: #EF4444;
                border: none;
                color: white;
                font-size: 14px;
                padding: 10px;
            }
            QPushButton#btnStop:hover {
                background-color: #DC2626;
            }
            QComboBox, QLineEdit, QTextEdit {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px;
                color: #F8FAFC;
            }
            QComboBox::drop-down {
                border: none;
            }
            QCheckBox {
                color: #E2E8F0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:checked {
                background-color: #3B82F6;
                border-color: #3B82F6;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 1. Header (Title + Pin + Stealth Status)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("🎙️ Hayamimi Business")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38BDF8;")
        header.addWidget(title)

        header.addStretch()

        self.btn_pin = QtWidgets.QPushButton("📌 常に表示")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        self.btn_pin.toggled.connect(self.on_pin_toggled)
        header.addWidget(self.btn_pin)

        layout.addLayout(header)

        # 2. Main Start/Stop Action Button
        self.btn_action = QtWidgets.QPushButton("▶ 会議の聞き取り・翻訳を開始")
        self.btn_action.setObjectName("btnStart")
        self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_action.clicked.connect(self.toggle_meeting)
        layout.addWidget(self.btn_action)

        # 3. Audio & Translation Settings Group
        grp_settings = QtWidgets.QGroupBox("音声 & 翻訳設定")
        settings_layout = QtWidgets.QVBoxLayout(grp_settings)
        settings_layout.setSpacing(8)

        # Remote App Selection (Zoom/Teams/Speaker)
        row_app = QtWidgets.QHBoxLayout()
        row_app.addWidget(QtWidgets.QLabel("相手の音声:"))
        self.combo_app = QtWidgets.QComboBox()
        self.combo_app.addItem("スピーカー全体 (Default Loopback)", 0)
        self.populate_audio_processes()
        row_app.addWidget(self.combo_app, 1)

        btn_refresh_apps = QtWidgets.QPushButton("🔄")
        btn_refresh_apps.setToolTip("起動中アプリ一覧を再読込")
        btn_refresh_apps.clicked.connect(self.populate_audio_processes)
        row_app.addWidget(btn_refresh_apps)
        settings_layout.addLayout(row_app)

        # Multicast Translation Languages (Max 5)
        trans_header = QtWidgets.QHBoxLayout()
        lbl_trans_title = QtWidgets.QLabel("🌐 同時通訳対象言語 (相互マルチキャスト):")
        lbl_trans_title.setStyleSheet("font-weight: bold;")
        trans_header.addWidget(lbl_trans_title)
        self.lbl_lang_count = QtWidgets.QLabel("選択中: 2 / 5 言語")
        self.lbl_lang_count.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 11px;")
        trans_header.addWidget(self.lbl_lang_count)
        trans_header.addStretch()
        settings_layout.addLayout(trans_header)

        # Languages Grid (Pill-style checkboxes)
        self.lang_checkboxes = {}
        grid_lang = QtWidgets.QGridLayout()
        grid_lang.setSpacing(6)

        available_langs = [
            ("ja", "日本語 🇯🇵"),
            ("en", "英語 🇺🇸"),
            ("zh", "中国語 🇨🇳"),
            ("ko", "韓国語 🇰🇷"),
            ("fr", "仏語 🇫🇷"),
            ("de", "独語 🇩🇪"),
            ("es", "西語 🇪🇸"),
            ("vi", "越語 🇻🇳"),
        ]

        for i, (code, name) in enumerate(available_langs):
            chk = QtWidgets.QCheckBox(name)
            chk.setProperty("lang_code", code)
            if code in ("ja", "en"):
                chk.setChecked(True)
            chk.toggled.connect(self.on_language_toggled)
            self.lang_checkboxes[code] = chk
            grid_lang.addWidget(chk, i // 4, i % 4)

        settings_layout.addLayout(grid_lang)

        layout.addWidget(grp_settings)

        # 4. Instant Hotwords (Meeting Agenda)
        grp_agenda = QtWidgets.QGroupBox("📋 Instant Hotwords (アジェンダ・資料キーワード)")
        agenda_layout = QtWidgets.QVBoxLayout(grp_agenda)
        agenda_layout.setSpacing(6)

        self.txt_agenda = QtWidgets.QTextEdit()
        self.txt_agenda.setPlaceholderText("会議のアジェンダ、スライドのテキスト、出席者氏名をここに貼り付けると、専門用語を即時ブースト認識します...")
        self.txt_agenda.setMaximumHeight(70)
        agenda_layout.addWidget(self.txt_agenda)

        btn_apply_hotwords = QtWidgets.QPushButton("⚡ アジェンダから辞書を即時反映")
        btn_apply_hotwords.clicked.connect(self.apply_hotwords)
        agenda_layout.addWidget(btn_apply_hotwords)

        layout.addWidget(grp_agenda)

        # 5. Display & Security Settings
        grp_display = QtWidgets.QGroupBox("画面共有 & 表示セキュリティ")
        disp_layout = QtWidgets.QVBoxLayout(grp_display)
        disp_layout.setSpacing(8)

        # Stealth Mode Toggle
        self.chk_stealth = QtWidgets.QCheckBox("🛡️ 画面共有から字幕を隠す (ステルス保護)")
        self.chk_stealth.setChecked(True)  # Default: ON
        self.chk_stealth.toggled.connect(self.on_stealth_toggled)
        disp_layout.addWidget(self.chk_stealth)

        # Click-through toggle
        self.chk_clickthrough = QtWidgets.QCheckBox("🖱️ 字幕をマウス透過する (操作を妨げない)")
        self.chk_clickthrough.setChecked(False)
        self.chk_clickthrough.toggled.connect(self.on_clickthrough_toggled)
        disp_layout.addWidget(self.chk_clickthrough)

        # View buttons
        row_views = QtWidgets.QHBoxLayout()
        btn_toggle_overlay = QtWidgets.QPushButton("👁 字幕オーバーレイ切替")
        btn_toggle_overlay.clicked.connect(self.toggle_overlay)
        row_views.addWidget(btn_toggle_overlay)

        btn_open_browser = QtWidgets.QPushButton("🌐 ブラウザ共有画面を開く")
        btn_open_browser.clicked.connect(self.open_browser_view)
        row_views.addWidget(btn_open_browser)
        disp_layout.addLayout(row_views)

        layout.addWidget(grp_display)

        # 6. Bottom Actions (Copy Transcript)
        bottom_layout = QtWidgets.QHBoxLayout()
        self.lbl_status = QtWidgets.QLabel("待機中 (完全オフライン)")
        self.lbl_status.setStyleSheet("color: #64748B; font-size: 12px;")
        bottom_layout.addWidget(self.lbl_status)
        bottom_layout.addStretch()

        btn_copy = QtWidgets.QPushButton("📋 議事録テキストをコピー")
        btn_copy.clicked.connect(self.copy_transcript)
        bottom_layout.addWidget(btn_copy)

        layout.addLayout(bottom_layout)

        self.resize(440, 520)

    def populate_audio_processes(self):
        """Scan active audio sessions."""
        current_text = self.combo_app.currentText()
        self.combo_app.clear()
        self.combo_app.addItem("スピーカー全体 (Default Loopback)", 0)

        procs = list_audio_processes()
        for p in procs:
            label = f"{p.name} (PID: {p.pid})"
            self.combo_app.addItem(label, p.pid)

        # Prioritize Zoom or Teams if present
        for i in range(self.combo_app.count()):
            text = self.combo_app.itemText(i).lower()
            if "zoom" in text or "teams" in text or "slack" in text:
                self.combo_app.setCurrentIndex(i)
                break

    def on_pin_toggled(self, checked: bool):
        self.is_pinned = checked
        if checked:
            self.btn_pin.setText("📌 固定中")
            self.btn_pin.setStyleSheet("font-size: 11px; padding: 4px 8px; background-color: #3B82F6;")
        else:
            self.btn_pin.setText("📌 常に表示")
            self.btn_pin.setStyleSheet("font-size: 11px; padding: 4px 8px;")

    def on_stealth_toggled(self, checked: bool):
        self.overlay.apply_stealth(checked)
        # Also apply stealth to control panel if on Windows
        set_stealth_mode(int(self.winId()), checked)

    def on_clickthrough_toggled(self, checked: bool):
        self.overlay.set_click_through_mode(checked)

    def toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()

    def open_browser_view(self):
        webbrowser.open("http://127.0.0.1:8844/view")

    def toggle_meeting(self):
        if not self.is_running:
            self.is_running = True
            self.btn_action.setText("■ 会議を終了する")
            self.btn_action.setObjectName("btnStop")
            self.btn_action.setStyle(self.btn_action.style())
            self.lbl_status.setText("● 聞き取り・翻訳中")
            self.lbl_status.setStyleSheet("color: #10B981; font-weight: bold;")
            self.overlay.show()
            self.start_requested.emit()
        else:
            self.is_running = False
            self.btn_action.setText("▶ 会議の聞き取り・翻訳を開始")
            self.btn_action.setObjectName("btnStart")
            self.btn_action.setStyle(self.btn_action.style())
            self.lbl_status.setText("待機中 (完全オフライン)")
            self.lbl_status.setStyleSheet("color: #64748B;")
            self.stop_requested.emit()

    def apply_hotwords(self):
        text = self.txt_agenda.toPlainText().strip()
        if text:
            self.hotwords_submitted.emit(text)
            QtWidgets.QMessageBox.information(self, "Hotwords 適用", "アジェンダから専門用語・キーワードを抽出して反映しました！")

    def copy_transcript(self):
        if not self.meeting_lines:
            QtWidgets.QMessageBox.information(self, "議事録コピー", "コピーできる会議テキストがありません。")
            return
        clipboard = QtGui.QGuiApplication.clipboard()
        clipboard.setText("\n\n".join(self.meeting_lines))
        QtWidgets.QMessageBox.information(self, "議事録コピー", "クリップボードに議事録テキストをコピーしました！")

    def on_language_toggled(self):
        selected = self.get_selected_languages()
        count = len(selected)
        self.lbl_lang_count.setText(f"選択中: {count} / 5 言語")

        # Max 5 selection guard: disable unselected checkboxes when count >= 5
        for code, chk in self.lang_checkboxes.items():
            if not chk.isChecked():
                chk.setEnabled(count < 5)
            else:
                chk.setEnabled(True)

    def get_selected_languages(self) -> List[str]:
        return [code for code, chk in self.lang_checkboxes.items() if chk.isChecked()]

    def append_transcript_line(self, track: str, text: str, translations: Optional[Dict[str, str] | str] = None):
        tag = "自分" if track == "self" else "相手"
        line = f"[{tag}] {text}"
        if isinstance(translations, dict):
            for lang, trans_text in translations.items():
                if trans_text:
                    line += f"\n↳ [{lang.upper()}] {trans_text}"
        elif isinstance(translations, str) and translations:
            line += f"\n↳ {translations}"
        self.meeting_lines.append(line)


class SystemTrayApp:
    """Manages system tray icon and popup behavior."""

    def __init__(self, panel: ControlPanel):
        self.panel = panel
        self.tray = QtWidgets.QSystemTrayIcon(panel)

        # Standard icon or fallback
        icon = panel.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaVolume)
        self.tray.setIcon(icon)
        self.tray.setToolTip("Hayamimi Business - 会議文字起こし & 翻訳")

        # Tray menu
        menu = QtWidgets.QMenu()
        act_open = menu.addAction("パネルを開く")
        act_open.triggered.connect(self.show_panel)

        act_toggle = menu.addAction("会議の開始 / 終了")
        act_toggle.triggered.connect(self.panel.toggle_meeting)

        menu.addSeparator()
        act_quit = menu.addAction("終了")
        act_quit.triggered.connect(QtWidgets.QApplication.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason in (QtWidgets.QSystemTrayIcon.ActivationReason.Trigger, QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel()

    def show_panel(self):
        if self.panel.isVisible() and not self.panel.is_pinned:
            self.panel.hide()
        else:
            self.panel.show()
            self.panel.raise_()
            self.panel.activateWindow()
