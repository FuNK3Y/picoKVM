import json
import os

from ddc_monitor import DdcMonitor
from generic_device import GenericDevice
from samsung_monitor import SamsungMonitor


class Config:
    wireless_network = {}
    inputs = {"A": {"color": "#FF8C00", "name": "PC1"}, "B": {"color": "#3DBDE7", "name": "PC2"}}  # Orange, blue
    led_idle_brightness = 0  # 0 turns the LEDs off after a switch; 0 < x <= 1 keeps the active input's color, dimmed
    admin_password = None  # Required, as HTTP Basic credentials (any user name), by the API calls that change the device
    update_repository = "FuNK3Y/picoKVM"  # GitHub repository whose latest release POST /api/update/latest installs
    devices = []
    _settings = ("wireless_network", "inputs", "led_idle_brightness", "admin_password", "update_repository")  # Others in config.json are ignored
    _device_types = {cls.__name__: cls for cls in (DdcMonitor, GenericDevice, SamsungMonitor)}
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
        Config.devices = [Config._device_types[device["type"]].from_dict(device["data"]) for device in content["devices"]]
        Config._lastSaved = Config._serialize()

    @staticmethod
    def public():
        """The settings, as the configuration page edits them: without the passwords."""
        settings = json.loads(Config._serialize())
        settings["wireless_network"].pop("password", None)
        settings.pop("admin_password")
        return settings

    @staticmethod
    def apply(settings):
        """Checks settings (as public() gives them; a password only when it changes), then applies and saves them.

        Raises ValueError, before changing anything, on an invalid setting. Returns whether the device has to restart
        for them to apply: Wi-Fi settings only take effect at start-up.
        """
        wireless_network = settings.get("wireless_network", {})
        for key in ("SSID", "hostname"):
            if not isinstance(wireless_network.get(key), str) or not wireless_network[key]:
                raise ValueError(f"Wi-Fi {key} missing")
        wireless_network = {
            "SSID": wireless_network["SSID"],
            "hostname": wireless_network["hostname"],
            "password": wireless_network.get("password") or Config.wireless_network.get("password", ""),
        }
        inputs = settings.get("inputs", {})
        for input in ("A", "B"):
            name = inputs.get(input, {}).get("name")
            color = inputs.get(input, {}).get("color")
            if not isinstance(name, str) or not name:
                raise ValueError(f"Input {input}: name missing")
            if not Config._is_color(color):
                raise ValueError(f"Input {input}: the color is not #rrggbb")
        brightness = settings.get("led_idle_brightness")
        if not isinstance(brightness, (int, float)) or not 0 <= brightness <= 1:
            raise ValueError("LED brightness: from 0 to 1")
        repository = settings.get("update_repository")
        if not isinstance(repository, str) or len([part for part in repository.split("/") if part]) != 2:
            raise ValueError("Update repository: owner/name")
        devices = []
        for number, device in enumerate(settings.get("devices", []), 1):
            if not isinstance(device, dict) or device.get("type") not in Config._device_types or not isinstance(device.get("data"), dict):
                raise ValueError(f"Monitor {number}: a type among {', '.join(Config._device_types)}, and its data")
            try:
                devices.append(Config._device_types[device["type"]].from_dict(device["data"]))
            except (TypeError, ValueError) as e:  # Missing or unknown settings, invalid values
                raise ValueError(f"Monitor {number} ({device['type']}): {e}")
        restart = wireless_network != Config.wireless_network
        Config.wireless_network = wireless_network
        Config.inputs = {input: {"name": inputs[input]["name"], "color": inputs[input]["color"]} for input in ("A", "B")}
        Config.led_idle_brightness = brightness
        Config.admin_password = settings.get("admin_password") or Config.admin_password
        Config.update_repository = repository
        Config.devices = devices
        Config.save()
        return restart

    @staticmethod
    def _is_color(color):
        return isinstance(color, str) and len(color) == 7 and color[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in color[1:])
