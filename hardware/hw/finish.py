"""
Via work around the autorouter, on out/kvm_board.kicad_pcb.

  python3 finish.py fanout   before routing: power pins narrower than the
                             POWER track get a neck-down stub; every SMD pad
                             on a plane net (GND -> In1, +3V3 -> In2) gets a
                             stub + via, so Freerouting only routes signals
  python3 finish.py stitch   after routing: GND stitching vias on a grid,
                             tying the F/B pours to In1

Every candidate via/track is checked against all other-net copper first.
"""

import math
import sys

import os
import pcbnew

PCB = "out/kvm_board.kicad_pcb"
mm = pcbnew.FromMM
VIA_D, VIA_DRILL = 0.45, 0.3       # GND (Default net class); 0.3 mm = JLC free tier
VIA_SIZE = {"+3V3": (0.5, 0.3)}    # POWER net class
HOLE_GAP_PAD = 0.5                 # drill edge to a pin's drill (JLC 0.45)
HOLE_GAP_VIA = 0.25                # drill edge to another via's drill (JLC 0.2)
CLEAR = 0.15          # via/stub to other-net copper (board min 0.127)
VIA_PAD_GAP = 0.2     # via copper to any SMD pad, same net too: a via at a
                      # pad edge wicks solder away from the joint (JLC DFM)
GRID = 4.0            # stitching pitch (mm)
DIFF_CLEAR = 0.5      # keep stitching vias this far from USB pairs
PLANE_NETS = ("GND", "+3V3")
ALL_CU = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]


