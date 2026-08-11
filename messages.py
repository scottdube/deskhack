#!/usr/bin/env python3
"""Decode the box's data line as discrete packets.

Usage:
    python3 messages.py ~/desk.csv

The line is not a continuous stream. It sends bursts of 32-bit packets at
~80ms intervals separated by a long low, so packets are segmented on that
gap and each is decoded independently. Framing is 1000 baud, 8 data bits,
odd parity, LSB first -- derived from the capture, not from the published
figures for other LOGICDATA models.
"""
import sys
from collections import Counter

from probe import load
from dataline import deglitch, rle

BLACK, WHITE, YELLOW = 6, 3, 2
BAUD = 1000.0


def bitstring(runs, bit):
    return "".join(str(v) * max(1, round(n / bit)) for _, v, n in runs)


DATABITS, STOPS = 9, 1
FRAME = 1 + DATABITS + STOPS


def frames(bits):
    """Parse an idle-high bit string into 9N1 frames.

    Solved rather than scanned: in real async serial every 0 bit must fall
    inside a frame and everything between frames is idle 1s, which is a tight
    enough constraint to find the one valid alignment. A greedy left-to-right
    scan misaligns on words whose data bits look like a start bit.

    Padded with idle bits because a packet followed by idle-high rather than
    the inter-burst low loses its trailing stop bit during segmentation.
    """
    bits += "1" * (FRAME + 1)
    n = len(bits)
    memo = {}

    def go(i):
        if i in memo:
            return memo[i]
        if i >= n:
            return ()
        if bits[i] == "1":
            r = go(i + 1)
        elif i + FRAME > n:
            r = None
        else:
            f = bits[i:i + FRAME]
            if any(c != "1" for c in f[-STOPS:]):
                r = None
            else:
                rest = go(i + FRAME)
                if rest is None:
                    r = None
                else:
                    v = sum(1 << k for k, c in enumerate(f[1:1 + DATABITS])
                            if c == "1")
                    r = (v,) + rest
        memo[i] = r
        return r

    parsed = go(0)
    return [(v, "") for v in parsed] if parsed is not None else [("bad", bits)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sr, _, rows = load(sys.argv[1])
    if not sr:
        sys.exit("no samplerate in capture")
    bit = sr / BAUD

    black = [r[BLACK] for r in rows]
    white = [r[WHITE] for r in rows]
    yellow = [r[YELLOW] for r in rows]

    packets, cur, at = [], [], 0
    for v, n in deglitch(rle(black), 2):
        if v == 0 and n > 20 * bit:          # inter-packet gap
            if cur:
                packets.append(cur)
                cur = []
        elif cur or v == 1:
            cur.append((at, v, n))
        at += n
    if cur:
        packets.append(cur)

    packets = [p for p in packets if sum(n for _, _, n in p) < 60 * bit]

    print(f"{len(packets)} packets\n")
    print("   time    ctx    gap      bytes            raw")
    print("  " + "-" * 66)
    prev, hist, second = None, Counter(), []
    for p in packets:
        start = p[0][0]
        bits = bitstring(p, bit)
        decoded = frames(bits)
        vals = [d[0] for d in decoded]
        ctx = "UP  " if white[start] else ("DOWN" if yellow[start] else "--  ")
        gap = f"{(start - prev) / sr * 1000:6.1f}ms" if prev else "     -"
        shown = " ".join(f"{v:03X}" if isinstance(v, int) else str(v)
                         for v in vals)
        print(f"  {start/sr:7.3f}s {ctx} {gap}  {shown:<20} {bits}")
        prev = start
        for v in vals:
            hist[v if isinstance(v, int) else "bad"] += 1
        ints = [v for v in vals if isinstance(v, int)]
        if len(ints) >= 2:
            second.append((start / sr, ints[1]))

    print("\n  byte frequency:")
    for v, c in hist.most_common(12):
        label = f"0x{v:02X} ({v:3d})" if isinstance(v, int) else "bad     "
        print(f"    {label}  x{c}")

    if second:
        print("\n  second byte over time (candidate payload):")
        for t, v in second:
            print(f"    {t:7.3f}s  0x{v:02X}  {v:3d}  {v & 0x7F:3d}(low7)")


if __name__ == "__main__":
    main()
