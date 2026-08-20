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
#
# ERRORS block. WARNINGS are printed in full every run but do not block.
#
# The split matters both ways. Since the legend became a lasered output, a silk
# warning is the difference between a readable board and an illegible one, so
# warnings must never be silently suppressed -- that is how four overlapping
# refdes reached the laser once already. But a warning the operator has looked
# at and accepted (geometry that cannot be resolved, e.g. a value field boxed in
# by its own footprint outline) would otherwise block the export permanently.
#
# KiCad's own Exclude is the way to retire a warning for good, but its key
# includes the marker coordinate, so an exclusion silently stops matching if the
# item is ever nudged. Printing warnings every run is the more durable check.
"$CLI" pcb drc --severity-all -o "$OUT/drc.rpt" "$PCB" >/dev/null 2>&1 || true

if ! "$CLI" pcb drc --severity-error --exit-code-violations \
        -o "$OUT/drc-errors.rpt" "$PCB" >/dev/null 2>&1; then
    echo "DRC FAILED - errors present, see $OUT/drc-errors.rpt"
    grep -oE "^\[[a-z_]+\]" "$OUT/drc-errors.rpt" | sort | uniq -c
    exit 1
fi

# List warnings, but skip ones already excluded in KiCad -- an exclusion is a
# decision already made, and re-reporting it every run trains you to skim past
# the list, which defeats the point of printing it at all.
_live=$(awk '/^\[[a-z_]+\]/{hdr=$0; getline nxt;
             if (nxt !~ /\(excluded\)/) print "    " hdr}' "$OUT/drc.rpt")
_excl=$(grep -c '(excluded)' "$OUT/drc.rpt" 2>/dev/null || true)
_excl=${_excl:-0}

if [ -n "$_live" ]; then
    echo "DRC: 0 errors, warnings NOT blocking - review before lasering:"
    echo "$_live"
    echo "    full report: $OUT/drc.rpt"
else
    echo "DRC clean (0 errors, 0 unexcluded warnings)"
fi
if [ "$_excl" -gt 0 ]; then
    echo "        ($_excl excluded violation(s) suppressed)"
fi

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

# ---------------------------------------------------------------------------
# Laser artwork for the F1 Ultra. NOT part of the milling job -- pcbmill is
# handed B.Cu / Edge.Cuts / drill explicitly, so these files just sit here
# until laser time. There are TWO jobs, on OPPOSITE faces of the board:
#
#   legend -> F.Silkscreen -> component face (white painted)   NOT mirrored
#   mask   -> B.Mask       -> copper face (cured UV mask)      MIRRORED
#
# THE MIRROR IS THE TRAP. KiCad plots every layer top-down, so an unmirrored
# B.Mask is the copper side seen THROUGH the board. Laser that onto a board
# sitting copper-up and every opening lands mirrored about the board centre --
# the SVG looks correct in a viewer and nothing downstream checks it.
#
# Note this is the OPPOSITE of the milling gerbers above, which are
# deliberately NOT mirrored because pcbmill owns that mirror. Two exports from
# one board with opposite mirror settings is exactly how this gets fumbled,
# which is why the guard below exists.
#
# Both SVGs use --page-size-mode 2 (board area only) so the two jobs share one
# crop and register to each other under the F1 Ultra camera.

"$CLI" pcb export gerbers \
    --output "$OUT/" \
    --layers F.Silkscreen \
    --no-protel-ext \
    --no-x2 \
    --no-netlist \
    --precision 6 \
    "$PCB" >/dev/null

# Legend -> component face. Front layer, NO mirror.
"$CLI" pcb export svg \
    --output "$OUT/silkscreen.svg" \
    --layers F.Silkscreen \
    --mode-single \
    --page-size-mode 2 \
    --exclude-drawing-sheet \
    "$PCB" >/dev/null
echo "legend  -> $OUT/silkscreen.svg  (F.Silkscreen, NOT mirrored)"

