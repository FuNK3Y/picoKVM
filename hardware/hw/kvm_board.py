"""
KVM controller board — circuit description (SKiDL).

ESP32-S3 + USB 3.0 2:1 switch (USB A / USB B -> peripheral port) + 2x HDMI
DDC/CI control ports.  This file is the source of truth for the schematic:
running it produces the KiCad netlist, a JSON parts/nets dump (consumed by
make_pcb.py) and the ERC report.

Signal conventions (one job per GPIO)
  USB_SEL        low = USB A, high = USB B: USB 3 + USB 2 data muxes *and* the
                 peripheral power source (TPS2116 PR1) switch together
  USB_OE_N       low = data muxes enabled (pulled up: off until firmware runs)
  PERIPH_EN      high = peripheral VBUS on (TPS2553, pulled down: off at reset)
  PERIPH_FAULT_N low = peripheral over-current / over-temperature (input)
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
# Fixed refs: U1 ESP32-S3, U2 HD3SS3212, U3 TS3USB221A, U4 TPS2116, U5 AP2112K,
# U6-U8 LM66100 (A/B/AUX), U9-U10 PCA9306, U11-U13 TPD4E05U06 (USB 2), U14-U16 USBLC6, U17-U19 TPD4E05U06,
# J1 USB A, J2 USB B, J3 peripheral, J4 aux USB-C, J5/J6 HDMI1/2, J7 UART.
# JLCPCB/LCSC numbers (stock checked 2026-10-01).  "base" = JLC basic part.
LCSC_R = {  # 0402 1% UniOhm, all basic
    "1k": "C11702", "2k": "C4109", "4.7k": "C25900", "5.1k": "C25905",
    "10k": "C25744", "20k": "C25765", "200k": "C25764", "100": "C25076",
    "220": "C25091", "15k": "C25756",
}
LCSC_C = {  # value -> (footprint, LCSC), all basic
    "10nF": ("Capacitor_SMD:C_0402_1005Metric", "C15195"),
    "100nF": ("Capacitor_SMD:C_0402_1005Metric", "C1525"),
    "1uF": ("Capacitor_SMD:C_0402_1005Metric", "C52923"),
    "10uF": ("Capacitor_SMD:C_0805_2012Metric", "C15850"),
    "22uF": ("Capacitor_SMD:C_0805_2012Metric", "C45783"),
}

_r = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0402_1005Metric")
_c = Part("Device", "C", dest=TEMPLATE)


def R(value, a, b):
    r = _r(value=value)
    r.fields["LCSC"] = LCSC_R[value]
    r[1] += a
    r[2] += b
    return r


def C(value, a, b):
    fp, lcsc = LCSC_C[value]
    c = _c(value=value, footprint=fp)
    c.fields["LCSC"] = lcsc
    c[1] += a
    c[2] += b
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
v5 = Net("+5V_SYS")
for n in (gnd, v3, v5):
    n.drive = 100  # power nets: let ERC treat them as driven
vbus_a, vbus_b, vbus_aux = Net("VBUS_A"), Net("VBUS_B"), Net("VBUS_AUX")
vbus_per = Net("VBUS_PERIPH")
vbus_per_raw = Net("VBUS_PERIPH_RAW")
for n in (vbus_a, vbus_b, vbus_aux):
    n.drive = 100  # sourced by the PC / aux cable through the connector
# Intentional OR of power outputs: 3x LM66100 onto +5V_SYS, and the two
# TPS2116 VOUT pins onto VBUS_PERIPH_RAW.
v5.do_erc = False
vbus_per_raw.do_erc = False

usb_sel, usb_oe_n = Net("USB_SEL"), Net("USB_OE_N")
periph_en, periph_fault_n = Net("PERIPH_EN"), Net("PERIPH_FAULT_N")

# --------------------------------------------------------------- USB connectors
def usb3_b(ref, ref_net_prefix, vbus):
    """PC-side USB 3.0 Type-B receptacle (board acts as a device here)."""
    j = part("lcsc", "HC-USB3.0-L1845-BF",
             footprint="lcsc:USB-B-TH_9P-L18.5-W12.0", lcsc="C7501849", ref=ref)
    p = ref_net_prefix
    nets = {k: Net(f"{p}_{k}") for k in
            ("DP", "DN", "SSTX_P", "SSTX_N", "SSRX_P", "SSRX_N")}
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

# Peripheral side: USB 3.0 Type-A receptacle (board acts as the host here).
per_j = part("lcsc", "HC-USB3.0-L168-WP",
             footprint="lcsc:USB-TH_USB3.0-A", lcsc="C7501850", ref="J3")
per = {k: Net(f"PER_{k}") for k in
       ("DP", "DN", "SSTX_P", "SSTX_N", "SSRX_P", "SSRX_N")}
per_j["VBUS"] += vbus_per
per_j["D+"] += per["DP"]
per_j["D-"] += per["DN"]
per_j["SSTX+"] += per["SSTX_P"]       # toward the device
per_j["SSTX-"] += per["SSTX_N"]
per_j["SSRX+"] += per["SSRX_P"]       # from the device
per_j["SSRX-"] += per["SSRX_N"]
per_j["GND"] += gnd
per_j["GND_DRAN"] += gnd
for pin in per_j.get_pins("SH"):
    pin += gnd

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

# ESD: TPD4E05U06 (flow-through, 0.5 mm pitch) on every SuperSpeed pair and
# on the three switched USB 2.0 pairs; USBLC6 on the aux USB-C and DDC lines.
_usblc6 = Part("Power_Protection", "USBLC6-2SC6", dest=TEMPLATE,
               footprint="Package_TO_SOT_SMD:SOT-23-6")


_usblc6_refs = iter(f"U{i}" for i in range(14, 17))


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


_tpd_refs = iter(f"U{i}" for i in range(17, 20))


def tpd4e(nets, ch1, ch2):
    """TPD4E05U06 in flow-through: the pair runs straight under the part, so
    each NC pin (6/7/9/10) carries the net of the pin opposite it
    (5/4/2/1).  Channels are interchangeable; they are assigned to match the
    pin order of the neighbouring connector so no pair has to cross."""
    u = _tpd(ref=next(_tpd_refs))
    u.fields["LCSC"] = "C138714"
    for pin in u.pins:
        pin.func = Pin.types.PASSIVE
    for (pp, pn, pp2, pn2), pair in (((1, 2, 10, 9), ch1), ((4, 5, 7, 6), ch2)):
        u[pp] += nets[pair + "_P"]
        u[pp2] += nets[pair + "_P"]
        u[pn] += nets[pair + "_N"]
        u[pn2] += nets[pair + "_N"]
    for pin in u.get_pins("GND"):
        pin += gnd
    return u


def usb2_esd(ref, dp, dn, channel=1):
    """TPD4E05U06 on a USB 2.0 pair, flow-through on one channel (1: D+ on
    pins 1/10, D- on 2/9; 2: D+ on 4/7, D- on 5/6); the other is unused.
    The channel is chosen so the unused pads face away from neighbours."""
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
usb2_esd("U13", per["DP"], per["DN"])

# PC side (Type-B): connector order is SSRX, SSTX; peripheral (Type-A): SSTX, SSRX
tpd4e(pca, "SSRX", "SSTX")
tpd4e(pcb, "SSRX", "SSTX")
tpd4e(per, "SSTX", "SSRX")

# ------------------------------------------------------------ USB 3 data muxes
# SuperSpeed: HD3SS3212 (A = common/peripheral, B = USB A, C = USB B).
# No AC-coupling caps on this board: the PC and the device already AC-couple
# their own transmitters, and the HD3SS3212 needs DC bias from one side
# (datasheet SLASE74F section 10.1) — adding caps here would float the switch.
ss = part("lcsc", "HD3SS3212IRKSR",
          footprint="lcsc:DHVQFN-20_L4.5-W2.5-P0.50-BL-EP", lcsc="C544517", ref="U2")
# channel 0: host TX -> device RX
ss["A0p"] += per["SSTX_P"]
ss["A0n"] += per["SSTX_N"]
ss["B0P"] += pca["SSRX_P"]
ss["B0N"] += pca["SSRX_N"]
ss["C0P"] += pcb["SSRX_P"]
ss["C0N"] += pcb["SSRX_N"]
# channel 1: device TX -> host RX
ss["A1p"] += per["SSRX_P"]
ss["A1n"] += per["SSRX_N"]
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
C("100nF", v3, gnd)
C("1uF", v3, gnd)

# USB 2.0 D+/D-: TS3USB221A.  Each pair sits on adjacent pins (port 1, port 2
# and common), so the pairs stay coupled up to the pins (route_usb2.py).
# S = L selects port 1 = USB A, like the HD3SS3212 and TPS2116 on USB_SEL.
hs = part("lcsc", "TS3USB221ARSER", footprint="lcsc:UQFN-10_L2.0-W1.5-P0.50-BL",
          lcsc="C128396", ref="U3")
hs["D+"] += per["DP"]
hs["D-"] += per["DN"]
hs["1D+"] += pca["DP"]
hs["1D-"] += pca["DN"]
hs["2D+"] += pcb["DP"]
hs["2D-"] += pcb["DN"]
hs["S"] += usb_sel
hs["~{OE}"] += usb_oe_n
hs["VCC"] += v3
hs["GND"] += gnd
C("100nF", v3, gnd)

R("10k", usb_sel, gnd)      # default USB A
R("10k", usb_oe_n, v3)      # muxes disabled until firmware enables them

# ------------------------------------------------------ peripheral VBUS mux
# Source select: TPS2116 in manual mode (MODE tied high), PR1 on USB_SEL, so
# peripheral power always comes from the PC whose data is selected:
# PR1 high (USB B) -> VIN1, PR1 low (USB A) -> VIN2.  It only ever switches
# while the TPS2553 below has the output off.
pm = part("Power_Management", "TPS2116DRL", lcsc="C3235557", ref="U4")
pm["VIN1"] += vbus_b
pm["VIN2"] += vbus_a
pm["PR1"] += usb_sel
pm["MODE"] += v3
for pin in pm.get_pins("VOUT"):
    pin += vbus_per_raw
pm["GND"] += gnd
pm["ST"] += NC
C("1uF", vbus_a, gnd)
C("1uF", vbus_b, gnd)

# On/off + port protection: TPS2553 current-limited switch (active-high EN).
# R_ILIM = 20k -> 1.20..1.38 A limit (datasheet), above USB 3's 900 mA.
ps = part("lcsc", "TPS2553DBVR", footprint="lcsc:SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BR",
          lcsc="C55266", ref="U20")
ilim = Net("PERIPH_ILIM")
ps["IN"] += vbus_per_raw
ps["OUT"] += vbus_per
ps["EN"] += periph_en
ps["/FAULT"] += periph_fault_n
ps["ILIM"] += ilim
ps["GND"] += gnd
R("20k", ilim, gnd)
R("10k", periph_en, gnd)          # off at reset
R("10k", periph_fault_n, v3)      # open-drain fault flag
C("100nF", vbus_per_raw, gnd)
C("22uF", vbus_per, gnd)
C("22uF", vbus_per, gnd)
C("100nF", vbus_per, gnd)

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
C("1uF", vbus_aux, gnd)
C("10uF", v5, gnd)

ldo = part("Regulator_Linear", "AP2112K-3.3", lcsc="C51118", ref="U5")
ldo["VIN"] += v5
ldo["EN"] += v5
ldo["GND"] += gnd
ldo["VOUT"] += v3
ldo["NC"] += NC
C("1uF", v5, gnd)
C("10uF", v3, gnd)

# PC VBUS sense dividers, 10k/15k = 0.6: even an out-of-spec 5.5 V port
# gives 3.3 V (ESP32 inputs: max VDD + 0.3 V), and the lowest legal VBUS
# (4.4 V) still reads high (2.64 V > 0.75 * VDD).
sense = {}
for name, vb in (("A", vbus_a), ("B", vbus_b)):
    s = Net(f"VBUS_{name}_SENSE")
    R("10k", vb, s)
    R("15k", s, gnd)
    sense[name] = s

# -------------------------------------------------------------- HDMI ports
def hdmi_port(n, ref):
    """DDC/CI-only HDMI Type-A receptacle: SCL/SDA/+5V, no TMDS, HPD unused."""
    j = part("lcsc", "HDMI-001", footprint="lcsc:HDMI-SMD_19P-P0.50-H-F",
             lcsc="C138388", ref=ref)
    p5 = Net(f"HDMI{n}_5V")
    p5_d = Net(f"HDMI{n}_5V_D")
    scl5, sda5 = Net(f"HDMI{n}_SCL"), Net(f"HDMI{n}_SDA")
    scl3, sda3 = Net(f"DDC{n}_SCL"), Net(f"DDC{n}_SDA")

    # +5V to the monitor (HDMI wants 4.8-5.3 V on pin 18): LM66100 ideal
    # diode for anti-backfeed (~5 mV drop, vs ~0.3 V for a Schottky; CE tied
    # to VOUT enables its reverse blocking) + 100 mA PTC
    d = part("Power_Management", "LM66100DCK", lcsc="C2869734", ref=f"U{20 + n}")
    d["VIN"] += v5
    d["VOUT"] += p5_d
    d["~{CE}"] += p5_d
    d["GND"] += gnd
    d["ST"] += NC
    d["NC"] += NC
    f = part("Device", "Polyfuse", footprint="Fuse:Fuse_0805_2012Metric",
             lcsc="C20975", value="100mA", ref=f"F{n + 1}")
    f[1] += p5_d
    f[2] += p5
    C("100nF", p5, gnd)

    j["+5VPower"] += p5
    j["SCL"] += scl5
    j["SDA"] += sda5
    # HPD not used: DDC/CI needs only SDA/SCL and +5V.  (Reading it would
    # put a monitor-driven 2.4-5.3 V signal on an ESP32 pin, even while
    # picoKVM is unpowered.)  Firmware can find a monitor by probing I2C 0x50.
    j["HotPlugDetect"] += NC
    j["DDC/CECGround"] += gnd
    for pin in j.pins:
        if pin.name.startswith("TMDS") or pin.name in ("CEC", "Reserved(N.C.)"):
            pin += NC
        elif pin.num in ("20", "21", "22", "23"):   # shell
            pin += gnd

    # level shifter 3.3 V (MCU) <-> 5 V (DDC)
    ls = part("Interface", "PCA9306DC",
              footprint="Package_SO:VSSOP-8_2.3x2mm_P0.5mm", lcsc="C33196",
              ref=f"U{8 + n}")
    vref2 = Net(f"DDC{n}_VREF2")
    vref2.drive = 100  # biased through 200k from the HDMI 5V, per datasheet
    ls["VREF1"] += v3
    ls["SCL1"] += scl3
    ls["SDA1"] += sda3
    ls["SCL2"] += scl5
    ls["SDA2"] += sda5
    ls["VREF2"] += vref2
    ls["EN"] += vref2
    ls["GND"] += gnd
    R("200k", vref2, p5)
    C("100nF", v3, gnd)
    R("4.7k", scl3, v3)
    R("4.7k", sda3, v3)
    R("2k", scl5, p5)              # HDMI source pull-ups (1.5k–2k spec)
    R("2k", sda5, p5)
    usblc6(scl5, sda5, p5)
    return scl3, sda3


ddc1_scl, ddc1_sda = hdmi_port(1, "J5")
ddc2_scl, ddc2_sda = hdmi_port(2, "J6")

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
btn = Net("BTN_SWITCH")
button(btn, "SWITCH").ref = "SW3"
R("10k", btn, v3)

mcu["IO1"] += ddc1_sda
mcu["IO2"] += ddc1_scl
mcu["IO4"] += ddc2_sda
mcu["IO5"] += ddc2_scl
mcu["IO8"] += usb_sel
mcu["IO9"] += usb_oe_n
mcu["IO10"] += periph_en
mcu["IO16"] += periph_fault_n
mcu["IO11"] += sense["A"]
mcu["IO12"] += sense["B"]
mcu["IO13"] += btn
mcu["USB_D-"] += aux_dn
mcu["USB_D+"] += aux_dp

# USB A / USB B LEDs: side-emitting, at the front edge, shining through a hole
# in the case wall.  Green = USB A, blue = USB B.  220R: a few mA from 3.3 V
# (blue Vf ~2.7 V at low current) -- plenty for an indicator.
# Status LED: one side-emitting SK6812 (WS2812-compatible RGB) on the front
# edge; firmware sets its colour per selected PC.  VDD is +5V_SYS through a
# diode (~4.3 V) so the 3.3 V data line clears VIH = 0.65 * VDD with margin.
# DOUT stays open (no chain).  GPIO15 is now spare.
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

# UART debug header
txd, rxd = Net("TXD0"), Net("RXD0")
mcu["TXD0"] += txd
mcu["RXD0"] += rxd
hdr = part("Connector_Generic", "Conn_01x04",
           footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
           value="UART", ref="J7", lcsc="C32713270")   # 1x4 2.54 mm male, gold
hdr[1] += gnd
hdr[2] += txd
hdr[3] += rxd
hdr[4] += v3

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
# Seen from outside the board's left edge, pad 1 is on the left (rear).
grove[1] += gnd         # black
grove[2] += grove_5v    # red
grove[3] += grove_led   # M5 yellow, next to 5 V
grove[4] += grove_btn   # M5 white, outer
for pin in grove.pins:          # mounting tabs
    if pin.num not in ("1", "2", "3", "4"):
        pin += gnd

# Local decoupling for the ideal diodes U6 / U7 (LM66100 datasheet 10.2 /
# 11.1: 1 uF input capacitor and output capacitance close to the device).
# U8 (AUX) already has C10 / C11 beside it.  Fixed refs, placed in make_pcb.
def C_ref(value, ref, a, b):
    c = C(value, a, b)
    c.ref = ref
    return c


C_ref("1uF", "C23", vbus_a, gnd)      # U6 VIN
C_ref("1uF", "C24", vbus_b, gnd)      # U7 VIN
C_ref("10uF", "C25", v5, gnd)         # U6 / U7 VOUT (+5V_SYS)

# Spare GPIO header, 2x8 2.54 mm.  IO35-37 are only free because the
# N8R2's PSRAM is quad SPI -- octal-PSRAM modules (R8, R8V, R16V) use them
# internally, so don't substitute one of those.
GPIO_HEADER = [  # (pin, net): even pins = row nearest the module, in the
    # same order as module pins 28..35; odd pins = far row
    (2, "IO35"), (4, "IO36"), (6, "IO37"), (8, "IO38"),
    (10, "IO39"), (12, "IO40"), (14, "IO41"), (16, "IO42"),
    (1, "IO48"), (3, "IO47"), (5, "IO21"), (7, "IO18"),
    (9, "GND"), (11, "+3V3"), (13, "+5V_SYS"), (15, "GND"),
]
gpio_hdr = part("Connector_Generic", "Conn_02x08_Odd_Even",
                footprint="Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical",
                value="GPIO", ref="J9", lcsc="C68234")   # 2x8 2.54 mm male, gold
for num, name in GPIO_HEADER:
    if name in ("+3V3", "+5V_SYS", "GND"):
        gpio_hdr[num] += {"+3V3": v3, "+5V_SYS": v5, "GND": gnd}[name]
    else:
        n = Net(f"GPIO{name[2:]}")
        mcu[name] += n
        gpio_hdr[num] += n

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
        })
    with open(os.path.join(OUT, "kvm_board.json"), "w") as f:
        json.dump(parts, f, indent=1)
    print(f"{len(parts)} parts written")
