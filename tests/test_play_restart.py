"""Regression test: pressing Space at the end of a preview restarts
playback from the beginning.

Before the fix, Space at the last frame started playback from that
frame, and the play loop stopped at once (the position was already
past the last frame's duration), so nothing visibly happened. Now
toggle_play - the handler behind both Space and the Play button -
seeks to frame 0 first when the playhead is on the last frame.

Run: .venv/bin/python tests/test_play_restart.py
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
                and win.info.path == str(path):
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out loading {path}")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    wait_loaded(app, win, SRC)
    assert win.info is not None, "file did not load"
    last = win.info.frame_count - 1
    assert last == 143, f"frame count {win.info.frame_count}"

    # At the end: Space restarts from the beginning.
    win.show_frame(last)
    assert win.current_frame == last
    win.toggle_play()
    assert win.current_frame == 0, (
        f"Space at the end left the playhead on {win.current_frame}")
    assert win._playing, "playback did not start after Space at the end"
    win._stop_play()
    assert not win._playing

    # Mid-file: Space starts from the playhead, no restart.
    win.show_frame(50)
    win.toggle_play()
    assert win.current_frame == 50, (
        f"Space mid-file moved the playhead to {win.current_frame}")
    assert win._playing, "playback did not start mid-file"
    win._stop_play()

    # Pausing still works from the start.
    win.show_frame(0)
    win.toggle_play()
    assert win._playing
    win.toggle_play()
    assert not win._playing, "second Space did not pause"

    win.close()
    print("PLAY RESTART TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
