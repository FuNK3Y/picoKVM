"""
Differential pairs behind the PC-side muxes (run after route_ss.py and
route_usb2.py, before the autorouter; tracks and vias are locked):

    U2 / U3 (muxes)  -> hub upstream
    hub ports 1-4    -> the two Type-A stacks (SuperSpeed and USB 2.0)
    port 4's USB 2.0 pair through the keyboard switches U47 / U48

The paths are searched (hw/pairs.py); this file only says what joins what,
on which layer, and where the layer changes are.

Conventions
  * SuperSpeed stays on F.Cu over the In1 ground plane, except each stack's
    inner-row receive pair, which has to cross the other port's pairs: it
    drops to B.Cu next to the hub and lands on the connector's through-hole
    pins from below.  Its ESD part hangs on a 2 mm F.Cu stub at those pins.
  * In a stack's pin field the outer-row pairs squeeze between two pin rows
    0.4 mm apart: drawn by hand there, necked to 0.105 / 0.105 mm.
  * USB 2.0 runs on B.Cu from a via pair at the hub to the connector.
"""

import os
import sys

import pcbnew

from layout import HUB, STACK_PARTS
from pairs import F, B, Router, Terminal, offset

PCB = "out/kvm_board.kicad_pcb"
NECK = 0.105         # track width and gap inside a stack's pin field (JLC DFM: >= 4 mil = 0.1016)


def stack_escape(r, jref, pair, side):
    """Outer-row SuperSpeed pair of a stack (pins 5/6 or 8/9), from its pins
    to just inboard of the innermost pin row.  side -1 = the pair on the
    connector's -x half (TX), +1 = the +x half (RX).  Returns a Terminal."""
    jx, jy = r.pad(jref, 7)                   # the drain pin between the two pairs: x = 0
    jy += 0.15                                # footprint origin
    s = side

    def at(pts):
        return [(jx + s * x, jy + y) for x, y in pts]

    # drawn on the +x half (travelling north, the outer pin's line is on the
    # left), mirrored for the other half
    centre = [(2.0, -1.2), (2.0, -2.1), (1.0, -3.1), (1.0, -4.3)]
    outer = at([(4.0, -0.15), (3.15, -1.0), (2.3, -1.0)] + offset(centre, NECK))
    inner = at([(2.0, -0.15), (2.0, -1.0), (1.9, -1.1)] + offset(centre, -NECK))
    # TX half: SSTX+ is the outer pin (9); RX half: SSRX+ is the inner pin (6)
    p, n = (outer, inner) if s < 0 else (inner, outer)
    # open out to the normal pitch over the last 0.1 mm, still at neck width
    for line, k in ((outer, 1), (inner, -1)):
        x, y = line[-1]
        line.append((x + k * s * (0.15 - NECK), y - 0.1))
    r.raw(pair, p, n, F, NECK)
    return Terminal(p[-1], n[-1], "N", 0.0)


def stack(r, jref, inner, outer, hub_dir, rx_via):
    """SuperSpeed for one stack, the F.Cu part.  inner / outer: hub port on
    the connector's inner rows (pins 10-18) / outer rows (1-9)."""
    sp = STACK_PARTS[jref]
    tx, rx = sp["tx_esd"], sp["rx_esd"]
    for port in (inner, outer):
        r.path[f"H{port}_SSTX"] = f"P{port}_SSTX"      # one path either side of the capacitors
    # the hand-drawn escapes first: their two lines differ by 1.2 mm, which
    # the searched stretches then make up
    esc_tx = stack_escape(r, jref, f"P{outer}_SSTX", -1)
    esc_rx = stack_escape(r, jref, f"P{outer}_SSRX", +1)
    # inner rows' receive pair first, so the others go round its via pair:
    # B.Cu from a via pair by the hub to the pins
    r.leg(f"P{inner}_SSRX", r.at("U30", f"P{inner}_SSRX", hub_dir), rx_via, F)
    # outer rows' receive pair, all on F.Cu, before the transmit pairs: on
    # the longer run to the stacks a transmit pair laid first hugged the hub's
    # corner and shut this pair's start in
    r.leg(f"P{outer}_SSRX", r.at("U30", f"P{outer}_SSRX", hub_dir), r.at(rx, f"P{outer}_SSRX", "N"), F, margin=10)
    r.through(rx, f"P{outer}_SSRX")
    r.leg(f"P{outer}_SSRX", r.at(rx, f"P{outer}_SSRX", "S"), esc_rx, F)
    # transmit pairs: hub -> capacitors -> ESD -> pins
    for port, end in ((inner, None), (outer, esc_tx)):
        r.leg(f"H{port}_SSTX", r.at("U30", f"H{port}_SSTX", hub_dir), r.cap_term(f"H{port}_SSTX", "N"), F)
        r.leg(f"P{port}_SSTX", r.cap_term(f"P{port}_SSTX", "S"), r.at(tx, f"P{port}_SSTX", "N"), F)
        r.through(tx, f"P{port}_SSTX")
        r.leg(f"P{port}_SSTX", r.at(tx, f"P{port}_SSTX", "S"),
              end or r.at(jref, f"P{port}_SSTX", "N", e=0.75), F)


