#!/usr/bin/env python3
"""Read the LOGICDATA handset bus as a 4-bit button code over time.

Usage:
    python3 timeline.py ~/desk.csv [glitch_us]

Capture channel order must be D0..D6 = red, green, yellow, white, brown,
blue, black. Red is the +5V rail and brown is ground, so the button code is
green/yellow/white/blue and black is the box's data output.

Runs shorter than glitch_us (default 200us) are absorbed into the preceding
state. Long unshielded pigtails pick up enough crosstalk to produce
single-sample spikes that would otherwise swamp the timeline.
"""
import sys
from collections import defaultdict

from probe import load  # reuse the CSV parser and its samplerate handling

# CSV column index -> wire
RED, GREEN, YELLOW, WHITE, BROWN, BLUE, BLACK = range(7)
CODE_BITS = [("G", GREEN), ("Y", YELLOW), ("W", WHITE), ("B", BLUE)]


def encode(row):
    """Pack the four button lines into a nibble, MSB = green."""
    v = 0
    for _, col in CODE_BITS:
        v = (v << 1) | row[col]
    return v


def render(code):
    """0b0010 -> '--W-' so a glance shows which lines are asserted."""
    out = ""
    for i, (name, _) in enumerate(CODE_BITS):
        out += name if code & (1 << (3 - i)) else "-"
    return out


def rle(values):
    runs = [[values[0], 1]]
    for v in values[1:]:
        if v == runs[-1][0]:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    return runs


def deglitch(runs, min_len):
    """Absorb sub-threshold runs into the previous state, then coalesce."""
    out = []
    for code, n in runs:
        if n < min_len and out:
            out[-1][1] += n
        elif out and out[-1][0] == code:
            out[-1][1] += n
        else:
            out.append([code, n])
    # merging can leave adjacent equal states; one more pass settles it
    final = []
    for code, n in out:
        if final and final[-1][0] == code:
            final[-1][1] += n
        else:
            final.append([code, n])
    return final


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    glitch_us = float(sys.argv[2]) if len(sys.argv) > 2 else 200.0

    sr, _, rows = load(sys.argv[1])
    if not sr:
        sys.exit("no samplerate in capture")
    if len(rows[0]) < 7:
        sys.exit(f"expected 7 channels, got {len(rows[0])}")

    min_len = max(1, int(sr * glitch_us / 1e6))
    print(f"{len(rows):,} samples @ {sr:,.0f} Hz "
          f"({len(rows)/sr:.1f}s), glitch filter {glitch_us:.0f}us "
          f"({min_len} samples)\n")

    # Sanity: red should never move, brown should never move.
    for col, name, want in ((RED, "red", 1), (BROWN, "brown", 0)):
        vals = {r[col] for r in rows}
        if vals != {want}:
            print(f"WARNING: {name} is not static {want} -- saw {sorted(vals)}")

    segs = deglitch(rle([encode(r) for r in rows]), min_len)

    black = [r[BLACK] for r in rows]
    print("  time      code            duration   data line (black)")
    print("  " + "-" * 60)
    at = 0
    totals = defaultdict(float)
    for code, n in segs:
        secs = n / sr
        totals[code] += secs
        edges = sum(1 for i in range(at + 1, at + n) if black[i] != black[i - 1])
        note = f"{edges:6,} edges" if edges else "     idle"
        if secs >= 0.02:      # skip blink-length fragments in the listing
            print(f"  {at/sr:7.3f}s  {code:04b} {render(code)}   "
                  f"{secs:7.3f}s   {note}")
        at += n

    print("\n  total time per code:")
    for code, secs in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"    {code:04b} {render(code)}  {secs:7.3f}s")


if __name__ == "__main__":
    main()
