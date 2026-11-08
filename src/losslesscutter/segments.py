"""Selection bookkeeping: frame ranges -> smartcut positive segments."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Annotation only - importing the engine here would pull PyAV/numpy
    # into the app's startup imports.
    from smartcut.media_container import MediaContainer


def frame_time(mc: MediaContainer, index: int) -> Fraction:
    return Fraction(mc.video_frame_times[index]) - Fraction(mc.start_time)


def frame_end_time(mc: MediaContainer, index: int) -> Fraction:
    """Time just after the given frame (the exclusive end of a selection)."""
    count = len(mc.video_frame_times)
    if index + 1 < count:
        return frame_time(mc, index + 1)
    if index > 0:
        return frame_time(mc, index) + (frame_time(mc, index) - frame_time(mc, index - 1))
    return frame_time(mc, index) + Fraction(1, 25)


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping or directly adjacent inclusive frame ranges."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [list(ordered[0])]
    for a, b in ordered[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def positive_segments(
    mc: MediaContainer,
    selections: list[tuple[int, int]],
    mode: str,
) -> list[tuple[Fraction, Fraction]]:
    """Convert inclusive frame selections to (start, end) time segments to keep.

    mode 'keep': the selections themselves are kept.
    mode 'remove': everything except the selections is kept.
    """
    frame_count = len(mc.video_frame_times)
    merged = merge_ranges(selections)
    if mode == "keep":
        keep = merged
    else:
        keep = []
        cursor = 0
        for a, b in merged:
            if a > cursor:
                keep.append((cursor, a - 1))
            cursor = max(cursor, b + 1)
        if cursor <= frame_count - 1:
            keep.append((cursor, frame_count - 1))
    segments = []
    for a, b in keep:
        start = frame_time(mc, a)
        end = frame_end_time(mc, b)
        if end > start:
            segments.append((start, end))
    return segments


def kept_ranges(frame_count: int, selections: list[tuple[int, int]], mode: str) -> list[tuple[int, int]]:
    """Merged inclusive (start, end) frame ranges that survive the edit."""
    merged = merge_ranges(selections)
    if mode == "keep":
        return merged
    out = []
    cursor = 0
    for a, b in merged:
        if a > cursor:
            out.append((cursor, a - 1))
        cursor = max(cursor, b + 1)
    if cursor <= frame_count - 1:
        out.append((cursor, frame_count - 1))
    return out


def removed_ranges(frame_count: int, selections: list[tuple[int, int]], mode: str) -> list[tuple[int, int]]:
    """Inclusive (start, end) frame ranges that are cut out."""
    out = []
    cursor = 0
    for a, b in kept_ranges(frame_count, selections, mode):
        if a > cursor:
            out.append((cursor, a - 1))
        cursor = max(cursor, b + 1)
    if cursor <= frame_count - 1:
        out.append((cursor, frame_count - 1))
    return out


def describe_cut(frame_count: int, selections: list[tuple[int, int]], mode: str) -> str:
    """Plain-language summary of what is cut, e.g.
    'Cutting the first 25 frames (0-24) and the last 174 frames (137-310).'"""
    ranges = removed_ranges(frame_count, selections, mode)
    if not ranges:
        return "Nothing is being cut."
    parts = []
    for a, b in ranges:
        n = b - a + 1
        word = "frame" if n == 1 else "frames"
        if a == 0 and b == frame_count - 1:
            parts.append(f"the whole file (frames {a}-{b})")
        elif a == 0:
            parts.append(f"the first {n} {word} ({a}-{b})")
        elif b == frame_count - 1:
            parts.append(f"the last {n} {word} ({a}-{b})")
        else:
            parts.append(f"{n} {word} in the middle ({a}-{b})")
    if len(parts) == 1:
        joined = parts[0]
    elif len(parts) == 2:
        joined = parts[0] + " and " + parts[1]
    else:
        joined = ", ".join(parts[:-1]) + ", and " + parts[-1]
    return f"Cutting {joined}."


def timestamp_seconds(text: str) -> float | None:
    """Parse a timestamp entry into seconds: "83.5", "1:23.5",
    "0:01:23.250". A bare integer is a frame number, not a timestamp,
    and returns None, as does anything unparseable or negative."""
    s = text.strip()
    if not s or ("." not in s and ":" not in s):
        return None
    parts = s.split(":")
    if len(parts) > 3:
        return None
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        else:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def parse_goto(text: str, fps: Fraction, frame_count: int) -> int | None:
    """Parse a Go-to entry into a target frame index.

    A bare integer is a frame number ("1250"). Anything with a decimal
    point or colons is a timestamp: seconds ("83.5"), minutes:seconds
    ("1:23.5"), or hours:minutes:seconds ("0:01:23.250"); the target is
    the frame at that time at the file's frame rate. Returns the target
    clamped to [0, frame_count - 1], or None if the text is neither a
    frame number nor a timestamp.
    """
    s = text.strip()
    if not s or frame_count <= 0:
        return None
    if s.lstrip("+-").isdigit():
        try:
            frame = int(s)
        except ValueError:
            return None
        return max(0, min(frame, frame_count - 1))
    seconds = timestamp_seconds(s)
    if seconds is None:
        return None
    frame = int(round(seconds * float(fps)))
    return max(0, min(frame, frame_count - 1))
