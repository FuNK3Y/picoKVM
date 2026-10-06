# picoKVM board — ESP32-S3 USB 3.0 KVM switch with HDMI DDC/CI

Two PCs (USB 3.0 Type-B) share one peripheral port (USB 3.0 Type-A).  An
ESP32-S3 flips the USB path and tells both monitors to change input over
HDMI DDC/CI.  The HDMI ports carry DDC/+5V only — video goes straight
from the PCs to the monitors.  The firmware is the MicroPython code in
the repository root (see the main [README](../README.md)).

![picoKVM rev A](revA/img/iso.png)

## Rev A release (ordered 2026-10-03, JLCPCB)

`revA/` holds the board exactly as it was sent to JLCPCB.  Freerouting is not
deterministic, so **`revA/kvm_board.kicad_pcb` is the design of record**: a
fresh `./build.sh` produces an equivalent board, not the same copper.

| file | what |
|---|---|
| `revA/kvm_board.kicad_pcb` / `.kicad_pro` / `.kicad_dru` | routed board (KiCad 10), its net classes and JLC design rules |
| `revA/jlcpcb/gerbers.zip`, `bom.csv`, `cpl.csv` | the files uploaded to JLCPCB (126 × 75 mm customer panel) |
| `revA/schematic_review.html` | readable schematic: every pin, its net and what else is on it |
| `revA/mechanical.txt` | connector, LED and button positions for the enclosure |
| `revA/thermal_justification.md` | proof that every single-spoke GND pad reaches the In1 plane |
| `revA/impedance.txt` | field-solver results for the 90 Ω pairs on JLC04161H-3313 |
| `revA/img/` | renders (top, bottom, iso, panel) and the Grove J8 pinout |

JLC order settings: 4 layers, 1.6 mm, **specified stackup JLC04161H-3313**,
no impedance control (accepted risk for prototypes, see below), 0.3 mm vias,
1 oz outer / 0.5 oz inner, flying-probe test, Standard PCBA top side,
**edge rails added by customer**, confirm production file and parts placement.

To regenerate the order files from the released board without re-routing:

```
mkdir -p out && cp revA/kvm_board.kicad_* out/
./build.sh fab        # panel (hw/panel.py), Gerbers, PTH/NPTH drill, BOM, CPL -> out/jlcpcb/
```

## Build

```
./build.sh          # netlist + ERC, PCB, routing, DRC, renders, JLCPCB files (all in Docker)
./build.sh noroute  # same, stopping at the placed, unrouted board
./build.sh parts    # re-import the LCSC symbols/footprints/3D models
./build.sh shell    # shell inside the toolchain (KiCad 10 + SKiDL + easyeda2kicad)
```

Sources:

