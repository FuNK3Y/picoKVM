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



def settings(**changes):
    """Valid settings, as the configuration page sends them back."""
    content = {
        "wireless_network": {"SSID": "home", "hostname": "picokvm"},
        "inputs": {"A": {"name": "PC", "color": "#007BFF"}, "B": {"name": "Laptop", "color": "#902a8d"}},
        "led_idle_brightness": 0.2,
        "update_repository": "owner/repo",
        "devices": [{"type": "DdcMonitor", "data": {"hdmi": 1, "inputs": {"A": 15, "B": 17}}}],
    }
    content.update(changes)
    return content


class ApplyTest(TestCase):
    def setUp(self):
        super().setUp()
        Config.wireless_network = {"SSID": "home", "hostname": "picokvm", "password": "wifi-secret"}
        Config.admin_password = "admin-secret"
        Config.devices = []
        Config.save()

    def test_public_hides_the_passwords(self):
        public = Config.public()
        self.assertEqual(public["wireless_network"], {"SSID": "home", "hostname": "picokvm"})
        self.assertNotIn("admin_password", public)

    def test_applies_without_restart(self):
        self.assertFalse(Config.apply(settings()))
        self.assertEqual(Config.wireless_network["password"], "wifi-secret")  # Kept: not sent
        self.assertEqual(Config.admin_password, "admin-secret")
        self.assertEqual(Config.led_idle_brightness, 0.2)
        self.assertEqual([type(device).__name__ for device in Config.devices], ["DdcMonitor"])
        with open("config.json") as file:
            self.assertEqual(json.load(file)["update_repository"], "owner/repo")

    def test_wifi_changes_restart(self):
        self.assertTrue(Config.apply(settings(wireless_network={"SSID": "office", "hostname": "picokvm"})))
        self.assertTrue(Config.apply(settings(wireless_network={"SSID": "office", "hostname": "picokvm", "password": "new"})))
        self.assertEqual(Config.wireless_network["password"], "new")
        self.assertFalse(Config.apply(settings(wireless_network={"SSID": "office", "hostname": "picokvm", "password": ""})))

    def test_changes_the_admin_password(self):
        Config.apply(settings(admin_password="new"))
        self.assertEqual(Config.admin_password, "new")
        Config.apply(settings(admin_password=""))  # Empty: unchanged
        self.assertEqual(Config.admin_password, "new")

    def test_refuses_invalid_settings_without_changing_anything(self):
        before = Config._serialize()
        for changes, message in (
            ({"wireless_network": {"SSID": "", "hostname": "picokvm"}}, "SSID"),
            ({"inputs": {"A": {"name": "PC", "color": "blue"}, "B": {"name": "Laptop", "color": "#902a8d"}}}, "color"),
            ({"inputs": {"A": {"name": "", "color": "#007BFF"}, "B": {"name": "Laptop", "color": "#902a8d"}}}, "name"),
            ({"led_idle_brightness": 2}, "brightness"),
            ({"update_repository": "repo"}, "owner/name"),
            ({"update_repository": "owner/repo?x=1"}, "owner/name"),
            ({"devices": [{"type": "Toaster", "data": {}}]}, "Monitor 1: a type"),
            ({"devices": [{"type": "DdcMonitor", "data": {"hdmi": 3, "inputs": {"A": 15, "B": 17}}}]}, "no HDMI port 3"),
            ({"devices": [{"type": "DdcMonitor", "data": {"hdmi": 1, "inputs": {"A": 15}}}]}, "inputs"),
            ({"devices": [{"type": "SamsungMonitor", "data": {"hostname": "tv"}}]}, r"Monitor 1 \(SamsungMonitor\)"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                Config.apply(settings(**changes))
        self.assertEqual(Config._serialize(), before)


class DdcMonitorTest(TestCase):
    async def test_switches_through_its_hdmi_port(self):
        await DdcMonitor(hdmi=2, inputs={"A": 15, "B": 17}).set_active_input("B")
        sda, address, message = SoftI2C.writes[0]
        self.assertEqual((sda, address), (board.HDMI_DDC[2][0], 0x37))
        self.assertEqual(message[:6], bytes([0x51, 0x84, 0x03, 0x60, 0x00, 17]))


if __name__ == "__main__":
    unittest.main()
