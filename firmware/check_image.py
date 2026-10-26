"""Checks that the updater (src/updater.py) accepts an application image, and prints the version it reads from it.

Usage: check_image.py firmware-ota.bin
"""

import os
import sys
import types

# updater.py runs on the board: stand in for the MicroPython modules it imports
for name in ("esp32", "machine"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["esp32"].Partition = None
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from updater import Updater

with open(sys.argv[1], "rb") as file:
    print("Image version:", Updater.image_version(bytearray(file.read(4096))))
