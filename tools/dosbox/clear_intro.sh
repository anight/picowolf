#! /bin/bash
#
# Get a Wolfenstein 3D - the DOS original or the port - from its opening
# screens to the attract sequence, and no further.
#
#   clear_intro.sh <display> <window> <x> <y> <width> <height>
#
# The game opens on screens that each wait for a key: the signon summary, the
# "not shareware" notice, the content rating card.  Past them is the title, and
# then the attract loop - credits, high scores, recorded demos - which is the
# part worth capturing because it is deterministic.
#
# Three approaches that do not work, so nobody tries them again:
#
#   NOWAIT (--nowait) looks like the switch for this and is the opposite of it.
#   It does skip the waits, but `while (!param_nowait)` in wl_main.c wraps the
#   whole attract loop, so the game goes straight past the title to the menu
#   and sits there.  A capture made with it contains a menu.
#
#   Pressing a fixed number of times depends on how many notices the build
#   shows.  One short parks the capture on a notice; one too many opens the
#   main menu from the title screen, and the attract sequence never starts.
#
#   Telling the title screen apart by counting colours - notices being flat
#   text, the title being a picture - fails on the first screen, because the
#   signon screen is itself a full 320x200 image.
#
# What does distinguish them: a waiting screen waits forever, and the title
# screen gives up after fifteen seconds and moves on by itself.  So after each
# keypress, watch without touching anything.  If the picture changes on its
# own, the attract loop is running and the job is done.  If it sits there, that
# was another notice and it needs another key.
#
set -u

DISP=$1; WIN=$2; X=$3; Y=$4; W=$5; H=$6
SELF_ADVANCE=20     # the title screen's own timeout is 15s

shot() {
    DISPLAY=$DISP ffmpeg -loglevel error -f x11grab -video_size "${W}x${H}" \
        -i "$DISP.0+$X,$Y" -frames:v 1 -y "$1" 2>/dev/null
}

DISPLAY=$DISP xdotool windowfocus "$WIN" 2>/dev/null
sleep 1

a=$(mktemp --suffix=.png); b=$(mktemp --suffix=.png)
trap 'rm -f "$a" "$b"' EXIT

for attempt in $(seq 1 6); do
    shot "$a"
    sleep "$SELF_ADVANCE"
    shot "$b"
    if ! cmp -s "$a" "$b"; then
        echo "clear_intro: picture moved on its own - attract sequence running"
        exit 0
    fi
    echo "clear_intro: static screen, sending key $attempt"
    DISPLAY=$DISP xdotool key --clearmodifiers Return
    sleep 2
done

echo "clear_intro: never saw the picture move by itself" >&2
exit 1
