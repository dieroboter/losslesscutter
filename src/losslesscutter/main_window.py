"""LosslessCutter main window: a VideoReDo-style cutting interface.

Layout follows the classic smart-editor workflow: preview on top, transport
with frame/GOP stepping, mark in/out, a selections list, then a save panel
with quality (SMC-style) and speed choices. Cutting only: there is no
full-recode mode anywhere in this app; if a file cannot be smart-cut the
export fails with an explanation instead of re-encoding the whole file.
"""
from __future__ import annotations

import os
from fractions import Fraction

from PySide6.QtCore import QEvent, Qt, QThread, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from smartcut.media_utils import VideoExportMode, VideoExportQuality
from smartcut.smart_cut import make_adjusted_segment_times, make_cut_segments
from smartcut.video_cutter import VideoSettings

from . import __version__
from .export_worker import ExportWorker
from .player import PreviewPlayer
from .probe import MediaInfo, probe_media
from .segments import (
    describe_cut, frame_end_time, frame_time, parse_goto, positive_segments,
)
from .update_check import UpdateChecker, is_newer

MEDIA_FILTER = (
    "Video files (*.mp4 *.mkv *.mov *.avi *.mpg *.mpeg *.m2ts *.mts *.ts "
    "*.webm *.flv *.wmv *.vob);;All files (*)"
)

QUALITY_ITEMS = [
    (VideoExportQuality.SOURCE_MATCHED, "Source matched (recommended)"),
    (VideoExportQuality.LOSSLESS, "Lossless"),
    (VideoExportQuality.NEAR_LOSSLESS, "Near lossless"),
    (VideoExportQuality.INDISTINGUISHABLE, "Almost indistinguishable"),
    (VideoExportQuality.HIGH, "High"),
    (VideoExportQuality.NORMAL, "Normal"),
    (VideoExportQuality.LOW, "Low"),
]
SPEED_ITEMS = ["ultrafast", "fast", "medium", "slow", "slower"]


