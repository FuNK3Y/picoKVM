"""
Board geometry for picoKVM rev B: the one place where sizes and positions
live.  make_pcb.py places from it, the routing scripts, panel.py and
checks.py read it, so moving a part means editing one number here.

Coordinates in mm, origin at the rear-left corner, y towards the front.

Floorplan: inputs on the rear edge (the two PCs and the aux supply), outputs
on the front edge (four USB ports, four HDMI on two stacked connectors).  The USB path runs straight
from rear to front: Type-B -> ESD -> muxes -> hub -> ESD -> Type-A.
"""

REV = "B"
W, H = 98.0, 102.0           # board outline
# The board grew 12 mm towards the front for the stacked HDMI connectors and
# their four DDC circuits, and 2 mm to the right so the front-right screw
# clears the right HDMI stack.  Then 6 mm more in the empty band between the
# hub / RP2350 area and the front parts (y ~ 63-68 on the 96 mm board), for
# wide port-power tracks across the board (placement_freeze.py shifts the
# parts below that band with it).  Positions laid out against the 78 mm front edge
# (connector-side parts, corridors to the stacks) are offset by FRONT.
FRONT = H - 78.0

# ---------------------------------------------------------------- edge parts
# ref -> (edge, position along the edge).  Each opens outward and sticks out
# by up to PROTRUDE (2 mm case wall - 0.5 mm), but never so far that a pad
# comes closer than EDGE_PAD_CLEAR to the edge.
PC_X = 27.0                  # USB A connector; the whole PC-side block hangs off it
STACK_X = (18.75, 37.75)     # the two Type-A stacks; the hub sits above the second, 1.75 mm
                             # to its left, so ports 3/4's pairs drop almost straight in
EDGE_PARTS = {
    "J4": ("rear", 13.5),            # aux / flash USB-C
    "J1": ("rear", PC_X),            # USB A  USB 3.0 B
    "J2": ("rear", PC_X + 18.0),     # USB B  USB 3.0 B
    "J3": ("front", STACK_X[0]),     # USB ports 1 + 2
    "J10": ("front", STACK_X[1]),    # USB ports 3 + 4 (keyboard-capable)
    # Two stacked HDMI connectors (18 mm wide), 20 mm from the keyboard stack
    # and 22.5 mm apart: a 21 mm overmoulded HDMI plug clears a 16 mm USB
    # plug and its twin by 1.5 mm
    "J5": ("front", 57.75),           # HDMI 1 (lower) / HDMI 3 (upper)
    "J6": ("front", 80.25),           # HDMI 2 (lower) / HDMI 4 (upper)
    # the two Grove ports side by side, the pair centred on the left edge
    "J8": ("left", 41.5),            # Grove button port
    "J11": ("left", 54.5),           # Grove I2C port
}
PROTRUDE = 1.5
EDGE_PAD_CLEAR = 0.3

# ESP32-S3-WROOM-1 (25.5 x 18 mm): the PCB antenna is the last ~6 mm of the
# module.  It sits flush with the right edge (no overhang).  Copper keep-out
# on every layer per Espressif / the KiCad footprint's own rule area: from
# the start of the antenna (6.75 mm from the module centre) to the edge, and
# 15 mm past the module on both sides.
ESP_X = W - 12.75 - 0.2      # module centre: antenna end 0.2 mm inside the edge
ESP_Y = 34.0
ANTENNA_KEEPOUT = (ESP_X + 6.75, ESP_Y - 24.0, W, ESP_Y + 24.0)

LED_X = 76.0                 # side-emitting RGB status LED, rear edge, above the PC switch button
PC_MID = PC_X + 9.0          # centre line of the PC-side block (U2, U3)
HUB = (PC_MID, 45.0)         # TUSB8041 centre, straight below the muxes
RP = (56.5, 52.5)            # RP2350 centre

# ------------------------------------------------------------------- anchors
# ref -> (x, y, rotation).  The PC-side block (connectors -> ESD -> muxes) is
# rev A's proven geometry, moved as a whole: route_ss.py / route_usb2.py are
# written relative to PC_X.
_px = PC_X - 17.0            # rev A had USB A at x = 17


def _hdmi_stack(cx, lower, upper):
    """DDC parts in the band behind a stacked HDMI connector at x = cx: the
    lower port's group to the left, the upper port's to the right.  lower /
    upper = (USBLC6, LM66100, PTC) refs; the upper port has no LM66100 of
    its own (None): the lower port's feeds both PTCs."""
    out = {}
    for s, (esd, diode, ptc) in ((-1, lower), (1, upper)):
        out[esd] = (cx + 3.0 * s, H - 25.5, 0)          # USBLC6 on SCL/SDA
        if diode:
            out[diode] = (cx + 4.6 * s, H - 21.7, 0)    # LM66100, HDMI 5 V
        out[ptc] = (cx + 1.2 * s, H - 21.7, 90)         # 100 mA PTC, standing
    return out


