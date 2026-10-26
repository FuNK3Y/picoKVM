"""
JLCPCB assembly files from out/kvm_board.kicad_pcb:
  out/jlcpcb/bom.csv   Comment, Designator, Footprint, LCSC Part #
  out/jlcpcb/cpl.csv   Designator, Mid X, Mid Y, Layer, Rotation
Gerbers + drill are produced by kicad-cli (see Makefile).

Footprints without an LCSC number (UART header, mounting holes) are skipped.
Check rotations in JLC's placement preview: some library footprints differ
from JLC's reel orientation and need a per-part offset (ROT_OFFSET below).
"""

import csv
import json
import os
import sys
from collections import defaultdict

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "out"))
FAB = os.path.join(OUT, "jlcpcb")

# LCSC part -> degrees to add after checking JLC's preview.
ROT_OFFSET = {}


JLCREF = os.path.join(HERE, "lib", "jlcref")
_jlc_map = None
_jlc_fps = {}


def jlc_frame(fp, lcsc):
    """Position/rotation (board coords, degrees) at which JLC's footprint for
    `lcsc` lands on fp's pads, and the worst pad mismatch in mm.  Pads are
    matched by number; tries the four 90-degree rotations."""
    global _jlc_map
    if _jlc_map is None:
        path = os.path.join(JLCREF, "lcsc_footprints.json")
        _jlc_map = json.load(open(path)) if os.path.exists(path) else {}
    name = _jlc_map.get(lcsc)
    if not name:
        return fp.GetPosition(), fp.GetOrientationDegrees(), None
    if name not in _jlc_fps:
        _jlc_fps[name] = pcbnew.FootprintLoad(os.path.join(JLCREF, "jlc.pretty"), name)
    jfp = _jlc_fps[name]
    if jfp is None:
        return fp.GetPosition(), fp.GetOrientationDegrees(), None

    def centroids(f):
        pts = defaultdict(list)
        for p in f.Pads():
            if p.GetNumber():
                pts[p.GetNumber()].append((p.GetPosition().x, p.GetPosition().y))
        return {k: (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v))
                for k, v in pts.items()}

    def all_pads(f):
        return [(p.GetPosition().x, p.GetPosition().y) for p in f.Pads()]

    ours = centroids(fp)
    # match by pin number when both libraries number the pads the same way,
    # otherwise by geometry (e.g. a 4-pad switch numbered 1,1,2,2 vs 1,2,3,4)
    def counts(f):
        c = defaultdict(int)
        for p in f.Pads():
            if p.GetNumber():
                c[p.GetNumber()] += 1
        return c

    co, cj = counts(fp), counts(jfp)
    same = {n for n in co if cj.get(n) == co[n]}   # numbered alike, same pad count
    by_number = len(same) >= 2
    best = None
    for k in range(4):
        rot = (fp.GetOrientationDegrees() + 90 * k) % 360
        jfp.SetOrientationDegrees(rot)
        jfp.SetPosition(pcbnew.VECTOR2I(0, 0))
        if by_number:
            theirs = centroids(jfp)
            common = sorted(same)
            tx = sum(ours[c][0] - theirs[c][0] for c in common) / len(common)
            ty = sum(ours[c][1] - theirs[c][1] for c in common) / len(common)
            err = max(((ours[c][0] - theirs[c][0] - tx) ** 2 +
                       (ours[c][1] - theirs[c][1] - ty) ** 2) ** 0.5 for c in common)
        else:
            a, b_ = all_pads(fp), all_pads(jfp)
            tx = sum(x for x, _ in a) / len(a) - sum(x for x, _ in b_) / len(b_)
            ty = sum(y for _, y in a) / len(a) - sum(y for _, y in b_) / len(b_)
            err = max(min(((x - u - tx) ** 2 + (y - v - ty) ** 2) ** 0.5 for u, v in b_)
                      for x, y in a)
        # prefer the unrotated solution on ties (symmetric 2-pin parts)
        key = (round(pcbnew.ToMM(err), 3), k != 0)
        if best is None or key < best[0]:
            best = (key, pcbnew.VECTOR2I(int(tx), int(ty)), rot, pcbnew.ToMM(err))
    if best is None:
        return fp.GetPosition(), fp.GetOrientationDegrees(), None
    return best[1], best[2], best[3]


def main():
    os.makedirs(FAB, exist_ok=True)
    board = pcbnew.LoadBoard(os.path.join(OUT, "kvm_board.kicad_pcb"))
    origin = board.GetDesignSettings().GetAuxOrigin()

    groups = defaultdict(list)
    rows = []
    fixed, bad, missing = [], [], []
    for fp in board.GetFootprints():
        if not fp.HasField("LCSC"):
            continue
        lcsc = fp.GetField("LCSC").GetText()
        if not lcsc:
            continue
        ref = fp.GetReference()
        # one BOM line per LCSC part + footprint: JLC rejects the same part
        # number on several lines (e.g. buttons with different values)
        groups[(lcsc, fp.GetFPID().GetLibItemName().wx_str())].append((ref, fp.GetValue()))

        # JLC places parts with *their* footprint (LCSC/EasyEDA library), whose
        # origin and 0-degree orientation can differ from KiCad's: express the
        # position and rotation in JLC's footprint frame.
        jpos, jrot, err = jlc_frame(fp, lcsc)
        if err is None:
            missing.append(ref)
        elif err > 0.35:     # pad sizes differ a little between libraries
            bad.append(f"{ref} ({err:.2f} mm)")
        elif abs(jrot - fp.GetOrientationDegrees()) % 360 > 0.1 or \
                (jpos - fp.GetPosition()).EuclideanNorm() > pcbnew.FromMM(0.05):
            fixed.append(f"{ref} {(jrot - fp.GetOrientationDegrees()) % 360:+.0f}deg "
                         f"{pcbnew.ToMM((jpos - fp.GetPosition()).EuclideanNorm()):.2f}mm")
        pos = jpos - origin
        rot = (jrot + ROT_OFFSET.get(lcsc, 0)) % 360
        rows.append([ref, f"{pcbnew.ToMM(pos.x):.3f}mm",
                     f"{-pcbnew.ToMM(pos.y):.3f}mm",
                     "Top" if fp.GetLayer() == pcbnew.F_Cu else "Bottom",
                     f"{rot:.1f}"])

    def refkey(r):
        head = r.rstrip("0123456789")
        return head, int(r[len(head):] or 0)

    with open(os.path.join(FAB, "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (lcsc, fpname), items in sorted(groups.items(),
                                            key=lambda kv: refkey(min((r for r, _ in kv[1]), key=refkey))):
            refs = sorted((r for r, _ in items), key=refkey)
            values = sorted({v for _, v in items})
            w.writerow(["/".join(values), ",".join(refs), fpname, lcsc])

    with open(os.path.join(FAB, "cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in sorted(rows, key=lambda r: refkey(r[0])):
            w.writerow(r)

    print(f"BOM: {len(groups)} lines, CPL: {len(rows)} placements")
    print(f"CPL in JLC's footprint frame: {len(fixed)} parts corrected"
          + (f" ({', '.join(fixed)})" if fixed else ""))
    if missing:
        print("  WARNING no JLC reference footprint (run `make jlcref`):", ", ".join(missing))
    if bad:
        print("  WARNING pads don't line up with JLC's footprint:", ", ".join(bad))


if __name__ == "__main__":
    main()
    # KiCad's SWIG bindings can segfault in destructors at interpreter exit;
    # the work is saved by now, so leave without running them
    sys.stdout.flush()
    os._exit(0)
