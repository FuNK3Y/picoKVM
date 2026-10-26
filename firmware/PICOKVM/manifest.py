# The modules of MicroPython's generic ESP32 firmware (asyncio, networking, neopixel, ...)
include("$(PORT_DIR)/boards/manifest.py")

require("aiohttp")

# The application, and the modules generate.py derives from it (the web page: frozen code cannot open files)
freeze("../../src")
freeze("../generated")
