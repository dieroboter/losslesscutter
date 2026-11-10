"""Regression test: MPEG-2 cut-point recodes must run at the fixed
quantizer (q=1 at lossless quality), not in bitrate mode.

The encoder options carried {'q': '1'}, but under PyAV that entry
alone never engages fixed-quantizer mode: the encoder stayed in
bitrate mode at whatever bitrate the context happened to carry
(the 200 kb/s factory default when the source stream declares
none), so the few recoded frames at each cut came out visibly
blockier than the copied material around them. On a real DVD cut
(head of a keep starting mid-GOP) the recoded I-frame was 23 KB
at 40 dB against the source where a true q=1 encode gives 72 KB
at 45 dB, and later recoded frames sagged to 39 dB. The fix sets
the encoder context's qscale flag when the options carry 'q'.

The fixture is deliberately noisy (noise stresses the encoder, so
bitrate mode and fixed-q separate cleanly). The assertion is on
the decoded pixels: every recoded head frame must sit at q=1
quality (PSNR >= 42 dB against the source frame); the broken
encoder drops to ~33 dB on this fixture.

Run: .venv/bin/python tests/test_mpeg2_recode_quality.py
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
from smartcut.video_cutter import VideoSettings
from losslesscutter.segments import frame_end_time, frame_time

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "test-out"
OUT.mkdir(exist_ok=True)
FIX = OUT / "noisy_mpeg2.fixture.mpg"

KEEP_START, KEEP_END = 32, 74  # mid-GOP start: head recode 32..44


def build_fixture() -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required to build the fixture"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=3:size=720x576:rate=25",
         "-vf", "noise=alls=14:allf=t+u",
         "-c:v", "mpeg2video", "-b:v", "12000k", "-maxrate", "15000k",
         "-bufsize", "7500k", "-qmax", "8", "-bf", "0", "-g", "15",
         "-f", "vob", str(FIX)], check=True)


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


def main() -> None:
    build_fixture()
    out_path = OUT / "noisy_mpeg2_cut.mpg"
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
    recoded = int(stats.get("frames_recoded_start") or 0)
    assert recoded >= 8, f"expected a real head recode, got {recoded}"
    src = frames(str(FIX), KEEP_START, recoded)
    got = frames(str(out_path), 0, recoded)
    worst = 99.0
    for k in range(recoded):
        p = psnr(src[KEEP_START + k], got[k])
        worst = min(worst, p)
        assert p >= 42.0, (
            f"recoded head frame {k} at {p:.1f} dB - the recode is "
            f"running in bitrate mode, not at the fixed quantizer")
    print(f"PASS: {recoded} recoded head frames all at q=1 quality "
          f"(worst {worst:.1f} dB)")
    mc.close()


if __name__ == "__main__":
    main()
