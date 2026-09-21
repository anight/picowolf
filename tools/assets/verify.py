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

    # A PC speaker sound, an AdLib sound and two music chunks: audiosegs[] is
    # not a copy of audiot, it is what CAL_SetupAudioFile() reshapes it into,
    # and each of those three classes is reshaped differently.
    audiospans = (generated / "wolf_assets.c").read_text()
    audiospans = audiospans.split("const wolfspan_t wolf_audiospans[] = {")[1].split("};")[0]
    audiospans = [(int(a), int(b)) for a, b in
                  re.findall(r"\{\s*(-?\d+),\s*(\d+)\s*\}", audiospans)]
    nsounds = (len(audiospans) - 27) // 3
    audiowanted = []
    for label, chunk in (("audio pc", 0),
                         ("audio pc last", nsounds - 1),
                         ("audio adlib", nsounds + 3),
                         ("audio music", 3 * nsounds),
                         ("audio music last", len(audiospans) - 1)):
        off, length = audiospans[chunk]
        if off < 0 or not length:
            continue
        audiowanted.append((label, chunk, off, length))
        dumps.append("dump binary memory %s/audio_%d.bin audiosegs[%d] audiosegs[%d]+%d"
                     % (work, chunk, chunk, chunk, length))

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
        # The whole page file and the whole pointer table.  Sampling three
        # pages was not enough: the game measures a page as the gap to the
        # next one, so a layout that differs only in padding gives every
        # sprite the wrong size while any single page still compares equal.
        "dump binary memory %s/pagedata.bin PMPages[0] PMPages[ChunksInFile]" % work,
        "dump binary memory %s/pagetable.bin PMPages PMPages+ChunksInFile+1" % work,
        "printf \"PMSOUNDINFOPAGEPADDED %d\\n\", PMSoundInfoPagePadded",
        "printf \"CHUNKSINFILE %d\\n\", ChunksInFile",
        "quit",
    ])
    (work / "dump.cmd").write_text(script)

    run = subprocess.run(
        ["timeout", "180", "gdb", "-batch", "-nx", "-x", str(work / "dump.cmd"),
         "--args", "./wolf4sdl", "--windowed", "--nowait", "--joystick", "-1",
         "--tedlevel", "0", "--configdir", str(work)],
        cwd=GAME, capture_output=True, text=True,
        env={"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
             "HOME": str(work), "PATH": "/usr/bin:/bin"})
    gdbout = run.stdout

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

    body = (generated / "wolf_assets.c").read_text()
    body = body.split("const int32_t wolf_pageoffsets[] = {")[1].split("};")[0]
    pageoffsets = [int(x) for x in re.findall(r"(-?\d+),", body)]
    pages = (generated / "blobs" / "vswap.bin").read_bytes()

    dump = work / "pagedata.bin"
    if dump.exists():
        theirs = dump.read_bytes()
        checked += 1
        if pages == theirs:
            print("  %-16s %7d bytes  ok" % ("whole page file", len(theirs)))
        else:
            bad = sum(1 for a, b in zip(pages, theirs) if a != b)
            print("  %-16s %7d bytes  DIFFERS in %d (lengths %d/%d)"
                  % ("whole page file", len(theirs), bad, len(pages), len(theirs)))
            fails += 1
    else:
        print("  %-16s          no dump" % "whole page file")
        fails += 1

    dump = work / "pagetable.bin"
    if dump.exists():
        raw = dump.read_bytes()
        width = 8 if len(raw) // (len(pageoffsets)) == 8 else 4
        fmt = "<%d%s" % (len(raw) // width, "Q" if width == 8 else "I")
        ptrs = struct.unpack(fmt, raw)
        theirs = [p - ptrs[0] for p in ptrs]
        checked += 1
        if theirs == pageoffsets:
            print("  %-16s %7d pages  ok" % ("page table", len(theirs) - 1))
        else:
            bad = sum(1 for a, b in zip(theirs, pageoffsets) if a != b)
            first = next((n for n, (a, b) in enumerate(zip(theirs, pageoffsets))
                          if a != b), None)
            print("  %-16s %7d pages  DIFFERS in %d, first at page %s"
                  % ("page table", len(theirs) - 1, bad, first))
            fails += 1
    else:
        print("  %-16s          no dump" % "page table")
        fails += 1

    audioblob = (generated / "blobs" / "audiot.bin").read_bytes()
    for label, chunk, off, length in audiowanted:
        dump = work / ("audio_%d.bin" % chunk)
        if not dump.exists():
            print("  %-16s %7d bytes  no dump" % (label, length))
            fails += 1
            continue
        mine, theirs = audioblob[off:off + length], dump.read_bytes()
        checked += 1
        if mine == theirs:
            print("  %-16s %7d bytes  ok" % (label, length))
        else:
            bad = sum(1 for a, b in zip(mine, theirs) if a != b)
            print("  %-16s %7d bytes  DIFFERS in %d" % (label, length, bad))
            fails += 1

    m = re.search(r"PMSOUNDINFOPAGEPADDED (\d+)", gdbout)
    want = "#define WOLF_SOUNDINFOPAGEPADDED 1" in (generated / "wolf_assets.h").read_text()
    if m:
        checked += 1
        if (m.group(1) == "1") == want:
            print("  %-16s          ok (%s)" % ("sound info pad", m.group(1)))
        else:
            print("  %-16s          DIFFERS (game %s, generated %d)"
                  % ("sound info pad", m.group(1), 1 if want else 0))
            fails += 1

    print()
    if not checked:
        sys.exit("nothing was checked - the game never reached the breakpoint")
    print("%d whole-blob checks, %d failed" % (whole, wfails))
    print("%d cross-checks against the game, %d failed" % (checked, fails))
    sys.exit(1 if (fails or wfails) else 0)


if __name__ == "__main__":
    main()
