import json
import os

from ddc_monitor import DdcMonitor
from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class Config:
    wireless_network = {}
    inputs = {"A": {"color": "#007BFF", "name": "PC1"}, "B": {"color": "#902a8d", "name": "PC2"}}
    led_idle_brightness = 0  # 0 turns the LEDs off after a switch; 0 < x <= 1 keeps the active input's color, dimmed
    admin_password = None  # Required, as HTTP Basic credentials (any user name), by the API calls that change the device
    update_repository = "FuNK3Y/picoKVM"  # GitHub repository whose latest release POST /api/update/latest installs
    devices = []
    _settings = ("wireless_network", "inputs", "led_idle_brightness", "admin_password", "update_repository")  # Others in config.json are ignored
    _configFile = "config.json"
    _lastSaved = None

    @staticmethod
    def _serialize():
        attributes = {key: getattr(Config, key) for key in Config._settings}
        attributes["devices"] = [{"type": type(device).__name__, "data": device.to_dict()} for device in Config.devices]
        return json.dumps(attributes)

    @staticmethod
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

    @staticmethod
    def load():
        with open(Config._configFile, "r") as file:
            content = json.loads(file.read())
        for key in Config._settings:
            if key in content:
                setattr(Config, key, content[key])
        Config.devices = [globals()[device["type"]].from_dict(device["data"]) for device in content["devices"]]
        Config._lastSaved = Config._serialize()