| file | what |
|---|---|
| `hw/kvm_board.py` | the schematic, as SKiDL code — edit this, not the netlist |
| `hw/make_pcb.py` | builds the 4-layer `.kicad_pcb`: placement, planes, net classes, JLC rules |
| `hw/route_ss.py` | hand-designed USB 3.0 SuperSpeed pairs (coupled, matched, no vias) |
| `hw/route_usb2.py` | hand-designed USB 2.0 pairs (coupled, matched, symmetric via pairs) |
| `hw/finish.py` | power neck-downs + plane fanout before routing; GND stitching after |
| `hw/route.py` | Freerouting round-trip (Specctra DSN/SES) for everything else |
| `hw/impedance.py` | 2-D field solver for the 90 Ω pairs on the JLC 3313 stackup |
| `hw/make_fab.py` | JLCPCB `bom.csv` / `cpl.csv` (CPL expressed in JLC's own footprint frame) |
| `hw/panel.py` | JLC assembly panel: rails, mouse bites, fiducials, tooling holes |
| `hw/thermal_report.py` | proves every single-spoke GND pad reaches the In1 plane |
| `hw/checks.py` | manufacturing checks beyond DRC, tuned to JLCDFM: vias near pads, SMD near through-hole pads, tracks near mask openings, USB 2 skew (`./build.sh checks`; part of every build) |
| `hw/review.py` | generates `schematic_review.html` |
| `hw/jlcref.py` | fetches JLC's footprints into `hw/lib/jlcref/` (used by `make_fab.py`) |
| `hw/lib/` | LCSC/EasyEDA imports; only the 3D models the board uses are committed (`./build.sh parts` re-fetches the rest, incl. STEP) |

Outputs in `out/`: `kvm_board.kicad_pro/.kicad_pcb` (open in KiCad 10),
`kvm_board.net`, `kvm_board.erc`, `drc.rpt`, `img/`, `jlcpcb/`,
`mechanical.txt` (positions for the case) and **`schematic_review.html`** —
the reviewable schematic: every chip and connector pin with its net and what
else is on it, grouped by function, plus a net index and automatic checks.

## Status

- [x] Circuit complete, ERC clean (0 errors / 0 warnings); D3 pin 3 (DOUT) is
      explicitly marked no-connect (single LED, no chain)
- [x] All parts in JLCPCB/LCSC stock (checked 2026-10-01); passives are basic parts
- [x] Placed and **fully routed**: DRC 0 errors, 0 unconnected.  Board:
      `out/drc.rpt`; JLC panel: `out/drc_panel.rpt`.  `min_resolved_spokes`
      is 1; every pad that would have a single outer-pour spoke is proven to
      reach the In1 GND plane independently in `out/thermal_justification.md`
- [x] 90 Ω pair geometry verified with a 2-D field solver (`hw/impedance.py`, see below)
- [ ] Human review of `out/schematic_review.html` (the schematic is code)
- [ ] Human review of the autorouted part in KiCad (DRC-clean and fully
      connected; not yet reviewed by eye)
- [x] Ordered from JLCPCB (5 assembled boards, rev A), files in `revA/`
- [ ] JLC production file and placement preview approved
- [ ] Prototype bring-up per the test plan below; DDC/CI with your monitors

`lib_footprint_issues` in `drc.rpt` only appears in the headless container
(no global library table) and can be ignored.  `lib_footprint_mismatch` on D3 is
intentional: the build replaces that EasyEDA footprint's open courtyard with a
closed rectangle and corrects its 3D-model offset (`hw/make_pcb.py`
`FIX_COURTYARD`, model offset in `hw/lib/lcsc.pretty`); its pads, numbering,
mask and paste are unchanged, and JLC's SMT check (its own C5378721 model on
our pads via the CPL) reports no pin-edge finding for D3.

### Toolchain

All versions are pinned (Dockerfile / `build.sh`): KiCad 10.0.6
(`kicad/kicad:10.0.6-full`), SKiDL 2.3.0, easyeda2kicad 1.0.1,
Freerouting 2.4.1 on `eclipse-temurin:25.0.4.1_1-jre`.

KiCad's Python bindings occasionally segfault in standalone scripts — on
both 9.0.9 and 10.0.6, mostly around zone filling.  Every script saves only
when its work is done and leaves via `os._exit(0)`, and `build.sh` retries
a crashed step (you'll see "crashed, retrying" in the log).  Routing results
vary slightly from run to run because Freerouting is not deterministic.

## How the board is routed

1. **USB 3.0 SuperSpeed** (`route_ss.py`): six pairs routed deliberately on
   F.Cu over the In1 GND plane — coupled 0.15/0.15 mm, 45° corners in
   cancelling pairs, intra-pair skew ≤ 0.1 mm, no vias, straight through
   the flow-through ESD parts.  Locked.
2. **USB 2.0** (`route_usb2.py`): the three switched pairs (USB A, USB B,
   peripheral) routed the same way — coupled 0.15/0.15 mm from connector to
   switch, D+/D− skew 0.000 mm (a 0.6 mm trombone on the peripheral pair
   cancels its one unbalanced 90° turn), symmetric via pairs where a pair
   changes layer (USB A: 0 vias, USB B: 4, peripheral: 6, i.e. 3 symmetric
   pairs; the B.Cu sections reference In2 (+3V3), the F.Cu ones In1 (GND)), straight through
   flow-through TPD4E05U06 ESD parts.  The TS3USB221A switch keeps each
   pair on adjacent pins, so pairs only separate for the last 0.1 mm into
   0.5 mm-pitch pads.  Locked.
3. **Pre-route** (`finish.py fanout`): every GND / +3V3 SMD pad gets a stub +
   via into its plane (In1 = GND, In2 = +3V3); fine-pitch power pins get
   neck-down stubs.  Locked.
4. **Everything else** (`route.py` + Freerouting 2.4.1 on Java 25):
   power, I²C, GPIO, aux USB-C (Full Speed only) on F.Cu/B.Cu.
5. **Stitching** (`finish.py stitch`): GND vias on a 4 mm grid tie the F/B
   pours to In1.

## Stackup and impedance

- **JLC04161H-3313**: L1 signal, L2 GND, L3 +3V3, L4 signal.  Select this
  stackup when ordering.  USB pairs on L4 (B.Cu) reference the L3 +3V3
  plane, AC-coupled to GND by the decoupling capacitors.
- Net class `USB_DIFF`: 0.15 mm track / 0.15 mm gap.  Verified with
  `hw/impedance.py`, a 2-D quasi-static field solver of the cross-section
  using JLC's published 3313 data (prepreg 0.0994 mm, Dk 4.1; solder mask
  1.2/0.6 mil, Dk 3.8; trapezoid etch W−0.025 mm; 0.04 mm finished copper).
  The solver matches Hammerstad-Jensen within 1.1–1.6 % on single
  microstrips.  Result (`out/impedance.txt`):
  - **Zdiff ≈ 90 Ω** with solder mask (99 Ω without), converging to ~89–90 Ω
  - every tolerance corner (Dk ±0.2, prepreg ±10 %, heavier etch, thinner
    copper, W or S ±0.02 mm) stays within **86–94 Ω**
