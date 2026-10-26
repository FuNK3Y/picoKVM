"""
Deliberate routing of the six USB 3.0 SuperSpeed pairs (run before the
autorouter; the tracks are locked so Freerouting keeps them).

Each pair is a hand-designed centreline (45-degree corners) turned into two
coupled tracks at USB_DIFF width/gap, with symmetric fan-ins to the pads.
Corners come in opposite pairs, so intra-pair skew cancels.  Path:

    J1/J2 (Type-B) -> U17/U18 (ESD, flow-through) -> U2 (HD3SS3212)
    U2 -> U19 (ESD, flow-through) -> J3 (Type-A)

The USB B group is the mirror image of the USB A group about U2's centre.
Everything is on F.Cu over the In1 GND plane, no vias.
"""

import math

import os
import sys

import pcbnew

PCB = "out/kvm_board.kicad_pcb"
W, GAP = 0.15, 0.15          # USB_DIFF net class
PITCH = W + GAP
mm = pcbnew.FromMM
DX = 3.0                     # USB block shift vs the original layout (make_pcb ANCHORS)
MIRROR_X = 23.0 + DX         # U2 centre

# Centrelines (mm).  Pads are entered/left heading down (+y); P is on the
# left of the direction of travel everywhere, matching every pad row.
PCA = {
    # J1 -> U17
    ("J1", "U17", "PCA_SSRX"): [(10.625, 18.2), (13.25, 20.825), (13.25, 22.9)],
    ("J1", "U17", "PCA_SSTX"): [(17.375, 18.2), (14.75, 20.825), (14.75, 22.9)],
    # U17 -> U2
    ("U17", "U2", "PCA_SSRX"): [(13.25, 25.3), (16.25, 28.3), (18.75, 28.3),
                                (21.5, 31.05), (21.5, 31.9)],
    ("U17", "U2", "PCA_SSTX"): [(14.75, 25.3), (16.75, 27.3), (19.05, 27.3),
                                (22.5, 30.75), (22.5, 31.9)],
}
PER = {
    ("U2", "U19", "PER_SSTX"): [(22.0, 35.9), (22.0, 44.0), (22.25, 44.25), (22.25, 53.0)],
    ("U2", "U19", "PER_SSRX"): [(24.0, 35.9), (24.0, 44.0), (23.75, 44.25), (23.75, 53.0)],
    ("U19", "J3", "PER_SSTX"): [(22.25, 55.0), (20.0, 57.25), (20.0, 58.4)],
    ("U19", "J3", "PER_SSRX"): [(23.75, 55.0), (26.0, 57.25), (26.0, 58.4)],
}
# apply the block shift
PCA = {k: [(x + DX, y) for x, y in v] for k, v in PCA.items()}
PER = {k: [(x + DX, y) for x, y in v] for k, v in PER.items()}

MIRROR = {"J1": "J2", "U17": "U18", "U2": "U2", "PCA_SSRX": "PCB_SSTX",
          "PCA_SSTX": "PCB_SSRX"}
# flow-through ESD parts: P/N pass from the top pad to the bottom pad
ESD = ("U17", "U18", "U19")


def mirrored(routes):
    out = {}
    for (a, b, pair), pts in routes.items():
        out[(MIRROR[a], MIRROR[b], MIRROR[pair])] = [(2 * MIRROR_X - x, y) for x, y in pts]
    return out


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


def fan(pad, cpl, toward_pad_down):
    """Pad -> coupled point: straight along y, then 45 degrees sideways."""
    px, py = pad
    cx, cy = cpl
    h = abs(cx - px)
    ymid = cy + h if toward_pad_down else cy - h
    return [(px, py), (px, ymid), (cx, cy)]


def pad_xy(board, ref, net):
    fp = board.FindFootprintByReference(ref)
    pads = [p for p in fp.Pads() if p.GetNetname() == net]
    if ref in ESD:   # two pads per net: top (entry) and bottom (exit)
        pads.sort(key=lambda p: p.GetPosition().y)
        return [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in pads]
    p = pads[0]
    return [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))]


def add_track(board, net, pts):
    for a, b in zip(pts, pts[1:]):
        if a == b:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        t.SetWidth(mm(W))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(board.FindNet(net))
        t.SetLocked(True)
        board.Add(t)


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def main():
    board = pcbnew.LoadBoard(PCB)
    routes = {**PCA, **mirrored(PCA), **PER}
    total = {}
    for (src, dst, pair), centre in routes.items():
        for sfx, d in (("_P", PITCH / 2), ("_N", -PITCH / 2)):
            net = pair + sfx
            line = offset(centre, d)
            start = pad_xy(board, src, net)[-1]   # bottom pad of an ESD part
            end = pad_xy(board, dst, net)[0]      # top pad of an ESD part
            pts = fan(start, line[0], False)[:-1] + line + fan(end, line[-1], True)[::-1][1:]
            add_track(board, net, pts)
            total[net] = total.get(net, 0.0) + length(pts)
    # straight runs through the flow-through ESD parts
    for ref in ESD:
        fp = board.FindFootprintByReference(ref)
        for net in {p.GetNetname() for p in fp.Pads() if "_SS" in p.GetNetname()}:
            top, bot = pad_xy(board, ref, net)
            add_track(board, net, [top, bot])
            total[net] += length([top, bot])
    pcbnew.SaveBoard(PCB, board)
    for pair in sorted({n[:-2] for n in total}):
        p, n = total[pair + "_P"], total[pair + "_N"]
        print(f"  {pair:9} P {p:6.2f} mm  N {n:6.2f} mm  skew {abs(p - n):.3f} mm")


if __name__ == "__main__":
    main()
    # KiCad's SWIG bindings can segfault in destructors at interpreter exit;
    # the work is saved by now, so leave without running them
    sys.stdout.flush()
    os._exit(0)
