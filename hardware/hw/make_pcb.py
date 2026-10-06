"""
Build out/kvm_board.kicad_pcb from out/kvm_board.json (written by kvm_board.py).

Places the connectors/ICs at fixed positions, packs every passive next to the
IC it belongs to (net affinity, collision-free), adds a 4-layer stackup,
GND/+3V3 planes, net classes and silkscreen labels.  Routing is done
afterwards by route.py (Freerouting) and finish.py.
"""

import json
import math
import os
import re
import shutil
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "out"))
STOCK_FP = "/usr/share/kicad/footprints"
LOCAL_LIBS = {"lcsc": os.path.join(HERE, "lib", "lcsc.pretty")}

W, H = 112.0, 75.0          # board outline (mm)

# ESP32-S3-WROOM-1 (25.5 x 18 mm): the PCB antenna is the last ~6 mm of the
# module.  It sits flush with the right edge (no overhang).  Copper keep-out
# on every layer per Espressif / the KiCad footprint's own rule area: from
# the start of the antenna (6.75 mm from the module centre) to the edge, and
# 15 mm past the module on both sides (48 mm along the edge).
ESP_X = W - 12.75 - 0.2      # module centre: antenna end 0.2 mm inside the edge
ESP_Y = 40.0
ANTENNA_KEEPOUT = (ESP_X + 6.75, ESP_Y - 24.0, W, ESP_Y + 24.0)

mm = pcbnew.FromMM