- **Rev A is ordered without impedance control** (+$33): an accepted risk
  for 5 prototypes.  The stackup is specified, so the geometry gives the
  calculated ~90 Ω, but it is not measured or guaranteed by the fab; USB 3
  is validated on the prototypes.  For production, order impedance control,
  90 Ω differential on L1 referenced to L2.  JLC's own calculator (web only) is
  the final word; this is the same class of computation.
- ESP32 antenna: flush with the right edge, with a copper keep-out rule area
  under it on all four layers (no tracks, vias, pads or plane fill), extending
  2.5 mm past the module's sides.  Freerouting and the fanout/stitching steps
  respect it.

## Design decisions

- **No AC-coupling caps on the SuperSpeed lines.**  The PC and the device
  already AC-couple their transmitters, and the HD3SS3212 must be DC-biased
  from one side (datasheet SLASE74F §10.1).  Caps on the board would leave
  the switch floating.
- **TX/RX crossover:** PC SSRX (B pins 8/9) ↔ peripheral SSTX (A pins 8/9),
  PC SSTX (B 5/6) ↔ peripheral SSRX (A 5/6), via mux channels 0/1.
- **LM66100 CE is tied to VOUT**, not GND — that is what enables its
  reverse-current blocking, so USB A can't back-feed USB B.
- **TS3USB221A** (µQFN-10) as the USB 2.0 switch: unlike the TS3USB30E, its
  D+/D− pins are adjacent for every port, so the pairs stay coupled up to the
  pins.  S = L selects port 1 (USB A), same polarity as the HD3SS3212 and
  TPS2116, so one `USB_SEL` still drives all three.
- **USB 2.0 ESD**: TPD4E05U06 (the SuperSpeed ESD part, channel 1 only) in
  flow-through right after J1 and J2 and on the switch's common side, instead
  of USBLC6s off to the side: no stubs, 0.5 mm pitch.
- **HDMI +5V** (pin 18; HDMI asks 4.8–5.3 V): LM66100 ideal diode (~5 mV
  drop, blocks back-feed from the monitor) + 100 mA PTC.  Expect ~4.9 V from
  a 5.0 V PC port, ~4.5 V in the worst case (4.75 V port and a heavily
  loaded cable) — check on the prototype.
