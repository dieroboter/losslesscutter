#!/usr/bin/env python3
"""Startup-shape and probe tests.

- Importing and constructing the main window must not import the engine
  (PyAV, numpy, smartcut), QtMultimedia, or the worker modules - that is
  the cold-start fix, verified in a clean subprocess.
- The update check throttles to once a day.
- The video bitrate estimate works for containers that store no stream
  bitrate (MKV), via packet sampling instead of a full-file demux.
- Timer-clocked playback (files without audio) follows the wall clock
  and skips frames when behind, instead of showing every late frame.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
TMP = Path("/tmp/lc-startup-test")
TMP.mkdir(exist_ok=True)


def test_lazy_imports() -> None:
    code = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from losslesscutter.main_window import MainWindow\n"
        "win = MainWindow()\n"
        "win.show()\n"
        "heavy = [m for m in sys.modules if m == 'av' or m == 'numpy'\n"
        "         or m.startswith('smartcut')\n"
        "         or m == 'PySide6.QtMultimedia'\n"
        "         or m.startswith('losslesscutter.player')\n"
        "         or m.startswith('losslesscutter.probe')\n"
        "         or m.startswith('losslesscutter.audio_player')\n"
        "         or m.startswith('losslesscutter.export_worker')\n"
        "         or m.startswith('losslesscutter.load_worker')\n"
        "         or m.startswith('losslesscutter.update_check')]\n"
        "print('HEAVY:', heavy)\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    r = subprocess.run([sys.executable, "-c", code], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    print("lazy startup imports OK")


def test_update_throttle() -> None:
    from losslesscutter.update_check import (
        already_checked_today, mark_checked_today,
    )

    class FakeSettings:
        def __init__(self):
            self.store = {}

        def value(self, key):
            return self.store.get(key)

        def setValue(self, key, value):
            self.store[key] = value

    s = FakeSettings()
    assert not already_checked_today(s, "2026-11-07")
    mark_checked_today(s, "2026-11-07")
    assert already_checked_today(s, "2026-11-07")
    assert not already_checked_today(s, "2026-11-08")
    print("update check throttle OK")


def make_mkv() -> Path:
    mkv = TMP / "sample.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=25",
         "-c:v", "libx264", "-b:v", "500k", "-an", str(mkv)],
        check=True)
    return mkv


def test_bitrate_sampling(mkv: Path) -> None:
    import av

    from losslesscutter.probe import estimate_video_bitrate
    with av.open(str(mkv)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        stored = vs.bit_rate
    est = estimate_video_bitrate(str(mkv))
    assert est is not None and est > 0, est
    if not stored:
        # MKV stores no stream bitrate: the value came from sampling.
        # testsrc at a 500k target lands well inside this band.
        assert 100_000 < est < 1_200_000, est
    print(f"bitrate estimate OK (stored={stored}, estimate={est})")


def test_timer_playback(mkv: Path) -> None:
    # Reuse the MKV (it has no audio track) for timer-clocked playback.
    from PySide6.QtWidgets import QApplication

    from losslesscutter.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    win.load_file(str(mkv))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None:
            break
        time.sleep(0.005)
    assert win.info is not None and not win.info.has_audio
    assert len(win._frame_times) == win.info.frame_count

    win.toggle_play()
    assert win._playing and not win._audio_mode
    # Pretend 1.0 s of wall clock has passed since play was pressed:
    # at 25 fps the playhead must be ~25 frames in, not 1.
    win._play_base_mono = time.monotonic() - 1.0
    win._play_base_media = 0.0
    win._play_tick()
    assert 23 <= win.current_frame <= 27, win.current_frame
    # Running past the end stops playback.
    win._play_base_mono = time.monotonic() - 60.0
    win._play_tick()
    assert not win._playing
    win.close()
    print("timer playback (wall clock, frame skipping) OK")


def test_load_cancel() -> None:
    from losslesscutter.probe import probe_media
    sample = ROOT / "test-media" / "h264.mp4"
    # A progress callback returning False must abort the scan - this is
    # the mechanism the window's close handler uses to avoid destroying
    # a running load thread.
    try:
        probe_media(str(sample), progress_cb=lambda frac: False)
        raise AssertionError("scan was not aborted")
    except InterruptedError:
        pass
    calls = []

    def cb(frac):
        calls.append(frac)
        return True

    info, mc = probe_media(str(sample), progress_cb=cb)
    assert info.frame_count == 144
    assert calls and calls[0] == 0.0
    assert all(f is None or 0.0 <= f <= 1.0 for f in calls)
    mc.close()
    print("load cancel (scan abort) OK")


def test_fps_and_time_stepping(mkv: Path) -> None:
    from fractions import Fraction

    from PySide6.QtWidgets import QApplication

    from losslesscutter.main_window import MainWindow
    from losslesscutter.probe import effective_fps

    # The reported real-world case: an MP4 declaring no rate, whose
    # guessed rate is the 1/1000 stream time base - 1128 frames over
    # 40.26 s is really ~28 fps, and the 1000 must not survive.
    fps = effective_fps(1000, 1128, Fraction(40261, 1000))
    assert abs(float(fps) - 28.02) < 0.1, fps
    assert effective_fps(None, 1128, Fraction(40261, 1000)) == fps
    # A sane declared rate is kept as-is.
    assert effective_fps(Fraction(30000, 1001), 3000,
                         Fraction(1001, 10)) == Fraction(30000, 1001)
    # Nothing to measure against: the fallback stands.
    assert effective_fps(None, 0, Fraction(0)) == 25
    print("effective fps OK")

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    win.load_file(str(mkv))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None:
            break
        time.sleep(0.005)
    assert win.info is not None

    shown = []

    def stub(idx):
        shown.append(idx)
        win.current_frame = idx

    win.show_frame = stub
    # Uniform real file: +2 s from frame 0 lands at ~frame 50 (25 fps).
    win.current_frame = 0
    win.step_seconds(2)
    assert 48 <= shown[-1] <= 52, shown
    # Sparse synthetic density (one frame every 2 s): +/-10 s must
    # move five frames BY TIME - frame-count math (10 s x fps) is the
    # reported bug and would clamp to the ends here.
    win._frame_times = [i * 2.0 for i in range(31)]
    win.current_frame = 15
    win.step_seconds(10)
    assert shown[-1] == 20, shown
    win.step_seconds(-10)
    assert shown[-1] == 15, shown
    # Landing rule: the frame on screen AT the target time (last frame
    # starting at or before it), never the frame after - off-grid
    # targets expose the difference.
    win._frame_times = [i * 2.0 + 0.5 for i in range(31)]
    win.current_frame = 15  # t = 30.5
    win.step_seconds(9)     # target 39.5: frame at 38.5, not 40.5
    assert shown[-1] == 19, shown
    win.step_seconds(-9)    # target 29.5: frame at 28.5
    assert shown[-1] == 14, shown
    # Frames sparser than the step itself still move by one.
    win._frame_times = [0.0, 15.0, 30.0]
    win.current_frame = 0
    win.step_seconds(10)
    assert shown[-1] == 1, shown
    # Go to a timestamp uses the same floor rule against the real
    # frame times; a bare integer still means a frame number.
    win._frame_times = [i * 2.0 + 0.5 for i in range(31)]
    win.goto_edit.setText("0:11")
    win._on_goto()
    assert shown[-1] == 5, shown  # frame at 10.5 is on screen at 0:11
    win.goto_edit.setText("90")
    win._on_goto()
    assert shown[-1] == 90, shown
    win.close()
    print("time-based stepping OK")


def test_load_export_exclusion(mkv: Path) -> None:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from losslesscutter.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    win.load_file(str(mkv))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        app.processEvents()
        if win._load_thread is None and win.info is not None:
            break
        time.sleep(0.005)
    assert win.info is not None and win.info.path == str(mkv)

    # Pretend an export is running: loading another file is refused and
    # the current file stays put.
    win._thread = QThread()
    win.load_file(str(ROOT / "test-media" / "h264.mp4"))
    assert "export" in win.status_label.text().lower(), \
        win.status_label.text()
    assert win.info.path == str(mkv)
    win._thread = None

    # Pretend a load is running: starting an export is refused.
    win._load_thread = QThread()
    win.start_export()
    assert "loading" in win.status_label.text().lower(), \
        win.status_label.text()
    assert win._worker is None
    win._load_thread = None
    win.close()
    print("load/export mutual exclusion OK")


def main() -> None:
    test_lazy_imports()
    test_update_throttle()
    test_load_cancel()
    mkv = make_mkv()
    test_bitrate_sampling(mkv)
    test_timer_playback(mkv)
    test_fps_and_time_stepping(mkv)
    test_load_export_exclusion(mkv)
    print("ALL STARTUP/PROBE TESTS PASSED")


if __name__ == "__main__":
    main()
