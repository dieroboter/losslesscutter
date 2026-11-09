"""Regression test: when the cut-plan text appears, the preview
picture must shrink to fit - not stay at its old size and clip.

The preview QLabel paints its pixmap centered. show_frame scaled
the pixmap to the preview's size at display time, and the window's
resizeEvent refit it on window resizes - but when the cut-plan
label gained text, the extra height came out of the preview via
the layout only: no window resize, no refit, and the label kept
painting the taller pixmap into the shorter area, clipping the
top and bottom of the picture. The preview now refits its pixmap
whenever its own size changes (event filter), scaling from the
stored unscaled frame.

Run: .venv/bin/python tests/test_preview_shrink.py
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


def settle(app, win):
    """Pump the event loop until the preview height stops changing
    (relayout after a widget show/hide is deferred a beat)."""
    last = -1
    for _ in range(200):
        app.processEvents()
        h = win.preview.height()
        if h == last:
            return
        last = h
        time.sleep(0.005)
    raise AssertionError("layout did not settle")


def wait_loaded(app, win, path):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None \
                and win.info.path == str(path):
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out loading {path}")


def main() -> None:
    app = QApplication([])
    win = MainWindow()
    # His maximized size at 150% scaling: 1280x697 logical px.
    win.resize(1280, 697)
    win.show()
    app.processEvents()

    win.load_file(str(SRC))
    wait_loaded(app, win, SRC)
    win.show_frame(10)
    settle(app, win)

    preview = win.preview
    pix1 = preview.pixmap()
    assert pix1 is not None and not pix1.isNull(), "no pixmap after show_frame"
    h1 = preview.height()
    assert pix1.height() <= h1, (
        f"pixmap {pix1.height()} taller than preview {h1} before text")

    # The cut-plan text appears: its height comes out of the preview.
    win._set_cut_text(
        "Plan: Cutting the first 10 frames (0-9). Keeping 100 frames. "
        "Re-encodes: 4 frames at the beginning, 3 at the end. "
        "The other 93 kept frames are copied bit-identical.")
    settle(app, win)
    h2 = preview.height()
    pix2 = preview.pixmap()
    assert h2 < h1, f"preview did not shrink ({h1} -> {h2})"
    assert pix2.height() <= h2, (
        f"pixmap {pix2.height()} taller than shrunken preview {h2}: "
        "the picture would be clipped at top and bottom")
    assert pix2.height() < pix1.height(), (
        f"pixmap did not rescale ({pix1.height()} -> {pix2.height()})")

    # And it grows back when the text goes away.
    win._set_cut_text("")
    settle(app, win)
    h3 = preview.height()
    pix3 = preview.pixmap()
    assert h3 > h2, f"preview did not grow back ({h2} -> {h3})"
    assert pix3.height() <= h3 and pix3.height() > pix2.height(), (
        f"pixmap did not refit on grow ({pix2.height()} -> "
        f"{pix3.height()} into {h3})")

    win.close()
    print("test_preview_shrink: OK")


if __name__ == "__main__":
    main()
