import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6 import QtWidgets, QtGui
from ui.overlay_window import OverlayWindow
from ui.control_panel import ControlPanel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
overlay = OverlayWindow()
panel = ControlPanel(overlay=overlay)

print("Checking color buttons...")
for k in ["self_tag", "remote_tag", "orig_text", "ja", "en", "zh", "ko", "fr", "de", "es", "vi"]:
    assert k in panel.color_btns, f"Missing color button for {k}"
    print(f"Color {k:10s} -> {overlay.colors[k]}")

# Test updating color for ja and self_tag
panel.overlay.set_color("ja", "#00FF00")
panel.overlay.set_color("self_tag", "#FF00FF")
assert overlay.colors["ja"] == "#00FF00"
assert overlay.colors["self_tag"] == "#FF00FF"

# Test saving settings
panel.save_settings()

# Create another instance to test loading settings
overlay2 = OverlayWindow()
panel2 = ControlPanel(overlay=overlay2)
print("Verifying loaded colors in second instance:")
print("overlay2 ja color:", overlay2.colors["ja"])
print("overlay2 self_tag color:", overlay2.colors["self_tag"])
assert overlay2.colors["ja"] == "#00FF00"
assert overlay2.colors["self_tag"] == "#FF00FF"

# Reset colors back to default
panel2.reset_colors()
print("After reset_colors -> ja:", overlay2.colors["ja"])
assert overlay2.colors["ja"] == "#34D399"

print("\nALL COLOR CUSTOMIZATION TESTS PASSED!")
