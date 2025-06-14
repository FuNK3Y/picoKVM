import asyncio
import gc
import neopixel
from machine import Pin
from config import Config


class Controller:
    _lock = asyncio.Lock()

    @property
    def selected_input(self):
        return "A" if Pin(Config.usb_gpio_pin, Pin.OUT).value() == 0 else "B"

    async def set_active_input(self, input=None):
        async def blink_led(color):
            led = neopixel.NeoPixel(Pin(Config.led_gpio_pin, Pin.OUT), 1)
            rgb = [int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
            try:
                while True:
                    led[0] = rgb
                    led.write()
                    await asyncio.sleep(0.1)
                    led[0] = (0, 0, 0)
                    led.write()
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                led[0] = (0, 0, 0)
                led.write()
                raise

        async with self._lock:
            if not input:
                input = "A" if self.selected_input == "B" else "B"
            blink_led_task = asyncio.create_task(blink_led(Config.inputs[input]["color"]))
            try:
                tasks = [asyncio.create_task(device.set_active_input(input)) for device in Config.devices]
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=20)
                Config.save()  # In order to persist tokens
                Pin(Config.usb_gpio_pin, Pin.OUT).value(0 if input == "A" else 1)
            except Exception:
                raise
            finally:
                blink_led_task.cancel()
                await asyncio.gather(blink_led_task, return_exceptions=True)
