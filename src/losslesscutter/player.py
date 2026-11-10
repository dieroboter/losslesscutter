"""Frame-accurate preview decoder based on PyAV.

Decoding is sequential from the nearest keyframe at or before the target
frame. A pts -> frame-index map (built from the engine's MediaContainer scan)
keeps frame numbers exact even for VFR material.
"""
from __future__ import annotations

from bisect import bisect_right
from fractions import Fraction

import av
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from smartcut.media_container import MediaContainer


class PreviewPlayer:
    def __init__(self) -> None:
        self._container = None
        self._stream = None
        self._path: str | None = None
        self._mc: MediaContainer | None = None
        self._pts_to_index: dict[int, int] = {}
        self._decoder = None          # active decode generator
        self._next_index: int = 0     # index of the next frame the generator yields
        self._cache_index: int = -1
        self._cache_image: QImage | None = None
        self._raw_index: int = -1     # last frame _fetch_frame returned
        self._raw_frame = None        # ... and the frame itself
        self._interlaced: bool | None = None  # first decoded frame's flag
        self._field_parity: int | None = None  # rows of the first field: 0 or 1
        self._di_graph = None         # bwdif graph for get_frame_2x
        self._di_in = None
        self._di_sink = None
        self._di_fed: int = 0         # next source index to push
        self._di_next: tuple[int, int] | None = None  # (index, field) of the next output
        self._di_pending: dict[tuple[int, int], QImage] = {}
        self._di_flushed: bool = False
        self.current_index: int = 0

    def open(self, path: str, mc: MediaContainer) -> None:
        self.close()
        self._mc = mc
        self._path = path
        self._container = av.open(path)
        self._stream = next(s for s in self._container.streams if s.type == "video")
        pts_array = mc.video_frame_times_pts
        self._pts_to_index = {int(p): i for i, p in enumerate(pts_array)}
        self.current_index = 0
        self._cache_index = -1
        self._decoder = None
        self._reset_display_state()

    def _reset_display_state(self) -> None:
        self._raw_index = -1
        self._raw_frame = None
        self._interlaced = None
        self._field_parity = None
        self._di_graph = None
        self._di_in = None
        self._di_sink = None
        self._di_fed = 0
        self._di_next = None
        self._di_pending = {}
        self._di_flushed = False

    def close(self) -> None:
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
        self._container = None
        self._decoder = None
        self._reset_display_state()

    @property
    def frame_count(self) -> int:
        return len(self._pts_to_index)

    def _seek_to_keyframe(self, index: int, gops_back: int = 0) -> None:
        assert self._container is not None and self._mc is not None
        # video_keyframe_indices holds, per GOP, the presentation index
        # of the GOP's span-start frame (its first presented frame; for
        # open GOPs that is a leading B-frame, not the keyframe itself).
        # Seek to that frame's pts and let the walk in get_frame sort
        # out exact frames by pts: ffmpeg lands on a keyframe packet at
        # or near the target timestamp - exactly where varies by
        # container, and on MPEG program streams it can land a GOP or
        # two late, which the retry in get_frame absorbs by aiming
        # further back (gops_back).
        keyframes = self._mc.video_keyframe_indices
        pos = bisect_right(keyframes, index) - 1
        pos = max(0, pos - gops_back)
        if pos == 0 and gops_back > 0:
            # Retries have backed into the first GOP and seeking still
            # has not landed early enough (timestamp-to-byte estimation
            # is coarsest near the start of a file). Decode from the
            # very beginning instead - the walk to the target is short
            # here by construction.
            self._restart_from_beginning()
            return
        kf = keyframes[pos] if pos >= 0 else 0
        target_pts = int(self._mc.video_frame_times_pts[kf])
        self._container.seek(target_pts, stream=self._stream, backward=True, any_frame=False)
        self._decoder = self._container.decode(self._stream)
        self._next_index = kf

    def _restart_from_beginning(self) -> None:
        assert self._mc is not None
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
        self._container = av.open(self._path)
        self._stream = next(s for s in self._container.streams if s.type == "video")
        self._decoder = self._container.decode(self._stream)
        self._next_index = 0

    @staticmethod
    def _to_image(frame) -> QImage:
        arr = frame.to_ndarray(format="rgb24")
        return QImage(arr.data, arr.shape[1], arr.shape[0],
                      arr.strides[0], QImage.Format.Format_RGB888).copy()

    def _fetch_frame(self, index: int):
        """The decoded source frame at `index` (an av.VideoFrame), or
        None when nothing displayable could be produced. All of the
        frame-exactness rules live here: the walk goes by pts and only
        ever returns the requested frame, or - for an undecodable head
        frame - the first frame at/after it."""
        if self._container is None:
            return None
        index = max(0, min(index, self.frame_count - 1))
        if index == self._raw_index and self._raw_frame is not None:
            return self._raw_frame
        # Continue sequentially when moving forward from where we are;
        # otherwise restart from the keyframe at or before the target.
        need_seek = (self._decoder is None or index < self._next_index
                     or index - self._next_index > 300)
        found = None
        for attempt in range(4):
            if need_seek:
                self._seek_to_keyframe(index, gops_back=attempt)
                need_seek = False
            assert self._decoder is not None
            overshot = False
            yielded = False
            while self._next_index <= index:
                try:
                    frame = next(self._decoder)
                except StopIteration:
                    break
                yielded = True
                frame_idx = self._pts_to_index.get(int(frame.pts), self._next_index) if frame.pts is not None else self._next_index
                self._next_index = frame_idx + 1
                if frame_idx == index:
                    found = frame
                elif frame_idx > index:
                    # The decoder started (or jumped) past the target:
                    # the seek landed late. Retry aiming further back -
                    # never display a frame other than the requested one.
                    overshot = True
                    break
            if found is not None:
                break
            if overshot or not yielded:
                # Overshot the target, or the seek produced nothing at
                # all (e.g. it landed past the last packet): retry
                # aiming further back.
                need_seek = True
                continue
            break
        if found is None:
            # The target frame itself was never yielded (e.g. an
            # undecodable leading picture at the very start of a file
            # that begins mid-GOP). Show the first frame at/after it
            # from a fresh seek rather than nothing.
            self._seek_to_keyframe(index)
            try:
                found = next(self._decoder)
                shown_idx = self._pts_to_index.get(int(found.pts), index) if found.pts is not None else index
                self._next_index = shown_idx + 1
            except StopIteration:
                return None
        self._raw_index = index
        self._raw_frame = found
        if self._interlaced is None:
            self._interlaced = bool(found.interlaced_frame)
        return found

    def get_frame(self, index: int) -> QImage | None:
        if self._container is None:
            return None
        index = max(0, min(index, self.frame_count - 1))
        if index == self._cache_index and self._cache_image is not None:
            self.current_index = index
            return self._cache_image
        frame = self._fetch_frame(index)
        if frame is None:
            return self._cache_image
        image = self._to_image(frame)
        self._cache_index = index
        self._cache_image = image
        self.current_index = index
        return image

    @property
    def is_interlaced(self) -> bool | None:
        """Whether the file's frames are interlaced, once a frame has
        been decoded (None before that)."""
        return self._interlaced

    def _make_bwdif_graph(self):
        graph = av.filter.Graph()
        src = graph.add_buffer(template=self._stream)
        filt = graph.add("bwdif", "mode=send_field:parity=auto:deint=all")
        sink = graph.add("buffersink")
        src.link_to(filt)
        filt.link_to(sink)
        graph.configure()
        return graph, src, sink

    def _detect_field_parity(self, frame) -> int:
        """Which rows of a woven frame hold its first field: 0 when
        they are the even rows (top field first), 1 when the odd
        rows. PyAV exposes no field-order flag, so for MPEG-2 (the
        interlaced material this exists for: DVD and VHS captures)
        the answer is read from the picture coding extension of the
        file's first picture, where top_field_first is one bit.
        Anything unparseable falls back to top field first, the
        common case for interlaced H.264 as well. Detected once per
        file."""
        if self._field_parity is not None:
            return self._field_parity
        parity = 0
        try:
            if self._stream is not None \
                    and self._stream.codec_context.name == "mpeg2video":
                tff = self._mpeg2_top_field_first()
                if tff is not None:
                    parity = 0 if tff else 1
        except Exception:
            parity = 0
        self._field_parity = parity
        return parity

    def _mpeg2_top_field_first(self) -> bool | None:
        """top_field_first from the first picture coding extension
        found in the file's first video packets, or None."""
        with av.open(self._path) as c:
            vs = next(s for s in c.streams if s.type == "video")
            for count, packet in enumerate(c.demux(vs)):
                if count > 50:
                    break
                data = bytes(packet)
                pic = data.find(b"\x00\x00\x01\x00")
                if pic < 0:
                    continue
                ext = data.find(b"\x00\x00\x01\xb5", pic)
                if ext < 0 or ext + 9 > len(data):
                    continue
                # Extension ID in the high nibble: 8 = picture coding.
                if data[ext + 4] >> 4 != 8:
                    continue
                # After the 4-bit ID: f_code 4x4 bits, intra_dc
                # precision 2, picture structure 2, then the bit.
                bits = int.from_bytes(data[ext + 4:ext + 9], "big")
                rest = bits & ((1 << 36) - 1)  # drop the ID nibble
                return bool((rest >> (36 - 4 * 4 - 2 - 2 - 1)) & 1)
        return None

    def get_frame_display(self, index: int) -> QImage | None:
        """The picture to show while paused or stepping. For an
        interlaced frame that is its first field alone, scaled
        smoothly to full height: exactly the field's own content at
        half resolution (the intermediate lines are blends of the
        field's own lines only), nothing woven in from the other
        field and nothing from neighbouring frames. Progressive
        frames show as the full frame, as get_frame."""
        if self._container is None:
            return None
        index = max(0, min(index, self.frame_count - 1))
        frame = self._fetch_frame(index)
        if frame is None:
            return self._cache_image
        if not frame.interlaced_frame:
            return self.get_frame(index)
        parity = self._detect_field_parity(frame)
        arr = frame.to_ndarray(format="rgb24")
        field_arr = np.ascontiguousarray(arr[parity::2])
        field_img = QImage(field_arr.data, field_arr.shape[1],
                           field_arr.shape[0], field_arr.strides[0],
                           QImage.Format.Format_RGB888).copy()
        image = field_img.scaled(
            arr.shape[1], arr.shape[0],
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.current_index = index
        return image

    def get_frame_2x(self, index: int, field: int) -> QImage | None:
        """One field of a frame as a full deinterlaced picture, the
        double-rate (2x) playback view: field 0 and field 1 of each
        frame are successive pictures at the field rate, deinterlaced
        by a bwdif graph that is fed the frames in presentation order
        and keeps its state between calls, so sequential playback
        requests are cheap. A request behind the stream's position
        restarts the graph at that frame. Progressive frames return
        the plain frame."""
        if self._container is None:
            return None
        index = max(0, min(index, self.frame_count - 1))
        frame = self._fetch_frame(index)
        if frame is None:
            return None
        if not frame.interlaced_frame:
            return self._to_image(frame)
        key = (index, 1 if field else 0)
        if key in self._di_pending:
            return self._di_pending[key]
        if (self._di_graph is None or self._di_next is None
                or key < self._di_next):
            self._di_graph, self._di_in, self._di_sink = \
                self._make_bwdif_graph()
            self._di_fed = index
            self._di_next = (index, 0)
            self._di_pending = {}
            self._di_flushed = False
        last = self.frame_count - 1
        while key not in self._di_pending:
            if self._di_fed <= last:
                raw = self._fetch_frame(self._di_fed)
                if raw is None:
                    break
                self._di_in.push(raw)
                self._di_fed += 1
            elif not self._di_flushed:
                self._di_in.push(None)
                self._di_flushed = True
            else:
                break
            self._drain_di()
        return self._di_pending.get(key)

    def _drain_di(self) -> None:
        while True:
            try:
                out = self._di_sink.pull()
            except (av.error.BlockingIOError, EOFError):
                return
            self._di_pending[self._di_next] = self._to_image(out)
            idx, fld = self._di_next
            self._di_next = (idx, 1) if fld == 0 else (idx + 1, 0)
            while len(self._di_pending) > 8:
                self._di_pending.pop(next(iter(self._di_pending)))

    def frame_time(self, index: int) -> Fraction:
        assert self._mc is not None
        return Fraction(self._mc.video_frame_times[index]) - Fraction(self._mc.start_time)

    def next_frame_time(self, index: int) -> Fraction:
        assert self._mc is not None
        times = self._mc.video_frame_times
        if index + 1 < len(times):
            return Fraction(times[index + 1]) - Fraction(times[index])
        return Fraction(1, 25)
