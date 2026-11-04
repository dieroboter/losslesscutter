# smartcut v1.7 baseline test report

Date: Nov 3, 2026 (America/Los_Angeles)
Source under test: ~/workspace/lossless-cutter/vendor-smartcut (smartcut 1.7, MIT), unmodified
Runner: ~/workspace/lossless-cutter/.venv, Python 3.12.3
Logs: ~/workspace/lossless-cutter/test-run/log-<category>.txt

## 1. Environment and PyAV

venv created at ~/workspace/lossless-cutter/.venv with packages:
av 16.0.1, numpy 2.5.4, tqdm 4.70.1, psutil 7.2.2, ffmpeg-python 0.2.0,
soundfile 0.14.0, scipy 1.18.1, requests 2.34.2 (runtime + test extras from the
project's own pyproject). System ffmpeg CLI 8.1.2 is on PATH, as the task stated.

### PyAV version finding (environment fix, no source touched)

- A plain `pip install av` first installed **PyAV 19.0.2** (bundled FFmpeg
  libavcodec 63.1.102). The suite cannot run on it: every test failed at
  MediaContainer open with
  `TypeError: open() got an unexpected keyword argument 'metadata_errors'`
  (smartcut calls `av_open(path, 'r', metadata_errors='ignore')`; that kwarg was
  removed after PyAV 16).
- The project pins `av==16.0.1` in pyproject.toml, so the venv was aligned to
  the pin. Baseline PyAV is therefore **16.0.1**, bundled FFmpeg libraries:
  libavutil 60.8.100, libavcodec 62.11.100, libavformat 62.3.100,
  libavdevice 62.1.100, libavfilter 11.4.100, libswscale 9.1.100,
  libswresample 6.1.100.

### Encoder availability in the bundled FFmpeg (PyAV 16.0.1, `Codec(name, 'w')`)

| Encoder | Status |
|---|---|
| libx264 | Available |
| libx265 | Available |
| libvpx-vp9 | Available |
| libaom-av1 | Available |
| libsvtav1 | Available |
| mpeg2video | Available |
| mpeg4 | Available |
| aac | Available |
| libopus | Available |
| libmp3lame | Available |

All 10 requested encoders are present. (Note: under PyAV 19.0.2, libaom-av1
was missing while libsvtav1 was present; irrelevant once pinned to 16.0.1.)

## 2. Test runs

Suite: vendor-smartcut/smartcut/tests/smartcut_tests.py, run with the venv
python, PYTHONPATH set to the vendor root and the tests dir, working directory
~/workspace/lossless-cutter/test-run so generated data stays out of the vendor
tree. Categories run: basic, h264, h265, codecs, containers, audio.
Skipped per instructions: real_world*, external, long, mixed, transforms, all.

| Category | Tests | Passed | Failed | Suite time | Wall time |
|---|---|---|---|---|---|
| basic | 6 | 6 | 0 | 3.9 s | 9 s |
| h264 | 13 | 9 | 4 | 9.7 s | 14 s |
| h265 | 7 | 4 | 3 | 67.9 s | 73 s |
| codecs | 7 | 7 | 0 | 83.3 s | 90 s |
| containers | 11 | 8 | 3 | 14.7 s | 21 s |
| audio | 2 | 2 | 0 | 2.2 s | 7 s |
| **Total** | **46** | **36** | **10** | **181.7 s** | **214 s** |

(two TS tests are members of both h264 and containers, so the 46 executions
cover 44 distinct tests; 8 distinct tests failed.)

Passing coverage includes: H.264 smart cut and all profiles (Baseline, Main,
High, High10, High422, High444), HEVC smart cut incl. MP4 and TS inputs,
VP9 (both profiles), AV1 smart cut, MPEG-2 (MPG, M2TS, TS), AVI MPEG-4/MJPEG/
H.263, FLV, MOV, WMV, MKV attachment preservation, and audio passthrough
(Vorbis, MP3).

## 3. Failures: all 10 are external test-data fetches, zero are code failures

Every test that actually executed passed (36/36). All 10 failing executions
died in setup while downloading test media, before any smartcut code ran.

### Group A: Tears of Steel sample returns HTTP 403 (7 executions, 5 distinct tests)

The tests call
`cached_download('http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4', ...)`
(test_utils.py line 49 / get_tears_of_steel_annexb line 962). First error lines:

```
File "test_utils.py", line 49, in cached_download
    raise ValueError(f"HTTP {response.status_code}")
ValueError: HTTP 403
```

Verified independently: the entire gtv-videos-bucket returns 403 through this
machine's egress, over both http and https and both hostnames
(commondatastorage.googleapis.com and storage.googleapis.com), for
TearsOfSteel.mp4 and BigBuckBunny.mp4 alike. Not fixable from here without an
alternate source for that exact Google sample encode.

Tests: test_h264_non_idr_keyframes, test_h264_non_idr_keyframes_annexb,
test_ts_h264_to_mp4_cut_on_keyframes (fails in both h264 and containers),
test_ts_h264_to_mkv_smart_cut (fails in both), test_ts_h264_to_mp4_smart_cut
(containers).

### Group B: media-test-data repo is not publicly cloneable (3 tests)

`get_media_test_data_file()` tries
`git clone --depth 1 https://github.com/skeskinen/media-test-data.git`.
First error lines:

```
fatal: could not read Username for 'https://github.com': No such device or address
subprocess.CalledProcessError: Command '['git', 'clone', '--depth', '1',
  'https://github.com/skeskinen/media-test-data.git', 'media-test-data']'
  returned non-zero exit status 128.
```

Verified independently: `curl -sI https://github.com/skeskinen/media-test-data`
returns **404 Not Found** (the repo is private or deleted; GitHub asks for
credentials on private repos, hence the username prompt). The needed files
cannot be fetched.

Tests: test_peaks_mkv_memory_usage (needs peaks.mkv),
test_hevc_mkv_nal_type_detection (needs hevc_mkv_no_dts.mkv),
test_hevc_mkv_no_dts_remux (needs hevc_mkv_no_dts.mkv).

## 4. Vendor integrity

No file in vendor-smartcut was modified. The runs produced bytecode caches
(__pycache__) and a generated tests/test_data directory inside the vendor
tree as side effects; both were deleted afterward, and a final check shows
no remaining added or changed files (only the two parent directories' mtimes
moved because of that cleanup).

## Bottom line

Baseline is green: on the project's pinned PyAV 16.0.1, all 36 executable
tests pass, covering H.264/HEVC/VP9/AV1/MPEG-2 smart cutting and 10 container
paths. The only failures are 8 distinct tests whose external sample files are
unreachable from this network (Google sample bucket 403, media-test-data repo
404). If those files are ever supplied locally (google_tears_of_steel.mp4 in
the run directory; peaks.mkv and hevc_mkv_no_dts.mkv in a media-test-data/
directory), the same commands will exercise them unchanged.
