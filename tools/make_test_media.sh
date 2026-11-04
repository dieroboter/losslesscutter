#!/bin/sh
# Generate the synthetic test media used by tests/ into test-media/.
# Every file is 320x240 testsrc2 with a sine audio track, 6 seconds.
set -e
mkdir -p test-media
V="testsrc2=size=320x240"
A="sine=frequency=440:sample_rate=44100"

ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v libx264 -g 24 -pix_fmt yuv420p -c:a aac -shortest test-media/h264.mp4
ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v libx264 -g 300 -pix_fmt yuv420p -c:a aac -shortest test-media/h264long.mp4
ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v libx265 -g 24 -pix_fmt yuv420p -c:a aac -shortest test-media/hevc.mp4
ffmpeg -y -v error -f lavfi -i "$V:rate=25:duration=6" -f lavfi -i "$A" \
  -c:v mpeg2video -g 15 -c:a mp2 -shortest test-media/mpeg2.mpg
ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v libvpx-vp9 -g 24 -b:v 400k -c:a libopus -shortest test-media/vp9.webm
ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v libsvtav1 -g 24 -pix_fmt yuv420p -c:a aac -shortest test-media/av1.mp4
ffmpeg -y -v error -f lavfi -i "$V:rate=24:duration=6" -f lavfi -i "$A" \
  -c:v mpeg4 -g 24 -c:a libmp3lame -shortest test-media/mpeg4.avi
echo "test media written to test-media/"