# Mask openings -> copper face. Back layer, MIRROR REQUIRED.
# --negative is deliberately NOT used: KiCad's B.Mask already draws the
# openings as filled shapes, which is exactly what the laser should ablate.
#
# --drill-shape-opt 0 suppresses the drill-hole circles. They default to
# "actual shape" and get plotted as filled shapes INSIDE each opening, so the
# laser runs its full pass count again over the hole rim -- the thinnest, least
# heat-sunk copper on the pad. On deskhack V1 that contributed to burning three
# pads clean off at 60% / 9 passes. The holes are drilled after masking anyway,
# so there is nothing there to clear.
"$CLI" pcb export svg \
    --output "$OUT/soldermask.svg" \
    --layers B.Mask \
    --mirror \
    --drill-shape-opt 0 \
    --mode-single \
    --page-size-mode 2 \
    --exclude-drawing-sheet \
    "$PCB" >/dev/null
echo "mask    -> $OUT/soldermask.svg  (B.Mask, MIRRORED)"

# Guard: prove --mirror actually took effect rather than trusting that the
# flag is still spelled the same. Export the same layer unmirrored and require
# the two to differ. If a future kicad-cli drops or renames --mirror, this
# fails here instead of at the laser.
_unmir="$(mktemp -t bmask_unmirrored).svg"
"$CLI" pcb export svg \
    --output "$_unmir" \
    --layers B.Mask \
    --drill-shape-opt 0 \
    --mode-single \
    --page-size-mode 2 \
    --exclude-drawing-sheet \
    "$PCB" >/dev/null
if cmp -s "$OUT/soldermask.svg" "$_unmir"; then
    rm -f "$_unmir"
    echo
    echo "ERROR: mirrored and unmirrored B.Mask exports are IDENTICAL."
    echo "  --mirror had no effect. Do NOT laser soldermask.svg -- every"
    echo "  opening would land mirrored about the board centre."
    echo "  Check 'kicad-cli pcb export svg --help' for the current flag."
    exit 1
fi
rm -f "$_unmir"
echo "        mirror verified (mirrored != unmirrored)"

# Guard: an empty B.Mask means no openings were plotted at all.
if [ ! -s "$OUT/soldermask.svg" ] || ! grep -qE '<path|<circle|<rect|<polygon' "$OUT/soldermask.svg"; then
    echo
    echo "ERROR: soldermask.svg contains no geometry. Every pad should"
    echo "produce an opening -- check that B.Mask is not empty."
    exit 1
fi

# ---------------------------------------------------------------------------
# LEGEND RASTER -- this, not silkscreen.svg, is what goes to the laser.
#
# WHY: KiCad writes stroke-font text to SVG as ~1700 separate TWO-POINT open
# polylines carrying a stroke-width (median segment 0.14 mm). Creative Space
# converts each segment into its own outline, so the legend imports as hollow,
# crossed, apparently-doubled letters needing hours of hand cleanup. The file
# is not corrupt -- the geometry is correct and contains zero duplicate paths.
# It is the stroke-vs-fill interpretation that is wrong, so cleaning the SVG
# cannot fix it. gerbv's SVG export has the identical shape (fill="none" +
# stroke) and is no better.
#
# A raster sidesteps it completely and costs nothing: profile B is a raster
# engrave already (200 lines/cm bi-directional = 508 lines/inch), so the laser
# rasterises either way. 1200 dpi is >2x what the engrave resolves.
#
# soldermask.svg stays a VECTOR -- pads export as filled polygons, no fill:none
# anywhere in it, so it imports correctly as-is.
#
# The canvas is forced to the Edge.Cuts extents instead of gerbv's default
# crop-to-artwork, so the PNG maps 1:1 onto the board and registers against
# soldermask.svg. Import it and set its size to exactly the mm printed below.

if ! command -v gerbv >/dev/null 2>&1; then
    echo
    echo "ERROR: gerbv not found (brew install gerbv). Needed to raster the"
    echo "legend -- do NOT fall back to silkscreen.svg, see comment above."
    exit 1
