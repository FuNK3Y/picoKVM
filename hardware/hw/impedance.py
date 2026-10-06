"""
2-D quasi-static field solver for the USB 3.0 / USB 2.0 pairs on the
JLC04161H-3313 stackup (edge-coupled surface microstrip with solder mask).

Finite differences on the cross-section: solve div(eps grad V) = 0 with the
traces at fixed potentials, get the per-unit-length capacitance from the
charge (Gauss's law), and do it twice -- with the real dielectrics (C) and
with vacuum everywhere (C0) -- so Z = 1 / (c0 * sqrt(C * C0)).

Stackup and solder-mask numbers are JLCPCB's published data for
JLC04161H-3313; trapezoid etch and finished copper follow the usual
SI9000-style conventions (top width = W - 0.025 mm, T = 0.04 mm).

  python3 impedance.py              # validate, then report our geometry
  python3 impedance.py sweep        # also sweep width/gap around 90 ohm
"""

import math
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

C0 = 299_792_458.0
EPS0 = 8.854_187_8128e-12

# JLC04161H-3313, L1 over L2 (mm)
H = 0.0994          # 3313 prepreg
ER = 4.1
T = 0.040           # 1 oz outer + plating, finished
ETCH = 0.025        # top width = bottom width - ETCH
MASK_SUB = 0.0305   # 1.2 mil on substrate / between traces
MASK_TOP = 0.0152   # 0.6 mil over the trace
ER_MASK = 3.8

D = 0.0025          # grid pitch (mm)


def solve(w, gap=None, mask=True, er=ER, h=H, t=T, etch=ETCH, dielectric=True):
    """Return capacitance per metre (F/m) of trace 1 for V1=+1, V2=-1 (pair)
    or V1=+1 (single trace)."""
    pair = gap is not None
    span = (2 * w + gap if pair else w)
    xw = span + 12 * h + 1.0             # side walls well away
    yh = h + t + 12 * h + 0.6            # lid well above
    nx, ny = int(round(xw / D)), int(round(yh / D))
    x = (np.arange(nx) + 0.5) * D - xw / 2
    y = (np.arange(ny) + 0.5) * D        # y=0: GND plane (L2)
    X, Y = np.meshgrid(x, y, indexing="xy")

    # permittivity map
    eps = np.ones((ny, nx))
    if dielectric:
        eps[Y < h] = er
    # conductors (trapezoids sitting on the prepreg)
    cond = np.zeros((ny, nx), dtype=np.int8)

    def trapezoid(xc):
        frac = np.clip((Y - h) / t, 0, 1)
        half = (w - etch * frac) / 2
        return (Y >= h) & (Y < h + t) & (np.abs(X - xc) <= half)

    if pair:
        c1 = -(gap + w) / 2
        c2 = +(gap + w) / 2
        cond[trapezoid(c1)] = 1
        cond[trapezoid(c2)] = 2
    else:
        c1 = 0.0
        cond[trapezoid(c1)] = 1
    if dielectric and mask:
        # conformal coat: MASK_SUB on the substrate, MASK_TOP over copper
        near = np.zeros_like(cond, dtype=bool)
        r = int(round(MASK_TOP / D))
        k = cond > 0
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    near |= np.roll(np.roll(k, dy, 0), dx, 1)
        m = ((Y >= h) & (Y < h + MASK_SUB)) | near
        eps[m & (cond == 0) & (Y >= h)] = ER_MASK

    # unknowns: every cell that is not a conductor and not on the box
    V = np.zeros((ny, nx))
    V[cond == 1] = 1.0
    if pair:
        V[cond == 2] = -1.0
    free = (cond == 0)
    free[0, :] = free[-1, :] = free[:, 0] = free[:, -1] = False
    idx = -np.ones((ny, nx), dtype=np.int64)
    idx[free] = np.arange(free.sum())

    rows, cols, vals = [], [], []
    rhs = np.zeros(free.sum())
    jj, ii = np.nonzero(free)
    diag = np.zeros(free.sum())
    for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nj, ni = jj + dj, ii + di
        # face permittivity: harmonic mean between two dielectric cells; next
        # to a conductor (or the box) the field lives in this cell's dielectric
        e = 2 * eps[jj, ii] * eps[nj, ni] / (eps[jj, ii] + eps[nj, ni])
        e = np.where(cond[nj, ni] > 0, eps[jj, ii], e)
        diag += e
        nb = idx[nj, ni]
        inner = nb >= 0
        rows.append(idx[jj, ii][inner]); cols.append(nb[inner]); vals.append(-e[inner])
        rhs[idx[jj, ii][~inner]] += e[~inner] * V[nj[~inner], ni[~inner]]
    A = sp.csr_matrix((np.concatenate(vals + [diag]),
                       (np.concatenate(rows + [np.arange(len(diag))]),
                        np.concatenate(cols + [np.arange(len(diag))]))),
                      shape=(len(diag), len(diag)))
    V[free] = spla.spsolve(A.tocsc(), rhs)

    # charge on conductor 1: flux through the faces of its cells
    q = 0.0
    k1 = cond == 1
    for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nb = np.roll(np.roll(k1, -dj, 0), -di, 1)    # neighbour is conductor 1?
        src = k1 & ~nb
        j, i = np.nonzero(src)
        nj, ni = j + dj, i + di
        e = eps[nj, ni]   # same face permittivity as in the matrix
        q += np.sum(e * (V[j, i] - V[nj, ni]))
    return q * EPS0   # 2-D: per metre, grid pitch cancels


