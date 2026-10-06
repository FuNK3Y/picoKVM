"""
Manufacturing checks beyond KiCad's DRC, tuned to what JLCDFM flags.
Run on the routed board (default out/kvm_board.kicad_pcb):

    python3 hw/checks.py [board.kicad_pcb]

  via_pad    no via within VIA_PAD mm of any pad, any net (solder wicking,
             thin mask web; JLCDFM "via to pad" / "pad spacing")
  tht_smd    no SMD pad within THT_SMD mm of another part's plated
             through-hole pad (JLC hand-solders THT after reflow; "tht to smd")
  mask       no track within MASK mm of a solder-mask opening it does not
             enter ("solder mask opening exposing trace"): another net fails,
             the same net is only reported (harmless, but JLCDFM flags it)
  usb2_skew  D+/D- copper path length, connector -> USB 2.0 switch, equal
             within SKEW mm for each switched pair

Exit status 1 if any check fails.
"""

import collections
import heapq
import os
import sys

import pcbnew

VIA_PAD = 0.11
THT_SMD = 2.03
MASK = 0.08
SKEW = 0.1
# connector -> TS3USB221A (U3) pins per pair
USB2 = {"PCA": ("J1", ("1", "2")), "PCB": ("J2", ("3", "4")), "PER": ("J3", ("8", "7"))}

mm, MM = pcbnew.ToMM, pcbnew.FromMM
failures = []


def report(name, bad, warn=()):
    print(f"{name:9} {'FAIL' if bad else 'ok'}" + (f"  ({len(warn)} same-net notes)" if warn else ""))
    for line in bad:
        print("   ", line)
    for line in warn:
        print("    note:", line)
    if bad:
        failures.append(name)


def poly(pad, layer):
    s = pcbnew.SHAPE_POLY_SET()
    pad.TransformShapeToPolygon(s, layer, 0, MM(0.002), pcbnew.ERROR_OUTSIDE)
    return s


def gap(shape, seg_or_pt, half_width, limit):
    """Smallest g in [0, limit] at which the item reaches the shape (None if
    it is further than limit, 0 if it already overlaps)."""
    if shape.Collide(seg_or_pt, half_width):
        return 0.0
    if not shape.Collide(seg_or_pt, half_width + MM(limit)):
        return None
    lo, hi = 0.0, limit
    for _ in range(12):
        m = (lo + hi) / 2
        if shape.Collide(seg_or_pt, half_width + MM(m)):
            hi = m
        else:
            lo = m
    return hi


def name(pad):
    return f"{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}"


