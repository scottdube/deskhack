#!/usr/bin/env python3
"""Generate a starter desk.kicad_pcb: all footprints placed and netted.

Usage:
    python3 gen_pcb.py [outdir]

No tracks are drawn -- routing is left to the human. Placement puts the two
ESP32 DevKit V1 socket rows exactly 25.4mm apart (measured on the actual
board), pin 1 of both rows at the top, antenna end toward the board edge.
"""
import os
import re
import sys

import sexp

FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"

FOOTPRINTS = {
    "J1": ("TerminalBlock_Phoenix",
           "TerminalBlock_Phoenix_MKDS-1,5-7_1x07_P5.00mm_Horizontal",
           "DIN harness"),
    "R1": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "330"),
    "R2": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "330"),
    "R3": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "100k"),
    "R4": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "100k"),
    "R5": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "22k"),
    "R6": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "22k"),
    "R7": ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
           "22k"),
    "U1": ("Package_DIP", "DIP-4_W7.62mm", "PC817"),
    "U2": ("Package_DIP", "DIP-4_W7.62mm", "PC817"),
    "J2": ("Connector_PinSocket_2.54mm", "PinSocket_1x15_P2.54mm_Vertical",
           "ESP32 left"),
    "J3": ("Connector_PinSocket_2.54mm", "PinSocket_1x15_P2.54mm_Vertical",
           "ESP32 right"),
}

# J1 terminal block along the top edge; optos and their parts mid-left;
# divider mid-right; DevKit sockets on the right, rows 25.4mm apart.
PLACE = {
    "J1": (112.0, 108.0),
    "R1": (106.0, 122.0), "U1": (124.0, 120.73),
    "R2": (106.0, 136.0), "U2": (124.0, 134.73),
    "R3": (106.0, 129.0),
    "R4": (106.0, 143.0),
    "R5": (140.0, 143.0), "R6": (140.0, 148.5), "R7": (140.0, 154.0),
    "J2": (157.0, 114.0), "J3": (182.4, 114.0),   # 25.4mm row spacing
}

NETS = ["GND", "+5V", "WHITE_UP", "YELLOW_DN", "BLACK_DATA",
        "GPIO16", "GPIO25", "GPIO26", "N-DIV", "N-LED1", "N-LED2"]

CONN = {
    ("J1", "1"): "GND", ("J1", "2"): "+5V", ("J1", "3"): "WHITE_UP",
    ("J1", "4"): "YELLOW_DN", ("J1", "5"): "BLACK_DATA",
    # PC817: 1 anode, 2 cathode, 3 emitter, 4 collector
    ("R1", "2"): "GPIO25", ("R1", "1"): "N-LED1",
    ("U1", "1"): "N-LED1", ("U1", "2"): "GND",
    ("U1", "4"): "+5V", ("U1", "3"): "WHITE_UP",
    ("R3", "1"): "WHITE_UP", ("R3", "2"): "GND",
    ("R2", "2"): "GPIO26", ("R2", "1"): "N-LED2",
    ("U2", "1"): "N-LED2", ("U2", "2"): "GND",
    ("U2", "4"): "+5V", ("U2", "3"): "YELLOW_DN",
    ("R4", "1"): "YELLOW_DN", ("R4", "2"): "GND",
    ("R5", "1"): "BLACK_DATA", ("R5", "2"): "GPIO16",
    ("R6", "1"): "GPIO16", ("R6", "2"): "N-DIV",
    ("R7", "1"): "N-DIV", ("R7", "2"): "GND",
    # DevKit V1 30-pin: J2 = EN..VIN row, J3 = D23..3V3 row, pin 1 at top
    ("J2", "8"): "GPIO25",     # D25
    ("J2", "9"): "GPIO26",     # D26
    ("J2", "14"): "GND",
    ("J3", "10"): "GPIO16",    # RX2/D16
    ("J3", "14"): "GND",
}

OUTLINE = (100.0, 100.0, 194.0, 160.0)          # x1 y1 x2 y2


def load_mod(lib, name):
    return sexp.parse(open(f"{FP}/{lib}.pretty/{name}.kicad_mod").read())


