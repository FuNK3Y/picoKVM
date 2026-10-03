"""
Human-reviewable "schematic": out/schematic_review.html, generated from the
same netlist dump as the PCB (out/kvm_board.json), grouped by function.

For every chip and connector: each pin's name, its net, and everything else
on that net.  Passives are listed with the two nets they join.  Ends with a
net index and automatic checks.  Regenerated on every build, so it always
matches the board.
"""

import html
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "out"))

POWER = {"GND", "+3V3", "+5V_SYS"}

BLOCKS = [
    ("USB data path (USB 3.0 + USB 2.0 switching)",
     "USB A / USB B Type-B in, peripheral Type-A out.  U2 switches the SuperSpeed "
     "pairs, U3 the USB 2.0 pair; both follow USB_SEL.  ESD at every connector.",
     ["J1", "J2", "J3", "U17", "U18", "U19", "U2", "U3", "U11", "U12", "U13"]),
    ("Peripheral power",
     "U4 picks the source (follows USB_SEL via PR1, MODE tied high); U20 switches "
     "the port on/off (PERIPH_EN), limits it to 1.2-1.38 A and flags faults.",
     ["U4", "U20"]),
    ("System power",
     "Ideal-diode OR of USB A / USB B / AUX VBUS into +5V_SYS, then the 3.3 V LDO.  "
     "J4 is the aux / flashing USB-C.",
     ["U6", "U7", "U8", "U5", "J4", "U14"]),
    ("HDMI 1 - DDC/CI", "Only DDC and +5V are wired (HPD unused); no video.",
     ["J5", "U9", "U15", "U21", "F2"]),
    ("HDMI 2 - DDC/CI", "Only DDC and +5V are wired (HPD unused); no video.",
     ["J6", "U10", "U16", "U22", "F3"]),
    ("Grove button port (M5Stack pinout)",
     "Yellow = LED data (SK6812), white = key, red = 5 V via 100 mA PTC.",
     ["J8", "F4"]),
    ("ESP32-S3 controller, buttons, LEDs, headers", "",
     ["U1", "SW1", "SW2", "SW3", "D3", "D4", "J7", "J9"]),
]


