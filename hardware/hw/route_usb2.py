"""
Deliberate routing of the three switched USB 2.0 pairs (run after
route_ss.py, before the autorouter; tracks and vias are locked).

    J1 (USB A) -> U11 (ESD) -> U3 port 1          F.Cu only
    J2 (USB B) -> U12 (ESD) -> U3 port 2          F.Cu, B.Cu under the
                                                  Type-B row, F.Cu
    U3 common  -> U13 (ESD) -> J3 (peripheral)    F.Cu; B.Cu under the
                                                  SuperSpeed lines into U2; F.Cu
                                                  beside the U2 -> U19 bundle;
                                                  B.Cu under J3's fan

Each pair is a centreline turned into two coupled tracks (USB_DIFF
0.15/0.15 mm, ~90 ohm on either outer layer of JLC04161H-3313), with
mirrored fans at the pins and symmetric via pairs at layer changes.  D+ is
on the left of the direction of travel everywhere, which is how all three
connectors and U3 / the ESD parts present their pins, so nothing crosses.
Coordinates are tied to make_pcb.py's ANCHORS for U3/U11/U12/U13 and the
connector positions.
"""

import math
import os
import sys

import pcbnew

PCB = "out/kvm_board.kicad_pcb"
W = 0.15                 # USB_DIFF track width
HALF = 0.15              # half the 0.30 mm track pitch (0.15 gap)
VIA_D, VIA_DRILL = 0.45, 0.3
VIA_HALF = 0.35          # via pair: 0.7 mm apart (0.25 mm copper gap)
mm = pcbnew.FromMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu


