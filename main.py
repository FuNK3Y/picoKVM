import network
import time
import asyncio
from machine import Pin
from config import Config
from webserver import WebServer
from controller import Controller

Config.load()
controller = Controller()

wlan = network.WLAN(network.STA_IF)
network.hostname(Config.wireless_network["hostname"])
wlan.active(True)
wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])

while not wlan.isconnected():
    print("Connecting to WLAN...")
    time.sleep(2)

print("Connected, IP address: ", wlan.ifconfig()[0])

Pin(Config.button_gpio_pin, Pin.OUT).on()  # To avoid the initial trigger on machine.reset()
Pin(Config.button_gpio_pin, Pin.IN).irq(trigger=Pin.IRQ_RISING, handler=lambda pin: asyncio.run(controller.set_active_input()))

server = asyncio.start_server(WebServer(controller).handle_client, "0.0.0.0", 80)
asyncio.create_task(server)

try:
    asyncio.get_event_loop().run_forever()
except KeyboardInterrupt:
    print("Program Interrupted by the user")