fi

DPI=1200
# Board extents from Edge.Cuts, in inches. Skip '%' lines so the format spec
# (%FSLAX46Y46*%) is not mistaken for a coordinate -- it matches X46Y46.
_dims=$(python3 - "$OUT/desk-Edge_Cuts.gbr" <<'PY'
import re, sys
xs=[]; ys=[]
for line in open(sys.argv[1]):
    if line.startswith('%'):
        continue
    m = re.search(r'X(-?\d+)Y(-?\d+)', line)
    if m:
        xs.append(int(m.group(1))/1e6); ys.append(int(m.group(2))/1e6)
# gerbv's --origin/--window_inch parser REJECTS long floats with
# "Specified origin is not recognized", so these must be rounded. 5 decimal
# inches is 0.25 um -- far below anything that matters here.
print(f"{min(xs)/25.4:.5f} {min(ys)/25.4:.5f} "
      f"{(max(xs)-min(xs))/25.4:.5f} {(max(ys)-min(ys))/25.4:.5f}")
PY
)
read -r _ox _oy _w _h <<< "$_dims"

# gerbv returns non-zero even on a successful headless export, so its exit code
# is deliberately ignored -- the dimension check below is the real gate, and it
# verifies the artifact rather than the invocation.
rm -f "$OUT/silkscreen_${DPI}dpi.png"
gerbv --export=png --output="$OUT/silkscreen_${DPI}dpi.png" \
      --border=0 \
      --origin="${_ox}x${_oy}" --window_inch="${_w}x${_h}" \
      --dpi="$DPI" --background=#FFFFFF --foreground=#000000FF \
      "$OUT/desk-F_Silkscreen.gbr" >/dev/null 2>&1 || true

if [ ! -s "$OUT/silkscreen_${DPI}dpi.png" ]; then
    echo
    echo "ERROR: gerbv produced no legend raster."
    exit 1
fi

# gerbv writes 8-bit RGB with NO pHYs chunk, i.e. no physical size. An importer
# with no DPI to go on assumes 72 or 96 dpi, so a 4440 px image arrives about
# 1.5 METRES wide -- this is why the raster looked "not to scale". Stamp the
# real DPI in and drop to greyscale (pure black/white line art does not need
# three colour channels).
#
# 1-BIT, NOT greyscale. This matters more than it looks. A greyscale raster makes
# the laser MODULATE POWER per pixel, so gerbv's antialiased edge pixels would
# fire at partial power and the importer may halftone -- neither of which the
# shop's validated profile B was ever tested against. 1-bit removes the variable
# entirely: every pixel is either "fire at profile power" or "do not fire",
# exactly like a vector fill.
#
# Profile B's settings therefore carry over unchanged, because that profile is a
# raster engrave already (200 lines/cm = 508 lines/inch, bi-directional). Even
# fed vectors, Creative Space rasterises to scan lines internally. At 1200 dpi
# the image is >2x finer than the machine scans, so thresholding costs nothing
# real: a 0.15 mm stroke is 7 px wide here, and the threshold moves an edge by at
# most half a pixel (0.01 mm).
#
# The threshold must be applied with dither=NONE -- PIL's convert("1") defaults
# to Floyd-Steinberg, which would stipple every stroke.
#
# The white background is deliberate and should NOT be made transparent. White
# does not fire the laser, and the opaque board-sized rectangle is what gives
# the object its exact extents for camera registration -- crop it to the ink and
# that reference is gone.
python3 - "$OUT/silkscreen_${DPI}dpi.png" "$DPI" <<'PY'
import sys
try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow not installed (pip3 install Pillow). Needed to "
             "stamp DPI into the legend raster, without which it imports at "
             "the wrong physical size.")
png, dpi = sys.argv[1], int(sys.argv[2])
im = Image.open(png).convert("L")
im = im.convert("1", dither=Image.Dither.NONE)   # hard threshold, no halftone
im.save(png, dpi=(dpi, dpi), optimize=True)

