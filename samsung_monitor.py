import ubinascii
import network
import aiohttp
import asyncio
from device import Device


class SamsungMonitor(Device):
    def __init__(self, hostname, command_sequences, command_interval=0.1, power_on_delay=1, token=None):
        super().__init__()
        self.hostname = hostname
        self.command_interval = command_interval
        self.power_on_delay = power_on_delay
        self.command_sequences = command_sequences
        self.token = token

    async def power_on(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://{self.hostname}:8002/api/v2/") as response:
                power_state = (await response.json())["device"]["PowerState"]
        if power_state != "on":
            self.send_commands(["KEY_POWER"])
            await asyncio.sleep(self.power_on_delay)

    async def send_commands(self, commands):
        encoded_name = ubinascii.b2a_base64(
            network.hostname()).decode().strip()
        channel_uri = f"wss://{self.hostname}:8002/api/v2/channels/samsung.remote.control?name={encoded_name}"
        if not self.token:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect("channel_uri") as ws:
                    self.token = await ws.receive_json()['data']['token']
        channel_uri += f"&token={self.token}"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(channel_uri) as ws:
                for command in commands:
                    message = {
                        "method": "ms.remote.control",
                        "params": {
                            "Cmd": "Click",
                            "DataOfCmd": command,
                            "Option": "false",
                            "TypeOfRemote": "SendRemoteKey"
                        }
                    }
                    await ws.send_json(message)
                    await asyncio.sleep(self.command_interval)

    async def set_input(self, input):
        await self.power_on()
        await self.send_commands(self.command_sequences[input])
