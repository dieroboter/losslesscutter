"""Media probing helpers shared by the GUI and tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import av

from smartcut.media_container import MediaContainer


@dataclass
class MediaInfo:
    path: str
    codec: str
    width: int
    height: int
    fps: Fraction
    frame_count: int
    duration: Fraction
    keyframe_indices: list[int] = field(default_factory=list)
    video_bitrate: int | None = None
    has_audio: bool = False

    def frame_time(self, mc: MediaContainer, index: int) -> Fraction:
        """Presentation time of a frame in smartcut segment-time units
        (seconds relative to the container start time)."""
        return Fraction(mc.video_frame_times[index]) - Fraction(mc.start_time)


def estimate_video_bitrate(path: str) -> int | None:
    """Average video bitrate in bits/s: the stream's own value when the
    container stores one (MP4, MPEG-PS usually do); otherwise estimated
    from a sample of the first ~10 seconds of packets. MKV stores no
    per-stream bitrate, and measuring the whole file there meant reading
    every video packet once just for this number."""
    try:
        with av.open(path) as c:
            vs = next((s for s in c.streams if s.type == "video"), None)
            if vs is None:
                return None
            if vs.bit_rate:
                return int(vs.bit_rate)
            if vs.time_base is None:
                return None
            total = 0
            first_pts: int | None = None
            last_end = 0
            count = 0
            for p in c.demux(vs):
                if p.pts is None:
                    continue
                if first_pts is None:
                    first_pts = p.pts
                total += p.size
                count += 1
                last_end = max(last_end, p.pts + (p.duration or 0))
                span = float((last_end - first_pts) * vs.time_base)
                if span >= 10.0 or count >= 20000:
                    break
            if first_pts is None:
                return None
            dur = float((last_end - first_pts) * vs.time_base)
            return int(total * 8 / dur) if dur > 0 else None
    except Exception:
        return None


def effective_fps(declared, frame_count: int,
                  duration: Fraction) -> Fraction:
    """The frame rate frame/time conversions should use. Some files
    declare no real rate - one real-world MP4 declares nothing, and
    the guessed rate falls back to its 1/1000 stream time base, making
    the file look like 1000 fps when its true rate is 28 (frame
    stepping and Go to then multiply by 1000 and clamp to the ends).
    Trust the declared rate only when it roughly agrees with the
    actual frame count over the duration; otherwise use that."""
    if frame_count <= 0 or duration <= 0:
        return Fraction(declared) if declared else Fraction(25, 1)
    actual = Fraction(frame_count, 1) / duration
    if not declared:
        return actual
    ratio = Fraction(declared) / actual
    return Fraction(declared) if Fraction(1, 2) <= ratio <= 2 else actual


def probe_media(path: str, progress_cb=None) -> tuple[MediaInfo, MediaContainer]:
    mc = MediaContainer(path, progress_cb=progress_cb)
    if mc.video_stream is None:
        mc.close()
        raise ValueError("No video stream found in this file.")
    vs = mc.video_stream
    frame_count = int(len(mc.video_frame_times))
    duration = Fraction(mc.duration)
    fps = effective_fps(vs.average_rate or vs.guessed_rate,
                        frame_count, duration)
    info = MediaInfo(
        path=path,
        codec=vs.codec_context.name,
        width=vs.codec_context.width,
        height=vs.codec_context.height,
        fps=fps,
        frame_count=frame_count,
        duration=duration,
        keyframe_indices=list(mc.video_keyframe_indices),
        video_bitrate=estimate_video_bitrate(path),
        has_audio=len(mc.audio_tracks) > 0,
    )
    return info, mc
