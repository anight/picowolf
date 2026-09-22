# picowolf

Wolfenstein 3D on a Raspberry Pi Pico 2 W: Wolf4SDL built against
[PicoSDL](https://github.com/anight/picosdl), a subset of SDL2 for the RP2040
and RP2350.

The board runs the game at 320x200 in 256 indexed colours, out of flash, with
AdLib music and digitised sound mixed on the second core, the analog stick and
an I2C gamepad both live, and PicoSDL's status bands above and below the
picture.

## Layout

```
src/        main.c for the bring-up, wolf_main.c for the game
picosdl/    the SDL2 subset, a submodule
Wolf4SDL/   the game, a submodule on its picowolf branch
tools/      the asset pipeline and the desktop-side helpers
generated/  the converted resources, derived from your own data files
```

## Building

```bash
git clone --recurse-submodules https://github.com/anight/picowolf.git
```

The game's data files are not here and never will be: put your own
Wolfenstein 3D v1.4 GoodTimes set - the eight `.wl6` files - in `Wolf4SDL/`
and convert them.

```bash
tools/assets/convert.py --data Wolf4SDL --gfxheader Wolf4SDL/gfxv_wl6.h \
                        --out generated --firmware 496008
cmake -S . -B build
cmake --build build
picosdl/picodev.sh flash build/picowolf.elf
```

Without `generated/` the build still produces `picowolf-bringup`, a
PicoSDL-only firmware with no game code in it, which is the fastest way to
separate a board fault from a game fault.

## Desktop

Everything that can be proved on a desktop is proved there first; see
[tools/README.md](tools/README.md) for the converter's tests, the frame
dumper and the launcher.

```bash
make -C Wolf4SDL FLASH_ASSETS=$PWD/generated
tools/host/play.sh
```

That binary reads no data files at all - it runs in an empty directory - and
its framebuffer is byte-identical to the one the file-reading build produces.

## Where the work is

The port assessment and implementation order are in [PLAN.md](PLAN.md); what
the port still owes is in [TODO.md](TODO.md).
