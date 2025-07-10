import ubinascii
import network
import aiohttp
import asyncio
import ssl
from device import Device


class SamsungMonitor(Device):
    def __init__(
        self,
        hostname,
        command_sequences,
        command_delay=0.1,
        token=None,
    ):
        super().__init__()
        self.hostname = hostname
        self.command_delay = command_delay
        self.command_sequences = command_sequences
        self.token = token
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._clientSession = aiohttp.ClientSession()

    async def send_commands(self, commands):
        encoded_name = ubinascii.b2a_base64(network.hostname()).decode().strip()
        channel_uri = f"wss://{self.hostname}:8002/api/v2/channels/samsung.remote.control?name={encoded_name}"
        if not self.token:
            async with self._clientSession.ws_connect(channel_uri, self._ctx) as ws:
                self.token = (await ws.receive_json())["data"]["token"]
        channel_uri += f"&token={self.token}"
        async with self._clientSession.ws_connect(channel_uri) as ws:
            await ws.receive_json()
            for command in commands:
                if isinstance(command, dict):
                    command_delay = command.get("delay", self.command_delay)
                    repeat = command.get("repeat", 1)
                    command = command["command"]
                else:
                    command_delay = self.command_delay
                    repeat = 1
                message = {
                    "method": "ms.remote.control",
                    "params": {
                        "Cmd": "Click",
                        "DataOfCmd": command,
                        "Option": "false",
                        "TypeOfRemote": "SendRemoteKey",
                    },
                }
                for _ in range(repeat):
                    await ws.send_json(message)
                    await asyncio.sleep(command_delay)

    async def set_active_input(self, input):
        await self.send_commands(self.command_sequences[input])
