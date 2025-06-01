import network
import time
import asyncio
from config import Config
from webserver import WebServer
from controller import Controller
from button_handler import ButtonHandler

Config.load()
controller = Controller()

wlan = network.WLAN(network.STA_IF)
network.hostname(Config.wireless_network["hostname"])
wlan.active(True)
wlan.config(pm=0xA11140)  # Disable power saving - seems to cause issue when idle for a long time
wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])

while not wlan.isconnected():
    print("Connecting to WLAN...")
    time.sleep(2)

print("Connected, IP address:", wlan.ifconfig()[0])

asyncio.create_task(asyncio.start_server(WebServer(controller).handle_client, "0.0.0.0", 80))
if Config.button_gpio_pin > 0:
    asyncio.create_task(ButtonHandler(Config.button_gpio_pin, controller.set_active_input).poll())

asyncio.get_event_loop().run_forever()
