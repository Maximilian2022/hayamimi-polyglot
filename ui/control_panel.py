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

import json
import os
import platform
import webbrowser
from pathlib import Path
from typing import Callable, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPoint, Signal

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_CONFIG_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.default.json"

try:
    from .overlay_window import OverlayWindow, set_stealth_mode, DEFAULT_COLORS
    from core.audio.win_loopback import list_audio_processes, AudioProcess
except Exception:
    from ui.overlay_window import OverlayWindow, set_stealth_mode, DEFAULT_COLORS
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
    high_accuracy_toggled = Signal(bool)

    def __init__(self, overlay: OverlayWindow, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.is_pinned = False
        self.is_running = False
        self.meeting_lines: List[str] = []

        self._drag_pos = QPoint()

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Hayamimi Polyglot - コントロールパネル")
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
                padding: 5px 8px;
                color: #F8FAFC;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #334155;
            }
            QComboBox::down-arrow {
                image: none;
                border-top: 5px solid #94A3B8;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                width: 0;
                height: 0;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #F8FAFC;
                selection-background-color: #3B82F6;
                selection-color: #FFFFFF;
                border: 1px solid #334155;
                outline: none;
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
            QSlider::groove:horizontal {
                height: 6px;
                background: #334155;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38BDF8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #F8FAFC;
                border: 1px solid #38BDF8;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 1. Header (Title + Pin + Stealth Status)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("🎙️🌐 Hayamimi Polyglot")
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

        # Self Microphone Selection
        row_mic = QtWidgets.QHBoxLayout()
        row_mic.addWidget(QtWidgets.QLabel("自分のマイク:"))
        self.combo_mic = QtWidgets.QComboBox()
        self.combo_mic.addItem("システム既定のマイク (Default)", None)
        row_mic.addWidget(self.combo_mic, 1)

        btn_refresh_mics = QtWidgets.QPushButton("🔄")
        btn_refresh_mics.setToolTip("接続マイク一覧を再読込")
        btn_refresh_mics.clicked.connect(self.populate_microphones)
        row_mic.addWidget(btn_refresh_mics)
        settings_layout.addLayout(row_mic)

        # Remote App Selection (Zoom/Teams/Speaker)
        row_app = QtWidgets.QHBoxLayout()
        row_app.addWidget(QtWidgets.QLabel("相手の音声:"))
        self.combo_app = QtWidgets.QComboBox()
        self.combo_app.addItem("スピーカー全体 (Default Loopback)", 0)
        self.populate_audio_processes()
        self.populate_microphones()
        row_app.addWidget(self.combo_app, 1)

        btn_refresh_apps = QtWidgets.QPushButton("🔄")
        btn_refresh_apps.setToolTip("起動中アプリ一覧を再読込")
        btn_refresh_apps.clicked.connect(self.populate_audio_processes)
        row_app.addWidget(btn_refresh_apps)
        settings_layout.addLayout(row_app)

        # High Accuracy ASR Mode Toggle
        row_asr = QtWidgets.QHBoxLayout()
        self.chk_high_acc = QtWidgets.QCheckBox("⚡ 高精度 ASR モード (英語: Parakeet TDT / 多言語: SenseVoice)")
        self.chk_high_acc.setChecked(True)
        self.chk_high_acc.setStyleSheet("color: #38BDF8; font-weight: bold;")
        self.chk_high_acc.setToolTip("【推奨: デフォルトON】\n英語は世界最高水準の Parakeet TDT v2 で、他言語は SenseVoice Small で超高精度デコードします。\nOFF にすると軽量な ReazonSpeech のみで動作します。")
        self.chk_high_acc.toggled.connect(self.on_high_accuracy_toggled)
        row_asr.addWidget(self.chk_high_acc)
        settings_layout.addLayout(row_asr)

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

        # 4.5 Subtitle Appearance Customization (Font, Size, Area)
        grp_sub_custom = QtWidgets.QGroupBox("🎨 字幕カスタマイズ (フォント・文字サイズ・エリア)")
        custom_layout = QtWidgets.QVBoxLayout(grp_sub_custom)
        custom_layout.setSpacing(6)

        # Font selection (Pure Dropdown)
        row_font = QtWidgets.QHBoxLayout()
        row_font.addWidget(QtWidgets.QLabel("フォント:"))
        self.combo_font = QtWidgets.QComboBox()
        self.combo_font.setEditable(False)
        self.combo_font.setMaxVisibleItems(16)
        self.combo_font.addItem("システム標準 (Meiryo / Yu Gothic)", "")
        self.populate_fonts()
        self.combo_font.currentTextChanged.connect(self.on_font_changed)
        row_font.addWidget(self.combo_font, 1)
        custom_layout.addLayout(row_font)

        # Font Size slider
        row_font_size = QtWidgets.QHBoxLayout()
        row_font_size.addWidget(QtWidgets.QLabel("文字サイズ:"))
        self.slider_font_size = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_font_size.setRange(12, 38)
        self.slider_font_size.setValue(18)
        self.lbl_font_size_val = QtWidgets.QLabel("18px")
        self.lbl_font_size_val.setStyleSheet("color: #38BDF8; font-weight: bold; min-width: 42px;")
        self.slider_font_size.valueChanged.connect(self.on_font_size_changed)
        row_font_size.addWidget(self.slider_font_size, 1)
        row_font_size.addWidget(self.lbl_font_size_val)
        custom_layout.addLayout(row_font_size)

        # Area Size (Presets + Sliders)
        row_area = QtWidgets.QHBoxLayout()
        row_area.addWidget(QtWidgets.QLabel("エリア:"))

        btn_preset_std = QtWidgets.QPushButton("標準")
        btn_preset_std.setStyleSheet("font-size: 11px; padding: 2px 8px; background-color: #334155;")
        btn_preset_std.clicked.connect(lambda: self.apply_area_preset(840, 190))
        row_area.addWidget(btn_preset_std)

        btn_preset_wide = QtWidgets.QPushButton("ワイド")
        btn_preset_wide.setStyleSheet("font-size: 11px; padding: 2px 8px; background-color: #334155;")
        btn_preset_wide.clicked.connect(lambda: self.apply_area_preset(1150, 220))
        row_area.addWidget(btn_preset_wide)

        btn_preset_compact = QtWidgets.QPushButton("コンパクト")
        btn_preset_compact.setStyleSheet("font-size: 11px; padding: 2px 8px; background-color: #334155;")
        btn_preset_compact.clicked.connect(lambda: self.apply_area_preset(650, 140))
        row_area.addWidget(btn_preset_compact)

        custom_layout.addLayout(row_area)

        # Width & Height Sliders
        row_wh = QtWidgets.QHBoxLayout()
        row_wh.addWidget(QtWidgets.QLabel("幅:"))
        self.slider_width = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_width.setRange(500, 1600)
        self.slider_width.setValue(840)
        self.lbl_width_val = QtWidgets.QLabel("840px")
        self.lbl_width_val.setStyleSheet("color: #94A3B8; font-size: 11px; min-width: 44px;")
        self.slider_width.valueChanged.connect(self.on_area_size_changed)
        row_wh.addWidget(self.slider_width, 1)
        row_wh.addWidget(self.lbl_width_val)

        row_wh.addWidget(QtWidgets.QLabel("高:"))
        self.slider_height = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_height.setRange(120, 500)
        self.slider_height.setValue(190)
        self.lbl_height_val = QtWidgets.QLabel("190px")
        self.lbl_height_val.setStyleSheet("color: #94A3B8; font-size: 11px; min-width: 44px;")
        self.slider_height.valueChanged.connect(self.on_area_size_changed)
        row_wh.addWidget(self.slider_height, 1)
        row_wh.addWidget(self.lbl_height_val)
        custom_layout.addLayout(row_wh)

        # Background Opacity
        row_op = QtWidgets.QHBoxLayout()
        row_op.addWidget(QtWidgets.QLabel("背景の濃さ:"))
        self.slider_opacity = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(20, 100)
        self.slider_opacity.setValue(82)
        self.lbl_opacity_val = QtWidgets.QLabel("82%")
        self.lbl_opacity_val.setStyleSheet("color: #38BDF8; font-weight: bold; min-width: 38px;")
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        row_op.addWidget(self.slider_opacity, 1)
        row_op.addWidget(self.lbl_opacity_val)
        custom_layout.addLayout(row_op)

        # Colors: Speaker & Translation Languages
        row_colors_title = QtWidgets.QHBoxLayout()
        row_colors_title.addWidget(QtWidgets.QLabel("🎨 文字色 (メイン言語・翻訳言語別):"))
        btn_reset_colors = QtWidgets.QPushButton("🔄 標準色に戻す")
        btn_reset_colors.setStyleSheet("font-size: 10px; padding: 2px 6px; background-color: #334155;")
        btn_reset_colors.clicked.connect(self.reset_colors)
        row_colors_title.addWidget(btn_reset_colors)
        row_colors_title.addStretch()
        custom_layout.addLayout(row_colors_title)

        # Primary Speaker colors (Self / Remote / Text)
        self.color_btns = {}
        row_spk_colors = QtWidgets.QHBoxLayout()
        row_spk_colors.addWidget(QtWidgets.QLabel("発言者:"))
        for key, label in [("self_tag", "自分"), ("remote_tag", "相手"), ("orig_text", "本文")]:
            lbl = QtWidgets.QLabel(f"{label}:")
            lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
            row_spk_colors.addWidget(lbl)
            btn = self._create_color_button(key)
            self.color_btns[key] = btn
            row_spk_colors.addWidget(btn)
        row_spk_colors.addStretch()
        custom_layout.addLayout(row_spk_colors)

        # Translation Language colors
        row_trans_colors = QtWidgets.QHBoxLayout()
        row_trans_colors.addWidget(QtWidgets.QLabel("翻訳言語:"))
        for lang_code, lang_label in [("ja", "日"), ("en", "米"), ("zh", "中"), ("ko", "韓"), ("fr", "仏"), ("de", "独"), ("es", "西"), ("vi", "越")]:
            lbl = QtWidgets.QLabel(f"{lang_label}:")
            lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
            row_trans_colors.addWidget(lbl)
            btn = self._create_color_button(lang_code)
            self.color_btns[lang_code] = btn
            row_trans_colors.addWidget(btn)
        row_trans_colors.addStretch()
        custom_layout.addLayout(row_trans_colors)

        layout.addWidget(grp_sub_custom)

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

        # 6. Bottom Actions (Copy Transcript & Updater)
        bottom_layout = QtWidgets.QHBoxLayout()
        self.lbl_status = QtWidgets.QLabel("待機中 (完全オフライン)")
        self.lbl_status.setStyleSheet("color: #64748B; font-size: 12px;")
        bottom_layout.addWidget(self.lbl_status)
        bottom_layout.addStretch()

        self.btn_update = QtWidgets.QPushButton("⚙️ モデル追加/更新")
        self.btn_update.setStyleSheet("font-size: 11px; padding: 4px 8px; background-color: #334155;")
        self.btn_update.setToolTip("追加AIモデルのダウンロードやアップデートを実行します")
        self.btn_update.clicked.connect(self.open_updater)
        bottom_layout.addWidget(self.btn_update)

        btn_copy = QtWidgets.QPushButton("📋 議事録コピー")
        btn_copy.clicked.connect(self.copy_transcript)
        bottom_layout.addWidget(btn_copy)

        layout.addLayout(bottom_layout)

        self.resize(480, 680)
        self.load_settings()

        # Check for updates in background (non-blocking)
        QtCore.QTimer.singleShot(1500, self.check_for_updates)

    def populate_fonts(self):
        """Scan local system fonts and populate dropdown."""
        try:
            fonts = QtGui.QFontDatabase.families()
            favs = ["Meiryo", "Yu Gothic UI", "BIZ UDPGothic", "Segoe UI", "Arial", "Noto Sans JP"]
            for f in favs:
                if f in fonts:
                    self.combo_font.addItem(f, f)
            for f in sorted(fonts):
                if f not in favs:
                    self.combo_font.addItem(f, f)
        except Exception as ex:
            print(f"[UI] Error listing fonts: {ex}")

    def on_font_changed(self, font_name: str):
        if font_name.startswith("システム標準"):
            self.overlay.set_font_family("")
        else:
            self.overlay.set_font_family(font_name)
        self.save_settings()

    def on_font_size_changed(self, size: int):
        self.lbl_font_size_val.setText(f"{size}px")
        self.overlay.set_font_size(size)
        self.save_settings()

    def apply_area_preset(self, w: int, h: int):
        self.slider_width.blockSignals(True)
        self.slider_height.blockSignals(True)
        self.slider_width.setValue(w)
        self.slider_height.setValue(h)
        self.slider_width.blockSignals(False)
        self.slider_height.blockSignals(False)
        self.lbl_width_val.setText(f"{w}px")
        self.lbl_height_val.setText(f"{h}px")
        self.overlay.set_overlay_size(w, h)
        self.save_settings()

    def on_area_size_changed(self):
        w = self.slider_width.value()
        h = self.slider_height.value()
        self.lbl_width_val.setText(f"{w}px")
        self.lbl_height_val.setText(f"{h}px")
        self.overlay.set_overlay_size(w, h)
        self.save_settings()

    def _create_color_button(self, color_key: str) -> QtWidgets.QPushButton:
        initial_hex = self.overlay.colors.get(color_key, "#FFFFFF")
        btn = QtWidgets.QPushButton()
        btn.setFixedSize(22, 18)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(f"クリックして色を変更: {color_key}")
        btn.setStyleSheet(f"background-color: {initial_hex}; border: 1px solid #64748B; border-radius: 3px;")

        def on_click():
            curr = self.overlay.colors.get(color_key, "#FFFFFF")
            color = QtWidgets.QColorDialog.getColor(QtGui.QColor(curr), self, f"文字色を選択 ({color_key})")
            if color.isValid():
                hex_str = color.name()
                btn.setStyleSheet(f"background-color: {hex_str}; border: 1px solid #FFFFFF; border-radius: 3px;")
                self.overlay.set_color(color_key, hex_str)
                self.save_settings()

        btn.clicked.connect(on_click)
        return btn

    def reset_colors(self):
        for key, hex_val in DEFAULT_COLORS.items():
            self.overlay.colors[key] = hex_val
            if key in self.color_btns:
                self.color_btns[key].setStyleSheet(f"background-color: {hex_val}; border: 1px solid #64748B; border-radius: 3px;")
        self.overlay.refresh_display()
        self.save_settings()

    def on_opacity_changed(self, val: int):
        self.lbl_opacity_val.setText(f"{val}%")
        self.overlay.set_bg_opacity(val / 100.0)
        self.save_settings()

    def load_settings(self):
        """Load persistent settings from config.json (falls back to config.default.json)."""
        target_path = _CONFIG_PATH if _CONFIG_PATH.exists() else _CONFIG_DEFAULT_PATH
        if not target_path.exists():
            return
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ui_cfg = cfg.get("ui", {})
            font_fam = ui_cfg.get("font_family", "")
            if font_fam:
                idx = self.combo_font.findText(font_fam)
                if idx >= 0:
                    self.combo_font.setCurrentIndex(idx)
                else:
                    self.combo_font.setCurrentText(font_fam)
                self.overlay.set_font_family(font_fam)

            font_sz = ui_cfg.get("font_size", 18)
            self.slider_font_size.setValue(int(font_sz))
            self.lbl_font_size_val.setText(f"{font_sz}px")
            self.overlay.set_font_size(int(font_sz))

            ow = ui_cfg.get("overlay_width", 840)
            oh = ui_cfg.get("overlay_height", 190)
            self.slider_width.setValue(int(ow))
            self.slider_height.setValue(int(oh))
            self.lbl_width_val.setText(f"{ow}px")
            self.lbl_height_val.setText(f"{oh}px")
            self.overlay.set_overlay_size(int(ow), int(oh))

            opac = ui_cfg.get("overlay_opacity", 0.82)
            opac_pct = int(opac * 100) if opac <= 1.0 else int(opac)
            self.slider_opacity.setValue(opac_pct)
            self.lbl_opacity_val.setText(f"{opac_pct}%")
            self.overlay.set_bg_opacity(opac_pct / 100.0)

            # Saved colors
            saved_colors = ui_cfg.get("colors", {})
            if isinstance(saved_colors, dict):
                for k, v in saved_colors.items():
                    self.overlay.colors[k] = v
                    if k in self.color_btns:
                        self.color_btns[k].setStyleSheet(f"background-color: {v}; border: 1px solid #64748B; border-radius: 3px;")
                self.overlay.refresh_display()

            # Saved microphone
            saved_mic = cfg.get("audio", {}).get("selected_mic_name")
            if saved_mic:
                for i in range(self.combo_mic.count()):
                    if self.combo_mic.itemText(i) == saved_mic:
                        self.combo_mic.setCurrentIndex(i)
                        break

            # Saved languages
            saved_langs = cfg.get("audio", {}).get("selected_languages")
            if saved_langs and isinstance(saved_langs, list):
                for chk in self.lang_checkboxes.values():
                    code = chk.property("lang_code")
                    chk.setChecked(code in saved_langs)

            # Saved High Accuracy Mode
            high_acc = cfg.get("asr", {}).get("high_accuracy_mode", True)
            self.chk_high_acc.setChecked(bool(high_acc))
        except Exception as e:
            print(f"[Config] Error loading settings: {e}")

    def save_settings(self):
        """Save settings to config.json."""
        try:
            cfg = {}
            if _CONFIG_PATH.exists():
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

            ui_cfg = cfg.setdefault("ui", {})
            curr_text = self.combo_font.currentText()
            ui_cfg["font_family"] = curr_text if not curr_text.startswith("システム標準") else ""
            ui_cfg["font_size"] = self.slider_font_size.value()
            ui_cfg["overlay_width"] = self.slider_width.value()
            ui_cfg["overlay_height"] = self.slider_height.value()
            ui_cfg["overlay_opacity"] = self.slider_opacity.value() / 100.0
            ui_cfg["colors"] = dict(self.overlay.colors)

            audio_cfg = cfg.setdefault("audio", {})
            audio_cfg["selected_mic_name"] = self.combo_mic.currentText()
            audio_cfg["selected_languages"] = self.get_selected_languages()

            asr_cfg = cfg.setdefault("asr", {})
            asr_cfg["high_accuracy_mode"] = self.chk_high_acc.isChecked()

            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Config] Error saving settings: {e}")

    def on_high_accuracy_toggled(self, checked: bool):
        self.high_accuracy_toggled.emit(checked)
        self.save_settings()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

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

    def populate_microphones(self):
        """Scan active input microphones without duplicates."""
        current_data = self.combo_mic.currentData() if hasattr(self, "combo_mic") else None
        self.combo_mic.clear()
        self.combo_mic.addItem("システム既定のマイク (Default)", None)

        try:
            import sounddevice as sd
            hostapis = sd.query_hostapis()
            # On Windows, prefer WASAPI hostapi to avoid MME/DirectSound duplicates
            wasapi_id = next((i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None)

            devs = sd.query_devices()
            seen_names = set()
            for i, d in enumerate(devs):
                if d["max_input_channels"] > 0:
                    if wasapi_id is not None and d["hostapi"] != wasapi_id:
                        continue
                    name = d["name"]
                    if name not in seen_names:
                        seen_names.add(name)
                        self.combo_mic.addItem(name, i)

            # Restore previous selection if possible
            if current_data is not None:
                for idx in range(self.combo_mic.count()):
                    if self.combo_mic.itemData(idx) == current_data:
                        self.combo_mic.setCurrentIndex(idx)
                        break
        except Exception as ex:
            print(f"[Audio] Error enumerating microphones: {ex}")

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

    def check_for_updates(self):
        """Asynchronously check if a newer version is available on GitHub."""
        import threading
        import urllib.request

        def _worker():
            try:
                root = Path(__file__).resolve().parent.parent
                ver_file = root / "version.txt"
                local_ver = ver_file.read_text(encoding="utf-8").strip() if ver_file.exists() else "1.0.0"

                url = "https://raw.githubusercontent.com/Maximilian2022/hayamimi-polyglot/main/version.txt"
                req = urllib.request.Request(url, headers={"User-Agent": "Hayamimi-Polyglot-Client"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    remote_ver = resp.read().decode("utf-8").strip()

                if remote_ver and remote_ver != local_ver:
                    def _notify():
                        self.btn_update.setText(f"🆕 更新利用可能 (v{remote_ver})")
                        self.btn_update.setStyleSheet("font-size: 11px; padding: 4px 8px; background-color: #0284C7; font-weight: bold; color: #FFFFFF;")
                        self.btn_update.setToolTip(f"最新バージョン v{remote_ver} が公開されています。クリックして更新できます。")
                    QtCore.QMetaObject.invokeMethod(self, _notify, QtCore.Qt.ConnectionType.QueuedConnection)
            except Exception:
                pass  # Offline or rate limit - fail silently

        threading.Thread(target=_worker, daemon=True).start()

    def open_updater(self):
        """Launch the setup/updater GUI to download extra models or update version."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "モデル追加 / アップデート",
            "AIモデルの追加ダウンロードや環境のクリーン再構築を行うため、現在のアプリを終了してアップデータを起動します。\n\n（※設定は自動保存され、更新完了後に自動で再起動されます）\n\nアップデータを起動しますか？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self.save_settings()
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if platform.system() == "Windows":
            setup_script = os.path.join(root, "setup.ps1")
            if os.path.isfile(setup_script):
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", setup_script],
                    cwd=root,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                )
        else:
            setup_script = os.path.join(root, "setup.sh")
            if os.path.isfile(setup_script):
                subprocess.Popen(["bash", setup_script], cwd=root, start_new_session=True)

        QtWidgets.QApplication.quit()

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
        self.tray.setToolTip("Hayamimi Polyglot - リアルタイム多言語同時並行通訳")

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
