"""Regression test: one corrupt audio packet must not silence the
whole track in preview playback.

Files joined by external merge tools can carry a stray
undecodable audio packet (a real DVDVOB2MPG merge has one as the
very first audio packet: a 240-byte fragment the AC-3 decoder
rejects). PcmDecoder used PyAV's bulk decode, which aborts on the
first bad packet - the whole file then "plays without audio" with
an avcodec_send_packet InvalidData error. The decoder now skips
invalid-data packets and resyncs on the next one, like other
players do.

The fixture corrupts exactly one audio packet's sync word in an
otherwise valid tone file; playback must still deliver the full
duration, including the beep after the bad packet.

Run: .venv/bin/python tests/test_bad_audio_packet.py
"""
import math
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from losslesscutter.audio_player import OUT_RATE, PcmDecoder

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "test-out"
TMP.mkdir(exist_ok=True)
SRC_RATE = 22050


def make_tone_wav(path: Path) -> None:
    frames = bytearray()
    for i in range(SRC_RATE * 3):
        t = i / SRC_RATE
        v = 0
        if (0.5 <= t < 0.8) or (2.0 <= t < 2.3):
            v = int(0.5 * 32767 * math.sin(2 * math.pi * 880 * t))
        frames += v.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SRC_RATE)
        w.writeframes(bytes(frames))


def corrupt_first_audio_packet(data: bytearray) -> None:
    """Flip the AC-3 sync word of the first audio PES packet.

    Walks the MPEG program stream properly (pack headers and
    length-delimited PES packets), so a start-code pattern inside
    video data cannot be mistaken for the audio packet."""
    i = 0
    n = len(data)
    while i + 4 <= n:
        if data[i:i + 3] != b"\x00\x00\x01":
            i += 1
            continue
        sid = data[i + 3]
        if sid == 0xBA:  # pack header: 10 bytes + stuffing length
            stuffing = data[i + 13] & 0x07 if i + 13 < n else 0
            i += 14 + stuffing
            continue
        if sid in (0xBD, 0xC0):  # private stream 1 (AC-3) / MPEG audio
            # PES: 6-byte start+length, 2 flag bytes, header length.
            hdr_len = data[i + 8]
            payload = i + 9 + hdr_len
            # The AC-3 sync word (0x0B77) sits within the first few
            # payload bytes (after the DVD substream prefix, if any).
            for j in range(payload, min(payload + 16, n - 1)):
                if data[j] == 0x0B and data[j + 1] == 0x77:
                    data[j] = 0xFF
                    data[j + 1] = 0xFF
                    return
            raise AssertionError("AC-3 sync word not found in first "
                                 "audio packet")
        if sid == 0xB9:  # program end
            break
        # Other PES: skip by its length field when it has one.
        if i + 6 <= n:
            length = (data[i + 4] << 8) | data[i + 5]
            i += 6 + length if length else 4
        else:
            break
    raise AssertionError("no audio PES packet found")


def decode_all(path: str, start: float) -> np.ndarray:
    d = PcmDecoder(path)
    try:
        data = b"".join(d.read_chunks(start))
    finally:
        d.close()
    return np.frombuffer(data, dtype=np.int16).reshape(-1, 2) \
        .astype(np.float64) / 32768.0


def rms(a: np.ndarray, t0: float, t1: float) -> float:
    seg = a[int(t0 * OUT_RATE):int(t1 * OUT_RATE)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def main() -> None:
    wav = TMP / "badpkt_tone.wav"
    make_tone_wav(wav)
    good = TMP / "badpkt_good.mpg"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
         "-i", str(wav), "-map", "0:v", "-map", "1:a",
         "-c:v", "mpeg2video", "-c:a", "ac3", "-f", "vob", str(good)],
        check=True)

    raw = bytearray(good.read_bytes())
    corrupt_first_audio_packet(raw)
    bad = TMP / "badpkt_corrupt.mpg"
    bad.write_bytes(bytes(raw))

    pcm = decode_all(str(good), 0.0)
    assert abs(len(pcm) / OUT_RATE - 3.0) < 0.15
    assert rms(pcm, 2.05, 2.25) > 0.08, "control file lost its beep"
    print("control file decodes OK")

    # The corrupted file: previously this raised InvalidDataError
    # and the whole track stayed silent. Now the bad packet is
    # skipped and everything else plays.
    pcm = decode_all(str(bad), 0.0)
    dur = len(pcm) / OUT_RATE
    assert abs(dur - 3.0) < 0.2, f"duration {dur:.2f}s - track aborted?"
    assert rms(pcm, 1.20, 1.80) < 0.02, "silence window has audio"
    assert rms(pcm, 2.05, 2.25) > 0.08, "beep after the bad packet lost"
    print(f"corrupt-first-packet file decodes OK ({dur:.2f}s)")

    print("test_bad_audio_packet: OK")


if __name__ == "__main__":
    main()
