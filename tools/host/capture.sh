#! /bin/bash
#
# Capture the picowolf host build the same way tools/dosbox/capture.sh captures
# the DOS original, so the two can be compared.
#
#   tools/host/capture.sh [seconds]
#
# Leaves captures/pw/video.mkv and captures/pw/audio.raw.
#
# Two things are deliberately the same as the DOS side and worth not
# "simplifying" later:
#
#   The game runs on an Xvfb display with the real x11 video driver, not with
#   SDL_VIDEODRIVER=dummy.  Dummy is the better way to dump frames when nothing
#   has to be typed, but it has no window, so there is nothing to send keys to -
#   and the opening notices need keys.
#
#   Video comes from x11grab rather than from tools/host/frame_dump.so.  The
#   shim captures the presented surface exactly, which is better in principle,
#   but it starts dumping at the first present and the opening notices would
#   spend the whole frame budget before the attract sequence began.  The port's
#   window is 1:1 at 320x200 with no compositor in the way, so a grab of it is
#   the surface pixels anyway.
#
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=$ROOT/captures/pw
SECONDS_TO_RUN=${1:-120}
DISP=:98

mkdir -p "$OUT"
rm -f "$OUT"/video.mkv "$OUT"/audio.raw "$OUT"/run.log

cleanup() {
    [ -n "${FFMPEG_PID:-}" ] && kill "$FFMPEG_PID" 2>/dev/null
    [ -n "${GAME_PID:-}" ]   && kill -9 "$GAME_PID" 2>/dev/null
    return 0
}
trap cleanup EXIT

if ! DISPLAY=$DISP xdpyinfo >/dev/null 2>&1; then
    Xvfb $DISP -screen 0 1280x1024x24 -nolisten tcp -noreset &
    sleep 2
fi

#
# No --nowait.  It reads like the switch for skipping the opening notices, but
# `while (!param_nowait)` in wl_main.c wraps the whole attract loop, so it goes
# past the title to the menu and sits there - see clear_intro.sh.
#
# --joystick -1 because Wolf4SDL opens joystick 0 by default and SDL enumerates
# some USB keyboards as joysticks; a stick resting off centre overwrites the
# direction the keyboard just produced.
#
cd "$ROOT/Wolf4SDL" || exit 1
DISPLAY=$DISP SDL_VIDEODRIVER=x11 \
SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=$OUT/audio.raw \
    ./wolf4sdl --windowed --joystick -1 --samplerate 44100 \
    >"$OUT/run.log" 2>&1 &
GAME_PID=$!

for i in $(seq 1 30); do
    WIN=$(DISPLAY=$DISP xdotool search --name "Wolfenstein" 2>/dev/null | tail -1)
    [ -n "$WIN" ] && break
    sleep 1
done
if [ -z "${WIN:-}" ]; then
    echo "capture.sh: no game window; see $OUT/run.log" >&2
    exit 1
fi
sleep 2
eval "$(DISPLAY=$DISP xdotool getwindowgeometry --shell "$WIN")"
echo "capture.sh: window $WIN at $X,$Y ${WIDTH}x${HEIGHT}"

if ! "$ROOT/tools/dosbox/clear_intro.sh" "$DISP" "$WIN" "$X" "$Y" "$WIDTH" "$HEIGHT"; then
    echo "capture.sh: could not reach the attract sequence" >&2
fi

DISPLAY=$DISP ffmpeg -loglevel error -f x11grab -framerate 70 \
    -video_size "${WIDTH}x${HEIGHT}" -i "$DISP.0+$X,$Y" \
    -t "$SECONDS_TO_RUN" -c:v ffv1 -level 3 -y "$OUT/video.mkv" &
FFMPEG_PID=$!
wait $FFMPEG_PID
FFMPEG_PID=

frames=$(mktemp -d)
ffmpeg -loglevel error -i "$OUT/video.mkv" -vf 'fps=1/5' -y "$frames/f%03d.png" 2>/dev/null
uniq_count=$(md5sum "$frames"/*.png 2>/dev/null | awk '{print $1}' | sort -u | wc -l)
total=$(ls "$frames"/*.png 2>/dev/null | wc -l)
rm -rf "$frames"
echo "capture.sh: $uniq_count distinct screens in $total samples"
[ "$uniq_count" -le 1 ] && echo "capture.sh: the capture never changed" >&2

echo "capture.sh: done"
ls -la "$OUT"
