import aiohttp
import ssl
from device import Device


class GenericDevice(Device):
    def __init__(self, uri, method, kwargs={"A": {}, "B": {}}):
        super().__init__()
        self.uri = uri
        self.kwargs = kwargs
        self.method = method
        self._clientSession = aiohttp.ClientSession()
        self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    async def set_active_input(self, input):
        async with self._clientSession.request(self.method, self.uri, ssl=self._ssl_context, **self.kwargs[input]) as response:
            return await response.text()
