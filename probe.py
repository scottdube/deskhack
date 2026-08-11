#!/usr/bin/env python3
"""Characterize the LOGICDATA handset bus from a sigrok capture.

Usage:
    sigrok-cli -i desk.sr -O csv > desk.csv
    python3 probe.py desk.csv

Prints, per channel: idle level, activity, and — for channels that look like
async serial — the implied baud rate derived from the narrowest pulse.
Do not trust a baud rate you have not measured; the 1000 figure in the
community projects comes from a different LOGICDATA model.
"""
import sys
from collections import Counter


SUFFIX = {"k": 1e3, "m": 1e6, "g": 1e9}


def parse_rate(line):
    """'; Samplerate: 100 kHz' or 'META samplerate: 100000' -> Hz.

    The unit suffix is not optional to handle: sigrok writes bare Hz for some
    input formats and scaled units for others, and silently dropping the 'k'
    scales every derived timing by 1000.
    """
    tail = line.lower().split("samplerate")[-1].lstrip(": ")
    parts = tail.split()
    if not parts:
        return None
    try:
        value = float(parts[0])
    except ValueError:
        return None
    unit = "".join(parts[1:]) if len(parts) > 1 else ""
    if unit[:1] in SUFFIX:
        value *= SUFFIX[unit[:1]]
    return value


def load(path):
    """Read a sigrok CSV export -> (samplerate, names, list-of-rows).

    sigrok's CSV has ';' comments, a bare "META samplerate: N" line, and a
    non-numeric header row before the samples. Anything that doesn't parse
    as a row of integers is metadata.
    """
    samplerate, names, rows = None, None, []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        if "samplerate" in line.lower():
            samplerate = parse_rate(line)
            continue
        if line.startswith(";"):
            if "channels" in line.lower() and ":" in line:
                names = [c.strip() for c in line.split(":", 1)[1].split(",")]
            continue
        try:
            rows.append([int(c) for c in line.split(",")])
        except ValueError:
            continue  # header row such as "logic"
    return samplerate, names, rows


def runs(seq):
    """Yield (value, run_length) for consecutive equal samples."""
    cur, n = seq[0], 1
    for v in seq[1:]:
        if v == cur:
            n += 1
        else:
            yield cur, n
            cur, n = v, 1
    yield cur, n


def describe(name, seq, sr):
    total = len(seq)
    high = sum(seq)
    lengths = [n for _, n in runs(seq)]
    edges = len(lengths) - 1

    if edges == 0:
        level = "HIGH (likely +5V rail)" if seq[0] else "LOW (likely GND)"
        return f"{name:>4}  static {level}"

    duty = 100.0 * high / total
    shortest = min(lengths)
    longest = max(lengths)

    out = [f"{name:>4}  {edges} edges, {duty:5.1f}% high, "
           f"idle={'HIGH' if seq[0] else 'LOW'}"]

    if sr:
        short_ms = 1000.0 * shortest / sr
        long_ms = 1000.0 * longest / sr
        out.append(f"      narrowest pulse {short_ms:.3f} ms  "
                   f"-> implied baud {sr / shortest:,.0f}")
        out.append(f"      widest pulse    {long_ms:.1f} ms")

    # A button line makes a handful of very wide transitions. A serial line
    # makes many narrow ones clustered around integer multiples of a bit time.
    if edges > 20 and shortest * 20 < longest:
        out.append("      -> looks like SERIAL DATA")
    elif edges <= 12 and longest > total * 0.05:
        out.append("      -> looks like a BUTTON line")

    hist = Counter(lengths).most_common(4)
    out.append("      run lengths (samples x count): " +
               ", ".join(f"{l}x{c}" for l, c in hist))
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sr, names, rows = load(sys.argv[1])
    if not rows:
        sys.exit("no samples parsed - is this a sigrok CSV export?")
    nch = len(rows[0])
    names = names or [f"D{i}" for i in range(nch)]
    print(f"{len(rows):,} samples, {nch} channels"
          + (f", {sr:,.0f} Hz\n" if sr else ", samplerate UNKNOWN\n"))
    for i in range(nch):
        print(describe(names[i], [r[i] for r in rows], sr))
        print()


if __name__ == "__main__":
    main()
