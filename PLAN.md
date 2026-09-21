# Wolf4SDL → Pico 2 W: initial port assessment

## Scope and baseline

The target should be the current `Wolf4SDL` default build: Wolfenstein 3D
GoodTimes v1.4 (`CARMACIZED` + `GOODTIMES` in `Wolf4SDL/version.h`), at its
native 320×200 logical resolution.  Do not try to support the full matrix of
Wolf/Spear/shareware/Japanese variants in the first Pico build.

`picosdl` is a suitable *hardware layer*, but it is not a drop-in SDL2 plus
SDL_mixer replacement.  It deliberately provides one 8-bit indexed 320×200
surface, fixed pools, an audio callback, keyboard/controller events, and no
filesystem.  The present workspace has only an empty `src/`; it does not yet
have the Picopop-style build, entry point, asset pipeline, or project metadata.

## Principal problems

1. **Game assets cannot be loaded as files at run time.**  Wolf4SDL opens and
   seeks through `vgahead/vgagraph/vgadict`, `maphead/gamemaps`, `audiohed/audiot`
   and `vswap` in `id_ca.c` and `id_pm.c`.  PicoSDL's `SDL_RWFromFile` explicitly
   fails and the firmware has no disk filesystem.  The supplied Wolf data alone
   is 2,294,043 bytes.  A host-side converter must turn one verified `.wl6`
   data set into flash-resident resources (and retain the offsets/metadata the
   cache manager needs), or an SD/FAT filesystem must be deliberately added.
   Flash resources are the right first route: it matches Picopop and avoids
   runtime I/O and large RAM copies.

2. **The current cache/page managers assume a general heap and load far too
   much into RAM.**  `PM_Startup()` copies the whole VSWAP page region into
   `PMPageData`; `CA_Startup`, `CA_CacheGrChunk`, `CA_CacheMap`, and
   `CA_CacheAudioChunk` repeatedly allocate and free decoded chunks.  PicoSDL
   intentionally has no allocator; its 16 KiB arena is LIFO-only and is not an
   asset cache.  The 520 KiB SRAM also already has meaningful fixed demand:
   Picopop's built image reports 351,276 bytes of `.bss` with PicoSDL's two
   framebuffers, Bluetooth, and audio enabled.  Replace the managers with
   fixed ownership: const XIP data for immutable compressed/decoded assets,
   bounded static decode/cache buffers for the few mutable items, and explicit
   RAM budgets/high-water reporting.  Do not replace `SafeMalloc` with the
   PicoSDL arena globally.

3. **Raw embedding will not fit without an asset budget and conversion.**
   Picopop's existing all-feature firmware is 1,947,312 bytes of flash.  Adding
   Wolf4SDL's raw 2.29 MiB data to an equivalently configured image already
   exceeds the Pico 2 W's 4 MiB flash before Wolf code, metadata, or alignment.
   The converter therefore needs to measure output and decide per class whether
   to retain compressed source, predecode, deduplicate, or omit optional data.
   It must also fail the build with a useful flash/RAM report.

4. **Wolf4SDL's video path is built around desktop SDL rendering, not PicoSDL.**
   `id_vl.c` creates an ARGB8888 screen, a separate indexed `screenBuffer`, an
   SDL renderer/texture, and presents with `SDL_UpdateTexture`/`SDL_Render*`
   (`id_vh.c`).  PicoSDL exposes none of the renderer/texture API and only
   supports indexed 320×200 surfaces.  Rework this path to draw directly into
   the window surface (or one supported 320×200 off-screen surface), set the
   global palette, and call `SDL_UpdateWindowSurface`.  Fix the port at
   `screenWidth=320`, `screenHeight=200`, `screenBits=8`, and `scaleFactor=1`;
   remove desktop fullscreen/resize/OpenGL/scaling assumptions.  The raycaster
   and panel transfer must then be measured on hardware before enabling optional
   visual features.

5. **SDL API compatibility is incomplete even before linking.**  Wolf includes
   `<SDL.h>` and `<SDL_syswm.h>`, while PicoSDL exports `<SDL2/SDL.h>`.  It also
   calls missing renderer/texture APIs, `SDL_PixelFormatEnumToMasks`, mouse and
   relative-mode APIs, `SDL_WaitEvent`, joystick hat/button-count APIs,
   `SDL_EventState`, and `SDL_MUSTLOCK`.  Add a small Wolf-specific platform
   adaptation layer and remove unneeded desktop behaviour rather than expanding
   PicoSDL into a fake desktop SDL.  A compile-time API audit target should make
   every remaining unsupported use intentional.

