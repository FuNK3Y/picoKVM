"""
Fetch JLC's own footprint for every LCSC part in the BOM (via easyeda2kicad)
into hw/lib/jlcref/, plus lcsc_footprints.json mapping each part number to
its footprint name.  make_fab.py uses them to express the CPL in JLC's
footprint frame.  Each part is imported on its own so the mapping is exact
even when several parts share a footprint (e.g. all 0402 resistors).
"""

import csv
import json
import os
import re
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "lib", "jlcref")
BOM = os.path.join(HERE, "..", "out", "jlcpcb", "bom.csv")


def main():
    os.makedirs(REF, exist_ok=True)
    codes = sorted({r["LCSC Part #"].strip() for r in csv.DictReader(open(BOM))})
    path = os.path.join(REF, "lcsc_footprints.json")
    # start from the previous mapping so a failed fetch never drops a part
    mapping = json.load(open(path)) if os.path.exists(path) else {}
    for code in codes:
        if code in mapping:             # already fetched (delete the json to refresh)
            continue
        # EasyEDA answers 403 when hit too fast: pace requests, back off
        for wait in (2, 10, 30, 60):
            time.sleep(wait)
            with tempfile.TemporaryDirectory() as tmp:
                out = subprocess.run(
                    ["easyeda2kicad", "--footprint", "--lcsc_id", code,
                     "--output", os.path.join(tmp, "x")],
                    capture_output=True, text=True, cwd=tmp)
            out = out.stdout + out.stderr   # its log goes to either, by version
            if "403" not in out:
                break
        m = re.search(r"Footprint name: *(\S+)", out)
        if not m:
            print(f"  {code}: no footprint found")
            continue
        mapping[code] = m.group(1)
        time.sleep(2)
        subprocess.run(["easyeda2kicad", "--footprint", "--overwrite", "--lcsc_id", code,
                        "--output", os.path.join(REF, "jlc")],
                       capture_output=True, cwd=REF)
    json.dump(mapping, open(path, "w"),
              indent=1, sort_keys=True)
    print(f"jlcref: {sum(c in mapping for c in codes)}/{len(codes)} parts mapped")


if __name__ == "__main__":
    main()
