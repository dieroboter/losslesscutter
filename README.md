# LosslessCutter

A lossless video cutting app for Windows, and nothing else. It smart-cuts:
everything between cut points is copied bit-identical, and only the small
parts at the cut points are re-encoded — always at the highest quality the
codec offers. There is no full re-encode mode anywhere in the app.
If a file cannot be smart-cut, the export fails with an explanation
instead of re-encoding your file.

The interface follows the classic VideoReDo workflow: preview with
frame/GOP stepping, mark start/end, add selections, then save. A readout
tells you in plain terms what is being cut ("Cutting the first 25 frames
(0-24) and the last 174 frames (137-310)") and how many frames had to be
re-encoded at the beginning and the end.

## Download

Get LosslessCutter from the [latest release](../../releases/latest).
An installer and a portable zip are attached there.
Windows 10/11, 64-bit.

The build is unsigned, so Windows SmartScreen may warn on first run:
choose "More info" -> "Run anyway".

## Updates

On startup the app checks this repository's latest release and, if a
newer version exists, shows an "Update available" link in the window.
It never downloads or installs anything by itself.

## Supported formats

H.264, HEVC (H.265), VP9, VP8, AV1, MPEG-2, and MPEG-4 ASP video, in the
usual containers (MP4, MKV, MOV, AVI, MPG, TS, WebM, ...). Audio is passed
through untouched; supported subtitle tracks are cut along with the video.
A few codec/container pairs are impossible (VP8 video, for example, cannot
be stored in MP4); the app checks before exporting and says so instead of
failing mid-export.

"Highest quality" per codec: H.264/HEVC/VP9/AV1 re-encode losslessly
(CRF 0 / equivalent). MPEG-2, MPEG-4 ASP, and VP8 have no lossless mode:
MPEG-2 and MPEG-4 ASP use their finest quantizer (q=1), and VP8 uses CRF 4,
the finest setting its encoder accepts.

## Usage

1. Open a video (or drag & drop it onto the window).
2. Step by frame or by GOP, set Start (I) and End (O), click Add Selection.
3. Repeat for more selections if needed. "Cut mode" keeps the selected
   parts; "Scene mode" removes them.
4. Pick an output file and Save.

The selection speed setting (ultrafast ... slower) only affects how fast
the small re-encoded parts are produced and how small they are, never
their quality.

Keys: Space = play/pause, I = set start, O = set end, Left/Right = one
frame, Shift+Left/Right = 10 seconds. The transport bar also has
frame-step, GOP-step, and 10-second jump buttons.

The Go to box next to the time display jumps straight to a frame
number or a timestamp: type or paste one (for example 1250 or 1:23.5)
and press Enter.

During playback the preview plays the file's first audio track, in
sync with the picture; the Mute button and volume slider sit next to
the Go to box. Stepping frame by frame is silent - sound is for
playback. Exports keep all audio tracks untouched.

Opening a file indexes every frame in it, which can take a few seconds
for long files. That index is what makes the frame and GOP stepping
exact.

## Building from source (Windows)

Requirements: Windows 10/11, Python 3.12 (from python.org, with
"Add python.exe to PATH" checked during setup), and Git.

```
git clone https://github.com/dieroboter/losslesscutter
cd losslesscutter
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install av==16.0.1 PySide6-Essentials PySide6-Addons numpy
python tools\make_icon.py
$env:PYTHONPATH = "src"
python -m losslesscutter
```

PyAV is pinned to 16.0.1 on purpose: newer PyAV versions changed APIs the
cutting engine relies on.

Tests: install ffmpeg and put it on the PATH, generate the test media with
`tools\make_test_media.sh` (a shell script — run it in Git Bash or WSL),
then run `tests\test_engine_integration.py` (7-codec battery) and
`tests\test_gui_smoke.py` (offscreen GUI end-to-end) with the venv active.

The portable zip attached to the release is assembled by
`build_portable.py`, which runs on Linux: it packs the CPython 3.12
embeddable package and win_amd64 wheels from `build-cache\` and
cross-compiles the small C launcher (`launcher.c`) with mingw-w64.
An Inno Setup script (`losslesscutter.iss`, Inno Setup 6) is included for
wrapping the assembled portable folder in an installer on Windows.

## Credits and license

The cutting engine in `src/smartcut/` is a fork of
[smartcut](https://github.com/skeskinen/smartcut) by Santtu Keskinen
(MIT, see `src/smartcut/LICENSE.txt`), with fixes for audio passthrough,
open-GOP trailing B-frames, zero-duration final packets, and lossless
encoder settings.

LosslessCutter itself is MIT licensed (see `LICENSE`).

## Disclaimer

LosslessCutter was written by AI. Use it at your own risk, and always keep backups of
irreplaceable recordings.
