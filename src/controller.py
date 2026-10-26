import asyncio
import gc
import board
import neopixel
from machine import Pin
from config import Config


class Controller:
    lock = asyncio.Lock()  # Held while switching, and while writing an update
    _switch_timeout = 45  # A monitor in standby has to bring its websocket service up before KEY_RETURN can even be sent
    _switch_attempts = 2
    _peripheral_off_time = 0.2  # Long enough for the peripheral to see a disconnect and re-enumerate on the new computer

    def __init__(self):
        self._usb_select = Pin(board.USB_SELECT, Pin.OUT)
        Pin(board.USB_ENABLE, Pin.OUT, value=0)  # The data switches are off until enabled
        self._peripheral_power = Pin(board.PERIPHERAL_POWER, Pin.OUT, value=1)  # The peripheral port is unpowered at reset
        self._leds = [neopixel.NeoPixel(Pin(pin, Pin.OUT), 1) for pin in board.LEDS]
        self._show_idle()

    @property
    def selected_input(self):
        return "A" if self._usb_select.value() == 0 else "B"

    def _set_leds(self, rgb):
        for led in self._leds:
            led[0] = rgb
            led.write()

    def _rgb(self, input, brightness=1.0):
        color = Config.inputs[input]["color"].lstrip("#")
        return [int(int(color[i : i + 2], 16) * brightness) for i in (0, 2, 4)]

    def _show_idle(self):
        self._set_leds(self._rgb(self.selected_input, Config.led_idle_brightness))

    async def _select_usb(self, input):
        level = 0 if input == "A" else 1
        if self._usb_select.value() == level:
            return
        self._peripheral_power.value(0)  # Power and data move together, so the peripheral never sees a half-switched port
        self._usb_select.value(level)
        await asyncio.sleep(self._peripheral_off_time)
        self._peripheral_power.value(1)

    async def set_active_input(self, input=None):
        async def blink_led(rgb):
            try:
                while True:
                    self._set_leds(rgb)
                    await asyncio.sleep(0.1)
                    self._set_leds((0, 0, 0))
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                self._set_leds((0, 0, 0))
                raise

        async with self.lock:
            if not input:
                input = "A" if self.selected_input == "B" else "B"
            blink_led_task = asyncio.create_task(blink_led(self._rgb(input)))
            try:
                for attempt in range(self._switch_attempts):
                    gc.collect()  # A failed wrap_socket strands a connected socket; only its finaliser returns it to the ESP-IDF heap
                    tasks = []
                    try:
                        tasks = [asyncio.create_task(device.set_active_input(input)) for device in Config.devices]
                        await asyncio.wait_for(asyncio.gather(*tasks), timeout=self._switch_timeout)
                        break
                    except Exception as e:
                        if attempt + 1 == self._switch_attempts:
                            raise
                        print("Switch attempt", attempt + 1, "failed, retrying:", e)
                    finally:
                        for task in tasks:  # wait_for abandons them on timeout, and an abandoned task never closes its TLS session
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                Config.save()  # In order to persist tokens
                await self._select_usb(input)
            finally:
                blink_led_task.cancel()
                await asyncio.gather(blink_led_task, return_exceptions=True)
                self._show_idle()
