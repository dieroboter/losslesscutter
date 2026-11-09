"""Regression test: a cut exactly on an open GOP's span start must
land on the marked frame.

Open GOPs (typical PAL DVD and broadcast MPEG-2) carry leading
pictures: B-frames presented before the GOP's keyframe but decoded
after it, referencing the previous GOP. The cut planner used to
treat a keep range starting exactly at such a GOP's span start as a
clean GOP-aligned copy. The copied leading pictures then had no
reference in the output, decoders silently dropped them, and the
export started that many frames late (2 frames on a VTS VOB,
measured end to end on the real file: mark 24 exported from 26;
marks at 20/25/26/27 were exact). The planner now recodes a segment
that starts a keep range at an open GOP's span start; the recode
path primes the decoder from the previous GOP and reproduces the
leading pictures exactly.

Two layers are tested:

1. Detection - MediaContainer flags GOPs whose presentation span
   starts before the keyframe's own pts. An x265 CRA encode (the
   HEVC form of an open GOP) must flag its non-first GOPs; the
   battery's closed-GOP MPEG-2 must flag none. (No available encoder
   produces open-GOP MPEG-2, and x264's open-GOP keyframes are
   non-IDR, which the engine deliberately never registers as GOP
   starts - so no synthetic MPEG-2 fixture can exercise this.)

2. Planning - make_cut_segments over a stub container carrying
   VOB-shaped GOP tables: a full-overlap segment that starts a keep
   range at an open GOP's span start must be planned as a recode;
   the following full GOP stays a copy; with no leading pictures
   anywhere, the same range stays all-copy.

Run: .venv/bin/python tests/test_opengop_boundary.py
"""
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from smartcut.media_container import MediaContainer
from smartcut.smart_cut import make_adjusted_segment_times, make_cut_segments

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIXTURE = OUT / "opengop_cra.fixture.mp4"


def build_cra_fixture() -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required to build the CRA fixture"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=4:size=320x240:rate=24",
         "-c:v", "libx265", "-g", "24",
         "-x265-params", "open-gop=1", str(FIXTURE)],
        check=True)


def test_detection() -> None:
    build_cra_fixture()
    mc = MediaContainer(str(FIXTURE))
    flags = mc.gop_has_leading_pictures
    mc.close()
    assert len(flags) >= 2 and any(flags[1:]), (
        f"CRA fixture: no non-first GOP flagged as open: {flags}")

    mc = MediaContainer(str(ROOT / "test-media" / "mpeg2.mpg"))
    flags = mc.gop_has_leading_pictures
    mc.close()
    assert flags and not any(flags), (
        f"closed-GOP MPEG-2 must flag no open GOPs: {flags}")
    print("PASS open-GOP detection (CRA flagged, closed MPEG-2 not)")


def stub_container(has_leading: list[bool]) -> SimpleNamespace:
    # VOB-shaped tables: 12-frame GOPs at 25 fps. Only the fields
    # make_cut_segments reads are provided.
    return SimpleNamespace(
        video_stream=object(),
        start_time=Fraction(0),
        duration=Fraction(36, 25),
        gop_start_times_pts_s=[Fraction(0), Fraction(12, 25),
                               Fraction(24, 25)],
        gop_start_times_dts=[0, 43200, 86400],
        gop_end_times_dts=[39600, 82800, 126000],
        gop_has_leading_pictures=has_leading,
    )


def recode_flags(mc, segments):
    # Address segments exactly like smart_cut does (its end-of-file
    # clamp is what makes a keep ending at the file's end count as
    # full overlap for the last GOP).
    adjusted = make_adjusted_segment_times(segments, mc)
    return [c.require_recode for c in make_cut_segments(mc, adjusted)]


def test_planning() -> None:
    keep = [(Fraction(12, 25), Fraction(36, 25))]  # GOP1 + GOP2, full

    flags = recode_flags(stub_container([True, True, True]), keep)
    assert flags == [True, False], (
        f"open GOP at keep start must recode, next GOP stays copy: {flags}")

    flags = recode_flags(stub_container([False, False, False]), keep)
    assert flags == [False, False], (
        f"closed GOPs must stay all-copy: {flags}")

    # A mid-GOP start still plans the ordinary partial recode first.
    keep_mid = [(Fraction(13, 25), Fraction(36, 25))]
    flags = recode_flags(stub_container([True, True, True]), keep_mid)
    assert flags == [True, False], (
        f"mid-GOP start: partial recode then copy expected: {flags}")
    print("PASS open-GOP planning (boundary segment recodes, copies kept)")


def main() -> None:
    test_detection()
    test_planning()
    print("ALL OPEN-GOP TESTS PASSED")


if __name__ == "__main__":
    main()
