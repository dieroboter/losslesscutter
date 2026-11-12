"""Regression test: a lossless-quality H.264 cut must not switch
profiles mid-file.

x264 lossless (CRF 0) requires High 4:4:4 Predictive profile, so
a recoded segment carried a High 4:4:4 SPS (profile 244, sps-id=3)
while the copied material - and the output header - used the
source's profile (often Main 77). The file then switched profile
mid-stream at each recode. An earlier fix (b070fc3) declared both
profiles in the header (avcC), but the corruption in VLC and
MPC-HC/LAV persisted: the head recode played clean, the first
corrupt frame was the tail IDR itself (output frame 5339), so the
switch up to High 4:4:4 mid-stream is what those players choke on,
header or not. ffmpeg (4.4 and 8.1.2 alike) decodes the switched
file pixel-perfect, so only on-device playback shows it.

The fix: H.264 recodes at the LOSSLESS preset use CRF 1 instead
of CRF 0 - the finest lossy step, visually indistinguishable from
lossless - in the source's own profile, so the stream never
switches profile. A source already in High 4:4:4 keeps true CRF 0.

Assertions on a Main-profile fixture cut mid-GOP at both ends:
  1. the output avcC lists a single SPS, Main 77 (no 244 anywhere)
  2. the in-band SPS of the recoded segments is Main 77 too
  3. the recoded frames are near-lossless against the source
     (worst PSNR >= 45 dB; measured 58 dB on this fixture)

Run: .venv/bin/python tests/test_h264_recode_avcc.py
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
from smartcut.misc_data import AudioExportInfo
from smartcut.smart_cut import smart_cut
from smartcut.video_cutter import (
    VideoSettings,
    _h264_extradata_param_sets,
)
from losslesscutter.segments import frame_end_time, frame_time

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIX = OUT / "main_h264.fixture.mp4"

KEEP_START, KEEP_END = 20, 58  # head recode 20..23, tail recode 48..57


def build_fixture() -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required to build the fixture"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=3:size=320x180:rate=25",
         "-c:v", "libx264", "-profile:v", "main", "-g", "12",
         "-pix_fmt", "yuv420p", str(FIX)], check=True)


def frames(path, start, count):
    res = {}
    with av.open(path) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for i, fr in enumerate(c.decode(vs)):
            if start <= i < start + count:
                res[i] = fr.to_ndarray(format="yuv420p").astype(int)
            if i >= start + count:
                break
    return res


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def length_prefixed_nals(packet_data: bytes) -> list[bytes]:
    """Split MP4-style length-prefixed NAL units."""
    nals = []
    i = 0
    while i + 4 <= len(packet_data):
        n = int.from_bytes(packet_data[i:i + 4], "big")
        if n < 1 or i + 4 + n > len(packet_data):
            break
        nals.append(packet_data[i + 4:i + 4 + n])
        i += 4 + n
    return nals


def in_band_sps(path):
    """SPS NAL payloads carried in-band in the file's packets."""
    found = []
    with av.open(path) as c:
        vs = next(s for s in c.streams if s.type == "video")
        for packet in c.demux(vs):
            for nal in length_prefixed_nals(bytes(packet)):
                if nal and (nal[0] & 0x1F) == 7 and nal not in found:
                    found.append(nal)
    return found


def main() -> None:
    build_fixture()
    out_path = OUT / "main_h264_cut.mp4"
    mc = MediaContainer(str(FIX))
    keep = [(frame_time(mc, KEEP_START), frame_end_time(mc, KEEP_END))]
    settings = VideoSettings(VideoExportMode.SMARTCUT,
                             VideoExportQuality.LOSSLESS,
                             speed="medium", source_bitrate=None)
    stats: dict = {}
    err = smart_cut(mc, keep, str(out_path), video_settings=settings,
                    audio_export_info=AudioExportInfo(output_tracks=[]),
                    stats_out=stats)
    assert err is None, f"export failed: {err}"
    assert int(stats.get("frames_recoded_start") or 0) >= 4, (
        f"expected a head recode, got {stats}")
    assert int(stats.get("frames_recoded_end") or 0) >= 8, (
        f"expected a tail recode, got {stats}")

    with av.open(str(out_path)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        sps, _pps = _h264_extradata_param_sets(vs.codec_context.extradata)
    profiles = [s[1] for s in sps]
    assert profiles == [77], (
        f"avcC must list only the source Main SPS, got profiles "
        f"{profiles} - the recode is switching profiles mid-file")

    in_profiles = [s[1] for s in in_band_sps(str(out_path))]
    assert 244 not in in_profiles, (
        f"recoded segments carry a High 4:4:4 SPS in-band: {in_profiles}")

    recoded = int(stats["frames_recoded_start"]) + int(stats["frames_recoded_end"])
    src = frames(str(FIX), KEEP_START, KEEP_END - KEEP_START)
    got = frames(str(out_path), 0, KEEP_END - KEEP_START)
    worst = 99.0
    for k in range(KEEP_END - KEEP_START):
        p = psnr(src[KEEP_START + k], got[k])
        worst = min(worst, p)
        assert p >= 45.0, f"frame {k} of the cut at {p:.1f} dB - not near-lossless"
    print(f"PASS: avcC declares profile {profiles}, no 244 in-band, "
          f"{recoded} recoded frames near-lossless (worst {worst:.1f} dB)")
    mc.close()


if __name__ == "__main__":
    main()
