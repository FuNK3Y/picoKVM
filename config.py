import json

from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class Config:
    wireless_network = {}
    usb_gpio_pin = "G1"
    button_gpio_pin = "BUTTON"
    led_gpio_pin = "LED_RGB"
    devices = []
    _configFile = "config.json"
    inputs = {"A": {"color": "#007BFF", "name": "PC1"}, "B": {"color": "#902a8d", "name": "PC2"}}

    def save():
        attributes_to_save = {k: v for k, v in Config.__dict__.items() if not callable(v) and not k.startswith("_") and k != "devices"}
        devices = {"devices": [{"type": type(device).__name__, "data": device.to_dict()} for device in Config.devices]}
        attributes_to_save.update(devices)
        with open(Config._configFile, "w") as file:
            file.write(json.dumps(attributes_to_save))

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
