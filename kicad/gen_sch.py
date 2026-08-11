#!/usr/bin/env python3
"""Generate the desk interface schematic as a KiCad 10 project.

Usage:
    python3 gen_sch.py [outdir]

Symbol definitions are lifted from the installed KiCad libraries and embedded
in the .kicad_sch, so the file opens standalone without library lookups.
"""
import os
import sys
import uuid as uuidlib

import sexp

LIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
NS = uuidlib.UUID("6f2b1d3e-0000-4000-8000-000000000000")
SHEET = "b1c0ffee-0000-4000-8000-000000000001"

_n = [0]


def uid():
    """Deterministic UUIDs so regenerating gives a clean diff."""
    _n[0] += 1
    return str(uuidlib.uuid5(NS, str(_n[0])))


# ---------------------------------------------------------------- symbols

_cache = {}


def libsym(lib, name):
    if (lib, name) not in _cache:
        tree = sexp.parse(open(f"{LIB}/{lib}.kicad_sym").read())
        for s in sexp.find(tree, "symbol"):
            if s[1] == f'"{name}"':
                _cache[(lib, name)] = s
                break
        else:
            raise KeyError(f"{lib}:{name}")
    return _cache[(lib, name)]


def pins_of(lib, name):
    """{number: (x, y)} in symbol space, from every unit/body-style block."""
    out = {}
    for sub in sexp.find(libsym(lib, name), "symbol"):
        for p in sexp.find(sub, "pin"):
            at = sexp.first(p, "at")
            num = sexp.first(p, "number")[1].strip('"')
            out[num] = (float(at[1]), float(at[2]))
    return out


def place_pin(px, py, x, y, rot, mirror):
    """Symbol-space pin -> sheet coordinates.

    Schematic Y runs downward while symbol Y runs up, hence the negation.
    """
    if mirror == "y":
        px = -px
    if rot == 0:
        dx, dy = px, -py
    elif rot == 90:
        dx, dy = py, px
    elif rot == 180:
        dx, dy = -px, py
    elif rot == 270:
        dx, dy = -py, -px
    else:
        raise ValueError(rot)
    return (round(x + dx, 4), round(y + dy, 4))


# ---------------------------------------------------------------- emitters

items = []
used = {}


def comp(lib, name, ref, value, x, y, rot=0, mirror=None, footprint="",
         val_off=6.35):
    used[(lib, name)] = True
    pins = pins_of(lib, name)
    body = [f'\t(symbol\n\t\t(lib_id "{lib}:{name}")\n\t\t(at {x} {y} {rot})']
    if mirror:
        body.append(f"\t\t(mirror {mirror})")
    body.append(
        f"\t\t(unit 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n"
        f"\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(uuid \"{uid()}\")"
    )
    for pname, pval, off, hide in (
        ("Reference", ref, -6.35, False),
        ("Value", value, val_off, False),
        ("Footprint", footprint, 0, True),
        ("Datasheet", "~", 0, True),
    ):
        h = "\n\t\t\t\t(hide yes)" if hide else ""
        body.append(
            f'\t\t(property "{pname}" "{pval}"\n'
            f"\t\t\t(at {x} {round(y + off, 4)} 0)\n"
            f"\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n"
            f"\t\t\t\t){h}\n\t\t\t)\n\t\t)"
        )
    for num in sorted(pins, key=lambda s: (len(s), s)):
        body.append(f'\t\t(pin "{num}"\n\t\t\t(uuid "{uid()}")\n\t\t)')
    body.append(
        f'\t\t(instances\n\t\t\t(project "desk"\n\t\t\t\t(path "/{SHEET}"\n'
        f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n'
        f"\t\t\t\t)\n\t\t\t)\n\t\t)"
    )
    body.append("\t)")
    items.append("\n".join(body))
    return {n: place_pin(*p, x, y, rot, mirror) for n, p in pins.items()}


def wire(a, b):
    items.append(
        f"\t(wire\n\t\t(pts\n\t\t\t(xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})\n"
        f"\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n"
        f'\t\t(uuid "{uid()}")\n\t)'
    )


def label(text, at, rot=0, justify="left bottom"):
    items.append(
        f'\t(label "{text}"\n\t\t(at {at[0]} {at[1]} {rot})\n\t\t(effects\n'
        f"\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
        f"\t\t\t(justify {justify})\n\t\t)\n"
        f'\t\t(uuid "{uid()}")\n\t)'
    )


