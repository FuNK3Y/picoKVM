# The modules of MicroPython's generic ESP32 firmware (asyncio, networking, neopixel, ...)
include("$(PORT_DIR)/boards/manifest.py")

require("aiohttp")

# The application
freeze("../../src")
