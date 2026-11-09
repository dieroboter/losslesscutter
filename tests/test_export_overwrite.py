"""Exporting must never silently overwrite an existing file.

start_export used to hand any output path straight to the export
worker, which truncates the target: re-exporting the same cut (the
default name is <file>_cut.<ext>) destroyed the previous export.
Now, when the chosen output path already exists, a popup says to
rename the export first and the export does not start. (The input
file itself keeps its own, earlier refusal.) The non-conflict path
must still export normally.

Run: .venv/bin/python tests/test_export_overwrite.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox

import losslesscutter.main_window as mw
from losslesscutter.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "test-media" / "h264.mp4"
OUTDIR = ROOT / "test-out"
OUTDIR.mkdir(exist_ok=True)
EXISTING = OUTDIR / "already_here.mp4"
FRESH = OUTDIR / "overwrite_fresh.mp4"


class BoxStub:
    StandardButton = QMessageBox.StandardButton
    warnings: list = []
    criticals: list = []
    informations: list = []

    @staticmethod
    def warning(parent, title, text):
        BoxStub.warnings.append(text)

    @staticmethod
    def critical(parent, title, text):
        BoxStub.criticals.append(text)

    @staticmethod
    def information(parent, title, text):
        BoxStub.informations.append(text)

    @staticmethod
    def question(parent, title, text, buttons, default):
        return QMessageBox.StandardButton.No


def wait_loaded(app, win, path):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None \
                and win.info.path == str(path):
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out loading {path}")


def wait_export_done(app, win):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        app.processEvents()
        if win._thread is None and win._worker is None:
            return
        time.sleep(0.005)
    raise AssertionError("export did not finish")


def main() -> None:
    app = QApplication([])
    real_box = mw.QMessageBox
    mw.QMessageBox = BoxStub
    try:
        EXISTING.write_bytes(b"previous export - do not destroy")
        if FRESH.exists():
            FRESH.unlink()

        win = MainWindow()
        win.show()
        win.load_file(str(SRC))
        wait_loaded(app, win, SRC)
        win.show_frame(26)
        win.set_mark_in()
        win.show_frame(53)
        win.set_mark_out()
        win.add_selection()
        assert win.selections == [(26, 53)], win.selections

        # Conflict: popup, no export, existing file untouched.
        win.out_edit.setText(str(EXISTING))
        win.start_export()
        app.processEvents()
        assert len(BoxStub.warnings) == 1, BoxStub.warnings
        assert "already exists" in BoxStub.warnings[0], BoxStub.warnings
        assert "Rename the export" in BoxStub.warnings[0], BoxStub.warnings
        assert win._worker is None and win._thread is None, \
            "export started despite the name conflict"
        assert EXISTING.read_bytes() == b"previous export - do not destroy"

        # The input path keeps its own refusal (critical, not warning).
        win.out_edit.setText(str(SRC))
        win.start_export()
        app.processEvents()
        assert len(BoxStub.criticals) == 1, BoxStub.criticals
        assert "overwrite the input" in BoxStub.criticals[0]
        assert win._worker is None and win._thread is None

        # No conflict: the export runs and writes the file.
        win.out_edit.setText(str(FRESH))
        win.start_export()
        assert win._thread is not None, "export did not start"
        wait_export_done(app, win)
        assert FRESH.exists() and FRESH.stat().st_size > 0
        assert "Done" in win.status_label.text(), win.status_label.text()

        win.close()
    finally:
        mw.QMessageBox = real_box
    print("test_export_overwrite: OK")


if __name__ == "__main__":
    main()
