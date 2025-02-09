import asyncio
from machine import Pin
from config import Config


class Controller:
    __lock = asyncio.Lock()

    @property
    def selected_input(self):
        return "A" if Pin(Config.usb_gpio_pin, Pin.OUT).value() == 0 else "B"

    async def set_active_input(self, input=None):
        async with self.__lock:

            async def blink_led():
                led = Pin(Config.led_gpio_pin, Pin.OUT)
                try:
                    while True:
                        led.on()
                        await asyncio.sleep(0.1)
                        led.off()
                        await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    led.off()
                    raise

            blink_led = asyncio.create_task(blink_led())
            if not input:
                input = "A" if self.selected_input == "B" else "B"
            tasks = [asyncio.create_task(device.set_active_input(input)) for device in Config.devices]
            await asyncio.gather(*tasks)
            Config.save()  # In order to persist tokens
            Pin(Config.usb_gpio_pin, Pin.OUT).value(0 if input == "A" else 1)
            blink_led.cancel()
