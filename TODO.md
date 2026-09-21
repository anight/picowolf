# TODO

Things this port owes, roughly in the order they get in the way.  The port
assessment and the order of the larger work are in [PLAN.md](PLAN.md); this is
the running list of what has been found since.

The board runs the game: 320x200 indexed out of flash, one framebuffer, AdLib
music and digitised sound mixed on core 1 at 22050 Hz, the analog stick and the
I2C pad both live, status bands top and bottom.  Flash is 75.1% of 4 MiB and
RAM 58.3% of 512 KiB.  What follows is what is still wrong with that.

## Nobody but this machine can build it

`anight/picowolf` now has all of its history on `master`, and cloning it gets
you a tree that does not build.  Two of its three parts are missing:

- `picosdl` is a symlink into the picopop checkout.  Convenient while both are
  being worked on - an edit is immediately live in both projects - and it means
  picowolf records no revision of its own.  `src/picosdl_version.cmake` warns on
  every build when PicoSDL is not the commit named in `src/CMakeLists.txt` and
  lists what moved in between, which stops another five days of silent
  breakage, but it is a smoke alarm, not the submodule PLAN asks for.
- `Wolf4SDL` is a local clone of bitbucket with fourteen port commits on top and
  nowhere to push them.  Its `origin` points at `anight/picowolf`, which is
  wrong - two unrelated root histories cannot both be `master` there.  Once a
  fork exists:

  ```
  git -C Wolf4SDL remote set-url origin git@github.com:anight/Wolf4SDL.git
  git -C Wolf4SDL push -u origin master:picowolf
  ```

Both are decisions about how the projects are developed rather than cleanups,
which is why neither has been made yet.  Until they are, the board build is
reproducible only here.

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
all five takes RAM from 58.3% to 53.9%.

Measure with `arm-none-eabi-size -A`, and count `.data` as well as `.bss`: the
53.3% quoted during the allocation work left `.data` out, which at the time was
87,884 bytes - 64,000 of them the signon screen, which was `byte signon[]`
rather than `const` and so lived in RAM as well as flash for the whole run.
Making it const was the cheapest 64,000 bytes on this list and is done.

picopop has done this for `DBOPL::WaveTable` already - `tools/assets/dbopl_tables.c`
generates it and `PICOPOP_DBOPL_CONST_TABLES` switches `dbopl.cpp` over - so
that one is a port rather than a design.  Each needs a test that checks the
generated table against the expression it replaces, and the test needs checking
that it fails when the table is wrong; a table nobody verified is worse than a
table computed at boot.

Nothing else near the top of the RAM list can move.  `PanelCanvas`, the map
planes and their scratch, the demo buffer, `actorat`, `objlist`, `tilemap`,
`spotvis`, `statobjlist` and `vislist` are all written while the game runs, and
the rest belongs to PicoSDL, the status bands and the Bluetooth stack.

## VW_UpdateScreen waits out the whole panel transfer

With one framebuffer the game has to wait for the DMA before drawing again, and
`VW_UpdateScreen()` does that with `PSDL_PresentSync()` immediately after
presenting.  That is correct, and it gives up the overlap the frame rate came
from: the CPU sits through the whole transfer doing nothing.

The wait belongs just before the next draw rather than just after the present.
`VW_UpdateScreen()` is the only point the game reliably passes through between
the two - menus, the HUD and the 3D view all draw from their own places - so
moving it means finding a later safe point, or gating every entry to the
framebuffer on `PSDL_BufferBusy()`.

The status band cannot answer what it costs.  Core 0's load there is time spent
outside `PSDL_CpuIdle()`, and both the present sync and `wl_draw.c`'s tic cap
(`SDL_Delay` in `CalcTics`) report idle, so the header blends the stall with the
frame limiter.  Timing `PSDL_PresentSync()` itself is what decides whether this
is worth the restructuring.

## Persistence is the last filesystem use left

strace over a full run of the flash build - startup, signon, a demo, exit -
shows no access to any of the eight data files.  What remains is `~/.wolf4sdl`,
`config.wl6` read at startup and written at exit, and ten savegame slots probed
by `SetupSaveGames()`.  On the board `$HOME` does not exist and the lookup is
compiled out, so the firmware forgets everything between runs.

