import network
import time
import asyncio
from config import Config
from webserver import WebServer

Config.load()

wlan = network.WLAN(network.STA_IF)
network.hostname(Config.wireless_network["hostname"])
wlan.active(True)
wlan.connect(Config.wireless_network["SSID"], Config.wireless_network["password"])

while not wlan.isconnected():
    print("Connecting to WLAN...")
    time.sleep(2)

print("Connected, IP address: ", wlan.ifconfig()[0])


async def handle_client(reader, writer):
    try:
        request = (await reader.read(1024)).decode("utf-8")
        method, path, _ = request.split(" ", 2)
        ws = WebServer()
        if path.startswith("/api/"):
            await ws.api(writer, method, path)
        else:
            await ws.single_page(writer)
        await writer.drain()
        await writer.wait_closed()
    except Exception as e:
        print("Error with client handing: ", e)


server = asyncio.start_server(handle_client, "0.0.0.0", 80)
asyncio.create_task(server)
loop = asyncio.get_event_loop()

try:
    loop.run_forever()
except KeyboardInterrupt:
    print("Program Interrupted by the user")
