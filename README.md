# picowolf

An in-progress Raspberry Pi Pico 2 W port of Wolf4SDL using PicoSDL.

## Current state

`src/` builds a PicoSDL-only bring-up firmware.  It is intentionally independent
of Wolf4SDL so the panel and board configuration can be verified before game
assets or ported source are introduced.

```bash
cmake -S src -B build
cmake --build build
picosdl/picodev.sh flash build/picowolf-bringup.elf
```

The port assessment and implementation order are in [PLAN.md](PLAN.md).
Original Wolfenstein 3D assets are user-supplied and must not be committed.

