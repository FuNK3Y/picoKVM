import network
import asyncio
from config import Config
from webserver import WebServer
from controller import Controller
from button_handler import ButtonHandler
from mdns_client import Client
from mdns_client.responder import Responder

Config.load()
controller = Controller()


async def connect():
    wlan = network.WLAN(network.STA_IF)
    network.hostname(Config.wireless_network["hostname"])
    wlan.active(True)
    wlan.config(pm=network.WLAN.PM_NONE)  # Disable power saving
    while not wlan.isconnected():
        print("Connecting to wifi...")
        wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])
        await asyncio.sleep(10)

    own_ip_address = wlan.ifconfig()[0]
    responder = Responder(
        Client(own_ip_address),
        own_ip=lambda: own_ip_address,
        host=lambda: Config.wireless_network["hostname"],
    )


asyncio.create_task(connect())
asyncio.create_task(asyncio.start_server(WebServer(controller).handle_client, "0.0.0.0", 80))
asyncio.create_task(ButtonHandler(Config.button_gpio_pin, controller.set_active_input).poll())

asyncio.get_event_loop().run_forever()