class Copper:
    """Other-net copper items, for collision checks."""

    def __init__(self, board):
        self.items = []
        for fp in board.GetFootprints():
            self.items.extend(fp.Pads())
        self.items.extend(board.GetTracks())
        self.holes = [p for fp in board.GetFootprints() for p in fp.Pads()
                      if p.GetDrillSize().x]
        # board-level keep-outs (e.g. the ESP32 antenna area)
        # board-level and footprint-level keep-outs (e.g. the ESP32 antenna)
        zones = list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
        self.keepouts = [z for z in zones
                         if z.GetIsRuleArea() and z.GetDoNotAllowVias()]

    def add(self, item):
        self.items.append(item)

    def on_pad(self, item, gap=VIA_PAD_GAP):
        """True if the item comes within gap of any pad, SMD or through-hole,
        whatever its net (no vias in or at the edge of solder pads: the mask
        web between them would be too thin).  Uses the real pad outline, so
        custom-polygon pads count at their true size."""
        for it in self.items:
            if it.GetClass() == "PAD" and it.IsOnLayer(pcbnew.F_Cu) and \
                    it.GetEffectiveShape(pcbnew.F_Cu).Collide(
                        item.GetEffectiveShape(pcbnew.F_Cu), mm(gap)):
                return True
        return False

    def in_keepout(self, item):
        if item.GetClass() == "PCB_VIA":   # whole copper ring + clearance
            c, r = item.GetPosition(), item.GetWidth(pcbnew.F_Cu) // 2 + mm(CLEAR)
            pts = [c] + [pcbnew.VECTOR2I(c.x + int(r * math.cos(a)), c.y + int(r * math.sin(a)))
                         for a in (k * math.pi / 8 for k in range(16))]
        else:
            a, b = item.GetStart(), item.GetEnd()
            pts = [pcbnew.VECTOR2I(a.x + (b.x - a.x) * k // 8, a.y + (b.y - a.y) * k // 8)
                   for k in range(9)]
            # widen by half the track width + clearance, both sides
            w = item.GetWidth() // 2 + mm(CLEAR)
            pts += [pcbnew.VECTOR2I(p.x + dx, p.y + dy) for p in list(pts)
                    for dx, dy in ((w, 0), (-w, 0), (0, w), (0, -w))]
        return any(z.Outline().Contains(p) for z in self.keepouts for p in pts)

    def clear(self, item, layers, net, clearance=CLEAR, diff_clear=None):
        if self.in_keepout(item):
            return False
        for it in self.items:
            if it.GetNetCode() == net.GetNetCode() and it.GetNetCode() != 0:
                continue
            cl = clearance
            if diff_clear and it.GetNetname().startswith(("PCA_", "PCB_", "PER_")):
                cl = diff_clear
            for layer in layers:
                if it.IsOnLayer(layer) and item.IsOnLayer(layer) and \
                        it.GetEffectiveShape(layer).Collide(
                            item.GetEffectiveShape(layer), mm(cl)):
                    return False
        if item.GetClass() == "PCB_VIA":
            # drill spacing applies whatever the nets (JLC drilling limits)
            r = item.GetDrillValue() / 2
            for h in self.holes:
                if (h.GetPosition() - item.GetPosition()).EuclideanNorm() < \
                        h.GetDrillSize().x / 2 + r + mm(HOLE_GAP_PAD):
                    return False
            for v in self.items:
                if v is not item and v.GetClass() == "PCB_VIA" and \
                        (v.GetPosition() - item.GetPosition()).EuclideanNorm() < \
                        v.GetDrillValue() / 2 + r + mm(HOLE_GAP_VIA):
                    return False
        return True


def via(board, net, p):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(p)
    d, drill = VIA_SIZE.get(net.GetNetname(), (VIA_D, VIA_DRILL))
    v.SetWidth(mm(d))
    v.SetDrill(mm(drill))
    v.SetNet(net)
    v.SetLocked(True)   # kept through the autorouter round-trip
    return v


def track(board, net, a, b, layer, w=0.2):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(a)
    t.SetEnd(b)
    t.SetWidth(mm(w))
    t.SetLayer(layer)
    t.SetNet(net)
    t.SetLocked(True)
    return t


def inside(bb, p, margin=0.8):
    return (bb.GetLeft() + mm(margin) < p.x < bb.GetRight() - mm(margin) and
            bb.GetTop() + mm(margin) < p.y < bb.GetBottom() - mm(margin))


def fanout(board):
    cu = Copper(board)
    bb = board.GetBoardEdgesBoundingBox()
    placed, failed = 0, []

    def is_ep(pad):
        size = pad.GetSize(pcbnew.F_Cu)
        return pcbnew.ToMM(size.x) >= 1.0 and pcbnew.ToMM(size.y) >= 1.0

    def same_net_ep(fp, pad):
        return next((p for p in fp.Pads() if p is not pad and is_ep(p)
                     and not p.GetDrillSize().x
                     and p.GetNetCode() == pad.GetNetCode()), None)

    def has_same_net_pins(fp, ep):
        return any(p is not ep and not is_ep(p) and p.GetNetCode() == ep.GetNetCode()
                   for p in fp.Pads())

    work = [(fp, pad) for fp in board.GetFootprints() for pad in fp.Pads()
            if pad.GetNetname() in PLANE_NETS and not pad.GetDrillSize().x]
    # pins already reached through a same-net exposed pad go last: their
    # extra via is a bonus and must not take the only spot a neighbour has
    work.sort(key=lambda fp_pad: same_net_ep(*fp_pad) is not None)
    for fp, pad in work:
        net = pad.GetNet()
        c = pad.GetPosition()
        size = pad.GetSize(pcbnew.F_Cu)
        # No vias inside exposed pads (solder would wick into them).  An
        # exposed pad with same-net pins around it is reached through those
        # pins; the ESP32's thermal pad has its own vias in the footprint.
        if is_ep(pad) and (fp.GetReference() == "U1" or has_same_net_pins(fp, pad)):
            continue
        # already joined by a pre-routed track to a same-net pad of the same
        # part (e.g. route_usb2.py's GND bridge under the ESD parts) whose
        # partner gets the via
        tied = False
        bridge = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"
                  and t.GetNetCode() == pad.GetNetCode()
                  and (pad.HitTest(t.GetStart()) or pad.HitTest(t.GetEnd()))
                  and any(q is not pad and q.GetNetCode() == pad.GetNetCode()
                          and (q.HitTest(t.GetStart()) or q.HitTest(t.GetEnd()))
                          for q in fp.Pads())]
        if bridge and fp.GetReference() in ("U11", "U12", "U13") and pad.GetNumber() == "8":
            placed += 1
            continue
        # a pin next to an exposed pad of the same net joins it inward ...
        ep = same_net_ep(fp, pad)
        if ep is not None:
            t = track(board, net, c, ep.GetPosition(), pcbnew.F_Cu)
            if cu.clear(t, [pcbnew.F_Cu], net):
                board.Add(t); cu.add(t); tied = True
        # ... and every pad gets its own stub + via outward, away from the
        # footprint centre, sweeping round if that direction is blocked
        d = c - fp.GetPosition()
        a0 = math.atan2(d.y, d.x) if d.EuclideanNorm() else 0.0
        half = max(size.x, size.y) / 2
        done = False
        for r in (0.45, 0.65, 0.9, 1.2, 1.6, 2.0, 2.5):
            for k in range(24):
                a = a0 + (k + 1) // 2 * (1 if k % 2 else -1) * math.pi / 12
                p = c + pcbnew.VECTOR2I(int((half + mm(r)) * math.cos(a)),
                                        int((half + mm(r)) * math.sin(a)))
                if not inside(bb, p):
                    continue
                v = via(board, net, p)
                t = track(board, net, c, p, pcbnew.F_Cu)
                if cu.clear(v, ALL_CU, net) and cu.clear(t, [pcbnew.F_Cu], net) \
                        and not cu.on_pad(v):
                    for it in (v, t):
                        board.Add(it); cu.add(it)
                    done = True
                    break
            if done:
                break
        if done or tied:
            placed += 1
        else:
            failed.append(f"{fp.GetReference()}.{pad.GetNumber()}")
    print(f"fanout: {placed} pads, failed: {failed or 'none'}")


