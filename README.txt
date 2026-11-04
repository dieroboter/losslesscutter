LosslessCutter 1.0
==================

A lossless cutting app and nothing else. It smart-cuts video: everything
between cut points is copied bit-identical, and only the small parts at the
cut points (part of one GOP each) are re-encoded - always at the highest
quality the codec offers. There is no full-recode mode in this app; if a
file cannot be smart-cut, the export fails with an explanation instead of
re-encoding your file.

Portable: no installation. Keep the folder together and run
LosslessCutter.exe. Optionally pass a video file path as an argument.

How to cut
----------
1. Open a video file.
2. Step through it with the transport buttons (frame step, GOP step,
   10-second jumps) or the slider. Keys: Space = play/pause, I = set start,
   O = set end, Left/Right = one frame, Shift+Left/Right = 10 seconds.
3. Set Start (I) and Set End (O), then "Add Selection". Add as many
   selections as you like.
4. Cut mode keeps the selected parts; Scene mode removes them.
5. The status line shows the plan before you save: how many frames will be
   re-encoded at the beginning, at the end, and at internal cut points.
   Everything else is copied bit-identical.
6. Pick an output file and Save. Speed only changes how fast the small
   re-encoded parts are encoded and how large they get, not their quality.
   After saving, the status line reports the actual numbers.

Supported
---------
Codecs: H.264, HEVC (incl. 10-bit and CRA/BLA open-GOP), VP9, AV1,
MPEG-2, MPEG-4 ASP (DivX/Xvid). Containers: MP4, MKV, MOV, AVI, MPG/VOB,
TS/M2TS, WebM, FLV, WMV. All audio tracks and subtitle tracks are passed
through untouched.

Per-codec cutting method (best quality available per codec):
- MPEG-2: boundary-GOP re-encode at the source's own bitrate with the
  finest quantizer (MPEG-2 has no lossless mode; its GOP-shortening style
  small recodes are what the planner produces: typically a few frames).
- H.264: smartcut planner + libx264, lossless (CRF 0, High 4:4:4
  Predictive segment SPS).
- HEVC: smartcut planner + libx265, lossless, source parameters carried
  over, 10-bit stays 10-bit.
- VP9 / AV1: smartcut planner, lossless mode of libvpx / libaom.
- MPEG-4 ASP: smartcut planner + finest quantizer (no lossless mode
  exists for ASP). Open-GOP B-frame AVIs are handled: trailing B-frames
  at GOP tails are preserved.

Notes
-----
- Frame numbers and stepping are exact: the app indexes every frame of
  the file when it opens (this can take a few seconds for long files).
- The preview is silent (no audio playback); exports keep all audio.
- H.264 detail: a lossless re-encoded segment uses a High 4:4:4 SPS.
  Decoders that play straight through an SPS switch can show a
  sub-1%-of-chroma-samples phase difference on the first copied GOP
  after a re-encoded segment; the copied data itself is bit-identical
  and decodes exactly when decoded from that GOP (verified by test).

Built on
--------
- smartcut engine by Santtu Keskinen (MIT License, see
  app/smartcut/LICENSE.txt), forked with fixes: decoder priming for
  open-GOP trailing B-frames, remux pts filtering, final-frame duration
  repair, MPEG-2/MPEG-4 quantizer quality mapping, lossless H.264
  profile fix, and export statistics.
- PyAV 16.0.1 / FFmpeg, PySide6, CPython 3.12 (embeddable distribution).
