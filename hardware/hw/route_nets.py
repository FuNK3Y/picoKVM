"""
Nets routed before the autorouter (after finish.py fanout; tracks and vias
are locked, so Freerouting keeps them).

Freerouting closes almost everything, but every run left a few of the same
kind of net open, and the board needs them done for certain:

  * single-ended signals that cross a crowded board (NETS): the hub's
    port-control lines, which run from its east pins to the port power
    switches at the west edge; its other slow pins; the RP2350's QSPI bus
    and host-side USB lines;
  * the power nets in JOIN_NETS (+1V1): every fanout via, stub and pad is
    tied into one tree of tracks.  Their B.Cu pour alone can't be trusted
    once signals cross it, and Freerouting doesn't reliably close what the
    pour leaves open.  The tree goes in after the signals and finds its way
    round them (laid first, it walled the hub's east-side pins in).

A two-layer A* on a 0.05 mm grid (F.Cu / B.Cu, vias between them) over the
copper map of pairs.Router.  A signal net grows as a tree from its first
pad; a power net from its biggest connected group.  Every track and via is
checked once more against the real copper (finish.Copper) before it goes
in; what fails is left to the autorouter and reported.  The signals are
tried in a few orders (the ones that failed moved to the front each time);
the best result is kept.

    python3 route_nets.py
"""

import fnmatch
import heapq
import json
import math
import os
import sys

import numpy as np
import pcbnew
from scipy import ndimage

import finish
from pairs import F, B, Router, RES

PCB = os.environ.get("ROUTE_NETS_PCB", "out/kvm_board.kicad_pcb")   # (override: tests on a copy)
NETS = [
    # the hub's crystal loop before anything can come between (layout.py Y1)
    "HUB_XI", "HUB_XO",
    # the hub's port-control lines first: ports 3/4's switches stand between
    # the hub's and their own capacitors, with little room left to reach EN
    "P3_PWR_EN", "P4_PWR_EN", "P3_OC_N", "P4_OC_N",
    # ports 1/2's switches share the front-west corner, ~55-65 mm from the
    # hub: port 2's EN (U34 pin 3, under U33) first, or it is walled in
    "P2_PWR_EN", "P2_OC_N", "P1_OC_N", "P1_PWR_EN",
    # the regulators' switch nodes and feedback: tiny loops between parts
    # placed for them (layout.py _buck)
    "U5_SW", "U31_SW", "U5_FB", "U31_FB",
    # the RP2350's QSPI bus (short, boxed in by the chip's 0.4 mm pitch).
    # Before the trunks: laid after them, SD1 / SCLK were left open.
    # (SD1 / SD2 cross between the chip's pins 59/58 and the flash's 2/3: in
    # any other order one of the six was left open; SD3 goes round, 39 mm)
    "RP_QSPI_SD2", "RP_QSPI_SS", "RP_QSPI_SD1", "RP_QSPI_SD0", "RP_QSPI_SCLK", "RP_QSPI_SD3",
    # the port supply path, wide (POWER_TRUNKS): PC connectors -> source
    # select -> AUX priority mux -> four port switches -> connectors.  At
    # 0.3-0.4 mm (Freerouting's) it measured ~0.5 ohm PC-to-port, 0.25 V at
    # 0.5 A.  Laid before the long signals so they get the straight runs;
    # the board grew 6 mm (layout.py) to make the room.
    "VBUS_HUB", "VBUS_PC", "VBUS_A", "VBUS_B",
    "VBUS_P1", "VBUS_P2", "VBUS_P3", "VBUS_P4",
    # its east-side lines to the ESP32 link and D5 (Freerouting left them
    # open): GPIO26 (pin 40) first, through the gap kept for it in the
    # capacitor rows, then the LED (pin 37) round it
    "RP_GPIO26", "RP_LED",
    # the hub's other short slow pins, and the RP2350's host-side USB (full
    # speed).  Long nets stay with Freerouting, which can rip up and retry:
    # laid first here, HUB_SDA / HUB_SCL (hub -> U13) went round the RP2350's
    # south side and fenced in its crystal, SWD and GPIO20-22.
    "HUB_VBUS_DET", "HUB_R1", "HUB_SMBUSZ", "RP_HOST_DP", "RP_HOST_DN",
    # and its device-side USB (full speed) to its 27R, past the flash's resistors
    # (D- first: its pin 51 and its 27R are on the inside, D+ wraps round it)
    "RP_USB_DN", "RP_USB_DP",
    # last, so they only take what the others left: the RP2350's crystal
    # loop (left open by one Freerouting run).  Not the ESP32's programming
    # lines to the flash taps: locked in early, they lay across the hub's
    # I2C lines' way east to U13 and those stayed open in every run.
    "RP_XIN", "RP_XOUT", "RP_XOUT_R",
    # and its reset (pin 50, north side): left to Freerouting, the +1V1 tree
    # (joined after the signals) boxed the pin in on F.Cu every time
    # the hub's SMBus to U13: with the HDMI DDC parts in the band below the
    # RP2350 every Freerouting run left this pair open
    "HUB_SDA", "HUB_SCL",
    "HUB_RESET_N",
    ]