def pt(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


# ref -> (x, y, rotation_deg).  Connectors open toward local +Y, so the rear
# edge (y=0) ones are rotated 180 and placed with their opening flush.
# Edge connectors: (edge, position along the edge in mm).  Each opens
# outward and sticks out by up to PROTRUDE (2 mm case wall - 0.5 mm), but
# never so far that a pad comes closer than EDGE_PAD_CLEAR to the edge.
# Signal flow: PCs at the rear, desk side (monitors, peripherals) at the
# front, aux/flash with the PC ports, Grove centred on the left side.
EDGE_PARTS = {
    "J1": ("rear", 17.0),     # USB A  USB 3.0 B  (route_ss.py tied to x)
    "J2": ("rear", 35.0),     # USB B  USB 3.0 B  (route_ss.py tied to x)
    "J3": ("front", 26.0),    # peripherals USB 3.0 A  (route_ss.py tied to x)
    # 26 mm HDMI pitch and 23 mm to the USB-A: room for thick overmoulded
    # plugs (up to ~25 mm wide) side by side
    "J5": ("front", 49.0),    # HDMI 1
    "J6": ("front", 75.0),    # HDMI 2
    "J4": ("rear", 95.0),     # aux / flash USB-C, behind the ESP32's USB pins
    "J8": ("left", H / 2),    # Grove button port, centred
}
PROTRUDE = 1.5
EDGE_PAD_CLEAR = 0.3

LED_X = 95.0                       # side-emitting RGB status LED, front edge

ANCHORS = {
    # USB data path: B receptacles -> ESD -> muxes -> ESD -> A receptacle
    # (route_ss.py's coordinates are tied to these: shift both together)
    "U17": (17.0, 24.0, 0),     # TPD4E05U06 USB A
    "U18": (35.0, 24.0, 0),     # TPD4E05U06 USB B
    "U2": (26.0, 34.0, 0),      # HD3SS3212
    "U19": (26.0, 54.0, 0),     # TPD4E05U06 peripheral
    # USB 2.0 (route_usb2.py's coordinates are tied to these): TS3USB221A
    # between the two Type-B connectors, ESD right next to each launch
    "U3": (26.0, 21.0, -90),    # TS3USB221A: ports west, common east
    "U11": (24.75, 18.4, 180),  # TPD4E05U06 USB A (channel 2), below J1's housing
    "U12": (43.6, 13.37, -90),  # TPD4E05U06 USB B, just past J2's housing
    "U13": (28.3, 21.75, -90),  # TPD4E05U06 peripheral, on U3's common pins
    "C3": (27.6, 18.9, 0),      # U3's decoupling, beside its VCC pin (the
                                # USB 2 corridors leave no automatic spot)
    # power
    # TPS2116 peripheral VBUS mux, turned 180 degrees: VIN2 (VBUS_A) faces
    # west towards J1 and VIN1 (VBUS_B) east, so the two supplies arrive
    # without crossing (route_usb2.py pre-routes both on B.Cu)
    "U4": (40.0, 45.0, 180),
    # U4's 1 uF input capacitors (TPS2116 datasheet 9.2 / 10.1: close to the
    # VIN pins), beside the VIN2 / VIN1 vias; route_usb2.py joins them
    "C4": (37.0, 44.75, 180),   # VBUS_A, west of U4
    "C5": (41.9, 42.6, 90),     # VBUS_B, north of U4's VIN1 via
    "U20": (44.5, 44.75, 0),
    # TPS2553 input capacitor (datasheet: 0.1 uF "as close to the IC as
    # possible"), beside U20's IN via; route_usb2.py joins it
    "C6": (48.2, 46.4, 0),
    # LM66100 U6 / U7 local decoupling: 1 uF on each VIN, 10 uF on VOUT
    "C23": (51.0, 38.6, 90),
    "C24": (56.5, 38.6, 90),
    "C25": (56.5, 42.3, 180),    # TPS2553 peripheral power switch, next to U4 VOUT
    "U6": (54.0, 40.0, 0),      # LM66100 A
    "U7": (59.0, 40.0, 0),      # LM66100 B
    "U5": (72.0, 46.0, 0),      # AP2112K
    # aux USB-C (rear edge): ESD + its ideal diode next to it
    "U14": (95.0, 13.5, 0),     # USBLC6 aux
    "U8": (86.5, 12.0, 0),      # LM66100 AUX
    # HDMI DDC, just inside the front HDMI ports
    # (each group sits at the same offset from its connector)
    "U15": (46.5, 61.0, 0),     # USBLC6 HDMI1
    "U9": (52.5, 60.0, 0),      # PCA9306 HDMI1
    "U21": (42.6, 60.0, 90),    # LM66100 HDMI1 5V
    "F2": (42.6, 55.3, 90),
    "U16": (72.5, 61.0, 0),     # USBLC6 HDMI2
    "U10": (78.5, 60.0, 0),     # PCA9306 HDMI2
    "U22": (68.6, 60.0, 90),    # LM66100 HDMI2 5V
    "F3": (68.6, 55.3, 90),
    # MCU: antenna (local -Y) points to +X, flush with the right edge
    "U1": (ESP_X, ESP_Y, -90),
    # bench / debug area in the free rear space: GPIO + UART headers and
    # the three buttons (the Grove port is the user's PC-switch button)
    "J9": (52.0, 14.0, 90),     # 2x8 spare GPIO header
    "J7": (74.0, 13.0, 90),     # UART header
    "SW1": (52.0, 22.0, 0),     # RESET
    "SW2": (60.0, 22.0, 0),     # BOOT
    "SW3": (68.0, 22.0, 0),     # PC switch (bench)
    # front edge (desk side): side-emitting RGB LED, lens (local +Y, 1.36 mm
    # from the origin) facing the edge, 0.2 mm inside it
    "D3": (LED_X, H - 0.2 - 1.36, 0),
    # screws: the four corners only
    "H1": (4.0, H - 4.0, 0),
    "H2": (W - 4.0, H - 4.0, 0),
    "H3": (4.0, 4.0, 0),
    "H4": (W - 4.0, 4.0, 0),
}

POWER_NETS = {"GND", "+3V3", "+5V_SYS"}
# nets whose passives must sit at a given part (overrides net affinity)
NET_HOME = {"GROVE_BTN": "J8", "GROVE_LED": "J8", "GROVE_5V": "J8",
            "AUX_CC1": "J4", "AUX_CC2": "J4", "VBUS_AUX": "U8"}
SCREW_KEEPOUT = 4.0   # mm radius around mounting holes (M3 washer is 7 mm)
THT_SMD_GAP = 2.1     # mm, SMD passives to plated through-hole pads (JLC DFM: 2.03)

# No passives here: J1/J2 -> U17/U18 -> U2 and U2 -> U19 -> J3 (x0,y0,x1,y1)
SS_CORRIDORS = [(12.0, 17.5, 40.0, 32.4), (22.0, 35.6, 30.0, 58.6),
                ANTENNA_KEEPOUT,
                # USB 2.0 pairs on F.Cu (route_usb2.py): keep passives off
                (17.5, 11.9, 26.2, 20.9), (21.2, 19.6, 31.3, 24.9),
                (42.4, 11.8, 46.3, 15.4), (27.8, 33.8, 31.4, 51.6)]

# Net classes (.kicad_pro).  USB_DIFF numbers are an IPC-2141 estimate for
# 90 ohm differential on L1 over L2 of JLC04161H-3313 (~0.1 mm 3313 prepreg,
# er ~4.1); thin prepreg keeps the pair narrow enough to leave 0.5 mm-pitch
# pads.  Confirm with JLCPCB's impedance calculator before ordering.
NETCLASSES = {
    "USB_DIFF": dict(track_width=0.15, diff_pair_width=0.15, diff_pair_gap=0.15,
                     clearance=0.15, via_diameter=0.45, via_drill=0.3),
    "POWER": dict(track_width=0.4, clearance=0.127, via_diameter=0.5,
                  via_drill=0.3),
    # board supply only (< 1 A): 0.3 mm of 1 oz outer copper carries ~1.1 A
    # at a 10 C rise, and leaves the autorouter room in the crowded areas
    "POWER_LIGHT": dict(track_width=0.3, clearance=0.127, via_diameter=0.5,
                        via_drill=0.3),
}
NETCLASS_PATTERNS = [
    ("*_SSTX_?", "USB_DIFF"), ("*_SSRX_?", "USB_DIFF"),
    ("PCA_D?", "USB_DIFF"), ("PCB_D?", "USB_DIFF"), ("PER_D?", "USB_DIFF"),
    ("AUX_D?", "USB_DIFF"),
    # VBUS_A/B and the peripheral path carry the peripheral's up to 1.2 A
    ("VBUS_A", "POWER"), ("VBUS_B", "POWER"), ("VBUS_PERIPH*", "POWER"),
    ("VBUS_AUX", "POWER_LIGHT"), ("+5V_SYS", "POWER_LIGHT"), ("+3V3", "POWER"),
    # GROVE_5V (100 mA PTC) and the HDMI 5 V lines (55 mA) are signal width
]


# Stock footprints whose 3D model KiCad 10 doesn't ship: borrow the model
# of the matching LCSC/EasyEDA part and fit it to the stock footprint's
# body outline (F.Fab): centred across, and either centred or with its front
# face on the outline's +Y edge (connector mouths).
MODEL_DONOR = {
    "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12":
        ("lcsc:USB-C_SMD-TYPE-C-31-M-12_1", "front"),
    "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A":
        ("lcsc:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H3.0", "centre"),   # 3 mm variant
}
WRL_UNIT = 2.54     # KiCad reads VRML in 0.1 inch units


def _lib_path(lib):
    return LOCAL_LIBS.get(lib, os.path.join(STOCK_FP, lib + ".pretty"))


def _fab_box(fp):
    bb = pcbnew.BOX2I()
    for g in fp.GraphicalItems():
        if g.GetLayer() == pcbnew.F_Fab and g.GetClass() == "PCB_SHAPE":
            bb.Merge(g.GetBoundingBox())   # arcs/circles: use their real extent
    o, t = fp.GetPosition(), pcbnew.ToMM
    return (t(bb.GetLeft() - o.x), t(bb.GetTop() - o.y),
            t(bb.GetRight() - o.x), t(bb.GetBottom() - o.y))


def _model_box(path, rot_z):
    """Model extent in mm in 3D axes (Y up) after rotating about Z."""
    txt = open(path).read()
    nums = []
    for blk in re.findall(r"point\s*\[(.*?)\]", txt, re.S):
        nums += [float(v) for v in re.findall(r"-?\d+(?:\.\d*)?(?:[eE]-?\d+)?", blk)]
    pts = [(nums[i] * WRL_UNIT, nums[i + 1] * WRL_UNIT) for i in range(0, len(nums) - 2, 3)]
    c, s_ = round(math.cos(math.radians(rot_z))), round(math.sin(math.radians(rot_z)))
    rx = [c * x - s_ * y for x, y in pts]
    ry = [s_ * x + c * y for x, y in pts]
    return min(rx), min(ry), max(rx), max(ry)


def _fit_model(fp, m, align):
    """Set m's X/Y offset so the model sits on fp's F.Fab body outline."""
    path = m.m_Filename.replace("${KIPRJMOD}/lcsc.3dshapes", os.path.join(HERE, "lib", "lcsc.3dshapes"))
    x0, y0, x1, y1 = _model_box(path, m.m_Rotation.z)
    fx0, fy0, fx1, fy1 = _fab_box(fp)
    m.m_Offset.x = (fx0 + fx1) / 2 - (x0 + x1) / 2
    # board Y = -(3D Y): the model's lowest 3D Y is its +Y (front) edge
    if align == "front":
        m.m_Offset.y = -fy1 - y0
    else:
        m.m_Offset.y = -(fy0 + fy1) / 2 - (y0 + y1) / 2
    return m


MIN_DRILL = 0.3   # mm, JLC's free tier for 4-layer boards

# Plated slots narrower than 0.61 mm are "danger" in JLC's DFM.  KiCad's
# HRO TYPE-C-31-M-12 shell slots are 0.6 mm wide in 1.0 mm pads; JLC's own
# footprint for the part (C165948) uses 0.8 mm in 1.2 mm.  Widen to match,
# keeping KiCad's slot lengths and positions.
SLOT_WIDEN = {"Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12": ("SH", 0.8, 1.2)}

# imported footprints whose courtyard outline isn't closed
FIX_COURTYARD = {"lcsc:LED-SMD_L1.7-W0.6-RD", "lcsc:LED-SMD_4P-L4.0-W1.6-L"}


def _rect_courtyard(fp, margin=0.15):
    """Replace a broken courtyard with a rectangle around pads + silk."""
    bb = pcbnew.BOX2I()
    for pd in fp.Pads():
        bb.Merge(pd.GetBoundingBox())
    for g in list(fp.GraphicalItems()):
        if g.GetLayer() == pcbnew.F_CrtYd:
            fp.Remove(g)
        elif g.GetClass() == "PCB_SHAPE" and g.GetLayer() == pcbnew.F_SilkS:
            bb.Merge(g.GetBoundingBox())
    r = pcbnew.PCB_SHAPE(fp)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetStart(pcbnew.VECTOR2I(bb.GetLeft() - mm(margin), bb.GetTop() - mm(margin)))
    r.SetEnd(pcbnew.VECTOR2I(bb.GetRight() + mm(margin), bb.GetBottom() + mm(margin)))
    r.SetLayer(pcbnew.F_CrtYd)
    r.SetWidth(mm(0.05))
    fp.Add(r)


def _fix_model_paths(fp):
    # EasyEDA models are stored relative to the library; the project lives
    # in out/, so point them at hw/lib.  (Assign by index: iterating
    # fp.Models() yields copies.)
    models = fp.Models()
    for i in range(len(models)):
        models[i].m_Filename = models[i].m_Filename.replace(
            "${KIPRJMOD}/lcsc.3dshapes", "${KIPRJMOD}/../hw/lib/lcsc.3dshapes")


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    fp = pcbnew.FootprintLoad(_lib_path(lib), name)
    if fp is None:
        sys.exit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    if fpid in MODEL_DONOR:
        donor_id, align = MODEL_DONOR[fpid]
        dlib, dname = donor_id.split(":", 1)
        donor = pcbnew.FootprintLoad(_lib_path(dlib), dname)
        models = fp.Models()
        models.clear()
        for i in range(len(donor.Models())):
            models.push_back(_fit_model(fp, donor.Models()[i], align))
    _fix_model_paths(fp)
    # no hole below 0.3 mm anywhere (JLC charges extra for smaller drills):
    # e.g. the ESP32 footprint's thermal-pad holes are 0.2 mm in 0.6 mm pads
    for pd in fp.Pads():
        d = pd.GetDrillSize()
        if d.x and pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and d.x < mm(MIN_DRILL):
            pd.SetDrillSize(pcbnew.VECTOR2I(mm(MIN_DRILL), mm(MIN_DRILL)))
    if fpid in SLOT_WIDEN:
        num, slot_w, pad_w = SLOT_WIDEN[fpid]
        for pd in fp.Pads():
            if pd.GetNumber() == num:
                d, s = pd.GetDrillSize(), pd.GetSize()
                pd.SetDrillSize(pcbnew.VECTOR2I(mm(slot_w), d.y))
                pd.SetSize(pcbnew.VECTOR2I(mm(pad_w), s.y))
    if fpid in FIX_COURTYARD:
        _rect_courtyard(fp)
    return fp


# Silkscreen: functional labels instead of reference designators,
# >= 1.0 mm text.  (text, x, y, size, rotation)
J9_X, J9_Y = 52.0, 14.0          # J9 pin 1 (keep in sync with ANCHORS)
LABELS = [
    ("picoKVM rev A", 80.0, 27.0, 1.5, 0),
    ("USB A", 17.0, 31.5, 1.2, 0),
    ("USB B", 35.0, 31.5, 1.2, 0),
    ("HDMI 1", 49.0, 52.8, 1.0, 0),
    ("HDMI 2", 75.0, 52.8, 1.0, 0),
    ("PERIPHERALS", 13.0, 66.0, 1.0, 90),
    ("AUX / FLASH", 95.0, 16.0, 1.0, 0),
    ("GROVE BTN", 2.3, H / 2 - 12.5, 1.0, 90),
    ("GPIO", J9_X - 4.6, J9_Y - 1.27, 1.0, 0),
    ("UART", 77.8, 15.8, 1.0, 0),
    ("RESET", 52.0, 25.7, 1.0, 0),
    ("BOOT", 60.0, 25.7, 1.0, 0),
    ("PC SW", 68.0, 25.7, 1.0, 0),
    ("STATUS", LED_X - 6.8, H - 1.3, 1.0, 0),   # beside the LED, along the edge
] + [  # GPIO numbers over J9's near row (even pins 2..16 = GPIO35..42)
    (str(35 + k), J9_X + 2.54 * k, J9_Y - 2.54 - 2.2, 1.0, 0) for k in range(8)
]


def add_labels(board):
    for text, x, y, size, rot in LABELS:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetPosition(pt(x, y))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(size * 0.15))
        t.SetTextAngleDegrees(rot)
        board.Add(t)


