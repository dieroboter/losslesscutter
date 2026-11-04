"""LosslessCutter engine integration tests.

Expects test media in ../test-media (made by tools/make_test_media.sh).
Keep-ranges are specified in FRAMES so every boundary lands mid-GOP.
For each case, at the app's only quality (highest possible / LOSSLESS):
- the engine returns no exception
- the output decodes cleanly with the exact expected frame count
- the audio track survives (passthrough)
- a frame deep inside a copied GOP is pixel-identical to the source frame
- a frame inside the recoded head is pixel-identical for codecs with a
  lossless mode (H.264/HEVC/VP9/AV1), or near-identical for MPEG-2/MPEG-4
  (no lossless mode exists; finest quantizer q=1)
- export stats report recoded frames at both the beginning and the end
"""
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from smartcut.media_container import MediaContainer
from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.misc_data import AudioExportInfo, AudioExportSettings
from smartcut.smart_cut import smart_cut
from smartcut.video_cutter import VideoSettings

from losslesscutter.segments import frame_end_time, frame_time

MEDIA = Path(__file__).resolve().parent.parent / "test-media"
OUT = Path(__file__).resolve().parent.parent / "test-out"
OUT.mkdir(exist_ok=True)

# filename, fps, gop_frames, keep ranges in frames [(a1,b1),(a2,b2)] (b exclusive)
CASES = [
    ("h264.mp4", 24, 24, [(26, 54), (86, 125)]),
    ("hevc.mp4", 24, 24, [(26, 54), (86, 125)]),
    ("mpeg2.mpg", 25, 15, [(27, 52), (88, 124)]),
    ("vp9.webm", 24, 24, [(26, 54), (86, 125)]),
    ("av1.mp4", 24, 24, [(26, 54), (86, 125)]),
    ("mpeg4.avi", 24, 24, [(26, 54), (86, 125)]),
]
LOSSLESS_CODECS = ("h264", "hevc", "vp9", "av1")


def decode_frames(path):
    frames = []
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for frame in c.decode(vs):
            frames.append(frame.to_ndarray(format="rgb24"))
    return frames


def decode_frame_fresh(path, index, gop_start_index, fps):
    """Decode one frame in a fresh session seeked to its GOP's keyframe.

    Needed for copied-GOP checks: decoding straight through an SPS switch
    (lossless H.264 recode -> original SPS) makes ffmpeg keep the first
    SPS's chroma handling for a while, which perturbs RGB/YUV comparisons
    even though the copied slice data is bit-identical.
    """
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        target = int(Fraction(gop_start_index, fps) / vs.time_base)
        c.seek(target, stream=vs, backward=True, any_frame=False)
        frames = list(c.decode(vs))
        return frames[index - gop_start_index].to_ndarray(format="rgb24")


def has_audio(path):
    with av.open(str(path)) as c:
        return any(s.type == "audio" for s in c.streams)


def estimate_bitrate(path):
    total = 0
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        dur = float(c.duration / av.time_base) if c.duration else 0
        for p in c.demux(vs):
            total += p.size
    return int(total * 8 / dur) if dur else None


def run_case(fname, fps, gop, keeps):
    src = MEDIA / fname
    out = OUT / (src.stem + ".lossless.out" + src.suffix)
    expected_frames = sum(b - a for a, b in keeps)
    mc = MediaContainer(str(src))
    # Address segments exactly like the GUI does: via the engine's own frame
    # times (some containers, e.g. B-frame AVIs, offset frame times by one
    # frame; assuming frame a sits at a/fps would cut one frame early).
    segments = [(frame_time(mc, a), frame_end_time(mc, b - 1)) for a, b in keeps]
    stats = {}
    settings = VideoSettings(
        VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS,
        speed="medium", source_bitrate=estimate_bitrate(src),
    )
    audio_info = AudioExportInfo(output_tracks=[
        AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
    ])
    err = smart_cut(mc, segments, str(out), audio_export_info=audio_info,
                    video_settings=settings, stats_out=stats)
    assert err is None, f"{fname}: engine error: {err}"
    assert out.exists() and out.stat().st_size > 0

    src_frames = decode_frames(src)
    out_frames = decode_frames(out)
    got = len(out_frames)
    assert got == expected_frames, f"{fname}: frames {got} != expected {expected_frames}"
    assert has_audio(out), f"{fname}: audio stream missing"

    # Copied-region frame: inside the second GOP of keep-segment 2, compared
    # via fresh-seek decodes (see decode_frame_fresh).
    (a1, b1), (a2, b2) = keeps
    copied_src_idx = a2 + gop + 2
    copied_out_idx = (b1 - a1) + (copied_src_idx - a2)
    out_gop_start = (b1 - a1) + gop  # output index of source frame a2+gop (a keyframe)
    a = decode_frame_fresh(src, copied_src_idx, a2 + gop, fps).astype(np.int16)
    b = decode_frame_fresh(out, copied_out_idx, out_gop_start, fps).astype(np.int16)
    assert np.array_equal(a, b), f"{fname}: copied-region frame differs (not lossless)"

    # Recoded head frame of segment 1.
    head_src = src_frames[a1 + 2].astype(np.int16)
    head_out = out_frames[2].astype(np.int16)
    mad = float(np.abs(head_src - head_out).mean())
    if fname.startswith(LOSSLESS_CODECS):
        assert mad == 0.0, f"{fname}: lossless head frame not identical, MAD={mad:.3f}"
    else:
        assert mad < 6.0, f"{fname}: recoded head frame MAD too high: {mad:.2f}"

    assert stats.get("frames_recoded_start", 0) > 0, f"{fname}: no start recode in stats {stats}"
    assert stats.get("frames_recoded_end", 0) > 0, f"{fname}: no end recode in stats {stats}"
    print(f"PASS {fname}: frames={got} start={stats['frames_recoded_start']} "
          f"end={stats['frames_recoded_end']} middle={stats['frames_recoded_middle']} head_MAD={mad:.2f}")


def run_single_gop_case():
    """Kept range inside one long GOP: everything must be re-encoded, and
    the stats must say so in the 'whole' bucket instead of double-counting
    the same frames as both beginning and end."""
    src = MEDIA / "h264long.mp4"
    out = OUT / "h264long.whole.out.mp4"
    mc = MediaContainer(str(src))
    segments = [(frame_time(mc, 30), frame_end_time(mc, 77))]
    stats = {}
    settings = VideoSettings(VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS, speed="medium")
    audio_info = AudioExportInfo(output_tracks=[
        AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
    ])
    err = smart_cut(mc, segments, str(out), audio_export_info=audio_info,
                    video_settings=settings, stats_out=stats)
    assert err is None, f"h264long: engine error: {err}"
    frames = decode_frames(out)
    assert len(frames) == 48, f"h264long: frames {len(frames)} != 48"
    assert stats.get("frames_recoded_whole") == 48, f"h264long: whole bucket wrong: {stats}"
    assert stats.get("frames_recoded_start") == 0 and stats.get("frames_recoded_end") == 0, \
        f"h264long: start/end double-counted: {stats}"
    print(f"PASS h264long.mp4 single-GOP: whole={stats['frames_recoded_whole']} kept={stats['frames_kept_approx']}")


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for fname, fps, gop, keeps in CASES:
        if only and only not in fname:
            continue
        run_case(fname, fps, gop, keeps)
    if not only or "h264long" in only:
        run_single_gop_case()
    print("ALL ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()