- **No added vias inside exposed pads**: the HD3SS3212's thermal pad joins
  its GND pins, which take vias outside the chip (no solder wicking, no
  filled vias needed).  The one exception is the ESP32-S3 module's own
  footprint (Espressif's land pattern), which has 0.3 mm thermal vias in its
  centre GND pad by design.
- Peripheral VBUS: the TPS2116 picks the source and follows `USB_SEL`
  (its PR1 pin), so power always comes from the PC whose data is selected.
  A TPS2553 after it switches the port on/off and limits it to 1.2–1.38 A
  (R_ILIM 20 kΩ) with a fault flag — one GPIO each, no pin combinations to
  get wrong.  The board itself is powered by whichever of USB A / USB B / AUX
  is present.

## Decoupling (per TI datasheets)

- U4 TPS2116: 1 µF on each VIN at the IC (C4 VBUS_A, C5 VBUS_B; datasheet
  9.2 / 10.1); C6 100 nF on VOUT (≥ 0.1 µF for soft start, 7.3.2), which is
  also U20's input capacitor (TPS2553: 0.1 µF next to IN).
- U6 / U7 LM66100: 1 µF on each VIN (C23, C24) and 10 µF on +5V_SYS between
  them (C25), datasheet 10.2 / 11.1.  U8 (AUX) has C10 / C11 beside it.
- Peripheral port after U20: 2 × 22 µF + 100 nF at J3.

## Prototype test plan (rev A)

USB host ports are specified for 0.9 A (USB 3) but their actual trip point
is not a design limit, so rev A is validated inside this envelope:

- **Base envelope:** nothing connected to J7/J9; HDMI +5 V, Grove and LEDs
  count in the measured board current.  Assume one PC port supplies both the
  board and the peripheral (the AUX input does not guarantee a favourable
  split).
- **Peripheral current:** 0.5 A minus whatever the measured board current
  exceeds 0.35 A, on a USB 3 host port (0.9 A budget); higher loads, and the
  test at the U20 limit (1.2–1.38 A), only from a source known to supply
  them (bench supply or powered hub).
- **Measure:** source VBUS, VBUS at J3 and the drop between them, at 0.5 A
  and (on a capable source) at the U20 limit — judge J3 against what the
  peripheral needs, not a fixed number; temperature of U4, U20 and the VBUS
  tracks with a thermal camera or thermocouple after 10 min at load.
- **Switchover:** scope +5V_SYS and VBUS_PERIPH while toggling USB_SEL with a
  load on J3.
- **Inrush at plug-in:** +5V_SYS carries ~21 µF (C11, C12, C25) charged
  through U6/U7/U8 with no current limit; scope VBUS at plug-in on A, B and
  AUX separately, and plug them one after another, on a protected source.
- **U5 AP2112K:** temperature with Wi-Fi active continuously (expected
  ~0.1 A average, ~0.17 W).
- **Grove short:** short GROVE_5V to GND; F4 (100 mA PTC) trips in seconds,
  not instantly — check that +5V_SYS and the ESP32 stay up, and that F4
  recovers.
- **HDMI +5 V:** voltage at J5/J6 pin 18 with each monitor (spec 4.8–5.3 V).
- **USB 3 / USB 2:** throughput with a real SuperSpeed device and a
  High-Speed device on each PC; DDC/CI with each monitor.

## Firmware contract

Implemented by the firmware in the repository root (`config.example.json` uses
these pins).

| GPIO | function |
|---|---|
| 1 / 2 | HDMI 1 DDC SDA / SCL (I2C0) |
| 4 / 5 | HDMI 2 DDC SDA / SCL (I2C1) |
| 6 / 7 | spare (not broken out; HDMI hot-plug detect is deliberately not wired: DDC/CI needs only SDA/SCL + 5 V, and a monitor can be found by probing I2C 0x50) |
| 8 | `USB_SEL` — low = USB A, high = USB B: USB 3 + USB 2 data **and** peripheral power source |
| 9 | `USB_OE_N` — low = data muxes on (pulled up: off at reset) |
| 10 | `PERIPH_EN` — high = peripheral power on (pulled down: off at reset) |
| 16 | `PERIPH_FAULT_N` — input, low = peripheral over-current / over-temperature |
| 11 / 12 | USB A / USB B VBUS present (10k/15k divider: 5 V → 3.0 V, max 3.3 V at an out-of-spec 5.5 V) |
| 13 | PC-switch button, active low: on-board SW3 **and** Grove J8 key, M5 white wire |
| 14 | on-board status LED data (SK6812 RGB, GRB order, 800 kHz) — set the colour per selected PC |
| 15 | spare (not broken out) |
| 19 / 20 | native USB (aux USB-C) |
| 17 | remote button RGB LED data (SK6812), Grove J8 LED, M5 yellow wire |
| 43 / 44 | UART0 on J7 (GND, TX, RX, 3V3) |
| 18, 21, 35–42, 47, 48 | spare, on J9 |

### Connectors for the box

- **J8 — Grove (HY2.0-4P), left edge, centred — M5Stack pinout:**
  looking into the socket from outside, latch window on top, left to right:
  GND, **5 V** (via 100 mA PTC), LED data (GPIO17, SK6812/NeoPixel), key
  (GPIO13, active low, 10k pull-up on board).  On an M5Stack cable that is
  black, red, yellow, white -- verified against a real Unit Key.  (The
  footprint's pad 1 is GND; Seeed cables use other colours.)
  100 Ω series resistors on both signals.  Made for the M5Stack Unit Key
  (mechanical key + RGB LED): it plugs straight in.  Avoid Seeed Grove
  modules that pull their signal up to VCC — they would put 5 V on an ESP32
  pin.
- **J9 — 2×8 header, 2.54 mm (assembled, C68234):**

  Even pins are the row nearest the ESP32, in module-pin order, so the
  fan-out is straight:

  | pin | signal | pin | signal |
  |---|---|---|---|
  | 1 | GPIO48 | 2 | GPIO35 |
  | 3 | GPIO47 | 4 | GPIO36 |
  | 5 | GPIO21 | 6 | GPIO37 |
  | 7 | GPIO18 | 8 | GPIO38 |
  | 9 | GND | 10 | GPIO39 |
  | 11 | 3V3 | 12 | GPIO40 |
  | 13 | 5V (5V_SYS) | 14 | GPIO41 |
  | 15 | GND | 16 | GPIO42 |

  The module is the **N8R2** (8 MB flash, 2 MB quad PSRAM).  GPIO35–37 are
  free only because its PSRAM is quad SPI — don't substitute an octal-PSRAM
  module (N8R8, N16R8…), which uses those pins internally.  In MicroPython
  use the plain ESP32_GENERIC_S3 build: it detects the quad PSRAM at boot (the
  `SPIRAM_OCT` build is for octal PSRAM and won't start it).  GPIO39–42 are also the JTAG pins (usable as
  normal GPIO; JTAG is over USB on the S3).  The 5V pin is the board's
  internal rail (ideal-diode OR of the USB inputs) — keep loads small.
- **J7 — UART header (assembled, C32713270):** GND, TX, RX, 3V3.

### Mechanical (for the enclosure)

- Board 112 × 75 mm, plain rectangle; the edge connectors protrude past it by
  up to 1.5 mm (see `out/mechanical.txt`).  The ESP32
  antenna is at the right edge, y 31–49: keep metal, screws and conductive
  filament ≥ 5 mm away from it; plain PLA/PETG walls are fine.
- Four M3 holes, 4 mm in from each corner; nothing within Ø8 mm of them.
- Edge connectors stick out up to 1.5 mm (2 mm wall − 0.5 mm); see
  `out/mechanical.txt` for each connector's edge, position and protrusion.
- Rear edge (PC side): USB A and USB B inputs (USB 3.0 Type-B), aux/flash (USB-C).
- Front edge (desk side): peripherals (USB-A), HDMI 1, HDMI 2, and the
  side-emitting RGB status LED (SK6812SIDE-A, lens 4 x 2 mm, centre 1 mm
  above the board), which shines straight out of the edge: a ~2 mm hole or
  light pipe in the wall is all it needs.  Its VDD comes from +5V_SYS through
  a 1N4148W (~4.3 V) so the 3.3 V data line clears VIH = 0.65 x VDD.
- Left edge: Grove button port, centred.  Right edge: ESP32 antenna.
- Buttons are 3 mm tall (TS-1187A-C-F-B): press them through flexures in the
  lid.  Positions in `out/mechanical.txt`.
- Inboard, rear: GPIO header J9, UART header J7, RESET / BOOT / PC-switch
  buttons (bench use; the Grove port is the user's button).

Switch sequence (every step is a single GPIO write):

1. `PERIPH_EN` = 0 — peripherals off
2. `USB_SEL` = target PC — data and power source follow together
3. wait ~200 ms — devices see a clean disconnect
4. `PERIPH_EN` = 1 — peripherals power up on the new PC and enumerate
5. send DDC/CI "input source" (VCP 0x60) to both monitors

MicroPython, e.g.:

```python
en.off(); sel.value(1); time.sleep_ms(200); en.on()   # switch to USB B
```

**Caveat:** many monitors only accept DDC/CI on the input currently being
shown.  Test your monitors with an ESP32 dev board + HDMI breakout before
ordering.
