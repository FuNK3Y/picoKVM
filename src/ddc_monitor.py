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
    _READ_ATTEMPTS = 3  # Monitors answer a read wrongly now and then
    _MAX_CAPABILITIES = 1024  # bytes: more is no capabilities string, but a monitor repeating itself

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
        """The monitor's current input source: the value inputs gives it. Trusted once two reads agree; raises OSError otherwise."""
        values = []
        error = None
        for attempt in range(self._READ_ATTEMPTS + 1):
            try:
                values.append(await self.get_vcp(self._VCP_INPUT_SOURCE) & 0xFF)  # Some monitors put garbage in the high byte
            except OSError as e:
                error = e
            if len(values) >= 2 and values[-1] == values[-2]:
                return values[-1]
            await asyncio.sleep(0.05)
        raise error or OSError(f"The monitor on HDMI {self.hdmi} gave changing values for its input")

    async def _get_capabilities_fragment(self, offset):
        error = None
        for attempt in range(self._READ_ATTEMPTS):
            self._write(bytes([self._SOURCE, 0x83, 0xF3, offset >> 8, offset & 0xFF]))
            await asyncio.sleep(0.05)
            try:
                reply = self._i2c.readfrom(self._ADDRESS, 38)
                # Source, length, opcode 0xE3, offset (2 bytes), up to 32 bytes of the string, checksum
                length = (reply[1] & 0x7F) - 3
                if 0 <= length <= 32 and reply[2] == 0xE3 and (reply[3] << 8) | reply[4] == offset and self._checksum(self._REPLY_SOURCE, reply[: 5 + length]) == reply[5 + length]:
                    return reply[5 : 5 + length]
                error = OSError(f"The monitor on HDMI {self.hdmi} gave an invalid capabilities string")
            except OSError as e:
                error = e
        raise error

    async def get_capabilities(self):
        """The monitor's capabilities string, as MCCS defines it: "(prot(monitor)type(lcd)vcp(02 10 60(0F 11 12) ...)...)"."""
        capabilities = b""
        while len(capabilities) < self._MAX_CAPABILITIES:
            fragment = await self._get_capabilities_fragment(len(capabilities))
            if not fragment:
                break
            capabilities += fragment
        return "".join(chr(byte) for byte in capabilities if 32 <= byte < 127)

    async def get_inputs(self):
        """The input source values the monitor lists in its capabilities; None when it lists none."""
        capabilities = (await self.get_capabilities()).lower()
        start = capabilities.find("vcp(")  # Not "vcpname(", which names manufacturer codes
        if start < 0:
            return None
        tokens = []  # Words and parentheses of vcp(...)
        word = ""
        for char in capabilities[start + 4 :]:
            if char in "() ":
                if word:
                    tokens.append(word)
                word = ""
                if char != " ":
                    tokens.append(char)
            else:
                word += char
        if word:  # Cut short
            tokens.append(word)
        depth = 0
        for index, token in enumerate(tokens):
            if token == "(":
                depth += 1
            elif token == ")":
                if depth == 0:  # The end of vcp(...)
                    return None
                depth -= 1
            elif depth == 0 and token == "60" and tokens[index + 1 : index + 2] == ["("]:  # The input source code, then its values
                values = []
                for value in tokens[index + 2 :]:
                    if value in "()":
                        break
                    try:
                        value = int(value, 16) & 0xFF
                    except ValueError:  # Garbage: skipped
                        continue
                    if value not in values:
                        values.append(value)
                return values or None
        return None

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