def _buck(u, l, x, y):
    """TLV62569 (SOT-23-5) turned so SW (pin 3) faces east, the inductor's
    SW pad straight beside it: a ~1 mm switch node on F.Cu.  Its input
    capacitor, output capacitors and feedback divider are placed at their
    pins by the at= hints in kvm_board.py."""
    return {u: (x, y, 180), l: (x + 4.1, y - 0.95, 180)}


ANCHORS = {
    # PC side: B receptacles -> ESD -> muxes
    "U17": (17.0 + _px, 24.0, 0),       # TPD4E05U06 USB A SuperSpeed
    "U18": (35.0 + _px, 24.0, 0),       # TPD4E05U06 USB B SuperSpeed
    "U2": (26.0 + _px, 34.0, 0),        # HD3SS3212
    "U3": (26.0 + _px, 21.0, -90),      # TS3USB221A: ports west, common east
    "U11": (24.75 + _px, 18.4, 180),    # TPD4E05U06 USB A D+/D-
    "U12": (43.6 + _px, 13.37, -90),    # TPD4E05U06 USB B D+/D-
    "C3": (27.6 + _px, 18.9, 0),        # U3's decoupling
    # hub: upstream on its north side, ports 1/2 west, 3/4 south
    "U30": (HUB[0], HUB[1], 0),
    # by XI/XO (pins 62/61, north-west corner), clear of U41 and C81, turned
    # so XI (pad 1) is the corner facing pin 62: XI runs straight in, XO
    # round the north side and down past the R9/C114 column to pin 61
    "Y1": (29.2, 37.0, 90),
    "C60": (HUB[0] - 0.05, 37.9, 90),   # AC coupling, hub upstream TX
    "C61": (HUB[0] + 1.05, 37.9, 90),
    # RP2350 (keyboard interception) between the hub and the ESP32
    "U45": (RP[0], RP[1], 0),
    "U46": (54.7, 43.0, 0),             # flash, by the QSPI pins
    "Y2": (54.4, 59.5, 0),
    "U47": (48.0, 55.4, 0),             # keyboard port switch (connector side)
    "U48": (62.4, 47.6, 0),             # keyboard port switch (hub side)
    # USB 2.0 ESD, flow-through on F.Cu: ports 1-3 right at the hub (the
    # unused half of the part hangs off to the side), port 4 where its pair
    # comes up beside J10 on its way to the keyboard switch
    # (U43 a step further out along its line than right at the pins: that
    # frees the hub's south-west corner for a +1V1 capacitor.  U41 stays at
    # the pins: moved out with a capacitor in the north-west corner, the
    # hub's east-side control lines (P1_PWR_EN, HUB_SDA) found no way round)
    "U41": (HUB[0] - 6.5, HUB[1] - 4.25, 90),
    "U42": (HUB[0] - 10.2, HUB[1] - 0.25, 90),
    "U43": (HUB[0] - 4.25, HUB[1] + 8.5, 0),
    "U44": (48.75, 55.6 + FRONT, 0),   # (3 mm short of the front offset: clear of HDMI stack J5)
    # power: aux input and regulators in the rear-left corner, the PC-side
    # source select beside the PC connectors, port switches by the stacks
    "U8": (6.5, 12.0, 90),              # LM66100 AUX
    "U14": (13.5, 12.6, 0),             # USBLC6 aux
    "U32": (17.6, 14.0, 90),            # TPS2116 AUX priority
    **_buck("U5", "L1", 8.0, 21.0),      # 3.3 V buck
    **_buck("U31", "L2", 44.0, 31.6),    # 1.1 V buck, next to its loads
    "U4": (58.5, 31.4, 180),            # TPS2116 A/B
    "U6": (54.5, 25.0, 90),             # LM66100 A
    "U7": (58.5, 25.0, 90),             # LM66100 B
    "U33": (6.0, 62.2 + FRONT, 0),      # port 1 (below the Grove ports, beside its stack)
    "U34": (6.0, 67.6 + FRONT, 0),      # port 2
    "U35": (47.0, 41.8, 0),            # port 3
    "U36": (47.0, 46.8, 0),            # port 4 (turned 180, its input capacitor walled in the hub's east pins)
    "C9": (12.6, 58.6 + FRONT, 90),      # 100 uF port reservoirs
    "C10": (53.0, 36.4, 0),
    # bench: buttons (well away from the edges, for lid flexures) and UART
    "SW1": (60.0, 19.0, 0),             # RESET
    "SW2": (68.0, 19.0, 0),             # BOOT
    "SW3": (76.0, 19.0, 0),             # PC switch
    "TP3": (64.0, 9.5, 0),              # UART0 TX
    "TP4": (66.6, 9.5, 0),              # UART0 RX
    "U13": (79.0, 51.0, 0),             # I2C multiplexer, between the ESP32 and the HDMI ports
    "TP1": (70.9, 53.4, 0),
    "TP2": (70.9, 56.0, 0),
    "D5": (70.9, 49.2, 90),             # keyboard activity LED
    "D4": (LED_X - 5.5, 2.2, 0),        # status LED supply diode, beside the LED
    # MCU: antenna (local -Y) points to +X, flush with the right edge
    "U1": (ESP_X, ESP_Y, -90),
    # rear edge: side-emitting RGB LED, lens (local +Y, 1.36 mm from the
    # origin) facing the edge, 0.2 mm inside it
    "D3": (LED_X, 0.2 + 1.36, 180),
    # screws: the four corners
    "H1": (4.0, H - 4.0, 0),
    "H2": (W - 4.0, H - 4.0, 0),
    "H3": (4.0, 4.0, 0),
    "H4": (W - 4.0, 4.0, 0),
}
ANCHORS.update(_hdmi_stack(EDGE_PARTS["J5"][1], ("U15", "U21", "F2"), ("U19", None, "F6")))
ANCHORS.update(_hdmi_stack(EDGE_PARTS["J6"][1], ("U16", "U22", "F3"), ("U20", None, "F7")))

