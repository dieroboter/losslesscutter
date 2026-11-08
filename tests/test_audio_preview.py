#!/usr/bin/env python3
"""Audio preview tests.

The PCM pipeline (PcmDecoder) is verified deterministically: a generated
file with beeps at known times must decode to PCM with energy in the
right windows, and seeks must land sample-accurately. The window wiring
is verified against this machine's audio device - in the test VM there
is none (null device), which exercises the silent-fallback path. Actual
audibility on real hardware is not testable here.
"""
import math
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from losslesscutter.audio_player import PcmDecoder, QT_AUDIO_AVAILABLE

TMP = Path("/tmp/lc-audio-test")
TMP.mkdir(exist_ok=True)
SRC_RATE = 22050
OUT_RATE = 48000


def make_tone_wav(path: Path) -> None:
    """3 s mono: 880 Hz beeps at 0.5-0.8 s and 2.0-2.3 s, else silence."""
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


def decode_all(path: str, start: float) -> np.ndarray:
    d = PcmDecoder(path)
    try:
        data = b"".join(d.read_chunks(start))
    finally:
        d.close()
    return np.frombuffer(data, dtype=np.int16).reshape(-1, 2).astype(np.float64) / 32768.0


def rms(a: np.ndarray, t0: float, t1: float) -> float:
    seg = a[int(t0 * OUT_RATE):int(t1 * OUT_RATE)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def main() -> None:
    wav = TMP / "tone.wav"
    make_tone_wav(wav)

    pcm = decode_all(str(wav), 0.0)
    dur = len(pcm) / OUT_RATE
    assert abs(dur - 3.0) < 0.15, dur
    assert rms(pcm, 0.10, 0.40) < 0.01
    assert rms(pcm, 0.55, 0.75) > 0.10
    assert rms(pcm, 1.20, 1.80) < 0.01
    assert rms(pcm, 2.05, 2.25) > 0.10
    print(f"pcm full decode OK ({dur:.2f}s)")

    pcm = decode_all(str(wav), 1.0)
    assert abs(len(pcm) / OUT_RATE - 2.0) < 0.15
    assert rms(pcm, 0.0, 0.8) < 0.01
    assert rms(pcm, 1.05, 1.25) > 0.10
    print("pcm seek OK")

    pcm = decode_all(str(wav), 2.1)
    assert abs(len(pcm) / OUT_RATE - 0.9) < 0.15
    assert rms(pcm, 0.0, 0.15) > 0.10  # starts inside the beep: head trim
    print("pcm head trim OK")

    mp4 = TMP / "tone.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
         "-i", str(wav), "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(mp4)],
        check=True)
    pcm = decode_all(str(mp4), 0.0)
    assert rms(pcm, 0.58, 0.72) > 0.08
    assert rms(pcm, 1.30, 1.70) < 0.02
    assert rms(pcm, 2.08, 2.22) > 0.08
    print("pcm mp4/aac OK")

    if QT_AUDIO_AVAILABLE:
        from PySide6.QtMultimedia import QMediaDevices
        from PySide6.QtWidgets import QApplication

        from losslesscutter.main_window import MainWindow

        app = QApplication([])
        win = MainWindow()
        win.show()
        win.load_file(str(mp4))
        for _ in range(3000):
            app.processEvents()
            if win._load_thread is None and win.info is not None:
                break
            time.sleep(0.005)
        assert win.info is not None and win.info.has_audio
        assert len(win._frame_times) == win.info.frame_count
        assert win.mute_btn.isEnabled() and win.volume_slider.isEnabled()
        # Position -> frame mapping (25 fps: frame 37 starts at 1.48 s).
        win._playing = True
        win._audio_mode = True
        win._on_audio_position(1.5)
        assert win.current_frame == 37, win.current_frame
        win._on_audio_position(0.0)
        assert win.current_frame == 0
        win._stop_play()
        print("gui audio position mapping OK")

        if QMediaDevices.defaultAudioOutput().isNull():
            # No device here: Play must fall back to silent timer
            # playback instead of wedging in audio mode.
            win.toggle_play()
            assert win._playing and win._audio_mode
            for _ in range(300):
                app.processEvents()
                if not win._audio_mode:
                    break
                time.sleep(0.01)
            assert win._playing and not win._audio_mode, \
                "no fallback after audio failure"
            assert "silently" in win.status_label.text()
            win._stop_play()
            print("gui audio fallback OK")
        win.close()

    print("ALL AUDIO TESTS PASSED")


if __name__ == "__main__":
    main()
