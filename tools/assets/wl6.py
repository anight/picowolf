"""
A reader for the Wolfenstein 3D v1.4 GoodTimes data set.

Everything here is a transcription of Wolf4SDL's own loaders - CAL_HuffExpand,
CAL_CarmackExpand and CA_RLEWexpand in id_ca.c, and PM_Startup in id_pm.c - so
that the converter and the game agree on what the files contain.  Nothing here
knows about the Pico; it reads the files and hands back bytes.

The chunk numbering comes from Wolf4SDL/gfxv_wl6.h rather than being repeated
here, because it is version-specific and getting it wrong is silent.
"""

import re
import struct
from pathlib import Path

CARMACK_NEAR = 0xA7
CARMACK_FAR = 0xA8

DIGI_RATE = 7042          # what VSWAP's digitised sounds were sampled at
MAP_AREA = 64 * 64        # tiles per map plane


# ----------------------------------------------------------------- enums ---

def read_enum(header, name):
    """
    Values for one C enum in a header, by name.  The graphics chunk numbering
    is a plain ascending enum with a few `X = Y` aliases, which is exactly what
    this handles and no more.
    """
    text = Path(header).read_text()
    m = re.search(r"enum\s+%s\s*\{(.*?)\}" % re.escape(name), text, re.S)
    if not m:
        raise KeyError("no enum %s in %s" % (name, header))

    values, nxt = {}, 0
    body = re.sub(r"//.*?$|/\*.*?\*/", "", m.group(1), flags=re.S | re.M)

    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            lhs, rhs = (s.strip() for s in item.split("=", 1))
            nxt = values[rhs] if rhs in values else int(rhs, 0)
            values[lhs] = nxt
        else:
            values[item] = nxt
        nxt += 1

    return values


# -------------------------------------------------------------- huffman ---

def huff_expand(src, length, dictionary):
    """
    CAL_HuffExpand.  `dictionary` is 255 {bit0, bit1} pairs; node 254 is the
    head; bits come out of each byte least significant first.
    """
    out = bytearray(length)
    head = 254
    node = head
    pos = 0
    val = src[0]
    mask = 1
    i = 1

    while pos < length:
        nodeval = dictionary[node][1] if (val & mask) else dictionary[node][0]

        if mask == 0x80:
            val = src[i] if i < len(src) else 0
            i += 1
            mask = 1
        else:
            mask <<= 1

        if nodeval < 256:
            out[pos] = nodeval
            pos += 1
            node = head
        else:
            node = nodeval - 256

    return bytes(out)


# --------------------------------------------------------------- carmack ---

def carmack_expand(src, length):
    """CAL_CarmackExpand.  `length` is the expanded length in bytes."""
    words = length // 2
    out = []
    i = 0

    while words > 0:
        ch = src[i] | (src[i + 1] << 8)
        i += 2
        high = ch >> 8

        if high in (CARMACK_NEAR, CARMACK_FAR):
            count = ch & 0xFF
            if not count:
                # A word that happens to hold the tag byte, escaped.
                out.append((ch & 0xFF00) | src[i])
                i += 1
                words -= 1
                continue

            if high == CARMACK_NEAR:
                offset = src[i]
                i += 1
                start = len(out) - offset
            else:
                offset = src[i] | (src[i + 1] << 8)
                i += 2
                start = offset

            words -= count
            if words < 0:
                break
            for n in range(count):
                out.append(out[start + n])
        else:
            out.append(ch)
            words -= 1

    return out


def rlew_expand(words, count, tag):
    """CA_RLEWexpand.  `count` is the expanded length in words."""
    out = []
    i = 0
    while len(out) < count:
        value = words[i]
        i += 1
        if value != tag:
            out.append(value)
        else:
            run = words[i]
            value = words[i + 1]
            i += 2
            out.extend([value] * run)
    return out[:count]


# ------------------------------------------------------------ the files ---