def check_via_pad(board, pads):
    bad = []
    for v in (t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"):
        c, r = v.GetPosition(), v.GetWidth(pcbnew.F_Cu) // 2
        for p in pads:
            q = p.GetPosition()
            if abs(q.x - c.x) > MM(4) or abs(q.y - c.y) > MM(4):
                continue
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if p.IsOnLayer(layer):
                    g = gap(poly(p, layer), pcbnew.VECTOR2I(c.x, c.y), r, VIA_PAD)
                    if g is not None and g > 0:
                        bad.append(f"via {v.GetNetname()} ({mm(c.x):.2f}, {mm(c.y):.2f}) "
                                   f"{g:.3f} mm from {name(p)} {p.GetNetname()}")
                        break
    report("via_pad", bad)


def check_tht_smd(board, pads):
    tht = [p for p in pads if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and p.GetSize().x > 0]
    smd = [p for p in pads if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(pcbnew.F_Cu)]
    bad = []
    for t in tht:
        tb = t.GetBoundingBox()
        for s in smd:
            if s.GetParentFootprint().GetReference() == t.GetParentFootprint().GetReference():
                continue
            sb = s.GetBoundingBox()
            if t.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                c, r = t.GetPosition(), mm(t.GetSize().x) / 2
                cx = min(max(mm(c.x), mm(sb.GetLeft())), mm(sb.GetRight()))
                cy = min(max(mm(c.y), mm(sb.GetTop())), mm(sb.GetBottom()))
                d = ((cx - mm(c.x)) ** 2 + (cy - mm(c.y)) ** 2) ** 0.5 - r
            else:
                dx = max(mm(sb.GetLeft()) - mm(tb.GetRight()), mm(tb.GetLeft()) - mm(sb.GetRight()), 0)
                dy = max(mm(sb.GetTop()) - mm(tb.GetBottom()), mm(tb.GetTop()) - mm(sb.GetBottom()), 0)
                d = (dx * dx + dy * dy) ** 0.5
            if d < THT_SMD:
                bad.append(f"{name(s)} {d:.2f} mm from {name(t)}")
    report("tht_smd", bad)


def check_mask(board):
    bad, warn = [], []
    for cu, mask in ((pcbnew.F_Cu, pcbnew.F_Mask), (pcbnew.B_Cu, pcbnew.B_Mask)):
        tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == cu]
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if not p.IsOnLayer(mask):
                    continue
                opening = poly(p, mask)
                box = p.GetBoundingBox()
                box.Inflate(MM(0.5))
                for t in tracks:
                    if not box.Intersects(t.GetBoundingBox()):
                        continue
                    g = gap(opening, pcbnew.SEG(t.GetStart(), t.GetEnd()), t.GetWidth() // 2, MASK)
                    if g is None or g == 0:
                        continue
                    line = (f"{pcbnew.LayerName(cu)} {t.GetNetname()} track {g:.3f} mm from the "
                            f"opening of {name(p)} {p.GetNetname()}")
                    (warn if t.GetNetname() == p.GetNetname() else bad).append(line)
    report("mask", bad, sorted(set(warn)))


def path_length(board, net, a, b):
    """Shortest copper path (mm) between two pads, through vias."""
    key = lambda p: (p.x, p.y)
    g = collections.defaultdict(list)
    vias = set()
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            vias.add(key(t.GetPosition()))
            continue
        s, e, L = key(t.GetStart()), key(t.GetEnd()), mm(t.GetLength())
        g[(s, t.GetLayer())].append(((e, t.GetLayer()), L))
        g[(e, t.GetLayer())].append(((s, t.GetLayer()), L))
    for v in vias:
        layers = [n[1] for n in g if n[0] == v]
        for l1 in layers:
            for l2 in layers:
                if l1 != l2:
                    g[(v, l1)].append(((v, l2), 0.0))

    def on(pad):
        return {n for n in g if pad.IsOnLayer(n[1]) and pad.HitTest(pcbnew.VECTOR2I(*n[0]))}

    src, dst = on(a), on(b)
    dist = {n: 0.0 for n in src}
    pq = [(0.0, i, n) for i, n in enumerate(src)]
    tie = len(pq)
    while pq:
        d, _, n = heapq.heappop(pq)
        if n in dst:
            return d
        if d > dist.get(n, 1e9):
            continue
        for m, L in g[n]:
            if d + L < dist.get(m, 1e9):
                dist[m] = d + L
                tie += 1
                heapq.heappush(pq, (d + L, tie, m))
    return None


def check_usb2(board):
    bad, notes = [], []
    switch = {p.GetNumber(): p for p in board.FindFootprintByReference("U3").Pads()}
    for pair, (conn, (pin_p, pin_n)) in USB2.items():
        jp = {p.GetNetname(): p for p in board.FindFootprintByReference(conn).Pads()}
        lp = path_length(board, f"{pair}_DP", jp[f"{pair}_DP"], switch[pin_p])
        ln = path_length(board, f"{pair}_DN", jp[f"{pair}_DN"], switch[pin_n])
        if lp is None or ln is None:
            bad.append(f"{pair}: no copper path connector -> U3")
            continue
        line = f"{pair}: D+ {lp:.2f} mm, D- {ln:.2f} mm, skew {abs(lp - ln):.3f} mm"
        (bad if abs(lp - ln) > SKEW else notes).append(line)
    report("usb2_skew", bad)
    for line in notes:
        print("   ", line)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "out/kvm_board.kicad_pcb"
    board = pcbnew.LoadBoard(path)
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    print(f"checks on {path}")
    check_via_pad(board, pads)
    check_tht_smd(board, pads)
    check_mask(board)
    check_usb2(board)
    print("checks:", "FAILED " + ", ".join(failures) if failures else "all passed")
    sys.stdout.flush()
    os._exit(1 if failures else 0)


if __name__ == "__main__":
    main()
