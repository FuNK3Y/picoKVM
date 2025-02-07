import aiohttp
from device import Device


class GenericDevice(Device):
    def __init__(self, uri, method, kwargs={"A": {}, "B": {}}):
        super().__init__()
        self.uri = uri
        self.kwargs = kwargs
        self.method = method

    async def set_input(self, input):
        async with aiohttp.ClientSession() as session:
            async with session.request(self.method, self.uri, **self.kwargs[input]) as response:
                return await response.text()