# Type-A stacks, in footprint coordinates (opening towards +y, x across).
# Inboard of the pin rows the SuperSpeed pairs come out at x = -3, -1, 1, 3:
# one flow-through ESD part per two pairs, then the TX pairs' AC-coupling
# capacitors.
STACK_PARTS = {
    "J3": {"tx_esd": "U37", "rx_esd": "U38", "caps": ("C62", "C63", "C64", "C65")},
    "J10": {"tx_esd": "U39", "rx_esd": "U40", "caps": ("C66", "C67", "C68", "C69")},
}
STACK_ESD_DY = -6.8          # ESD row, from the connector origin
STACK_CAP_DY = -9.6          # AC-coupling capacitor row
STACK_ESD_DX = 2.0           # ESD parts at -/+ this (TX west, RX east)

# nets whose passives must sit at a given part (overrides net affinity)
NET_HOME = {"GROVE_BTN": "J8", "GROVE_LED": "J8", "GROVE_5V": "J8",
            "AUX_CC1": "J4", "AUX_CC2": "J4", "AUX_CC_SENSE": "J4",
            "VBUS_AUX": "U8", "AUX_PR1": "U32",
            "VBUS_A_SENSE": "U6", "VBUS_B_SENSE": "U7", "VBUS_AUX_SENSE": "U8",
            "HUB_VBUS_DET": "U4", "U5_FB": "U5", "U31_FB": "U31", "+1V1": "U31", "HUB_XI": "Y1", "HUB_XO": "Y1",
            "RP_PROG_SS": "U46", "RP_PROG_SCLK": "U46", "RP_PROG_SD0": "U46",
            "RP_PROG_SD1": "U46", "RP_QSPI_SS": "U46",
            "KBH_DP": "U47", "KBH_DN": "U47", "KBD_DP": "U48", "KBD_DN": "U48",
            "VBUS_P1": "U33", "VBUS_P2": "U34", "VBUS_P3": "U35", "VBUS_P4": "U36",
            "EN": "SW1", "BOOT": "SW2", "BTN_SWITCH": "SW3",
            "LED_VDD": "D3", "LED_DIN": "D3", "RP_LED_K": "D5",
            "RP_LINK_TX": "D5", "RP_LINK_RX": "D5", "RP_LINK_ATTN": "D5",
            "GROVE_SDA_C": "J11", "GROVE_SCL_C": "J11", "GROVE2_5V": "J11",
            "GROVE_SDA": "U13", "GROVE_SCL": "U13", "I2C_SDA": "U13", "I2C_SCL": "U13",
            "I2C_MUX_RESET_N": "U13"}

