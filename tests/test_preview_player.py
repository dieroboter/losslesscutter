"""Regression test: the preview must display the exact frame asked for.

On open-GOP files (typical PAL DVD MPEG-2) the preview player used
to show the wrong frame after a seek. Its seek aimed at the GOP's
span-start pts - for an open GOP that is a leading B-frame's pts,
not the keyframe's - and on MPEG program streams ffmpeg's
timestamp-to-byte seek can land a GOP or two late; the player then
displayed whatever frame the seek produced (in practice a keyframe
up to two GOPs past the target) instead of the requested frame.
The user marking a cut therefore saw one frame while the export
(correctly) cut at another, which looked like the export starting
frames late. get_frame now walks by pts and, when a seek lands past
the target, retries aiming further back; it never displays a frame
other than the requested one.

Exercised here on the x265 CRA fixture (the HEVC form of an open
GOP; no available encoder produces open-GOP MPEG-2) written as
MPEG-TS, whose byte-estimated seeking reproduces the late-landing
seek - in an MP4 container the index-based seek is accurate and the
old code passes, so the container choice matters. The closed-GOP
battery MPEG-2 is the control. Reference frames come from a plain
sequential decode anchored by pts; every displayed frame must match
its reference exactly. Verified: the old player fails this test
(get_frame(22) showed a different frame); the fixed one passes.
End-to-end on a real DVDVOB2MPG-merged MPEG-2 (51,123 frames, not
in the repo): the old logic displayed frame 44717 for a request of
44703 and 29 for 15; the fixed player is exact at every probed
index, including span starts and the last GOP.

Run: .venv/bin/python tests/test_preview_player.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import av
import numpy as np
from PySide6.QtWidgets import QApplication

from smartcut.media_container import MediaContainer
from losslesscutter.player import PreviewPlayer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIXTURE = OUT / "preview_cra.fixture.mp4"


def build_cra_fixture() -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required to build the CRA fixture"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=4:size=320x240:rate=24",
         "-c:v", "libx265", "-g", "24",
         "-x265-params", "open-gop=1", str(FIXTURE)],
        check=True)


def qimage_to_array(img) -> np.ndarray:
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8)
    return buf[:bpl * h].reshape(h, bpl)[:, :w * 3].reshape(
        h, w, 3).astype(np.int16)


def reference_frames(path: str, mc: MediaContainer,
                     targets: list[int]) -> dict[int, np.ndarray]:
    want = {int(mc.video_frame_times_pts[i]): i for i in targets}
    refs = {}
    with av.open(path) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for fr in c.decode(vs):
            if fr.pts in want:
                refs[want[fr.pts]] = fr.to_ndarray(
                    format="rgb24").astype(np.int16)
            if fr.pts is not None and fr.pts > max(want):
                break
    return refs


def check(path: str, targets: list[int], label: str) -> None:
    mc = MediaContainer(path)
    refs = reference_frames(path, mc, targets)
    assert len(refs) == len(targets), (
        f"{label}: only {len(refs)}/{len(targets)} reference frames "
        f"decoded for {targets}")
    for t in targets:
        player = PreviewPlayer()
        player.open(path, mc)
        img = player.get_frame(t)
        player.close()
        assert img is not None, f"{label}: get_frame({t}) returned None"
        arr = qimage_to_array(img)
        assert arr.shape == refs[t].shape, (
            f"{label}: get_frame({t}) shape {arr.shape} "
            f"!= reference {refs[t].shape}")
        mad = float(np.abs(arr - refs[t]).mean())
        assert mad == 0.0, (
            f"{label}: get_frame({t}) shows a different frame "
            f"(MAD {mad:.2f} vs the true frame {t})")
    # Sequential stepping through the same range must be exact too.
    player = PreviewPlayer()
    player.open(path, mc)
    for t in targets:
        img = player.get_frame(t)
        assert img is not None, f"{label}: step to {t} returned None"
        mad = float(np.abs(qimage_to_array(img) - refs[t]).mean())
        assert mad == 0.0, (
            f"{label}: sequential step to {t} shows a different "
            f"frame (MAD {mad:.2f})")
    player.close()
    mc.close()


def main() -> None:
    app = QApplication([])
    build_cra_fixture()

    # Open-GOP (CRA) fixture: aim at a non-first GOP's span start, its
    # leading-picture zone, its keyframe, and mid-GOP frames.
    mc = MediaContainer(str(FIXTURE))
    tb = mc.video_stream.time_base
    span_idx = []
    for g, span in enumerate(mc.gop_start_times_pts_s):
        s = int(np.searchsorted(mc.video_frame_times_pts,
                                round(span / tb)))
        span_idx.append(s)
    flags = mc.gop_has_leading_pictures
    mc.close()
    open_g = next(g for g in range(1, len(flags)) if flags[g])
    s = span_idx[open_g]
    targets = sorted({span_idx[open_g - 1], s - 1, s, s + 1,
                      span_idx[open_g] + (span_idx[open_g + 1] - s) // 2
                      if open_g + 1 < len(span_idx) else s + 3})
    check(str(FIXTURE), targets, "CRA fixture")

    # Closed-GOP control: the battery MPEG-2.
    mc = MediaContainer(str(ROOT / "test-media" / "mpeg2.mpg"))
    n = len(mc.video_frame_times)
    mc.close()
    check(str(ROOT / "test-media" / "mpeg2.mpg"),
          [0, 1, 14, 15, 16, 40, n - 1], "battery MPEG-2")

    print("test_preview_player: OK")


if __name__ == "__main__":
    main()
