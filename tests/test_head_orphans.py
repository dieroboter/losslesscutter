"""Head-of-file orphan frames: a file that starts with an open GOP
(leading pictures presented before the first keyframe but
referencing a previous GOP that is not in the file) must not count
those pictures as frames. No decoder can produce them, so counting
them shifts every frame number and time in the file: the preview
showed frame 15 for frames 0 and 1 and ran two frames early for
the rest of a real user's MPEG-2 capture.

The fixture is built by encoding an open-GOP H.264 clip and
cutting it at the second keyframe packet, which leaves exactly
that structure. A closed-GOP MPEG-2 file is the control.

Run: .venv/bin/python tests/test_head_orphans.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import av  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from smartcut.media_container import MediaContainer  # noqa: E402
from losslesscutter.player import PreviewPlayer  # noqa: E402

OUT = ROOT / "test-out"
SRC = OUT / "orphan_src.mp4"
CUT = OUT / "orphan_cut.mp4"
CONTROL = OUT / "orphan_control.mpg"


def build_fixtures() -> None:
    OUT.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=352x288:rate=25:duration=4",
         "-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-bf", "3",
         "-x264-params", "open-gop=1", "-pix_fmt", "yuv420p", str(SRC)],
        check=True)
    # Cut at the second keyframe packet: the file then starts with
    # that keyframe followed by its leading pictures (pts below the
    # keyframe's), which reference the dropped first GOP.
    with av.open(str(SRC)) as cin:
        vs = cin.streams.video[0]
        packets = [p for p in cin.demux(vs) if p.pts is not None]
    keyframes = [i for i, p in enumerate(packets) if p.is_keyframe]
    assert len(keyframes) >= 2, "fixture source has too few keyframes"
    kept = packets[keyframes[1]:]
    orphans = [p for p in kept if int(p.pts) < int(kept[0].pts)]
    assert orphans, "fixture has no leading pictures before its keyframe"
    with av.open(str(SRC)) as cin:
        vs = cin.streams.video[0]
        with av.open(str(CUT), "w") as cout:
            out_stream = cout.add_stream_from_template(vs)
            for i, p in enumerate(cin.demux(vs)):
                if p.pts is None:
                    continue
                if i >= keyframes[1]:
                    p.stream = out_stream
                    cout.mux(p)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=352x288:rate=25:duration=2",
         "-c:v", "mpeg2video", "-q:v", "2", "-g", "15", "-bf", "2",
         "-f", "vob", str(CONTROL)], check=True)


def decoded(path):
    frames = []
    with av.open(str(path)) as c:
        for f in c.decode(video=0):
            frames.append((int(f.pts), f.to_ndarray(format="rgb24")))
    return frames


def img_array(img):
    a = np.frombuffer(img.constBits(), dtype=np.uint8)
    return a.reshape(img.height(), img.width(), 3).copy()


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("SKIP: ffmpeg not on PATH")
        return
    build_fixtures()
    QGuiApplication([])

    frames = decoded(CUT)
    mc = MediaContainer(str(CUT))
    try:
        grid = mc.video_frame_times_pts
        assert int(grid[0]) == frames[0][0], (
            f"grid starts at {int(grid[0])}, first decodable frame "
            f"is {frames[0][0]}")
        assert len(grid) == len(frames), (
            f"grid counts {len(grid)} frames, the decoder produces "
            f"{len(frames)}")
        assert mc.gop_has_leading_pictures[0] is False, (
            "first GOP still marked as having leading pictures")
        print(f"orphan file: grid == {len(frames)} decodable frames, "
              f"starts at the keyframe")
        p = PreviewPlayer()
        p.open(str(CUT), mc)
        try:
            for idx in (0, 1, 2, 3):
                shown = img_array(p.get_frame(idx))
                mad = np.abs(shown.astype(int)
                             - frames[idx][1].astype(int)).mean()
                assert mad < 1.0, f"frame {idx} shows another frame (MAD {mad})"
            print("orphan file: preview frames 0-3 exact")
        finally:
            p.close()
    finally:
        mc.close()

    control_frames = decoded(CONTROL)
    mc = MediaContainer(str(CONTROL))
    try:
        assert len(mc.video_frame_times_pts) == len(control_frames), (
            "closed-GOP control changed frame count")
        print(f"control: {len(control_frames)} frames, grid unchanged")
    finally:
        mc.close()
    print("HEAD ORPHANS TEST PASSED")


if __name__ == "__main__":
    main()