# Passives placed by hand: ref -> (x, y, rotation)
# The hub's supply pins sit between the pairs that leave it on three sides,
# with no room for a capacitor and its ground via.  Each pin drops straight
# into its plane or pour through a via under the package (finish.py), and the
# capacitors stand in two rows off the hub's east corners, on the same pour.
FIXED_PASSIVES = {
    "C76": (HUB[0] + 6.4, HUB[1] - 4.6, 0),      # pin 51, joined along the pad row
    **{c: (HUB[0] + 6.3, HUB[1] - 6.8 - 1.1 * i, 0) for i, c in enumerate(("C80", "C77", "C70"))},
    # the south-west corner, freed by moving U43 out along its line: pins
    # 5 / 8 / 13 (+1V1, west side) reach it through the B.Cu ring under the
    # package, 2-4 mm instead of ~10 mm to the east rows
    "C71": (HUB[0] - 5.0, HUB[1] + 6.3, 180),
    **{c: (HUB[0] + 6.3, HUB[1] + 5.7 + 1.1 * i, 0) for i, c in enumerate(("C72", "C73", "C74"))},
    # The RP2350's supply pins do the same (0.4 mm pitch: no room at the pins
    # either); its capacitors stand east of it, clear of the three lines to
    # the ESP32 that leave that side.
    # (the first place of the top row stays empty: GPIO26, pin 40, leaves
    # through it; that row's third capacitor stands at its east end instead)
    **{c: (RP[0] + 5.5 + 2.1 * (i % 3), RP[1] - 1.1 + 1.25 * (i // 3), 0)
       for i, c in enumerate((None, "C91", "C86", "C84", "C85", "C90")) if c},
    "C92": (RP[0] + 5.5 + 6.3, RP[1] - 1.1, 0),
    **{c: (RP[0] + 5.5 + 2.1 * i, RP[1] + 3.1, 0) for i, c in enumerate(("C88", "C89", "C87"))},
}

# Passives placed by hand, found by (value, one of their nets) instead of by
# reference: SKiDL numbers parts in schematic order, so a reference in
# FIXED_PASSIVES silently moves to another part whenever the schematic above
# it changes (rev B put EN's pull-up next to the RP2350 that way).
# make_pcb.py stops if a key matches no part or more than one.
FIXED_BY_NET = {
    # crystal circuit at the RP2350's XIN/XOUT pins
    ("1k", "RP_XOUT_R"): (57.4, 58.4, 90), ("15pF", "RP_XIN"): (51.6, 59.0, 90),
    ("15pF", "RP_XOUT_R"): (58.2, 60.7, 0),
    # USB series resistors at their pins (pad 1 on the RP2350's net, facing
    # it): device side (USB_DP/DM) towards U48, host side (GPIO0/1) towards U47
    ("27", "RP_USB_DN"): (60.4, 45.6, 0), ("27", "RP_USB_DP"): (60.4, 44.35, 0),
    ("27", "RP_HOST_DP"): (50.6, 49.5, 180), ("27", "RP_HOST_DN"): (50.6, 50.75, 180),
    # hub crystal: R9 (1M, pad 1 XI below, XO above) and XI's load capacitor
    # in a column between Y1 and the hub's corner, where XO passes on its way
    # down to pin 61; XO's capacitor sits at Y1's XO pad (at= hint)
    ("1M", "HUB_XI"): (31.95, 34.55, 90), ("18pF", "HUB_XI"): (31.95, 36.6, 270),
    # USB_R1's bias resistor west of Y1, ~6.6 mm of track to pin 64: the
    # nearest spot that leaves the crystal loop and the port 1/2 pairs alone
    ("9.53k", "HUB_R1"): (26.0, 39.06, 180),
}

# Parts with a placement hint (kvm_board.py at=) go in this order of the part
# they hint to, before the rest: the regulators' loops and the flash taps
# must not lose their spots to a bypass capacitor of a crowded neighbour
AT_FIRST = ("U5", "L1", "U31", "L2", "U46")

# Supply pins with room for their 100 nF right at the pin: (capacitor, pin,
# distance).  The capacitor goes radially outward from the pin; make_pcb.py
# computes the position.  Neighbouring pins get different distances.
HUB_DECOUPLING = [("C75", "31", 1.9), ("C78", "16", 1.9), ("C79", "34", 1.9), ("C81", "63", 1.9)]
RP_DECOUPLING = []

# +1V1 is poured on B.Cu under its two loads and the regulator between them:
# one outline, clockwise from the hub's north-west corner
V1_OUTLINE = [(HUB[0] - 6.0, HUB[1] - 6.0), (HUB[0] + 4.5, HUB[1] - 6.0), (HUB[0] + 4.5, 24.0),
              (53.0, 24.0), (53.0, HUB[1] - 6.0), (RP[0] + 11.0, HUB[1] - 6.0),
              (RP[0] + 11.0, RP[1] + 5.0), (RP[0] - 5.0, RP[1] + 5.0), (RP[0] - 5.0, HUB[1] + 9.5),
              (HUB[0] - 6.0, HUB[1] + 9.5)]

# No automatic passives here (x0, y0, x1, y1): the differential pairs' corridors
CORRIDORS = [
    # J1/J2 -> U17/U18 -> U2; east of U2 the pairs stay above y = 28.5 (west of x = 37.8 below it), so
    # the corner below is free for the 1.1 V regulator's input side
    (12.0 + _px, 17.5, 40.0 + _px, 29.0),
    (12.0 + _px, 29.0, 38.6, 32.4),
    (17.5 + _px, 11.9, 26.2 + _px, 20.9),        # USB 2.0, PC side
    (21.2 + _px, 19.6, 31.3 + _px, 24.9),
    (42.4 + _px, 11.8, 46.3 + _px, 15.4),
    (HUB[0] - 3.0, 35.6, HUB[0] + 4.6, 40.2),    # U2 -> hub upstream, incl. the USB 2.0 pair's via pair at x 39-39.9
    (13.0, 40.0, 31.0, 56.0 + FRONT),                    # hub -> J3
    (HUB[0] - 5.5, 50.0, HUB[0] + 5.5, 59.6 + FRONT),    # hub -> J10, down to its ESD row
    (HUB[0] + 5.0, 39.0, 45.1, 50.0),            # hub's east pins -> ports 3/4's switches (EN, OC, I2C, reset)
    (25.2, 44.0, 31.4, 62.0 + FRONT),                    # ports 1-3 USB 2.0, down between the stacks
    (46.0, 56.0, 50.4, 66.0 + FRONT),                    # port 4 USB 2.0
    (52.4, 45.4, 57.0, 48.5),                    # RP2350 <-> flash
    (56.6, 45.2, 60.4, 48.6),                    # RP2350 USB D+/D- (pins 51/52) up to their 27R
    (46.2, 50.6, 49.8, 54.2),                    # keyboard switches' via pairs
    (60.4, 48.8, 64.6, 51.4),
    (60.4, 43.2, 64.6, 46.4),
    ANTENNA_KEEPOUT,
]

# Silkscreen: functional labels instead of reference designators,
# >= 1.0 mm text.  (text, x, y, size, rotation)
LABELS = [
    (f"picoKVM rev {REV}", 72.0, 6.4, 1.5, 0),
    ("AUX", EDGE_PARTS["J4"][1], 9.2, 1.0, 0),
    ("USB A", EDGE_PARTS["J1"][1], 21.0, 1.2, 0),
    ("USB B", EDGE_PARTS["J2"][1], 21.0, 1.2, 0),
    ("1 / 2", STACK_X[0], 55.0 + FRONT, 1.0, 0),
    ("3 / 4 KBD", STACK_X[1], 55.0 + FRONT, 1.0, 0),
    ("HDMI 1 / 3", EDGE_PARTS["J5"][1], H - 28.2, 1.0, 0),
    ("HDMI 2 / 4", EDGE_PARTS["J6"][1], H - 28.2, 1.0, 0),
    ("GROVE BTN", 16.2, 41.5, 1.0, 90),
    ("UART TX RX", 65.3, 11.6, 1.0, 0),
    ("GROVE I2C", 16.2, 54.5, 1.0, 90),
    ("RESET", 60.0, 15.2, 1.0, 0),
    ("BOOT", 68.0, 15.2, 1.0, 0),
    ("PC SW", 76.0, 15.2, 1.0, 0),
    ("STATUS", LED_X + 6.0, 1.6, 1.0, 0),
    ("SWD", 70.9, 58.0, 1.0, 0),
]

BUTTONS = (("SW1", "RESET"), ("SW2", "BOOT"), ("SW3", "PC SW"))

# parts turned so that one pin faces a compass direction: ref -> (pin, "N/E/S/W")
ORIENT = {"C60": ("1", "S"), "C61": ("1", "S"),      # AC coupling: pad 1 is the hub side
          **{f"C{n}": ("1", "N") for n in range(62, 70)},
          "U30": ("57", "N"),   # hub: upstream north, ports 1/2 west, 3/4 south
          "U41": ("5", "S"), "U42": ("5", "S"), "U43": ("5", "E"),   # the used half next to the hub's pins
          "U44": ("1", "W"),
          "U47": ("8", "S"),    # common (connector pair) towards J10
          "U48": ("8", "N")}    # common (hub pair) towards the hub
