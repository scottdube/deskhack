#!/usr/bin/env python3
"""Copy the proven isolation-milling design rules into a KiCad project.

Usage:
    python3 apply_mill_rules.py <target.kicad_pro> [...]

Rules and net classes are lifted from sln-geo-aux-heat, which has actually
been milled and whose G-code lives in pcbmill's proven_out fixtures -- so
these numbers are field-tested rather than guessed. Everything else in the
target project file is left untouched.
"""
import json
import os
import sys

SRC = ("/Users/scottdube/code/sln-ha-config/electronics/kicad/"
       "sln-geo-aux-heat/sln-geo-aux-heat.kicad_pro")

# Nets matched to the Power class automatically, so a board does not need
# hand-assignment every time. Patterns are KiCad wildcard syntax.
POWER_PATTERNS = ["GND", "+5V", "+3V3", "+12V", "VCC", "VIN"]

# The committed v1-as-cut board used 0.4mm on the Default class and 0.5mm on
# Power. Later (uncommitted) revisions moved everything to 0.5mm, which is
# what actually gets milled, so both classes are normalized to it here.
CLEARANCE = 0.5


def load_reference():
    src = json.load(open(SRC))
    rules = dict(src["board"]["design_settings"]["rules"])
    classes = [dict(c) for c in src["net_settings"]["classes"]]
    rules["min_clearance"] = CLEARANCE
    for c in classes:
        c["clearance"] = CLEARANCE
    return rules, classes


def apply(path, rules, classes):
    d = json.load(open(path)) if os.path.exists(path) else {}

    ds = d.setdefault("board", {}).setdefault("design_settings", {})
    ds["rules"] = rules
    ds["track_widths"] = [0.0, 0.6, 1.0, 1.5, 2.0]   # 0.0 = use netclass
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0},
                            {"diameter": 1.6, "drill": 0.8}]

    ns = d.setdefault("net_settings", {})
    ns["classes"] = classes
    ns.setdefault("meta", {"version": 5})
    ns.setdefault("net_colors", None)
    ns.setdefault("netclass_assignments", None)
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": p}
                               for p in POWER_PATTERNS]

    d.setdefault("libraries",
                 {"pinned_footprint_libs": [], "pinned_symbol_libs": []})
    d.setdefault("boards", [])
    d.setdefault("text_variables", {})
    meta = d.setdefault("meta", {})
    meta.setdefault("filename", os.path.basename(path))
    meta.setdefault("version", 3)

    json.dump(d, open(path, "w"), indent=2)
    return d


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rules, classes = load_reference()
    for path in sys.argv[1:]:
        apply(path, rules, classes)
        widths = {c["name"]: c["track_width"] for c in classes}
        print(f"{path}: min_track={rules['min_track_width']} "
              f"min_clearance={rules['min_clearance']} classes={widths}")


if __name__ == "__main__":
    main()
