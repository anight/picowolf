#!/usr/bin/env python3
"""
Does the converted data match what the game's own decoders produce?

convert.py reimplements CAL_HuffExpand, CAL_CarmackExpand, CA_RLEWexpand and
VW_DePlaneVGA in Python.  Four reimplementations is four chances to be subtly
wrong in a way that shows up as one corrupt sprite and nothing else, so this
checks them against the originals rather than against themselves: it runs the
desktop game under gdb, dumps chunks out of its live grsegs and mapsegs, and
compares those bytes against the generated blobs.

    tools/assets/verify.py

The chunks are chosen to cover every path through the converter - fonts and
text come out of the Huffman decoder untouched, pics go through deplane(), and
tile8 goes through it thirty-five times inside one chunk.
"""

import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GAME = ROOT / "Wolf4SDL"

sys.path.insert(0, str(HERE))
import convert                                                   # noqa: E402
import wl6                                                       # noqa: E402

SAMPLE = ["FONT1", "FONT2", "STARTTILE8", "ORDERSCREEN", "T_ENDART1",
          "H_BJPIC", "C_CURSOR1PIC", "STATUSBARPIC", "TITLEPIC", "GETPSYCHEDPIC"]


def gr_spans(generated):
    body = (generated / "wolf_assets.c").read_text()
    body = body.split("const wolfspan_t wolf_grspans[] = {")[1].split("};")[0]
    return [(int(a), int(b)) for a, b in re.findall(r"\{\s*(-?\d+),\s*(\d+)\s*\}", body)]


