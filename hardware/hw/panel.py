"""
JLCPCB assembly panel ("edge rails added by customer") around the routed
board: out/kvm_board.kicad_pcb -> out/kvm_board_panel.kicad_pcb.

The board itself is untouched and keeps its coordinates, so the CPL (made
from the board) stays valid for the panel Gerbers.  Added:

  * 5 mm rails on the LEFT and RIGHT (75 mm) edges only: the front and rear
    edges carry connectors that protrude 1.5 mm.
  * a 2 mm routed gap between board and rail, bridged by two 5 mm tabs per
    side, away from J8 (left), the ESP32 antenna keep-out (right) and the
    corner screw holes;
  * mouse bites in each tab: 0.5 mm NPTH at 0.95 mm pitch (0.45 mm web, JLC minimum), tangent to the
    board edge, so a broken-off tab leaves at most a ~0.3 mm nub;
  * 3 fiducials (1 mm copper, 2 mm mask opening, asymmetric) and 4 tooling
    holes (1.152 mm NPTH) on the rails, per JLCPCB's panel guidelines.

Written as KiCad s-expressions (hand-built footprints crash KiCad 10's
Python bindings), then loaded and saved once by pcbnew to validate.
"""

import os
import sys
import uuid

SRC = "out/kvm_board.kicad_pcb"
DST = "out/kvm_board_panel.kicad_pcb"
W, H = 112.0, 75.0
RAIL, GAP = 5.0, 2.0
TAB_W = 5.0
TABS = {"left": (10.0, 65.0),     # J8 sits at y 31-44
        "right": (8.0, 69.0)}     # ESP32 antenna keep-out is y 16-64
BITE_D, BITE_PITCH = 0.5, 0.95  # 0.45 mm web: JLC min hole spacing
XL = -GAP - RAIL / 2              # left rail centre line
XR = W + GAP + RAIL / 2           # right rail centre line
FIDUCIALS = [(XL, 20.0), (XL, 55.0), (XR, 13.0)]   # right: above the antenna keep-out
TOOLING = [(XL, 3.0), (XL, H - 3.0), (XR, 3.0), (XR, H - 3.0)]
TOOLING_D = 1.152


def top_level_children(text):
    """Spans of the top-level s-expressions inside (kicad_pcb ...)."""
    spans, depth, start, instr = [], 0, None, False
    for i, ch in enumerate(text):
        if ch == '"' and text[i - 1] != "\\":
            instr = not instr
        if instr:
            continue
        if ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2:
                spans.append((start, i + 1))
            depth -= 1
    return spans


def u():
    return f'(uuid "{uuid.uuid4()}")'


def line(x0, y0, x1, y1):
    return (f'\t(gr_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f}) '
            f'(stroke (width 0.1) (type default)) (layer "Edge.Cuts") {u()})\n')


def text_props(ref, value):
    p = ""
    for name, val in (("Reference", ref), ("Value", value)):
        p += (f'\t\t(property "{name}" "{val}" (at 0 0 0) (layer "F.Fab") (hide yes) {u()}\n'
              f'\t\t\t(effects (font (size 1 1) (thickness 0.15))))\n')
    return p


def npth(ref, x, y, d):
    return (f'\t(footprint "panel:NPTH_{d:g}mm" (layer "F.Cu") {u()} (at {x:.4f} {y:.4f})\n'
            f'{text_props(ref, "NPTH")}'
            f'\t\t(attr exclude_from_pos_files exclude_from_bom)\n'
            f'\t\t(pad "" np_thru_hole circle (at 0 0) (size {d} {d}) (drill {d}) '
            f'(layers "*.Cu" "*.Mask") {u()})\n\t)\n')


def fiducial(ref, x, y):
    return (f'\t(footprint "panel:Fiducial_1mm_Mask2mm" (layer "F.Cu") {u()} (at {x:.4f} {y:.4f})\n'
            f'{text_props(ref, "Fiducial")}'
            f'\t\t(attr smd exclude_from_pos_files exclude_from_bom)\n'
            f'\t\t(pad "" smd circle (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") '
            f'(solder_mask_margin 0.5) {u()})\n\t)\n')


def main():
    text = open(SRC).read()

    # drop the board outline (it becomes part of the panel outline)
    keep, last = [], 0
    for a, b in top_level_children(text):
        block = text[a:b]
        if block.startswith(("(gr_line", "(gr_rect", "(gr_arc")) and '"Edge.Cuts"' in block:
            keep.append(text[last:a])
            last = b
    keep.append(text[last:])
    text = "".join(keep)

    # outline: board + rails + tabs.  One outer contour (open notches in the
    # gaps above the top tab and below the bottom tab) + one closed slot per
    # side between the tabs.
    xl0, xl1 = -GAP - RAIL, -GAP
    xr0, xr1 = W + GAP, W + GAP + RAIL
    (lt, lb), (rt, rb) = TABS["left"], TABS["right"]
    h = TAB_W / 2
    outer = [(xl0, 0), (xl1, 0), (xl1, lt - h), (0, lt - h), (0, 0),
             (W, 0), (W, rt - h), (xr0, rt - h), (xr0, 0), (xr1, 0),
             (xr1, H), (xr0, H), (xr0, rb + h), (W, rb + h), (W, H),
             (0, H), (0, lb + h), (xl1, lb + h), (xl1, H), (xl0, H)]
    slots = [[(xl1, lt + h), (0, lt + h), (0, lb - h), (xl1, lb - h)],
             [(W, rt + h), (xr0, rt + h), (xr0, rb - h), (W, rb - h)]]
    add = ""
    for poly in [outer] + slots:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            add += line(x0, y0, x1, y1)

    # mouse bites, tangent to the board edge on the tab side
    n = 0
    k = int(((TAB_W - BITE_D) / 2) // BITE_PITCH)
    for side, ys in TABS.items():
        x = -BITE_D / 2 if side == "left" else W + BITE_D / 2
        for yc in ys:
            for i in range(-k, k + 1):
                n += 1
                add += npth(f"MB{n}", x, yc + i * BITE_PITCH, BITE_D)
    for i, (x, y) in enumerate(TOOLING, 1):
        add += npth(f"TH{i}", x, y, TOOLING_D)
    for i, (x, y) in enumerate(FIDUCIALS, 1):
        add += fiducial(f"FID{i}", x, y)

    text = text[:text.rstrip().rfind(")")] + add + ")\n"
    open(DST, "w").write(text)

    # validate: pcbnew must load it and see the new items
    import pcbnew
    board = pcbnew.LoadBoard(DST)
    refs = [fp.GetReference() for fp in board.GetFootprints()]
    assert sum(r.startswith("MB") for r in refs) == n and "FID3" in refs and "TH4" in refs, refs[-5:]
    pcbnew.SaveBoard(DST, board)
    print(f"panel: {W + 2 * (GAP + RAIL):.0f} x {H:.0f} mm, {n} mouse-bite holes, "
          f"{len(FIDUCIALS)} fiducials, {len(TOOLING)} tooling holes -> {DST}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
