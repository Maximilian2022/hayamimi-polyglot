from PySide6 import QtWidgets
import sys
from ui.overlay_window import OverlayWindow
from ui.control_panel import ControlPanel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
overlay = OverlayWindow()
panel = ControlPanel(overlay=overlay)

print("Control panel initialized successfully.")
print(f"Font combo count: {panel.combo_font.count()}")
print(f"Overlay font_size: {overlay.font_size}")
print(f"Overlay font_family: '{overlay.font_family}'")
print(f"Overlay geometry: {overlay.geometry().width()}x{overlay.geometry().height()}")
print(f"Overlay opacity: {overlay.bg_opacity}")

# Test changing font size
panel.slider_font_size.setValue(24)
print(f"After slider update -> overlay font_size: {overlay.font_size}")
assert overlay.font_size == 24

# Test preset
panel.apply_area_preset(1150, 220)
print(f"After preset update -> overlay size: {overlay.geometry().width()}x{overlay.geometry().height()}")
assert overlay.geometry().width() == 1150
assert overlay.geometry().height() == 220

# Test saving and loading
panel.save_settings()
print("Settings saved successfully!")
print("ALL TESTS PASSED!")
