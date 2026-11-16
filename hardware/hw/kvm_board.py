"""
picoKVM rev B — circuit description (SKiDL).

ESP32-S3 + USB 3.0 2:1 switch (USB A / USB B) feeding a 4-port USB 3.0 hub
(TUSB8041), an RP2350 for keyboard interception (hid-remapper) on port 4, and
2x HDMI DDC/CI control ports.  This file is the source of truth for the
schematic: running it produces the KiCad netlist, a JSON parts/nets dump
(consumed by make_pcb.py) and the ERC report.

USB topology
  PC A / PC B (Type-B) -> ESD -> U2 (SuperSpeed) + U3 (USB 2.0) muxes
                       -> U30 TUSB8041 upstream
  U30 ports 1-3        -> Type-A connectors (two stacked pairs)
  U30 port 4           -> SuperSpeed straight to the 4th connector; its
                          USB 2.0 pair goes through U47/U48:
                            KBD_INTERCEPT low  = connector <-> hub (plain port)
                            KBD_INTERCEPT high = connector <-> RP2350 host,
                                                 RP2350 device <-> hub

Signal conventions (one job per GPIO)
  USB_SEL        low = USB A, high = USB B: USB 3 + USB 2 data muxes *and* the
                 PC-side port power source (U4 PR1) switch together
  USB_OE_N       low = data muxes enabled (pulled up: off until firmware runs)
  HUB_RESET_N    low = hub in reset, which also turns the four ports' power
                 off (pulled down: off at reset).  Same pin and polarity as
                 rev A's PERIPH_EN.
  KBD_INTERCEPT  high = keyboard port goes through the RP2350 (pulled down)
"""

import json
import os
import sys

