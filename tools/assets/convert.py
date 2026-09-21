#!/usr/bin/env python3
"""
Turn one Wolfenstein 3D v1.4 GoodTimes data set into flash-resident resources.

The board has no filesystem, so nothing can be opened at run time; and it has
520 KB of SRAM against a game that currently puts 2.3 MB of data in it, most of
that PM_Startup() copying the whole VSWAP page region.  So the data moves to
flash, and what the game used to decompress at startup is decompressed here
instead - once, at build time, where the CPU and the memory are free.

What is decided per class, and why:

  graphics  decoded and deplaned into flash.  407,678 bytes against 275,774
            compressed, so it costs 132 KB of flash to remove the Huffman
            decoder, the decode buffers and the 149 allocations from the board.
            Flash is what this project has spare.

  maps      left Carmack+RLEW compressed.  148,121 bytes against 1,474,560
            decoded, which is three times the whole SRAM and most of the flash
            budget, so this one is not close.  The board decompresses one level
            at a time into a fixed 24,576-byte buffer.

  audio     copied as it stands.  The AdLib and PC-speaker sounds and the IMF
            music are already in the form the sound manager wants.

  vswap     copied as it stands.  Walls, sprites and digitised sound are read
            straight out of it by the renderer and the mixer.

The bulk goes into .bin files included by an assembler stub rather than being
written as C arrays: 2.3 MB of data would be about 15 MB of C source, and
.incbin puts the same bytes in .rodata without a compiler having to parse them.
Only the small structured tables - the pic dimensions, the level directory, the
chunk offsets - are generated as C, because those are what the game indexes.
"""

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wl6


def deplane(pic, width, height):
    """VW_DePlaneVGA: four VGA bit planes interleaved back into linear pixels."""
    if width & 3:
        raise ValueError("width %d not divisible by 4" % width)

    out = bytearray(width * height)
    pwidth = width >> 2
    src = 0

    for plane in range(4):
        for y in range(height):
            row = y * width
            for x in range(pwidth):
                out[row + (x << 2) + plane] = pic[src]
                src += 1

    return bytes(out)


