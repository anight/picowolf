#!/usr/bin/env python3
"""
What is inside wolf_vswap, item by item.

VSWAP is 1,540,280 of the 2,415,963 bytes of converted data - two thirds of
it, and the first place to look when the flash budget shrinks.  It holds three
things and they are independent of each other:

    wall textures   one 64x64 page each, paired light and dark
    sprites         one page each, run-length encoded columns
    digitised sound one or more pages each, 8-bit at 7042 Hz

The names come from the game's own headers, so this says which sprite and
which sound rather than which page number.

    tools/assets/vswap_inventory.py [--sprites] [--sounds] [--walls]
"""

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wl6

ROOT = Path(__file__).resolve().parent.parent.parent
GAME = ROOT / "Wolf4SDL"

# The version this data set is: version.h defines GOODTIMES and CARMACIZED and
# nothing else, so these are the conditionals to resolve in the sprite enum.
DEFINED = {"GOODTIMES", "CARMACIZED"}


def sprite_names(header):
    """
    The sprite enum is anonymous, so read_enum cannot find it by name, and it
    is full of version conditionals.  This walks it with just enough
    preprocessor to resolve the four that appear.
    """
    text = Path(header).read_text()
    body = text[text.index("// sprite constants"):]
    body = body[body.index("enum") : body.index("\n};")]

    names, keep, stack = [], True, []
    for line in body.splitlines():
        s = line.strip()
        m = re.match(r"#\s*(ifdef|ifndef|elif|else|endif)\s*(.*)", s)
        if m:
            kind, rest = m.group(1), m.group(2)
            if kind == "ifdef":
                stack.append(keep); keep = keep and (rest.strip() in DEFINED)
            elif kind == "ifndef":
                stack.append(keep); keep = keep and (rest.strip() not in DEFINED)
            elif kind == "elif":
                syms = re.findall(r"defined\((\w+)\)", rest)
                keep = stack[-1] and all(x in DEFINED for x in syms) and bool(syms)
            elif kind == "else":
                keep = stack[-1] and not keep
            elif kind == "endif":
                keep = stack.pop()
            continue
        if not keep or s.startswith("//") or s.startswith("enum") or s.startswith("{"):
            continue
        s = re.sub(r"/\*.*?\*/", "", s)
        for tok in s.split(","):
            tok = tok.strip()
            if re.fullmatch(r"SPR_\w+", tok):
                names.append(tok)
    return names


def digi_names(gamefile, audiofile):
    """digi index -> sound name, out of wolfdigimap in wl_main.c."""
    sounds = wl6.read_enum(audiofile, "soundnames")
    byvalue = {v: k for k, v in sounds.items()}
    text = Path(gamefile).read_text()
    body = text[text.index("wolfdigimap[]"):]
    body = body[: body.index("LASTSOUND")]
    out = {}
    for m in re.finditer(r"(\w+SND)\s*,\s*(\d+)\s*,\s*(-?\d+)", body):
        name, idx = m.group(1), int(m.group(2))
        out[idx] = name
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--walls", action="store_true")
    ap.add_argument("--sprites", action="store_true")
    ap.add_argument("--sounds", action="store_true")
    args = ap.parse_args()
    everything = not (args.walls or args.sprites or args.sounds)

    d = wl6.DataSet(GAME, GAME / "gfxv_wl6.h")
    v = d.vswap
    lens, offs = v["lengths"], v["offsets"]
    SS, SD, N = v["spritestart"], v["soundstart"], v["chunks"]

    def span(a, b):
        return sum(lens[i] for i in range(a, b) if offs[i])

    walls, sprites, sounds = span(0, SS), span(SS, SD), span(SD, N - 1)
    info = lens[N - 1]
    total = walls + sprites + sounds + info

    print("wolf_vswap, %d bytes in %d pages\n" % (total, N))
    print("  %-22s %9s %6s  %s" % ("", "bytes", "pages", "what it is"))
    print("  " + "-" * 92)
    print("  %-22s %9d %6d  %d textures, light and dark of each, 64x64 at one byte a pixel"
          % ("wall textures", walls, SS, SS // 2))
    print("  %-22s %9d %6d  run-length encoded columns, so sizes vary"
          % ("sprites", sprites, SD - SS))
    ndigi = lens[N - 1] // 4
    print("  %-22s %9d %6d  %d sounds, 8-bit mono at 7042 Hz, 55.6 s in all"
          % ("digitised sound", sounds, N - 1 - SD, ndigi))
    print("  %-22s %9d %6d  where each digitised sound starts and how long it is"
          % ("sound directory", info, 1))
    print("  " + "-" * 92)
    print("  %-22s %9d %6d" % ("total", total, N))

    if everything or args.walls:
        print("\n\nWall textures - %d pages, %d bytes, every page 4096" % (SS, walls))
        print("  paired: page 2n is the lit face of a wall, 2n+1 the shadowed one,")
        print("  and the map's tile value picks the pair.  %d walls in all." % (SS // 2))

    if everything or args.sprites:
        names = sprite_names(GAME / "wl_def.h")
        print("\n\nSprites - %d pages, %d bytes" % (SD - SS, sprites))
        if len(names) != SD - SS:
            # The enum is verified against the game - SPR_DEMO 0, SPR_STAT_0 2,
            # SPR_GRD_S_1 50, SPR_BOSS_W1 296 - so any surplus is a page VSWAP
            # holds and the game never names.
            print("  (%d named, %d pages: %d unnamed at the end)"
                  % (len(names), SD - SS, SD - SS - len(names)))
        items = sorted(((lens[SS + i], names[i] if i < len(names) else "sprite %d" % i)
                        for i in range(SD - SS)), reverse=True)
        print("\n  largest:")
        for n, name in items[:15]:
            print("    %6d  %s" % (n, name))
        print("\n  by family:")
        fam = {}
        for n, name in items:
            key = re.sub(r"_[SWEDPA]?\d.*$", "", name.replace("SPR_", ""))
            key = re.sub(r"\d+$", "", key)
            fam.setdefault(key, [0, 0])
            fam[key][0] += n
            fam[key][1] += 1
        for key, (n, c) in sorted(fam.items(), key=lambda x: -x[1][0])[:22]:
            print("    %7d  %4d pages  %s" % (n, c, key.lower()))

    if everything or args.sounds:
        names = digi_names(GAME / "wl_main.c", GAME / "audiowl6.h")
        print("\n\nDigitised sounds - %d pages, %d bytes" % (N - 1 - SD, sounds))
        # sizes come from the directory page the same way SDL_SetupDigi reads it
        page = v["raw"][offs[N - 1]: offs[N - 1] + lens[N - 1]]
        entries = len(page) // 4
        items = []
        for i in range(entries):
            start, length = struct.unpack_from("<HH", page, i * 4)
            if start >= N - 1:
                break
            items.append((length, names.get(i, "digi %d" % i)))
        for n, name in sorted(items, reverse=True):
            print("    %6d  %5.2f s  %s" % (n, n / 7042.0, name.replace("SND", "").lower()))
        print("    %6d  %5.2f s  total over %d sounds"
              % (sum(i[0] for i in items), sum(i[0] for i in items) / 7042.0, len(items)))


if __name__ == "__main__":
    main()
