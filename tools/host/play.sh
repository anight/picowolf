#!/bin/sh
#
# Run the desktop Wolf4SDL build.
#
# The port is fixed at 320x200, so a window is 1/16th the width of a modern
# display, and fullscreen scales it up without the game knowing.  Windowed is
# the default here because it stays out of the way; pass --fullscreen for the
# large version.
#
#   tools/host/play.sh                 a 320x200 window
#   tools/host/play.sh --fullscreen    scaled up to the display
#   tools/host/play.sh --tedlevel 0    start on E1M1 instead of the title
#
# Set DUMP to a directory to also save every presented frame as a BMP through
# tools/host/frame_dump.so; see this directory's README for the knobs.
#
#   DUMP=/tmp/frames tools/host/play.sh --windowed
#
# The joystick is disabled here, because Wolf4SDL opens joystick 0 by default
# and SDL enumerates some USB keyboards as joysticks - a Keychron K1's "System
# Control" collection appears as a one-axis stick parked at -32768.  Wolf then
# lets that axis overwrite the keyboard's direction on every read, which pins
# the menu to dir_West so the arrow keys do nothing, and turns the player left
# for ever in game.  Pass --joystick <n> after this to use a real one.
#
set -eu

# Wolf4SDL has no --help and treats an unrecognised option as "just start",
# so answer for it here rather than launching the game fullscreen at someone
# who only wanted to know the options.
case ${1-} in
-h|--help)
    sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
game=$here/../../Wolf4SDL

[ -d "$game" ] || { echo "play.sh: $game is missing" >&2; exit 1; }

missing=
for f in audiohed.wl6 audiot.wl6 gamemaps.wl6 maphead.wl6 \
         vgadict.wl6 vgagraph.wl6 vgahead.wl6 vswap.wl6; do
    [ -f "$game/$f" ] || missing="$missing $f"
done
if [ -n "$missing" ]; then
    echo "play.sh: Wolfenstein 3D v1.4 GT data missing from $game:$missing" >&2
    echo "play.sh: these are yours to supply and are never committed" >&2
    exit 1
fi

# The game is built by its own Makefile and writes its config and savegames
# into the directory it runs from, which is why we go there rather than
# pointing at the binary from here.
make -C "$game" -s

if [ -n "${DUMP-}" ]; then
    [ -f "$here/frame_dump.so" ] || make -C "$here" -s
    mkdir -p "$DUMP"
    WOLF_DUMP_DIR=$DUMP
    export WOLF_DUMP_DIR
    LD_PRELOAD=${LD_PRELOAD-}${LD_PRELOAD:+:}$here/frame_dump.so
    export LD_PRELOAD
    echo "play.sh: saving frames to $DUMP" >&2
fi

cd "$game"

# Wolf4SDL has no --fullscreen; it has --windowed and defaults to fullscreen.
# Since this script defaults the other way, spell the inverse here.
for arg
do
    [ "$arg" = --fullscreen ] || set -- "$@" "$arg"
    shift
    [ "$arg" != --fullscreen ] || windowed=
done

# These come first so a caller's own --windowed or --joystick wins: Wolf4SDL's
# option loop keeps the last occurrence.
exec ./wolf4sdl ${windowed---windowed} --joystick -1 "$@"
