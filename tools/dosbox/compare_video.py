#! /usr/bin/env python3
"""
Compare picowolf's frames against the original DOS game's.

Both sides are reduced to palette indices before anything is compared.  The
pixels that reach a VGA DAC are 6 bits per channel and the two paths widen them
differently - Wolf4SDL computes r*255/63, DOSBox-X has its own - so comparing
RGB would report a difference on every pixel of an identical picture.  What the
port is actually responsible for is which palette entry each pixel got, and
that is what this compares.

    tools/dosbox/compare_video.py --dos captures/dos/video.mkv \\
                                  --pw  captures/pw/frames

It samples the DOS video, maps every frame on both sides to indices, and for
each sampled DOS frame reports the picowolf frame that agrees with it best.
"""

import argparse, os, subprocess, sys, tempfile, re
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load_palette(inc=None):
    """gamepal, as id_vw.c builds it from wolfpal.inc."""
    inc = inc or os.path.join(ROOT, 'Wolf4SDL', 'wolfpal.inc')
    text = open(inc).read()
    pal = [(int(r) * 255 // 63, int(g) * 255 // 63, int(b) * 255 // 63)
           for r, g, b in re.findall(r'RGB\(\s*(\d+),\s*(\d+),\s*(\d+)\)', text)]
    if len(pal) != 256:
        sys.exit(f'{inc}: {len(pal)} colours, expected 256')
    return np.array(pal, dtype=np.int32)


def to_indices(rgb, pal):
    """Nearest palette entry per pixel, plus how far away it was.

    The distance matters: an exact match means the frame really is drawn from
    this palette, and a large one means the game had faded it, in which case
    comparing indices is meaningless and the caller should say so.
    """
    # int32, not int16: a squared channel difference reaches 255*255 = 65025,
    # which overflows int16 and turns the distances into noise.
    flat = rgb.reshape(-1, 3).astype(np.int32)
    #
    # A 320x200 indexed frame holds at most 256 distinct colours however many
    # pixels it has, so the search runs over the unique ones and the result is
    # scattered back.  Done per pixel this is 64000x256 distances a frame and
    # the comparison takes minutes; done per colour it is a few hundred.
    #
    uniq, inverse = np.unique(flat, axis=0, return_inverse=True)
    d = ((uniq[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
    nearest = d.argmin(axis=1)
    dist = np.sqrt(d[np.arange(len(uniq)), nearest])
    idx = nearest[inverse]
    return idx.reshape(rgb.shape[:2]), float(dist[inverse].mean())


def dos_frames(video, every, outdir):
    """Sample the capture, undoing DOSBox-X's integer pixel doubling."""
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-i', video,
         '-vf', f'fps=1/{every},scale=320:200:flags=neighbor',
         '-y', os.path.join(outdir, 'dos%04d.png')], check=True)
    return sorted(os.path.join(outdir, f) for f in os.listdir(outdir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dos', required=True, help='the DOS capture (video.mkv)')
    ap.add_argument('--pw', required=True, help='directory of picowolf BMP frames')
    ap.add_argument('--every', type=float, default=2.0,
                    help='sample the DOS video this many seconds apart')
    ap.add_argument('--keep', help='write the sampled DOS frames here')
    args = ap.parse_args()

    pal = load_palette()

    pw_files = sorted(os.path.join(args.pw, f) for f in os.listdir(args.pw)
                      if f.endswith('.bmp'))
    if not pw_files:
        sys.exit(f'{args.pw}: no frames')
    pw = []
    for f in pw_files:
        idx, dist = to_indices(np.array(Image.open(f).convert('RGB')), pal)
        pw.append((os.path.basename(f), idx, dist))
    print(f'picowolf: {len(pw)} frames')

    tmp = args.keep or tempfile.mkdtemp()
    os.makedirs(tmp, exist_ok=True)
    dos = dos_frames(args.dos, args.every, tmp)
    print(f'DOS: {len(dos)} frames sampled every {args.every}s\n')

    print(f'{"DOS frame":<14}{"palette fit":>12}   best picowolf match')
    print('-' * 64)
    for f in dos:
        didx, ddist = to_indices(np.array(Image.open(f).convert('RGB')), pal)
        best, bestpct = None, -1.0
        for name, pidx, _ in pw:
            pct = float((didx == pidx).mean()) * 100.0
            if pct > bestpct:
                best, bestpct = name, pct
        fit = 'exact' if ddist < 0.5 else f'{ddist:.1f} off'
        print(f'{os.path.basename(f):<14}{fit:>12}   {best}  {bestpct:6.2f}%')


if __name__ == '__main__':
    main()