def main():
    generated = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "generated"

    if not (generated / "blobs" / "vgagraph.bin").exists():
        sys.exit("verify: no converted resources in %s - run convert.py first" % generated)

    subprocess.run(["make", "-C", str(GAME), "-s"], check=True)

    gfx = wl6.read_enum(str(GAME / "gfxv_wl6.h"), "graphicnums")
    spans = gr_spans(generated)

    work = Path(tempfile.mkdtemp())
    wanted = []
    dumps = []

    for name in SAMPLE:
        if name not in gfx:
            continue
        chunk = gfx[name]
        off, length = spans[chunk]
        if off < 0 or not length:
            continue
        wanted.append((name, off, length))
        dumps.append("dump binary memory %s/game_%s.bin grsegs[%d] grsegs[%d]+%d"
                     % (work, name, chunk, chunk, length))

    # wl_game.c:657 is the line after CA_CacheMap() in SetupGameLevel, which is
    # the only moment mapsegs holds the file's contents: the lines below it
    # rewrite plane 0 as it spawns the level's objects.
    script = "\n".join([
        "set pagination off",
        "set confirm off",
        "break wl_game.c:657",
        "run",
        *dumps,
        "dump binary memory %s/map_p0.bin mapsegs[0] mapsegs[0]+8192" % work,
        "dump binary memory %s/map_p1.bin mapsegs[1] mapsegs[1]+8192" % work,
        "dump binary memory %s/map_p2.bin mapsegs[2] mapsegs[2]+8192" % work,
        # A wall, a sprite and a digitised sound, to check the page table the
        # renderer and the mixer index rather than just the bytes in it.
        "dump binary memory %s/page_wall.bin PMPages[0] PMPages[0]+4096" % work,
        "dump binary memory %s/page_sprite.bin PMPages[PMSpriteStart] PMPages[PMSpriteStart]+64" % work,
        "dump binary memory %s/page_sound.bin PMPages[PMSoundStart] PMPages[PMSoundStart]+4096" % work,
        "quit",
    ])
    (work / "dump.cmd").write_text(script)

    subprocess.run(
        ["timeout", "180", "gdb", "-batch", "-nx", "-x", str(work / "dump.cmd"),
         "--args", "./wolf4sdl", "--windowed", "--nowait", "--joystick", "-1",
         "--tedlevel", "0", "--configdir", str(work)],
        cwd=GAME, capture_output=True,
        env={"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
             "HOME": str(work), "PATH": "/usr/bin:/bin"})

    gr = (generated / "blobs" / "vgagraph.bin").read_bytes()
    checked = fails = 0

    # ---------------------------------------------------------------
    # First, that what is on disk is what the converter produces.  The
    # cross-check below samples ten chunks out of a hundred and forty-nine, so
    # on its own it would miss a blob truncated or corrupted anywhere else.
    # ---------------------------------------------------------------
    print("generated blobs against a fresh conversion\n")

    fresh = wl6.DataSet(str(GAME), str(GAME / "gfxv_wl6.h"))
    blobs, _ = convert.build(fresh, generated)
    whole = wfails = 0

    for name in sorted(blobs):
        onfile = (generated / "blobs" / (name + ".bin")).read_bytes()
        whole += 1
        if onfile == blobs[name]:
            print("  %-16s %7d bytes  ok" % (name, len(onfile)))
        else:
            bad = sum(1 for a, b in zip(onfile, blobs[name]) if a != b)
            print("  %-16s %7d bytes  DIFFERS in %d (lengths %d/%d)"
                  % (name, len(onfile), bad, len(onfile), len(blobs[name])))
            wfails += 1

    print()
    print("converted resources against the game's own decoders\n")

    for name, off, length in wanted:
        dump = work / ("game_%s.bin" % name)
        if not dump.exists():
            print("  %-16s %7d bytes  no dump" % (name, length))
            fails += 1
            continue
        mine, theirs = gr[off:off + length], dump.read_bytes()
        checked += 1
        if mine == theirs:
            print("  %-16s %7d bytes  ok" % (name, length))
        else:
            bad = sum(1 for a, b in zip(mine, theirs) if a != b)
            print("  %-16s %7d bytes  DIFFERS in %d" % (name, length, bad))
            fails += 1

    data = fresh
    lvl = data.levels[0]

    #
    # Decoded out of the shipped blob rather than out of the file again, so a
    # map span written with the wrong offset or length is a failure here.
    #
    mapblob = (generated / "blobs" / "gamemaps.bin").read_bytes()
    mapspans = (generated / "wolf_assets.c").read_text()
    mapspans = mapspans.split("const wolflevel_t wolf_levels[] = {")[1].split("};")[0]
    first = re.search(r"\{\s*\"[^\"]*\",\s*(\d+),\s*(\d+),\s*\{(.*?)\}\s*\},",
                      mapspans, re.S)
    width, height = int(first.group(1)), int(first.group(2))
    planespans = [(int(a), int(b)) for a, b in
                  re.findall(r"\{\s*(\d+),\s*(\d+)\s*\}", first.group(3))]

    for n in range(3):
        dump = work / ("map_p%d.bin" % n)
        if not dump.exists():
            print("  %-16s          no dump" % ("map plane %d" % n))
            fails += 1
            continue
        off, length = planespans[n]
        src = mapblob[off:off + length]
        expanded = struct.unpack_from("<H", src)[0]
        inter = wl6.carmack_expand(src[2:], expanded)
        plane = wl6.rlew_expand(inter[1:], width * height, data.rlewtag)
        mine = struct.pack("<%dH" % len(plane), *plane)
        theirs = dump.read_bytes()[:len(mine)]
        checked += 1
        if mine == theirs:
            print("  %-16s %7d bytes  ok" % ("map plane %d" % n, len(mine)))
        else:
            print("  %-16s %7d bytes  DIFFERS" % ("map plane %d" % n, len(mine)))
            fails += 1

    pagespans = (generated / "wolf_assets.c").read_text()
    pagespans = pagespans.split("const wolfspan_t wolf_pagespans[] = {")[1].split("};")[0]
    pagespans = [(int(a), int(b)) for a, b in
                 re.findall(r"\{\s*(-?\d+),\s*(\d+)\s*\}", pagespans)]
    pages = (generated / "blobs" / "vswap.bin").read_bytes()
    v = data.vswap

    for label, index in (("vswap wall", 0),
                         ("vswap sprite", v["spritestart"]),
                         ("vswap sound", v["soundstart"])):
        dump = work / ("page_%s.bin" % label.split()[1])
        if not dump.exists():
            print("  %-16s          no dump" % label)
            fails += 1
            continue
        theirs = dump.read_bytes()
        off, length = pagespans[index]
        mine = pages[off:off + len(theirs)]
        checked += 1
        if mine == theirs:
            print("  %-16s %7d bytes  ok" % (label, len(theirs)))
        else:
            print("  %-16s %7d bytes  DIFFERS" % (label, len(theirs)))
            fails += 1

    print()
    if not checked:
        sys.exit("nothing was checked - the game never reached the breakpoint")
    print("%d whole-blob checks, %d failed" % (whole, wfails))
    print("%d cross-checks against the game, %d failed" % (checked, fails))
    sys.exit(1 if (fails or wfails) else 0)


if __name__ == "__main__":
    main()
