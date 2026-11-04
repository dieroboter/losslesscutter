"""End-to-end test of the WINDOWS portable build, run by the portable's own
python.exe (under Wine here, or real Windows). Relies entirely on the
portable's python312._pth for imports - no sys.path help.

Usage: python.exe test_wine_portable.py <input-video> <output-video>
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy

SKIP_GUI = bool(os.environ.get("LC_SKIP_GUI"))
if not SKIP_GUI:
    import PySide6
    from PySide6.QtWidgets import QApplication
    print("PySide6:", PySide6.__version__)

from smartcut.media_container import MediaContainer
from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.misc_data import AudioExportInfo, AudioExportSettings
from smartcut.smart_cut import smart_cut
from smartcut.video_cutter import VideoSettings

print("python:", sys.version.split()[0])
print("PyAV:", av.__version__, "numpy:", numpy.__version__)

src, out = sys.argv[1], sys.argv[2]

# Engine cut through the exact call the GUI worker makes
from losslesscutter.segments import frame_end_time, frame_time

mc = MediaContainer(src)
total = len(mc.video_frame_times)
a, b = total // 6 + 3, total // 3 + 2  # mid-GOP boundaries: forces head+tail recodes
segments = [(frame_time(mc, a), frame_end_time(mc, b - 1))]
settings = VideoSettings(VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS, speed="medium")
audio_info = AudioExportInfo(output_tracks=[
    AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
])
stats = {}
err = smart_cut(mc, segments, out, audio_export_info=audio_info,
                video_settings=settings, stats_out=stats)
assert err is None, f"engine error: {err}"
print("engine stats:", stats)

n = 0
has_audio = False
with av.open(out) as c:
    has_audio = any(s.type == "audio" for s in c.streams)
    vs = next(s for s in c.streams if s.type == "video")
    for _ in c.decode(vs):
        n += 1
print("output frames:", n, "expected:", b - a, "audio:", has_audio)
assert n == b - a, "frame count mismatch"
assert stats.get("frames_recoded_start", 0) > 0 or stats.get("frames_recoded_end", 0) > 0

if SKIP_GUI:
    print("WINE/PORTABLE ENGINE TEST PASSED (GUI skipped)")
    sys.exit(0)

# GUI: create the window, load the file, build a plan
from losslesscutter.main_window import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.load_file(src)
assert win.info is not None and win.info.frame_count == total
win.show_frame(a)
win.set_mark_in()
win.show_frame(b - 1)
win.set_mark_out()
win.add_selection()
plan = win.status_label.text()
print("plan readout:", plan)
assert "beginning" in plan and "end" in plan
print("WINE/PORTABLE TEST PASSED")