def keep_ref(ref):
    """No reference designators on the silkscreen: the functional LABELS say
    what things are.  They stay on F.Fab and in the BOM/CPL for assembly."""
    return False


def tidy_silk(board):
    for fp in board.GetFootprints():
        ref = fp.Reference()
        if keep_ref(fp.GetReference()):
            ref.SetVisible(True)
        else:   # off the silkscreen entirely: assembly drawing (F.Fab) only
            ref.SetLayer(pcbnew.B_Fab if fp.GetLayer() == pcbnew.B_Cu else pcbnew.F_Fab)
            ref.SetVisible(False)


def retidy_silk(path):
    """Apply the silkscreen rules and labels to an existing (routed) board."""
    board = pcbnew.LoadBoard(path)
    removed = []   # keep Python references: SWIG would otherwise free them
    for d in list(board.GetDrawings()):
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.F_SilkS:
            board.Remove(d)
            removed.append(d)
    add_labels(board)
    tidy_silk(board)
    pcbnew.SaveBoard(path, board)
    print("silkscreen tidied", flush=True)
    os._exit(0)   # before the removed objects get garbage-collected


def refresh_models(path):
    """Re-apply the 3D model fixes to an existing (e.g. routed) board.
    Only needed for boards made by an older generator; a fresh board already
    has them, so footprints whose model list KiCad's bindings won't hand over
    are skipped rather than failing the build."""
    board = pcbnew.LoadBoard(path)
    done = skipped = 0
    for fp in board.GetFootprints():
        try:
            fid = fp.GetFPID()
            fresh = load_fp(f"{fid.GetLibNickname().wx_str()}:{fid.GetLibItemName().wx_str()}")
            models = fp.Models()
            models.clear()
            for i in range(len(fresh.Models())):
                models.push_back(fresh.Models()[i])
            done += 1
        except (AttributeError, TypeError):
            skipped += 1
    pcbnew.SaveBoard(path, board)
    print(f"3D models refreshed ({done} footprints, {skipped} skipped)", flush=True)
    os._exit(0)