# Also emit a TRANSPARENT-background copy. The opaque white version hides the
# camera view of the board, so you can only align its bounding box against an
# eyeballed board edge. With white knocked out you can see the drilled holes
# through the artwork and align to those instead -- they are in the same
# coordinate frame as the silk, so that is a direct registration rather than an
# inferred one, and it costs nothing.
#
# The CANVAS STAYS BOARD-SIZED -- white is made transparent, the image is NOT
# cropped to the ink. Cropping would throw away the extents that make the
# object's bounding box equal the board.
#
# Alpha is binary (source is 1-bit), and the visible pixels stay pure black, so
# this does not reintroduce the power modulation that greyscale would.
#
# VALIDATED 2026-08-14 on deskhack V1 -- Creative Space honours the alpha and
# the transparent file is the better one to place: you can see the drilled holes
# and terminals through the artwork and align to them directly. Prefer it.
# The opaque file is kept as a fallback in case a future importer ignores alpha
# and renders transparent as BLACK, which would engrave the whole background;
# the preview makes that failure obvious immediately.
mask = im.convert("L").point(lambda v: 255 if v < 128 else 0)   # ink -> opaque
rgba = Image.merge("LA", [Image.new("L", im.size, 0), mask])
alpha_path = png.replace(".png", "_transparent.png")
rgba.save(alpha_path, dpi=(dpi, dpi), optimize=True)

# Prove it really is two-tone -- a stray intermediate value means the laser
# would modulate power somewhere the profile was never tested at.
vals = {v for v, n in zip(range(256), im.convert("L").histogram()) if n}
if not vals <= {0, 255}:
    sys.exit(f"ERROR: raster is not pure black/white, found levels {sorted(vals)}")
PY

# Guard: the raster must come out board-sized, or it will not register against
# soldermask.svg. gerbv silently applies a 2% border if --border is dropped.
python3 - "$OUT/silkscreen_${DPI}dpi.png" "$DPI" "$_w" "$_h" <<'PY'
import struct, sys
png, dpi, w_in, h_in = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
d = open(png,'rb').read()
px, py = struct.unpack('>II', d[16:24])
mm_x, mm_y = px/dpi*25.4, py/dpi*25.4
want_x, want_y = w_in*25.4, h_in*25.4
if abs(mm_x-want_x) > 0.05 or abs(mm_y-want_y) > 0.05:
    sys.exit(f"ERROR: legend raster is {mm_x:.3f} x {mm_y:.3f} mm, expected "
             f"{want_x:.3f} x {want_y:.3f}. It will NOT register against the mask.")
print(f"legend  -> {png.rsplit('/',1)[-1]}  ({px} x {py} px @ {dpi:.0f} dpi"
      f" = {mm_x:.3f} x {mm_y:.3f} mm)  <-- SEND THIS TO THE LASER")
PY

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

laser (F1 Ultra, AFTER milling -- two jobs, opposite faces):
  soldermask.svg  -> copper face, over cured UV mask
                     Fiber IR / 50% / 800 mm/s / 6 passes / 200 lpc /
                     bi-directional / 30 kHz / cross hatch ON / angle 0 incr.
  silkscreen_1200dpi.png -> component face, over white rattle-can paint
                     (RASTER, not the SVG -- see comment in this script)
                     MEASURED 2026-08-14, deskhack V1:
                     Blue light / dot duration 100 us / power range 1-75% /
                     DPI 500 / Pass 1 / bitmap mode Grayscale /
                     bi-directional / thickness 0.126 in
                     (a bitmap object exposes dot duration + power RANGE + DPI,
                      not speed/power/lines-per-cm like a vector object.
                      Frequency is fiber-only and absent for blue light.)
                     Find the power that clears paint in ONE pass. Multi-pass at
                     marginal power dumped 2x the energy for a worse result.

  Registration for both is by F1 Ultra camera. Board is loose by this point.
  Do NOT carry the fiber settings across to the legend -- 6 passes would cut
  rather than mark it.
EOF
