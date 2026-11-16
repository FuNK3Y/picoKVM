"""
Grid router for differential pairs.

A pair is routed as one "fat" centreline: an A* search on a 0.05 mm grid,
moving in the eight 45-degree directions, over a map of how far each cell is
from foreign copper.  The centreline is then split into two coupled tracks,
with mirrored fans at the pins, and the two tracks' lengths are evened out
with small bumps on the shorter one.

Nothing here knows the board: route_pairs.py says which pins to join, on
which layer, and where the layer changes are.  Because the paths are searched
rather than drawn, moving a part in layout.py does not break them.

    r = Router(board)
    a = r.at("U30", "UP_SSRX", "N")          # the pair's pads on U30, leaving north
    b = r.at("U2", "UP_SSRX", "S")
    r.leg("UP_SSRX", a, b, F)                # search, add tracks, balance lengths
    v = r.via((40.6, 23.6), "S")             # a via pair, to be used by two legs
"""

import heapq
import math

import numpy as np
import pcbnew
from scipy import ndimage

RES = 0.05                    # grid pitch (mm)
TW = 0.15                     # track width  (USB_DIFF net class)
HALF = 0.15                   # centreline to track centre (0.15 mm gap)
CLR = 0.15                    # to foreign copper
PAIR_CLR = 0.40               # to another routed pair (>= 2.5 x the track width)
VIA_D, VIA_DRILL = 0.45, 0.3
VIA_HALF = 0.35               # via pair: 0.7 mm apart
EDGE = 0.45                   # copper to board edge
TURN = 30                     # cost of a 45-degree bend, in cells
MINRUN = 5                    # cells between bends (0.25 mm)
SLACK = 3                     # cells the end may be off sideways: the last corner absorbs it
MARGIN = 4.0                  # how far outside the box around its ends a path may go
F, B = pcbnew.F_Cu, pcbnew.B_Cu
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
COMPASS = {"E": 0, "SE": 1, "S": 2, "SW": 3, "W": 4, "NW": 5, "N": 6, "NE": 7}
mm, MM = pcbnew.FromMM, pcbnew.ToMM


def nets(pair):
    """'P1_D' -> (P1_DP, P1_DN); 'UP_SSTX' -> (UP_SSTX_P, UP_SSTX_N)."""
    return (pair + "P", pair + "N") if pair.endswith("_D") else (pair + "_P", pair + "_N")