def bbox_mm(fp, grow=0.25):
    # pads + fab/silk outline; used instead of the courtyard when there is
    # none (EasyEDA imports draw the body on silk) or when it is much bigger
    # (the ESP32 courtyard wraps the antenna keep-out)
    body = pcbnew.BOX2I()
    for pd in fp.Pads():
        body.Merge(pd.GetBoundingBox())
    for g in fp.GraphicalItems():
        if g.GetClass() == "MGRAPHIC" or g.GetClass() == "PCB_SHAPE":
            if g.GetLayer() in (pcbnew.F_Fab, pcbnew.F_SilkS):
                body.Merge(g.GetBoundingBox())
    bb = body
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    if cy.OutlineCount():
        c = cy.BBox()
        if c.GetArea() < 2 * body.GetArea():
            bb = c
            for pd in fp.Pads():          # some courtyards miss shell lugs
                bb.Merge(pd.GetBoundingBox())
    t = pcbnew.ToMM
    return (t(bb.GetLeft()) - grow, t(bb.GetTop()) - grow,
            t(bb.GetRight()) + grow, t(bb.GetBottom()) + grow)


def body_box(fp):
    """Connector body in board mm: F.Fab outline, else silkscreen + pads
    (EasyEDA imports draw the body on silk).  Courtyard margins excluded."""
    fab, silk = pcbnew.BOX2I(), pcbnew.BOX2I()
    for g in fp.GraphicalItems():
        if g.GetClass() == "PCB_SHAPE":
            if g.GetLayer() == pcbnew.F_Fab:
                fab.Merge(g.GetBoundingBox())
            elif g.GetLayer() == pcbnew.F_SilkS:
                silk.Merge(g.GetBoundingBox())
    bb = fab if fab.GetWidth() else silk
    if not fab.GetWidth():
        for pd in fp.Pads():
            bb.Merge(pd.GetBoundingBox())
    t = pcbnew.ToMM
    return t(bb.GetLeft()), t(bb.GetTop()), t(bb.GetRight()), t(bb.GetBottom())


