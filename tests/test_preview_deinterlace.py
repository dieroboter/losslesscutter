"""Deinterlaced preview: paused shows the first field alone (line
doubled, half resolution, nothing invented); playback shows each
field as its own deinterlaced picture (double rate, "2x"), the way
MPC-HC displays interlaced video. Progressive files are untouched.

Covers the player paths (field view, get_frame_2x streaming, field
parity detection for top- and bottom-field-first material) and the
GUI routing (show_frame's field argument, stop returning to the
field view).

Run: .venv/bin/python tests/test_preview_deinterlace.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import av
from PySide6.QtWidgets import QApplication

from smartcut.media_container import MediaContainer
from losslesscutter.player import PreviewPlayer
from losslesscutter.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
TFF = OUT / "deint_tff.mpg"
BFF = OUT / "deint_bff.mpg"
PROG = ROOT / "test-media" / "h264.mp4"


def build_fixtures():
    OUT.mkdir(exist_ok=True)
    for path, mode, top in ((TFF, "interleave_top", "1"),
                            (BFF, "interleave_bottom", "0")):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=50:duration=3",
             "-vf", f"tinterlace={mode}",
             "-c:v", "mpeg2video", "-q:v", "2", "-flags", "+ildct+ilme",
             "-top", top, "-f", "vob", str(path)],
            check=True)


def reference_frame(path, index):
    with av.open(str(path)) as c:
        for i, f in enumerate(c.decode(video=0)):
            if i == index:
                return f.to_ndarray(format="rgb24")
    raise AssertionError("no such frame")


def img_array(img):
    arr = np.frombuffer(img.constBits(), dtype=np.uint8)
    return arr.reshape(img.height(), img.width(), 3).copy()


def open_player(path):
    mc = MediaContainer(str(path))
    p = PreviewPlayer()
    p.open(str(path), mc)
    return p, mc


def expected_field_view(woven, parity):
    """The spec's paused picture for a frame: the field at `parity`,
    scaled smoothly to full height (the same construction the probe
    script uses, so a working build matches it exactly)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    fa = np.ascontiguousarray(woven[parity::2])
    img = QImage(fa.data, fa.shape[1], fa.shape[0], fa.strides[0],
                 QImage.Format.Format_RGB888).copy()
    out = img.scaled(woven.shape[1], woven.shape[0],
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    return img_array(out)


def view_mads(view, woven):
    """Distance of a paused view from each parity's expected view."""
    return tuple(
        np.abs(view.astype(int) - expected_field_view(woven, p).astype(int)).mean()
        for p in (0, 1))


def check_field_view(path, parity, label):
    p, mc = open_player(path)
    try:
        woven = reference_frame(path, 30)
        assert p.is_interlaced is None or p.is_interlaced
        view_img = p.get_frame_display(30)
        view = img_array(view_img)
        assert p.is_interlaced is True, f"{label}: not seen as interlaced"
        assert view.shape == woven.shape, f"{label}: field view size"
        # Smoothly scaled, not line doubled: adjacent lines are not
        # locked in identical pairs.
        pairs_equal = (view[0::2] == view[1::2]).all(axis=(1, 2)).mean()
        assert pairs_equal < 0.5, \
            f"{label}: field view is line doubled ({pairs_equal:.2f} pairs equal)"
        # Pure first field: the view matches the first field's
        # expected smooth view essentially exactly, and is far from
        # the second field's.
        mads = view_mads(view, woven)
        assert mads[parity] < 0.05 and mads[1 - parity] > 10 * mads[parity] + 0.5, \
            f"{label}: field view is not the pure first field (MADs {mads})"
        assert not (view == woven).all(), \
            f"{label}: field view equals the woven frame on moving content"
        print(f"{label}: field view OK (first-field parity {parity}, "
              f"view MADs {mads[0]:.3f}/{mads[1]:.3f})")
        return p, mc
    except Exception:
        mc.close()
        raise


def main():
    build_fixtures()

    # Top-field-first: first field = even rows. Bottom-field-first:
    # first field = odd rows.
    p, mc = check_field_view(TFF, 0, "tff")
    woven = reference_frame(TFF, 30)

    def mad(a, b):
        return np.abs(a.astype(int) - b.astype(int)).mean()

    def assert_field_of(pic, frame_idx, parity):
        """The picture is frame_idx's field `parity`: its own-parity
        lines match that frame far better than either neighbour's
        (bwdif filters its output, so the check is closeness, not
        exact equality like the pure field view)."""
        w_prev = reference_frame(TFF, frame_idx - 1)
        w_here = reference_frame(TFF, frame_idx)
        w_next = reference_frame(TFF, frame_idx + 1)
        d = mad(pic[parity::2], w_here[parity::2])
        assert d < 0.5 * min(mad(pic[parity::2], w_prev[parity::2]),
                             mad(pic[parity::2], w_next[parity::2])), \
            f"picture is not frame {frame_idx} field {parity} (MAD {d:.2f})"

    try:
        # --- 2x playback pictures ---------------------------------
        f0 = img_array(p.get_frame_2x(30, 0))
        f1 = img_array(p.get_frame_2x(30, 1))
        assert f0.shape == woven.shape and f1.shape == woven.shape
        assert_field_of(f0, 30, 0)
        assert_field_of(f1, 30, 1)
        # ...and the two fields differ on moving content, and neither
        # is the woven frame.
        assert not (f0 == f1).all(), "2x fields are identical"
        assert not (f0 == woven).all() and not (f1 == woven).all()
        # Sequential playback sweep: every field picture available.
        for i in range(20, 41):
            for f in (0, 1):
                assert p.get_frame_2x(i, f) is not None, f"missing {(i, f)}"
        # A backward jump restarts the graph and still answers with
        # the right frame's field.
        assert_field_of(img_array(p.get_frame_2x(10, 1)), 10, 1)
        print("tff: 2x pictures OK")
    finally:
        p.close()
        mc.close()

    p2, mc2 = check_field_view(BFF, 1, "bff")
    p2.close()
    mc2.close()

    # --- progressive files: everything is the plain frame ---------
    p3, mc3 = open_player(PROG)
    try:
        plain = img_array(p3.get_frame(10))
        assert p3.is_interlaced is False
        assert (img_array(p3.get_frame_display(10)) == plain).all(), \
            "progressive display differs from the plain frame"
        assert (img_array(p3.get_frame_2x(10, 1)) == plain).all(), \
            "progressive 2x differs from the plain frame"
        print("progressive: untouched OK")
    finally:
        p3.close()
        mc3.close()

    # --- GUI routing ----------------------------------------------
    app = QApplication([])
    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    app.processEvents()
    path = str(TFF)
    win.load_file(path)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None \
                and win.info.path == path:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("file did not finish loading")
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)

    w0 = reference_frame(TFF, 0)
    mads = view_mads(img_array(win._current_image), w0)
    assert mads[0] < 0.05 and mads[1] > 0.5, \
        f"GUI paused view is not the field view (MADs {mads})"
    win.show_frame(30, field=1)
    shown = img_array(win._current_image)
    w30 = reference_frame(TFF, 30)
    d = np.abs(shown[1::2].astype(int) - w30[1::2].astype(int)).mean()
    d_prev = np.abs(shown[1::2].astype(int)
                    - reference_frame(TFF, 29)[1::2].astype(int)).mean()
    assert d < 0.5 * d_prev and not (shown == w30).all(), \
        "GUI playback view is not the 2x field picture"
    win._stop_play()
    mads = view_mads(img_array(win._current_image), w30)
    assert mads[0] < 0.05 and mads[1] > 0.5, \
        f"stop did not return to the field view (MADs {mads})"
    assert win.current_frame == 30, "stop moved the current frame"

    # Picture numbering on interlaced files (his pick: match MPC-HC
    # everywhere). The fixture has 75 frames = pictures 0..149.
    assert "Frame 60 / 149" in win.time_label.text(), win.time_label.text()
    win.show_frame(30, field=1)
    assert "Frame 61 / 149" in win.time_label.text(), win.time_label.text()
    win.goto_edit.setText("101")
    win._on_goto()
    assert win.current_frame == 50, win.current_frame
    assert "Frame 100 / 149" in win.time_label.text(), win.time_label.text()
    win.goto_edit.setText("150")
    win._on_goto()
    assert win.current_frame == 50, "out-of-range picture was accepted"
    assert "picture 150" in win.status_label.text(), win.status_label.text()
    win.goto_edit.setText("0:02")
    win._on_goto()
    assert win.current_frame == 50, win.current_frame
    assert "Frame 100 / 149" in win.time_label.text(), win.time_label.text()
    print("gui: picture numbering OK")

    # The selection surfaces use the same numbering: marks at
    # source frames 25 and 49 display as pictures 50 and 98, the
    # list entry as frames 50-99, and the plan text counts pictures.
    win.mark_in, win.mark_out = 25, 49
    win._update_marks_label()
    assert "(frame 50)" in win.marks_label.text(), win.marks_label.text()
    assert "(frame 98)" in win.marks_label.text(), win.marks_label.text()
    win.add_selection()
    item = win.sel_list.item(0).text()
    assert "(frames 50-99)" in item, item
    assert "Cutting the first 50 frames (0-49)" in win.cut_label.text(), \
        win.cut_label.text()
    assert "Keeping 50 frames" in win.status_label.text(), \
        win.status_label.text()
    print("gui: selection numbering OK")
    win.close()

    # Progressive files keep source-frame numbering throughout.
    win = MainWindow()
    win.show()
    app.processEvents()
    prog_path = str(PROG)
    win.load_file(prog_path)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None \
                and win.info.path == prog_path:
            break
    assert win.info is not None and win.info.path == prog_path
    assert "Frame 0 / 143" in win.time_label.text(), win.time_label.text()
    win.goto_edit.setText("30")
    win._on_goto()
    assert win.current_frame == 30, win.current_frame
    assert "Frame 30 / 143" in win.time_label.text(), win.time_label.text()
    win.mark_in, win.mark_out = 25, 49
    win.add_selection()
    item = win.sel_list.item(0).text()
    assert "(frames 25-49)" in item, item
    print("gui: progressive numbering unchanged OK")
    win.close()
    print("gui: routing OK")

    print("PREVIEW DEINTERLACE TEST PASSED")


if __name__ == "__main__":
    main()