def unit(d):
    dx, dy = DIRS[COMPASS[d]] if isinstance(d, str) else d
    n = math.hypot(dx, dy)
    return dx / n, dy / n


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def offset(pts, d):
    """Polyline offset by d along the left normal (-dy, dx), mitred."""
    def norm(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        return -dy / n, dx / n
    ns = [norm(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            n, k = ns[0], 1.0
        elif i == len(pts) - 1:
            n, k = ns[-1], 1.0
        else:
            n1, n2 = ns[i - 1], ns[i]
            n = (n1[0] + n2[0], n1[1] + n2[1])
            k = 1.0 / (1.0 + n1[0] * n2[0] + n1[1] * n2[1])
        out.append((p[0] + n[0] * d * k, p[1] + n[1] * d * k))
    return out


class Terminal:
    """Where a pair starts or ends: two pads (or vias, or track ends) and the
    direction u in which the pair leaves them.  Each track runs along u for
    `e`, then at 45 degrees onto the coupled lines, which start at `launch`."""

    def __init__(self, p, n, u, e, names=None):
        self.p, self.n, self.u, self.e = p, n, unit(u), e
        self.names = names
        ux, uy = self.u
        self.perp = (-uy, ux)
        mx, my = (p[0] + n[0]) / 2, (p[1] + n[1]) / 2
        lat = ((p[0] - mx) * self.perp[0] + (p[1] - my) * self.perp[1])
        self.side = 1 if lat > 0 else -1                 # P's side of the left normal
        dp = (p[0] - mx) * ux + (p[1] - my) * uy         # P ahead of N along u (staggered vias)
        self.depth = {"p": dp, "n": -dp}
        self.reach = e + abs(dp) + abs(abs(lat) - HALF)
        self.launch = (mx + ux * self.reach, my + uy * self.reach)

    def fan(self, which):
        """Pad -> end of the straight escape -> coupled point."""
        pad = self.p if which == "p" else self.n
        s = self.side if which == "p" else -self.side
        ux, uy = self.u
        k = self.e + abs(self.depth[which]) - self.depth[which]
        mid = (pad[0] + ux * k, pad[1] + uy * k)
        end = (self.launch[0] + self.perp[0] * HALF * s, self.launch[1] + self.perp[1] * HALF * s)
        return [pad, mid, end]


class Via:
    """A via pair on the centreline at `c`, the pair travelling along `axis`.
    With `stagger` the two vias sit one behind the other (for corridors too
    narrow for them side by side)."""

    def __init__(self, c, axis, half=VIA_HALF, stagger=0.0):
        self.c, self.axis, self.half, self.stagger = c, unit(axis), half, stagger
        self.side = None

    def place(self, side):
        ax, ay = self.axis
        px, py = -ay, ax
        self.side = side
        k = self.stagger / 2
        self.p = (self.c[0] + px * self.half * side - ax * k, self.c[1] + py * self.half * side - ay * k)
        self.n = (self.c[0] - px * self.half * side + ax * k, self.c[1] - py * self.half * side + ay * k)

    def term(self, forward):
        u = self.axis if forward else (-self.axis[0], -self.axis[1])
        return Terminal(self.p, self.n, u, 0.3)


class Router:
    def __init__(self, board):
        self.board = board
        bb = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = MM(bb.GetLeft()), MM(bb.GetTop())
        self.nx = int(round(MM(bb.GetWidth()) / RES)) + 1
        self.ny = int(round(MM(bb.GetHeight()) / RES)) + 1
        self.label = {l: np.zeros((self.ny, self.nx), np.int32) for l in (F, B)}
        self.pairs = {l: np.zeros((self.ny, self.nx), bool) for l in (F, B)}
        self.len = {}
        self.debt = {}       # path -> P minus N length still to be evened out
        self.path = {}       # pair -> the electrical path it belongs to (default: itself)
        self._load()

    # ------------------------------------------------------------ rasterising
    def _box(self, x0, y0, x1, y1):
        i0, i1 = max(0, int((x0 - self.x0) / RES)), min(self.nx, int((x1 - self.x0) / RES) + 2)
        j0, j1 = max(0, int((y0 - self.y0) / RES)), min(self.ny, int((y1 - self.y0) / RES) + 2)
        xs = self.x0 + np.arange(i0, i1) * RES
        ys = self.y0 + np.arange(j0, j1) * RES
        return (slice(j0, j1), slice(i0, i1)), np.meshgrid(xs, ys)

    def disc(self, layer, c, r, code, pair=False):
        sl, (X, Y) = self._box(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        m = (X - c[0]) ** 2 + (Y - c[1]) ** 2 <= r * r
        self.label[layer][sl][m] = code
        if pair:
            self.pairs[layer][sl][m] = True

    def seg(self, layer, a, b, w, code, pair=False):
        r = w / 2
        sl, (X, Y) = self._box(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r)
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = np.clip(((X - a[0]) * dx + (Y - a[1]) * dy) / L2, 0, 1) if L2 else 0
        m = (X - a[0] - t * dx) ** 2 + (Y - a[1] - t * dy) ** 2 <= r * r
        self.label[layer][sl][m] = code
        if pair:
            self.pairs[layer][sl][m] = True

    def poly(self, layer, pts, code):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sl, (X, Y) = self._box(min(xs), min(ys), max(xs), max(ys))
        inside = np.zeros(X.shape, bool)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            if y1 == y2:
                continue
            cross = ((y1 > Y) != (y2 > Y)) & (X < (x2 - x1) * (Y - y1) / (y2 - y1) + x1)
            inside ^= cross
        self.label[layer][sl][inside] = code

    def _load(self):
        b = self.board
        for fp in b.GetFootprints():
            for pad in fp.Pads():
                code = pad.GetNetCode() or -1
                for layer in (F, B):
                    if not pad.IsOnLayer(layer):
                        continue
                    ps = pcbnew.SHAPE_POLY_SET()
                    pad.TransformShapeToPolygon(ps, layer, 0, mm(0.005), pcbnew.ERROR_OUTSIDE)
                    if ps.OutlineCount():
                        o = ps.Outline(0)
                        self.poly(layer, [(MM(o.CPoint(i).x), MM(o.CPoint(i).y)) for i in range(o.PointCount())], code)
                if pad.GetDrillSize().x and pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    c = (MM(pad.GetPosition().x), MM(pad.GetPosition().y))
                    for layer in (F, B):
                        self.disc(layer, c, MM(pad.GetDrillSize().x) / 2 + 0.1, -1)
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                c = (MM(t.GetPosition().x), MM(t.GetPosition().y))
                for layer in (F, B):
                    self.disc(layer, c, MM(t.GetWidth(F)) / 2, t.GetNetCode())
            else:
                a, e = t.GetStart(), t.GetEnd()
                self.seg(t.GetLayer(), (MM(a.x), MM(a.y)), (MM(e.x), MM(e.y)), MM(t.GetWidth()),
                         t.GetNetCode(), pair=t.GetNetname().startswith(("PCA_", "PCB_")))
        k = int(EDGE / RES)
        for lab in self.label.values():
            lab[:k, :] = lab[-k:, :] = lab[:, :k] = lab[:, -k:] = -1
        for z in b.Zones():
            if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
                bb = z.GetBoundingBox()
                sl, _ = self._box(MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom()))
                for lab in self.label.values():
                    lab[sl] = -1

    def free(self, layer, own, out, ends=()):
        """Cells where a centreline of half-width `out` may run.  The pair's
        own copper is in the way like any other (one line must not run over
        the other's pad, or over an earlier stretch), except on the route's
        spot where each end in `ends` launches, just off its own pads."""
        lab = self.label[layer]
        mine = np.isin(lab, own)
        other = (lab != 0) & ~mine
        if ends:
            ys, xs = np.mgrid[0:self.ny, 0:self.nx]
            X, Y = self.x0 + xs * RES, self.y0 + ys * RES
            keep = np.zeros(lab.shape, bool)
            for t in ends:
                # the coupled lines start at the launch point, already clear
                # of the pads behind it: only its immediate surroundings
                lx, ly = t.launch
                keep |= (X - lx) ** 2 + (Y - ly) ** 2 <= 0.65 ** 2
            other |= mine & ~keep
        d = ndimage.distance_transform_edt(~other) * RES
        ok = d >= out + CLR + RES * 0.6
        op = other & self.pairs[layer]
        if op.any():
            ok &= ndimage.distance_transform_edt(~op) * RES >= out + PAIR_CLR
        return ok, d

    # ---------------------------------------------------------------- lookups
    def pad(self, ref, num):
        fp = self.board.FindFootprintByReference(ref)
        p = next(q for q in fp.Pads() if q.GetNumber() == str(num))
        return MM(p.GetPosition().x), MM(p.GetPosition().y)

    def at(self, ref, pair, u, e=None):
        """The pair's pads on `ref` (the ones furthest along u if a net has
        several, as on flow-through parts), leaving in direction u."""
        fp = self.board.FindFootprintByReference(ref)
        ux, uy = unit(u)
        found = []
        for net in nets(pair):
            pads = [q for q in fp.Pads() if q.GetNetname() == net]
            if not pads:
                raise SystemExit(f"{ref} has no pad on {net}")
            q = max(pads, key=lambda q: q.GetPosition().x * ux + q.GetPosition().y * uy)
            found.append(q)
        if e is None:      # clear the pad along u, plus a little
            bb = found[0].GetBoundingBox()
            e = (MM(bb.GetWidth()) * abs(ux) + MM(bb.GetHeight()) * abs(uy)) / 2 + 0.12
        pts = [(MM(q.GetPosition().x), MM(q.GetPosition().y)) for q in found]
        return Terminal(pts[0], pts[1], (ux, uy), e)

    def via(self, c, axis, **kw):
        return Via(c, axis, **kw)

    # ----------------------------------------------------------------- search
    def _cell(self, p):
        return int(round((p[0] - self.x0) / RES)), int(round((p[1] - self.y0) / RES))

    def _astar(self, ok, start, sdir, goal, gdir, margin):
        nx, ny = self.nx, self.ny
        flat = ok.tobytes()
        sx, sy = start
        gx, gy = goal

        def h(x, y):
            dx, dy = abs(x - gx), abs(y - gy)
            return max(dx, dy) + 0.4142 * min(dx, dy)

        def run(x, y, d, n):
            ddx, ddy = DIRS[d]
            for _ in range(n):
                x += ddx
                y += ddy
                if not (bx0 <= x <= bx1 and by0 <= y <= by1) or not flat[y * nx + x]:
                    return None
            return x, y

        # a pair never needs to stray far from the box around its two ends
        m = int(margin / RES)
        bx0, bx1 = min(sx, gx) - m, max(sx, gx) + m
        by0, by1 = min(sy, gy) - m, max(sy, gy) + m
        limit = 80_000 + 3 * (bx1 - bx0) * (by1 - by0)      # most of the box, at worst
        gdx, gdy = DIRS[gdir]
        best = {(sx, sy, sdir): 0.0}
        prev = {}
        heap = [(h(sx, sy), 0.0, sx, sy, sdir)]
        n = 0
        while heap:
            _, g, x, y, d = heapq.heappop(heap)
            if g > best.get((x, y, d), 1e18):
                continue
            # at the goal, or up to SLACK cells beside it: _centreline() slides
            # the last corner so the final segment lands on the exact point
            rx, ry = x - gx, y - gy
            if d == gdir and rx * gdx + ry * gdy == 0 and max(abs(rx), abs(ry)) <= SLACK:
                path = [(x, y, d)]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return path[::-1]
            n += 1
            if n > limit:
                break
            step = 1.4142 if d % 2 else 1.0
            for nd, cells, cost in ((d, 1, step), ((d + 1) % 8, MINRUN, None), ((d - 1) % 8, MINRUN, None)):
                q = run(x, y, nd, cells)
                if q is None:
                    continue
                if cost is None:
                    cost = TURN + cells * (1.4142 if nd % 2 else 1.0)
                ng = g + cost
                key = (q[0], q[1], nd)
                if ng < best.get(key, 1e18):
                    best[key] = ng
                    prev[key] = (x, y, d)
                    heapq.heappush(heap, (ng + h(*q), ng, q[0], q[1], nd))
        return None

    def _centreline(self, ok, a, b, margin=MARGIN):
        """Exact launch point a -> exact launch point b, 45-degree segments."""
        sdir = min(range(8), key=lambda k: -(unit(DIRS[k])[0] * a.u[0] + unit(DIRS[k])[1] * a.u[1]))
        gdir = min(range(8), key=lambda k: (unit(DIRS[k])[0] * b.u[0] + unit(DIRS[k])[1] * b.u[1]))
        path = self._astar(ok, self._cell(a.launch), sdir, self._cell(b.launch), gdir, margin)
        if path is None:
            return None
        # corners only
        pts, ds = [], []
        for i, (x, y, d) in enumerate(path):
            if i == 0 or i == len(path) - 1 or path[i + 1][2] != d:
                pts.append((self.x0 + x * RES, self.y0 + y * RES))
                ds.append(d)
        dirs = [unit(DIRS[path[1][2]])] if len(path) > 1 else [a.u]
        dirs = []
        for p, q in zip(pts, pts[1:]):
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            dirs.append(((q[0] - p[0]) / L, (q[1] - p[1]) / L))

        def cross(p, d1, q, d2):      # line p + t d1 meets line q + s d2
            det = d1[0] * d2[1] - d1[1] * d2[0]
            t = ((q[0] - p[0]) * d2[1] - (q[1] - p[1]) * d2[0]) / det
            return p[0] + t * d1[0], p[1] + t * d1[1]

        # the grid ends are within half a cell of the real launch points: slide
        # the first and last segments onto them, keeping every direction
        if len(pts) >= 3:
            pts[1] = cross(a.launch, dirs[0], pts[1], dirs[1])
            pts[-2] = cross(b.launch, dirs[-1], pts[-2], dirs[-2])
        pts[0], pts[-1] = a.launch, b.launch
        return pts

    # ---------------------------------------------------------------- copper
    def _track(self, net, pts, layer, w=TW):
        code = self.board.FindNet(net)
        for p, q in zip(pts, pts[1:]):
            if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-4:
                continue
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(pcbnew.VECTOR2I(mm(round(p[0], 4)), mm(round(p[1], 4))))
            t.SetEnd(pcbnew.VECTOR2I(mm(round(q[0], 4)), mm(round(q[1], 4))))
            t.SetWidth(mm(w))
            t.SetLayer(layer)
            t.SetNet(code)
            t.SetLocked(True)
            self.board.Add(t)
            self.seg(layer, p, q, w, code.GetNetCode(), pair=True)
        self.len[net] = self.len.get(net, 0.0) + length(pts)

    def _via(self, net, p):
        code = self.board.FindNet(net)
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(mm(round(p[0], 4)), mm(round(p[1], 4))))
        v.SetWidth(mm(VIA_D))
        v.SetDrill(mm(VIA_DRILL))
        v.SetNet(code)
        v.SetLocked(True)
        self.board.Add(v)
        for layer in (F, B):
            self.disc(layer, p, VIA_D / 2, code.GetNetCode())

    def _bumps(self, line, need, dist, outward):
        """Lengthen `line` by up to `need` with 45-degree bumps on its straight
        runs, longest first, bowing to the side `outward` (+1 = left normal).
        Returns the new line and what could not be placed."""
        H = 0.5                                    # bump height: adds 0.8284 x H
        out = list(line)
        order = sorted(range(len(line) - 1), key=lambda i: -length(line[i:i + 2]))
        extra = {}
        for i in order:
            if need < 0.02:
                break
            p, q = line[i], line[i + 1]
            L = length([p, q])
            tx, ty = (q[0] - p[0]) / L, (q[1] - p[1]) / L
            nxn, nyn = -ty * outward, tx * outward
            s, pts = 0.2, []
            while need >= 0.02 and s + 2 * min(H, need / 0.8284) + 0.4 <= L:
                h = min(H, need / 0.8284)
                a = (p[0] + tx * s, p[1] + ty * s)
                b = (a[0] + tx * h + nxn * h, a[1] + ty * h + nyn * h)
                c = (b[0] + tx * 0.2, b[1] + ty * 0.2)
                d = (c[0] + tx * h - nxn * h, c[1] + ty * h - nyn * h)
                cells = [self._cell(pt) for pt in (b, c)]
                if all(dist[cy, cx] >= TW / 2 + CLR + 0.02 for cx, cy in cells):
                    pts += [a, b, c, d]
                    need -= 0.8284 * h
                    s += 2 * h + 0.2 + 0.2
                else:
                    s += 0.25
            if pts:
                extra[i] = pts
        for i in sorted(extra, reverse=True):
            out[i + 1:i + 1] = extra[i]
        return out, need

    def leg(self, pair, a, b, layer, w=TW, margin=MARGIN):
        """Route one stretch of `pair` on `layer` between two Terminals / Vias."""
        np_, nn = nets(pair)
        own = [self.board.FindNet(np_).GetNetCode(), self.board.FindNet(nn).GetNetCode()]
        va = a if isinstance(a, Via) else None
        vb = b if isinstance(b, Via) else None
        if va:
            if va.side is None:
                raise SystemExit(f"{pair}: via used before it was placed")
            a = va.term(True)
        if vb:
            if vb.side is None:
                # P keeps its side of the direction of travel through the via
                vb.place(a.side if self._same(a, vb) else -a.side)
                for net, p in ((np_, vb.p), (nn, vb.n)):
                    self._via(net, p)
            b = vb.term(False)
        if a.side != -b.side:
            raise SystemExit(f"{pair}: the pair would have to twist between its two ends "
                             f"(swap the pins at one end)")
        ok, dist = self.free(layer, own, HALF + w / 2, ends=(a, b))
        centre = self._centreline(ok, a, b, margin)
        if centre is None:
            for name, t in (("start", a), ("end", b)):
                cx, cy = self._cell(t.launch)
                if not ok[cy, cx]:
                    print(f"  {pair}: the {name} point ({t.launch[0]:.2f}, {t.launch[1]:.2f}) is "
                          f"{dist[cy, cx]:.2f} mm from foreign copper (needs {HALF + w / 2 + CLR:.2f})")
            raise SystemExit(f"{pair}: no path on {self.board.GetLayerName(layer)} from "
                             f"({a.launch[0]:.2f}, {a.launch[1]:.2f}) to ({b.launch[0]:.2f}, {b.launch[1]:.2f})")
        lines = {}
        for which, s in (("p", a.side), ("n", -a.side)):
            mid = offset(centre, HALF * s)
            lines[which] = a.fan(which)[:-1] + mid + b.fan(which)[::-1][1:]
        # even out the two lengths (plus what earlier legs of this pair left over)
        path = self.path.get(pair, pair)
        skew = length(lines["p"]) - length(lines["n"]) + self.debt.get(path, 0.0)
        if abs(skew) > 0.02:
            short = "n" if skew > 0 else "p"
            side = -a.side if short == "n" else a.side
            lines[short], left = self._bumps(lines[short], abs(skew), dist, side)
            skew = math.copysign(left, skew)
        self.debt[path] = skew
        self._track(np_, lines["p"], layer, w)
        self._track(nn, lines["n"], layer, w)
        return centre

    @staticmethod
    def _same(a, via):
        """Whether P is on the same side of travel at terminal a and through the via."""
        return True

    def through(self, ref, pair, layer=F):
        """Flow-through part: join the two pads of each net straight across."""
        fp = self.board.FindFootprintByReference(ref)
        for net in nets(pair):
            pads = [q for q in fp.Pads() if q.GetNetname() == net]
            pts = [(MM(q.GetPosition().x), MM(q.GetPosition().y)) for q in pads]
            self._track(net, pts[:2], layer)

    def raw(self, pair, p_pts, n_pts, layer, w=TW):
        """Hand-drawn stretch (connector escapes)."""
        np_, nn = nets(pair)
        self._track(np_, p_pts, layer, w)
        self._track(nn, n_pts, layer, w)
        path = self.path.get(pair, pair)
        self.debt[path] = self.debt.get(path, 0.0) + length(p_pts) - length(n_pts)

    def summary(self, groups):
        """groups: {name: [pairs that are one electrical path]}."""
        worst = 0.0
        for name, pairs in groups.items():
            lp = sum(self.len.get(nets(p)[0], 0.0) for p in pairs)
            ln = sum(self.len.get(nets(p)[1], 0.0) for p in pairs)
            worst = max(worst, abs(lp - ln))
            print(f"  {name:10} P {lp:6.2f} mm  N {ln:6.2f} mm  skew {abs(lp - ln):.3f} mm")
        return worst
