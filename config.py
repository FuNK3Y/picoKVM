import json
import os

from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class Config:
    wireless_network = {}
    usb_gpio_pin = "G1"
    button_gpio_pin = "BUTTON"
    led_gpio_pin = "LED_RGB"
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