def pads_box(fp):
    bb = pcbnew.BOX2I()
    for pd in fp.Pads():
        bb.Merge(pd.GetBoundingBox())
    t = pcbnew.ToMM
    return t(bb.GetLeft()), t(bb.GetTop()), t(bb.GetRight()), t(bb.GetBottom())


# edge -> (rotation that turns the footprint's local +Y opening outward,
#          outward axis, sign, edge coordinate)
EDGES = {"rear": (180, 1, -1, 0.0), "front": (0, 1, +1, H),
         "left": (-90, 0, -1, 0.0), "right": (90, 0, +1, W)}


def edge_anchor(fp, edge, along):
    """Position an edge connector; returns (x, y, rot, protrusion_mm)."""
    rot, axis, sgn, e = EDGES[edge]
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pt(0, 0))
    body, pads = body_box(fp), pads_box(fp)
    # outward extent relative to the origin (larger = further out)
    out = lambda box: max(sgn * box[axis], sgn * box[axis + 2])
    c = sgn * e + PROTRUDE - out(body)                 # body face at edge + PROTRUDE
    c = min(c, sgn * e - EDGE_PAD_CLEAR - out(pads))   # keep pads on the board
    pos = sgn * c
    protrusion = c + out(body) - sgn * e
    x, y = (pos, along) if axis == 0 else (along, pos)
    return round(x, 3), round(y, 3), rot, round(protrusion, 2)


def overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def main():
    parts = json.load(open(os.path.join(OUT, "kvm_board.json")))
    pcb_path = os.path.join(OUT, "kvm_board.kicad_pcb")
    board = pcbnew.NewBoard(pcb_path)
    board.SetCopperLayerCount(4)

    # JLCPCB 4-layer capabilities (with margin)
    ds = board.GetDesignSettings()
    ds.m_MinClearance = mm(0.1)
    ds.m_TrackMinWidth = mm(0.1)
    ds.m_MinThroughDrill = mm(0.3)      # JLC's free via tier: 0.3 mm drill
    ds.m_ViasMinSize = mm(0.4)
    ds.m_ViasMinAnnularWidth = mm(0.07)
    ds.m_HoleClearance = mm(0.2)
    ds.m_HoleToHoleMin = mm(0.25)
    ds.m_CopperEdgeClearance = mm(0.25)
    ds.m_SilkClearance = mm(0)

    # nets
    netinfo = {}
    for p in parts:
        for net in p["pads"].values():
            if net not in netinfo:
                ni = pcbnew.NETINFO_ITEM(board, net)
                board.Add(ni)
                netinfo[net] = ni

    # footprints
    fps, problems = {}, []
    for p in parts:
        fp = load_fp(p["footprint"])
        fp.SetReference(p["ref"])
        fp.SetValue(p["value"])
        if p["lcsc"]:
            fp.SetField("LCSC", p["lcsc"])
            fp.GetField("LCSC").SetVisible(False)
        else:
            # mechanical / hand-soldered: keep out of JLC BOM and CPL
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        pad_nums = set()
        for pad in fp.Pads():
            num = pad.GetNumber()
            pad_nums.add(num)
            if num in p["pads"]:
                pad.SetNet(netinfo[p["pads"][num]])
            elif num == "" and p["ref"] == "U1":
                pad.SetNet(netinfo["GND"])   # ESP32 thermal-pad sub-pads
        missing = set(p["pads"]) - pad_nums
        if missing:
            problems.append(f'{p["ref"]}: symbol pins without pads {sorted(missing)}')
        board.Add(fp)
        fps[p["ref"]] = (fp, p)

    # edge connectors first: computed from their footprints
    anchors, mech = {}, []
    for ref, (edge, along) in EDGE_PARTS.items():
        x, y, rot, prot = edge_anchor(fps[ref][0], edge, along)
        anchors[ref] = (x, y, rot)
        mech.append((ref, fps[ref][1]["value"], edge, along, prot))
    anchors.update(ANCHORS)
    write_mechanical(mech)

    # fixed placement (and warn if two fixed parts overlap)
    placed, fixed = [], {}
    for ref, (x, y, rot) in anchors.items():
        fp = fps[ref][0]
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pt(x, y))
        b = bbox_mm(fp, 0.1)
        if ref.startswith("H"):
            b = (x - SCREW_KEEPOUT, y - SCREW_KEEPOUT, x + SCREW_KEEPOUT, y + SCREW_KEEPOUT)
        for other, ob in fixed.items():
            if overlaps(b, ob):
                problems.append(f"{ref} overlaps {other}")
        fixed[ref] = b
        placed.append(b if ref.startswith("H") else bbox_mm(fp))

    # passive placement by net affinity
    home_by_net = {}
    for ref in anchors:
        if ref[0] in "UJD":
            for net in fps[ref][1]["pads"].values():
                if net not in POWER_NETS:
                    home_by_net.setdefault(net, ref)

    def home_of(p):
        nets = [n for n in p["pads"].values() if n not in POWER_NETS]
        for n in nets:  # series protection belongs at its connector
            if n in NET_HOME:
                return NET_HOME[n]
        for n in nets:  # prefer an IC over a connector
            h = home_by_net.get(n)
            if h and h.startswith("U"):
                return h
        for n in nets:
            if n in home_by_net:
                return home_by_net[n]
        return None

    # power-only caps follow the IC created just before them
    last_ic = None
    plan = []
    for p in parts:
        ref = p["ref"]
        if ref in anchors:
            if ref.startswith("U"):
                last_ic = ref
            continue
        plan.append((p, home_of(p) or last_ic or "U1"))

    def outline_ok(b):
        return b[0] >= 0.5 and b[1] >= 0.5 and b[2] <= W - 0.5 and b[3] <= H - 0.5

    # keep the USB 3.0 SuperSpeed corridors free (route_ss.py routes them)
    placed.extend(SS_CORRIDORS)

    # JLC hand-solders through-hole pins after reflow: keep SMD passives
    # THT_SMD_GAP clear of every plated through-hole pad so the iron can't
    # disturb them (their DFM flags < 2.03 mm)
    for fp, _ in fps.values():
        for pd in fp.Pads():
            if pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pd.GetSize().x > 0:
                bb = pd.GetBoundingBox()
                placed.append((pcbnew.ToMM(bb.GetLeft()) - THT_SMD_GAP,
                               pcbnew.ToMM(bb.GetTop()) - THT_SMD_GAP,
                               pcbnew.ToMM(bb.GetRight()) + THT_SMD_GAP,
                               pcbnew.ToMM(bb.GetBottom()) + THT_SMD_GAP))

    for p, home in plan:
        fp = fps[p["ref"]][0]
        hx, hy = (pcbnew.ToMM(v) for v in (fps[home][0].GetPosition().x,
                                           fps[home][0].GetPosition().y))
        # search radius from the pad extent (courtyards may include
        # antenna keep-outs etc.)
        pads = [pcbnew.ToMM(v) for pd in fps[home][0].Pads()
                for v in (pd.GetPosition().x - fps[home][0].GetPosition().x,
                          pd.GetPosition().y - fps[home][0].GetPosition().y)]
        r0 = min(max(abs(v) for v in pads) + 1.0, 6.0)
        done = False
        for step in range(0, 400):
            r = r0 + 0.5 * (step // 16)
            a = (step % 16) * math.pi / 8
            x, y = hx + r * math.cos(a), hy + r * math.sin(a)
            fp.SetPosition(pt(round(x, 2), round(y, 2)))
            b = bbox_mm(fp)
            if outline_ok(b) and not any(overlaps(b, o) for o in placed):
                placed.append(b)
                done = True
                break
        if not done:
            problems.append(f'{p["ref"]}: no free spot near {home}')

    # outline
    corners = [(0, 0), (W, 0), (W, H), (0, H)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pt(x1, y1))
        seg.SetEnd(pt(x2, y2))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    # Planes: In1 solid GND (reference for the F.Cu USB pairs), In2 solid
    # +3V3 (SIG/GND/PWR/SIG), F/B flooded with GND
    for layer, net in ((pcbnew.In1_Cu, "GND"), (pcbnew.In2_Cu, "+3V3"),
                       (pcbnew.F_Cu, "GND"), (pcbnew.B_Cu, "GND")):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(netinfo[net])
        z.SetLocalClearance(mm(0.3))
        z.SetMinThickness(mm(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        # no floating scraps of pour (e.g. a sliver held only by one spoke)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetIsFilled(False)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)):
            ol.Append(mm(x), mm(y))
        board.Add(z)

    # antenna keep-out: no tracks, vias, pads or copper fill on any layer
    ka = pcbnew.ZONE(board)
    ka.SetIsRuleArea(True)
    ka.SetZoneName("ESP32 antenna keep-out")
    ls = pcbnew.LSET()
    for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
        ls.AddLayer(layer)
    ka.SetLayerSet(ls)
    ka.SetDoNotAllowTracks(True)
    ka.SetDoNotAllowVias(True)
    ka.SetDoNotAllowPads(True)
    ka.SetDoNotAllowZoneFills(True)
    ka.SetDoNotAllowFootprints(False)   # the module itself sits over it
    ol = ka.Outline()
    ol.NewOutline()
    x0, y0, x1, y1 = ANTENNA_KEEPOUT
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        ol.Append(mm(x), mm(y))
    board.Add(ka)

    # Grove J8: its leads run from the pads back into the housing over the
    # board; a via there would sit under a lead (JLC DFM "lead to hole").
    # Via-only keep-out from the housing front to the signal pads, as wide
    # as the signal pads (the GND tabs outside it keep their vias).
    j8 = fps["J8"][0]
    sig = [pd.GetBoundingBox() for pd in j8.Pads() if pd.GetNumber() in ("1", "2", "3", "4")]
    sx0 = min(pcbnew.ToMM(b.GetLeft()) for b in sig)
    sy0 = min(pcbnew.ToMM(b.GetTop()) for b in sig) - 0.3
    sy1 = max(pcbnew.ToMM(b.GetBottom()) for b in sig) + 0.3
    kv = pcbnew.ZONE(board)
    kv.SetIsRuleArea(True)
    kv.SetZoneName("J8 lead keep-out")
    kv.SetLayerSet(ls)
    kv.SetDoNotAllowVias(True)
    kv.SetDoNotAllowTracks(False)
    kv.SetDoNotAllowPads(False)
    kv.SetDoNotAllowZoneFills(False)
    kv.SetDoNotAllowFootprints(False)
    ol = kv.Outline()
    ol.NewOutline()
    for x, y in ((0.0, sy0), (sx0, sy0), (sx0, sy1), (0.0, sy1)):
        ol.Append(mm(x), mm(y))
    board.Add(kv)

    add_labels(board)

    # title block
    tb = board.GetTitleBlock()
    tb.SetTitle("picoKVM: ESP32-S3 USB 3.0 KVM + HDMI DDC/CI")
    tb.SetRevision("A")
    tb.SetCompany("github.com/FuNK3Y/picoKVM")

    tidy_silk(board)
    pcbnew.SaveBoard(pcb_path, board)
    write_stackup(pcb_path)
    write_project(os.path.join(OUT, "kvm_board.kicad_pro"))

    # fill zones on a fresh load so the project rules (net classes, hole
    # clearance) are in effect
    board = pcbnew.LoadBoard(pcb_path)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(pcb_path, board)
    # SaveBoard rewrites the .kicad_pro from its cached copy: re-apply ours
    write_project(os.path.join(OUT, "kvm_board.kicad_pro"))

    for p in problems:
        print("PROBLEM:", p)
    print(f"wrote {pcb_path}: {len(fps)} footprints, {len(netinfo)} nets")


# JLC04161H-3313 (1.6 mm, ordered as "specified stackup"), the same numbers
# hw/impedance.py uses.  KiCad's Python API doesn't expose the stackup, so
# it is written into the board file's setup section; KiCad keeps it from
# then on, and the Gerber job file / fab outputs describe the real board.
STACKUP = """\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "prepreg") (thickness 0.0994) (material "3313") (epsilon_r 4.1) (loss_tangent 0.02))
\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0152))
\t\t\t(layer "dielectric 2" (type "core") (thickness 1.265) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0152))
\t\t\t(layer "dielectric 3" (type "prepreg") (thickness 0.0994) (material "3313") (epsilon_r 4.1) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))
\t\t\t(copper_finish "None")
\t\t\t(dielectric_constraints no)
\t\t)
"""


def write_stackup(path):
    s = open(path).read()
    if "(stackup" in s:
        return
    s = s.replace("\t(setup\n", "\t(setup\n" + STACKUP, 1)
    open(path, "w").write(s)


def write_mechanical(rows):
    """Edge-connector positions for the enclosure design."""
    with open(os.path.join(OUT, "mechanical.txt"), "w") as f:
        f.write(f"Board {W:g} x {H:g} mm, origin top-left (rear-left corner), y toward the front.\n")
        f.write(f"ESP32 antenna flush with the right edge (y {ESP_Y - 9:g}..{ESP_Y + 9:g}); "
                "keep metal and conductive filament >= 5 mm away from it.\n")
        f.write("M3 holes at (4,4) (108,4) (4,71) (108,71); keep 8 mm around them clear.\n")
        f.write(f"Connectors stick out past the edge by up to {PROTRUDE} mm (2 mm wall - 0.5 mm);\n")
        f.write("less where a pad would get too close to the edge.\n\n")
        f.write(f"{'ref':4} {'part':28} {'edge':6} {'centre along edge':>18} {'protrusion':>11}\n")
        for ref, part, edge, along, prot in rows:
            f.write(f"{ref:4} {part:28} {edge:6} {along:15.2f} mm {prot:8.2f} mm\n")
            print(f"  {ref} {edge:5} at {along:6.2f} mm, protrudes {prot:.2f} mm")
        f.write("\nSide-emitting RGB status LED (SK6812SIDE-A; lens 4.0 x 2.0 mm, light exits\n"
                "the front edge; ~2 mm hole or light pipe in the wall, centre 1.0 mm above\n"
                "the board surface, lens face 0.2 mm inside the edge):\n")
        f.write(f"  D3 at x = {LED_X:.2f} mm\n")
        f.write("\nButtons (TS-1187A-C-F-B, 5.1 x 5.1 mm, top of actuator 3.0 mm above the board;\n"
                "press them through lid flexures):\n")
        for ref, name in (("SW1", "RESET"), ("SW2", "BOOT"), ("SW3", "PC SW")):
            x, y, _ = ANCHORS[ref]
            f.write(f"  {ref} {name:6} centre ({x:.2f}, {y:.2f}) mm\n")


def write_project(path):
    pro = json.load(open(path)) if os.path.exists(path) else {}
    ns = pro.setdefault("net_settings", {})
    classes = ns.get("classes") or []
    default = next((c for c in classes if c.get("name") == "Default"), {"name": "Default"})
    default.update(clearance=0.127, track_width=0.2, via_diameter=0.45,
                   via_drill=0.3)
    new = [default]
    for name, v in NETCLASSES.items():
        c = dict(default)
        c["name"] = name
        c.update(v)
        new.append(c)
    ns["classes"] = new
    ns["netclass_patterns"] = [{"netclass": c, "pattern": p} for p, c in NETCLASS_PATTERNS]
    # Every GND/+3V3 pad already reaches its solid inner plane through its
    # plated hole or its own fanout via, and the F/B GND pours are only a
    # shield: one thermal spoke into a pour is enough (KiCad's default of 2
    # reports "starved_thermal" on pads boxed in by routing).
    rules = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    rules["min_resolved_spokes"] = 1
    pro.setdefault("meta", {"filename": os.path.basename(path), "version": 3})
    json.dump(pro, open(path, "w"), indent=2)
    # JLCPCB 4-layer manufacturing limits, checked by every DRC run
    shutil.copy(os.path.join(HERE, "jlcpcb_4layer.kicad_dru"),
                os.path.splitext(path)[0] + ".kicad_dru")
    # project-local library tables so KiCad finds the LCSC imports
    d = os.path.dirname(path)
    with open(os.path.join(d, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "lcsc")(type "KiCad")'
                '(uri "${KIPRJMOD}/../hw/lib/lcsc.pretty")(options "")(descr "LCSC/EasyEDA imports"))\n)\n')
    with open(os.path.join(d, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "lcsc")(type "KiCad")'
                '(uri "${KIPRJMOD}/../hw/lib/lcsc.kicad_sym")(options "")(descr "LCSC/EasyEDA imports"))\n)\n')


if __name__ == "__main__":
    if sys.argv[1:] == ["models"]:
        refresh_models(os.path.join(OUT, "kvm_board.kicad_pcb"))
    elif sys.argv[1:] == ["silk"]:
        retidy_silk(os.path.join(OUT, "kvm_board.kicad_pcb"))
    else:
        main()
    # KiCad's SWIG bindings can segfault in destructors at interpreter exit;
    # the work is saved by now, so leave without running them
    sys.stdout.flush()
    os._exit(0)