def junction(at):
    items.append(
        f"\t(junction\n\t\t(at {at[0]} {at[1]})\n\t\t(diameter 0)\n"
        f"\t\t(color 0 0 0 0)\n"
        f'\t\t(uuid "{uid()}")\n\t)'
    )


def noconn(at):
    items.append(f'\t(no_connect\n\t\t(at {at[0]} {at[1]})\n\t\t(uuid "{uid()}")\n\t)')


def note(text, at, size=1.27):
    esc = text.replace("\n", "\\n")
    items.append(
        f'\t(text "{esc}"\n\t\t(exclude_from_sim no)\n'
        f"\t\t(at {at[0]} {at[1]} 0)\n\t\t(effects\n\t\t\t(font\n"
        f"\t\t\t\t(size {size} {size})\n\t\t\t)\n\t\t\t(justify left top)\n"
        f'\t\t)\n\t\t(uuid "{uid()}")\n\t)'
    )


# ---------------------------------------------------------------- circuit

def build():
    # ---- DIN harness in, on the left, mirrored so its pins face the circuit
    j1 = comp("Connector_Generic", "Conn_01x07", "J1", "DIN harness",
              63.5, 101.6, mirror="y",
              footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-7_1x07_P5.00mm_Horizontal")
    names = {
        "1": ("GND", "brown"),
        "2": ("+5V", "red"),
        "3": ("WHITE_UP", "white"),
        "4": ("YELLOW_DN", "yellow"),
        "5": ("BLACK_DATA", "black"),
    }
    for num, (net, colour) in names.items():
        p = j1[num]
        end = (p[0] + 10.16, p[1])
        wire(p, end)
        label(net, end)
    for num in ("6", "7"):                      # green / blue, HS3 / HS4
        p = j1[num]
        end = (p[0] + 5.08, p[1])
        wire(p, end)
        noconn(end)

    # ---- opto channels. PC817: 1 anode, 2 cathode, 3 emitter, 4 collector.
    for ref_u, ref_r, ref_b, gpio, net, y in (
        ("U1", "R1", "R3", "GPIO25", "WHITE_UP", 76.2),
        ("U2", "R2", "R4", "GPIO26", "YELLOW_DN", 114.3),
    ):
        r = comp("Device", "R", ref_r, "330", 109.22, y, rot=90,
                 footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
        u = comp("Isolator", "PC817", ref_u, "PC817", 127.0, y + 2.54,
                 footprint="Package_DIP:DIP-4_W7.62mm")
        label(gpio, (r["2"][0] - 10.16, y))
        wire((r["2"][0] - 10.16, y), r["2"])
        wire(r["1"], u["1"])                      # series R into the LED

        wire(u["2"], (u["2"][0] - 5.08, u["2"][1]))   # cathode to ground
        label("GND", (u["2"][0] - 5.08, u["2"][1]), justify="right bottom")

        wire(u["4"], (u["4"][0] + 5.08, u["4"][1]))   # collector to +5V
        label("+5V", (u["4"][0] + 5.08, u["4"][1]))

        # Emitter drives the desk's button line, with a bleed to ground so
        # phototransistor leakage cannot float a high-impedance input high.
        tap = (u["3"][0] + 15.24, u["3"][1])
        wire(u["3"], tap)
        label(net, tap)
        bleed = comp("Device", "R", ref_b, "100k", u["3"][0] + 7.62,
                     u["3"][1] + 11.43,
                     footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
        junction((bleed["1"][0], u["3"][1]))
        wire((bleed["1"][0], u["3"][1]), bleed["1"])
        wire(bleed["2"], (bleed["2"][0], bleed["2"][1] + 5.08))
        label("GND", (bleed["2"][0], bleed["2"][1] + 5.08), justify="left top")

    # ---- 3:1 divider dropping the 5V data line to 3.33V for the ESP32
    x = 190.5
    label("BLACK_DATA", (x, 57.15), justify="left bottom")
    r5 = comp("Device", "R", "R5", "22k", x, 66.04,
              footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
    r6 = comp("Device", "R", "R6", "22k", x, 83.82,
              footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
    r7 = comp("Device", "R", "R7", "22k", x, 99.06,
              footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
    wire((x, 57.15), r5["1"])
    tap = (x, 74.93)
    wire(r5["2"], r6["1"])
    junction(tap)
    wire(tap, (x + 15.24, 74.93))
    label("GPIO16", (x + 15.24, 74.93))
    wire(r6["2"], r7["1"])
    wire(r7["2"], (x, 107.95))
    label("GND", (x, 107.95), justify="left top")

    # ---- ESP32 DevKit V1 (30-pin) as the two socket rows a carrier board
    # actually holds. Silk names run EN..VIN down the left row and
    # D23..3V3 down the right row with the USB jack at the bottom.
    LEFT = ["EN", "VP/D36", "VN/D39", "D34", "D35", "D32", "D33",
            "D25", "D26", "D27", "D14", "D12", "D13", "GND", "VIN"]
    RIGHT = ["D23", "D22", "TX0/D1", "RX0/D3", "D21", "D19", "D18", "D5",
             "TX2/D17", "RX2/D16", "D4", "D2", "D15", "GND", "3V3"]
    NETS = {"D25": "GPIO25", "D26": "GPIO26", "RX2/D16": "GPIO16",
            "GND": "GND"}
    for ref, x, names, mirror in (("J2", 228.6, LEFT, None),
                                  ("J3", 260.35, RIGHT, "y")):
        j = comp("Connector_Generic", "Conn_01x15", ref,
                 "ESP32 DevKit V1", x, 88.9, mirror=mirror, val_off=24.13,
                 footprint="Connector_PinSocket_2.54mm:"
                           "PinSocket_1x15_P2.54mm_Vertical")
        sign = 1 if mirror else -1          # stub direction away from body
        for i, silk in enumerate(names, 1):
            p = j[str(i)]
            if silk in NETS:
                end = (round(p[0] + sign * 7.62, 4), p[1])
                wire(p, end)
                label(NETS[silk], end,
                      justify="left bottom" if sign > 0 else "right bottom")
            else:
                # Unused socket position: flag it, annotate the silk name as
                # plain text so it does not become a one-pin net.
                noconn(p)
                tx = round(p[0] + sign * 2.0, 4)
                note(silk, (tx if sign > 0 else tx - 12.7, p[1] - 0.8),
                     size=1.0)

    note("ErgoSwiss / LOGICDATA COMPACT-e-3-VAL desk interface\\n"
         "J1 wire colours: 1 brown GND, 2 red +5V, 3 white UP, 4 yellow DOWN,\\n"
         "5 black data out, 6 green HS3 (spare), 7 blue HS4 (spare).\\n"
         "Button lines are ACTIVE HIGH: the opto ties them to +5V, exactly as\\n"
         "the panel button does, so the original panel keeps working.\\n"
         "Data line is 1000 baud 9N1; a plain 8N1 UART reads it as 0xFE <byte>,\\n"
         "height_inches = (245 - byte) / 2.  Measured travel 27.0 - 38.0 in.",
         (63.5, 132.08), size=1.6)


# ---------------------------------------------------------------- output

def write(outdir):
    build()
    libs = []
    for (lib, name) in used:
        blk = sexp.dump(libsym(lib, name), indent=2)
        libs.append(blk.replace(f'(symbol "{name}"', f'(symbol "{lib}:{name}"', 1))

    doc = [
        "(kicad_sch",
        "\t(version 20260306)",
        '\t(generator "eeschema")',
        '\t(generator_version "10.0")',
        f'\t(uuid "{SHEET}")',
        '\t(paper "A4")',
        "\t(title_block",
        '\t\t(title "Standing desk interface")',
        '\t\t(company "deskhack")',
        '\t\t(comment 1 "ESP32 <-> ErgoSwiss compact-3-eco handset bus")',
        "\t)",
        "\t(lib_symbols",
        "\n".join(libs),
        "\t)",
        "\n".join(items),
        "\t(sheet_instances",
        '\t\t(path "/"',
        '\t\t\t(page "1")',
        "\t\t)",
        "\t)",
        "\t(embedded_fonts no)",
        ")",
    ]
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/desk.kicad_sch", "w") as f:
        f.write("\n".join(doc) + "\n")
    with open(f"{outdir}/desk.kicad_pro", "w") as f:
        f.write('{\n  "board": {},\n  "boards": [],\n  "libraries": '
                '{"pinned_footprint_libs": [], "pinned_symbol_libs": []},\n'
                '  "meta": {"filename": "desk.kicad_pro", "version": 3},\n'
                '  "net_settings": {"classes": [{"name": "Default", '
                '"clearance": 0.2, "track_width": 0.25}]},\n'
                '  "sheets": [["' + SHEET + '", "Root"]],\n'
                '  "text_variables": {}\n}\n')
    print(f"wrote {outdir}/desk.kicad_sch")


if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else ".")