def main():
    parts = json.load(open(os.path.join(OUT, "kvm_board.json")))
    by_ref = {p["ref"]: p for p in parts}
    members = defaultdict(list)                      # net -> [(ref, pin, name)]
    for p in parts:
        for num, net in p["pads"].items():
            members[net].append((p["ref"], num, p.get("pin_names", {}).get(num, "")))

    def is_passive(p):
        return p["ref"][0] in "RCF" and len(p["pads"]) == 2 and p["ref"] not in sum(
            (b[2] for b in BLOCKS), [])

    # passives go to the block of the first non-power part they touch
    block_of = {ref: i for i, b in enumerate(BLOCKS) for ref in b[2]}
    passives = defaultdict(list)
    for p in parts:
        if not is_passive(p):
            continue
        home = None
        for net in sorted(p["pads"].values(), key=lambda n: n in POWER):
            for ref, _, _ in members[net]:
                if ref in block_of and ref != p["ref"]:
                    home = block_of[ref]
                    break
            if home is not None:
                break
        passives[home if home is not None else len(BLOCKS) - 1].append(p)

    def others(net, me):
        m = [f"{r}.{n}" + (f" ({nm})" if nm and nm not in ("~", n) else "")
             for r, n, nm in members[net] if r != me]
        if net in POWER or len(m) > 8:
            return f"<span class=dim>{len(m)} connections</span>"
        return html.escape(", ".join(m)) if m else "<b class=bad>nothing else</b>"

    h = []
    w = h.append
    erc = ""
    erc_path = os.path.join(OUT, "kvm_board.erc")
    if os.path.exists(erc_path):
        erc = open(erc_path).read().strip()
    w(f"<h1>picoKVM rev A — schematic review</h1>")
    w(f"<p class=dim>Generated from <code>hw/kvm_board.py</code> via "
      f"<code>out/kvm_board.json</code> — {len(parts)} parts, {len(members)} nets.  "
      f"ERC: {html.escape(erc) or 'see out/kvm_board.erc'}</p>")

    w("<nav><b>Blocks:</b> " + " · ".join(
        f"<a href='#b{i}'>{html.escape(b[0])}</a>" for i, b in enumerate(BLOCKS))
      + " · <a href='#nets'>Net index</a> · <a href='#checks'>Checks</a></nav>")

    for i, (title, note, refs) in enumerate(BLOCKS):
        w(f"<h2 id=b{i}>{html.escape(title)}</h2>")
        if note:
            w(f"<p>{html.escape(note)}</p>")
        for ref in refs:
            p = by_ref.get(ref)
            if not p:
                continue
            lcsc = p["lcsc"] or "not assembled"
            w(f"<h3>{ref} — {html.escape(p['value'])} <span class=dim>"
              f"({html.escape(p['symbol'])}, {lcsc})</span></h3>")
            w("<table><tr><th>pin</th><th>name</th><th>net</th><th>also on this net</th></tr>")
            names = p.get("pin_names", {})
            for num in sorted(names, key=lambda n: (len(n), n)):
                net = p["pads"].get(num)
                cls = " class=nc" if net is None else ""
                w(f"<tr{cls}><td>{num}</td><td>{html.escape(names[num])}</td>"
                  f"<td>{html.escape(net) if net else '<i>not connected</i>'}</td>"
                  f"<td>{others(net, ref) if net else ''}</td></tr>")
            w("</table>")
        if passives[i]:
            w("<h3>Passives</h3><table><tr><th>ref</th><th>value</th><th>joins</th><th>LCSC</th></tr>")
            for p in sorted(passives[i], key=lambda p: (p["ref"][0], int(p["ref"][1:]))):
                nets = " — ".join(html.escape(n) for n in p["pads"].values())
                w(f"<tr><td>{p['ref']}</td><td>{html.escape(p['value'])}</td>"
                  f"<td>{nets}</td><td>{p['lcsc']}</td></tr>")
            w("</table>")

    w("<h2 id=nets>Net index</h2><table><tr><th>net</th><th>#</th><th>members</th></tr>")
    for net in sorted(members, key=lambda n: (n not in POWER, n)):
        m = members[net]
        txt = (f"<span class=dim>{len(m)} pins</span>" if net in POWER else
               html.escape(", ".join(f"{r}.{n}" for r, n, _ in m)))
        w(f"<tr><td>{html.escape(net)}</td><td>{len(m)}</td><td>{txt}</td></tr>")
    w("</table>")

    w("<h2 id=checks>Automatic checks</h2><ul>")
    single = [n for n, m in members.items() if len(m) < 2]
    w(f"<li>{'<b class=bad>' if single else '<b class=ok>'}Nets with a single pin: "
      f"{', '.join(single) if single else 'none'}</b></li>")
    unplaced = [r for r in by_ref if r not in block_of and not is_passive(by_ref[r])
                and not r.startswith("H")]
    w(f"<li>Parts outside every block: {', '.join(unplaced) or 'none'}</li>")
    dnp = [p["ref"] for p in parts if not p["lcsc"] and not p["ref"].startswith("H")]
    w(f"<li>Not assembled by JLC (no LCSC number): {', '.join(dnp)}</li>")
    for net in sorted(POWER):
        w(f"<li>{net}: {len(members[net])} pins</li>")
    w("</ul>")

    css = """
:root{--bg:#fff;--fg:#1d1d1f;--dim:#6e6e73;--line:#d2d2d7;--head:#f5f5f7;--bad:#c62828;--ok:#2e7d32;--nc:#9e9e9e}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#e8e8ea;--dim:#9a9aa0;--line:#3a3a3e;--head:#1f1f23;--bad:#ef5350;--ok:#66bb6a;--nc:#757575}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:22px}h2{margin-top:36px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:15px;margin:18px 0 6px}
table{border-collapse:collapse;width:100%;margin-bottom:8px}th,td{border:1px solid var(--line);padding:3px 6px;text-align:left;vertical-align:top}
th{background:var(--head)}td:first-child{white-space:nowrap}.dim{color:var(--dim)}.bad{color:var(--bad)}.ok{color:var(--ok)}
tr.nc td{color:var(--nc)}nav{position:sticky;top:0;background:var(--bg);padding:6px 0;border-bottom:1px solid var(--line)}
a{color:inherit}code{font-size:13px}"""
    page = (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>picoKVM schematic review</title><style>{css}</style></head><body>"
            + "\n".join(h) + "</body></html>")
    path = os.path.join(OUT, "schematic_review.html")
    open(path, "w").write(page)
    print(f"wrote {path}: {len(single)} single-pin nets")


if __name__ == "__main__":
    main()
