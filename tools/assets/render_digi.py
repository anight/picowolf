#!/usr/bin/env python3
"""
Render every digitised sound through the port's own mixer, one WAV each.

The names come from wolfdigimap[] in wl_main.c, read with the preprocessor
honoured.  That matters: the array holds a Wolfenstein table and a Spear of
Destiny table in the same declaration, and the same index means different
sounds in each - index 15 is PUSHWALLSND in one and AHHHGSND in the other - so
a regex over the whole body silently takes whichever came last.

Each sound is rendered by tools/host/digi_render, which includes sd_mixer.h and
calls the same SD_ResampleStep/SD_ResampleSample/SD_MixSample the board runs,
so these are the firmware's samples rather than an approximation of them.

    tools/assets/render_digi.py [--out DIR] [--rate 22050]
"""

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wl6

ROOT = Path(__file__).resolve().parent.parent.parent
GAME = ROOT / "Wolf4SDL"
RENDER = ROOT / "tools" / "host" / "digi_render"


def digi_names(defines=frozenset()):
    """digi index -> sound name, from wolfdigimap with #if honoured."""
    text = (GAME / "wl_main.c").read_text()
    body = text[text.index("wolfdigimap[]"):]
    body = body[: body.index("LASTSOUND")]
    body = re.sub(r"//.*", "", body)

    def truth(expr):
        expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)",
                      lambda m: "True" if m.group(1) in defines else "False", expr)
        expr = expr.replace("!", " not ").replace("&&", " and ").replace("||", " or ")
        return eval(expr)

    out, stack = {}, []
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("#"):
            d = s[1:].strip()
            if d.startswith("ifdef"):    stack.append(d.split()[1] in defines)
            elif d.startswith("ifndef"): stack.append(d.split()[1] not in defines)
            elif d.startswith("if"):     stack.append(truth(d[2:]))
            elif d.startswith("else"):   stack[-1] = not stack[-1]
            elif d.startswith("endif"):  stack.pop()
            continue
        if not all(stack):
            continue
        m = re.match(r"(\w+SND)\s*,\s*(\d+)\s*,\s*(-?\d+)", s)
        if m:
            out[int(m.group(2))] = m.group(1)
    return out


def digi_table(data):
    """Every digitised sound's start page and length, as SDL_SetupDigi() finds them."""
    v = data.vswap
    chunks, soundstart = v["chunks"], v["soundstart"]
    offsets, lengths, raw = v["offsets"], v["lengths"], v["raw"]

    info_off, info_len = offsets[chunks - 1], lengths[chunks - 1]
    info = struct.unpack_from("<%dH" % (info_len // 2), raw, info_off)

    out = []
    for i in range(info_len // 4):
        start, dirlen = info[i * 2], info[i * 2 + 1]
        if start >= chunks - 1:
            break
        out.append((i, offsets[soundstart + start], dirlen))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "captures" / "digi" / "all"))
    ap.add_argument("--rate", type=int, default=22050)
    args = ap.parse_args()

    if not RENDER.exists():
        sys.exit("build it first: make -C tools/host digi_render")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    data = wl6.DataSet(GAME, GAME / "gfxv_wl6.h")
    names = digi_names()
    table = digi_table(data)
    raw = data.vswap["raw"]

    print("%3s %-22s %8s %8s  %s" % ("idx", "name", "bytes", "seconds", "file"))
    for idx, off, length in table:
        name = names.get(idx, "unmapped")
        stem = "%02d_%s" % (idx, name.lower().replace("snd", ""))
        rawpath = outdir / (stem + ".raw")
        wavpath = outdir / (stem + ".wav")
        rawpath.write_bytes(raw[off:off + length])
        subprocess.run([str(RENDER), str(rawpath), str(wavpath),
                        str(args.rate), "0", "0"],
                       check=True, stderr=subprocess.DEVNULL)
        rawpath.unlink()
        print("%3d %-22s %8d %8.3f  %s" % (idx, name, length, length / 7042.0,
                                           wavpath.name))

    print("\n%d sounds -> %s" % (len(table), outdir))


if __name__ == "__main__":
    main()
