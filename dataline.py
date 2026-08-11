#!/usr/bin/env python3
"""Characterize the box's data line and attempt a UART decode.

Usage:
    python3 dataline.py ~/desk.csv [glitch_us]

Measures the bit time from the run-length distribution rather than trusting
the 1000 baud figure published for other LOGICDATA models, then tries the
plausible framings and reports whichever produces valid stop bits.
"""
import sys
from collections import Counter

from probe import load

BLACK = 6


def rle(values):
    runs = [[values[0], 1]]
    for v in values[1:]:
        if v == runs[-1][0]:
            runs[-1][1] += 1
        else:
            runs.append([v, 1])
    return runs


def deglitch(runs, min_len):
    out = []
    for val, n in runs:
        if n < min_len and out:
            out[-1][1] += n
        elif out and out[-1][0] == val:
            out[-1][1] += n
        else:
            out.append([val, n])
    return out


def rebuild(runs):
    sig = []
    for val, n in runs:
        sig.extend([val] * n)
    return sig


def decode(sig, bit, databits=8, parity="none", stops=1, msb=False):
    """Walk the signal as async serial.

    Returns (list of (sample_index, value), frame_errors). The published
    LOGICDATA framing is for a different model, so every plausible
    combination gets tried rather than assuming 8-N-1 LSB-first.
    """
    has_parity = parity != "none"
    frame = 1 + databits + (1 if has_parity else 0) + stops
    out, bad, i, n = [], 0, 1, len(sig)
    while i < n:
        if sig[i] == 0 and sig[i - 1] == 1:            # falling edge = start
            centers = [int(i + bit * (0.5 + k)) for k in range(frame)]
            if centers[-1] >= n:
                break
            s = [sig[c] for c in centers]
            if s[0] != 0 or any(v != 1 for v in s[-stops:]):
                bad += 1
                i += 1
                continue
            bits = s[1:1 + databits]
            order = reversed(bits) if msb else bits
            byte = sum(b << k for k, b in enumerate(order))
            if has_parity:
                want = sum(bits) & 1
                got = s[1 + databits]
                if (parity == "even") != (got == want):
                    bad += 1
                    i += 1
                    continue
            out.append((i, byte))
            i = centers[-1] + 1
        else:
            i += 1
    return out, bad


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    glitch_us = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

    sr, _, rows = load(sys.argv[1])
    if not sr:
        sys.exit("no samplerate in capture")

    min_len = max(1, int(sr * glitch_us / 1e6))
    runs = deglitch(rle([r[BLACK] for r in rows]), min_len)
    sig = rebuild(runs)

    us = lambda n: n / sr * 1e6
    print(f"{len(rows):,} samples @ {sr:,.0f} Hz, "
          f"glitch filter {glitch_us:.0f}us ({min_len} samples)")
    print(f"{len(runs):,} runs after filtering\n")

    hist = Counter(n for _, n in runs)
    print("  most common run lengths:")
    for n, count in hist.most_common(12):
        print(f"    {us(n):9.1f} us  ({n:6,} samples)  x{count:,}")

    # The bit time is the shortest run that shows up often enough to be real.
    common = [n for n, c in hist.items() if c >= max(5, len(runs) // 100)]
    if not common:
        sys.exit("\nnot enough structure to estimate a bit time")
    bit = min(common)
    print(f"\n  estimated bit time {us(bit):.1f} us "
          f"-> {sr / bit:,.0f} baud\n")

    results = []
    for databits in (7, 8, 9):
        for parity in ("none", "even", "odd"):
            for stops in (1, 2):
                for msb in (False, True):
                    data, bad = decode(sig, bit, databits, parity, stops, msb)
                    total = len(data) + bad
                    if total < 4:
                        continue
                    rate = 100.0 * len(data) / total
                    results.append((rate, len(data), databits, parity,
                                    stops, msb, data))

    if not results:
        sys.exit("  no framing produced enough frames to judge")

    results.sort(key=lambda r: (-r[0], -r[1]))
    print("  best framings (ranked by clean rate):")
    for rate, count, db, par, st, msb, _ in results[:6]:
        order = "MSB" if msb else "LSB"
        print(f"    {db}{par[0].upper()}{st} {order}-first: "
              f"{count:5,} frames, {rate:5.1f}% clean")

    def dump(rate, db, par, st, msb, data):
        order = "MSB" if msb else "LSB"
        print(f"\n  bytes for {db}{par[0].upper()}{st} {order}-first"
              f"  ({rate:.1f}% clean):")
        prev, line = None, []
        for idx, byte in data[:96]:
            # A long gap means a new message; break the listing there so the
            # structure is visible instead of one undifferentiated run.
            if prev is not None and (idx - prev) > bit * 20:
                print("    " + " ".join(line)
                      + f"     [+{us(idx - prev) / 1000:.0f}ms]")
                line = []
            line.append(f"{byte:02X}")
            prev = idx
        if line:
            print("    " + " ".join(line))

    top = results[0]
    dump(top[0], *top[2:])
    # Parity is order-independent, so MSB-first always ties with LSB-first.
    # Print the counterpart too -- only the values themselves can break it.
    for r in results:
        if r[0] == top[0] and r[5] != top[5] and r[2] == top[2]:
            dump(r[0], *r[2:])
            break


if __name__ == "__main__":
    main()
