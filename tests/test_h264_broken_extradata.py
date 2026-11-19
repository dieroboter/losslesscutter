"""H.264 export with a truncated avcC extradata.

Some files carry an avcC that is only the 7-byte header (0 SPS, 0 PPS)
while the parameter sets only exist in-band in the keyframes. Decoders
tolerate that, but the muxer rejects the output header, so the export
used to fail with "[Errno 1094995529] Invalid data found when
processing input" naming the OUTPUT path. The engine now repairs the
extradata from the first keyframe before the header is written.

The broken fixture is built from test-media/h264.mp4 (valid avcC) by
remuxing it to MKV and patching the avcC's SPS count to 0, which
reproduces the exact failure mode without a binary fixture.
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
from smartcut.video_cutter import (
    VideoSettings,
    _build_h264_avcc,
    _first_keyframe_param_sets,
    _h264_extradata_param_sets,
)
from losslesscutter.segments import frame_end_time, frame_time

MEDIA = Path(__file__).resolve().parent.parent / "test-media"
OUT = Path(__file__).resolve().parent.parent / "test-out"
OUT.mkdir(exist_ok=True)

FPS = 24
GOP = 24
KEEPS = [(26, 54), (86, 125)]


def decode_frames(path):
    frames = []
    with av.open(str(path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for frame in c.decode(vs):
            frames.append(frame.to_ndarray(format="rgb24"))
    return frames


def decode_frame_fresh(path, index, gop_start_index, fps):
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


def _avcc_nal(nal: bytes) -> bytes:
    return len(nal).to_bytes(4, "big") + nal


def make_broken_mkv(src: Path, dst: Path) -> None:
    """Remux src to MKV with the SPS/PPS prepended to every keyframe
    packet (in-band, AVCC form), then patch the avcC's SPS count to 0
    so the extradata parses to no parameter sets. That is the
    real-world file's shape: a truncated avcC, with the parameter
    sets only in the keyframes. A fresh Packet built from bytes has
    time_base None, which makes the muxer misplace the next packet's
    timestamp, so copy the video time base onto it."""
    with av.open(str(src)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        sps, pps = _h264_extradata_param_sets(
            bytes(vs.codec_context.extradata))
    assert len(sps) == 1 and len(pps) == 1, \
        f"fixture param sets: sps={len(sps)} pps={len(pps)}"
    sps_bytes, pps_bytes = sps[0], pps[0]
    with av.open(str(src)) as inp:
        vs_in = next(s for s in inp.streams if s.type == "video")
        with av.open(str(dst), "w") as out:
            streams = {}
            for s in inp.streams:
                streams[s.index] = out.add_stream_from_template(s)
            for packet in inp.demux():
                if packet.dts is None:
                    continue
                if packet.stream.type == "video" and packet.is_keyframe:
                    new_data = (_avcc_nal(sps_bytes) + _avcc_nal(pps_bytes)
                                + bytes(packet))
                    np = av.Packet(new_data)
                    np.pts = packet.pts
                    np.dts = packet.dts
                    np.duration = packet.duration
                    np.stream = streams[packet.stream.index]
                    np.is_keyframe = True
                    np.time_base = vs_in.time_base
                    out.mux(np)
                else:
                    packet.stream = streams[packet.stream.index]
                    out.mux(packet)
    # Find the avcC in the file: SPS payload preceded by the 8-byte
    # avcC prefix (version/profile/compat/level/lengthSize/numSPS/len).
    data = bytearray(dst.read_bytes())
    off = data.find(sps_bytes)
    assert off != -1, "SPS not found in remuxed MKV"
    assert data[off - 8] == 1, "avcC header not found before SPS"
    assert data[off - 2:off] == len(sps_bytes).to_bytes(2, "big"), \
        "SPS length field mismatch"
    # numSPS is 3 bytes before the SPS payload (offset -3 from payload).
    data[off - 3] = 0xE0  # 0 SPS
    dst.write_bytes(bytes(data))


def test_broken_extradata_export():
    broken = OUT / "h264_broken_extradata.mkv"
    make_broken_mkv(MEDIA / "h264.mp4", broken)
    # The patched file's extradata really is broken now.
    with av.open(str(broken)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        sps, pps = _h264_extradata_param_sets(
            bytes(vs.codec_context.extradata))
        assert not sps and not pps, \
            f"patched extradata still parses: sps={len(sps)} pps={len(pps)}"
    # ... but the parameter sets are still in the first keyframe.
    sps, pps = _first_keyframe_param_sets(str(broken))
    assert len(sps) == 1 and len(pps) == 1, \
        f"keyframe param sets: sps={len(sps)} pps={len(pps)}"
    # avcC built from them round-trips.
    rebuilt = _build_h264_avcc(sps, pps)
    sps2, pps2 = _h264_extradata_param_sets(rebuilt)
    assert sps2 == sps and pps2 == pps, "rebuilt avcC does not round-trip"
    # Truncated 7-byte avcC header parses to no sets.
    assert _h264_extradata_param_sets(bytes.fromhex("01640020ffe000")) == ([], []), \
        "truncated avcC should parse to no sets"

    out = OUT / "h264_broken_extradata.out.mkv"
    mc = MediaContainer(str(broken))
    segments = [(frame_time(mc, a), frame_end_time(mc, b - 1))
                for a, b in KEEPS]
    stats = {}
    settings = VideoSettings(
        VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS,
        speed="medium", source_bitrate=estimate_bitrate(broken),
    )
    audio_info = AudioExportInfo(output_tracks=[
        AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
    ])
    err = smart_cut(mc, segments, str(out), audio_export_info=audio_info,
                    video_settings=settings, stats_out=stats)
    assert err is None, f"broken-extradata export failed: {err}"
    assert out.exists() and out.stat().st_size > 0, "no output file"

    expected_frames = sum(b - a for a, b in KEEPS)
    out_frames = decode_frames(out)
    assert len(out_frames) == expected_frames, \
        f"frames {len(out_frames)} != expected {expected_frames}"
    assert has_audio(out), "audio stream missing"
    # Copied-region frame: inside the second GOP of keep-segment 2.
    (a1, b1), (a2, b2) = KEEPS
    copied_src_idx = a2 + GOP + 2
    copied_out_idx = (b1 - a1) + (copied_src_idx - a2)
    out_gop_start = (b1 - a1) + GOP
    a = decode_frame_fresh(broken, copied_src_idx, a2 + GOP, FPS).astype(np.int16)
    b = decode_frame_fresh(out, copied_out_idx, out_gop_start, FPS).astype(np.int16)
    assert np.array_equal(a, b), "copied-region frame differs (not lossless)"
    # Recoded head frame of segment 1: H.264 CRF 1, near-identical.
    src_frames = decode_frames(broken)
    mad = float(np.abs(src_frames[a1 + 2].astype(np.int16)
                       - out_frames[2].astype(np.int16)).mean())
    assert mad < 6.0, f"recoded head frame MAD too high: {mad:.2f}"
    print(f"PASS broken-extradata: frames={len(out_frames)} "
          f"head_MAD={mad:.2f} stats={stats}")


def main():
    test_broken_extradata_export()
    print("H264 BROKEN EXTRADATA TEST PASSED")


if __name__ == "__main__":
    main()
