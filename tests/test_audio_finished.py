"""Regression test: AudioPlayer must report `finished` when the track
plays out, even when the sink never reports IdleState.

The old _pump only fired `finished` on QAudio.State.IdleState. On
some backends (Windows WASAPI) the sink never goes Idle when its
buffer drains, so the window never stopped playback at the natural
end: the Play button stayed on Pause and Space had to be pressed
twice (once to stop the already-ended playback, once to restart).
_track_finished now also accepts the sink having processed
essentially all written audio, or its buffer being entirely free
again, both gated on the decoder being exhausted with nothing
pending, so neither can fire mid-track.

The decision is tested directly with a fake sink (no audio device
needed); the window's reaction to `finished` is covered by the
natural-end probe in test_play_restart's flow.

Run: .venv/bin/python tests/test_audio_finished.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QAudio

from losslesscutter.audio_player import _FINISH_EPSILON_US, AudioPlayer

BYTES_PER_SEC = 48000 * 2 * 2  # OUT_RATE * stereo * s16


class FakeSink:
    """Duck-typed stand-in for QAudioSink."""

    def __init__(self, state=QAudio.State.ActiveState, processed=0,
                 free=0, bufsize=1 << 15):
        self._state = state
        self._processed = processed
        self._free = free
        self._bufsize = bufsize

    def state(self):
        return self._state

    def processedUSecs(self):
        return self._processed

    def bytesFree(self):
        return self._free

    def bufferSize(self):
        return self._bufsize


def make_player(eof=True, pending=b"", wrote=True, written=BYTES_PER_SEC,
                sink=None):
    p = AudioPlayer()
    p._eof = eof
    p._pending = pending
    p._wrote_any = wrote
    p._written_bytes = written
    p._bytes_per_sec = BYTES_PER_SEC
    p._sink = sink if sink is not None else FakeSink()
    return p


def main():
    app = QCoreApplication(sys.argv)

    # Not at the end yet: decoder still has data.
    assert not make_player(eof=False)._track_finished(), "fired before EOF"
    # Decoder exhausted but a chunk is still waiting to be written.
    assert not make_player(pending=b"x" * 100)._track_finished(), \
        "fired with pending data"
    # Nothing written at all (e.g. empty track): not a finish.
    assert not make_player(wrote=False, written=0)._track_finished(), \
        "fired without writing anything"

    # IdleState is the direct signal (the old behavior).
    assert make_player(sink=FakeSink(
        state=QAudio.State.IdleState))._track_finished(), \
        "IdleState did not finish"

    # No IdleState, but the sink processed essentially all written
    # audio (1 s written, 0.95 s processed, epsilon 0.1 s).
    assert make_player(sink=FakeSink(
        state=QAudio.State.ActiveState, processed=950_000,
        free=100))._track_finished(), \
        "processed-audio check did not finish"

    # No IdleState, sink only halfway through the written audio,
    # buffer still partly full: not finished.
    assert not make_player(sink=FakeSink(
        state=QAudio.State.ActiveState, processed=500_000,
        free=100))._track_finished(), \
        "fired halfway through the track"

    # No IdleState, sink only halfway through by processed time, but
    # its buffer is entirely free again: finished.
    assert make_player(sink=FakeSink(
        state=QAudio.State.ActiveState, processed=500_000,
        free=1 << 15))._track_finished(), \
        "empty-buffer check did not finish"

    # The epsilon is tight: just outside it, with a partly full
    # buffer, does not finish (1 s written, 0.89 s processed).
    assert not make_player(sink=FakeSink(
        state=QAudio.State.ActiveState,
        processed=1_000_000 - _FINISH_EPSILON_US - 10_000,
        free=100))._track_finished(), \
        "fired outside the finish epsilon"

    print("AUDIO FINISHED TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
