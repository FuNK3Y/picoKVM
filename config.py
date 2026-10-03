import json
import os

from ddc_monitor import DdcMonitor
from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class Config:
    wireless_network = {}
    usb_gpio_pin = "G1"  # USB select: low = input A, high = input B
    button_gpio_pin = "BUTTON"
    led_gpio_pin = "LED_RGB"  # One pin, or a list of pins driving one SK6812/WS2812 each
    led_idle_brightness = 0  # 0 turns the LEDs off after a switch; 0 < x <= 1 keeps the active input's color, dimmed
    # Optional, picoKVM board only (see hardware/README.md): left at None they are not used
    usb_enable_gpio_pin = None  # Active low: enables the USB data switches
    peripheral_power_gpio_pin = None  # Active high: powers the peripheral port, cycled on each switch
    peripheral_fault_gpio_pin = None  # Active low: peripheral port over-current / over-temperature
    vbus_sense_gpio_pins = None  # {"A": pin, "B": pin}: high while that computer powers its USB port
    devices = []
    _configFile = "config.json"
    _lastSaved = None
    inputs = {"A": {"color": "#007BFF", "name": "PC1"}, "B": {"color": "#902a8d", "name": "PC2"}}

    def _serialize():
        attributes = {k: v for k, v in Config.__dict__.items() if not callable(v) and not k.startswith("_") and k != "devices"}
        attributes["devices"] = [{"type": type(device).__name__, "data": device.to_dict()} for device in Config.devices]
        return json.dumps(attributes)

    def save():
        content = Config._serialize()
        if content == Config._lastSaved:  # Nothing changed, do not wear out the flash on every switch
            return
        temp_file = Config._configFile + ".tmp"
        with open(temp_file, "w") as file:
            file.write(content)
        try:
            os.rename(temp_file, Config._configFile)  # Atomic on littlefs, so a power loss cannot leave a truncated config
        except OSError:  # FAT cannot rename onto an existing file
            os.remove(Config._configFile)
            os.rename(temp_file, Config._configFile)
        Config._lastSaved = content

    def load():
        with open(Config._configFile, "r") as file:
            content = json.loads(file.read())
        for key in (k for k in content.keys() if k != "devices"):
            setattr(Config, key, content[key])
        setattr(
            Config,
            "devices",
            [globals()[device["type"]].from_dict(device["data"]) for device in content["devices"]],
        )
        Config._lastSaved = Config._serialize()
