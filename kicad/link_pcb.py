#!/usr/bin/env python3
"""Repair the schematic<->board linkage in desk.kicad_pcb.

Usage:
    python3 link_pcb.py [desk.kicad_sch] [desk.kicad_pcb]

Every footprint on a KiCad board carries (path "/<symbol-uuid>") pointing at
the schematic symbol it came from. Boards written by hand (or by a generator
that forgets it) have no such link, so "Update PCB from Schematic" cannot
match anything: it treats every symbol as new and every footprint as an
orphan. This walks the schematic, maps reference designator -> symbol uuid,
and injects the matching path into each footprint.

Idempotent: footprints that already carry a path are left alone.
"""
import re
import sys

import sexp


def symbol_uuids(sch_path):
    """{reference: uuid} for every placed symbol in the schematic."""
    tree = sexp.parse(open(sch_path).read())
    out = {}
    for s in sexp.find(tree, "symbol"):
        if not sexp.find(s, "lib_id"):
            continue                       # a lib_symbols definition, not an instance
        uid = sexp.first(s, "uuid")
        ref = None
        for p in sexp.find(s, "property"):
            if p[1] == '"Reference"':
                ref = p[2].strip('"')
        if ref and uid:
            out[ref] = uid[1].strip('"')
    return out


def main():
    sch = sys.argv[1] if len(sys.argv) > 1 else "desk.kicad_sch"
    pcb = sys.argv[2] if len(sys.argv) > 2 else "desk.kicad_pcb"

    uuids = symbol_uuids(sch)
    text = open(pcb).read()

    added, missing = [], []

    def repair(match):
        """Insert path + sheetname right after a footprint's own uuid."""
        block_start = match.end()
        # reference designator lives in this footprint's Reference property
        window = text[match.start():match.start() + 4000]
        m = re.search(r'\(property "Reference"\s*"([^"]+)"', window)
        if not m:
            return match.group(0)
        ref = m.group(1)
        if '(path "' in window[:window.find('(pad ')]:
            return match.group(0)          # already linked
        uid = uuids.get(ref)
        if not uid:
            missing.append(ref)
            return match.group(0)
        added.append(ref)
        return match.group(0) + f'\n\t\t(path "/{uid}")\n\t\t(sheetname "/")'

    # anchor on each footprint's own uuid line, which the generator does emit
    out = re.sub(r'\(footprint "[^"]+"\s*\(layer "[^"]+"\)\s*'
                 r'\(uuid "[0-9a-f-]+"\)',
                 repair, text)

    if not added:
        print("nothing to do - no unlinked footprints found")
        return
    open(pcb, "w").write(out)
    print(f"linked {len(added)} footprints: {', '.join(sorted(added))}")
    if missing:
        print(f"WARNING no schematic symbol for: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    main()
