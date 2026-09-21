# TODO

Things this port owes, roughly in the order they get in the way.  The port
assessment and the order of the larger work are in [PLAN.md](PLAN.md); this is
the running list of what has been found since.

## picosdl is a symlink, not a submodule

The bring-up target is building again, and `src/picosdl_version.cmake` now
warns on every build when PicoSDL is not the revision recorded in
`src/CMakeLists.txt`, naming the commits that moved.  That is enough to stop
the same five days of silent breakage happening twice, but it is not the thing
PLAN asks for.

`picosdl` is a symlink into the picopop checkout, which is convenient while
both are being worked on - an edit is immediately live in both projects - and
means picowolf records no revision of its own and cannot be cloned and built
by anyone else.  Making it a proper submodule splits that shared tree, so it
is a decision about how the two projects are developed rather than a cleanup.
Wolf4SDL has the same shape: a local clone tracking bitbucket, with the port
commits on top and no fork pushed anywhere.

## VW_UpdateScreen waits out the whole panel transfer

With one framebuffer the game has to wait for the DMA before drawing again,
and `VW_UpdateScreen()` does that with `PSDL_PresentSync()` immediately after
presenting.  That is correct and it gives up the overlap the frame rate came
from: on the board the CPU now sits through the whole transfer doing nothing.

The wait belongs just before the next draw rather than just after the present.
`VW_UpdateScreen()` is the only point the game reliably passes through between
the two - menus, the HUD and the 3D view all draw from their own places - so
moving it means finding a later safe point, or gating every entry to the
framebuffer on `PSDL_BufferBusy()`.  Worth measuring what it costs before
deciding how much to spend on it.

## The PicoSDL host build does not model DMA

`tools/host/psdl_host_backend.c` runs the real library on a desktop, and that
is how the tearing above was pinned down - every pixel and every palette entry
matched the SDL2 build, which left only the way they reach the panel.  But its
present is a synchronous copy and `psdl_backend_video_buffer_busy()` always
answers no, so the class of bug it just helped find is one it cannot itself
reproduce.

Making the present asynchronous there - a pending transfer with a deadline,
`buffer_busy` true until it passes - would catch a one-buffer client writing
over a frame in flight on the host.  It would also model the panel being
320x240 with the canvas letterboxed, which it currently does not: it assumes
the canvas is the panel.

## 22,808 bytes of SRAM are tables that could be in flash

Five arrays are computed once at startup and only read afterwards, so each is a
constant the build could work out instead of the board:

| table | bytes | computed from |
|---|---|---|
| `DBOPL::WaveTable` | 8,192 | `sin` and `pow`, in `InitTables()` |
| `redshifts` | 6,144 | `gamepal`, in `InitRedShifts()` |
| `finetangent` | 3,600 | `tan`, in `BuildTables()` |
| `whiteshifts` | 3,072 | `gamepal`, in `InitRedShifts()` |
| `sintable` | 1,800 | `sin`, in `BuildTables()` |

`gamepal` is already a const include in flash, so the two shift tables are a
pure function of data the build has.  The other three are arithmetic.  Moving
all five takes SRAM from 53.3% of a Pico 2 W to 49.0%.

picopop has done this for `DBOPL::WaveTable` already - `tools/assets/dbopl_tables.c`
generates it and `PICOPOP_DBOPL_CONST_TABLES` switches `dbopl.cpp` over - so
that one is a port rather than a design.  Each needs a test that checks the
generated table against the expression it replaces, and the test needs checking
that it fails when the table is wrong; a table nobody verified is worse than a
table computed at boot.

Nothing else in the top of the SRAM list can move.  The framebuffer, the map
planes and their scratch, the demo buffer, `actorat`, `objlist`, `tilemap`,
`spotvis`, `statobjlist` and `vislist` are all written while the game runs, and
the rest belongs to PicoSDL and the Bluetooth stack.

## Persistence is the last filesystem use left

strace over a full run of the flash build - startup, signon, a demo, exit -
shows no access to any of the eight data files.  What remains is `~/.wolf4sdl`,
`config.wl6` read at startup and written at exit, and ten savegame slots probed
by `SetupSaveGames()`.

That is PLAN item 8, and it needs a decision before it needs code: either the
first firmware has no persistence at all, or there is a bounded LittleFS-backed
store and a versioned, validated format to put in it.  The config magic bump
was a patch on the symptom; raw structs written straight to storage are what
caused it.

## `VW_SetPalette()` writes the CLUT twice

It sets `screen.buffer`'s palette and then `screen.surface`'s.  On the desktop
those are two different `SDL_Palette` objects and only the first matters.  On
PicoSDL there is exactly one palette - `SDL_SetPaletteColors()` opens with
`(void)palette; /* there is only one */` - so both calls write the same
hardware CLUT, each one paying a full `dispSetClut()` upload and a
`psdl_backend_video_sync()` wait on the in-flight panel DMA.

A full fade is 30 steps, so that is 60 uploads and 60 syncs where 30 would do.
The guard is to skip the second write when the two surfaces already share a
palette.

## Audio: what is left after SDL_mixer

SDL_mixer is gone - one `SDL_OpenAudio` callback runs the voices, the OPL and
the speaker - and `SD_PrepareSound()` no longer expands anything.  What remains
is measurement on the board rather than design.

The whole audio inventory is 711,871 bytes of flash: 9,986 of PC speaker
sounds, 12,969 of AdLib sounds, 297,250 of IMF music and 391,666 of digitised
sound.  DBOPL costs 938 instructions per output sample, so 16.5% of one 125 MHz
core at 22050 Hz and 8.3% at 11025, on the core that does nothing else - but
that is picopop's measurement of picopop's build, and this one has eight voices
resampling alongside it.  The mixer needs a load report of its own before the
sample rate and the voice count are settled.

The rate is still 44100 by default, which no target wants.  `--samplerate`
already accepts anything from 7042 up; picking the number is waiting on the
load report.

`SD_SoundPlaying()` still answers only for the PC speaker and the AdLib
channel, as it always did, so `SD_WaitSoundDone()` does not wait for a
digitised sound.  That was true under SDL_mixer too and nothing depends on it
yet, but it is a surprise worth removing rather than inheriting.

## Input assumes a desktop, and trusts whatever SDL enumerates

`IN_Startup()` opens joystick 0 by default and `ReadAnyControl()` then applies
the joystick after the keyboard without checking that the axis has moved, so a
stick resting off-centre overwrites the direction the player just typed.  On
this machine SDL enumerates a Keychron K1's "System Control" HID collection as
a one-axis joystick parked at -32768: the menu saw `dir_West` for ever, the
arrow keys did nothing, and in game `PollJoystickMove()` turned the player left
and never stopped.  `tools/host/play.sh` passes `--joystick -1` to get out of
the way of it, which is a workaround and not the fix.

The fix is the one PLAN item 7 already describes, and this is the shape of it:
the board has one known stick and no mouse, so the port should name the devices
it uses instead of probing, and an axis should only override a key when it has
actually left centre.  `MousePresent` becomes false and the mouse grab and warp
calls go with it.