def format_timecode(t: Fraction) -> str:
    ms_total = int(round(float(t) * 1000))
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"LosslessCutter {__version__}")
        self.resize(1060, 760)
        self.setAcceptDrops(True)
        _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(_icon):
            self.setWindowIcon(QIcon(_icon))

        self.info: MediaInfo | None = None
        self.mc = None
        self.player = PreviewPlayer()
        self.current_frame = 0
        self.mark_in: int | None = None
        self.mark_out: int | None = None
        self.selections: list[tuple[int, int]] = []
        self._playing = False
        self._thread: QThread | None = None
        self._worker: ExportWorker | None = None
        self._update_thread: QThread | None = None
        self._update_checker: UpdateChecker | None = None

        self._build_ui()
        self.goto_edit.installEventFilter(self)
        self._build_shortcuts()
        self._play_timer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.timeout.connect(self._play_tick)
        self._set_controls_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self.open_btn = QPushButton("Open...")
        self.open_btn.clicked.connect(self.open_file_dialog)
        top.addWidget(self.open_btn)
        self.file_label = QLabel("No file loaded")
        self.file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.file_label, 1)
        self.info_label = QLabel("")
        self.info_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.info_label)
        # Filled in (as a link to the release page) only when the startup
        # update check finds a newer version; empty otherwise.
        self.update_label = QLabel("")
        self.update_label.setOpenExternalLinks(True)
        top.addWidget(self.update_label)
        root.addLayout(top)

        self.preview = QLabel("Drop a video file here, or click Open...")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: black; color: #888;")
        self.preview.setMinimumHeight(320)
        root.addWidget(self.preview, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider)
        root.addWidget(self.slider)

        transport = QHBoxLayout()
        self.prev_gop_btn = QPushButton("Prev GOP")
        self.prev_gop_btn.clicked.connect(lambda: self.step_gop(-1))
        self.back_btn = QPushButton("-10 sec")
        self.back_btn.clicked.connect(lambda: self.step_frames(-self._ten_seconds()))
        self.prev_frame_btn = QPushButton("-1 Frame")
        self.prev_frame_btn.clicked.connect(lambda: self.step_frames(-1))
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.next_frame_btn = QPushButton("+1 Frame")
        self.next_frame_btn.clicked.connect(lambda: self.step_frames(1))
        self.fwd_btn = QPushButton("+10 sec")
        self.fwd_btn.clicked.connect(lambda: self.step_frames(self._ten_seconds()))
        self.next_gop_btn = QPushButton("Next GOP")
        self.next_gop_btn.clicked.connect(lambda: self.step_gop(1))
        for b in (self.prev_gop_btn, self.back_btn, self.prev_frame_btn, self.play_btn,
                  self.next_frame_btn, self.fwd_btn, self.next_gop_btn):
            transport.addWidget(b)
        self.time_label = QLabel("00:00:00.000   Frame 0 / 0")
        self.time_label.setMinimumWidth(250)
        transport.addWidget(self.time_label)
        transport.addWidget(QLabel("Go to:"))
        self.goto_edit = QLineEdit()
        self.goto_edit.setPlaceholderText("frame # or 1:23.5")
        self.goto_edit.setToolTip(
            "Jump to a frame number (1250) or a timestamp (1:23.5). "
            "Type or paste, then press Enter."
        )
        self.goto_edit.setFixedWidth(120)
        self.goto_edit.returnPressed.connect(self._on_goto)
        transport.addWidget(self.goto_edit)
        root.addLayout(transport)

        marks = QHBoxLayout()
        self.set_in_btn = QPushButton("Set Start  [ I ]")
        self.set_in_btn.clicked.connect(self.set_mark_in)
        self.set_out_btn = QPushButton("Set End  [ O ]")
        self.set_out_btn.clicked.connect(self.set_mark_out)
        self.marks_label = QLabel("Start: -    End: -")
        self.add_sel_btn = QPushButton("Add Selection")
        self.add_sel_btn.clicked.connect(self.add_selection)
        marks.addWidget(self.set_in_btn)
        marks.addWidget(self.set_out_btn)
        marks.addWidget(self.marks_label, 1)
        marks.addWidget(self.add_sel_btn)
        root.addLayout(marks)

        sel_row = QHBoxLayout()
        self.sel_list = QListWidget()
        self.sel_list.setMaximumHeight(110)
        sel_row.addWidget(self.sel_list, 1)
        sel_btns = QVBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Cut mode: keep the selected parts", "keep")
        self.mode_combo.addItem("Scene mode: remove the selected parts", "remove")
        self.mode_combo.currentIndexChanged.connect(self._update_plan)
        self.remove_sel_btn = QPushButton("Remove Selection")
        self.remove_sel_btn.clicked.connect(self.remove_selection)
        self.clear_sel_btn = QPushButton("Clear All")
        self.clear_sel_btn.clicked.connect(self.clear_selections)
        sel_btns.addWidget(self.mode_combo)
        sel_btns.addWidget(self.remove_sel_btn)
        sel_btns.addWidget(self.clear_sel_btn)
        sel_row.addLayout(sel_btns)
        root.addLayout(sel_row)

        self.cut_label = QLabel("")
        self.cut_label.setWordWrap(True)
        self.cut_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.cut_label)

        export_box = QHBoxLayout()
        quality_label = QLabel("Re-encode quality: Highest possible (lossless)")
        quality_label.setToolTip(
            "The parts at cut points that must be re-encoded are always encoded "
            "at the highest quality the codec offers. Everything else is copied "
            "bit-identical. MPEG-2 / MPEG-4 have no lossless mode; they use "
            "their finest quantizer."
        )
        export_box.addWidget(quality_label)
        export_box.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        for s in SPEED_ITEMS:
            self.speed_combo.addItem(s.capitalize(), s)
        self.speed_combo.setCurrentText("Medium")
        export_box.addWidget(self.speed_combo)
        root.addLayout(export_box)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.out_edit = QLineEdit()
        out_row.addWidget(self.out_edit, 1)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_output)
        out_row.addWidget(self.browse_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.start_export)
        out_row.addWidget(self.save_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_export)
        out_row.addWidget(self.cancel_btn)
        root.addLayout(out_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        # A long status text (e.g. the Done line with a full output path)
        # must wrap inside the window, never push the window wider.
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.status_label)

        self.setCentralWidget(central)

    def _build_shortcuts(self) -> None:
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ShortcutContext.ApplicationShortcut)
            s.activated.connect(fn)
            return s
        self._shortcuts = [
            sc("Space", self.toggle_play),
            sc("I", self.set_mark_in),
            sc("O", self.set_mark_out),
            sc("Left", lambda: self.step_frames(-1)),
            sc("Right", lambda: self.step_frames(1)),
            sc("Shift+Left", lambda: self.step_frames(-self._ten_seconds())),
            sc("Shift+Right", lambda: self.step_frames(self._ten_seconds())),
        ]

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self.slider, self.prev_gop_btn, self.back_btn, self.prev_frame_btn,
                  self.play_btn, self.next_frame_btn, self.fwd_btn, self.next_gop_btn,
                  self.goto_edit,
                  self.set_in_btn, self.set_out_btn, self.add_sel_btn, self.remove_sel_btn,
                  self.clear_sel_btn, self.mode_combo, self.speed_combo,
                  self.out_edit, self.browse_btn, self.save_btn):
            w.setEnabled(enabled)

    def _ten_seconds(self) -> int:
        if self.info is None:
            return 250
        return max(1, int(self.info.fps * 10))

    # -------------------------------------------------------------- loading
    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open video", "", MEDIA_FILTER)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        self.status_label.setText(f"Loading {os.path.basename(path)} ...")
        QApplication.processEvents()
        try:
            info, mc = probe_media(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open file", str(exc))
            self.status_label.setText("Ready")
            return
        if self.mc is not None:
            try:
                self.mc.close()
            except Exception:
                pass
        self.player.close()
        self.info, self.mc = info, mc
        self.player.open(path, mc)
        self.current_frame = 0
        self.mark_in = None
        self.mark_out = None
        self.selections = []
        self.sel_list.clear()
        self.cut_label.setText("")
        self.file_label.setText(os.path.basename(path))
        self.info_label.setText(
            f"{info.codec}  {info.width}x{info.height}  {float(info.fps):.3f} fps  "
            f"{info.frame_count} frames  {format_timecode(info.duration)}"
        )
        self.slider.setRange(0, max(0, info.frame_count - 1))
        self.slider.setValue(0)
        stem, ext = os.path.splitext(path)
        self.out_edit.setText(stem + "_cut" + ext)
        self._update_marks_label()
        self._set_controls_enabled(True)
        self.show_frame(0)
        self.status_label.setText(
            "Loaded. Mark a start and end, add selections, then Save. "
            "Only the small bits at cut points are re-encoded; everything else is copied bit-identical."
        )

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(
            url.isLocalFile() for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_file(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    # ------------------------------------------------------------- playback
    def show_frame(self, index: int) -> None:
        if self.info is None or self.mc is None:
            return
        index = max(0, min(index, self.info.frame_count - 1))
        image = self.player.get_frame(index)
        self.current_frame = index
        if image is not None:
            pix = QPixmap.fromImage(image)
            scaled = pix.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        t = frame_time(self.mc, index)
        self.time_label.setText(f"{format_timecode(t)}   Frame {index} / {self.info.frame_count - 1}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.info is not None:
            self.show_frame(self.current_frame)

    def _on_slider(self, value: int) -> None:
        self._stop_play()
        self.show_frame(value)

    def _on_goto(self) -> None:
        if self.info is None:
            return
        target = parse_goto(
            self.goto_edit.text(), self.info.fps, self.info.frame_count)
        if target is None:
            self.status_label.setText(
                "Could not understand the Go to entry - enter a frame number "
                "or a timestamp like 1:23.5.")
            self.goto_edit.selectAll()
            return
        self._stop_play()
        self.show_frame(target)
        # Hand the keyboard back to the window so the transport shortcuts
        # (arrows, Space, I/O) work again without another click.
        self.goto_edit.clearFocus()

    def mousePressEvent(self, event) -> None:
        # Clicking anywhere outside the Go to box (clicks on buttons and
        # other focus-taking widgets move focus by themselves; clicks on
        # labels or empty areas reach this handler) also releases it.
        if self.goto_edit.hasFocus():
            self.goto_edit.clearFocus()
        super().mousePressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if (obj is self.goto_edit
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self.goto_edit.clearFocus()
            return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------------- update check
    def start_update_check(self) -> None:
        """Ask GitHub for the latest release, once, in the background.
        Called by the app entry point, not the constructor, so tests that
        build the window directly never trigger a network call."""
        if self._update_thread is not None:
            return
        self._update_checker = UpdateChecker()
        self._update_thread = QThread(self)
        self._update_checker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_checker.run)
        self._update_checker.finished.connect(self._on_update_checked)
        self._update_checker.finished.connect(self._update_thread.quit)
        self._update_thread.start()

    def _on_update_checked(self, result) -> None:
        if not result:
            return
        version, url = result
        if is_newer(version, __version__):
            self.update_label.setText(
                f'<a href="{url}">Update available: LosslessCutter {version}</a>')

    def step_frames(self, delta: int) -> None:
        self._stop_play()
        self.show_frame(self.current_frame + delta)

    def step_gop(self, direction: int) -> None:
        self._stop_play()
        if self.info is None:
            return
        keys = self.info.keyframe_indices
        if direction > 0:
            target = next((k for k in keys if k > self.current_frame), self.info.frame_count - 1)
        else:
            target = max([k for k in keys if k < self.current_frame], default=0)
        self.show_frame(target)

    def toggle_play(self) -> None:
        if self.info is None:
            return
        if self._playing:
            self._stop_play()
        else:
            self._playing = True
            self.play_btn.setText("Pause")
            self._play_tick()

    def _stop_play(self) -> None:
        self._playing = False
        self._play_timer.stop()
        self.play_btn.setText("Play")

    def _play_tick(self) -> None:
        if not self._playing or self.info is None:
            return
        nxt = self.current_frame + 1
        if nxt >= self.info.frame_count:
            self._stop_play()
            return
        self.show_frame(nxt)
        delay_ms = max(1, int(float(self.player.next_frame_time(self.current_frame)) * 1000))
        self._play_timer.start(delay_ms)

    # --------------------------------------------------------------- marks
    def set_mark_in(self) -> None:
        if self.info is None:
            return
        self.mark_in = self.current_frame
        self._update_marks_label()

    def set_mark_out(self) -> None:
        if self.info is None:
            return
        self.mark_out = self.current_frame
        self._update_marks_label()

    def _update_marks_label(self) -> None:
        def fmt(v):
            if v is None or self.mc is None:
                return "-"
            return f"{format_timecode(frame_time(self.mc, v))} (frame {v})"
        self.marks_label.setText(f"Start: {fmt(self.mark_in)}    End: {fmt(self.mark_out)}")

    def add_selection(self) -> None:
        if self.info is None or self.mc is None:
            return
        if self.mark_in is None or self.mark_out is None:
            QMessageBox.information(self, "Add Selection", "Set a start (I) and an end (O) first.")
            return
        a, b = sorted((self.mark_in, self.mark_out))
        self.selections.append((a, b))
        self.sel_list.addItem(
            f"{format_timecode(frame_time(self.mc, a))} - {format_timecode(frame_end_time(self.mc, b))}"
            f"   (frames {a}-{b})"
        )
        self._update_plan()

    def remove_selection(self) -> None:
        row = self.sel_list.currentRow()
        if row >= 0:
            self.sel_list.takeItem(row)
            del self.selections[row]
            self._update_plan()

    def clear_selections(self) -> None:
        self.sel_list.clear()
        self.selections = []
        self._update_plan()

    def _update_plan(self) -> None:
        """Show what is being cut (frame ranges), and how many frames will be
        re-encoded at the beginning, at the end, and at internal cut points,
        before exporting."""
        if self.info is None or self.mc is None:
            return
        if not self.selections:
            self.cut_label.setText("")
            return
        mode = self.mode_combo.currentData()
        cut_text = describe_cut(self.info.frame_count, self.selections, mode)
        self.cut_label.setText(cut_text)
        try:
            segments = positive_segments(self.mc, self.selections, mode)
            if not segments:
                self.status_label.setText("Nothing to keep with the current selections and mode.")
                return
            adjusted = make_adjusted_segment_times(segments, self.mc)
            cut_segments = make_cut_segments(self.mc, adjusted, False)
            fps = self.info.fps
            first_start = adjusted[0][0]
            last_end = adjusted[-1][1]
            start = end = middle = whole = kept = 0
            for c in cut_segments:
                n = int(round(float((c.end_time - c.start_time) * fps)))
                kept += n
                if not c.require_recode:
                    continue
                at_start = c.start_time == first_start
                at_end = c.end_time == last_end
                if at_start and at_end:
                    whole += n
                elif at_start:
                    start += n
                elif at_end:
                    end += n
                else:
                    middle += n
            if whole and not (start or end or middle):
                text = (f"Plan: {cut_text} Keeping {kept} frames. "
                        f"All {whole} kept frames will be re-encoded (at lossless quality): "
                        f"the kept range sits inside a single GOP of the source, "
                        f"so there is nothing that can be copied.")
            else:
                copied = kept - (start + end + middle)
                text = (f"Plan: {cut_text} Keeping {kept} frames. "
                        f"Re-encodes: {start} frames at the beginning, {end} at the end")
                if middle:
                    text += f", {middle} at internal cut points"
                if copied > 0:
                    text += f". The other {copied} kept frames are copied bit-identical."
                else:
                    text += ". Every kept frame falls in a re-encoded part."
            self.status_label.setText(text)
        except Exception:
            self.status_label.setText("Selections updated.")

    # -------------------------------------------------------------- export
    def browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save as", self.out_edit.text(), MEDIA_FILTER)
        if path:
            self.out_edit.setText(path)

    def start_export(self) -> None:
        if self.info is None or self.mc is None:
            return
        if not self.selections:
            QMessageBox.information(self, "Save", "Add at least one selection first.")
            return
        out_path = self.out_edit.text().strip()
        if not out_path:
            QMessageBox.information(self, "Save", "Choose an output file first.")
            return
        if os.path.abspath(out_path) == os.path.abspath(self.info.path):
            QMessageBox.critical(self, "Save", "Output cannot overwrite the input file.")
            return
        mode = self.mode_combo.currentData()
        segments = positive_segments(self.mc, self.selections, mode)
        if not segments:
            QMessageBox.information(self, "Save", "Nothing to keep with the current selections and mode.")
            return
        speed = self.speed_combo.currentData()
        settings = VideoSettings(
            VideoExportMode.SMARTCUT, VideoExportQuality.LOSSLESS,
            speed=speed, source_bitrate=self.info.video_bitrate,
        )
        self._worker = ExportWorker(self.info.path, segments, out_path, settings)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.succeeded.connect(self._export_done)
        self._worker.failed.connect(self._export_failed)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self.progress.setValue(0)
        self.status_label.setText("Exporting...")
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._thread.start()

    def cancel_export(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("Cancelling...")

    def _export_done(self, stats: dict, out_path: str) -> None:
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        cut_text = ""
        if self.info is not None and self.selections:
            cut_text = describe_cut(
                self.info.frame_count, self.selections,
                self.mode_combo.currentData()) + " "
            self.cut_label.setText(cut_text.strip())
        kept = stats.get("frames_kept_approx", 0)
        recoded = stats.get("frames_recoded_approx", 0)
        whole = stats.get("frames_recoded_whole", 0)
        if whole and recoded >= kept and kept > 0:
            self.status_label.setText(
                f"Done: {out_path}   {cut_text}All {kept} kept frames were re-encoded "
                f"(at lossless quality): the kept range sits inside a single GOP "
                f"of the source, so there was nothing that could be copied."
            )
        else:
            start = stats.get("frames_recoded_start", 0)
            end = stats.get("frames_recoded_end", 0)
            middle = stats.get("frames_recoded_middle", 0)
            copied = max(0, kept - recoded)
            parts = [f"{start} frames re-encoded at the beginning", f"{end} at the end"]
            if middle:
                parts.append(f"{middle} at internal cut points")
            self.status_label.setText(
                f"Done: {out_path}   {cut_text}" + ", ".join(parts) +
                f". The other {copied} kept frames were copied bit-identical."
            )
        self.progress.setValue(100)

    def _export_failed(self, message: str) -> None:
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(message)
        QMessageBox.critical(self, "Export", message)


def create_window() -> MainWindow:
    return MainWindow()
