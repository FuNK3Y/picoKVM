import machine
import asyncio


class ButtonHandler:
    def __init__(self, pin, callback, debounce=0.05):
        self._downCounter = 0
        self.pin = machine.Pin(pin, machine.Pin.IN)
        self.debounce = debounce
        self.callback = callback
        self.reset_counter = 10 / debounce
        machine.Pin(pin, machine.Pin.OUT).on()  # To avoid the initial trigger on machine.reset()

    async def poll(self):
        while True:
            if self._downCounter >= self.reset_counter:
                print("Resetting...")
                machine.reset()
            if self._downCounter > 0 and self.pin.value() == 1:
                self._downCounter = 0
                try:
                    await self.callback()
                except Exception as e:
                    print("Uncaught exception in callback:", e)
            elif self.pin.value() == 0:
                self._downCounter += 1
            await asyncio.sleep(self.debounce)
