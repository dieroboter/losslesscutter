# LosslessCutter

A lossless video cutting app for Windows, and nothing else. It smart-cuts:
everything between cut points is copied bit-identical, and only the small
parts at the cut points are re-encoded — always at the highest quality the
codec offers. There is no full re-encode mode anywhere in the app.

The interface follows the classic VideoReDo workflow: preview with
frame/GOP stepping, mark start/end, add selections, then save. A readout
tells you in plain terms what is being cut ("Cutting the first 25 frames
(0-24) and the last 174 frames (137-310)") and how many frames had to be
re-encoded at the beginning and the end.

## Download

Grab the installer from the [latest release](../../releases/latest)
(`LosslessCutter-Setup-1.0.exe`). It installs per-user (no admin prompt)
and adds a Start Menu entry and an uninstaller. A portable zip is attached
to the release as well.

The installer is unsigned, so Windows SmartScreen will warn on first run:
choose "More info" -> "Run anyway".

## Supported formats

H.264, HEVC (H.265), VP9, AV1, MPEG-2, and MPEG-4 ASP video, in the usual
containers (MP4, MKV, MOV, AVI, MPG, TS, WebM, ...). Audio is passed
through untouched; supported subtitle tracks are cut along with the video.

"Highest quality" per codec: H.264/HEVC/VP9/AV1 re-encode losslessly
(CRF 0 / equivalent). MPEG-2 and MPEG-4 ASP have no lossless mode, so they
use their finest quantizer (q=1).

## Usage

1. Open a video (or drag & drop it onto the window).
2. Step by frame or by GOP, set Start (I) and End (O), click Add Selection.
3. Repeat for more selections if needed. "Cut mode" keeps the selected
   parts; "Scene mode" removes them.
4. Pick an output file and Save.

The selection speed setting (ultrafast ... slower) only affects how fast
the small re-encoded parts are produced and how small they are, never
their quality.

## Building from source

Requirements: Python 3.12, PySide6, PyAV 16.0.1, ffmpeg (for test media).

```
python tools/make_icon.py        # generates src/losslesscutter/icon.ico/.png
python -m losslesscutter         # run the GUI from src/ (PYTHONPATH=src)
```

Portable Windows build (what the release zip is): `python build_portable.py`
assembles `dist/LosslessCutter/` from the CPython embeddable package and
win_amd64 wheels in `build-cache/`, with a small C launcher
(`launcher.c`, cross-compiled with mingw-w64) as `LosslessCutter.exe`.

Installer: `losslesscutter.iss` (Inno Setup 6) wraps the portable folder.

Tests: generate media with `tools/make_test_media.sh`, then run
`tests/test_engine_integration.py` (6-codec battery) and
`tests/test_gui_smoke.py` (offscreen GUI end-to-end).

## Credits and license

The cutting engine in `src/smartcut/` is a fork of
[smartcut](https://github.com/skeskinen/smartcut) by Santtu Keskinen
(MIT, see `src/smartcut/LICENSE.txt`), with fixes for audio passthrough,
open-GOP trailing B-frames, zero-duration final packets, and lossless
encoder settings.

LosslessCutter itself is MIT licensed (see `LICENSE`).