def stack_rx(r, jref, inner, rx_via):
    """The inner rows' receive pair of a stack: B.Cu from its via pair to the
    pins (after the USB 2.0 pairs, which it goes round), and its ESD part on
    a stub from the pins."""
    rx = STACK_PARTS[jref]["rx_esd"]
    r.leg(f"P{inner}_SSRX", rx_via, r.at(jref, f"P{inner}_SSRX", "N", e=0.75), B, margin=10)
    Router.leg_stub(r, f"P{inner}_SSRX", r.at(jref, f"P{inner}_SSRX", "N", e=0.75), r.at(rx, f"P{inner}_SSRX", "S"))
    r.through(rx, f"P{inner}_SSRX")      # (the part's far pads: same net, so they are joined too)


def cap_term(r, pair, u):
    """The pads of a pair's two series capacitors that carry `pair`."""
    found = []
    for net in (pair + "_P", pair + "_N"):
        for fp in r.board.GetFootprints():
            if fp.GetReference().startswith("C"):
                for q in fp.Pads():
                    if q.GetNetname() == net:
                        found.append((pcbnew.ToMM(q.GetPosition().x), pcbnew.ToMM(q.GetPosition().y)))
    if len(found) != 2:
        raise SystemExit(f"{pair}: expected one capacitor pad per line, found {len(found)}")
    return Terminal(found[0], found[1], u, 0.3)


Router.cap_term = cap_term


def leg_stub(r, pair, a, b):
    """A branch off the pair (an ESD part beside it): routed like a leg, but
    its length is no part of the pair's."""
    np_, nn = (pair + "_P", pair + "_N")
    before = (r.len.get(np_, 0.0), r.len.get(nn, 0.0), r.debt.get(r.path.get(pair, pair), 0.0))
    r.leg(pair, a, b, F)
    r.len[np_], r.len[nn], r.debt[r.path.get(pair, pair)] = before


Router.leg_stub = staticmethod(leg_stub)


def main():
    board = pcbnew.LoadBoard(PCB)
    r = Router(board)
    try:
        jobs(r)
    except SystemExit as e:
        print("FAILED:", e)
        if os.environ.get("KEEP_PARTIAL"):      # for a look at where it stopped (hw/plot.py)
            pcbnew.SaveBoard(PCB, board)
        return
    pcbnew.SaveBoard(PCB, board)
    report(r)


