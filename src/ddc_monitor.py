import asyncio
import board
from machine import Pin, SoftI2C
from device import Device


class DdcMonitor(Device):
    """Monitor switched over DDC/CI (VESA MCCS), through one of the picoKVM board's HDMI ports.

    `inputs` maps "A"/"B" to the MCCS value of VCP 0x60 (input source), e.g. 0x0F/15 = DisplayPort 1,
    0x10/16 = DisplayPort 2, 0x11/17 = HDMI 1, 0x12/18 = HDMI 2. Some monitors use their own values:
    read VCP 0x60 with a DDC tool (e.g. `ddcutil getvcp 60` on Linux) while each input is active.
    """

    _ADDRESS = 0x37  # DDC/CI slave address (0x6E for writes)
    _EDID_ADDRESS = 0x50
    _SOURCE = 0x51  # Host address, as seen by the monitor
    _REPLY_SOURCE = 0x50  # Stands for the host in the checksum of the monitor's replies
    _VCP_INPUT_SOURCE = 0x60
    _VCP_POWER_MODE = 0xD6

    def __init__(self, hdmi, inputs, power_on=False, power_on_delay=2.0, freq=50000):
        super().__init__()
        self.hdmi = hdmi
        self.inputs = inputs
        self.power_on = power_on
        self.power_on_delay = power_on_delay
        self.freq = freq
        if hdmi not in board.HDMI_DDC:
            raise ValueError(f"no HDMI port {hdmi}")
        if sorted(inputs) != ["A", "B"] or not all(isinstance(value, int) for value in inputs.values()):
            raise ValueError("inputs: an MCCS value for A and for B")
        sda, scl = board.HDMI_DDC[hdmi]
        self._i2c = SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=freq)

    @staticmethod
    def _checksum(start, data):
        for byte in data:
            start ^= byte
        return start

    def _write(self, message):
        try:
            self._i2c.writeto(self._ADDRESS, message + bytes([self._checksum(self._ADDRESS << 1, message)]))
        except OSError as e:  # NACK: no monitor on this port, DDC/CI disabled in its menu, or monitor fully off
            raise OSError(f"DDC/CI write to the monitor on HDMI {self.hdmi} failed: {e}")

    def _set_vcp(self, code, value):
        self._write(bytes([self._SOURCE, 0x84, 0x03, code, (value >> 8) & 0xFF, value & 0xFF]))

    async def get_vcp(self, code):
        """The current value of VCP code, read from the monitor. Raises OSError when it does not tell."""
        self._write(bytes([self._SOURCE, 0x82, 0x01, code]))
        await asyncio.sleep(0.04)  # DDC/CI gives the monitor 40 ms to prepare its reply
        try:
            reply = self._i2c.readfrom(self._ADDRESS, 11)
        except OSError as e:
            raise OSError(f"DDC/CI read from the monitor on HDMI {self.hdmi} failed: {e}")
        # Source, length, opcode 0x02, result, code, type, maximum (2 bytes), current (2 bytes), checksum
        if reply[1] & 0x7F != 8 or reply[2] != 0x02 or reply[4] != code or self._checksum(self._REPLY_SOURCE, reply[:10]) != reply[10]:
            raise OSError(f"The monitor on HDMI {self.hdmi} gave no valid reply for VCP 0x{code:02x}")
        if reply[3] != 0x00:
            raise OSError(f"The monitor on HDMI {self.hdmi} does not support VCP 0x{code:02x}")
        return (reply[8] << 8) | reply[9]

    async def get_input(self):
        """The monitor's current input source: the value inputs gives it."""
        return await self.get_vcp(self._VCP_INPUT_SOURCE) & 0xFF  # Some monitors put garbage in the high byte

    def read_name(self):
        """The monitor's name, from its EDID (which answers even with DDC/CI disabled). Raises OSError when none answers."""
        try:
            self._i2c.writeto(self._EDID_ADDRESS, b"\x00")
            edid = self._i2c.readfrom(self._EDID_ADDRESS, 128)
        except OSError as e:
            raise OSError(f"No monitor answers on HDMI {self.hdmi}: {e}")
        if edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00" or sum(edid) & 0xFF:
            raise OSError(f"The monitor on HDMI {self.hdmi} gave an invalid EDID")
        for offset in (54, 72, 90, 108):  # The display descriptors
            if edid[offset : offset + 3] == b"\x00\x00\x00" and edid[offset + 3] == 0xFC:  # Its name
                return "".join(chr(byte) for byte in edid[offset + 5 : offset + 18] if 32 <= byte < 127).strip()  # Ends with \n, then spaces
        vendor = (edid[8] << 8) | edid[9]  # Three letters, 5 bits each
        return "".join(chr(64 + (vendor >> shift & 0x1F)) for shift in (10, 5, 0)) + " monitor"

    async def set_active_input(self, input):
        if self.power_on:
            self._set_vcp(self._VCP_POWER_MODE, 0x01)
            await asyncio.sleep(self.power_on_delay)
        self._set_vcp(self._VCP_INPUT_SOURCE, self.inputs[input])
        await asyncio.sleep(0.05)  # DDC/CI asks for 50 ms between messages
