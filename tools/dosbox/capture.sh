#! /bin/bash
#
# Capture the original DOS Wolfenstein 3D as a reference to compare picowolf
# against: video and audio from one run, with nothing typed by hand.
#
# It runs on its own X server rather than the desktop.  This session is GNOME
# on Wayland, where an emulator window lives under XWayland: synthetic key
# events do not reach it (the compositor owns the keyboard, and the 1x1 window
# holding X focus is XWayland's focus proxy), and x11grab of the root returns
# black because XWayland windows are not composited into it.  Inside Xvfb there
# is no compositor, so both work - and nothing touches the real desktop.
#
#   tools/dosbox/capture.sh [seconds]
#
# Leaves captures/dos/video.mkv (lossless, the emulator's 640x400 window) and
# captures/dos/audio.raw (44100 Hz stereo s16, straight out of the DOSBox-X
# mixer through SDL's disk audio driver - the same driver the picowolf host
# build is captured with, so the two are the same format).
#
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=$ROOT/captures/dos
SECONDS_TO_RUN=${1:-120}
DISP=:99

mkdir -p "$OUT"
rm -f "$OUT"/video.mkv "$OUT"/audio.raw "$OUT"/dosbox.log

cleanup() {
    [ -n "${FFMPEG_PID:-}" ] && kill "$FFMPEG_PID" 2>/dev/null
    [ -n "${DOSBOX_PID:-}" ] && kill "$DOSBOX_PID" 2>/dev/null
    [ -n "${XVFB_PID:-}" ]   && kill "$XVFB_PID" 2>/dev/null
    return 0
}
trap cleanup EXIT

# A private X server.  -noreset so it survives the last client going away.
if ! DISPLAY=$DISP xdpyinfo >/dev/null 2>&1; then
    Xvfb $DISP -screen 0 1280x1024x24 -nolisten tcp -noreset &
    XVFB_PID=$!
    sleep 2
fi

#
# SDL's disk audio driver writes what the mixer produces to a file instead of a
# sound card, so the audio needs no sound hardware and no capture hotkey.  Its
# default pacing is real time, which is what keeps it lined up with the video.
#
SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=$OUT/audio.raw \
DISPLAY=$DISP dosbox-x -conf "$ROOT/tools/dosbox/reference-x.conf" \
    -nomenu -time-limit "$((SECONDS_TO_RUN + 15))" >"$OUT/dosbox.log" 2>&1 &
DOSBOX_PID=$!

# Wait for the window, then read its geometry - the position is not fixed.
for i in $(seq 1 30); do
    WIN=$(DISPLAY=$DISP xdotool search --name "DOSBox-X" 2>/dev/null | tail -1)
    [ -n "$WIN" ] && break
    sleep 1
done
if [ -z "${WIN:-}" ]; then
    echo "capture.sh: DOSBox-X window never appeared; see $OUT/dosbox.log" >&2
    exit 1
fi
sleep 4
eval "$(DISPLAY=$DISP xdotool getwindowgeometry --shell "$WIN")"
echo "capture.sh: window $WIN at $X,$Y ${WIDTH}x${HEIGHT}"

#
# No keys are sent, because the game has a switch for this: WOLF3D.EXE NOWAIT
# in the config's autoexec skips the IN_Ack() waits on the screens that would
# otherwise sit there until somebody pressed something - the signon summary,
# the "not shareware" notice, the rating card - and drops straight into the
# title and the attract sequence.  The picowolf host build takes the same
# switch spelled --nowait, which is the other half of why this is the right
# route: both sides skip the same waits for the same reason.
#
# Driving it with synthetic keys instead is possible and works (see the
# wolf3d-ab-capture skill), but it is guesswork about how many notices this
# build shows: one key short parks the capture on a notice, one too many opens
# the main menu, where the attract sequence never starts.
#
# Get the game from its opening notices to the attract sequence.  The reasons
# this is a separate script, and why every simpler approach fails, are in
# clear_intro.sh - the short version is that NOWAIT skips the attract loop
# rather than entering it, so it cannot be used here.
#
if ! "$ROOT/tools/dosbox/clear_intro.sh" "$DISP" "$WIN" "$X" "$Y" "$WIDTH" "$HEIGHT"; then
    echo "capture.sh: could not reach the attract sequence" >&2
fi

# Lossless, so the comparison is against the emulator's pixels and not an
# encoder's idea of them.  70 fps is the mode 13h refresh rate.
DISPLAY=$DISP ffmpeg -loglevel error -f x11grab -framerate 70 \
    -video_size "${WIDTH}x${HEIGHT}" -i "$DISP.0+$X,$Y" \
    -t "$SECONDS_TO_RUN" -c:v ffv1 -level 3 -y "$OUT/video.mkv" &
FFMPEG_PID=$!

wait $FFMPEG_PID
FFMPEG_PID=

#
# A capture of a game sitting on a screen that wants a keypress is the failure
# this is guarding against, and it is invisible from the file size: right
# length, right duration, every frame identical.
#
frames=$(mktemp -d)
ffmpeg -loglevel error -i "$OUT/video.mkv" -vf 'fps=1/5,scale=320:200:flags=neighbor' \
    -y "$frames/f%03d.png" 2>/dev/null
uniq_count=$(md5sum "$frames"/*.png 2>/dev/null | awk '{print $1}' | sort -u | wc -l)
total=$(ls "$frames"/*.png 2>/dev/null | wc -l)
rm -rf "$frames"
echo "capture.sh: $uniq_count distinct screens in $total samples"
if [ "$uniq_count" -le 1 ]; then
    echo "capture.sh: the capture never changed - the game was parked on a" >&2
    echo "capture.sh: screen waiting for a key, and this recording is no use" >&2
fi

echo "capture.sh: done"
ls -la "$OUT"
