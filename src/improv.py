import asyncio
import micropython
import select
import sys
from config import Config


class Improv:
    """Improv Wi-Fi over the USB serial port (https://www.improv-wifi.com/serial/): the browser installer (ESP Web Tools)
    sends the Wi-Fi credentials, kept in config.json once the device connects with them.

    The port is the REPL's too. Its Ctrl-C would go off on any 0x03 byte of a packet (a length, a checksum), so this
    turns it off and raises KeyboardInterrupt itself on a 0x03 outside a packet: Ctrl-C still stops the program (mpremote,
    Thonny).
    """

    _HEADER = b"IMPROV"
    _VERSION = 1
    # Packet types
    _CURRENT_STATE = 0x01
    _ERROR_STATE = 0x02
    _RPC_COMMAND = 0x03
    _RPC_RESULT = 0x04
    # Current states
    _READY = 0x02
    _PROVISIONING = 0x03
    _PROVISIONED = 0x04
    # Error states
    _NO_ERROR = 0x00
    _INVALID_RPC = 0x01
    _UNKNOWN_RPC = 0x02
    _UNABLE_TO_CONNECT = 0x03
    _BAD_HOSTNAME = 0x05
    # RPC commands
    _WIFI_SETTINGS = 0x01
    _GET_STATE = 0x02
    _GET_INFO = 0x03
    _GET_NETWORKS = 0x04
    _HOSTNAME = 0x05

    _CTRL_C = 0x03
    _PACKET_TIMEOUT = 1  # s: for the rest of a packet, once its header came
    _CONNECT_TIMEOUT = 20  # s: for the device to join a network with the credentials sent
    _POLL_INTERVAL = 0.02  # s: of the port
    _HOSTNAME_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"  # RFC 1123

    def __init__(self, wlan, connect, version, read=None, write=None):
        """connect() (re)connects wlan to Config.wireless_network. read() returns the next byte from the port, write(bytes)
        sends to it: the REPL's stdin and stdout by default."""
        self.wlan = wlan
        self.connect = connect
        self.version = version
        self._read = read or self._read_stdin
        self._write = write or sys.stdout.buffer.write
        self._poller = None

    async def _read_stdin(self):
        if self._poller is None:
            self._poller = select.poll()
            self._poller.register(sys.stdin, select.POLLIN)
        while True:
            if self._poller.poll(0):
                byte = sys.stdin.buffer.read(1)
                if byte:
                    return byte[0]
            await asyncio.sleep(self._POLL_INTERVAL)

    async def run(self):
        micropython.kbd_intr(-1)
        try:
            while True:
                packet = await self._receive()
                if packet:
                    await self._handle(*packet)
        finally:
            micropython.kbd_intr(self._CTRL_C)

    async def _receive(self):
        """The next packet addressed to the device: (command, data); None for a corrupted one."""
        matched = 0
        while matched < len(self._HEADER):
            byte = await self._read()
            if byte == self._CTRL_C:  # Not in "IMPROV": typed, not part of a packet
                raise KeyboardInterrupt
            if byte == self._HEADER[matched]:
                matched += 1
            else:
                matched = 1 if byte == self._HEADER[0] else 0

        async def rest():
            version, type, length = await self._read(), await self._read(), await self._read()
            data = bytearray(length)
            for i in range(length):
                data[i] = await self._read()
            return version, type, length, bytes(data), await self._read()

        try:
            version, type, length, data, checksum = await asyncio.wait_for(rest(), self._PACKET_TIMEOUT)
        except asyncio.TimeoutError:
            return None
        if version != self._VERSION or type != self._RPC_COMMAND:
            return None
        if checksum != sum(self._HEADER + bytes([version, type, length]) + data) & 0xFF or len(data) < 2 or data[1] != len(data) - 2:
            self._send(self._ERROR_STATE, bytes([self._INVALID_RPC]))
            return None
        return data[0], data[2:]

    def _send(self, type, data):
        packet = self._HEADER + bytes([self._VERSION, type, len(data)]) + data
        self._write(packet + bytes([sum(packet) & 0xFF]) + b"\n")  # The newline keeps the log readable around it

    def _send_result(self, command, strings):
        data = b"".join(bytes([len(string)]) + string for string in (string.encode()[:255] for string in strings))
        self._send(self._RPC_RESULT, bytes([command, len(data)]) + data)

    def _send_state(self):
        provisioned = self.wlan.isconnected()
        self._send(self._CURRENT_STATE, bytes([self._PROVISIONED if provisioned else self._READY]))
        return provisioned

    def _url(self):
        return f"http://{self.wlan.ifconfig()[0]}/"  # Not the hostname: .local names do not resolve everywhere

    async def _handle(self, command, data):
        self._send(self._ERROR_STATE, bytes([self._NO_ERROR]))
        if command == self._WIFI_SETTINGS:
            await self._provision(data)
        elif command == self._GET_STATE:
            if self._send_state():
                self._send_result(command, [self._url()])
        elif command == self._GET_INFO:
            self._send_result(command, ["picoKVM", self.version, "ESP32-S3", Config.wireless_network["hostname"]])
        elif command == self._GET_NETWORKS:
            await self._send_networks()
        elif command == self._HOSTNAME:
            if data:
                hostname = self._hostname(data)
                if not hostname:
                    self._send(self._ERROR_STATE, bytes([self._BAD_HOSTNAME]))
                    return
                Config.wireless_network = Config.wireless_network.copy()
                Config.wireless_network["hostname"] = hostname  # Applies at the next connection
                Config.save()
            self._send_result(command, [Config.wireless_network["hostname"]])
        else:
            self._send(self._ERROR_STATE, bytes([self._UNKNOWN_RPC]))

    @staticmethod
    def _hostname(data):
        try:
            hostname = data.decode()
        except UnicodeError:
            return None
        valid = all(0 < len(label) <= 63 and label[0] != "-" and label[-1] != "-" and all(c in Improv._HOSTNAME_CHARACTERS for c in label) for label in hostname.split("."))
        return hostname if valid and len(hostname) <= 255 else None

    async def _provision(self, data):
        try:
            ssid_end = 1 + data[0]
            ssid = data[1:ssid_end].decode()
            password = data[ssid_end + 1 : ssid_end + 1 + data[ssid_end]].decode()
            if not ssid or len(data) != ssid_end + 1 + data[ssid_end]:
                raise ValueError
        except (IndexError, UnicodeError, ValueError):
            self._send(self._ERROR_STATE, bytes([self._INVALID_RPC]))
            return
        self._send(self._CURRENT_STATE, bytes([self._PROVISIONING]))
        previous = Config.wireless_network
        Config.wireless_network = previous.copy()
        Config.wireless_network.update({"SSID": ssid, "password": password})
        if await self._join():
            Config.save()
            self._send(self._CURRENT_STATE, bytes([self._PROVISIONED]))
            self._send_result(self._WIFI_SETTINGS, [self._url()])
            return
        Config.wireless_network = previous
        self._send(self._ERROR_STATE, bytes([self._UNABLE_TO_CONNECT]))
        self._send_state()
        if previous["SSID"]:
            await self._join()  # Back on the network it was on

    async def _join(self):
        """Connects to Config.wireless_network; returns whether it did."""
        try:
            self.wlan.disconnect()
        except OSError:  # Not connected
            pass
        self.connect()
        for _ in range(self._CONNECT_TIMEOUT * 5):
            if self.wlan.isconnected():
                return True
            await asyncio.sleep(0.2)
        return self.wlan.isconnected()

    async def _send_networks(self):
        self.wlan.active(True)
        networks = {}
        for network in self.wlan.scan():  # (ssid, bssid, channel, RSSI, security, hidden); blocks a couple of seconds
            rssi, security = network[3], network[4]
            try:
                ssid = network[0].decode()
            except UnicodeError:
                continue
            if ssid and (ssid not in networks or networks[ssid][0] < rssi):
                networks[ssid] = (rssi, security != 0)
        for ssid, (rssi, secured) in sorted(networks.items(), key=lambda network: -network[1][0]):
            self._send_result(self._GET_NETWORKS, [ssid, str(rssi), "YES" if secured else "NO"])
        self._send_result(self._GET_NETWORKS, [])