def build(data, outdir):
    """Everything the board will see, as bytes plus the tables that index it."""
    g = data.gfx
    blobs, tables = {}, {}

    # ---- graphics: decoded, and deplaned where the game would deplane ----
    start_pics, start_tile8 = g["STARTPICS"], g["STARTTILE8"]
    start_ext = g["STARTEXTERNS"]

    gr = bytearray()
    groffsets = []

    for chunk in range(data.numchunks):
        body = data.grchunks.get(chunk)
        if body is None:
            groffsets.append((-1, 0))
            continue

        if chunk == start_tile8:
            body = b"".join(deplane(body[n * 64:(n + 1) * 64], 8, 8) for n in range(35))
        elif start_pics <= chunk < start_ext:
            w, h = data.pictable[chunk - start_pics]
            body = deplane(body, w, h)

        groffsets.append((len(gr), len(body)))
        gr += body

    blobs["vgagraph"] = bytes(gr)
    tables["gr"] = groffsets

    # ---- maps: compressed, one span per plane ----
    maps = bytearray()
    mapdir = []

    for lvl in data.levels:
        planes = []
        for n in range(3):
            src = lvl["raw_planes"][n]
            planes.append((len(maps), len(src)))
            maps += src
        mapdir.append({
            "name": lvl["name"], "width": lvl["width"], "height": lvl["height"],
            "planes": planes,
        })

    blobs["gamemaps"] = bytes(maps)
    tables["maps"] = mapdir
    tables["rlewtag"] = data.rlewtag

    #
    # Audio is not a copy.  CAL_SetupAudioFile() reshapes what it reads, and
    # audiosegs[] is what the sound manager indexes, so that is what ships:
    #
    #   PC speaker sounds   taken as they are
    #   AdLib sounds        extended by the difference between the AdLibSound
    #                       struct and its data member, 23 bytes, which reads
    #                       on into whatever follows the chunk - that is the
    #                       format, not a mistake to fix here
    #   digitised sounds    skipped; their bytes live in VSWAP and audiot holds
    #                       only an unused directory
    #   music               given a four-byte little-endian length of its own
    #                       at the front, and, when the original two-byte
    #                       length is non-zero, its 88 bytes of Muse trailer
    #                       dropped
    #
    ADLIB_EXTRA = 23          # sizeof(AdLibSound) - sizeof(((AdLibSound*)0)->data)
    MUSE_TRAILER = 88

    start_adlib = data.audio_start["adlib"]
    start_digi = data.audio_start["digi"]
    start_music = data.audio_start["music"]

    raw = data.audioraw
    starts = data.audiostarts

    audio = bytearray()
    audiodir = []

    for chunk in range(len(starts) - 1):
        pos = starts[chunk]
        size = starts[chunk + 1] - pos

        if start_digi <= chunk < start_music:
            audiodir.append((-1, 0))              # never cached
            continue

        if chunk >= start_music:
            length = int.from_bytes(raw[pos:pos + 2], "little")
            if length:
                size += 2 - MUSE_TRAILER
                src = raw[pos + 2:pos + 2 + size - 4]
            else:
                size += 4
                src = raw[pos:pos + size - 4]
            body = size.to_bytes(4, "little", signed=True) + src
        else:
            if chunk >= start_adlib:
                size += ADLIB_EXTRA
            body = raw[pos:pos + size]

        audiodir.append((len(audio), len(body)))
        audio += body

    blobs["audiot"] = bytes(audio)
    tables["audio"] = audiodir

    #
    # The page layout is PM_Startup()'s, replicated rather than invented,
    # because the game measures a page as the gap to the next one:
    #
    #   PM_GetPageSize(p) == PMPages[p + 1] - PMPages[p]
    #
    # so anything that changes the spacing changes every sprite's size and the
    # sound info page's length.  Three things do:
    #
    #   - sprite pages and the sound info page are padded to a 2-byte boundary,
    #   - a sparse page (offset 0) holds no data and takes none, which makes it
    #     zero length and points it at whatever follows,
    #   - a page whose successor is sparse is measured by the length table
    #     rather than by the offset gap, because there is no next offset.
    #
    v = data.vswap
    raw = v["raw"]
    chunks = v["chunks"]
    offsets, lengths = v["offsets"], v["lengths"]

    pages = bytearray()
    pageoffsets = []
    soundinfopadded = False

    for i in range(chunks):
        if (v["spritestart"] <= i < v["soundstart"]) or i == chunks - 1:
            if len(pages) & 1:
                pages.append(0)
                if i == chunks - 1:
                    soundinfopadded = True

        pageoffsets.append(len(pages))

        if not offsets[i]:
            continue                     # sparse

        if i + 1 < chunks and not offsets[i + 1]:
            size = lengths[i]
        elif i + 1 < chunks:
            size = offsets[i + 1] - offsets[i]
        else:
            size = lengths[i]

        pages += raw[offsets[i]:offsets[i] + size]

    pageoffsets.append(len(pages))       # one past the last page

    blobs["vswap"] = bytes(pages)
    tables["pages"] = pageoffsets
    tables["soundinfopadded"] = soundinfopadded
    tables["vswap"] = v

    tables["pictable"] = data.pictable
    return blobs, tables


