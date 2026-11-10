"""Regression test: the preview pixmap must be rendered at the
display's physical resolution, not its logical size.

_fit_preview_pixmap scaled the frame to the preview label's size,
which is in logical pixels. On a display scaled to 150% the
label's backing store is 1.5x that, so the window system stretched
the already-downscaled pixmap back up when painting it - a double
resample that softened everything, most visibly crisp 1080p screen
recordings (OBS captures). The pixmap is now scaled straight to
the physical size (logical size x device pixel ratio) and tagged
with that ratio, so painting it is 1:1.

The discriminating run needs a scaled display:
    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 \
        .venv/bin/python tests/test_preview_dpr.py
On an unscaled display (ratio 1) the same assertions validate the
1:1 path instead.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication

from losslesscutter.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "test-media" / "h264.mp4"


def wait_loaded(app, win, path):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None \
                and win.info.path == path:
            return
        time.sleep(0.01)
    raise AssertionError("file did not finish loading")


def main():
    app = QApplication([])
    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    app.processEvents()
    path = str(SRC)
    win.load_file(path)
    wait_loaded(app, win, path)
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)

    label = win.preview
    pix = label.pixmap()
    assert pix is not None and not pix.isNull(), "no preview pixmap"
    assert win._current_image is not None

    dpr = label.devicePixelRatioF()
    print(f"display dpr: {dpr}, label: {label.width()}x{label.height()}, "
          f"pixmap: {pix.width()}x{pix.height()} @ {pix.devicePixelRatio()}")

    # The pixmap must be tagged with the display's ratio, so the
    # compositor paints it 1:1 instead of stretching it.
    assert abs(pix.devicePixelRatio() - dpr) < 0.01, (
        f"pixmap device pixel ratio is {pix.devicePixelRatio()}, "
        f"display is {dpr}: the painted preview gets upscaled and "
        "softened on a scaled display")

    # And it must actually hold physical-resolution pixels: the
    # aspect fit of the source frame into the label, times the ratio.
    src_w, src_h = win._current_image.width(), win._current_image.height()
    fit = min(label.width() / src_w, label.height() / src_h)
    exp_w, exp_h = src_w * fit * dpr, src_h * fit * dpr
    assert abs(pix.width() - exp_w) <= 2 and abs(pix.height() - exp_h) <= 2, (
        f"pixmap is {pix.width()}x{pix.height()}, expected about "
        f"{exp_w:.0f}x{exp_h:.0f} (fit x dpr)")

    # Content: the pixmap must be a single direct scale of the
    # stored frame to its own size (not a two-step down-then-up).
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    direct = QPixmap.fromImage(win._current_image).scaled(
        pix.size(), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    assert direct.toImage() == pix.toImage(), (
        "pixmap is not a direct scale of the frame")

    win.close()
    print("PREVIEW DPR TEST PASSED")


if __name__ == "__main__":
    main()
