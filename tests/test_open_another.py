"""Opening a file while another is open: ask, don't refuse.

load_file used to answer every second open with "Wait for the
export to finish before loading another file." - even when no
export had ever run, and forever after any export, because
_export_done/_export_failed never cleared the export thread/worker
state the guard checks. Now:

- an export really running keeps the status-line refusal (and no
  popup is shown);
- otherwise, with a file open, a confirmation popup asks whether
  to open the different file; No leaves the current file untouched,
  Yes loads the new one;
- finishing or failing an export clears the export state, so the
  refusal only ever appears while an export is actually running.

Run: .venv/bin/python tests/test_open_another.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

import losslesscutter.main_window as mw
from losslesscutter.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "test-media" / "h264.mp4"
B = ROOT / "test-media" / "mpeg2.mpg"


class QMessageBoxStub:
    """Records question() calls and answers with a preset button;
    the other boxes become no-ops. StandardButton stays the real
    enum - the code under test compares against it."""
    StandardButton = QMessageBox.StandardButton
    answer = QMessageBox.StandardButton.No
    calls: list = []

    @staticmethod
    def question(parent, title, text, buttons, default):
        QMessageBoxStub.calls.append((title, text))
        return QMessageBoxStub.answer

    @staticmethod
    def critical(parent, title, text):
        pass

    @staticmethod
    def warning(parent, title, text):
        pass

    @staticmethod
    def information(parent, title, text):
        pass


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
    real_box = mw.QMessageBox
    mw.QMessageBox = QMessageBoxStub
    try:
        win = MainWindow()
        win.show()
        win.load_file(str(A))
        wait_loaded(app, win, A)

        # No to the popup: the current file stays, no load starts.
        QMessageBoxStub.answer = QMessageBox.StandardButton.No
        QMessageBoxStub.calls.clear()
        win.load_file(str(B))
        app.processEvents()
        assert len(QMessageBoxStub.calls) == 1, QMessageBoxStub.calls
        assert win.info.path == str(A), win.info.path
        assert win._load_thread is None

        # Yes to the popup: the new file loads.
        QMessageBoxStub.answer = QMessageBox.StandardButton.Yes
        win.load_file(str(B))
        wait_loaded(app, win, B)
        assert win.info.path == str(B)

        # Finishing an export clears the export state...
        win._thread = QThread()
        win._worker = object()
        win._export_done({}, "out.mp4")
        assert win._thread is None and win._worker is None
        # ...and so does failing one.
        win._thread = QThread()
        win._worker = object()
        win._export_failed("boom")
        assert win._thread is None and win._worker is None

        # With an export actually running: status refusal, no popup.
        QMessageBoxStub.calls.clear()
        win._thread = QThread()
        win.load_file(str(A))
        app.processEvents()
        assert QMessageBoxStub.calls == [], QMessageBoxStub.calls
        assert "export" in win.status_label.text().lower(), \
            win.status_label.text()
        assert win.info.path == str(B)
        win._thread = None

        win.close()
    finally:
        mw.QMessageBox = real_box
    print("test_open_another: OK")


if __name__ == "__main__":
    main()
