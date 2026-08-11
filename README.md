# deskhack

Home Assistant control and height readback for an **ErgoSwiss hydraulic standing
desk** running a **LOGICDATA COMPACT-e-3-VAL-ES-US** control box ("Compact-3-eco",
software V290) — without buying the vendor Memory handset, and without opening
either sealed box.

The desk shipped with a dumb up/down panel: no presets, no display. This project
taps the 7-pin DIN handset cable inline, drives the button lines from an ESP32
through optocouplers, and reads the desk's height from a previously undocumented
serial broadcast the control box sends on one of the handset pins. The original
panel keeps working in parallel.

As far as I can tell this is the first public decode of the COMPACT-e-**3**
handset bus. The well-known reverse-engineering projects
([RoboDesk](https://github.com/phord/RoboDesk),
[logicdata-standing-desk](https://github.com/DanielHabenicht/logicdata-standing-desk))
target the COMPACT-e-2L, whose framing differs in an important way (see below).

## The protocol

Everything below was measured on real hardware with a $12 FX2LP logic analyzer
and `sigrok-cli`; nothing is copied from other models' documentation.

### Physical

7-pin DIN (DIN 45329 family) between handset and control box. Wire colours in
the cheap extension cable used for the tap:

| wire   | function                                              |
|--------|-------------------------------------------------------|
| brown  | GND                                                   |
| red    | +5V supply to handset                                 |
| white  | HS line — assert **high** to drive **UP**             |
| yellow | HS line — assert **high** to drive **DOWN**           |
| green  | HS line, unused by the basic panel (memory functions) |
| blue   | HS line, unused by the basic panel (memory functions) |
| black  | serial data **out of** the box, idles high            |

Button lines are **active-high** and high-impedance: the box's inputs are
sensitive enough that a multimeter in ohms mode will command motion (ask me how
I know). A dumb panel is nothing but switches connecting HS lines to the +5V
rail.

### Serial framing

The data line is **1000 baud, 9 data bits, no parity, 1 stop, LSB-first** — a
classic 9-bit multi-drop bus. Community docs for the COMPACT-e-2L describe
"1000 baud with even parity"; on this box that is a misread of the 9th data
bit. The framing here was solved by constraint propagation over the raw bit
runs (every 0 must sit inside a frame; see `dataline.py` and `messages.py`),
not assumed.

Packets are two 9-bit words, sent only **when the displayed height changes**
(one packet per inch of travel) plus a fixed handshake burst at the start of
any button press. Packet: `0x07F` header, then the payload word.

### Height

```
height_inches = (245 - (payload & 0xFF)) / 2
```

Verified against a tape measure at four points across the full travel
(69–96 cm on this desk, 27.0–38.0 in): every reading within 0.5 cm. The box
counts pump-motor Hall pulses internally, so this is the same position the
controller itself acts on.

### The 8N1 trick

You do not need 9-bit UART support to read this bus. In a plain **8N1** UART at
1000 baud, the 9th data bit of the payload word lands where the stop bit is
expected — and it happens to be 1 for every height word, so the frame
validates. The `0x07F` header mis-frames into a constant **`0xFE`**, which
serves as a free sync marker. Each height report therefore arrives at an
ordinary UART as:

```
0xFE <height byte>
```

Handshake words have the 9th bit clear, fail the fake stop bit, and are
discarded by the UART hardware for you. One survivor (`0xFE 0x80` → "58.5 in")
is rejected by range-gating to the desk's physical travel.

## Hardware

Eight components, all through-hole:

- 2 × PC817 optocoupler (or CPC1017N photoMOS) — GPIO drives the LED through
  330 Ω; the output side connects a button line to the +5V rail, exactly as a
  finger on the panel does
- 2 × 100 kΩ bleed, opto emitter → GND, so leakage can't float the
  high-impedance inputs
- 3 × 22 kΩ — divider (22k : 44k) dropping the 5 V data line to 3.3 V for the
  ESP32's RX
- ESP32 dev board on its own USB supply, grounds tied at the DIN cable

The tap itself is a male-female 7-pin DIN extension cable cut in half and
landed on lever nuts, so the whole thing unplugs back to stock in seconds.

`kicad/` contains a KiCad 10 project (ERC-clean, footprints assigned) with the
interface circuit and a 30-pin ESP32 DevKit V1 socket, ready for board layout.
The schematic is *generated* — edit `kicad/gen_sch.py` and rerun rather than
editing the sheet, or retire the generator once you start hand-routing.

## Firmware

`desk.yaml` is a complete ESPHome configuration:

- height sensor via the 8N1 trick (hardware UART, zero protocol code)
- target-height number entity + sit/stand/stop buttons for Home Assistant
- bang-bang seek loop (feedback is 1-inch granular; there is nothing finer to
  chase)
- **duty-cycle watchdog** — the box is rated 2 min on / 18 min off and this is
  enforced in firmware, don't remove it
- stall detection (no height change while driving → stop)

Copy `wifi.yaml.example` to `wifi.yaml` first.

## Analysis tools

Everything runs on a capture exported to CSV
(`sigrok-cli -i cap.sr -O csv > cap.csv`):

| tool                   | what it does                                                                    |
|------------------------|---------------------------------------------------------------------------------|
| `probe.py`             | per-channel characterization: idle level, edges, implied baud from narrowest pulse |
| `timeline.py`          | button lines as a deglitched state timeline                                     |
| `dataline.py`          | bit-time histogram and exhaustive UART framing search                           |
| `messages.py`          | packet segmentation + solved 9N1 decode — the useful one                        |
| `viewer.py`            | renders a capture as a self-contained interactive HTML waveform viewer          |
| `make_test_capture.py` | synthetic capture for self-testing the toolchain                                |

## Safety notes

- The control box is mains-fed and sealed. Nothing here requires opening it,
  and you shouldn't.
- Disconnect mains before plugging/unplugging anything on the handset cable —
  the box enters a re-commissioning state (down-only until re-homed) if the
  handset connection glitches while powered.
- Respect the 2/18 duty cycle. A "nudge every N minutes" automation will
  overheat the box; preset seeks lasting seconds are fine.
- If the box loses its reference: drive to the bottom, hold both panel buttons
  5 s, drive to the top, hold both 5 s (the §4.2 commissioning procedure — it
  works with a plain up/down panel).

## Applies to

Verified on: ErgoSwiss "Steuerung Compact-3-eco 110V V290" (P/N 124.30290),
LOGICDATA type `COMPACT-e-3-VAL-ES-US`, revision 3/1.9.14, US 120 V. The VAL
firmware is hydraulic-specific ("only for hydraulic lift system — modified
parameters"). Other COMPACT-e-3 variants likely match; measure before you
trust — `probe.py` will tell you in one capture.

## License

MIT. If this saved you a €63 handset or an afternoon with a logic analyzer,
pay it forward.
