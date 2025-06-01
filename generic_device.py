import aiohttp
from device import Device


class GenericDevice(Device):

    def __init__(self, uri, method, kwargs={"A": {}, "B": {}}):
        super().__init__()
        self.uri = uri
        self.kwargs = kwargs
        self.method = method
        self._clientSession = aiohttp.ClientSession()

    async def set_active_input(self, input):
        async with self._clientSession.request(self.method, self.uri, **self.kwargs[input]) as response:
            return await response.text()