JOIN_NETS = ("+1V1",)
# after the power trees: ports 3/4's VBUS as trunks (TRUNKS below).  Their
# switches sit by the hub, ~35 mm from J10; left to Freerouting, 4 runs in 6
# sent port 3's round the board (107-149 mm).  Laid before the +1V1 tree they
# cut it off from the hub's east pins.
LATE_NETS = ()
# pins tied straight to a same-net pad of their own part: (ref, pin, pad).
# The RP2350's pin 50 (GND) has no room for a fanout via between its
# neighbours; the HDMI stacks' DDC grounds (17 / P17) sit in a through-hole
# pin field where no pour gets between the unconnected TMDS pins, so they are
# tied to the shell (pad 0)
TIES = [("U45", "50", "61"),
        ("J5", "17", "0"), ("J5", "P17", "0"), ("J6", "17", "0"), ("J6", "P17", "0")]

# Signals: 0.15 mm fits between 0.4 mm-pitch pins.  0.13 mm clearance: the
# board's custom rules (0.1 pad-track, 0.09 track-track) don't cover vias, so
# a track next to a via falls back to the Default class's 0.127 mm.
W, CLR = 0.15, 0.13
# Port supply trunks: as wide as the way allows (one width per trunk).
# Only the pads listed in POWER_TRUNKS: the fine-pitch IC pins (TPS2116's
# 0.5 mm SOT-583) take a 0.4 mm track at most, so the trunks end on the
# capacitor beside such a pin and Freerouting adds the 2-3 mm from there.
TRUNK_W = (1.0, 0.8, 0.6, 0.4)
POWER_TRUNKS = {
    "VBUS_HUB": (("C8", "1"), ("C9", "1"), ("U33", "1"), ("U34", "1"), ("C10", "1"), ("U35", "1"), ("U36", "1")),
    "VBUS_PC": (("C6", "1"), ("C27", "1")),
    "VBUS_A": (("J1", "1"), ("C4", "1"), ("C23", "1")),
    "VBUS_B": (("J2", "1"), ("C5", "1"), ("C24", "1")),
    "VBUS_P1": (("U33", "6"), ("J3", "10")),
    "VBUS_P2": (("U34", "6"), ("J3", "1")),
    "VBUS_P3": (("U35", "6"), ("J10", "10")),
    "VBUS_P4": (("U36", "6"), ("J10", "1")),
}
NET_W = {"U5_SW": 0.4, "U31_SW": 0.4, **{n: TRUNK_W for n in POWER_TRUNKS},
         **{f"RP_QSPI_{n}": (0.15, 0.13, 0.11) for n in ("SD0", "SD1", "SD2", "SD3", "SCLK", "SS")}}    # switch nodes: POWER class width


def class_clearance(name):
    """The clearance of the net's class if it isn't Default (USB_DIFF asks
    0.15 mm), so a net is never laid closer than its class allows; 0 for
    Default nets, which follow the board's custom rules instead."""
    pro = os.path.splitext(PCB)[0] + ".kicad_pro"
    try:
        ns = json.load(open(pro))["net_settings"]
    except (OSError, KeyError, ValueError):
        return 0.0
    cls = next((p["netclass"] for p in ns.get("netclass_patterns", [])
                if fnmatch.fnmatchcase(name, p["pattern"])), "Default")
    if cls == "Default":
        return 0.0
    return next((c.get("clearance", 0.0) for c in ns["classes"] if c["name"] == cls), 0.0)
