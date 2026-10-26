import unittest
from unittest.mock import patch

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


class DeviceTest(unittest.TestCase):
    def test_base(self):
        self.assertIsNone(Device().set_active_input("A"))


if __name__ == "__main__":
    unittest.main()
