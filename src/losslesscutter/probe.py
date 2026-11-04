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
    """Average video bitrate in bits/s: stream value if present, else measured."""
    try:
        with av.open(path) as c:
            vs = next((s for s in c.streams if s.type == "video"), None)
            if vs is None:
                return None
            if vs.bit_rate:
                return int(vs.bit_rate)
            if not c.duration:
                return None
            total = 0
            for p in c.demux(vs):
                total += p.size
            dur = float(c.duration / av.time_base)
            return int(total * 8 / dur) if dur > 0 else None
    except Exception:
        return None


def probe_media(path: str) -> tuple[MediaInfo, MediaContainer]:
    mc = MediaContainer(path)
    if mc.video_stream is None:
        mc.close()
        raise ValueError("No video stream found in this file.")
    vs = mc.video_stream
    fps = vs.average_rate or vs.guessed_rate or Fraction(25, 1)
    info = MediaInfo(
        path=path,
        codec=vs.codec_context.name,
        width=vs.codec_context.width,
        height=vs.codec_context.height,
        fps=Fraction(fps),
        frame_count=int(len(mc.video_frame_times)),
        duration=Fraction(mc.duration),
        keyframe_indices=list(mc.video_keyframe_indices),
        video_bitrate=estimate_video_bitrate(path),
        has_audio=len(mc.audio_tracks) > 0,
    )
    return info, mc