def jobs(r):
    hx, hy = HUB
    only = sys.argv[1:]

    def want(name):
        return not only or name in only

    v = {}       # via pairs used by two legs

    if want("up"):
        # ---- upstream: muxes -> hub ------------------------------------------
        r.leg("UP_SSRX", r.at("U2", "UP_SSRX", "S"), r.at("U30", "UP_SSRX", "N"), F)
        r.leg("UP_SSTX", r.at("U2", "UP_SSTX", "S"), r.cap_term("UP_SSTX", "N"), F)
        r.leg("UPH_SSTX", r.cap_term("UPH_SSTX", "S"), r.at("U30", "UPH_SSTX", "N"), F)
        # USB 2.0: under the SuperSpeed lines on B.Cu
        v1, v2 = r.via((hx + 4.6, 23.6), "S"), r.via((hx + 3.3, hy - 7.7), "S")
        r.leg("UP_D", r.at("U3", "UP_D", "E"), v1, F)
        r.leg("UP_D", v1, v2, B)
        r.leg("UP_D", v2, r.at("U30", "UP_D", "N"), F)

    if want("usb2"):
        # ---- USB 2.0, hub side: ESD right at the pins, then down to B.Cu.
        # Done before the SuperSpeed pairs, which then go round these vias.
        v["P1"] = r.via((hx - 8.2, hy - 3.5), "W")
        v["P2"] = r.via((hx - 12.8, hy + 0.5), "W")
        v["P3"] = r.via((hx - 3.5, hy + 10.5), "S")
        v["H4"] = r.via((hx, hy + 7.3), "S", half=0.3, stagger=0.9)
        for port, esd, d in ((1, "U41", "W"), (2, "U42", "W"), (3, "U43", "S")):
            back = {"W": "E", "S": "N"}[d]
            r.leg(f"P{port}_D", r.at("U30", f"P{port}_D", d), r.at(esd, f"P{port}_D", back), F)
            r.through(esd, f"P{port}_D")
            r.leg(f"P{port}_D", r.at(esd, f"P{port}_D", d), v[f"P{port}"], F)
        r.leg("H4_D", r.at("U30", "H4_D", "S"), v["H4"], F)

    if want("j10"):
        # ---- ports 3 / 4 -> J10, straight below the hub ---------------------
        v["R3"] = r.via((hx - 1.0, hy + 8.9), "S", half=0.3, stagger=0.9)
        stack(r, "J10", 3, 4, "S", v["R3"])

    if want("j3"):
        # ---- ports 1 / 2 -> J3: west out of the hub, then south -------------
        v["R1"] = r.via((hx - 8.6, hy - 1.0), "W", half=0.3, stagger=0.9)
        stack(r, "J3", 1, 2, "W", v["R1"])

    # the stacks' B.Cu receive pairs take the direct line; the USB 2.0 pairs
    # that follow go round them
    if want("j10"):
        stack_rx(r, "J10", 3, v["R3"])
    if want("j3"):
        stack_rx(r, "J3", 1, v["R1"])

    if want("usb2"):
        # ---- USB 2.0, connector side.  The pairs enter each stack's pin field
        # from the south, through the gap between its two shell pegs: the
        # outer rows' pair on B.Cu, the inner rows' pair on F.Cu (it passes
        # between the outer rows' D+ / D- pins and round the drain pin).
        lane = (r.pad("J3", 20)[0] + r.pad("J10", 19)[0]) / 2       # between the stacks
        top = r.pad("J3", 16)[1] - 5.0
        r.leg("P2_D", v["P2"], r.at("J3", "P2_D", "S", e=0.75), B, margin=14)
        # port 3 before port 1: on the 102 mm board port 1's pair otherwise
        # took the lane right over port 3's via pair
        v3 = r.via((lane + 0.7, top - 1.6), "S")
        r.leg("P3_D", v["P3"], v3, B, margin=14)
        r.leg("P3_D", v3, r.at("J10", "P3_D", "S", e=2.05), F, margin=14)
        v1 = r.via((lane - 0.7, top), "S")
        r.leg("P1_D", v["P1"], v1, B, margin=14)
        r.leg("P1_D", v1, r.at("J3", "P1_D", "S", e=2.05), F, margin=14)
        # port 4: out of J10's east side, up to the keyboard switch
        ex = r.pad("U47", 8)[0]
        v4 = r.via((ex, r.pad("U44", 3)[1] + 2.4), "N")
        r.leg("P4_D", r.at("J10", "P4_D", "S", e=0.75), v4, B, margin=14)
        r.leg("P4_D", v4, r.at("U44", "P4_D", "S"), F)
        r.through("U44", "P4_D")
        r.leg("P4_D", r.at("U44", "P4_D", "N"), r.at("U47", "P4_D", "S"), F)
        # straight-through link between the two keyboard switches, and the
        # hub's port 4 pair to the second one
        t1, t2 = r.at("U47", "KBT_D", "N"), r.at("U48", "KBT_D", "S")
        k1 = r.via((t1.launch[0], t1.launch[1] - 1.3), "N")
        k2 = r.via((t2.launch[0], t2.launch[1] + 1.3), "N")
        r.leg("KBT_D", t1, k1, F)
        r.leg("KBT_D", k1, k2, B, margin=14)
        r.leg("KBT_D", k2, t2, F)
        t3 = r.at("U48", "H4_D", "N")
        h2 = r.via((t3.launch[0], t3.launch[1] - 1.3), "S")
        r.leg("H4_D", v["H4"], h2, B, margin=14)
        r.leg("H4_D", h2, t3, F)



def report(r):
    groups = {"UP RX": ["UP_SSRX"], "UP TX": ["UPH_SSTX", "UP_SSTX"], "UP D": ["UP_D"],
              "port 1 D": ["P1_D"], "port 2 D": ["P2_D"], "port 3 D": ["P3_D"],
              "port 4 D": ["P4_D", "KBT_D", "H4_D"]}
    for n in (1, 2, 3, 4):
        groups[f"port {n} TX"] = [f"H{n}_SSTX", f"P{n}_SSTX"]
        groups[f"port {n} RX"] = [f"P{n}_SSRX"]
    worst = r.summary(groups)
    print(f"pairs routed, worst skew {worst:.3f} mm", flush=True)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
