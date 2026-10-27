import asyncio
import json
import unittest
from unittest.mock import patch

from mocks import WLAN, TestCase
from config import Config
from improv import Improv


def packet(command, data=b"", type=0x03, checksum=None):
    """An RPC command, as ESP Web Tools sends it."""
    data = bytes([command, len(data)]) + data
    content = b"IMPROV" + bytes([1, type, len(data)]) + data
    return content + bytes([sum(content) & 0xFF if checksum is None else checksum]) + b"\n"


def credentials(ssid, password):
    ssid, password = ssid.encode(), password.encode()
    return bytes([len(ssid)]) + ssid + bytes([len(password)]) + password


def parse(output):
    """The packets the device sent: (type, data) for states and errors, (type, command, strings) for RPC results."""
    packets = []
    while b"IMPROV" in output:
        output = output[output.index(b"IMPROV") :]
        type, length = output[7], output[8]
        data = output[9 : 9 + length]
        assert output[9 + length] == sum(output[: 9 + length]) & 0xFF
        if type == 0x04:
            strings, position = [], 2
            while position < 2 + data[1]:
                strings.append(data[position + 1 : position + 1 + data[position]].decode())
                position += 1 + data[position]
            packets.append((type, data[0], strings))
        else:
            packets.append((type, data[0]))
        output = output[10 + length :]
    return packets


class ImprovTest(TestCase):
    def setUp(self):
        super().setUp()
        Config.wireless_network = {"SSID": "", "password": "", "hostname": "picokvm"}
        WLAN.connected = False
        self.input = asyncio.Queue()
        self.output = b""
        patcher = patch.object(Improv, "_CONNECT_TIMEOUT", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        self.output += data

    def connect(self):  # main.connect()
        WLAN(WLAN.STA_IF).connect(Config.wireless_network["SSID"], Config.wireless_network["password"])

    async def exchange(self, *data, wait=0.05):
        """Sends data to a running Improv; returns the packets it answered."""
        improv = Improv(WLAN(WLAN.STA_IF), self.connect, "v1.2.3", self.input.get, self.write)
        task = asyncio.create_task(improv.run())
        for byte in b"".join(data):
            self.input.put_nowait(byte)
        await asyncio.sleep(wait)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return parse(self.output)

    async def test_state_and_info(self):
        self.assertEqual(await self.exchange(b"boot log\r\n", packet(0x02), packet(0x03)), [
            (0x02, 0x00), (0x01, 0x02),  # Ready
            (0x02, 0x00), (0x04, 0x03, ["picoKVM", "v1.2.3", "ESP32-S3", "picokvm"]),
        ])
        WLAN.connected = True
        self.output = b""
        self.assertEqual(await self.exchange(packet(0x02)), [(0x02, 0x00), (0x01, 0x04), (0x04, 0x02, ["http://192.168.1.42/"])])

    async def test_provisions(self):
        WLAN.networks = {"home": "pässword"}
        packets = await self.exchange(packet(0x01, credentials("home", "pässword")), wait=0.3)
        self.assertEqual(packets, [(0x02, 0x00), (0x01, 0x03), (0x01, 0x04), (0x04, 0x01, ["http://192.168.1.42/"])])
        with open("config.json") as file:
            self.assertEqual(json.load(file)["wireless_network"], {"SSID": "home", "password": "pässword", "hostname": "picokvm"})

    async def test_wrong_credentials_go_back_to_the_previous_network(self):
        Config.wireless_network = {"SSID": "home", "password": "secret", "hostname": "picokvm"}
        WLAN.networks = {"home": "secret"}
        packets = await self.exchange(packet(0x01, credentials("office", "wrong")), wait=1.5)
        self.assertEqual(packets, [(0x02, 0x00), (0x01, 0x03), (0x02, 0x03), (0x01, 0x02)])
        self.assertEqual(Config.wireless_network["SSID"], "home")
        self.assertEqual(WLAN.joined, "home")
        self.assertTrue(WLAN.connected)

    async def test_scans(self):
        WLAN.scanned = [(b"home", b"", 1, -70, 3, False), (b"open", b"", 6, -50, 0, False), (b"home", b"", 11, -60, 3, False), (b"", b"", 1, -40, 3, True), (b"\xff", b"", 1, -40, 3, False)]
        self.assertEqual(await self.exchange(packet(0x04)), [
            (0x02, 0x00),
            (0x04, 0x04, ["open", "-50", "NO"]),
            (0x04, 0x04, ["home", "-60", "YES"]),  # Its strongest access point
            (0x04, 0x04, []),
        ])

    async def test_hostname(self):
        packets = await self.exchange(packet(0x05), packet(0x05, b"desk-kvm"), packet(0x05, b"-bad"), packet(0x05, b"b\xffd"))
        self.assertEqual(packets, [
            (0x02, 0x00), (0x04, 0x05, ["picokvm"]),
            (0x02, 0x00), (0x04, 0x05, ["desk-kvm"]),
            (0x02, 0x00), (0x02, 0x05),
            (0x02, 0x00), (0x02, 0x05),
        ])
        with open("config.json") as file:
            self.assertEqual(json.load(file)["wireless_network"]["hostname"], "desk-kvm")

    async def test_invalid_packets(self):
        packets = await self.exchange(
            packet(0x02, checksum=0),
            packet(0x01, b"\x09home"),  # The SSID runs past the data
            packet(0x01, credentials("", "")),
            packet(0x07),
            packet(0x02, type=0x01),  # Not a command: ignored
            b"IMPROV\x02\x03\x02\x02\x00\x00",  # Another version: ignored
            b"IMPROV\x01\x03\x05\x02\x00",  # Cut off: dropped
            wait=1.2,
        )
        self.assertEqual(packets, [(0x02, 0x01), (0x02, 0x00), (0x02, 0x01), (0x02, 0x00), (0x02, 0x01), (0x02, 0x00), (0x02, 0x02)])
        self.output = b""
        self.assertEqual(await self.exchange(b"IMIMPROV" + packet(0x02)[6:]), [(0x02, 0x00), (0x01, 0x02)])  # Found after a false start



class CtrlCTest(unittest.TestCase):
    def test_ctrl_c_outside_a_packet_interrupts(self):
        """On its own event loop: asyncio lets KeyboardInterrupt out of the loop, as MicroPython's does."""
        Config.wireless_network = {"SSID": "", "password": "", "hostname": "picokvm"}
        WLAN.networks = {"home\x03": "\x03"}  # 0x03 within a packet does not interrupt
        output = []
        data = iter(packet(0x01, credentials("home\x03", "\x03")) + b"\r\x03")

        async def read():
            return next(data)

        improv = Improv(WLAN(WLAN.STA_IF), lambda: WLAN(WLAN.STA_IF).connect(Config.wireless_network["SSID"], Config.wireless_network["password"]), "v1.2.3", read, output.append)
        loop = asyncio.new_event_loop()
        try:
            with patch("config.Config.save"), self.assertRaises(KeyboardInterrupt):
                loop.run_until_complete(improv.run())
        finally:
            loop.close()
            WLAN.networks, WLAN.connected = {}, True
        self.assertEqual(parse(b"".join(output))[-1], (0x04, 0x01, ["http://192.168.1.42/"]))


if __name__ == "__main__":
    unittest.main()
