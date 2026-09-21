#!/usr/bin/env python3
"""
What is in the converted data, by class and by item.

The flash budget is the thing that decides whether a board can run this, and
2,415,963 bytes of it is game data.  A Pico 2 W has room; a 2 MB RP2040 board
does not, so something has to go.  This says what there is to give up and what
each thing is worth, rather than leaving it to be guessed at.

    tools/assets/inventory.py [--detail]
"""

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wl6

ROOT = Path(__file__).resolve().parent.parent.parent
GAME = ROOT / "Wolf4SDL"


def bar(n, total, width=28):
    filled = int(round(width * n / total)) if total else 0
    return "#" * filled + "." * (width - filled)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true", help="every item, not just classes")
    args = ap.parse_args()

    d = wl6.DataSet(GAME, GAME / "gfxv_wl6.h")
    g = d.gfx
    music = wl6.read_enum(GAME / "audiowl6.h", "musicnames")
    v = d.vswap

    rows = []

    # ---- VSWAP, by page class ----
    def pagebytes(a, b):
        return sum(v["lengths"][i] for i in range(a, b) if v["offsets"][i])

    walls = pagebytes(0, v["spritestart"])
    sprites = pagebytes(v["spritestart"], v["soundstart"])
    sounds = pagebytes(v["soundstart"], v["chunks"] - 1)
    soundinfo = v["lengths"][v["chunks"] - 1]

    rows += [
        ("VSWAP", "wall textures", walls, v["spritestart"], "no"),
        ("VSWAP", "sprites", sprites, v["soundstart"] - v["spritestart"], "no"),
        ("VSWAP", "digitised sounds", sounds, v["chunks"] - 1 - v["soundstart"],
         "yes - AdLib sounds cover the same effects"),
        ("VSWAP", "sound directory", soundinfo, 1, "no"),
    ]

    # ---- VGAGRAPH, by chunk class ----
    def grbytes(a, b):
        return sum(len(d.grchunks[c]) for c in range(a, b) if c in d.grchunks)

    rows += [
        ("VGAGRAPH", "pic dimension table", grbytes(g["STRUCTPIC"], g["STARTFONT"]), 1, "no"),
        ("VGAGRAPH", "fonts", grbytes(g["STARTFONT"], g["STARTPICS"]),
         g["STARTPICS"] - g["STARTFONT"], "no"),
        ("VGAGRAPH", "pics (menus, HUD, title, art)",
         grbytes(g["STARTPICS"], g["STARTTILE8"]), g["STARTTILE8"] - g["STARTPICS"],
         "some - see --detail"),
        ("VGAGRAPH", "tile8 (menu glyphs)", grbytes(g["STARTTILE8"], g["STARTEXTERNS"]), 1, "no"),
        ("VGAGRAPH", "order/error screens",
         grbytes(g["STARTEXTERNS"], g["STARTHELPTEXT"]),
         g["STARTHELPTEXT"] - g["STARTEXTERNS"], "yes - shareware nag screens"),
        ("VGAGRAPH", "help text", grbytes(g["STARTHELPTEXT"], g["STARTDEMOS"]),
         g["STARTDEMOS"] - g["STARTHELPTEXT"], "yes"),
        ("VGAGRAPH", "demos", grbytes(g["STARTDEMOS"], g["STARTENDTEXT"]),
         g["STARTENDTEXT"] - g["STARTDEMOS"], "yes - the title loop plays them"),
        ("VGAGRAPH", "end text", grbytes(g["STARTENDTEXT"], d.numchunks),
         d.numchunks - g["STARTENDTEXT"], "yes"),
    ]

    # ---- AUDIOT ----
    starts, raw = d.audiostarts, d.audioraw
    a = d.audio_start
    pc = sum(starts[i + 1] - starts[i] for i in range(a["pc"], a["adlib"]))
    adlib = sum(starts[i + 1] - starts[i] for i in range(a["adlib"], a["digi"]))
    mus = sum(starts[i + 1] - starts[i] for i in range(a["music"], len(starts) - 1))

    rows += [
        ("AUDIOT", "PC speaker sounds", pc, a["adlib"] - a["pc"], "yes - if AdLib is the only mode"),
        ("AUDIOT", "AdLib sounds", adlib, a["digi"] - a["adlib"], "no"),
        ("AUDIOT", "IMF music", mus, len(starts) - 1 - a["music"], "some - see --detail"),
    ]

    # ---- GAMEMAPS, by episode ----
    for ep in range(6):
        lv = d.levels[ep * 10:(ep + 1) * 10]
        if not lv:
            continue
        rows.append(("GAMEMAPS", "episode %d (%d levels)" % (ep + 1, len(lv)),
                     sum(l["compressed"] for l in lv), len(lv),
                     "no" if ep == 0 else "yes - episodes are independent"))

    total = sum(r[2] for r in rows)

    print("Converted game data, %d bytes\n" % total)
    print("%-9s %-32s %9s %5s %-30s %s"
          % ("file", "what", "bytes", "n", "", "strippable"))
    print("-" * 118)
    lastfile = None
    for f, what, n, count, strip in sorted(rows, key=lambda r: -r[2]):
        print("%-9s %-32s %9d %5d %-30s %s"
              % (f if f != lastfile else "", what, n, count, bar(n, total), strip))
        lastfile = f
    print("-" * 118)
    print("%-9s %-32s %9d" % ("", "total", total))

    if not args.detail:
        return

    print("\n\nIMF music, by tune")
    print("-" * 48)
    names = {v_: k for k, v_ in music.items() if k != "LASTMUSIC"}
    tunes = []
    for i in range(a["music"], len(starts) - 1):
        tunes.append((starts[i + 1] - starts[i], names.get(i - a["music"], "?")))
    for n, name in sorted(tunes, reverse=True):
        print("  %7d  %s" % (n, name.replace("_MUS", "").lower()))
    print("  %7d  total over %d tunes" % (sum(t[0] for t in tunes), len(tunes)))

    print("\n\nLargest pics")
    print("-" * 48)
    picnames = {v_: k for k, v_ in g.items()}
    pics = [(len(d.grchunks[c]), picnames.get(c, "chunk %d" % c))
            for c in range(g["STARTPICS"], g["STARTTILE8"]) if c in d.grchunks]
    for n, name in sorted(pics, reverse=True)[:20]:
        print("  %7d  %s" % (n, name))
    print("  %7d  total over %d pics" % (sum(p[0] for p in pics), len(pics)))


if __name__ == "__main__":
    main()