# Power: 0.3 mm (the hub's and the RP2350's cores draw well under an amp),
# 0.25 where a via is boxed in.  The tree keeps to B.Cu, under its pour: an
# F.Cu cell costs JOIN_F_COST times a B.Cu one, so it only hops over a
# signal there (with 0.4 mm tracks on both layers it took the room the
# RP2350's pins need to get out).
JOIN_WIDTHS = (0.3, 0.25)
JOIN_F_COST = 6.0
PAIR_GAP = 0.25       # to the routed USB pairs' copper (crosstalk)
VIA_COST = 50         # in grid cells (2.5 mm of track)
TURN_COST = 4
MARGIN = 6.0          # how far outside the box around its ends a search may wander
JOIN_MARGIN = 10.0
NET_MARGIN = {n: 12.0 for n in ("RP_QSPI_SD2", "RP_QSPI_SS", "RP_QSPI_SD1", "RP_QSPI_SD0", "RP_QSPI_SCLK", "RP_QSPI_SD3")}
ROUNDS = 4
MM = pcbnew.ToMM
mm = pcbnew.FromMM
V = pcbnew.VECTOR2I


class Grid:
    """pairs.Router's copper map, plus every pad (any net) and every drill."""

    def __init__(self, board):
        self.board = board
        self.r = r = Router(board)
        self.x0, self.y0 = r.x0, r.y0
        self.ny, self.nx = r.label[F].shape
        self.padmask = np.zeros((self.ny, self.nx), bool)
        self.holes = np.zeros((self.ny, self.nx), bool)
        for fp in board.GetFootprints():
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                sl, (X, Y) = r._box(MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom()))
                self.padmask[sl] |= (X >= MM(bb.GetLeft())) & (X <= MM(bb.GetRight())) & \
                                    (Y >= MM(bb.GetTop())) & (Y <= MM(bb.GetBottom()))
                if p.GetDrillSize().x:
                    self.hole((MM(p.GetPosition().x), MM(p.GetPosition().y)), MM(p.GetDrillSize().x) / 2)
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                self.hole((MM(t.GetPosition().x), MM(t.GetPosition().y)), MM(t.GetDrillValue()) / 2)
            # Router only marks PCA_/PCB_ tracks as pair copper: every USB
            # pair's tracks and vias keep PAIR_GAP here
            if finish.is_pair(t.GetNetname()):
                if t.GetClass() == "PCB_VIA":
                    c = (MM(t.GetPosition().x), MM(t.GetPosition().y))
                    for layer in (F, B):
                        r.disc(layer, c, MM(t.GetWidth(F)) / 2, t.GetNetCode(), pair=True)
                else:
                    r.seg(t.GetLayer(), (MM(t.GetStart().x), MM(t.GetStart().y)),
                          (MM(t.GetEnd().x), MM(t.GetEnd().y)), MM(t.GetWidth()), t.GetNetCode(), pair=True)

    def hole(self, c, rr):
        sl, (X, Y) = self.r._box(c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr)
        self.holes[sl] |= (X - c[0]) ** 2 + (Y - c[1]) ** 2 <= rr * rr

    def cell(self, x, y):
        return int(round((x - self.x0) / RES)), int(round((y - self.y0) / RES))

    def pt(self, i, j):
        return self.x0 + i * RES, self.y0 + j * RES

    def maps(self, code, w, clr, via_d):
        """Per layer: where a w track of net `code` may run; where a via may go."""
        lab = self.r.label
        ok = {}
        for layer in (F, B):
            other = (lab[layer] != 0) & (lab[layer] != code)
            ok[layer] = ndimage.distance_transform_edt(~other) * RES >= w / 2 + clr + RES * 0.75
            op = other & self.r.pairs[layer]
            if op.any():
                ok[layer] &= ndimage.distance_transform_edt(~op) * RES >= w / 2 + PAIR_GAP
        via = np.ones((self.ny, self.nx), bool)
        for layer in (F, B):
            other = (lab[layer] != 0) & (lab[layer] != code)
            via &= ndimage.distance_transform_edt(~other) * RES >= via_d / 2 + finish.CLEAR + RES * 0.75
        # not in or at the edge of any pad, own net too; drill clear of other drills
        via &= ndimage.distance_transform_edt(~self.padmask) * RES >= via_d / 2 + finish.VIA_PAD_GAP + RES
        via &= ndimage.distance_transform_edt(~self.holes) * RES >= finish.VIA_DRILL / 2 + finish.HOLE_GAP_PAD
        return ok, via

    def pad_cells(self, p):
        out = []
        bb = p.GetBoundingBox()
        ia, ja = self.cell(MM(bb.GetLeft()), MM(bb.GetTop()))
        ib, jb = self.cell(MM(bb.GetRight()), MM(bb.GetBottom()))
        for layer in (F, B):
            if p.IsOnLayer(layer):
                out += [(i, j, layer) for i in range(ia, ib + 1) for j in range(ja, jb + 1)
                        if p.HitTest(V(mm(self.pt(i, j)[0]), mm(self.pt(i, j)[1])))]
        return out or [self.cell(MM(p.GetPosition().x), MM(p.GetPosition().y)) + (F,)]

    def item_cells(self, it):
        if it.GetClass() == "PAD":
            return self.pad_cells(it)
        if it.GetClass() == "PCB_VIA":
            c = self.cell(MM(it.GetPosition().x), MM(it.GetPosition().y))
            return [c + (F,), c + (B,)]
        a, b = it.GetStart(), it.GetEnd()
        n = max(1, int(MM((b - a).EuclideanNorm()) / RES))
        return [self.cell(MM(a.x + (b.x - a.x) * k / n), MM(a.y + (b.y - a.y) * k / n)) + (it.GetLayer(),)
                for k in range(n + 1)]

    def commit(self, cu, net, path, w, clr, small_via):
        """Path cells -> locked tracks and vias, after the exact copper check.
        Returns (items, None) or (None, reason)."""
        board, code = self.board, net.GetNetCode()
        runs, cur, vias = [], [path[0]], []
        for a, b in zip(path, path[1:]):
            if a[2] != b[2]:
                runs.append(cur); vias.append(self.pt(a[0], a[1])); cur = [b]
            else:
                cur.append(b)
        runs.append(cur)
        items = []
        for p in vias:
            v = finish.via(board, net, V(mm(p[0]), mm(p[1])), small=small_via)
            if not cu.clear(v, finish.ALL_CU, net) or cu.on_pad(v):
                return None, f"via at {p[0]:.2f},{p[1]:.2f} fails the copper check"
            items.append(v)
        for run in runs:
            keep = [run[0]] + [c for a, c, b in zip(run, run[1:], run[2:])
                               if (c[0] - a[0], c[1] - a[1]) != (b[0] - c[0], b[1] - c[1])] + [run[-1]]
            for a, b in zip(keep, keep[1:]):
                if a[:2] == b[:2]:      # a one-cell run between two vias: no track
                    continue
                pa, pb = self.pt(a[0], a[1]), self.pt(b[0], b[1])
                t = finish.track(board, net, V(mm(pa[0]), mm(pa[1])), V(mm(pb[0]), mm(pb[1])), a[2], w)
                if not cu.clear(t, [a[2]], net, clearance=clr):
                    return None, f"track at {pa[0]:.2f},{pa[1]:.2f} fails the copper check"
                items.append(t)
        for it in items:
            board.Add(it); cu.add(it)
            if it.GetClass() == "PCB_VIA":
                c = (MM(it.GetPosition().x), MM(it.GetPosition().y))
                for layer in (F, B):
                    self.r.disc(layer, c, MM(it.GetWidth(F)) / 2, code)
                self.hole(c, MM(it.GetDrillValue()) / 2)
            else:
                self.r.seg(it.GetLayer(), (MM(it.GetStart().x), MM(it.GetStart().y)),
                           (MM(it.GetEnd().x), MM(it.GetEnd().y)), MM(it.GetWidth()), code)
        return items, None

    def box(self, pts, margin):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ia, ja = self.cell(min(xs) - margin, min(ys) - margin)
        ib, jb = self.cell(max(xs) + margin, max(ys) + margin)
        return max(ia, 0), max(ja, 0), min(ib, self.nx - 1), min(jb, self.ny - 1)


