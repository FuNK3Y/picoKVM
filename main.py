import network
import asyncio
import gc
from config import Config
from webserver import WebServer
from controller import Controller
from button_handler import ButtonHandler
from metrics_provider import MetricsProvider

gc.threshold((gc.mem_free() + gc.mem_alloc()) // 3)

Config.load()
controller = Controller()


async def connect():
    wlan = network.WLAN(network.STA_IF)
    network.hostname(Config.wireless_network["hostname"])
    wlan.active(True)
    wlan.config(pm=network.WLAN.PM_NONE)
    wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])


asyncio.create_task(connect())
asyncio.create_task(asyncio.start_server(WebServer(controller, MetricsProvider()).handle_client, "0.0.0.0", 80))
asyncio.create_task(ButtonHandler(Config.button_gpio_pin, controller.set_active_input).poll())

asyncio.get_event_loop().run_forever()
