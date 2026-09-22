#! /usr/bin/env python3
"""
Compare picowolf's audio against the original DOS game's.

Both captures are 44100 Hz stereo signed 16-bit, written by SDL's disk audio
driver straight out of each mixer, so no file format or resampler sits between
the two.  They are not synchronised: each run started its own attract sequence
when it felt like it, so the first thing this does is find the offset that
lines them up, and everything after is reported at that offset.

    tools/dosbox/compare_audio.py --dos captures/dos/audio.raw \\
                                  --pw  captures/pw/audio.raw

What a good result looks like: the music is the same IMF data driving the same
DBOPL in both, so correlation should be high.  It will not be 1.0 - DOSBox-X
renders the OPL at its own rate and resamples to 44100 differently than the
port does, and the digitised sounds are resampled differently again - so this
characterises the gap rather than demanding a match.
"""

import argparse, sys
import numpy as np


def load(path, rate=44100):
    raw = np.fromfile(path, dtype='<i2')
    if raw.size % 2:
        raw = raw[:-1]
    st = raw.reshape(-1, 2).astype(np.float32) / 32768.0
    return st, st.mean(axis=1)


def describe(name, st, mono, rate):
    secs = len(mono) / rate
    peak = float(np.abs(st).max())
    rms = float(np.sqrt((mono ** 2).mean()))
    silent = float((np.abs(mono) < 1e-4).mean()) * 100
    print(f'{name:<10} {secs:7.1f}s  peak {peak:6.3f}  rms {rms:6.4f}  '
          f'silent {silent:5.1f}%')
    return secs


def best_offset(a, b, rate, max_shift_s=60.0):
    """Offset of b within a, by normalised cross-correlation of the envelope.

    Correlating the samples themselves needs the two OPL renderings to agree
    phase for phase over minutes, which they do not.  The envelope - energy per
    10 ms - only needs the same notes at the same times, which is the thing
    being checked.
    """
    hop = rate // 100
    ea = np.array([np.sqrt((a[i:i + hop] ** 2).mean() + 1e-12)
                   for i in range(0, len(a) - hop, hop)])
    eb = np.array([np.sqrt((b[i:i + hop] ** 2).mean() + 1e-12)
                   for i in range(0, len(b) - hop, hop)])
    ea = (ea - ea.mean()) / (ea.std() + 1e-12)
    eb = (eb - eb.mean()) / (eb.std() + 1e-12)
    n = int(max_shift_s * 100)
    best, bestval = 0, -2.0
    for shift in range(-min(n, len(eb)), min(n, len(ea))):
        if shift >= 0:
            x, y = ea[shift:], eb[:len(ea) - shift]
        else:
            x, y = ea[:len(eb) + shift], eb[-shift:]
        m = min(len(x), len(y))
        if m < 200:
            continue
        v = float((x[:m] * y[:m]).mean())
        if v > bestval:
            best, bestval = shift, v
    return best / 100.0, bestval


def bands(mono, rate):
    """Energy per octave band, which is what a wrong OPL would move."""
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / rate)
    out = []
    edges = [0, 125, 250, 500, 1000, 2000, 4000, 8000, 22050]
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (freqs >= lo) & (freqs < hi)
        out.append(float((spec[sel] ** 2).sum()))
    total = sum(out) or 1.0
    return [o / total * 100 for o in out], edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dos', required=True)
    ap.add_argument('--pw', required=True)
    ap.add_argument('--rate', type=int, default=44100)
    args = ap.parse_args()

    dos_st, dos = load(args.dos, args.rate)
    pw_st, pw = load(args.pw, args.rate)
    if not len(dos) or not len(pw):
        sys.exit('one of the captures is empty')

    print(f'{"":<10} {"length":>8}')
    describe('DOS', dos_st, dos, args.rate)
    describe('picowolf', pw_st, pw, args.rate)

    off, corr = best_offset(dos, pw, args.rate)
    print(f'\nbest alignment: picowolf is {off:+.2f}s from the DOS capture, '
          f'envelope correlation {corr:.3f}')

    # Compare the overlapping stretch at that offset.
    a, b = dos, pw
    s = int(abs(off) * args.rate)
    if off >= 0:
        a = a[s:]
    else:
        b = b[s:]
    m = min(len(a), len(b))
    a, b = a[:m], b[:m]
    print(f'overlap: {m / args.rate:.1f}s')

    ba, edges = bands(a, args.rate)
    bb, _ = bands(b, args.rate)
    print(f'\n{"band":>14}{"DOS":>9}{"picowolf":>11}{"diff":>9}')
    print('-' * 44)
    for lo, hi, x, y in zip(edges[:-1], edges[1:], ba, bb):
        print(f'{f"{lo}-{hi} Hz":>14}{x:8.2f}%{y:10.2f}%{y - x:+8.2f}')


if __name__ == '__main__':
    main()