def search(ok, via, starts, goals, box, f_cost=1.0):
    """Cheapest path from any start (i, j, layer) to any goal cell, inside
    box; a step on F.Cu costs f_cost times one on B.Cu."""
    i0, j0, i1, j1 = box
    goalset = set(goals)
    # heuristic: exact straight-line distance to the nearest goal cell
    gm = np.ones((j1 - j0 + 1, i1 - i0 + 1), bool)
    for i, j, _ in goals:
        if i0 <= i <= i1 and j0 <= j <= j1:
            gm[j - j0, i - i0] = False
    hmap = ndimage.distance_transform_edt(gm)
    dist, prev, heap = {}, {}, []
    for s in starts:
        if i0 <= s[0] <= i1 and j0 <= s[1] <= j1:
            dist[s] = 0.0
            heapq.heappush(heap, (hmap[s[1] - j0, s[0] - i0], 0.0, s, None))
    moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    while heap:
        _, g, n, dirn = heapq.heappop(heap)
        if g > dist.get(n, 1e18):
            continue
        if n in goalset:
            path = [n]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        i, j, l = n
        for di, dj, c in moves:
            a, b = i + di, j + dj
            if not (i0 <= a <= i1 and j0 <= b <= j1) or not ok[l][b, a]:
                continue
            ng = g + c * (f_cost if l == F else 1.0) + \
                (TURN_COST if dirn is not None and dirn != (di, dj) else 0)
            m = (a, b, l)
            if ng < dist.get(m, 1e18):
                dist[m], prev[m] = ng, n
                heapq.heappush(heap, (ng + hmap[b - j0, a - i0], ng, m, (di, dj)))
        if via[j, i]:
            m = (i, j, B if l == F else F)
            ng = g + VIA_COST
            if ng < dist.get(m, 1e18):
                dist[m], prev[m] = ng, n
                heapq.heappush(heap, (ng + hmap[j - j0, i - i0], ng, m, None))
    return None


