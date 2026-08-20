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

You do not need 9-bit UART support to read this bus — a plain **8N1** UART at
1000 baud recovers every payload byte intact. But how the packet arrives
depends on how the UART handles framing errors, and real ESP32 silicon
differs from the obvious simulation:

- A UART that **discards** error bytes and resyncs bit-by-bit (what a naive
  software decoder does) sees the header mis-frame into a constant `0xFE`
  sync marker followed by the height byte.
- The **ESP32 keeps** framing-error bytes (verified on an ESP32-WROOM-32,
  ESP-IDF 5.5). Packets arrive as `00 7F <payload>`: the header comes through
  verbatim as `0x7F`, each framing error also emits a `0x00` artifact, and
  the payload byte is unmangled.

Either way the sync-then-payload structure survives. On the ESP32: skip
`0x00`, treat `0x7F` as "next byte is payload".

Filtering the handshake burst is easy thanks to an accident of the encoding:
**real heights are always odd bytes** (`245 - 2*inches`), and the handshake
constants are even or outside the travel range — except `0x0BF`, which
aliases a true 27.0 in reading. Its tell is timing: as a handshake word it
arrives within ~400 ms of the others, as a real height it arrives alone, so
reject `0xBF` seen within 600 ms of other handshake traffic. The working
lambda is in `desk.yaml`.

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

![The tap: a 7-pin DIN extension cut in half, each conductor landed in a
WAGO 221 lever nut with a pigtail out to the logic analyzer](docs/tap.jpeg)

Nothing is soldered and nothing on the desk is modified — the box and the
original panel each keep their own connector, and the lever nuts sit in
between. Pull the two halves and the desk is stock again.

![The injection rig: a cheap male-female 7-pin DIN extension cut in half, both
halves landed in WAGO 221 lever nuts. Male end to the control box, female end
to the original handset.](docs/injection-rig.jpeg)

**This rig is the whole trick, and it generalises.** It is a $10 extension
cable, not the desk's harness. Cutting it gives you seven conductors broken out
into lever nuts, which is simultaneously a **probe point** for the logic
analyzer and an **injection point** for the ESP32 — read the bus and drive it
without ever putting a knife near the cable that came with the machine. Get it
wrong, unplug two connectors, and the desk has never been touched. Any bus
that runs through a detachable cable can be attacked this way.

![The finished board wired to the rig on the bench, before install. The
wire-colour legend along each terminal block matches the DIN conductor
colours.](docs/board-and-rig.jpeg)

The board keeps the same idea: J1 and J4 are wired straight through, so the
control box and the original handset each land on their own terminal block and
the ESP32 sits across the pair. The panel goes on working exactly as before.

### The cable shield is left floating — on purpose

The handset cable is seven conductors **plus a shield**, and the shield is not
grounded here. That is deliberate, and it is worth stating plainly because the
instinct on seeing an ungrounded shield is that somebody forgot.

**It is not grounded in the desk's own wiring.** The two halves of the tap have
their drains joined to each other, so the shield stays electrically continuous
end to end exactly as it was before the cable was cut — and it terminates
nowhere, exactly as it did before.

Why not "improve" it: **the whole design goal is that the control box cannot
tell the difference.** Everything else here is built that way — the original
panel keeps working, the box keeps its own connector, nothing is soldered to
the desk. Bonding the shield to logic ground would be a change to a mains-fed
system whose internal grounding we cannot see, in exchange for a benefit
nothing has demonstrated a need for. If the box grounds the shield at its end,
adding a second bond creates a loop.

No idea *why* LOGICDATA left it floating. Matching what the manufacturer did is
the conservative choice when you do not know the reason.

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
  enforced in firmware, don't remove it; Drive Budget and Budget Recovery
  sensors expose how much motion is left before lockout. The budget persists
  across reboots (and credits real elapsed time while powered off), so an OTA
  can't hand you a fresh one. A diagnostic **Reset Duty Budget** button exists
  for bench work — deliberate operator action only, never automate it
- stall detection (no height change while driving → stop)
- a template **cover** face (0% = bottom of travel, 100% = top) so voice
  assistants can drive it with built-in position intents — no custom
  sentences required, and it provides a voice "stop"

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
