#!/bin/bash
# Export desk.kicad_pcb for the SLN shop milling pipeline.
#
#   ./export_for_mill.sh [outdir]      (default: ./gerbers)
#
# Settings come from docs/reference/shop-pcb-fabrication-guide.md §4 in
# sln-ha-config -- they are not defaults and not guesses:
#
#   Gerber : B.Cu + Edge.Cuts, mm, 4.6 precision, X2 OFF, netlist
#            attributes OFF, no drawing sheet, NO mirror (pipeline owns it)
#   Drill  : Excellon, INCH, decimal, absolute origin, minimal header off,
#            mirror off, PTH and NPTH in ONE merged file
#
# The merged drill file is non-negotiable: KiCad's own tooltip advises
# splitting them, but that advice targets board houses. pcbmill verify
# check 0 rejects split PTH/NPTH pairs.
#
# No silkscreen or mask layers are exported. Milled boards get their legend
# lasered on the F1 Ultra afterward, and there is no mask gerber at all.
set -euo pipefail

CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
HERE="$(cd "$(dirname "$0")" && pwd)"
PCB="$HERE/desk.kicad_pcb"
OUT="${1:-$HERE/gerbers}"

if pgrep -qi kicad; then
    echo "WARNING: KiCad is running."
    echo "  The shop guide's rule is: never write to the project dir while"
    echo "  KiCad has it open. Exporting reads only, but save first or the"
    echo "  export will lag what is on screen."
    echo
fi

mkdir -p "$OUT"

# Gate: never cut a board that has not passed DRC.
if ! "$CLI" pcb drc --exit-code-violations -o "$OUT/drc.rpt" "$PCB" >/dev/null 2>&1; then
    echo "DRC FAILED - see $OUT/drc.rpt"
    grep -oE "^\[[a-z_]+\]" "$OUT/drc.rpt" | sort | uniq -c
    exit 1
fi
echo "DRC clean"

"$CLI" pcb export gerbers \
    --output "$OUT/" \
    --layers B.Cu,Edge.Cuts \
    --no-protel-ext \
    --no-x2 \
    --no-netlist \
    --precision 6 \
    --exclude-value \
    "$PCB" >/dev/null
echo "gerbers -> $OUT  (B.Cu, Edge.Cuts, 4.6, X2 off, no netlist attrs)"

# Front legend for the F1 Ultra. NOT part of the milling job -- pcbmill is
# handed B.Cu / Edge.Cuts / drill explicitly, so this file just sits here
# until laser time. Components mount on the bare top face, so the placement
# legend belongs on F.Silkscreen.
"$CLI" pcb export gerbers \
    --output "$OUT/" \
    --layers F.Silkscreen \
    --no-protel-ext \
    --no-x2 \
    --no-netlist \
    --precision 6 \
    "$PCB" >/dev/null
"$CLI" pcb export svg \
    --output "$OUT/silkscreen.svg" \
    --layers F.Silkscreen \
    --page-size-mode 2 \
    --exclude-drawing-sheet \
    "$PCB" >/dev/null 2>&1 || true
echo "legend  -> $OUT  (F.Silkscreen gerber + SVG for xTool)"

"$CLI" pcb export drill \
    --output "$OUT/" \
    --format excellon \
    --drill-origin absolute \
    --excellon-units in \
    --excellon-zeros-format decimal \
    --generate-map --map-format pdf \
    "$PCB" >/dev/null
echo "drill   -> $OUT  (merged PTH+NPTH, inch, decimal, absolute)"

# Confirm the merge actually happened -- pcbmill rejects split files.
if ls "$OUT"/*-PTH.drl >/dev/null 2>&1 || ls "$OUT"/*-NPTH.drl >/dev/null 2>&1; then
    echo
    echo "ERROR: drill files came out SPLIT (PTH/NPTH). pcbmill will reject"
    echo "these. Do not proceed."
    exit 1
fi
if ! grep -qi "MixedPlating\|;TYPE=PLATED" "$OUT"/*.drl 2>/dev/null; then
    echo
    echo "NOTE: could not confirm MixedPlating in the drill header - check"
    echo "     'pcbmill verify' check 0 before cutting."
fi

echo
ls -1 "$OUT" | sed 's/^/  /'
cat <<EOF

next:
  pcbmill new deskv1 --back $OUT/desk-B_Cu.gbr \\
      --drill $OUT/desk.drl --pcb $PCB
  pcbmill consolidate                       # drill->bit + 0.25mm annulus gate
  pcbmill set cam.isolation_width 0.030
  pcbmill set blank.x0 <DRO X>              # blank lower-left, G54 inches
  pcbmill set blank.y0 <DRO Y>
  pcbmill set blank.width <in>
  pcbmill set blank.height <in>
  pcbmill solve-offsets                     # places the job BY MEASUREMENT
  pcbmill probe-gen ; pcbmill probe-import probe-results.ngc ; pcbmill touchoff
  pcbmill regen && pcbmill verify && pcbmill runsheet

  DO NOT use 'pcbmill frame 4.3372 3.2478'. Those MX/MY are per-board --
  they encode one board's page position AND one blank placement. On this
  board (Edge.Cuts at 100-194mm, not near page origin) they put the job at
  negative Y, entirely off the fixture. Use solve-offsets, which never
  touches MX/MY. See docs/reference/pcbmill-frame-mxmy-ANSWER.md.

  'verify' check 1 (extents vs blank/probe map) is the gate that catches a
  placement error. 'frame --verify' only proves frame stability, not
  correctness.
EOF
