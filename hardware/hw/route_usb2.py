"""
Deliberate routing of the two PC-side USB 2.0 pairs (run after
route_ss.py, before the autorouter; tracks and vias are locked).  Rev A's
geometry, unchanged; U3's common side and everything else is route_pairs.py's.

    J1 (USB A) -> U11 (ESD) -> U3 port 1          F.Cu only
    J2 (USB B) -> U12 (ESD) -> U3 port 2          F.Cu, B.Cu under the
                                                  Type-B row, F.Cu

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

from layout import PC_X  # noqa: E402

DX = PC_X - 17.0


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
    the same point (cleanup treats a 1 nm gap as an unconnected stub).  Also
    where the block shift is applied: the coordinates in main() were drawn
    with USB A at x = 17."""
    return (round(p[0] + DX, 4), round(p[1], 4))


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

    # GND bridge under each ESD part: its two GND pins (3, 8) are joined
    # straight across the body, so one plane via (from fanout) serves both
    for ref in ("U11", "U12"):
        g = [q for q in board.FindFootprintByReference(ref).Pads() if q.GetNumber() in ("3", "8")]
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(g[0].GetPosition())
        t.SetEnd(g[1].GetPosition())
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
        x += DX
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

    pcbnew.SaveBoard(PCB, board)
    for name, pr in result.items():
        lp, ln = pr.len["P"], pr.len["N"]
        print(f"  {name:17} D+ {lp:6.2f} mm  D- {ln:6.2f} mm  skew {abs(lp - ln):.3f} mm"
              f"  vias {pr.vias}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
