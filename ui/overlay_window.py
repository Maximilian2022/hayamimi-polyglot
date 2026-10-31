"""
Hayamimi For Business - Transparent Desktop Subtitle Overlay.
Features:
  - Topmost transparent overlay (PySide6)
  - Click-through (mouse event transparent)
  - Stealth Mode (SetWindowDisplayAffinity: hidden from Zoom/Teams screen sharing)
  - Dual-track display: [自分] and [相手] with different colors
  - Draggable & resizable
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from collections import deque
from typing import Deque, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPoint


# Windows display affinity constants
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 2004+ / Windows 11


def set_stealth_mode(window_id: int, stealth_on: bool) -> bool:
    """
    Set window display affinity to exclude it from screen capture (Zoom/Teams/Google Meet).
    Works on both Windows (SetWindowDisplayAffinity) and macOS (NSWindow.sharingType = NSWindowSharingNone).
    """
    system = platform.system()
    if system == "Windows":
        if not window_id:
            return False
        try:
            user32 = ctypes.windll.user32
            affinity = WDA_EXCLUDEFROMCAPTURE if stealth_on else WDA_NONE
            res = user32.SetWindowDisplayAffinity(ctypes.c_void_p(window_id), ctypes.c_uint32(affinity))
            return bool(res)
        except Exception as e:
            print(f"[StealthMode Win] Error: {e}")
            return False
    elif system == "Darwin":
        try:
            import ctypes.util
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            objc_msgSend = objc.objc_msgSend
            objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            objc_msgSend.restype = ctypes.c_void_p
            sel_registerName = objc.sel_registerName
            sel_registerName.argtypes = [ctypes.c_char_p]
            sel_registerName.restype = ctypes.c_void_p

            sel_window = sel_registerName(b"window")
            ns_window = objc_msgSend(ctypes.c_void_p(window_id), sel_window)
            target = ns_window if ns_window else ctypes.c_void_p(window_id)

            # NSWindowSharingNone = 0, NSWindowSharingReadOnly = 1
            sel_setSharingType = sel_registerName(b"setSharingType:")
            objc_msgSend_set = objc.objc_msgSend
            objc_msgSend_set.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
            objc_msgSend_set.restype = None

            sharing_type = 0 if stealth_on else 1
            objc_msgSend_set(target, sel_setSharingType, sharing_type)
            return True
        except Exception as e:
            print(f"[StealthMode Mac] Error: {e}")
            return False
    return False


def set_click_through(window_id: int, click_through: bool) -> None:
    """
    Set mouse event pass-through.
    Works on both Windows (WS_EX_TRANSPARENT) and macOS (ignoresMouseEvents).
    """
    system = platform.system()
    if system == "Windows":
        if not window_id:
            return
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000

            style = user32.GetWindowLongW(ctypes.c_void_p(window_id), GWL_EXSTYLE)
            if click_through:
                style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED)
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(ctypes.c_void_p(window_id), GWL_EXSTYLE, style)
        except Exception:
            pass
    elif system == "Darwin":
        try:
            import ctypes.util
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            sel_registerName = objc.sel_registerName
            sel_registerName.argtypes = [ctypes.c_char_p]
            sel_registerName.restype = ctypes.c_void_p
            sel_window = sel_registerName(b"window")
            objc_msgSend = objc.objc_msgSend
            objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            objc_msgSend.restype = ctypes.c_void_p
            ns_window = objc_msgSend(ctypes.c_void_p(window_id), sel_window)
            target = ns_window if ns_window else ctypes.c_void_p(window_id)

            sel_setIgnores = sel_registerName(b"setIgnoresMouseEvents:")
            objc_msgSend_bool = objc.objc_msgSend
            objc_msgSend_bool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            objc_msgSend_bool.restype = None
            objc_msgSend_bool(target, sel_setIgnores, click_through)
        except Exception:
            pass


class SubtitleItem:
    def __init__(self, track: str, text: str, translations: Optional[Dict[str, str]] = None):
        self.track = track  # "self" or "remote"
        self.text = text
        self.translations: Dict[str, str] = translations or {}


class OverlayWindow(QtWidgets.QWidget):
    """Transparent, click-through, stealth-protected subtitle window."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.stealth_enabled = True  # Default: hidden from screen sharing
        self.click_through = False  # Default: draggable until locked
        self.max_lines = 4
        self.history: Deque[SubtitleItem] = deque(maxlen=self.max_lines)

        self._drag_pos = QPoint()

        self.init_ui()

    def init_ui(self):
        # Window flags: Frameless, Topmost, Tool window (hidden from taskbar)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Drag handle / Header bar
        self.header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QtWidgets.QLabel("Hayamimi Business Subtitles")
        self.lbl_title.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        # Stealth badge
        self.lbl_stealth = QtWidgets.QLabel("🛡️ 画面共有から非表示中")
        self.lbl_stealth.setStyleSheet("color: #10B981; font-size: 11px; font-weight: bold; padding: 2px 6px; background: rgba(16, 185, 129, 0.15); border-radius: 4px;")
        header_layout.addWidget(self.lbl_stealth)

        layout.addWidget(self.header)

        # Subtitle scroll/content container
        self.content_area = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 4, 0, 4)
        self.content_layout.setSpacing(8)
        layout.addWidget(self.content_area)

        # Default size and position (bottom center of primary screen)
        screen = QtGui.QGuiApplication.primaryScreen().geometry()
        w, h = 820, 180
        x = (screen.width() - w) // 2
        y = screen.height() - h - 60
        self.setGeometry(x, y, w, h)

        self.refresh_display()

    def showEvent(self, event):
        super().showEvent(event)
        # Apply stealth mode once window handle exists
        self.apply_stealth(self.stealth_enabled)

    def apply_stealth(self, enabled: bool):
        self.stealth_enabled = enabled
        hwnd = int(self.winId())
        set_stealth_mode(hwnd, enabled)
        if enabled:
            self.lbl_stealth.setText("🛡️ 画面共有から非表示中")
            self.lbl_stealth.setStyleSheet("color: #10B981; font-size: 11px; font-weight: bold; padding: 2px 6px; background: rgba(16, 185, 129, 0.15); border-radius: 4px;")
        else:
            self.lbl_stealth.setText("👁️ 画面共有に表示中")
            self.lbl_stealth.setStyleSheet("color: #F59E0B; font-size: 11px; font-weight: bold; padding: 2px 6px; background: rgba(245, 158, 11, 0.15); border-radius: 4px;")

    def set_click_through_mode(self, enabled: bool):
        self.click_through = enabled
        hwnd = int(self.winId())
        set_click_through(hwnd, enabled)
        self.header.setVisible(not enabled)

    def add_subtitle(self, track: str, text: str, translations: Optional[Dict[str, str]] = None):
        """Add new finalized subtitle item and refresh view."""
        if not text.strip():
            return
        item = SubtitleItem(track=track, text=text, translations=translations)
        self.history.append(item)
        self.refresh_display()

    def update_last_translation(self, translation: str):
        """Update translation for single language."""
        if self.history:
            self.history[-1].translations["trans"] = translation
            self.refresh_display()

    def update_last_translations(self, translations: Dict[str, str]):
        """Update multicast translations for the most recent subtitle item."""
        if self.history:
            self.history[-1].translations.update(translations)
            self.refresh_display()

    def refresh_display(self):
        # Clear content layout
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.history:
            placeholder = QtWidgets.QLabel("（会議の発言がリアルタイムに表示されます）")
            placeholder.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 14px; font-style: italic;")
            self.content_layout.addWidget(placeholder)
            return

        lang_colors = {
            "en": "#FBBF24",  # Amber
            "zh": "#F472B6",  # Rose
            "ja": "#34D399",  # Emerald
            "ko": "#A78BFA",  # Purple
            "fr": "#60A5FA",  # Blue
            "de": "#F87171",  # Red
            "es": "#FB923C",  # Orange
        }

        for item in self.history:
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)

            # Speaker tag + Original text
            tag_color = "#38BDF8" if item.track == "self" else "#A78BFA"
            tag_label = "自分" if item.track == "self" else "相手"

            safe_text = item.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            orig_html = f"<span style='color: {tag_color}; font-weight: bold;'>[{tag_label}]</span> <span style='color: #FFFFFF; font-size: 15px;'>{safe_text}</span>"
            lbl_orig = QtWidgets.QLabel(orig_html)
            lbl_orig.setTextFormat(Qt.TextFormat.RichText)
            lbl_orig.setWordWrap(True)
            row_layout.addWidget(lbl_orig)

            # Translations (multiple targets)
            for lang, trans_text in item.translations.items():
                if trans_text:
                    safe_trans = trans_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    color = lang_colors.get(lang.lower(), "#FBBF24")
                    lang_tag = f"[{lang.upper()}] " if lang != "trans" else ""
                    trans_html = f"<span style='color: {color}; font-size: 13.5px; margin-left: 16px;'>↳ <b style='color:{color};'>{lang_tag}</b>{safe_trans}</span>"
                    lbl_trans = QtWidgets.QLabel(trans_html)
                    lbl_trans.setTextFormat(Qt.TextFormat.RichText)
                    lbl_trans.setWordWrap(True)
                    row_layout.addWidget(lbl_trans)

            self.content_layout.addWidget(row)

    def paintEvent(self, event):
        # Render semi-transparent dark rounded container
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        color = QtGui.QColor(15, 23, 42, 210)  # Dark slate with ~82% opacity
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(QtGui.QPen(QtGui.QColor(51, 65, 85, 180), 1.5))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)

    # Mouse drag events
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.click_through:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.click_through:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
