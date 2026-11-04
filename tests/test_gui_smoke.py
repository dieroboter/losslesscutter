"""GUI end-to-end smoke test (offscreen Qt).

Loads a real file into the main window, steps frames, jumps GOPs, sets
marks, adds a selection, checks the plan readout, then runs the export
synchronously through ExportWorker and validates the output.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import av
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from losslesscutter.export_worker import ExportWorker
from losslesscutter.main_window import MainWindow
from losslesscutter.segments import describe_cut, parse_goto, positive_segments
from losslesscutter.update_check import is_newer, parse_version
from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.video_cutter import VideoSettings

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "test-media" / "h264.mp4"
OUT = ROOT / "test-out" / "gui-smoke-out.mp4"


def count_frames(path):
    n = 0
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for _ in c.decode(vs):
            n += 1
    return n


def main():
    # Cut-range wording (the user's melobytes1.mp4 case: 311 frames, keep 25-136)
    assert describe_cut(311, [(25, 136)], "keep") == (
        "Cutting the first 25 frames (0-24) and the last 174 frames (137-310)."
    ), describe_cut(311, [(25, 136)], "keep")
    assert describe_cut(100, [(0, 99)], "keep") == "Nothing is being cut."
    assert describe_cut(100, [(10, 19)], "remove") == \
        "Cutting 10 frames in the middle (10-19)."
    assert describe_cut(100, [(0, 9), (90, 99)], "remove") == (
        "Cutting the first 10 frames (0-9) and the last 10 frames (90-99)."
    )
    print("describe_cut wording OK")

    # Go-to parsing: bare integers are frames, "." / ":" means a timestamp
    from fractions import Fraction
    fps, count = Fraction(24), 144
    assert parse_goto("48", fps, count) == 48
    assert parse_goto("0", fps, count) == 0
    assert parse_goto("143", fps, count) == 143
    assert parse_goto("144", fps, count) == 143  # clamped to last frame
    assert parse_goto("99999", fps, count) == 143
    assert parse_goto(" 12 ", fps, count) == 12
    assert parse_goto("-3", fps, count) == 0  # clamped to first frame
    assert parse_goto("2.0", fps, count) == 48  # 2 seconds at 24 fps
    assert parse_goto("0:03", fps, count) == 72
    assert parse_goto("1:00", fps, count) == 143  # 1440 frames, clamped
    assert parse_goto("0:00:02.5", fps, count) == 60
    for bad in ("", "abc", "1:2:3:4", "12:", "1::2", "nan", "inf", "-1:30"):
        assert parse_goto(bad, fps, count) is None, f"accepted {bad!r}"
    print("parse_goto OK")

    # Update-check version logic
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.0") == (1, 0)
    assert parse_version("V2") == (2,)
    assert parse_version("dev") is None
    assert parse_version("") is None
    assert parse_version("v") is None
    assert is_newer("1.1", "1.0")
    assert is_newer("v1.1", "1.0")
    assert is_newer("1.0.1", "1.0")
    assert is_newer("2", "1.9")
    assert not is_newer("1.0", "1.0")
    assert not is_newer("1.0.0", "1.0")
    assert not is_newer("0.9.9", "1.0")
    assert not is_newer("junk", "1.0")
    print("update version logic OK")

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    assert win.acceptDrops(), "drag & drop not enabled"
    assert not win.windowIcon().isNull(), "window icon missing"

    # Regression (window stretching past the screen edge on Windows): labels
    # carrying long texts must wrap and must never demand width.
    from PySide6.QtWidgets import QSizePolicy
    for lbl in (win.status_label, win.cut_label, win.file_label, win.info_label):
        assert lbl.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored, \
            f"{lbl.objectName() or type(lbl).__name__} can demand width"
    assert win.status_label.wordWrap() and win.cut_label.wordWrap()
    print("no-stretch label policies OK")

    # Update notice: only a strictly newer version fills the label
    assert win.update_label.text() == ""
    win._on_update_checked(None)
    win._on_update_checked(("0.9", "https://example.invalid/rel"))
    assert win.update_label.text() == "", "notice shown for old version"
    win._on_update_checked(("9.9", "https://example.invalid/rel"))
    assert "Update available" in win.update_label.text(), win.update_label.text()
    assert "9.9" in win.update_label.text()
    win.update_label.setText("")
    print("update notice OK")

    win.load_file(str(SRC))
    assert win.info is not None, "file did not load"
    assert win.info.frame_count == 144, f"frame count {win.info.frame_count}"
    assert win.preview.pixmap() is not None and not win.preview.pixmap().isNull(), "no preview frame"

    # Frame stepping and GOP navigation
    win.step_frames(1)
    assert win.current_frame == 1
    win.step_frames(-1)
    assert win.current_frame == 0
    win.step_gop(1)
    assert win.current_frame == 24, f"next GOP landed on {win.current_frame}"
    win.step_gop(-1)
    assert win.current_frame == 0

    # Go to: frame number, timestamp, clamp, and a rejected entry
    win.goto_edit.setText("48")
    win._on_goto()
    assert win.current_frame == 48, f"goto frame landed on {win.current_frame}"
    win.goto_edit.setText("0:03")
    win._on_goto()
    assert win.current_frame == 72, f"goto time landed on {win.current_frame}"
    win.goto_edit.setText("2.5")
    win._on_goto()
    assert win.current_frame == 60, f"goto seconds landed on {win.current_frame}"
    win.goto_edit.setText("99999")
    win._on_goto()
    assert win.current_frame == 143, f"goto clamp landed on {win.current_frame}"
    win.goto_edit.setText("nonsense")
    win._on_goto()
    assert win.current_frame == 143, "rejected goto moved the playhead"
    assert "Could not understand" in win.status_label.text(), win.status_label.text()
    win.show_frame(0)
    print("go to OK")

    # Marks + selection frames 26..53
    win.show_frame(26)
    win.set_mark_in()
    win.show_frame(53)
    win.set_mark_out()
    win.add_selection()
    assert win.selections == [(26, 53)], win.selections
    plan_text = win.status_label.text()
    assert "beginning" in plan_text and "end" in plan_text, f"plan readout missing: {plan_text}"
    assert "Cutting the first 26 frames (0-25)" in plan_text, f"plan lacks cut ranges: {plan_text}"
    assert win.cut_label.text() == (
        "Cutting the first 26 frames (0-25) and the last 90 frames (54-143)."
    ), f"cut label: {win.cut_label.text()}"
    print("plan readout:", plan_text)
    print("cut label:", win.cut_label.text())

    # Export through the worker, driven synchronously
    segments = positive_segments(win.mc, win.selections, "keep")
    settings = VideoSettings(
        VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS,
        speed="medium", source_bitrate=win.info.video_bitrate,
    )
    worker = ExportWorker(win.info.path, segments, str(OUT), settings)
    result = {}
    worker.succeeded.connect(lambda stats, path: result.update(stats=stats, path=path))
    worker.failed.connect(lambda msg: result.update(error=msg))
    worker.run()
    assert "error" not in result, f"export failed: {result.get('error')}"
    stats = result["stats"]
    assert stats.get("frames_recoded_start", 0) > 0, stats
    assert stats.get("frames_recoded_end", 0) > 0, stats
    got = count_frames(OUT)
    assert got == 28, f"exported frames {got} != 28"
    print("export stats:", stats)

    # Drag & drop: dropping another file loads it
    other = ROOT / "test-media" / "mpeg2.mpg"
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(other))])
    ev = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    win.dropEvent(ev)
    assert win.info is not None and win.info.path == str(other), \
        f"drop did not load {other}: {win.info and win.info.path}"
    assert win.cut_label.text() == "", "cut label not reset after drop"
    print("drag & drop load OK:", win.info.path)
    print("GUI SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