6. **SDL_mixer is the largest functional mismatch.**  `id_sd.c` relies on
   `Mix_OpenAudioDevice`, chunk loading from generated WAV data, channel groups,
   reservation/oldest-channel selection, per-channel panning, completion
   callbacks, music hooks, and a post-mix PC-speaker callback.  PicoSDL only
   offers `SDL_OpenAudio` and one pull callback running on the audio core.
   Port the sound manager to one bounded, allocation-free mixer: mix digitised
   effects with per-voice position/priority, PC-speaker synthesis, and OPL/IMF
   music in that callback.  Preconvert digitised samples during the asset build
   instead of allocating WAV buffers in `SD_PrepareSound()`.  Reuse/benchmark a
   Pico-appropriate OPL core (Picopop's DBOPL path is the useful reference);
   Wolf4SDL's default MAME OPL implementation itself allocates.

7. **Input must be redesigned for the devices that actually exist.**
   Wolf treats a mouse as present on normal builds, grabs it, consumes relative
   motion, and supports joystick hats/buttons (`id_in.c`).  PicoSDL provides a
   Bluetooth keyboard, analog stick, and optionally a mapped game controller;
   it has no mouse/hat implementation and no desktop focus/grab semantics.
   Make the Pico mapping explicit (stick for turn/move, controller buttons for
   fire/use/run/strafe, keyboard fallback), set `MousePresent=false`, and remove
   mouse grab/warp code.  Adapt `IN_Startup`, acknowledgement, menus, and key
   binding defaults so a controller-only board remains playable.

8. **Persistent configuration and save games have no backend.**  Configuration,
   high scores, saves, and demo recording use `FILE*`, `stat`, `mkdir`, `$HOME`,
   and native-layout `fread`/`fwrite` in `wl_main.c` and `wl_menu.c`.  Decide
   early whether the first firmware disables persistence or adds a bounded
   LittleFS/FatFs-backed storage layer.  The latter also needs a versioned,
   validated serialization format; raw structs and pointer-offset fixups are
   not a safe long-term on-flash format.

9. **Several dynamic/transient rendering paths still allocate.**  Examples
   include fullscreen/raycast lookup tables in `id_vl.c`, deplaning scratch
   space, graphics decompression, text layout, and the `MAXDEMOSIZE` demo
   buffer.  Inventory each allocation by maximum size and lifetime, then make
   it static, stack-bounded, flash-resident, or disable the feature.  All error
   and shutdown paths must stop using `free()` on memory they do not own.

10. **The startup/exit model is desktop-oriented.**  `wl_main.c` owns
    `main(argc, argv)`, parses filesystem/desktop command-line options, calls
    `atexit`, and uses `exit()` from errors.  The firmware needs a Picopop-like
    `src/main.c` to set the Pico clock/stdio, provide a fixed argv/configuration,
    call a renamed Wolf entry point, and turn fatal errors into a serial-visible
    halt or controlled reboot.  The port should not silently preserve options
    such as arbitrary resolution, window mode, or filesystem paths that cannot
    work on the board.

11. **Data layout and toolchain assumptions need an explicit audit.**
    Wolf uses `#pragma pack(1)`, unaligned game-file structs, native `long` and
    pointer representations, `math.h`, POSIX headers, and serializes structs
    containing pointer-derived values.  Cortex-M33 is little-endian and
    32-bit, which helps, but that is not a license to dereference unaligned
    packed fields or preserve host ABI files blindly.  Use fixed-width types and
    byte readers for converted assets, link only the required Pico math support
    (or generate tables), and run host tests for decompression, map loading,
    and save compatibility.

## Recommended project shape

Copy Picopop's separation, not its game-specific code:

```
src/        Pico SDK CMake entry point, firmware main, Wolf platform adapters
picosdl/    existing reusable SDL subset (submodule/link dependency)
Wolf4SDL/   upstream game source, kept minimally patched or as a submodule
tools/      host build, tests, and Wolf asset conversion scripts
generated/  ignored converted Wolf resources and generated tables
```

The root README and `.gitmodules` should document the exact supported Wolf data
release and state that original game assets are user supplied and never
committed.  `src/CMakeLists.txt` should follow Picopop: bootstrap the Pico SDK,
add PicoSDL as a subdirectory, run the converter at configure/build time, build
the selected Wolf source set, and emit UF2/ELF plus a map/size report.  Keep a
PicoSDL demo target as the independent board bring-up test.

## Suggested implementation order

1. Scaffold the Picopop-style repository/build and a PicoSDL-only firmware
   target; verify it flashes before importing game code.
2. Add a desktop-host Wolf target and an asset converter with tests; support one
   `wl6` release only and produce a flash/RAM size report.
3. Port the data/cache/page interfaces to generated resources and fixed memory;
   prove title/menu rendering without audio or persistence.
4. Replace the video path with the 320×200 indexed direct-present path; profile
   the raycaster and establish a frame-time budget.
5. Port keyboard/controller input and the allocation-free audio mixer/OPL path.
6. Add saves/configuration only after choosing and testing a filesystem and
   serialized format; then add optional features and broader data variants.

## Acceptance checks for the first playable build

- Cold boot reaches the title screen from generated, user-supplied assets with
  no heap allocation from game code.
- A keyboard and the board controller can navigate menus and complete gameplay
  controls without mouse support.
- Palette fades, walls, sprites, and HUD render correctly at 320×200 without
  out-of-bounds surface writes.
- Digitised effects, PC-speaker effects, and IMF music mix without audio
  underruns; report audio/core load over serial.
- Build reports flash and static RAM use and stays within the selected Pico 2 W
  board limits; host asset/decompression tests and a hardware smoke test pass.