def open_cells(ok, cells):
    """An item's own cells are always open to its net."""
    ny, nx = ok[F].shape
    for i, j, l in cells:
        if 0 <= i < nx and 0 <= j < ny:
            ok[l][j, i] = True


def route_net(g, cu, name, pads=None):
    """Route net `name` as a tree over all its pads (or just `pads`).  The
    grid search is a little optimistic next to odd pad shapes: when the
    exact copper check rejects the first branch, search again with a bit
    more clearance on the grid (nothing is committed until a branch passes)."""
    board = g.board
    net = board.FindNet(name)
    if pads is None:
        pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode() == net.GetNetCode()]
    if len(pads) < 2:
        return False, 0.0, f"{name}: {len(pads)} pad(s), nothing to do"
    ws = NET_W.get(name, W)
    ws = ws if isinstance(ws, tuple) else (ws,)     # a tuple: widths to fall back to
    clr = max(CLR, class_clearance(name) + 0.01)
    box = g.box([(MM(p.GetPosition().x), MM(p.GetPosition().y)) for p in pads], NET_MARGIN.get(name, MARGIN))
    why, skip = "no attempt", None
    for w, extra in [(w, e) for w in ws for e in (0.0, 0.03, 0.06)]:
        if w == skip:
            continue                # no path at this width: more clearance won't make one
        ok, via = g.maps(net.GetNetCode(), w, clr + extra, finish.VIA_D)
        for p in pads:
            open_cells(ok, g.pad_cells(p))
        tree, todo, paths = g.pad_cells(pads[0]), pads[1:], []
        while todo:
            todo.sort(key=lambda p: min(math.hypot(MM(p.GetPosition().x) - g.pt(i, j)[0],
                                                   MM(p.GetPosition().y) - g.pt(i, j)[1]) for i, j, _ in tree))
            p = todo.pop(0)
            path = search(ok, via, tree, g.pad_cells(p), box)
            if path is None:
                why = f"no path to {p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
                break
            paths.append(path)
            tree = tree + path + g.pad_cells(p)
        if len(paths) < len(pads) - 1:
            if w == ws[-1]:
                return False, 0.0, f"{name}: {why}"
            skip = w                # a narrower track may find a way
            continue
        # all branches pass the exact check, or the net is left open
        total, nv = 0.0, 0
        for k, path in enumerate(paths):
            items, why = g.commit(cu, net, path, w, clr, small_via=True)
            if items is None:
                if k == 0:
                    break           # nothing in yet: retry with more grid clearance
                return False, 0.0, f"{name}: {why}"
            total += sum(MM(it.GetLength()) for it in items if it.GetClass() != "PCB_VIA")
            nv += sum(1 for it in items if it.GetClass() == "PCB_VIA")
        else:
            return True, total, f"{name}: {total:.1f} mm, {nv} vias" + (f" at {w} mm" if len(ws) > 1 else "")
    return False, 0.0, f"{name}: {why}"