class DataSet:
    """One .wl6 data set, opened and parsed."""

    def __init__(self, directory, gfxheader):
        self.dir = Path(directory)
        self.gfx = read_enum(gfxheader, "graphicnums")
        self._read_graphics()
        self._read_maps()
        self._read_audio()
        self._read_vswap()

    def _path(self, name):
        p = self.dir / (name + ".wl6")
        if not p.exists():
            raise SystemExit("missing data file: %s" % p)
        return p

    # -- vgadict / vgahead / vgagraph --
    def _read_graphics(self):
        raw = self._path("vgadict").read_bytes()
        self.grdict = [struct.unpack_from("<HH", raw, n * 4) for n in range(255)]

        head = self._path("vgahead").read_bytes()
        self.grstarts = []
        for n in range(0, len(head), 3):
            off = head[n] | (head[n + 1] << 8) | (head[n + 2] << 16)
            self.grstarts.append(-1 if off == 0x00FFFFFF else off)

        self.numchunks = len(self.grstarts) - 1
        graph = self._path("vgagraph").read_bytes()

        # STRUCTPIC holds the pic dimension table, which every pic chunk needs
        # before it can be sized.
        self.grchunks = {}
        for chunk in range(self.numchunks):
            pos = self.grstarts[chunk]
            if pos < 0:
                continue
            nxt = chunk + 1
            while nxt < len(self.grstarts) and self.grstarts[nxt] == -1:
                nxt += 1
            src = graph[pos:self.grstarts[nxt]]

            start_tile8 = self.gfx["STARTTILE8"]
            start_ext = self.gfx["STARTEXTERNS"]

            if start_tile8 <= chunk < start_ext:
                expanded = 64 * 35          # NUMTILE8, all in one chunk
                body = src
            else:
                expanded = struct.unpack_from("<i", src)[0]
                body = src[4:]

            self.grchunks[chunk] = huff_expand(body, expanded, self.grdict)

        start_pics = self.gfx["STARTPICS"]
        numpics = self.gfx["STARTTILE8"] - start_pics
        table = self.grchunks[self.gfx["STRUCTPIC"]]
        self.pictable = [struct.unpack_from("<hh", table, n * 4) for n in range(numpics)]

    # -- maphead / gamemaps --
    def _read_maps(self):
        head = self._path("maphead").read_bytes()
        self.rlewtag = struct.unpack_from("<H", head)[0]
        offsets = [struct.unpack_from("<i", head, 2 + n * 4)[0]
                   for n in range((len(head) - 2) // 4)]

        maps = self._path("gamemaps").read_bytes()
        self.levels = []

        for off in offsets:
            if off <= 0:
                continue
            planestart = struct.unpack_from("<3i", maps, off)
            planelen = struct.unpack_from("<3H", maps, off + 12)
            width, height = struct.unpack_from("<HH", maps, off + 18)
            name = maps[off + 22:off + 38].split(b"\0")[0].decode("latin-1")

            planes, raw = [], []
            for n in range(3):
                src = maps[planestart[n]:planestart[n] + planelen[n]]
                raw.append(src)
                expanded = struct.unpack_from("<H", src)[0]
                inter = carmack_expand(src[2:], expanded)
                planes.append(rlew_expand(inter[1:], width * height, self.rlewtag))

            self.levels.append({
                "name": name, "width": width, "height": height,
                # `planes` is decoded, for checking against the game; `raw_planes`
                # is what ships, still Carmack+RLEW as the file holds it.
                "planes": planes, "raw_planes": raw,
                "compressed": sum(planelen),
            })

    # -- audiohed / audiot --
    def _read_audio(self):
        head = self._path("audiohed").read_bytes()
        offs = list(struct.unpack("<%dI" % (len(head) // 4), head))
        data = self._path("audiot").read_bytes()
        self.audio = [data[offs[n]:offs[n + 1]] for n in range(len(offs) - 1)]

    # -- vswap --
    def _read_vswap(self):
        raw = self._path("vswap").read_bytes()
        chunks, spritestart, soundstart = struct.unpack_from("<HHH", raw)
        offsets = list(struct.unpack_from("<%dI" % chunks, raw, 6))
        lengths = list(struct.unpack_from("<%dH" % chunks, raw, 6 + chunks * 4))

        self.vswap = {
            "chunks": chunks,
            "spritestart": spritestart,
            "soundstart": soundstart,
            "offsets": offsets,
            "lengths": lengths,
            "raw": raw,
            "pagesize": sum(l for l in lengths),
        }