def offset(pts, d):
    """Polyline offset by d along the left normal (-dy, dx), mitred."""
    def norm(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy)
        return (-dy / l, dx / l)
    ns = [norm(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            n = ns[0]; k = 1.0
        elif i == len(pts) - 1:
            n = ns[-1]; k = 1.0
        else:
            n1, n2 = ns[i - 1], ns[i]
            n = (n1[0] + n2[0], n1[1] + n2[1])
            k = 1.0 / (1.0 + n1[0] * n2[0] + n1[1] * n2[1])
        out.append((p[0] + n[0] * d * k, p[1] + n[1] * d * k))
    return out


def pair(centre):
    """Centreline -> (P, N): P on the left of the direction of travel."""
    # KiCad's y axis points down, so the left of travel is +normal here
    # when the normal is (dy, -dx); offset() uses (-dy, dx) = right.
    return offset(centre, -HALF), offset(centre, HALF)


def via_hop(end, direction):
    """Layer change at the end of a coupled leg heading `direction`
    (unit vector): both lines spread to the via pitch at 45 degrees, drop
    through a via each, and close back to the track pitch on the other
    layer.  Returns (P points before, P via, P points after) and the same
    for N, plus the next leg's start point on the centreline."""
    dx, dy = direction
    lx, ly = dy, -dx                      # left of travel (y down)
    ex, ey = end
    spread = VIA_HALF - HALF
    out = {}
    for name, s in (("P", 1), ("N", -1)):
        a = (ex + s * HALF * lx, ey + s * HALF * ly)
        b = (ex + dx * spread + s * VIA_HALF * lx, ey + dy * spread + s * VIA_HALF * ly)
        v = (b[0] + dx * 0.25, b[1] + dy * 0.25)
        c = (v[0] + dx * 0.25, v[1] + dy * 0.25)
        d = (c[0] + dx * spread - s * spread * lx, c[1] + dy * spread - s * spread * ly)
        out[name] = ([a, b, v], v, [v, c, d])
    nxt = (ex + dx * (2 * spread + 0.5), ey + dy * (2 * spread + 0.5))
    return out, nxt


def bump(pts, y0, h, flat, side):
    """Skew compensation on a vertical run (heading +y): bow the line out by
    h (side -1 = -x) between y0 and y0 + 2h + flat, with 45-degree flanks.
    Adds 2h(sqrt2 - 1) of length."""
    out = []
    for a, b in zip(pts, pts[1:]):
        out.append(a)
        if abs(a[0] - b[0]) < 1e-9 and a[1] < y0 and b[1] > y0 + 2 * h + flat:
            x = a[0]
            out += [(x, y0), (x + side * h, y0 + h), (x + side * h, y0 + h + flat),
                    (x, y0 + 2 * h + flat)]
    out.append(pts[-1])
    return out


def snap(p):
    """Round to 0.1 um so separately computed ends of joined segments are
    the same point (cleanup treats a 1 nm gap as an unconnected stub)."""
    return (round(p[0], 4), round(p[1], 4))


def add_track(board, net, pts, layer):
    pts = [snap(p) for p in pts]
    for a, b in zip(pts, pts[1:]):
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        t.SetWidth(mm(W))
        t.SetLayer(layer)
        t.SetNet(board.FindNet(net))
        t.SetLocked(True)
        board.Add(t)


def add_via(board, net, p):
    v = pcbnew.PCB_VIA(board)
    p = snap(p)
    v.SetPosition(pcbnew.VECTOR2I(mm(p[0]), mm(p[1])))
    v.SetWidth(mm(VIA_D))
    v.SetDrill(mm(VIA_DRILL))
    v.SetNet(board.FindNet(net))
    v.SetLocked(True)
    board.Add(v)


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


class Pair:
    """Accumulates the P and N paths of one pair, leg by leg."""

    def __init__(self, board, p_net, n_net):
        self.board, self.nets = board, {"P": p_net, "N": n_net}
        self.len = {"P": 0.0, "N": 0.0}
        self.vias = 0

    def line(self, which, pts, layer):
        add_track(self.board, self.nets[which], pts, layer)
        self.len[which] += length(pts)

    def lines(self, p_pts, n_pts, layer):
        self.line("P", p_pts, layer)
        self.line("N", n_pts, layer)

    def leg(self, centre, layer):
        p, n = pair(centre)
        self.lines(p, n, layer)
        return p, n

    def hop(self, end, direction, layer_from, layer_to):
        h, nxt = via_hop(end, direction)
        for which in ("P", "N"):
            before, v, after = h[which]
            self.line(which, before, layer_from)
            self.line(which, after, layer_to)
            add_via(self.board, self.nets[which], v)
            self.len[which] += 0.0
        self.vias += 2
        return nxt


def main():
    board = pcbnew.LoadBoard(PCB)
    result = {}

    # ---- USB A: J1 -> U11 -> U3 port 1, all F.Cu ------------------------
    a = Pair(board, "PCA_DP", "PCA_DN")
    # J1 D+ (18.25, 11.62) / D- (18.25, 13.62): mirrored fan to y 12.62
    a.lines([(18.25, 11.62), (19.4, 11.62), (20.25, 12.47)],
            [(18.25, 13.62), (19.4, 13.62), (20.25, 12.77)], F)
    p, n = a.leg([(20.25, 12.62), (23.7, 12.62), (24.0, 12.92), (24.0, 17.3)], F)
    # into U11 (rot 180, channel 2): D+ pins at x 24.25, D- at 23.75, y 18.0 -> 18.8
    a.lines([p[-1], (24.25, 17.4), (24.25, 18.0)], [n[-1], (23.75, 17.4), (23.75, 18.0)], F)
    a.lines([(24.25, 18.0), (24.25, 18.8)], [(23.75, 18.0), (23.75, 18.8)], F)
    a.lines([(24.25, 18.8), (24.25, 19.4), (24.15, 19.5)],
            [(23.75, 18.8), (23.75, 19.4), (23.85, 19.5)], F)
    p, n = a.leg([(24.0, 19.5), (24.0, 19.9), (24.6, 20.5), (24.7, 20.5)], F)
    # U3 port 1: 1D+ (25.32, 20.25), 1D- (25.32, 20.75)
    a.lines([p[-1], (24.8, 20.25), (25.32, 20.25)], [n[-1], (24.8, 20.75), (25.32, 20.75)], F)
    result["USB A (PCA)"] = a

    # ---- USB B: J2 -> U12 -> B.Cu -> U3 port 2 ---------------------------
    b = Pair(board, "PCB_DP", "PCB_DN")
    b.lines([(36.25, 11.62), (37.4, 11.62), (38.25, 12.47)],
            [(36.25, 13.62), (37.4, 13.62), (38.25, 12.77)], F)
    p, n = b.leg([(38.25, 12.62), (42.6, 12.62)], F)
    # U12 (rot -90): D+ pins y 12.37, D- y 12.87, x 43.2 -> 44.0
    b.lines([p[-1], (42.7, 12.37), (43.2, 12.37)], [n[-1], (42.7, 12.87), (43.2, 12.87)], F)
    b.lines([(43.2, 12.37), (44.0, 12.37)], [(43.2, 12.87), (44.0, 12.87)], F)
    b.lines([(44.0, 12.37), (44.4, 12.37), (44.5, 12.47)],
            [(44.0, 12.87), (44.4, 12.87), (44.5, 12.77)], F)
    p, n = b.leg([(44.5, 12.62), (44.9, 12.62), (45.2, 12.92), (45.2, 13.4)], F)
    nxt = b.hop((45.2, 13.4), (0, 1), F, B)
    p, n = b.leg([nxt, (45.2, 18.2), (44.9, 18.5), (22.5, 18.5), (22.2, 18.8), (22.2, 19.6)], B)
    nxt = b.hop((22.2, 19.6), (0, 1), B, F)
    p, n = b.leg([nxt, (22.2, 20.9), (22.8, 21.5), (24.7, 21.5)], F)
    # U3 port 2: 2D+ (25.32, 21.25), 2D- (25.32, 21.75)
    b.lines([p[-1], (24.8, 21.25), (25.32, 21.25)], [n[-1], (24.8, 21.75), (25.32, 21.75)], F)
    result["USB B (PCB)"] = b

    # ---- peripheral: U3 common -> U13 -> B.Cu -> J3 ----------------------
    c = Pair(board, "PER_DP", "PER_DN")
    # U3 D+ (26.68, 20.75) / D- (26.68, 21.25) straight into U13 (0.5 mm pitch)
    c.lines([(26.68, 20.75), (27.9, 20.75)], [(26.68, 21.25), (27.9, 21.25)], F)
    c.lines([(27.9, 20.75), (28.7, 20.75)], [(27.9, 21.25), (28.7, 21.25)], F)
    c.lines([(28.7, 20.75), (29.0, 20.75), (29.1, 20.85)],
            [(28.7, 21.25), (29.0, 21.25), (29.1, 21.15)], F)
    # turn south at x 30.6, leaving room east of U13 for its GND via
    p, n = c.leg([(29.1, 21.0), (30.3, 21.0), (30.6, 21.3), (30.6, 23.8)], F)
    nxt = c.hop((30.6, 23.8), (0, 1), F, B)
    # B.Cu under the SuperSpeed lines converging on U2 ...
    p, n = c.leg([nxt, (30.6, 34.6)], B)
    nxt = c.hop((30.6, 34.6), (0, 1), B, F)
    # ... back on F.Cu right beside the U2 -> U19 SuperSpeed bundle, so the
    # two form one barrier and B.Cu stays free for east-west signals.  The
    # pair turns right once more than left overall (east -> south): D+ is
    # the outer line by 4 x 45-degree mitres (0.497 mm); a 0.6 mm bump on D-
    # (2 x 0.6 x (sqrt2 - 1) = 0.497 mm) evens it out.
    p, n = pair([nxt, (30.6, 36.0), (28.6, 38.0), (28.6, 50.6)])
    n = bump(n, 42.0, 0.6, 1.0, -1)
    c.lines(p, n, F)
    nxt = c.hop((28.6, 50.6), (0, 1), F, B)
    # ... and B.Cu again under U19 and J3's SuperSpeed fan
    p, n = c.leg([nxt, (28.6, 58.2), (28.0, 58.8), (26.6, 58.8), (26.0, 59.4), (26.0, 59.6)], B)
    # J3 D+ (27.0, 62.52) / D- (25.0, 62.52), either side of the GND pin (26, 61.02)
    c.lines([p[-1], (27.0, 60.45), (27.0, 62.52)], [n[-1], (25.0, 60.45), (25.0, 62.52)], B)
    result["peripheral (PER)"] = c

    # GND bridge under each ESD part: its two GND pins (3, 8) are joined
    # straight across the body, so one plane via (from fanout) serves both
    for ref in ("U11", "U12", "U13"):
        g = [q for q in board.FindFootprintByReference(ref).Pads() if q.GetNumber() in ("3", "8")]
        pts = [(pcbnew.ToMM(q.GetPosition().x), pcbnew.ToMM(q.GetPosition().y)) for q in g]
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(mm(pts[0][0]), mm(pts[0][1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(pts[1][0]), mm(pts[1][1])))
        t.SetWidth(mm(0.2))
        t.SetLayer(F)
        t.SetNet(board.FindNet("GND"))
        t.SetLocked(True)
        board.Add(t)

    # VBUS escapes from the Type-B connectors.  The USB A/B pairs leave the
    # D+/D- pins eastward, so VBUS (pin 1, west column) leaves straight down
    # between two SuperSpeed pins (1.1 mm gap) into the V between that
    # connector's two SuperSpeed fans and drops to B.Cu below the USB B
    # pair's B.Cu run (y 18.5).  The autorouter rarely finds this on its own.
    for net, x in (("VBUS_A", 15.75), ("VBUS_B", 33.75)):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(mm(x), mm(13.62)))
        t.SetEnd(pcbnew.VECTOR2I(mm(x), mm(19.15)))
        t.SetWidth(mm(0.4))
        t.SetLayer(F)
        t.SetNet(board.FindNet(net))
        t.SetLocked(True)
        board.Add(t)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(19.15)))
        v.SetWidth(mm(0.5))
        v.SetDrill(mm(0.3))
        v.SetNet(board.FindNet(net))
        v.SetLocked(True)
        board.Add(v)

    # Peripheral power, U4 (TPS2116) VOUT -> U20 (TPS2553) IN: the F.Cu side
    # of U4 is boxed in by its four power pins, so drop to the nearly empty
    # B.Cu straight from the VOUT tie under U4 and come up beside U20 pin 1.
    def track(net, pts, layer, w):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
            t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
            t.SetWidth(mm(w))
            t.SetLayer(layer)
            t.SetNet(board.FindNet(net))
            t.SetLocked(True)
            board.Add(t)

    def pvia(net, x, y):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(0.5))
        v.SetDrill(mm(0.3))
        v.SetNet(board.FindNet(net))
        v.SetLocked(True)
        board.Add(v)

    u4 = {q.GetNumber(): q.GetPosition() for q in board.FindFootprintByReference("U4").Pads()}
    u20 = {q.GetNumber(): q.GetPosition() for q in board.FindFootprintByReference("U20").Pads()}
    tie_x = pcbnew.ToMM(u4["2"].x + u4["7"].x) / 2
    tie_y = pcbnew.ToMM(u4["7"].y)
    ix, iy = pcbnew.ToMM(u20["1"].x), pcbnew.ToMM(u20["1"].y)
    pvia("VBUS_PERIPH_RAW", tie_x, tie_y)
    track("VBUS_PERIPH_RAW", [(tie_x, tie_y), (tie_x, iy + 0.7), (ix + 1.05, iy + 0.7)], B, 0.4)
    pvia("VBUS_PERIPH_RAW", ix + 1.05, iy + 0.7)
    track("VBUS_PERIPH_RAW", [(ix + 1.05, iy + 0.7), (ix + 1.05, iy), (ix, iy)], F, 0.4)

    # C6 (U20's input capacitor) straight onto U20's IN via
    c6 = [d for d in board.FindFootprintByReference("C6").Pads() if d.GetNumber() == "1"][0]
    track("VBUS_PERIPH_RAW", [(ix + 1.05, iy + 0.7),
                              (pcbnew.ToMM(c6.GetPosition().x), pcbnew.ToMM(c6.GetPosition().y))], F, 0.4)

    # LM66100 U6 / U7: input caps C23 / C24 onto VIN (pin 1), output cap C25
    # onto U7's VOUT (pin 3); U6's VOUT joins through the +5V_SYS routing
    def pad_mm(ref, num):
        d = [q for q in board.FindFootprintByReference(ref).Pads() if q.GetNumber() == num][0]
        return pcbnew.ToMM(d.GetPosition().x), pcbnew.ToMM(d.GetPosition().y)
    for cref, uref, net in (("C23", "U6", "VBUS_A"), ("C24", "U7", "VBUS_B")):
        (cx, cy), (ux, uy) = pad_mm(cref, "1"), pad_mm(uref, "1")
        track(net, [(cx, cy), (cx, uy), (ux, uy)], F, 0.3)
    # leave C25's pad straight out of its top edge, then 45 degrees into
    # U7 pin 3, so the track never runs alongside the pad's mask opening
    (cx, cy), (ux, uy) = pad_mm("C25", "1"), pad_mm("U7", "3")
    # (1.3 mm straight out clears the 0805 pad's corner before turning)
    track("+5V_SYS", [(cx, cy), (cx, cy - 1.3), (ux, uy)], F, 0.3)

    # PC supplies into U4 on B.Cu (0.4 mm, POWER class), from the escape vias
    # under J1 / J2 (above): VBUS_A down the west side and east along U4's
    # row into VIN2; VBUS_B down, diagonally past U18's GND vias, and south
    # into VIN1.  Each lands on a via just beyond its pin's neck-down.
    neck = 0.935                       # half pad length + finish.py NECK_LEN
    p6x, p6y = (pcbnew.ToMM(v) for v in (u4["6"].x, u4["6"].y))   # VIN2 = VBUS_A
    p3x, p3y = (pcbnew.ToMM(v) for v in (u4["3"].x, u4["3"].y))   # VIN1 = VBUS_B
    ax = p6x - neck
    track("VBUS_A", [(15.75, 19.15), (15.75, p6y - 3.85), (19.6, p6y), (ax, p6y)], B, 0.4)
    pvia("VBUS_A", ax, p6y)
    track("VBUS_A", [(ax, p6y), (p6x, p6y)], F, 0.3)
    bx = p3x + neck
    track("VBUS_B", [(33.75, 19.15), (33.75, 26.5), (bx, 26.5 + (bx - 33.75)), (bx, p3y)], B, 0.4)
    pvia("VBUS_B", bx, p3y)
    track("VBUS_B", [(bx, p3y), (p3x, p3y)], F, 0.3)
    # U4's input capacitors C4 (VBUS_A) / C5 (VBUS_B) straight onto those vias
    for ref, net, (vx, vy) in (("C4", "VBUS_A", (ax, p6y)), ("C5", "VBUS_B", (bx, p3y))):
        q = [d for d in board.FindFootprintByReference(ref).Pads() if d.GetNumber() == "1"][0]
        qx, qy = pcbnew.ToMM(q.GetPosition().x), pcbnew.ToMM(q.GetPosition().y)
        track(net, [(qx, qy), (vx, vy)], F, 0.4)

    pcbnew.SaveBoard(PCB, board)
    for name, pr in result.items():
        lp, ln = pr.len["P"], pr.len["N"]
        print(f"  {name:17} D+ {lp:6.2f} mm  D- {ln:6.2f} mm  skew {abs(lp - ln):.3f} mm"
              f"  vias {pr.vias}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