def groups(board, code):
    """The net's copper, split into the groups already joined by tracks."""
    items = [t for t in board.GetTracks() if t.GetNetCode() == code] + \
            [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode() == code]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    def ends(it):
        return [it.GetStart(), it.GetEnd()] if it.GetClass() == "PCB_TRACK" else [it.GetPosition()]

    layers = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)

    def touches(x, y):
        # only copper on a common layer: a B.Cu track running under an F.Cu
        # pad is not a connection
        if not any(x.IsOnLayer(l) and y.IsOnLayer(l) for l in layers):
            return False
        for q in ends(y):
            if x.GetClass() == "PAD" and x.HitTest(q):
                return True
            if x.GetClass() == "PCB_VIA" and (x.GetPosition() - q).EuclideanNorm() <= x.GetWidth(F) // 2:
                return True
            if x.GetClass() == "PCB_TRACK" and any((q - e).EuclideanNorm() <= x.GetWidth() // 2
                                                   for e in (x.GetStart(), x.GetEnd())):
                return True
        return False
    for i, x in enumerate(items):
        for j in range(i):
            if find(i) != find(j) and (touches(x, items[j]) or touches(items[j], x)):
                parent[find(i)] = find(j)
    out = {}
    for i, it in enumerate(items):
        out.setdefault(find(i), []).append(it)
    return list(out.values())


def join_net(g, cu, name):
    board = g.board
    net = board.FindNet(name)
    code = net.GetNetCode()
    gs = groups(board, code)
    if len(gs) < 2:
        return True, f"join {name}: already one group"
    via_d = finish.VIA_SIZE.get(name, (finish.VIA_D, 0))[0]
    maps = {w: g.maps(code, w, finish.CLEAR, via_d) for w in JOIN_WIDTHS}
    cells = [sum((g.item_cells(it) for it in grp), []) for grp in gs]
    for ok, _ in maps.values():
        for c in cells:
            open_cells(ok, c)
    pos = lambda it: (MM(it.GetPosition().x), MM(it.GetPosition().y))
    tree = max(range(len(gs)), key=lambda k: len(gs[k]))
    tree_items, tree_cells = list(gs[tree]), list(cells[tree])
    rest = [k for k in range(len(gs)) if k != tree]
    links, narrow = 0, 0
    while rest:
        # nearest group first; one that can't be reached now may be later,
        # from a group joined in the meantime
        def gap(k):
            return min(math.dist(pos(a), pos(b)) for a in tree_items for b in gs[k])
        progress = False
        for k in sorted(rest, key=gap):
            near = min(tree_items, key=lambda a: min(math.dist(pos(a), pos(b)) for b in gs[k]))
            box = g.box([pos(near)] + [pos(b) for b in gs[k]], JOIN_MARGIN)
            for w in JOIN_WIDTHS:
                ok, via = maps[w]
                path = search(ok, via, tree_cells, set(cells[k]), box, f_cost=JOIN_F_COST)
                if path is None:
                    continue
                items, _ = g.commit(cu, net, path, w, finish.CLEAR, small_via=False)
                if items is None:
                    continue
                tree_items += gs[k] + items
                tree_cells += cells[k] + path
                rest.remove(k)
                links += 1
                narrow += w < JOIN_WIDTHS[0]
                progress = True
                break
            if progress:
                break
        if not progress:
            break
    msg = f"join {name}: {links} links ({narrow} narrowed)"
    if rest:
        msg += ", WARNING not joined: " + ", ".join(
            f"{pos(gs[k][0])[0]:.2f},{pos(gs[k][0])[1]:.2f}" for k in rest)
    return not rest, msg


