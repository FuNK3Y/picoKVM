import json
import os
import unittest
from unittest.mock import patch

from mocks import SoftI2C, TestCase
import board
from config import Config
from ddc_monitor import DdcMonitor


class ConfigTest(TestCase):
    def write(self, content):
        with open("config.json", "w") as file:
            json.dump(content, file)

    def test_load_and_save(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.example.json")) as file:
            example = json.load(file)
        example["usb_gpio_pin"] = 8  # From an earlier version: ignored, and dropped on save
        self.write(example)
        Config.load()
        self.assertEqual([type(device).__name__ for device in Config.devices], ["DdcMonitor", "DdcMonitor", "SamsungMonitor", "GenericDevice"])
        self.assertFalse(hasattr(Config, "usb_gpio_pin"))
        Config.devices[2].token = "paired"
        Config.save()
        with open("config.json") as file:
            saved = json.load(file)
        self.assertNotIn("usb_gpio_pin", saved)
        self.assertEqual(saved["devices"][0], {"type": "DdcMonitor", "data": {"hdmi": 1, "inputs": {"A": 15, "B": 17}, "power_on": False, "power_on_delay": 2.0, "freq": 50000}})
        self.assertEqual(saved["devices"][2]["data"]["token"], "paired")
        self.assertEqual(saved["admin_password"], example["admin_password"])

    def test_save_on_fat(self):
        Config.devices = []
        Config.admin_password = "first"
        Config.save()
        rename = os.rename
        calls = []

        def fat_rename(source, target):  # FAT cannot rename onto an existing file
            calls.append(target)
            if os.path.exists(target):
                raise OSError("EEXIST")
            rename(source, target)

        Config.admin_password = "second"
        with patch("os.rename", fat_rename):
            Config.save()
            Config.save()  # Unchanged: not written again
        self.assertEqual(len(calls), 2)
        with open("config.json") as file:
            self.assertEqual(json.load(file)["admin_password"], "second")
        self.assertFalse(os.path.exists("config.json.tmp"))


class DdcMonitorTest(TestCase):
    async def test_switches_through_its_hdmi_port(self):
        await DdcMonitor(hdmi=2, inputs={"A": 15, "B": 17}).set_active_input("B")
        sda, address, message = SoftI2C.writes[0]
        self.assertEqual((sda, address), (board.HDMI_DDC[2][0], 0x37))
        self.assertEqual(message[:6], bytes([0x51, 0x84, 0x03, 0x60, 0x00, 17]))


if __name__ == "__main__":
    unittest.main()