def render(node):
    """Serialize a nested list back to KiCad text."""
    if not isinstance(node, list):
        return node
    parts = []
    for x in node:
        parts.append(render(x))
    return "(" + " ".join(parts) + ")"


def footprint(ref, lib, name, value, x, y, net_ids):
    tree = load_mod(lib, name)
    tree[1] = f'"{lib}:{name}"'
    # strip source-file bookkeeping that does not belong on a board instance
    tree[:] = [n for n in tree
               if not (isinstance(n, list)
                       and n and n[0] in ("version", "generator",
                                          "generator_version"))]
    # placement + identity, inserted right after the name
    tree.insert(2, ["layer", '"F.Cu"'])
    tree.insert(3, ["uuid", f'"{sexp_uid()}"'])
    tree.insert(4, ["at", str(x), str(y)])
    for prop in sexp.find(tree, "property"):
        if prop[1] == '"Reference"':
            prop[2] = f'"{ref}"'
        elif prop[1] == '"Value"':
            prop[2] = f'"{value}"'
    unconnected = []
    for pad in sexp.find(tree, "pad"):
        num = pad[1].strip('"')
        net = CONN.get((ref, num))
        if net:
            nid = net_ids[net]
            pad.append(["net", str(nid), f'"{net}"'])
        elif num:
            uname = f"unconnected-({ref}-Pad{num})"
            nid = len(net_ids) + 1
            net_ids[uname] = nid
            unconnected.append(uname)
            pad.append(["net", str(nid), f'"{uname}"'])
        pad.append(["uuid", f'"{sexp_uid()}"'])
    return render(tree)


_uid = [0]


def sexp_uid():
    import uuid as u
    _uid[0] += 1
    return str(u.uuid5(u.UUID("6f2b1d3e-0000-4000-8000-0000000000cd"),
                       str(_uid[0])))


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    net_ids = {n: i + 1 for i, n in enumerate(NETS)}

    fps = []
    for ref, (lib, name, value) in FOOTPRINTS.items():
        x, y = PLACE[ref]
        fps.append(footprint(ref, lib, name, value, x, y, net_ids))

    nets = ['(net 0 "")'] + [
        f'(net {i} "{n}")'
        for n, i in sorted(net_ids.items(), key=lambda kv: kv[1])
    ]

    x1, y1, x2, y2 = OUTLINE
    edges = []
    for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)),
                 ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        edges.append(
            f"(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) "
            f'(stroke (width 0.1) (type default)) (layer "Edge.Cuts") '
            f'(uuid "{sexp_uid()}"))'
        )

    doc = "\n".join([
        "(kicad_pcb",
        "\t(version 20241229)",
        '\t(generator "pcbnew")',
        '\t(generator_version "9.0")',
        "\t(general (thickness 1.6) (legacy_teardrops no))",
        '\t(paper "A4")',
        '\t(title_block (title "Standing desk interface"))',
        "\t(layers",
        '\t\t(0 "F.Cu" signal)',
        '\t\t(2 "B.Cu" signal)',
        '\t\t(5 "F.SilkS" user "F.Silkscreen")',
        '\t\t(7 "B.SilkS" user "B.Silkscreen")',
        '\t\t(1 "F.Mask" user)',
        '\t\t(3 "B.Mask" user)',
        '\t\t(13 "F.Paste" user)',
        '\t\t(15 "B.Paste" user)',
        '\t\t(25 "Edge.Cuts" user)',
        '\t\t(29 "F.CrtYd" user "F.Courtyard")',
        '\t\t(31 "B.CrtYd" user "B.Courtyard")',
        '\t\t(35 "F.Fab" user)',
        '\t\t(37 "B.Fab" user)',
        "\t)",
        "\t(setup (pad_to_mask_clearance 0))",
        "\t" + "\n\t".join(nets),
        "\t" + "\n\t".join(fps),
        "\t" + "\n\t".join(edges),
        ")",
    ])
    path = os.path.join(outdir, "desk.kicad_pcb")
    open(path, "w").write(doc + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