That is PLAN item 8, and it needs a decision before it needs code: either the
first firmware keeps no state at all, or there is a bounded LittleFS-backed
store and a versioned, validated format to put in it.  The config magic bump
was a patch on the symptom; raw structs written straight to storage are what
caused it.

## `VW_SetPalette()` writes the CLUT twice

It sets `screen.buffer`'s palette and then `screen.surface`'s.  On the desktop
those are two different `SDL_Palette` objects and only the first matters.  On
the board they are now the same surface - one framebuffer - and PicoSDL has
exactly one palette anyway, `SDL_SetPaletteColors()` opening with
`(void)palette; /* there is only one */`.  So both calls write the same hardware
CLUT, each paying a full `dispSetClut()` upload and a wait on the in-flight
panel DMA.

A full fade is 30 steps, so that is 60 uploads and 60 syncs where 30 would do.
The guard is to skip the second write when the two surfaces already share a
palette.

## Audio: measurement, and one inherited surprise

SDL_mixer is gone - one `SDL_OpenAudio` callback runs the eight digi voices, the
OPL and the speaker - `SD_PrepareSound()` no longer expands anything, and the
rate is 22050 Hz, passed as `--samplerate` from `src/wolf_main.c` and confirmed
by the board (`audio 22050 Hz stereo, 256-frame blocks (11.6 ms)`).

What is left is the load report that rate was picked without.  DBOPL costs 938
instructions per output sample, so 16.5% of one 150 MHz core at 22050 by
picopop's measurement of picopop's build; this one has eight resampling voices
alongside it.  The figure is now readable rather than estimated: core 1 reports
through `PSDL_CpuIdle()` from inside PicoSDL's audio callback, and the status
band header prints it.  Read it with music and several sounds playing before
deciding whether 22050 and eight voices are the right pair.

`SD_SoundPlaying()` still answers only for the PC speaker and the AdLib channel,
as it always did, so `SD_WaitSoundDone()` does not wait for a digitised sound.
That was true under SDL_mixer too and nothing depends on it yet, but it is a
surprise worth removing rather than inheriting.

## The PicoSDL host build does not model DMA

`tools/host/psdl_host_backend.c` runs the real library on a desktop, and that is
how the board's tearing was pinned down - every pixel and every palette entry
matched the SDL2 build, which left only the way they reach the panel, and the
fault was a missing `PSDL_PresentSync()`.  But its present is a synchronous copy
and `psdl_backend_video_buffer_busy()` always answers no, so the class of bug it
just helped find is one it cannot itself reproduce.

Making the present asynchronous there - a pending transfer with a deadline,
`buffer_busy` true until it passes - would catch a one-buffer client writing
over a frame in flight, on the host, before it reaches a board.  It would also
model the panel being 320x240 with the canvas letterboxed, which it currently
does not: it assumes the canvas is the panel, and so never exercises the bands.

## Input still probes instead of naming its devices

The board's half is settled.  `--joystick 0` is PicoSDL's single device, the
analog stick and the I2C pad arrive merged, `IN_JoyButtons()` reads A/B/X/Y,
Start and Back from the game controller API and ORs in the stick click from the
joystick API, and the movement axes come from `SDL_CONTROLLER_AXIS_LEFTX/Y`.
`MousePresent` is false under `PICOWOLF` and the grab and warp calls are
compiled out.  Three separate bugs came out of that one device reaching the
client through two APIs, which is worth remembering before touching it again.

The desktop half is not.  `IN_Startup()` opens joystick 0 by default and
`ReadAnyControl()` applies the joystick after the keyboard without checking that
the axis has moved, so a stick resting off-centre overwrites the direction the
player just typed.  On this machine SDL enumerates a Keychron K1's "System
Control" HID collection as a one-axis joystick parked at -32768: the menu saw
`dir_West` for ever, the arrow keys did nothing, and in game
`PollJoystickMove()` turned the player left and never stopped.  This is upstream
behaviour, proved against an unmodified checkout, and `tools/host/play.sh`
passes `--joystick -1` to get out of its way, which is a workaround and not the
fix.

The fix is PLAN item 7: an axis should only override a key when it has actually
left centre, and the port should name the devices it uses rather than taking
whatever SDL enumerated first.
