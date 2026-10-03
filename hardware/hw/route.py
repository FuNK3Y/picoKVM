"""
Autorouting round-trip with Freerouting (Specctra DSN/SES).

  python3 route.py export   out/kvm_board.kicad_pcb -> out/route/kvm_board.dsn
  (run freerouting on the .dsn -> out/route/kvm_board.ses)
  python3 route.py import   out/route/kvm_board.ses -> tracks/vias in the .kicad_pcb
  python3 route.py cleanup  drop dangling vias, refill zones (separate process)

The outer GND pours are left out of the DSN (they would only block routing)
and the inner layers are declared power planes, so signals stay on F.Cu/B.Cu
and GND connects with vias to In1/In2.  The pours are refilled after import.
"""

import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "out"))
PCB = os.path.join(OUT, "kvm_board.kicad_pcb")
RDIR = os.path.join(OUT, "route")
DSN = os.path.join(RDIR, "kvm_board.dsn")
SES = os.path.join(RDIR, "kvm_board.ses")


def export():
    os.makedirs(RDIR, exist_ok=True)
    board = pcbnew.LoadBoard(PCB)
    for z in list(board.Zones()):
        if z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            board.Remove(z)
    if not pcbnew.ExportSpecctraDSN(board, DSN):
        sys.exit("DSN export failed")
    dsn = open(DSN).read()
    for layer in ("In1.Cu", "In2.Cu"):
        dsn, n = re.subn(r"(\(layer %s\s*\(type )signal" % re.escape(layer),
                         r"\1power", dsn)
        if n != 1:
            sys.exit(f"could not mark {layer} as power plane")
    open(DSN, "w").write(dsn)
    print(f"wrote {DSN}")


def import_():
    board = pcbnew.LoadBoard(PCB)
    # re-import replaces earlier autorouting; locked items (the hand-designed
    # SuperSpeed pairs and the plane fanout) are not in the SES, so keep them
    for t in list(board.GetTracks()):
        if not t.IsLocked():
            board.Remove(t)
    if not pcbnew.ImportSpecctraSES(board, SES):
        sys.exit("SES import failed")
    # after an SES import the board can't be walked from Python any more
    # (even via LoadBoard in the same process): save, and let `cleanup`
    # finish in a fresh process
    pcbnew.SaveBoard(PCB, board)
    print("\nimported", SES, flush=True)


def cleanup():
    board = pcbnew.LoadBoard(PCB)
    # drop vias the router left with nothing attached (plane-net vias stay)
    items = list(board.GetTracks())
    ends = {(p.x, p.y, t.GetNetCode()) for t in items if t.GetClass() != "PCB_VIA"
            for p in (t.GetStart(), t.GetEnd())}
    zone_nets = {z.GetNetCode() for z in board.Zones()}
    dangling = [v for v in items if v.GetClass() == "PCB_VIA"
                and v.GetNetCode() not in zone_nets
                and (v.GetPosition().x, v.GetPosition().y, v.GetNetCode()) not in ends]
    for v in dangling:
        board.Remove(v)
    # the hand-routed USB pairs (route_ss.py / route_usb2.py, all locked) are
    # complete by construction: anything the router added on those nets is a
    # redundant parallel path, i.e. a stub on the pair
    def on_pair(t):
        return not t.IsLocked() and t.GetNetname().startswith(("PCA_", "PCB_", "PER_"))
    extra = [t for t in items if on_pair(t)]
    items = [t for t in items if not on_pair(t)]   # (no `in` on SWIG objects)
    for t in extra:
        board.Remove(t)
    # zero-length segments the router sometimes leaves behind
    zero = [t for t in items if t.GetClass() != "PCB_VIA" and t.GetStart() == t.GetEnd()]
    for t in zero:
        board.Remove(t)
    # drop pre-route stubs the router didn't attach to (one free end)
    stubs = 0
    while True:
        tracks = [t for t in board.GetTracks() if t.GetClass() != "PCB_VIA"]
        anchors = {}
        for t in board.GetTracks():
            pts = [t.GetPosition()] if t.GetClass() == "PCB_VIA" else [t.GetStart(), t.GetEnd()]
            for q in pts:
                anchors[(q.x, q.y, t.GetNetCode())] = anchors.get((q.x, q.y, t.GetNetCode()), 0) + 1
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()]

        def free(t, q):
            if anchors.get((q.x, q.y, t.GetNetCode()), 0) > 1:
                return False
            return not any(p.GetNetCode() == t.GetNetCode() and
                           p.HitTest(q) for p in pads)
        # hand-routed USB pairs (route_ss.py / route_usb2.py) are never stubs
        dead = [t for t in tracks if not t.GetNetname().startswith(("PCA_", "PCB_", "PER_"))
                and (free(t, t.GetStart()) or free(t, t.GetEnd()))]
        if not dead:
            break
        for t in dead:
            board.Remove(t)
        stubs += len(dead)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    vias = sum(1 for t in items if t.GetClass() == "PCB_VIA")
    print(f"routed: {len(items) - vias} track segments, {vias - len(dangling)} vias "
          f"({len(dangling)} dangling vias, {stubs} unused stubs, {len(zero)} zero-length removed)")


if __name__ == "__main__":
    {"export": export, "import": import_, "cleanup": cleanup}[sys.argv[1]]()
    # KiCad's SWIG bindings can segfault in destructors at interpreter exit;
    # the work is saved by now, so leave without running them
    sys.stdout.flush()
    os._exit(0)
