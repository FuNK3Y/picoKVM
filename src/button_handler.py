import machine
import asyncio
import sys


class ButtonHandler:
    def __init__(self, pin, callback, debounce=0.04):
        self.pin = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_UP)
        self.debounce = debounce
        self.callback = callback
        self._pressed = False

    async def poll(self):
        while True:
            if self.pin.value() == 0:
                self._pressed = True
            elif self._pressed:
                await asyncio.sleep(self.debounce)
                if self.pin.value() == 0:  # A bounce while held, not a release
                    continue
                self._pressed = False
                try:
                    await self.callback()
                except Exception as e:
                    print("Uncaught exception in callback:", e)
                    sys.print_exception(e)
            await asyncio.sleep(self.debounce)
