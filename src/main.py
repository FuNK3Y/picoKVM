import sys

sys.path.remove(".frozen")  # Run the firmware's modules even if stale copies are left on the filesystem
sys.path.insert(0, ".frozen")

from updater import Updater

updater = Updater()  # First: on the trial boot of an update, its watchdog covers everything below

import network
import asyncio
import gc
from config import Config
from webserver import WebServer
from controller import Controller
from button_handler import ButtonHandler
from metrics_provider import MetricsProvider
import board

gc.threshold((gc.mem_free() + gc.mem_alloc()) // 3)

Config.load()
controller = Controller()


def connect():
    wlan = network.WLAN(network.STA_IF)
    network.hostname(Config.wireless_network["hostname"])
    wlan.active(True)
    wlan.config(pm=network.WLAN.PM_NONE)
    if wlan.isconnected():  # A soft reboot (Ctrl-D, Thonny) restarts MicroPython but not the Wi-Fi driver
        return wlan
    try:
        wlan.disconnect()  # Ends an attempt still in progress: connecting during one fails with "Wifi Internal State Error"
    except OSError:
        pass
    wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])
    return wlan


async def main():
    wlan = connect()
    await asyncio.start_server(WebServer(controller, MetricsProvider(updater), updater).handle_client, "0.0.0.0", 80)
    asyncio.create_task(ButtonHandler(board.BUTTON, controller.set_active_input).poll())
    await updater.run(wlan.isconnected)  # Healthy: config loaded, web server up, and on the network


asyncio.create_task(main())
asyncio.get_event_loop().run_forever()
