# picowolf host tools

Host-side work happens here first.  Anything that can be proved on a desktop
should be proved there before it is built for the board, where the only
instrument is a serial console.

```
assets/     the converter that turns the .wl6 files into flash resources
host/       helpers for running and inspecting the desktop Wolf4SDL build
```

Generated resources belong in `../generated/` and are ignored, because they
derive from user-supplied original game files.

## assets/

```bash
tools/assets/convert.py --data Wolf4SDL --gfxheader Wolf4SDL/gfxv_wl6.h \
                        --out generated --firmware 496008
tools/assets/verify.py
```

`convert.py` reads one Wolfenstein 3D v1.4 GoodTimes data set and writes
`generated/`: four `.bin` blobs, an assembler stub that `.incbin`s them into
`.rodata`, the small tables the game indexes as generated C, and a size report.

What it decides and why is in its module docstring; the short version is that
graphics are decoded and deplaned into flash because flash is what this project
has spare, and maps stay Carmack+RLEW compressed because decoding all sixty
levels would be 1.4 MB against 148 KB.

`wl6.py` is the reader underneath: `CAL_HuffExpand`, `CAL_CarmackExpand`,
`CA_RLEWexpand` and `VW_DePlaneVGA` transcribed into Python, with the chunk
numbering read out of `gfxv_wl6.h` rather than repeated.

To build the desktop game against them:

```bash
make -C Wolf4SDL FLASH_ASSETS=$PWD/generated
```

That binary needs no data files at all - it will run in an empty directory -
and its framebuffer is byte-identical to the file-reading build's.

`verify.py` checks the result two ways.  It rebuilds every blob and compares it
with what is on disk, which catches anything truncated or corrupted; and it
runs the desktop game under gdb, dumps chunks out of its live `grsegs`,
`mapsegs` and `PMPages`, and compares those against the generated blobs and
span tables - which is the only way to know that four reimplemented decoders
agree with the originals.  Corrupting a blob, a span offset, or a decoder each
make it fail, and all three were checked.

## host/play.sh

Builds the desktop game if needed and runs it from `../Wolf4SDL`, where its
data, config and savegames live.  It checks the eight `.wl6` files are present
and names the missing ones rather than failing inside the cache manager.

```bash
tools/host/play.sh                 # fullscreen
tools/host/play.sh --windowed      # a 320x200 window
tools/host/play.sh --tedlevel 0    # straight into E1M1
DUMP=/tmp/frames tools/host/play.sh --windowed
```

The port is fixed at 320x200, so on a large display a window is very small and
fullscreen is the comfortable way to look at it - the X server scales the mode
up and the game still presents exactly 320x200 indexed pixels.

Default controls: arrows move, `Ctrl` fire, `Alt` strafe, `Shift` run, `Space`
open, `1`-`4` weapons, `Esc` menu.

It passes `--joystick -1`.  Wolf4SDL opens joystick 0 by default, and SDL
enumerates some USB keyboards as joysticks: a Keychron K1's "System Control"
collection arrives as a one-axis stick parked at -32768.  `ReadAnyControl()`
then overwrites the direction the keyboard just produced on every read, so the
menu sees `dir_West` for ever and the arrow keys do nothing, while in game
`PollJoystickMove()` turns the player left and never lets go.  This is upstream
behaviour - unmodified Wolf4SDL does the same on this machine - and the option
is the documented way out.  Pass `--joystick <n>` after the script's own
arguments to use a real one; Wolf4SDL keeps the last occurrence.

Still to come: the asset converter and its tests.  Generated resources belong
in `../generated/` and are ignored because they derive from user-supplied
original game files.

## host/resample_check

Compares the port's fixed-point digi resampler against the float quadratic it
replaced, at each sample rate worth considering, and checks the properties that
have to hold whatever the interpolator: a null source is silent, past the end
is silent, a constant 128 is exactly silence with no DC, and mixing saturates
instead of wrapping.

```bash
make -C tools/host check
```

The two are different interpolators, so this characterises the gap rather than
demanding a match - 37 dB SNR on a sine, and much less on noise, because at
7042 Hz consecutive samples are unrelated and any disagreement is large.

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

## dosbox/

The original DOS game, captured as a reference to compare the port against.
It needs your own copy of Wolfenstein 3D in `dosbox/` - the executable and its
data - which, like the `.wl6` files in the Wolf4SDL submodule, is never
committed.

```bash
tools/dosbox/capture.sh 120
tools/dosbox/compare_video.py --dos captures/dos/video.mkv --pw captures/pw/frames
tools/dosbox/compare_audio.py --dos captures/dos/audio.raw --pw captures/pw/audio.raw
```

`capture.sh` runs DOSBox-X on its own Xvfb display rather than on the desktop.
That is not tidiness: this session is GNOME on Wayland, where the emulator
window lives under XWayland, synthetic key events never reach it - the
compositor owns the keyboard, and the 1x1 window holding X focus is XWayland's
focus proxy - and `x11grab` of the root returns black, because XWayland windows
are not composited into it.  Both work inside Xvfb, where there is no
compositor, and the run cannot type into whatever the user has open.

It captures without touching DOSBox-X's capture hotkeys, which would need
synthetic input to reach the mapper: video comes from `x11grab` on the Xvfb
display, and audio from SDL's disk audio driver, which writes what the mixer
produces to a file instead of to a sound card.  The picowolf host build is
captured the same way, so the two are the same format - 44100 Hz stereo signed
16-bit - with no resampler in between.

`reference-x.conf` is the emulator side of that: `vgaonly`, `core=normal` and
`cycles=fixed 20000` so two runs agree, `scaler=none` so the window is the
game's pixels doubled exactly and a capture can be halved back to 320x200
without guessing.

`compare_video.py` reduces both sides to palette indices before comparing
anything.  A VGA DAC takes 6 bits per channel and the two paths widen them to 8
differently, so comparing RGB would report every pixel of an identical picture
as a difference; which palette entry each pixel got is what the port is
responsible for.

`compare_audio.py` aligns the two captures first - each run started its attract
sequence when it felt like it - by correlating 10 ms energy envelopes rather
than samples, since that only requires the same notes at the same times, not
two OPL renderings agreeing phase for phase.
