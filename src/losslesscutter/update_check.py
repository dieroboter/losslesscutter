"""Startup update check: ask GitHub for the latest release and report
whether it is newer than the running version. Notify only - this module
never downloads or installs anything."""
from __future__ import annotations

import json
import urllib.request

from PySide6.QtCore import QObject, Signal, Slot

from . import __version__

LATEST_RELEASE_URL = (
    "https://api.github.com/repos/dieroboter/losslesscutter/releases/latest"
)
RELEASES_PAGE = "https://github.com/dieroboter/losslesscutter/releases/latest"


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v1.2.3' / '1.2' -> (1, 2, 3) / (1, 2); None if not a version."""
    s = text.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    if not s:
        return None
    try:
        return tuple(int(p) for p in s.split("."))
    except ValueError:
        return None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_latest(timeout: float = 5.0) -> tuple[str, str] | None:
    """(version, release page URL) of the latest GitHub release, or None
    on any failure (offline, no release yet, unexpected response)."""
    req = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"LosslessCutter/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data["tag_name"]
        version = parse_version(tag)
        if version is None:
            return None
        shown = tag[1:] if tag[:1] in ("v", "V") else tag
        return shown, data.get("html_url") or RELEASES_PAGE
    except Exception:
        return None


class UpdateChecker(QObject):
    """Runs fetch_latest on a worker thread; emits the result once."""

    finished = Signal(object)  # (version, url) tuple or None

    @Slot()
    def run(self) -> None:
        self.finished.emit(fetch_latest())
