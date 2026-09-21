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

## The converted resources are not built or used yet

`tools/assets/convert.py` produces them and `verify.py` checks them, but
nothing consumes them: `src/CMakeLists.txt` still builds only the bring-up
firmware, and the game still reads the `.wl6` files through `CA_Startup()` and
`PM_Startup()` into 2.1 MB of SRAM.

Two pieces remain, and they go together.  A firmware target that compiles
Wolf4SDL and links `generated/wolf_assets.S`; and the cache and page managers
rewritten against the span tables - `PM_GetPage()` returning a pointer into
flash instead of into `PMPageData`, `grsegs[]` becoming
`wolf_vgagraph + wolf_grspans[chunk].offset`, `audiosegs[]` the same, and
`CA_CacheMap()` decompressing into one fixed 24,576-byte buffer rather than
three allocations per level.

The report says it fits: 2,305,798 bytes of resources and 496,008 of bring-up
firmware is 66.8% of the flash, leaving 1.39 MB, and it takes 2,146,429 bytes
out of a 524,288-byte SRAM that could never have held them.

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

## `screen.surface` and `screen.buffer` should be one buffer

The game draws into `screen.buffer` and `VW_UpdateScreen()` blits it to
`screen.surface`.  On PicoSDL `SDL_GetWindowSurface()` wraps the client's own
canvas without copying, so that blit becomes a 64,000-byte memcpy per frame
that achieves nothing, and holding both costs 125 KB of an SRAM that already
has around 350 KB of fixed demand.

`FizzleFade()` is what stands in the way: it dissolves the new frame into the
displayed one, so it genuinely wants a source and a destination.  Everything
else in the video path draws into `screen.buffer` and would not notice the
collapse.  Whatever replaces it has to keep the dissolve without keeping a
second full-screen buffer alive for the rest of the frame's life.

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
