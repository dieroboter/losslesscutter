"""Regression test: recoded cut-point frames of an interlaced
source must stay interlaced.

The MPEG-2/MPEG-4 encoder was created without the interlaced-DCT
flag, so it wrote the recoded frames at a cut as progressive
pictures even though their content is two fields. Players showed
those few frames un-deinterlaced - visible interlace combing on
exactly the recoded head of a cut (5 frames on a real DVD merge:
cut at 19858, recode covered 19858-19862) - while the copied
frames around them were flagged correctly. The pixels were never
wrong (MAD ~2), only the flag. _ensure_enc_codec now probes the
source's first frame and sets AV_CODEC_FLAG_INTERLACED_DCT for
interlaced MPEG-2/MPEG-4 sources; INTERLACED_ME is deliberately
not set (it wrecked quality in testing, MAD ~13 vs ~1-2).

Fixtures are synthetic interlaced encodes (testsrc2 50p run
through tinterlace), cut mid-GOP so the head segment is recoded.
The battery's progressive MPEG-2 is the control: its recoded
frames must stay progressive.

Run: .venv/bin/python tests/test_interlaced_recode.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import av
import numpy as np

from smartcut.media_container import MediaContainer
from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.misc_data import AudioExportInfo, AudioExportSettings
from smartcut.smart_cut import smart_cut
from smartcut.video_cutter import VideoSettings
from losslesscutter.segments import positive_segments

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIX2 = OUT / "interlaced_mpeg2.fixture.mpg"
FIX4 = OUT / "interlaced_mpeg4.fixture.avi"


def build_fixtures() -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required to build the fixtures"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=3:size=704x576:rate=50",
         "-vf", "tinterlace=mode=merge", "-c:v", "mpeg2video",
         "-g", "12", "-flags", "+ildct", "-q:v", "2",
         "-f", "vob", str(FIX2)], check=True)
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=2:size=352x288:rate=50",
         "-vf", "tinterlace=mode=merge", "-c:v", "mpeg4",
         "-g", "12", "-flags", "+ildct", "-q:v", "3",
         str(FIX4)], check=True)


def decode_props(path, count):
    """(interlaced flags, pixel arrays) of the first `count` frames."""
    flags, frames = [], []
    with av.open(path) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for fr in c.decode(vs):
            flags.append(bool(fr.interlaced_frame))
            frames.append(fr.to_ndarray(format="rgb24").astype(np.int16))
            if len(frames) >= count:
                break
    return flags, frames


def source_frames(path, mc, start, count):
    want = {int(mc.video_frame_times_pts[start + i]): start + i
            for i in range(count)}
    got = {}
    with av.open(path) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for fr in c.decode(vs):
            if fr.pts in want:
                got[want[fr.pts]] = fr.to_ndarray(
                    format="rgb24").astype(np.int16)
            if fr.pts is not None and fr.pts > max(want):
                break
    assert len(got) == count, f"only {len(got)}/{count} source frames"
    return [got[start + i] for i in range(count)]


def run_case(src_path, out_path, keep, label):
    mc = MediaContainer(str(src_path))
    segs = positive_segments(mc, [keep], "keep")
    ai = AudioExportInfo(output_tracks=[
        AudioExportSettings(codec="passthru") for _ in mc.audio_tracks])
    settings = VideoSettings(VideoExportMode.SMARTCUT,
                             VideoExportQuality.LOSSLESS,
                             speed="medium", source_bitrate=None)
    err = smart_cut(mc, segs, str(out_path), audio_export_info=ai,
                    video_settings=settings)
    assert err is None, err
    start, end = keep
    head = 7  # the mid-GOP head recode spans at most one GOP (12)
    flags, frames = decode_props(str(out_path), end - start + 1)
    assert len(frames) == end - start + 1, (
        f"{label}: {len(frames)} frames, expected {end - start + 1}")
    refs = source_frames(str(src_path), mc, start, head)
    mc.close()
    return flags, frames, refs, head


def main() -> None:
    build_fixtures()

    for src, out, label in ((FIX2, OUT / "il2_out.mpg", "MPEG-2"),
                            (FIX4, OUT / "il4_out.avi", "MPEG-4")):
        flags, frames, refs, head = run_case(src, out, (17, 44), label)
        assert all(flags), (
            f"{label}: output frames lost interlacing: {flags}")
        for i in range(head):
            mad = float(np.abs(frames[i] - refs[i]).mean())
            assert mad < 6, (
                f"{label}: recoded head frame {i} MAD {mad:.2f} "
                "(quality regressed?)")

    # Control: progressive source stays progressive after a recode.
    src = ROOT / "test-media" / "mpeg2.mpg"
    flags, frames, refs, head = run_case(
        src, OUT / "il_prog_out.mpg", (27, 52), "progressive MPEG-2")
    assert not any(flags), (
        f"progressive MPEG-2: recoded frames flagged interlaced: {flags}")

    print("test_interlaced_recode: OK")


if __name__ == "__main__":
    main()
