import asyncio
from machine import Pin
from config import Config


class Controller:
    @property
    def selected_input(self):
        return "A" if Pin(Config.usb_gpio_pin, Pin.OUT).value() == 0 else "B"

    async def set_input(self, input=None):
        if not input:
            input = "A" if self.selected_input == "B" else "B"
        tasks = [asyncio.create_task(device.set_input(input)) for device in Config.devices]
        await asyncio.gather(*tasks)
        Config.save()  # In order to persist tokens
        Pin(Config.usb_gpio_pin, Pin.OUT).value(0 if input == "A" else 1)
