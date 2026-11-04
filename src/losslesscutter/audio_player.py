"""Audio preview playback: PyAV decodes, Qt's QAudioSink plays.

The video preview (player.py) is a custom frame-accurate PyAV decoder, so
audio follows the same route instead of a second media player: PyAV
decodes the first audio track to PCM and QAudioSink writes it to the
default output device. Playback position comes from the sink (samples
actually played), which makes audio the master clock for the video
frames while sound is on.

QAudioSink lives in QtMultimedia, which ships in PySide6-Addons, not
PySide6-Essentials. When it (or an output device) is unavailable the app
still runs: QT_AUDIO_AVAILABLE is False / play() fails with a message
and the window falls back to silent, timer-clocked playback.

Times everywhere are seconds relative to the container start, the same
units as PreviewPlayer.frame_time.
"""
from __future__ import annotations

import av
from PySide6.QtCore import QObject, QTimer, Signal, Slot

try:
    from PySide6.QtMultimedia import (
        QAudio, QAudioFormat, QAudioSink, QMediaDevices,
    )
    QT_AUDIO_AVAILABLE = True
except Exception:  # PySide6-Addons not installed
    QT_AUDIO_AVAILABLE = False

OUT_RATE = 48000
OUT_CHANNELS = 2
_BYTES_PER_SAMPLE = 2  # s16
_PUMP_MS = 20
_BUFFER_BYTES = 1 << 15


class PcmDecoder:
    """Seekable PCM source over a file's first audio track. Pure PyAV
    (no Qt), so the decode/resample pipeline is testable headless."""

    def __init__(self, path: str, rate: int = OUT_RATE,
                 channels: int = OUT_CHANNELS) -> None:
        self._container = av.open(path)
        stream = next(
            (s for s in self._container.streams if s.type == "audio"), None)
        if stream is None:
            self._container.close()
            raise ValueError("No audio stream in this file.")
        self._stream = stream
        self.rate = rate
        self.channels = channels
        start = self._container.start_time
        self.start_offset = (start / av.time_base) if start is not None else 0.0
        self._resampler = self._new_resampler()

    def _new_resampler(self) -> av.AudioResampler:
        layout = "stereo" if self.channels == 2 else "mono"
        return av.AudioResampler(format="s16", layout=layout, rate=self.rate)

    def close(self) -> None:
        try:
            self._container.close()
        except Exception:
            pass

    def read_chunks(self, start_time: float):
        """Yield PCM byte chunks starting at start_time (relative
        seconds), trimmed to sample accuracy at the head."""
        stream = self._stream
        tb = stream.time_base
        target_abs = start_time + self.start_offset
        self._container.seek(
            int(target_abs / float(tb)), stream=stream,
            backward=True, any_frame=False)
        # The seek invalidates anything the resampler had buffered.
        self._resampler = self._new_resampler()
        frame_bytes = self.channels * _BYTES_PER_SAMPLE
        drop = 0          # samples still to trim from the head
        armed = False     # drop computed from the first kept frame
        for frame in self._container.decode(stream):
            if frame.pts is not None:
                f_start = float(frame.pts * tb) - self.start_offset
                f_dur = frame.samples / frame.sample_rate
                if f_start + f_dur <= start_time:
                    continue
                if not armed and f_start < start_time:
                    drop = int(round((start_time - f_start) * self.rate))
                    armed = True
            for out in self._resampler.resample(frame):
                data = out.to_ndarray().tobytes()
                if drop:
                    n = min(drop, len(data) // frame_bytes)
                    data = data[n * frame_bytes:]
                    drop -= n
                if data:
                    yield data
        for out in self._resampler.resample(None):
            data = out.to_ndarray().tobytes()
            if drop:
                n = min(drop, len(data) // frame_bytes)
                data = data[n * frame_bytes:]
                drop -= n
            if data:
                yield data


class AudioPlayer(QObject):
    """Plays a file's audio track from a given position. Lives on its
    own QThread; the window drives it through the command signals it is
    connected to (play/stop/set_volume/set_muted are slots)."""

    position_changed = Signal(float)   # relative seconds actually played
    finished = Signal()                # track played out to its end
    failed = Signal(str)               # playback impossible; stay silent

    def __init__(self) -> None:
        super().__init__()
        self._decoder: PcmDecoder | None = None
        self._chunks = None
        self._sink = None
        self._io = None
        self._timer: QTimer | None = None
        self._pending = b""
        self._base = 0.0
        self._eof = False
        self._wrote_any = False
        self._volume = 1.0
        self._muted = False
        self.active = False

    # ------------------------------------------------------------ commands
    @Slot(str, float)
    def play(self, path: str, start_time: float) -> None:
        self._teardown()
        if not QT_AUDIO_AVAILABLE:
            self.failed.emit(
                "Audio preview needs PySide6-Addons, which is not installed.")
            return
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.failed.emit("No audio output device found.")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(OUT_RATE)
        fmt.setChannelCount(OUT_CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            pref = device.preferredFormat()
            fmt.setSampleRate(pref.sampleRate())
            fmt.setChannelCount(pref.channelCount())
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                self.failed.emit("No usable audio output format found.")
                return
        try:
            self._decoder = PcmDecoder(
                path, rate=fmt.sampleRate(), channels=fmt.channelCount())
            self._chunks = self._decoder.read_chunks(start_time)
        except Exception as exc:
            self.failed.emit(f"Audio preview unavailable: {exc}")
            self._teardown()
            return
        self._sink = QAudioSink(device, fmt)
        self._sink.setBufferSize(_BUFFER_BYTES)
        self._sink.setVolume(0.0 if self._muted else self._volume)
        self._io = self._sink.start()
        if self._io is None:
            self.failed.emit("Could not open the audio output device.")
            self._teardown()
            return
        self._base = start_time
        self._eof = False
        self._wrote_any = False
        self._pending = b""
        self.active = True
        self._timer = QTimer(self)
        self._timer.setInterval(_PUMP_MS)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        self._pump()

    @Slot()
    def stop(self) -> None:
        self._teardown()

    @Slot(float)
    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        if self._sink is not None and not self._muted:
            self._sink.setVolume(self._volume)

    @Slot(bool)
    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if self._sink is not None:
            self._sink.setVolume(0.0 if muted else self._volume)

    # ------------------------------------------------------------- pumping
    def _position(self) -> float:
        if self._sink is None:
            return self._base
        return self._base + self._sink.processedUSecs() / 1_000_000.0

    def _pump(self) -> None:
        if self._sink is None or self._io is None:
            return
        try:
            while True:
                if not self._pending:
                    if self._eof:
                        break
                    try:
                        self._pending = next(self._chunks)
                    except StopIteration:
                        self._eof = True
                        break
                free = self._sink.bytesFree()
                if free <= 0:
                    break
                n = self._io.write(self._pending[:free])
                if n <= 0:
                    break
                self._wrote_any = True
                self._pending = self._pending[n:]
        except Exception as exc:
            self._teardown()
            self.failed.emit(f"Audio preview stopped: {exc}")
            return
        self.position_changed.emit(self._position())
        if (self._eof and not self._pending and self._wrote_any
                and self._sink.state() == QAudio.State.IdleState):
            self._teardown()
            self.finished.emit()
        elif (self._sink.error() != QAudio.Error.NoError
                and self._sink.state() == QAudio.State.StoppedState):
            self._teardown()
            self.failed.emit("Audio output error.")

    def _teardown(self) -> None:
        self.active = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None
            self._io = None
        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None
        self._chunks = None
        self._pending = b""
