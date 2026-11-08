"""Regression test: files that start mid-GOP must still export video.

A file whose first packets precede its first keyframe (split VOBs -
VTS_01_5.VOB begins with the tail of a GOP whose I-frame is in
VTS_01_4.VOB - captures started mid-stream, etc.) used to export
audio only. MediaContainer closed that partial leading GOP when its
first keyframe arrived, adding a GOP end time with no matching start
and shifting every later start/end pairing by one GOP; each pair's
end landed before its start, so the video cutter fetched an empty
packet window for every segment and muxed no video at all. The audio
cutter slices by time rather than GOP windows, so the audio survived
and nothing reported an error.

The fixture is built from the battery's mpeg2.mpg by dropping exactly
one packet - the first GOP's keyframe packet - which puts the file in
the same state. Run: .venv/bin/python tests/test_midgop_start.py
"""
import sys
from pathlib import Path

import av

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from smartcut.media_container import MediaContainer
from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.misc_data import AudioExportInfo, AudioExportSettings
from smartcut.smart_cut import smart_cut
from smartcut.video_cutter import VideoSettings

from losslesscutter.segments import frame_end_time, frame_time

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "test-media" / "mpeg2.mpg"
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIXTURE = OUT / "mpeg2_midgop.fixture.mpg"
OUTPUT = OUT / "mpeg2_midgop.out.mpg"


def build_fixture() -> None:
    dropped = False
    with av.open(str(SRC)) as inp, av.open(str(FIXTURE), "w") as out:
        stream_map = {s.index: out.add_stream_from_template(s)
                      for s in inp.streams}
        for packet in inp.demux():
            if packet.pts is None:
                continue  # trailing flush packet demux() yields per stream
            if (not dropped and packet.stream.type == "video"
                    and packet.is_keyframe):
                dropped = True
                continue  # the file now starts mid-GOP, like a split VOB
            packet.stream = stream_map[packet.stream.index]
            out.mux(packet)
    assert dropped, "source had no video keyframe packet to drop"


def count_decoded_frames(path: Path) -> int:
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        return sum(1 for _ in c.decode(vs))


def has_stream(path: Path, kind: str) -> bool:
    with av.open(str(path)) as c:
        return any(s.type == kind for s in c.streams)


def main() -> None:
    build_fixture()

    # The fixture really is in the pathological state: video packets
    # exist before the first keyframe.
    mc = MediaContainer(str(FIXTURE))
    assert mc.video_stream is not None
    assert mc.video_keyframe_indices[0] > 0, (
        "fixture does not start mid-GOP: first keyframe is frame 0")

    # The invariant the bug broke: the GOP start/end lists stay paired,
    # and no GOP ends before it starts.
    assert len(mc.gop_start_times_dts) == len(mc.gop_end_times_dts), (
        f"GOP list length mismatch: {len(mc.gop_start_times_dts)} starts, "
        f"{len(mc.gop_end_times_dts)} ends")
    bad = [(s, e) for s, e in zip(mc.gop_start_times_dts,
                                  mc.gop_end_times_dts) if e < s]
    assert not bad, f"GOP end before start (shifted pairing): {bad[:3]}"

    # A keep range well past the partial head GOP (mc frame indices,
    # addressed exactly like the GUI addresses them).
    a, b = 30, 90
    segments = [(frame_time(mc, a), frame_end_time(mc, b - 1))]
    settings = VideoSettings(VideoExportMode.SMARTCUT,
                             VideoExportQuality.LOSSLESS,
                             speed="medium", source_bitrate=None)
    audio_info = AudioExportInfo(output_tracks=[
        AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
    ])
    err = smart_cut(mc, segments, str(OUTPUT), audio_export_info=audio_info,
                    video_settings=settings)
    mc.close()
    assert err is None, f"engine error: {err}"

    # The regression itself: the output must contain the video, with
    # exactly the kept frames decodable, and the audio alongside.
    assert has_stream(OUTPUT, "video"), "output has no video stream"
    got = count_decoded_frames(OUTPUT)
    assert got == b - a, f"output frames {got} != expected {b - a}"
    assert has_stream(OUTPUT, "audio"), "output has no audio stream"

    print(f"PASS mid-GOP start: {b - a} frames exported with video + audio")


if __name__ == "__main__":
    main()