# skidl injects NC and default_circuit as builtins on star-import
from skidl import *  # noqa: F401,F403
from skidl import (
    KICAD10, TEMPLATE, Net, Part, Pin, ERC, generate_netlist, lib_search_paths,
    set_default_tool,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out")
os.makedirs(OUT, exist_ok=True)

set_default_tool(KICAD10)
lib_search_paths[KICAD10].append(os.path.join(HERE, "lib"))

# ---------------------------------------------------------------- part helpers
# Fixed refs: U1 ESP32-S3, U2 HD3SS3212, U3 TS3USB221A, U4 TPS2116 (A/B),
# U5 3.3 V buck, U6-U8 LM66100 (A/B/AUX), U11-U12 TPD4E05U06
# (PC USB 2), U13 TCA9548A (I2C multiplexer), U14-U16 USBLC6, U17-U18 TPD4E05U06 (PC SuperSpeed), U21-U22
# LM66100 (HDMI 5 V, one per stacked connector), U30 TUSB8041, U31 1.1 V buck, U32 TPS2116 (AUX priority),
# U33-U36 TPS2553 (ports 1-4), U37-U40 TPD4E05U06 (port SuperSpeed: TX and
# RX part per stack), U41-U44
# TPD4E05U06 (port USB 2), U45 RP2350A, U46 flash, U47-U48 TS3USB221A.
# J1 USB A, J2 USB B, J3 ports 1+2, J10 ports 3+4, J4 aux USB-C, J5/J6 HDMI,
# J8 Grove (button), J11 Grove (I2C).
# JLCPCB/LCSC numbers (stock checked 2026-11-12).  "base" = JLC basic part.
LCSC_R = {  # 0402 1% UniOhm, all basic
    "1k": "C11702", "2k": "C4109", "4.7k": "C25900", "5.1k": "C25905",
    "10k": "C25744", "20k": "C25765", "200k": "C25764", "100": "C25076",
    "220": "C25091", "15k": "C25756", "33": "C25105", "12k": "C25752",
    "22k": "C25768", "100k": "C25741", "1M": "C26083",
    # extended parts
    "27": "C25100", "8.2k": "C25924", "9.53k": "C96273", "90.9k": "C26989",
    "33k": "C25779",
}
LCSC_C = {  # value -> (footprint, LCSC), all basic
    "15pF": ("Capacitor_SMD:C_0402_1005Metric", "C1548"),
    "18pF": ("Capacitor_SMD:C_0402_1005Metric", "C1549"),
    "10nF": ("Capacitor_SMD:C_0402_1005Metric", "C15195"),
    "100nF": ("Capacitor_SMD:C_0402_1005Metric", "C1525"),
    "1uF": ("Capacitor_SMD:C_0402_1005Metric", "C52923"),
    "4.7uF": ("Capacitor_SMD:C_0402_1005Metric", "C23733"),
    "10uF": ("Capacitor_SMD:C_0805_2012Metric", "C15850"),
    "22uF": ("Capacitor_SMD:C_0805_2012Metric", "C45783"),
    "100uF": ("Capacitor_SMD:C_1206_3216Metric", "C15008"),
}

_r = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0402_1005Metric")
_c = Part("Device", "C", dest=TEMPLATE)


# Placement hints: part -> (ref, pin) it must sit next to.  make_pcb.py puts
# the part right at that pin, its pad on the pin's net facing it, instead of
# wherever net affinity finds room (which put input capacitors 40 mm from
# their IC in rev B).  The pin is a number or a pin name.
AT = {}


def R(value, a, b, at=None):
    r = _r(value=value)
    r.fields["LCSC"] = LCSC_R[value]
    r[1] += a
    r[2] += b
    if at:
        AT[r] = at
    return r


_c_auto = iter(range(100, 1000))   # C1-C99 are for capacitors with a fixed ref (C_ref)


def C(value, a, b, at=None):
    fp, lcsc = LCSC_C[value]
    c = _c(value=value, footprint=fp, ref=f"C{next(_c_auto)}")
    c.fields["LCSC"] = lcsc
    c[1] += a
    c[2] += b
    if at:
        AT[c] = at
    return c


def part(lib, name, footprint=None, lcsc=None, **kw):
    p = Part(lib, name, **kw)
    if footprint:
        p.footprint = footprint
    if lcsc:
        p.fields["LCSC"] = lcsc
    if lib == "lcsc":
        # EasyEDA imports leave every pin "unspecified", which floods ERC.
        for pin in p.pins:
            if pin.func == Pin.types.UNSPEC:
                pin.func = Pin.types.PASSIVE
    return p


# ---------------------------------------------------------------------- nets
gnd = Net("GND")
v3 = Net("+3V3")
v1 = Net("+1V1")
v5 = Net("+5V_SYS")
for n in (gnd, v3, v1, v5):
    n.drive = 100  # power nets: let ERC treat them as driven
vbus_a, vbus_b, vbus_aux = Net("VBUS_A"), Net("VBUS_B"), Net("VBUS_AUX")
vbus_pc = Net("VBUS_PC")      # the selected PC's VBUS (U4)
vbus_hub = Net("VBUS_HUB")    # port supply: AUX if present, else the selected PC (U32)
for n in (vbus_a, vbus_b, vbus_aux):
    n.drive = 100  # sourced by the PC / aux cable through the connector
# Intentional OR of power outputs: 3x LM66100 onto +5V_SYS, and each
# TPS2116's two VOUT pins.
for n in (v5, vbus_pc, vbus_hub):
    n.do_erc = False

usb_sel, usb_oe_n = Net("USB_SEL"), Net("USB_OE_N")
hub_reset_n = Net("HUB_RESET_N")
kbd_intercept = Net("KBD_INTERCEPT")


def C_ref(value, ref, a, b, at=None):
    c = C(value, a, b, at)
    c.ref = ref
    return c


def pair(prefix, *names):
    """{name_P/N or DP/DN: Net} for the differential pairs of one port."""
    nets = {}
    for name in names:
        if name == "D":
            nets["DP"], nets["DN"] = Net(f"{prefix}_DP"), Net(f"{prefix}_DN")
        else:
            nets[name + "_P"], nets[name + "_N"] = Net(f"{prefix}_{name}_P"), Net(f"{prefix}_{name}_N")
    return nets


# --------------------------------------------------------------- USB connectors
def usb3_b(ref, ref_net_prefix, vbus):
    """PC-side USB 3.0 Type-B receptacle (board acts as a device here)."""
    j = part("lcsc", "HC-USB3.0-L1845-BF",
             footprint="lcsc:USB-B-TH_9P-L18.5-W12.0", lcsc="C7501849", ref=ref)
    nets = pair(ref_net_prefix, "D", "SSTX", "SSRX")
    j["VBUS"] += vbus
    j["D+"] += nets["DP"]
    j["D-"] += nets["DN"]
    j["SSTX+"] += nets["SSTX_P"]      # PC receives on these (device TX)
    j["SSTX-"] += nets["SSTX_N"]
    j["SSRX+"] += nets["SSRX_P"]      # PC transmits on these (device RX)
    j["SSRX-"] += nets["SSRX_N"]
    j["GND"] += gnd
    j["GND_DRAN"] += gnd
    for pin in j.get_pins("SH"):
        pin += gnd
    return j, nets


pca_j, pca = usb3_b("J1", "PCA", vbus_a)
pcb_j, pcb = usb3_b("J2", "PCB", vbus_b)

# Hub side: two stacked dual USB 3.0 Type-A receptacles (board is the host).
# Pins 1-9 are one port, 10-18 the other: VBUS, D-, D+, GND, SSRX-, SSRX+,
# GND_DRAIN, SSTX-, SSTX+.  PORT_PINS says which hub port lands on which
# half (the routing scripts read the nets off the pads, so only this table
# decides it).  The hub presents its pairs as TX, RX, TX, RX and a stacked
# connector as TX, TX, RX, RX: ports 1 and 3 take the inner pin rows
# (10-18), whose SuperSpeed receive pair is the one that changes layer.
PORT_PINS = {1: ("J3", 9), 2: ("J3", 0), 3: ("J10", 9), 4: ("J10", 0)}
stacks = {ref: part("lcsc", "HC-USB3.0-L175-2X1-P",
                    footprint="lcsc:USB-A-TH_H181-AF2R06-12ALCR", lcsc="C7501881", ref=ref)
          for ref in ("J3", "J10")}
for j in stacks.values():
    for num in (19, 20):               # shell pegs
        for pin in j.get_pins(str(num)):
            pin += gnd
port = {}       # n -> nets at the connector
vbus_port = {}  # n -> that port's switched VBUS
for n, (ref, base) in PORT_PINS.items():
    j = stacks[ref]
    port[n] = pair(f"P{n}", "D", "SSTX", "SSRX")
    vbus_port[n] = Net(f"VBUS_P{n}")
    j[base + 1] += vbus_port[n]
    j[base + 2] += port[n]["DN"]
    j[base + 3] += port[n]["DP"]
    j[base + 4] += gnd
    j[base + 5] += port[n]["SSRX_N"]      # from the device
    j[base + 6] += port[n]["SSRX_P"]
    j[base + 7] += gnd
    j[base + 8] += port[n]["SSTX_N"]      # toward the device
    j[base + 9] += port[n]["SSTX_P"]

# Aux USB-C (power + ESP32 native USB for flashing/console), USB 2.0 only.
aux_j = part("Connector", "USB_C_Receptacle_USB2.0_16P",
             footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
             lcsc="C165948", ref="J4")
aux_dp, aux_dn = Net("AUX_DP"), Net("AUX_DN")
aux_j["VBUS"] += vbus_aux
aux_j["GND"] += gnd
aux_j["SHIELD"] += gnd
aux_j["D+"] += aux_dp
aux_j["D-"] += aux_dn
aux_j["SBU1"] += NC
aux_j["SBU2"] += NC
aux_cc1, aux_cc2 = Net("AUX_CC1"), Net("AUX_CC2")
aux_j["CC1"] += aux_cc1
aux_j["CC2"] += aux_cc2
R("5.1k", aux_cc1, gnd)            # UFP: Rd on both CC lines
R("5.1k", aux_cc2, gnd)
# What the AUX supply advertises: only the CC line the cable connects carries
# the source's pull-up (0.41 V default, 0.92 V 1.5 A, 1.68 V 3 A); the other
# sits at 0 V.  Two 100k sum them, so one ADC pin reads half of it whichever
# way the plug is in.
aux_cc_sense = Net("AUX_CC_SENSE")
R("100k", aux_cc1, aux_cc_sense)
R("100k", aux_cc2, aux_cc_sense)
C("100nF", aux_cc_sense, gnd)

# ESD: TPD4E05U06 (flow-through, 0.5 mm pitch) on every SuperSpeed pair and
# on every USB 2.0 pair that leaves the board; USBLC6 on the aux USB-C and
# DDC lines.
_usblc6 = Part("Power_Protection", "USBLC6-2SC6", dest=TEMPLATE,
               footprint="Package_TO_SOT_SMD:SOT-23-6")
_usblc6_refs = iter(f"U{i}" for i in (14, 15, 16, 19, 20))   # aux, HDMI 1, 2, 3, 4


def usblc6(io1, io2, vref):
    u = _usblc6(ref=next(_usblc6_refs))
    u.fields["LCSC"] = "C7519"
    u["I/O1"] += io1
    u["I/O2"] += io2
    u["VBUS"] += vref
    u["GND"] += gnd
    return u


usblc6(aux_dp, aux_dn, vbus_aux)

_tpd = Part("lcsc", "TPD4E05U06DQAR_C138714", dest=TEMPLATE,
            footprint="lcsc:USON-10_L2.5-W1.0-P0.50-BL")


def tpd4e(ref, nets, ch1, ch2):
    """TPD4E05U06 in flow-through: the pair runs straight under the part, so
    each NC pin (6/7/9/10) carries the net of the pin opposite it
    (5/4/2/1).  Channels are interchangeable; they are assigned to match the
    pin order of the neighbouring connector so no pair has to cross."""
    u = _tpd(ref=ref)
    u.fields["LCSC"] = "C138714"
    for pin in u.pins:
        pin.func = Pin.types.PASSIVE
    for (pp, pn, pp2, pn2), name in (((1, 2, 10, 9), ch1), ((4, 5, 7, 6), ch2)):
        u[pp] += nets[name + "_P"]
        u[pp2] += nets[name + "_P"]
        u[pn] += nets[name + "_N"]
        u[pn2] += nets[name + "_N"]
    for pin in u.get_pins("GND"):
        pin += gnd
    return u


def usb2_esd(ref, dp, dn, channel=1):
    """TPD4E05U06 on a USB 2.0 pair, flow-through on one channel (1: D+ on
    pins 1/10, D- on 2/9; 2: D+ on 4/7, D- on 5/6); the other is unused."""
    u = _tpd(ref=ref)
    u.fields["LCSC"] = "C138714"
    for pin in u.pins:
        pin.func = Pin.types.PASSIVE
    used = ((1, 10), (2, 9)) if channel == 1 else ((4, 7), (5, 6))
    for p in used[0]:
        u[p] += dp
    for p in used[1]:
        u[p] += dn
    for p in ((4, 5, 6, 7) if channel == 1 else (1, 2, 9, 10)):
        u[p] += NC
    for pin in u.get_pins("GND"):
        pin += gnd
    return u


usb2_esd("U11", pca["DP"], pca["DN"], channel=2)   # unused pads away from J1
usb2_esd("U12", pcb["DP"], pcb["DN"])
# PC side (Type-B): connector order is SSRX, SSTX
tpd4e("U17", pca, "SSRX", "SSTX")
tpd4e("U18", pcb, "SSRX", "SSTX")
# Type-A stacks: seen from the hub the SuperSpeed pairs leave each connector
# in the order TX (rows 10-18), TX (rows 1-9), RX (rows 1-9), RX (rows 10-18),
# so one part takes the two TX pairs and one the two RX pairs.
for (inner, outer), (tx_ref, rx_ref) in (((1, 2), ("U37", "U38")), ((3, 4), ("U39", "U40"))):
    both = {f"{n}{k}": v for n in (inner, outer) for k, v in port[n].items()}
    tpd4e(tx_ref, both, f"{inner}SSTX", f"{outer}SSTX")
    tpd4e(rx_ref, both, f"{outer}SSRX", f"{inner}SSRX")
# USB 2.0 (placement in layout.py decides the channel: the unused half of
# the part hangs off the side that has room)
usb2_esd("U41", port[1]["DP"], port[1]["DN"], channel=2)
usb2_esd("U42", port[2]["DP"], port[2]["DN"], channel=2)
usb2_esd("U43", port[3]["DP"], port[3]["DN"], channel=2)
usb2_esd("U44", port[4]["DP"], port[4]["DN"], channel=1)

# ------------------------------------------------------------ PC-side data muxes
# The hub's upstream port is the muxes' common side.
up = pair("UP", "D", "SSTX", "SSRX")       # at the muxes
uph = pair("UPH", "SSTX")                  # hub side of the AC-coupling caps

# SuperSpeed: HD3SS3212 (A = common/hub, B = USB A, C = USB B).  The hub's
# transmitter is AC-coupled here (USB 3: 100 nF on every TX pair); the PCs
# AC-couple theirs.  The switch gets its DC bias through the PC's receiver
# termination on the TX channel and the hub's on the RX channel
# (datasheet SLASE74F section 10.1).
ss = part("lcsc", "HD3SS3212IRKSR",
          footprint="lcsc:DHVQFN-20_L4.5-W2.5-P0.50-BL-EP", lcsc="C544517", ref="U2")
# channel 0: PC TX -> hub RX
ss["A0p"] += up["SSRX_P"]
ss["A0n"] += up["SSRX_N"]
ss["B0P"] += pca["SSRX_P"]
ss["B0N"] += pca["SSRX_N"]
ss["C0P"] += pcb["SSRX_P"]
ss["C0N"] += pcb["SSRX_N"]
# channel 1: hub TX -> PC RX
ss["A1p"] += up["SSTX_P"]
ss["A1n"] += up["SSTX_N"]
ss["B1P"] += pca["SSTX_P"]
ss["B1N"] += pca["SSTX_N"]
ss["C1P"] += pcb["SSTX_P"]
ss["C1N"] += pcb["SSTX_N"]
ss["SEL"] += usb_sel
ss["OEn"] += usb_oe_n
ss["VCC"] += v3
for pin in ss.get_pins("GND"):
    pin += gnd
ss["EP"] += gnd
ss["RSVD1"] += NC
ss["RSVD2"] += NC
C("100nF", v3, gnd, at=("U2", "VCC"))
C("1uF", v3, gnd, at=("U2", "VCC"))

_ts3 = Part("lcsc", "TS3USB221ARSER", dest=TEMPLATE,
            footprint="lcsc:UQFN-10_L2.0-W1.5-P0.50-BL")


def usb2_switch(ref, common, port1, port2, sel, oe_n, cref=None, swap=False):
    """TS3USB221A: S low = port 1.  Each pair sits on adjacent pins.  The
    part is a pair of plain analog switches, so with `swap` D+ runs through
    its "D-" channel and D- through "D+": that mirrors the pair across the
    chip where the layout needs it."""
    u = _ts3(ref=ref)
    u.fields["LCSC"] = "C128396"
    for pin in u.pins:
        if pin.func == Pin.types.UNSPEC:
            pin.func = Pin.types.PASSIVE
    p, n = ("DN", "DP") if swap else ("DP", "DN")
    u["D+"] += common[p]
    u["D-"] += common[n]
    u["1D+"] += port1[p]
    u["1D-"] += port1[n]
    u["2D+"] += port2[p]
    u["2D-"] += port2[n]
    u["S"] += sel
    u["~{OE}"] += oe_n
    u["VCC"] += v3
    u["GND"] += gnd
    if cref:
        C_ref("100nF", cref, v3, gnd)
    else:
        C("100nF", v3, gnd, at=(ref, "VCC"))
    return u


# S = L selects port 1 = USB A, like the HD3SS3212 and U4 on USB_SEL.
usb2_switch("U3", up, pca, pcb, usb_sel, usb_oe_n, cref="C3")
R("10k", usb_sel, gnd)      # default USB A
R("10k", usb_oe_n, v3)      # muxes disabled until firmware enables them

# ------------------------------------------------------------------ USB 3 hub
# TUSB8041: straps left at their internal defaults unless noted --
# FULLPWRMGMTz low (port power switching on), GANGED low (per-port control),
# PWRCTL_POL high (PWRCTL active high), AUTOENz high, BATEN[4:1] low.
hub = part("Interface_USB", "TUSB8041", lcsc="C544686", ref="U30",
           value="TUSB8041IRGCR",
           footprint="Package_DFN_QFN:QFN-64-1EP_9x9mm_P0.5mm_EP6x6mm_ThermalVias")
hub["USB_DP_UP"] += up["DP"]
hub["USB_DM_UP"] += up["DN"]
# The two upstream SuperSpeed pairs reach the hub with their lines the other
# way round than its P / M pins: wired crossed here rather than twisted on the
# board.  USB 3 receivers detect and correct a polarity inversion during link
# training (USB 3.2 section 6.4.2), so the names are only names.
hub["USB_SSRXP_UP"] += up["SSRX_N"]
hub["USB_SSRXM_UP"] += up["SSRX_P"]
hub["USB_SSTXP_UP"] += uph["SSTX_N"]
hub["USB_SSTXM_UP"] += uph["SSTX_P"]
C_ref("100nF", "C60", uph["SSTX_P"], up["SSTX_P"])
C_ref("100nF", "C61", uph["SSTX_N"], up["SSTX_N"])

hub_dn = {}     # n -> the hub's USB 2.0 pair for port n
for n in port:
    h = pair(f"H{n}", "SSTX")          # hub side of the AC-coupling caps
    hub[f"USB_SSTXP_DN{n}"] += h["SSTX_P"]
    hub[f"USB_SSTXM_DN{n}"] += h["SSTX_N"]
    C_ref("100nF", f"C{60 + 2 * n}", h["SSTX_P"], port[n]["SSTX_P"])
    C_ref("100nF", f"C{61 + 2 * n}", h["SSTX_N"], port[n]["SSTX_N"])
    hub[f"USB_SSRXP_DN{n}"] += port[n]["SSRX_P"]
    hub[f"USB_SSRXM_DN{n}"] += port[n]["SSRX_N"]
    # ports 1-3: the USB 2.0 pair goes straight to the connector
    hub_dn[n] = port[n] if n != 4 else pair("H4", "D")
    hub[f"USB_DP_DN{n}"] += hub_dn[n]["DP"]
    hub[f"USB_DM_DN{n}"] += hub_dn[n]["DN"]

for pin in hub.get_pins("VDD"):
    pin += v1
for pin in hub.get_pins("VDD33"):
    pin += v3
hub["VSS"] += gnd
hub["NC"] += NC
hub_r1 = Net("HUB_R1")
hub["USB_R1"] += hub_r1
R("9.53k", hub_r1, gnd)    # placed by layout.py FIXED_BY_NET
hub["TEST"] += gnd                       # factory test, internal pull-down

# Reset: held low until the ESP32 releases it, so both rails are long stable
# (datasheet: >= 3 ms).  1k: the internal pull-up may source 250 uA (I_OZP),
# which leaves 0.87 V on 4.7k, above VIL = 0.8 V.  In reset
# the PWRCTL pins are inputs with pull-downs: the port switches are off.
hub["GRSTz"] += hub_reset_n
R("1k", hub_reset_n, gnd, at=("U30", "GRSTz"))

# 24 MHz crystal (12 pF load: 2 x 18 pF) with the 1 M feedback resistor the
# datasheet asks for.
hub_xi, hub_xo = Net("HUB_XI"), Net("HUB_XO")
hub["XI"] += hub_xi
hub["XO"] += hub_xo
y1 = part("Device", "Crystal_GND24", footprint="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
          lcsc="C70590", value="24MHz", ref="Y1")
y1[1] += hub_xi
y1[3] += hub_xo
y1[2] += gnd
y1[4] += gnd
C("18pF", hub_xi, gnd)                   # placed by layout.py FIXED_BY_NET
C("18pF", hub_xo, gnd, at=("Y1", "3"))
R("1M", hub_xi, hub_xo)                  # placed by layout.py FIXED_BY_NET

# Upstream VBUS detect: the selected PC's VBUS through the datasheet's
# 90.9k / 10k divider (the pin takes 1.155 V at most).
hub_vbus = Net("HUB_VBUS_DET")
hub["USB_VBUS"] += hub_vbus
R("90.9k", vbus_pc, hub_vbus)
R("10k", hub_vbus, gnd)

# SMBus (optional): with HUB_CFG low the pull-ups hold SCL/SDA low at reset
# and the hub runs on its defaults.  With HUB_CFG high they are pulled up, and
# SMBUSz strapped low makes the hub an SMBus slave at 0x44 that waits for the
# ESP32 to configure it (U1/U2 off, port settings, strings, ...).
hub_scl, hub_sda, hub_cfg = Net("HUB_SCL"), Net("HUB_SDA"), Net("HUB_CFG")
hub["SCL/SMBCLK"] += hub_scl
hub["SDA/SMBDAT"] += hub_sda
R("4.7k", hub_scl, hub_cfg)
R("4.7k", hub_sda, hub_cfg)
R("10k", hub_cfg, gnd)
hub_smbusz = Net("HUB_SMBUSZ")
hub[39] += hub_smbusz
R("1k", hub_smbusz, gnd)      # 1k: same pull-up margin as GRSTz
for num in (40, 41, 42, 45):             # straps at their internal defaults
    hub[num] += NC

# decoupling: 100 nF at every supply pin (placed pin by pin in make_pcb.py),
# 10 uF bulk on each rail
for i in range(8):
    C_ref("100nF", f"C{70 + i}", v1, gnd)
for i in range(4):
    C_ref("100nF", f"C{78 + i}", v3, gnd)
C_ref("10uF", "C82", v1, gnd)
C_ref("10uF", "C83", v3, gnd)

# ------------------------------------------------------------------ port power
# PC-side source: TPS2116 in manual mode (MODE tied high), PR1 on USB_SEL:
# PR1 high (USB B) -> VIN1, PR1 low (USB A) -> VIN2.  Also what the hub sees
# as its upstream VBUS.
pm = part("Power_Management", "TPS2116DRL", lcsc="C3235557", ref="U4")
pm["VIN1"] += vbus_b
pm["VIN2"] += vbus_a
pm["PR1"] += usb_sel
pm["MODE"] += v3
for pin in pm.get_pins("VOUT"):
    pin += vbus_pc
pm["GND"] += gnd
pm["ST"] += NC
C_ref("1uF", "C4", vbus_a, gnd, at=("U4", "VIN2"))
C_ref("1uF", "C5", vbus_b, gnd, at=("U4", "VIN1"))
C_ref("1uF", "C6", vbus_pc, gnd, at=("U4", "VOUT"))

# Port supply: a second TPS2116 in priority mode (MODE = VIN1) puts the ports
# on the AUX input whenever it is above ~4.3 V (PR1 = 1 V through 33k / 10k),
# so a charger there makes this a powered hub; otherwise on the selected PC.
pa = part("Power_Management", "TPS2116DRL", lcsc="C3235557", ref="U32")
aux_pr1 = Net("AUX_PR1")
pa["VIN1"] += vbus_aux
pa["VIN2"] += vbus_pc
pa["PR1"] += aux_pr1
pa["MODE"] += vbus_aux
for pin in pa.get_pins("VOUT"):
    pin += vbus_hub
pa["GND"] += gnd
pa["ST"] += NC
R("33k", vbus_aux, aux_pr1)
R("10k", aux_pr1, gnd)
C_ref("1uF", "C7", vbus_aux, gnd, at=("U32", "VIN1"))
C_ref("10uF", "C8", vbus_hub, gnd, at=("U32", "VOUT"))
C_ref("1uF", "C27", vbus_pc, gnd, at=("U32", "VIN2"))    # VIN2's own input capacitor (C6 is U4's output)
# reservoir for the port switches, one per connector stack: a device being
# plugged in fills its input capacitors from here, not from the supply cable
C_ref("100uF", "C9", vbus_hub, gnd)
C_ref("100uF", "C10", vbus_hub, gnd)

# One current-limited switch per port, driven by the hub (PWRCTLn, active
# high) and reporting to it (OVERCURnz, internal pull-ups), so the PC can
# power-cycle a port and sees an over-current on the port that caused it.
# R_ILIM = 20k -> 1.20..1.38 A (datasheet), above USB 3's 900 mA.
for n in port:
    sw = part("lcsc", "TPS2553DBVR", footprint="lcsc:SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BR",
              lcsc="C55266", ref=f"U{32 + n}")
    en, fault, ilim = Net(f"P{n}_PWR_EN"), Net(f"P{n}_OC_N"), Net(f"P{n}_ILIM")
    sw["IN"] += vbus_hub
    sw["OUT"] += vbus_port[n]
    sw["EN"] += en
    sw["/FAULT"] += fault
    sw["ILIM"] += ilim
    sw["GND"] += gnd
    hub[f"PWRCTL{n}/BATEN{n}"] += en
    hub[f"OVERCUR{n}z"] += fault
    R("20k", ilim, gnd, at=(sw.ref, "ILIM"))     # sets the limit: at the pin
    C("100nF", vbus_hub, gnd, at=(sw.ref, "IN"))
    # (ports 3/4: layout.py keeps the band between the hub's east pins and
    # these switches free of passives, so their capacitors stay out of it)
    C("22uF", vbus_port[n], gnd, at=(sw.ref, "OUT"))
    C("22uF", vbus_port[n], gnd, at=(sw.ref, "OUT"))
    C("100nF", vbus_port[n], gnd, at=(sw.ref, "OUT"))

# --------------------------------------------------------- system power
# Ideal-diode OR of USB A / USB B / AUX VBUS -> +5V_SYS.  CE tied to VOUT
# enables the LM66100's reverse-current blocking (datasheet pin table).
for i, vin in enumerate((vbus_a, vbus_b, vbus_aux)):
    d = part("Power_Management", "LM66100DCK", lcsc="C2869734", ref=f"U{6 + i}")
    d["VIN"] += vin
    d["VOUT"] += v5
    d["~{CE}"] += v5
    d["GND"] += gnd
    d["ST"] += NC
    d["NC"] += NC
# 1 uF on each LM66100 VIN (datasheet 10.2 / 11.1) and 10 uF on +5V_SYS
C_ref("1uF", "C23", vbus_a, gnd, at=("U6", "VIN"))
C_ref("1uF", "C24", vbus_b, gnd, at=("U7", "VIN"))
C_ref("1uF", "C26", vbus_aux, gnd, at=("U8", "VIN"))
C_ref("10uF", "C25", v5, gnd, at=("U6", "VOUT"))   # U6/U7's shared output, beside them


def buck(ref, lref, vout, r_top, r_bottom):
    """TLV62569 (2 A, 1.5 MHz): VOUT = 0.6 V x (1 + r_top / r_bottom),
    2.2 uH, 10 uF in, 2 x 10 uF out."""
    u = part("Regulator_Switching", "TLV62569DBV", lcsc="C141836", ref=ref)
    sw, fb = Net(f"{ref}_SW"), Net(f"{ref}_FB")
    u["VIN"] += v5
    u["EN"] += v5
    u["GND"] += gnd
    u["SW"] += sw
    u["FB"] += fb
    C("10uF", v5, gnd, at=(ref, "VIN"))
    l = part("lcsc", "SWPA3015S2R2MT", footprint="lcsc:IND-SMD_L3.0-W3.0",
             lcsc="C43389", value="2.2uH", ref=lref)
    l[1] += sw
    l[2] += vout
    R(r_top, vout, fb, at=(ref, "FB"))
    R(r_bottom, fb, gnd, at=(ref, "FB"))
    C("10uF", vout, gnd, at=(lref, "2"))
    C("10uF", vout, gnd, at=(lref, "2"))
    return u


buck("U5", "L1", v3, "100k", "22k")      # 3.33 V
buck("U31", "L2", v1, "10k", "12k")      # 1.10 V: hub core + RP2350 core

# VBUS sense dividers, 10k/15k = 0.6: even an out-of-spec 5.5 V port gives
# 3.3 V (ESP32 inputs: max VDD + 0.3 V), and the lowest legal VBUS (4.4 V)
# still reads high (2.64 V > 0.75 * VDD).
sense = {}
for name, vb in (("A", vbus_a), ("B", vbus_b), ("AUX", vbus_aux)):
    s = Net(f"VBUS_{name}_SENSE")
    R("10k", vb, s)
    R("15k", s, gnd)
    sense[name] = s

# -------------------------------------------------------------- HDMI ports
def hdmi_stack(ref):
    """Two HDMI Type-A receptacles stacked in one part (Foxconn QJ11191-DFB2-4H,
    through-hole): the lower port's pins are 1-19, the upper port's P1-P19,
    shell and posts pad 0.  DDC/CI only: SCL/SDA/+5V, no TMDS, HPD unused."""
    j = part("lcsc", "QJ11191-DFB2-4H", footprint="lcsc:HDMI-TH_QJ11191-DFB1-4F",
             lcsc="C225760", ref=ref)
    for pin in j.pins:
        if pin.num == "0":
            pin += gnd                      # shell
        elif pin.name.startswith("TMDS") or pin.name in ("CEC", "Reserved(N.C.)", "HotPlugDetect"):
            # HPD not used: DDC/CI needs only SDA/SCL and +5V.  (Reading it would
            # put a monitor-driven 2.4-5.3 V signal on an ESP32 pin, even while
            # picoKVM is unpowered.)  Firmware finds a monitor by probing I2C 0x50.
            pin += NC
    return j


def hdmi_port(n, j, upper, refs, p5_d=None):
    """One port of a stack j (upper or lower) as monitor n: +5V on pin 18
    through an ideal diode and a PTC, DDC pull-ups to that 5 V, ESD on
    SCL/SDA.  refs = (LM66100, PTC).  With p5_d (the other port's diode
    output) the port shares that diode: refs[0] is then unused.  Returns
    (SCL, SDA, diode output)."""
    pfx = "P" if upper else ""
    p5 = Net(f"HDMI{n}_5V")
    scl5, sda5 = Net(f"HDMI{n}_SCL"), Net(f"HDMI{n}_SDA")

    # +5V to the monitor (HDMI wants 4.8-5.3 V on pin 18): LM66100 ideal
    # diode for anti-backfeed (~5 mV drop, vs ~0.3 V for a Schottky; CE tied
    # to VOUT enables its reverse blocking) + 100 mA PTC per port.  One
    # diode per stacked connector: its two ports draw ~55 mA each (1.5 A
    # part), and their PTCs stand side by side.
    if p5_d is None:
        p5_d = Net(f"HDMI{n}_5V_D")
        d = part("Power_Management", "LM66100DCK", lcsc="C2869734", ref=refs[0])
        d["VIN"] += v5
        C("1uF", v5, gnd, at=(d.ref, "VIN"))   # its input capacitor (datasheet 10.2)
        d["VOUT"] += p5_d
        d["~{CE}"] += p5_d
        d["GND"] += gnd
        d["ST"] += NC
        d["NC"] += NC
    else:
        # keep the shared port's capacitor number (C168 / C170) reserved: every
        # later capacitor keeps its reference, so placement_freeze.py still fits
        next(_c_auto)
    f = part("Device", "Polyfuse", footprint="Fuse:Fuse_0805_2012Metric",
             lcsc="C20975", value="100mA", ref=refs[1])
    f[1] += p5_d
    f[2] += p5
    C("100nF", p5, gnd)

    j[pfx + "18"] += p5                    # +5V Power
    j[pfx + "15"] += scl5                  # SCL
    j[pfx + "16"] += sda5                  # SDA
    j[pfx + "17"] += gnd                   # DDC/CEC ground

    # No level shifter: the I2C multiplexer U13 runs from 3.3 V, so its pass
    # gates never let more than 2.8 V through to the ESP32 side (TCA9548A
    # datasheet 5.5, Vo(sw), and 8.2.1 "voltage translation"), while these
    # pull-ups take the monitor side to 5 V.  Its channel pins are 5 V
    # tolerant with or without supply, so a powered monitor on an unpowered
    # picoKVM is fine too.
    R("2k", scl5, p5)              # HDMI source pull-ups (1.5k–2k spec)
    R("2k", sda5, p5)
    usblc6(scl5, sda5, p5)
    return scl5, sda5, p5_d


# Four monitors on two stacked connectors: J5 (left) lower = HDMI 1, upper =
# HDMI 3; J6 (right) lower = HDMI 2, upper = HDMI 4.  Monitors 1/2 keep their
# rev-B-with-two-ports multiplexer channels 0/1; 3/4 are on channels 4/5.
j5, j6 = hdmi_stack("J5"), hdmi_stack("J6")
ddc1_scl, ddc1_sda, j5_5v = hdmi_port(1, j5, False, ("U21", "F2"))
ddc2_scl, ddc2_sda, j6_5v = hdmi_port(2, j6, False, ("U22", "F3"))
ddc3_scl, ddc3_sda, _ = hdmi_port(3, j5, True, (None, "F6"), p5_d=j5_5v)    # J5's diode U21
ddc4_scl, ddc4_sda, _ = hdmi_port(4, j6, True, (None, "F7"), p5_d=j6_5v)    # J6's diode U22

# ------------------------------------------------- RP2350: keyboard interception
# Wired like a Raspberry Pi Pico 2 where it matters, so hid-remapper's stock
# Pico 2 build runs unchanged: 12 MHz crystal, PIO-USB host on GPIO0 (D+) /
# GPIO1 (D-), LED on GPIO25.
rp = part("MCU_RaspberryPi", "RP2350A", lcsc="C42411118", ref="U45",
          footprint="Package_DFN_QFN:QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm_ThermalVias")
rp["GND"] += gnd
for name in ("IOVDD", "QSPI_IOVDD", "USB_OTP_VDD", "ADC_AVDD", "VREG_AVDD", "VREG_VIN"):
    for pin in rp.get_pins(name):
        pin += v3
for pin in rp.get_pins("DVDD"):
    pin += v1
# Core supply from the board's 1.1 V rail instead of the on-chip switcher
# (RP2350 datasheet, "External core supply with on-chip regulator disabled",
# figure 24): VREG_VIN / VREG_AVDD stay on 3.3 V for the power-on reset and
# brown-out detector, VREG_FB to ground, no inductor.  So Raspberry Pi's
# polarised inductor (AOTA-B201610S3R3-101-T) does not apply to this board.
rp["VREG_FB"] += gnd
rp["VREG_PGND"] += gnd
rp["VREG_LX"] += NC
for i in range(4):
    C_ref("100nF", f"C{84 + i}", v3, gnd)     # IOVDD / QSPI / USB / ADC
for i in range(3):
    C_ref("100nF", f"C{88 + i}", v1, gnd)     # DVDD
C_ref("4.7uF", "C91", v3, gnd)                # VREG_VIN
C_ref("100nF", "C92", v3, gnd)                # VREG_AVDD

# Crystal circuit exactly as Raspberry Pi specify it ("Hardware design with
# RP2350", ch. 4; same as the Pico 2): Abracon ABM8-272-T3 (12 MHz, 10 pF
# load, ESR <= 50 ohm), 2 x 15 pF, 1k in series with XOUT against overdrive.
# They tuned the oscillator for this part; another crystal needs testing
# over temperature.
rp_xin, rp_xout, rp_xout_r = Net("RP_XIN"), Net("RP_XOUT"), Net("RP_XOUT_R")
rp["XIN"] += rp_xin
rp["XOUT"] += rp_xout
y2 = part("Device", "Crystal_GND24", footprint="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
          lcsc="C20625731", value="ABM8-272-T3", ref="Y2")
y2[1] += rp_xin
y2[3] += rp_xout_r
y2[2] += gnd
y2[4] += gnd
R("1k", rp_xout, rp_xout_r)
C("15pF", rp_xin, gnd)
C("15pF", rp_xout_r, gnd)

# Flash: W25Q32JV-IQ, 4 MB like the Pico 2 (quad enable set at the factory,
# so /WP and /HOLD are plain data lines), in the narrow SOIC-8.
flash = part("Memory_Flash", "W25Q128JVS", lcsc="C5355146", ref="U46",
             value="W25Q32JVSNIQ", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
qspi = {name: Net(f"RP_QSPI_{name}") for name in ("SS", "SCLK", "SD0", "SD1", "SD2", "SD3")}
rp["~{QSPI_SS}"] += qspi["SS"]
rp["QSPI_SCLK"] += qspi["SCLK"]
for i in range(4):
    rp[f"QSPI_SD{i}"] += qspi[f"SD{i}"]
flash[1] += qspi["SS"]
flash[2] += qspi["SD1"]
flash[3] += qspi["SD2"]
flash[4] += gnd
flash[5] += qspi["SD0"]
flash[6] += qspi["SCLK"]
flash[7] += qspi["SD3"]
flash[8] += v3
C("100nF", v3, gnd)
R("10k", qspi["SS"], v3)

# The ESP32 reaches the flash through 1k resistors: with the RP2350 held in
# reset (RP_RUN low) its QSPI pads are released and the ESP32 programs the
# flash as a plain SPI device; pulling RP_QSPI_SS low through its 1k while
# releasing RUN starts the RP2350 in USB boot mode instead.  The resistors sit
# at the flash, so the ESP32's tracks are not stubs on the QSPI bus.
rp_prog = {name: Net(f"RP_PROG_{name}") for name in ("SS", "SCLK", "SD0", "SD1")}
FLASH_PIN = {"SS": "1", "SD1": "2", "SD0": "5", "SCLK": "6"}   # W25Q32 SOIC-8
for name, net in rp_prog.items():
    R("1k", qspi[name], net, at=("U46", FLASH_PIN[name]))
rp_run = Net("RP_RUN")
rp["RUN"] += rp_run
R("10k", rp_run, v3)

# Four lines to the ESP32, all Pico 2 header GPIOs (so hid-remapper's Pico 2
# build may map them; output mode "0 = high impedance, 1 = low"), on the side
# of the chip that faces the ESP32, 220R in series against contention, idle
# high through 10k:
#   GPIO22  toggle: straight onto the PC-switch button line (BTN_SWITCH), so
#           it works with firmware that knows nothing about the RP2350
#   GPIO20  RP_LINK_TX   GPIO21  RP_LINK_RX   GPIO26  RP_LINK_ATTN
# With stock hid-remapper the three RP_LINK lines are plain hotkey outputs
# (e.g. "go to PC A" / "go to PC B" / spare).  For a richer protocol
# GPIO20 / GPIO21 are UART1 TX / RX (also I2C0 SDA / SCL) and GPIO26 is free
# as an attention / interrupt line; the ESP32 side can take any role.
btn = Net("BTN_SWITCH")
rp_link = {}
for gpio, net in ((22, btn), (20, Net("RP_LINK_TX")), (21, Net("RP_LINK_RX")),
                  (26, Net("RP_LINK_ATTN"))):
    at_rp = Net(f"RP_GPIO{gpio}")
    rp[f"GPIO{gpio}/ADC0" if gpio == 26 else f"GPIO{gpio}"] += at_rp
    R("220", at_rp, net)
    if net is not btn:
        R("10k", net, v3)    # idle high (the button line has its own pull-up)
        rp_link[net.name] = net

# activity LED (hid-remapper blinks GPIO25)
rp_led, rp_led_k = Net("RP_LED"), Net("RP_LED_K")
rp["GPIO25"] += rp_led
d5 = part("Device", "LED", footprint="LED_SMD:LED_0603_1608Metric", lcsc="C2286",
          value="KBD", ref="D5")
d5["A"] += rp_led
d5["K"] += rp_led_k
R("1k", rp_led_k, gnd)

# SWD test pads
for name, pin in (("SWCLK", "SWCLK"), ("SWDIO", "SWDIO")):
    net = Net(f"RP_{name}")
    rp[pin] += net
    tp = part("Connector", "TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
              value=name, ref={"SWCLK": "TP1", "SWDIO": "TP2"}[name])
    tp[1] += net

# Keyboard port (hub port 4), USB 2.0 pair.  Two TS3USB221A on KBD_INTERCEPT:
#   low  (default): connector <-> U47 <-> KBT <-> U48 <-> hub port 4
#   high          : connector <-> U47 <-> RP2350 PIO-USB host (GPIO0 / GPIO1)
#                   hub port 4 <-> U48 <-> RP2350 native USB (device)
kbt = pair("KBT", "D")           # straight-through link between the switches
kbh = pair("KBH", "D")           # RP2350 host side, at the switch
kbd = pair("KBD", "D")           # RP2350 device side, at the switch
usb2_switch("U47", port[4], kbt, kbh, kbd_intercept, gnd, swap=True)
usb2_switch("U48", hub_dn[4], kbt, kbd, kbd_intercept, gnd)
R("10k", kbd_intercept, gnd)     # plain hub port until firmware says otherwise
# host side: 27R in series, and the host's pull-downs.  8.2k rather than
# USB's 15k so that RP2350 A2 silicon (erratum E9: an input pad leaks up to
# ~120 uA towards 2.2 V) still reads a disconnected line as low; a device's
# 1.5k pull-up still gives 2.8 V.
rp_hdp, rp_hdn = Net("RP_HOST_DP"), Net("RP_HOST_DN")
rp["GPIO0"] += rp_hdp
rp["GPIO1"] += rp_hdn
R("27", rp_hdp, kbh["DP"])
R("27", rp_hdn, kbh["DN"])
R("8.2k", kbh["DP"], gnd, at=("U47", "4"))     # at U47's port-2 pins (2D-/2D+ carry KBH_DP/DN)
R("8.2k", kbh["DN"], gnd, at=("U47", "3"))
# device side: 27R in series (RP2350 datasheet)
rp_ddp, rp_ddn = Net("RP_USB_DP"), Net("RP_USB_DN")
rp["USB_DP"] += rp_ddp
rp["USB_DM"] += rp_ddn
R("27", rp_ddp, kbd["DP"])
R("27", rp_ddn, kbd["DN"])

for pin in rp.pins:
    if not pin.nets:
        pin += NC

# ----------------------------------------------------------------- ESP32-S3
mcu = part("RF_Module", "ESP32-S3-WROOM-1", lcsc="C2913204",
           value="ESP32-S3-WROOM-1-N8R2", ref="U1")   # 8 MB flash, 2 MB quad PSRAM
mcu["3V3"] += v3
for pin in mcu.get_pins("GND"):
    pin += gnd
C("22uF", v3, gnd)
C("100nF", v3, gnd)

en, boot = Net("EN"), Net("BOOT")
mcu["EN"] += en
R("10k", en, v3)
C("1uF", en, gnd)
mcu["IO0"] += boot
R("10k", boot, v3)

_sw = Part("Switch", "SW_Push", dest=TEMPLATE,
           footprint="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A")


def button(net, label):
    s = _sw(value=label)
    s.fields["LCSC"] = "C571338"   # TS-1187A-C-F-B: 3 mm tall, for lid flexure buttons
    s[1] += net
    s[2] += gnd
    return s


button(en, "RESET").ref = "SW1"
button(boot, "BOOT").ref = "SW2"
button(btn, "SWITCH").ref = "SW3"
R("10k", btn, v3)

# Pins shared with rev A keep their GPIO where the function still exists;
# BOARD_REV tells the boards apart (rev A leaves GPIO15 open).  Differences
# from rev A (README.md, "Rev B: differences from rev A"): GPIO1 / GPIO2 are
# the I2C bus to the multiplexer U13 instead of HDMI 1's DDC, GPIO4 is the
# multiplexer's reset instead of HDMI 2's SDA, GPIO5 is free.
i2c_sda, i2c_scl, i2c_reset_n = Net("I2C_SDA"), Net("I2C_SCL"), Net("I2C_MUX_RESET_N")
mcu["IO1"] += i2c_sda
mcu["IO2"] += i2c_scl
mcu["IO4"] += i2c_reset_n
mcu["IO8"] += usb_sel
mcu["IO9"] += usb_oe_n
mcu["IO10"] += hub_reset_n           # rev A: PERIPH_EN (same meaning: high = ports on)
mcu["IO11"] += sense["A"]
mcu["IO12"] += sense["B"]
mcu["IO13"] += btn
mcu["USB_D-"] += aux_dn
mcu["USB_D+"] += aux_dp
board_rev = Net("BOARD_REV")
mcu["IO15"] += board_rev
R("10k", board_rev, gnd)             # low = rev B
# rev A's PERIPH_FAULT_N: no single fault line any more (the hub handles
# over-current per port); pulled up so rev A firmware reads "no fault"
fault_compat = Net("PERIPH_FAULT_N")
mcu["IO16"] += fault_compat
R("10k", fault_compat, v3)
# new in rev B
mcu["IO6"] += aux_cc_sense           # ADC1: what the AUX supply advertises
mcu["IO7"] += sense["AUX"]
mcu["IO21"] += kbd_intercept
mcu["IO40"] += hub_cfg
mcu["IO42"] += rp_link["RP_LINK_TX"]     # RP2350 -> ESP32
mcu["IO47"] += rp_link["RP_LINK_RX"]     # ESP32 -> RP2350
mcu["IO41"] += rp_link["RP_LINK_ATTN"]
mcu["IO48"] += rp_run
mcu["IO35"] += rp_prog["SS"]
mcu["IO36"] += rp_prog["SCLK"]
mcu["IO37"] += rp_prog["SD0"]
mcu["IO18"] += rp_prog["SD1"]

# Status LED: one side-emitting SK6812 (WS2812-compatible RGB) on the front
# edge; firmware sets its colour per selected PC.  VDD is +5V_SYS through a
# diode (~4.3 V) so the 3.3 V data line clears VIH = 0.65 * VDD with margin.
# DOUT stays open (no chain).
led_din, led_vdd = Net("LED_DIN"), Net("LED_VDD")
rgb = part("lcsc", "SK6812SIDE-A_C5378721", footprint="lcsc:LED-SMD_4P-L4.0-W1.6-L",
           lcsc="C5378721", value="SK6812SIDE-A", ref="D3")
rgb["DIN"] += led_din
rgb["VDD"] += led_vdd
rgb["GND"] += gnd
rgb["DOUT"] += NC          # single LED, no chain
led_rgb = Net("LED_RGB")
mcu["IO14"] += led_rgb
R("100", led_rgb, led_din)
d_led = part("Device", "D", footprint="Diode_SMD:D_SOD-123", lcsc="C81598",
             value="1N4148W", ref="D4")
d_led[2] += v5        # anode
d_led[1] += led_vdd   # cathode
C("100nF", led_vdd, gnd)

# UART0 on two test pads (no header: the console is on the aux USB-C)
for name, pin, ref in (("TXD0", "TXD0", "TP3"), ("RXD0", "RXD0", "TP4")):
    net = Net(name)
    mcu[pin] += net
    tp = part("Connector", "TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
              value=name, ref=ref)
    tp[1] += net

# Grove port for a remote PC-switch button with its own RGB LED, in parallel
# with SW3.  Pinout follows M5Stack (e.g. Unit Key, U144): yellow = LED data
# (SK6812 DIN, drive as a NeoPixel), white = key (unit pulls up to its own
# 3.3 V), red = 5 V (the unit regulates to 3.3 V), black = GND.
# 100R in series on the signals and a 100 mA PTC on the 5 V: the cable
# leaves the board.  Note: Seeed Grove modules that pull their signal up to
# VCC would put 5 V on an ESP32 pin -- not for those.
ext_led = Net("EXT_LED")
mcu["IO17"] += ext_led
grove_btn, grove_led, grove_5v = Net("GROVE_BTN"), Net("GROVE_LED"), Net("GROVE_5V")
R("100", btn, grove_btn)
R("100", ext_led, grove_led)
f_grove = part("Device", "Polyfuse", footprint="Fuse:Fuse_0805_2012Metric",
               lcsc="C20975", value="100mA", ref="F4")
f_grove[1] += v5
f_grove[2] += grove_5v
C("100nF", grove_5v, gnd)
grove = part("lcsc", "ZX-HY2.0-4PWT", footprint="lcsc:CONN-SMD_4P-P2.00_ZX-HY2.0-4PWT",
             lcsc="C7429571", value="GROVE_BTN", ref="J8")
# Wired by physical position, not by "pin 1": looking into any Grove socket
# with the latch window on top, the contacts read GND, 5 V, LED, key from
# left to right (checked on a real Unit Key: black, red, yellow, white).
# This LCSC footprint numbers its pads from the other end, so pad 1 = GND.
grove[1] += gnd         # black
grove[2] += grove_5v    # red
grove[3] += grove_led   # M5 yellow, next to 5 V
grove[4] += grove_btn   # M5 white, outer
for pin in grove.pins:          # mounting tabs
    if pin.num not in ("1", "2", "3", "4"):
        pin += gnd

# I2C multiplexer: one ESP32 I2C controller (GPIO1 SDA / GPIO2 SCL) reaches
# every bus through U13 (TCA9548A, address 0x70): write a channel mask, then
# talk to the device.  The two monitors both answer at 0x37, so they need a
# bus each anyway, and ESPHome has no bit-banged I2C to add buses with.
#   channel 0  HDMI 1 DDC (5 V)  channel 2  hub SMBus (0x44)   channel 4  HDMI 3 DDC
#   channel 1  HDMI 2 DDC      channel 3  Grove I2C port J11  channel 5  HDMI 4 DDC
# Powered from 3.3 V its pass gates clamp what comes back from a channel to
# below 3.3 V, so a Grove module that pulls its lines up to 5 V is safe.
# RESET (low, from GPIO4) drops every channel: the way out when a device
# holds a bus low.  No power-on select: all channels are off until written.
# Firmware rule: select channel 2 only while HUB_CFG is high (with it low
# the hub's pull-ups hold that bus low on purpose).
mux = part("Interface_Expansion", "TCA9548APWR",
           footprint="Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm", lcsc="C130026", ref="U13")
mux[24] += v3
mux[12] += gnd
C("100nF", v3, gnd)
for a in (1, 2, 21):                 # A0-A2 low: 0x70
    mux[a] += gnd
mux[23] += i2c_sda
mux[22] += i2c_scl
mux[3] += i2c_reset_n
R("4.7k", i2c_sda, v3)
R("4.7k", i2c_scl, v3)
R("10k", i2c_reset_n, v3)
grove_sda, grove_scl = Net("GROVE_SDA"), Net("GROVE_SCL")
for ch, (sda, scl) in enumerate(((ddc1_sda, ddc1_scl), (ddc2_sda, ddc2_scl),
                                 (hub_sda, hub_scl), (grove_sda, grove_scl))):
    mux[4 + 2 * ch] += sda           # SDn
    mux[5 + 2 * ch] += scl           # SCn
# channels 4/5 (TSSOP pins 13-16): HDMI 3 / HDMI 4
mux[13] += ddc3_sda
mux[14] += ddc3_scl
mux[15] += ddc4_sda
mux[16] += ddc4_scl
for n in range(17, 21):              # channels 6-7 unused
    mux[n] += NC

# Second Grove port: I2C, M5Stack port A pinout (yellow = SDA, white = SCL,
# red = 5 V, black = GND), on multiplexer channel 3.  Pull-ups to 3.3 V on
# the board, 100R in series and its own 100 mA PTC: the cable leaves the board.
grove2_5v = Net("GROVE2_5V")
grove_sda_c, grove_scl_c = Net("GROVE_SDA_C"), Net("GROVE_SCL_C")
R("4.7k", grove_sda, v3)
R("4.7k", grove_scl, v3)
R("100", grove_sda, grove_sda_c)
R("100", grove_scl, grove_scl_c)
f_grove2 = part("Device", "Polyfuse", footprint="Fuse:Fuse_0805_2012Metric",
                lcsc="C20975", value="100mA", ref="F5")
f_grove2[1] += v5
f_grove2[2] += grove2_5v
C("100nF", grove2_5v, gnd)
grove2 = part("lcsc", "ZX-HY2.0-4PWT", footprint="lcsc:CONN-SMD_4P-P2.00_ZX-HY2.0-4PWT",
              lcsc="C7429571", value="GROVE_I2C", ref="J11")
grove2[1] += gnd          # same physical order as J8: GND, 5 V, yellow, white
grove2[2] += grove2_5v
grove2[3] += grove_sda_c  # yellow
grove2[4] += grove_scl_c  # white
for pin in grove2.pins:
    if pin.num not in ("1", "2", "3", "4"):
        pin += gnd

for pin in mcu.pins:
    if not pin.nets:
        pin += NC

# Mounting holes
for _ in range(4):
    Part("Mechanical", "MountingHole",
         footprint="MountingHole:MountingHole_3.2mm_M3")

# ---------------------------------------------------------------- outputs
if __name__ == "__main__":
    ERC()
    generate_netlist(file_=os.path.join(OUT, "kvm_board.net"))

    by_ref = {p.ref: p for p in default_circuit.parts}

    def at_pin(p):
        """[ref, pad number] of the pin `p` must sit next to, or None."""
        if p not in AT:
            return None
        ref, pin = AT[p]
        nums = [q.num for q in by_ref[ref].pins if str(pin) in (q.num, q.name)]
        assert nums, f"{p.ref}: no pin {pin} on {ref}"
        return [ref, nums[0]]

    parts = []
    for p in default_circuit.parts:
        parts.append({
            "ref": p.ref,
            "value": str(p.value),
            "footprint": p.footprint,
            "lcsc": p.fields.get("LCSC", ""),
            "symbol": p.name,
            "description": getattr(p, "description", "") or "",
            "pads": {pin.num: pin.net.name for pin in p.pins
                     if pin.net is not None and pin.is_connected()},
            "pin_names": {pin.num: pin.name for pin in p.pins},
            "at": at_pin(p),
        })
    with open(os.path.join(OUT, "kvm_board.json"), "w") as f:
        json.dump(parts, f, indent=1)
    print(f"{len(parts)} parts written")