def emit(blobs, tables, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    blobdir = outdir / "blobs"
    blobdir.mkdir(exist_ok=True)

    for name, body in blobs.items():
        (blobdir / (name + ".bin")).write_bytes(body)

    # -- the assembler stub --
    lines = [
        "/* DO NOT EDIT.  Generated by tools/assets/convert.py. */",
        "",
        "/*",
        " * The converted data, placed in .rodata so it is read in place out of",
        " * flash and never copied to SRAM.  .incbin rather than C arrays: the",
        " * same bytes, without asking a compiler to parse 15 MB of hex.",
        " */",
        "",
    ]
    for name in sorted(blobs):
        lines += [
            "    .section .rodata.wolf_%s, \"a\"" % name,
            "    .balign 4",
            "    .global wolf_%s" % name,
            "wolf_%s:" % name,
            "    .incbin \"blobs/%s.bin\"" % name,
            "    .global wolf_%s_end" % name,
            "wolf_%s_end:" % name,
            "",
        ]
    (outdir / "wolf_blobs.S").write_text("\n".join(lines))

    # -- the tables the game indexes --
    gr = tables["gr"]
    pics = tables["pictable"]
    maps = tables["maps"]
    audio = tables["audio"]
    pages = tables["pages"]
    v = tables["vswap"]
    numpages = len(pages) - 1

    h = ["/* DO NOT EDIT.  Generated by tools/assets/convert.py. */", "",
         "#ifndef __WOLF_ASSETS_H_", "#define __WOLF_ASSETS_H_", "",
         "#include <stdint.h>", "",
         "typedef struct { int32_t offset; int32_t length; } wolfspan_t;",
         "",
         "typedef struct {",
         "    const char *name;",
         "    int16_t     width,height;",
         "    wolfspan_t  planes[3];",
         "} wolflevel_t;", "",
         "typedef struct { int16_t width,height; } wolfpic_t;", "",
         ]
    for name in sorted(blobs):
        h += ["extern const uint8_t wolf_%s[];" % name,
              "extern const uint8_t wolf_%s_end[];" % name]
    h += ["",
          "#define WOLF_NUMCHUNKS   %d" % len(gr),
          "#define WOLF_NUMPICS     %d" % len(pics),
          "#define WOLF_NUMLEVELS   %d" % len(maps),
          "#define WOLF_NUMAUDIO    %d" % len(audio),
          "#define WOLF_NUMPAGES    %d" % numpages,
          "#define WOLF_SOUNDINFOPAGEPADDED %d" % (1 if tables["soundinfopadded"] else 0),
          "#define WOLF_SPRITESTART %d" % v["spritestart"],
          "#define WOLF_SOUNDSTART  %d" % v["soundstart"],
          "#define WOLF_RLEWTAG     0x%04x" % tables["rlewtag"],
          "",
          "extern const wolfspan_t  wolf_grspans[WOLF_NUMCHUNKS];",
          "extern const wolfpic_t   wolf_pictable[WOLF_NUMPICS];",
          "extern const wolflevel_t wolf_levels[WOLF_NUMLEVELS];",
          "extern const wolfspan_t  wolf_audiospans[WOLF_NUMAUDIO];",
          "/* One offset per page plus one past the last, so that a page's size is",
          " * the gap to the next - which is how PM_GetPageSize() measures it. */",
          "extern const int32_t     wolf_pageoffsets[WOLF_NUMPAGES + 1];",
          "", "#endif", ""]
    (outdir / "wolf_assets.h").write_text("\n".join(h))

    def spans(name, items):
        out = ["const wolfspan_t %s[] = {" % name]
        for off, length in items:
            out.append("    { %8d, %7d }," % (off, length))
        out += ["};", ""]
        return out

    c = ["/* DO NOT EDIT.  Generated by tools/assets/convert.py. */", "",
         '#include "wolf_assets.h"', ""]
    c += spans("wolf_grspans", gr)
    c += spans("wolf_audiospans", audio)
    c += ["const int32_t wolf_pageoffsets[] = {"]
    for n in range(0, len(pages), 8):
        c.append("    " + " ".join("%8d," % o for o in pages[n:n + 8]))
    c += ["};", ""]
    c += ["const wolfpic_t wolf_pictable[] = {"]
    for w, hh in pics:
        c.append("    { %4d, %4d }," % (w, hh))
    c += ["};", "", "const wolflevel_t wolf_levels[] = {"]
    for lvl in maps:
        p = ", ".join("{ %d, %d }" % (o, l) for o, l in lvl["planes"])
        c.append('    { "%s", %d, %d, { %s } },' % (lvl["name"], lvl["width"], lvl["height"], p))
    c += ["};", ""]
    (outdir / "wolf_assets.c").write_text("\n".join(c))

    return blobdir


def report(blobs, tables, data, outdir, firmware):
    src = {
        "vgagraph": ("vgagraph + vgahead + vgadict", "decoded and deplaned"),
        "gamemaps": ("gamemaps + maphead", "kept compressed"),
        "audiot":   ("audiot + audiohed", "reshaped as audiosegs"),
        "vswap":    ("vswap", "copied"),
    }
    origin = {
        "vgagraph": sum((data.dir / (n + ".wl6")).stat().st_size
                        for n in ("vgagraph", "vgahead", "vgadict")),
        "gamemaps": sum((data.dir / (n + ".wl6")).stat().st_size
                        for n in ("gamemaps", "maphead")),
        "audiot":   sum((data.dir / (n + ".wl6")).stat().st_size
                        for n in ("audiot", "audiohed")),
        "vswap":    (data.dir / "vswap.wl6").stat().st_size,
    }

    tabledir = outdir / "wolf_assets.c"
    tablesize = sum(len(t) * 8 for t in (tables["gr"], tables["audio"])) \
        + len(tables["pages"]) * 4 \
        + len(tables["pictable"]) * 4 + len(tables["maps"]) * 32

    lines = ["Converted resources", "==================="]
    lines.append("")
    lines.append("%-10s %12s %12s   %s" % ("class", "source", "flash", "treatment"))
    total = 0
    for name in ("vgagraph", "gamemaps", "audiot", "vswap"):
        size = len(blobs[name])
        total += size
        lines.append("%-10s %12d %12d   %s" % (name, origin[name], size, src[name][1]))
    lines.append("%-10s %12s %12d   %s" % ("tables", "-", tablesize, "generated C"))
    total += tablesize
    lines.append("%-10s %12d %12d" % ("total", sum(origin.values()), total))
    lines.append("")

    FLASH, SRAM = 4 * 1024 * 1024, 512 * 1024
    lines.append("Against a Pico 2 W")
    lines.append("------------------")
    lines.append("resources          %9d  %5.1f%% of %d flash" % (total, 100.0 * total / FLASH, FLASH))
    if firmware:
        lines.append("bring-up firmware  %9d  %5.1f%%" % (firmware, 100.0 * firmware / FLASH))
        lines.append("together           %9d  %5.1f%%  (%d free)"
                     % (total + firmware, 100.0 * (total + firmware) / FLASH,
                        FLASH - total - firmware))
    lines.append("")
    lines.append("SRAM this removes")
    lines.append("-----------------")
    pm = len(blobs["vswap"])
    gr = len(blobs["vgagraph"])
    au = len(blobs["audiot"])
    lines.append("PM_Startup page file      %9d   now read in place" % pm)
    lines.append("grsegs, all chunks cached %9d   now read in place" % gr)
    lines.append("audiosegs                 %9d   now read in place" % au)
    lines.append("%-25s %9d   %.1f%% of %d SRAM"
                 % ("total", pm + gr + au, 100.0 * (pm + gr + au) / SRAM, SRAM))
    lines.append("")
    lines.append("still needed in SRAM: one level of map planes, %d bytes"
                 % (3 * 64 * 64 * 2))

    text = "\n".join(lines) + "\n"
    (outdir / "report.txt").write_text(text)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--data", required=True, help="directory holding the .wl6 files")
    ap.add_argument("--gfxheader", required=True, help="Wolf4SDL/gfxv_wl6.h")
    ap.add_argument("--out", required=True, help="where to write the resources")
    ap.add_argument("--firmware", type=int, default=0,
                    help="firmware flash bytes, for the report")
    args = ap.parse_args()

    data = wl6.DataSet(args.data, args.gfxheader)
    blobs, tables = build(data, Path(args.out))
    emit(blobs, tables, Path(args.out))
    sys.stdout.write(report(blobs, tables, data, Path(args.out), args.firmware))


if __name__ == "__main__":
    main()
