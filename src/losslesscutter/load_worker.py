"""Probes and indexes a media file on a worker thread.

The MediaContainer packet scan takes seconds on long files; running it
on the GUI thread froze the window for the whole scan. Imported lazily
by the main window at the first file load, so the engine (PyAV, numpy,
smartcut) stays out of the app's startup imports. The probe import
itself also happens here, on the worker thread: it used to ride along
with this module's import on the GUI thread, where its ~seconds of
library loading froze the window before any "loading" text could
paint. The phase signal announces that step so the window can say
what the pause is.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class LoadWorker(QObject):
    progress = Signal(int)                 # percent of the file indexed
    phase = Signal(str)                    # "libraries", then "indexing"
    finished = Signal(object, object)      # (MediaInfo, MediaContainer)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._last_pct = -1
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the scan to abort at its next progress checkpoint. Safe
        to call from the GUI thread (a plain flag, read by the worker)."""
        self._cancelled = True

    def _on_progress(self, fraction) -> bool:
        # Returning False aborts the MediaContainer scan.
        if self._cancelled:
            return False
        if fraction is not None:
            pct = int(fraction * 100)
            if pct != self._last_pct:
                self._last_pct = pct
                self.progress.emit(pct)
        return True

    @Slot()
    def run(self) -> None:
        try:
            self.phase.emit("libraries")
            from .probe import probe_media
            self.phase.emit("indexing")
            info, mc = probe_media(self._path, progress_cb=self._on_progress)
        except InterruptedError:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(info, mc)
