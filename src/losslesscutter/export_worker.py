"""Runs the smartcut engine on a worker thread with progress + cancel."""
from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import QObject, Signal, Slot

from smartcut.media_container import MediaContainer
from smartcut.misc_data import AudioExportInfo, AudioExportSettings
from smartcut.smart_cut import CancelObject, smart_cut
from smartcut.video_cutter import VideoSettings


class _Progress:
    """Matches the engine's ProgressCallback protocol (emit(int percent))."""

    def __init__(self, signal):
        self._signal = signal

    def emit(self, value: int) -> None:
        self._signal.emit(int(value))


class ExportWorker(QObject):
    progress = Signal(int)
    succeeded = Signal(dict, str)
    failed = Signal(str)

    def __init__(self, path: str, segments: list[tuple[Fraction, Fraction]],
                 out_path: str, settings: VideoSettings) -> None:
        super().__init__()
        self._path = path
        self._segments = segments
        self._out_path = out_path
        self._settings = settings
        self._cancel = CancelObject()

    def cancel(self) -> None:
        self._cancel.cancelled = True

    @Slot()
    def run(self) -> None:
        mc = None
        try:
            mc = MediaContainer(self._path)
            stats: dict = {}
            # All audio tracks passthrough (the engine exports no audio at
            # all unless this is passed explicitly).
            audio_info = AudioExportInfo(output_tracks=[
                AudioExportSettings(codec="passthru") for _ in mc.audio_tracks
            ])
            err = smart_cut(
                mc, self._segments, self._out_path,
                audio_export_info=audio_info,
                video_settings=self._settings,
                progress=_Progress(self.progress),
                cancel_object=self._cancel,
                stats_out=stats,
            )
            if self._cancel.cancelled:
                self.failed.emit("Export cancelled.")
            elif err is not None:
                self.failed.emit(f"Export failed: {err}")
            else:
                self.succeeded.emit(stats, self._out_path)
        except Exception as exc:  # engine raises for unsupported streams etc.
            self.failed.emit(f"Export failed: {exc}")
        finally:
            if mc is not None:
                try:
                    mc.close()
                except Exception:
                    pass
