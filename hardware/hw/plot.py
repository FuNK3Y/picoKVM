"""
Quick 2-D drawing of the board for layout work: out/img/plan.svg.

    python3 hw/plot.py [x0 y0 x1 y1]      (optional window in mm)

Pads in their net's colour class, part outlines with reference designators,
tracks per layer (F.Cu red, B.Cu blue), vias, keep-outs and the passive-free
corridors.  Unlike the 3-D renders it shows what is where by name.
"""

import os
import sys

import pcbnew

PCB = "out/kvm_board.kicad_pcb"
OUT = "out/img/plan.svg"
MM = pcbnew.ToMM


def colour(net):
    if net == "GND":
        return "#888"
    if net.startswith(("+", "VBUS")):
        return "#d80"
    if "_SS" in net:
        return "#c0c"
    if net.endswith(("_DP", "_DN")):
        return "#07a"
    return "#2a2" if net else "#bbb"


def main():
    board = pcbnew.LoadBoard(PCB)
    bb = board.GetBoardEdgesBoundingBox()
    win = [float(v) for v in sys.argv[1:5]] if len(sys.argv) >= 5 else \
        [MM(bb.GetLeft()) - 3, MM(bb.GetTop()) - 3, MM(bb.GetRight()) + 3, MM(bb.GetBottom()) + 3]
    x0, y0, x1, y1 = win
    scale = min(1800 / (x1 - x0), 1300 / (y1 - y0))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{(x1 - x0) * scale:.0f}" '
           f'height="{(y1 - y0) * scale:.0f}" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}">',
           f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="white"/>',
           f'<rect x="{MM(bb.GetLeft())}" y="{MM(bb.GetTop())}" width="{MM(bb.GetWidth())}" '
           f'height="{MM(bb.GetHeight())}" fill="#f4f4ee" stroke="black" stroke-width="0.15"/>']
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetLayer() == pcbnew.B_Cu and z.GetNetname() != "GND":
            b = z.GetBoundingBox()
            out.append(f'<rect x="{MM(b.GetLeft())}" y="{MM(b.GetTop())}" width="{MM(b.GetWidth())}" '
                       f'height="{MM(b.GetHeight())}" fill="none" stroke="#a55" stroke-width="0.1" '
                       f'stroke-dasharray="0.6 0.4"/>')
    for layer, col in ((pcbnew.B_Cu, "#36c"), (pcbnew.F_Cu, "#d33")):
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA" or t.GetLayer() != layer:
                continue
            a, b = t.GetStart(), t.GetEnd()
            out.append(f'<line x1="{MM(a.x)}" y1="{MM(a.y)}" x2="{MM(b.x)}" y2="{MM(b.y)}" stroke="{col}" '
                       f'stroke-width="{MM(t.GetWidth())}" stroke-linecap="round" opacity="0.8"/>')
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            out.append(f'<circle cx="{MM(p.x)}" cy="{MM(p.y)}" r="{MM(t.GetWidth(pcbnew.F_Cu)) / 2}" '
                       f'fill="#333" opacity="0.7"/>')
    size = 0.9 if (x1 - x0) > 60 else 0.5
    for fp in board.GetFootprints():
        for pd in fp.Pads():
            b = pd.GetBoundingBox()
            out.append(f'<rect x="{MM(b.GetLeft())}" y="{MM(b.GetTop())}" width="{MM(b.GetWidth())}" '
                       f'height="{MM(b.GetHeight())}" fill="{colour(pd.GetNetname())}" opacity="0.75"/>')
        b = fp.GetBoundingBox(False)
        out.append(f'<rect x="{MM(b.GetLeft())}" y="{MM(b.GetTop())}" width="{MM(b.GetWidth())}" '
                   f'height="{MM(b.GetHeight())}" fill="none" stroke="#333" stroke-width="0.06"/>')
        ref = fp.GetReference()
        s = size if ref[0] in "UJYLSD" else size * 0.6
        c = b.GetCenter()
        out.append(f'<text x="{MM(c.x)}" y="{MM(c.y) + s * 0.35}" font-size="{s}" text-anchor="middle" '
                   f'font-family="sans-serif" fill="black">{ref}</text>')
    for gx in range(int(x0 // 10 * 10), int(x1) + 1, 10):
        out.append(f'<text x="{gx}" y="{y0 + 1.2}" font-size="1" fill="#06c">{gx}</text>')
    for gy in range(int(y0 // 10 * 10), int(y1) + 1, 10):
        out.append(f'<text x="{x0 + 0.2}" y="{gy}" font-size="1" fill="#06c">{gy}</text>')
    out.append("</svg>")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(out))
    print("wrote", OUT, flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