def impedance(w, gap=None, mask=True, **kw):
    c = solve(w, gap, mask, **kw)
    c_air = solve(w, gap, mask, dielectric=False, **kw)
    z = 1.0 / (C0 * math.sqrt(c * c_air))
    eeff = c / c_air
    return (2 * z if gap is not None else z), eeff


def hammerstad_jensen(w, h, er, t):
    """Closed-form single microstrip (Hammerstad-Jensen with thickness
    correction), accurate to ~1% -- used only to validate the solver."""
    u = w / h
    t1 = t / h
    du1 = t1 / math.pi * math.log(1 + 4 * math.e / (t1 * (1 / math.tanh(math.sqrt(6.517 * u))) ** 2))
    dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
    u1, ur = u + du1, u + dur

    def z01(u):
        f = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u) ** 0.7528)
        return 60 * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))

    def ee(u):
        a = 1 + math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 \
            + math.log(1 + (u / 18.1) ** 3) / 18.7
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)

    return z01(ur) / math.sqrt(ee(ur)) * math.sqrt(1.0)  # Z0 = Z01(ur)/sqrt(ee(ur))


def main():
    print("validation: single microstrip, rectangular trace, no mask")
    for w in (0.15, 0.20, 0.30):
        zs, _ = impedance(w, mask=False, etch=0.0)
        zh = hammerstad_jensen(w, H, ER, T)
        print(f"  W={w:.2f}  solver {zs:6.2f} ohm   Hammerstad-Jensen {zh:6.2f} ohm   "
              f"diff {100 * (zs - zh) / zh:+.1f} %")

    print("\nour USB pairs on JLC04161H-3313 (L1 over GND L2), trapezoid etch")
    for w, g in ((0.15, 0.15),):
        for m in (False, True):
            z, ee = impedance(w, g, mask=m)
            print(f"  W={w:.3f} S={g:.3f} {'with   ' if m else 'without'} solder mask: "
                  f"Zdiff = {z:5.1f} ohm  (eps_eff {ee:.2f})")

    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        print("\nsweep with solder mask (Zdiff, ohm)")
        gaps = (0.10, 0.125, 0.15, 0.175, 0.20)
        print("   W \\ S " + "".join(f"{g:8.3f}" for g in gaps))
        for w in (0.10, 0.11, 0.12, 0.13, 0.14, 0.15):
            print(f"  {w:6.3f} " + "".join(f"{impedance(w, g)[0]:8.1f}" for g in gaps))


if __name__ == "__main__":
    main()