# power nets laid as a trunk between two pins: only the pads near the line
# between them join the trunk, the others (a capacitor placed the other way)
# are left to Freerouting as a stub, instead of the trunk detouring to them
TRUNKS = {"VBUS_P3": (("U35", "6"), ("J10", "10")), "VBUS_P4": (("U36", "6"), ("J10", "1"))}
TRUNK_REACH = 3.0      # mm either side of the line


def trunk_pads(board, name):
    if name not in TRUNKS:
        return None
    ends = [next(p for p in board.FindFootprintByReference(r).Pads() if p.GetNumber() == n)
            for r, n in TRUNKS[name]]
    (ax, ay), (bx, by) = [(MM(p.GetPosition().x), MM(p.GetPosition().y)) for p in ends]
    code = ends[0].GetNetCode()
    keep = list(ends)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() != code or any(p is e for e in ends):
                continue
            x, y = MM(p.GetPosition().x), MM(p.GetPosition().y)
            t = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
            if 0.0 <= t <= 1.0 and math.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay)) <= TRUNK_REACH:
                keep.append(p)
    return keep


def attempt(order):
    """Signals in `order`, then the power trees, on a fresh copy of the board."""
    board = pcbnew.LoadBoard(PCB)
    g = Grid(board)
    cu = finish.Copper(board)
    routed, total, lines, failed = 0, 0.0, [], []
    for ref, pin, pad in TIES:
        fp = board.FindFootprintByReference(ref)
        a = next(p for p in fp.Pads() if p.GetNumber() == pin)
        b = min((p for p in fp.Pads() if p.GetNumber() == pad and p is not a),
                key=lambda p: (p.GetPosition() - a.GetPosition()).EuclideanNorm())
        done, length, msg = route_net(g, cu, a.GetNetname(), pads=[a, b])
        lines.append(f"tie {ref}.{pin}-{pad}: " + msg)
        print(lines[-1], flush=True)
    for name in order:
        if board.FindNet(name) is None:
            lines.append(f"{name}: no such net")
            continue
        pads = None
        if name in POWER_TRUNKS:
            pads = [next(p for p in board.FindFootprintByReference(r).Pads() if p.GetNumber() == n)
                    for r, n in POWER_TRUNKS[name]]
        done, length, msg = route_net(g, cu, name, pads=pads)
        routed += done
        total += length
        if not done:
            failed.append(name)
        lines.append(msg)
    joined = 0
    for name in JOIN_NETS:
        ok, msg = join_net(g, cu, name)
        joined += ok
        lines.append(msg)
    for name in LATE_NETS:
        done, length, msg = route_net(g, cu, name, pads=trunk_pads(board, name))
        routed += done
        total += length
        lines.append(msg)
        if not done:
            failed.append(name)
    return dict(board=board, routed=routed, total=total, lines=lines, failed=failed, joined=joined)


def main():
    order, best = list(NETS), None
    for k in range(ROUNDS):
        a = attempt(order)
        print(f"order {k + 1}: {a['routed']}/{len(NETS) + len(LATE_NETS)} routed, {a['total']:.0f} mm, "
              f"{a['joined']}/{len(JOIN_NETS)} power nets joined", flush=True)
        for line in a["lines"]:
            if line.startswith("VBUS"):
                print("   ", line, flush=True)
        score = lambda a: (a["joined"], a["routed"], -a["total"])
        if best is None or score(a) > score(best):
            best = a
        if not a["failed"] and a["joined"] == len(JOIN_NETS):
            break
        early = [n for n in a["failed"] if n not in LATE_NETS]
        order = early + [n for n in order if n not in early]
    for line in best["lines"]:
        print("  " + line)
    board = best["board"]
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print(f"nets routed: {best['routed']}/{len(NETS) + len(LATE_NETS)}, {best['total']:.0f} mm, "
          f"{best['joined']}/{len(JOIN_NETS)} power nets joined"
          + (f" (left to the autorouter: {', '.join(best['failed'])})" if best["failed"] else ""))


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
