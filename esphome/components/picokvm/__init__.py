"""picoKVM board: USB switch and DDC/CI monitor switching, exposed as one select (see select.py)."""

import esphome.codegen as cg

CODEOWNERS = ["@FuNK3Y"]
DEPENDENCIES = ["i2c"]

picokvm_ns = cg.esphome_ns.namespace("picokvm")