POWER_TRACK = 0.4    # POWER net class width (make_pcb.py)
NECK_LEN = 0.6       # stub length beyond the pad edge


def necks(board):
    """Power pins narrower than the POWER track width get a locked stub at
    pin width, so the autorouter (which can't neck down) can attach."""
    cu = Copper(board)
    n = 0
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            name = pad.GetNetname()
            if not (name.startswith("VBUS") or name == "+5V_SYS") or pad.GetDrillSize().x:
                continue
            size = pad.GetSize(pcbnew.F_Cu)
            w, l = min(size.x, size.y), max(size.x, size.y)
            if pcbnew.ToMM(w) >= POWER_TRACK:
                continue
            c = pad.GetPosition()
            d = c - fp.GetPosition()
            # stub along the pad's long axis, away from the part
            horiz = (size.x > size.y) != (round(pad.GetOrientationDegrees()) % 180 == 90)
            if horiz:
                sgn = 1 if d.x >= 0 else -1
                e = c + pcbnew.VECTOR2I(sgn * int(l / 2 + mm(NECK_LEN)), 0)
            else:
                sgn = 1 if d.y >= 0 else -1
                e = c + pcbnew.VECTOR2I(0, sgn * int(l / 2 + mm(NECK_LEN)))
            t = track(board, pad.GetNet(), c, e, pcbnew.F_Cu, pcbnew.ToMM(w))
            if cu.clear(t, [pcbnew.F_Cu], pad.GetNet()):
                board.Add(t); cu.add(t); n += 1
    # same-net power pins of one part (e.g. TPS2116 VOUT 2/7) tied directly
    ties = 0
    for fp in board.GetFootprints():
        by_net = {}
        for pad in fp.Pads():
            if pad.GetNetname().startswith("VBUS") and not pad.GetDrillSize().x:
                by_net.setdefault(pad.GetNetname(), []).append(pad)
        for pads in by_net.values():
            for a, b in zip(pads, pads[1:]):
                w = min(min(a.GetSize(pcbnew.F_Cu).x, a.GetSize(pcbnew.F_Cu).y),
                        min(b.GetSize(pcbnew.F_Cu).x, b.GetSize(pcbnew.F_Cu).y))
                t = track(board, a.GetNet(), a.GetPosition(), b.GetPosition(),
                          pcbnew.F_Cu, pcbnew.ToMM(w))
                if cu.clear(t, [pcbnew.F_Cu], a.GetNet()):
                    board.Add(t); cu.add(t); ties += 1
    print(f"power neck-downs: {n}, same-part ties: {ties}")


def stitch(board):
    cu = Copper(board)
    gnd = board.FindNet("GND")
    bb = board.GetBoardEdgesBoundingBox()
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    n = 0
    y = bb.GetTop() + mm(GRID / 2)
    while y < bb.GetBottom():
        x = bb.GetLeft() + mm(GRID / 2)
        while x < bb.GetRight():
            p = pcbnew.VECTOR2I(x, y)
            if inside(bb, p, 1.0) and \
                    all((v.GetPosition() - p).EuclideanNorm() > mm(1.5) for v in vias):
                v = via(board, gnd, p)
                if cu.clear(v, ALL_CU, gnd, diff_clear=DIFF_CLEAR) and not cu.on_pad(v):
                    board.Add(v); cu.add(v); vias.append(v); n += 1
            x += mm(GRID)
        y += mm(GRID)
    # drop stitching vias that ended up reaching the pours on <2 layers
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    gz = [z for z in board.Zones() if z.GetNetCode() == gnd.GetNetCode()]
    dead = [v for v in vias[-n:] if n and sum(
        1 for z in gz for layer in z.GetLayerSet().Seq()
        if z.HitTestFilledArea(layer, v.GetPosition())) < 2]
    for v in dead:
        board.Remove(v)
    print(f"stitching vias: {n - len(dead)}")


def main():
    board = pcbnew.LoadBoard(PCB)
    {"fanout": lambda b: (necks(b), fanout(b)), "stitch": stitch}[sys.argv[1]](board)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)


if __name__ == "__main__":
    main()
    # KiCad's SWIG bindings can segfault in destructors at interpreter exit;
    # the work is saved by now, so leave without running them
    sys.stdout.flush()
    os._exit(0)
