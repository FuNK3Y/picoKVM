import asyncio
from machine import Pin, SoftI2C
from device import Device


class DdcMonitor(Device):
    """Monitor switched over DDC/CI (VESA MCCS), through one of the picoKVM board's HDMI ports.

    `inputs` maps "A"/"B" to the MCCS value of VCP 0x60 (input source), e.g. 0x0F/15 = DisplayPort 1,
    0x10/16 = DisplayPort 2, 0x11/17 = HDMI 1, 0x12/18 = HDMI 2. Some monitors use their own values:
    read VCP 0x60 with a DDC tool (e.g. `ddcutil getvcp 60` on Linux) while each input is active.
    """

    _ADDRESS = 0x37  # DDC/CI slave address (0x6E for writes)
    _SOURCE = 0x51  # Host address, as seen by the monitor
    _VCP_INPUT_SOURCE = 0x60
    _VCP_POWER_MODE = 0xD6

    def __init__(self, sda_gpio_pin, scl_gpio_pin, inputs, power_on=False, power_on_delay=2.0, freq=50000):
        super().__init__()
        self.sda_gpio_pin = sda_gpio_pin
        self.scl_gpio_pin = scl_gpio_pin
        self.inputs = inputs
        self.power_on = power_on
        self.power_on_delay = power_on_delay
        self.freq = freq
        self._i2c = SoftI2C(sda=Pin(sda_gpio_pin), scl=Pin(scl_gpio_pin), freq=freq)

    def _set_vcp(self, code, value):
        message = bytes([self._SOURCE, 0x84, 0x03, code, (value >> 8) & 0xFF, value & 0xFF])
        checksum = self._ADDRESS << 1
        for byte in message:
            checksum ^= byte
        try:
            self._i2c.writeto(self._ADDRESS, message + bytes([checksum]))
        except OSError as e:  # NACK: no monitor on this port, DDC/CI disabled in its menu, or monitor fully off
            raise OSError(f"DDC/CI write to the monitor on SDA {self.sda_gpio_pin} failed: {e}")

    async def set_active_input(self, input):
        if self.power_on:
            self._set_vcp(self._VCP_POWER_MODE, 0x01)
            await asyncio.sleep(self.power_on_delay)
        self._set_vcp(self._VCP_INPUT_SOURCE, self.inputs[input])
        await asyncio.sleep(0.05)  # DDC/CI asks for 50 ms between messages
