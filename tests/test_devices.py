import unittest
from unittest.mock import patch

import board
from mocks import ClientSession, SoftI2C, TestCase
from ddc_monitor import DdcMonitor
from device import Device
from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class SamsungMonitorTest(TestCase):
    def setUp(self):
        super().setUp()
        self.monitor = SamsungMonitor("192.168.1.20", {"A": [{"command": "KEY_RETURN", "delay": 0}, {"command": "KEY_LEFT", "repeat": 2}, "KEY_ENTER"]}, command_delay=0)

    def commands(self):
        return [message["params"]["DataOfCmd"] for message in ClientSession.sent]

    async def test_pairs_then_sends_the_sequence(self):
        ClientSession.received = [{"data": {"token": "1234"}}, {"event": "ms.channel.connect"}]
        await self.monitor.set_active_input("A")
        self.assertEqual(self.monitor.token, "1234")
        pairing, session = ClientSession.connections
        self.assertTrue(pairing.startswith("wss://192.168.1.20:8002/api/v2/channels/samsung.remote.control?name="))
        self.assertEqual(session, pairing + "&token=1234")
        self.assertEqual(self.commands(), ["KEY_RETURN", "KEY_LEFT", "KEY_LEFT", "KEY_ENTER"])
        self.assertEqual(ClientSession.sent[0]["method"], "ms.remote.control")

    async def test_paired_already(self):
        self.monitor.token = "1234"
        ClientSession.received = [{"event": "ms.channel.connect"}]
        await self.monitor.set_active_input("A")
        self.assertEqual(len(ClientSession.connections), 1)
        self.assertEqual(self.monitor.to_dict()["token"], "1234")  # Persisted with the configuration


class GenericDeviceTest(TestCase):
    async def test_sends_the_request_of_the_input(self):
        device = GenericDevice("https://example.com/input", "POST", {"A": {"data": "a"}, "B": {"data": "b"}})
        self.assertEqual(await device.set_active_input("B"), "OK")
        self.assertEqual(ClientSession.requests, [("POST", "https://example.com/input", {"data": "b"})])

    async def test_no_arguments(self):
        await GenericDevice("https://example.com/input", "GET").set_active_input("A")
        self.assertEqual(ClientSession.requests, [("GET", "https://example.com/input", {})])

    def test_round_trip(self):
        device = GenericDevice.from_dict({"uri": "https://example.com", "method": "GET"})
        self.assertEqual(device.to_dict(), {"uri": "https://example.com", "method": "GET", "kwargs": {"A": {}, "B": {}}})


class DdcMonitorTest(TestCase):
    async def test_powers_on_first(self):
        await DdcMonitor(hdmi=1, inputs={"A": 15, "B": 17}, power_on=True, power_on_delay=0).set_active_input("A")
        self.assertEqual([message[3] for _, _, message in SoftI2C.writes], [0xD6, 0x60])

    async def test_no_monitor(self):
        with patch.object(SoftI2C, "writeto", side_effect=OSError("ENODEV")):
            with self.assertRaisesRegex(OSError, "monitor on HDMI 1 failed"):
                await DdcMonitor(hdmi=1, inputs={"A": 15, "B": 17}).set_active_input("A")


def edid(name=b"DELL U2723QE"):
    """A 128-byte EDID block: header, vendor DEL, and a display name descriptor unless name is None."""
    data = bytearray(128)
    data[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    data[8:10] = bytes([0x10, 0xAC])  # D, E, L
    if name is not None:
        data[72:77] = b"\x00\x00\x00\xfc\x00"
        data[77:90] = (name + b"\n").ljust(13, b" ")
    data[127] = -sum(data) & 0xFF
    return bytes(data)


def vcp_reply(code, current, result=0x00, maximum=0xFF):
    reply = bytes([0x6E, 0x88, 0x02, result, code, 0x00, maximum >> 8, maximum & 0xFF, current >> 8, current & 0xFF])
    checksum = 0x50
    for byte in reply:
        checksum ^= byte
    return reply + bytes([checksum])


class DdcMonitorReadTest(TestCase):
    def setUp(self):
        super().setUp()
        self.monitor = DdcMonitor(hdmi=1, inputs={"A": 15, "B": 17})
        self.sda = board.HDMI_DDC[1][0]

    async def test_reads_the_input(self):
        SoftI2C.replies[(self.sda, 0x37)] = vcp_reply(0x60, 0x0311)  # A high byte some monitors add
        self.assertEqual(await self.monitor.get_input(), 17)
        self.assertEqual(SoftI2C.writes, [(self.sda, 0x37, bytes([0x51, 0x82, 0x01, 0x60, 0x6E ^ 0x51 ^ 0x82 ^ 0x01 ^ 0x60]))])

    async def test_bad_replies(self):
        for reply, message in (
            (vcp_reply(0x60, 17)[:10] + b"\x00", "no valid reply"),  # Checksum
            (vcp_reply(0x10, 17), "no valid reply"),  # Another code
            (bytes([0x6E, 0x80, 0xBE]) + bytes(8), "no valid reply"),  # Null message: busy
            (vcp_reply(0x60, 0, result=0x01), "does not support VCP 0x60"),
        ):
            SoftI2C.replies[(self.sda, 0x37)] = reply
            with self.assertRaisesRegex(OSError, message):
                await self.monitor.get_vcp(0x60)
        del SoftI2C.replies[(self.sda, 0x37)]
        with self.assertRaisesRegex(OSError, "read from the monitor on HDMI 1 failed"):
            await self.monitor.get_vcp(0x60)

    def test_name(self):
        SoftI2C.replies[(self.sda, 0x50)] = edid()
        self.assertEqual(self.monitor.read_name(), "DELL U2723QE")
        self.assertIn((self.sda, 0x50, b"\x00"), SoftI2C.writes)
        SoftI2C.replies[(self.sda, 0x50)] = edid(name=None)
        self.assertEqual(self.monitor.read_name(), "DEL monitor")
        SoftI2C.replies[(self.sda, 0x50)] = edid()[:127] + b"\x00"
        with self.assertRaisesRegex(OSError, "invalid EDID"):
            self.monitor.read_name()
        del SoftI2C.replies[(self.sda, 0x50)]
        with self.assertRaisesRegex(OSError, "No monitor answers on HDMI 1"):
            self.monitor.read_name()


class DeviceTest(unittest.TestCase):
    def test_base(self):
        self.assertIsNone(Device().set_active_input("A"))


if __name__ == "__main__":
    unittest.main()
