import network
import asyncio
from config import Config
from webserver import WebServer
from controller import Controller
from button_handler import ButtonHandler

Config.load()
controller = Controller()


async def connect():
    wlan = network.WLAN(network.STA_IF)
    network.hostname(Config.wireless_network["hostname"])
    wlan.active(True)
    wlan.config(pm=0xA11140)  # Disable power saving - seems to cause issue when idle for a long time
    while True:
        if not wlan.isconnected():
            print("Connecting to wifi...")
            wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])
        await asyncio.sleep(10)


asyncio.create_task(connect())
asyncio.create_task(asyncio.start_server(WebServer(controller).handle_client, "0.0.0.0", 80))
if Config.button_gpio_pin > 0:
    asyncio.create_task(ButtonHandler(Config.button_gpio_pin, controller.set_active_input).poll())

asyncio.get_event_loop().run_forever()
