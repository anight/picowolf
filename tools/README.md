# picowolf host tools

Host-side work happens here first.  Anything that can be proved on a desktop
should be proved there before it is built for the board, where the only
instrument is a serial console.

```
host/       helpers for running and inspecting the desktop Wolf4SDL build
```

Still to come: the asset converter and its tests.  Generated resources belong
in `../generated/` and are ignored because they derive from user-supplied
original game files.

## host/frame_dump.so

An `LD_PRELOAD` shim that interposes on `SDL_UpdateWindowSurface()` and saves
each presented frame as a BMP.  Wolf4SDL's video path now presents through the
window surface rather than a renderer and texture, which is the only path
PicoSDL offers; this captures exactly what reaches that surface, with no
debug hook added to the game and no display attached.

```bash
make -C tools/host
cd Wolf4SDL
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
WOLF_DUMP_DIR=/tmp/frames WOLF_DUMP_EVERY=15 WOLF_DUMP_MAX=40 \
LD_PRELOAD=../tools/host/frame_dump.so ./wolf4sdl --windowed --nowait
```

| variable | meaning |
|---|---|
| `WOLF_DUMP_DIR` | where to write `frameNNNNN.bmp` (default: the working directory) |
| `WOLF_DUMP_EVERY` | save every Nth present (default 1) |
| `WOLF_DUMP_MAX` | stop after this many saved frames, 0 for no limit (default 0) |
| `WOLF_DUMP_VERBOSE` | name every saved frame on stderr, so a debugger breakpoint logged alongside says which frames a given call produced |

The BMP comes from the window surface itself, so a wrong palette, a missing
blit and a frame that was never presented all show up in the output.  A frame
sequence also makes a before/after comparison possible for later steps of the
port: the pixels that reach the panel are the thing being preserved.
