"""Preview aspect ratio: anamorphic sources must display at their
flagged display aspect, not at the raw pixel ratio. A 720x576 file
flagged 16:9 (SAR 64:45) must come out of the player as a 1024x576
image; square-pixel files must pass through untouched. Covers the
plain frame, the interlaced field view and the 2x picture.

Run: .venv/bin/python tests/test_preview_aspect.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from smartcut.media_container import MediaContainer  # noqa: E402
from losslesscutter.player import PreviewPlayer  # noqa: E402

OUT = ROOT / "test-out"
ANA_PROG = OUT / "aspect_ana_prog.mpg"
ANA_INT = OUT / "aspect_ana_int.mpg"


def build_fixtures() -> None:
    OUT.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=25:duration=2",
         "-c:v", "mpeg2video", "-q:v", "2", "-aspect", "16:9",
         "-f", "vob", str(ANA_PROG)], check=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=720x576:rate=50:duration=2",
         "-vf", "tinterlace=interleave_top",
         "-c:v", "mpeg2video", "-q:v", "2", "-flags", "+ildct+ilme",
         "-top", "1", "-aspect", "16:9", "-f", "vob", str(ANA_INT)],
        check=True)


def check(path, label, frames):
    mc = MediaContainer(str(path))
    p = PreviewPlayer()
    p.open(str(path), mc)
    try:
        for name, image in frames(p):
            assert image is not None, f"{label}: {name} produced no image"
            assert (image.width(), image.height()) == (1024, 576), (
                f"{label}: {name} is {image.width()}x{image.height()}, "
                f"expected 1024x576 (16:9 from SAR 64:45)")
            print(f"{label}: {name} 1024x576 OK")
    finally:
        p.close()
        mc.close()


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("SKIP: ffmpeg not on PATH")
        return
    build_fixtures()
    QGuiApplication([])
    check(ANA_PROG, "anamorphic progressive",
          lambda p: [("frame", p.get_frame(10)),
                     ("display", p.get_frame_display(10))])
    check(ANA_INT, "anamorphic interlaced",
          lambda p: [("field view", p.get_frame_display(10)),
                     ("2x picture", p.get_frame_2x(10, 0))])
    # Square-pixel control: the deinterlace fixture is 720x576 SAR 1.
    square = OUT / "deint_tff.mpg"
    if square.exists():
        mc = MediaContainer(str(square))
        p = PreviewPlayer()
        p.open(str(square), mc)
        try:
            image = p.get_frame(10)
            assert (image.width(), image.height()) == (720, 576), (
                f"square-pixel frame changed size: "
                f"{image.width()}x{image.height()}")
            print("square-pixel control: 720x576 untouched OK")
        finally:
            p.close()
            mc.close()
    print("PREVIEW ASPECT TEST PASSED")


if __name__ == "__main__":
    main()
