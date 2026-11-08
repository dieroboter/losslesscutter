"""Frame-accurate preview decoder based on PyAV.

Decoding is sequential from the nearest keyframe at or before the target
frame. A pts -> frame-index map (built from the engine's MediaContainer scan)
keeps frame numbers exact even for VFR material.
"""
from __future__ import annotations

from bisect import bisect_right
from fractions import Fraction

import av
from PySide6.QtGui import QImage

from smartcut.media_container import MediaContainer


class PreviewPlayer:
    def __init__(self) -> None:
        self._container = None
        self._stream = None
        self._mc: MediaContainer | None = None
        self._pts_to_index: dict[int, int] = {}
        self._decoder = None          # active decode generator
        self._next_index: int = 0     # index of the next frame the generator yields
        self._cache_index: int = -1
        self._cache_image: QImage | None = None
        self.current_index: int = 0

    def open(self, path: str, mc: MediaContainer) -> None:
        self.close()
        self._mc = mc
        self._container = av.open(path)
        self._stream = next(s for s in self._container.streams if s.type == "video")
        pts_array = mc.video_frame_times_pts
        self._pts_to_index = {int(p): i for i, p in enumerate(pts_array)}
        self.current_index = 0
        self._cache_index = -1
        self._decoder = None

    def close(self) -> None:
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
        self._container = None
        self._decoder = None

    @property
    def frame_count(self) -> int:
        return len(self._pts_to_index)

    def _seek_to_keyframe(self, index: int) -> None:
        assert self._container is not None and self._mc is not None
        keyframes = self._mc.video_keyframe_indices
        pos = bisect_right(keyframes, index) - 1
        kf = keyframes[pos] if pos >= 0 else 0
        target_pts = int(self._mc.video_frame_times_pts[kf])
        self._container.seek(target_pts, stream=self._stream, backward=True, any_frame=False)
        self._decoder = self._container.decode(self._stream)
        self._next_index = kf

    def get_frame(self, index: int) -> QImage | None:
        if self._container is None:
            return None
        index = max(0, min(index, self.frame_count - 1))
        if index == self._cache_index and self._cache_image is not None:
            self.current_index = index
            return self._cache_image
        # Continue sequentially when moving forward from where we are;
        # otherwise restart from the keyframe at or before the target.
        if self._decoder is None or index < self._next_index or index - self._next_index > 300:
            self._seek_to_keyframe(index)
        assert self._decoder is not None
        image = None
        while self._next_index <= index:
            try:
                frame = next(self._decoder)
            except StopIteration:
                break
            frame_idx = self._pts_to_index.get(int(frame.pts), self._next_index) if frame.pts is not None else self._next_index
            self._next_index = frame_idx + 1
            if frame_idx == index:
                arr = frame.to_ndarray(format="rgb24")
                image = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format.Format_RGB888).copy()
            elif frame_idx > index:
                # Overshot (should not happen with an exact pts map); reseek once.
                break
        if image is None:
            # Fall back to a fresh seek and take the first frame at/after target.
            self._seek_to_keyframe(index)
            try:
                frame = next(self._decoder)
                arr = frame.to_ndarray(format="rgb24")
                image = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format.Format_RGB888).copy()
                self._next_index = index + 1
            except StopIteration:
                return self._cache_image
        self._cache_index = index
        self._cache_image = image
        self.current_index = index
        return image

    def frame_time(self, index: int) -> Fraction:
        assert self._mc is not None
        return Fraction(self._mc.video_frame_times[index]) - Fraction(self._mc.start_time)

    def next_frame_time(self, index: int) -> Fraction:
        assert self._mc is not None
        times = self._mc.video_frame_times
        if index + 1 < len(times):
            return Fraction(times[index + 1]) - Fraction(times[index])
        return Fraction(1, 25)
