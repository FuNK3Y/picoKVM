"""Stand-ins for the MicroPython modules the firmware imports, so that src/ runs on CPython.

Importing this module installs them in sys.modules, adds MicroPython's time.ticks_*, and puts src/ on sys.path.
"""

import asyncio
import gc
import json
import os
import struct
import sys
import tempfile
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.append(".frozen")  # MicroPython's entry for the frozen modules, which main.py moves first


def module(name, **attributes):
    sys.modules[name] = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(sys.modules[name], key, value)


class Reset(Exception):
    """machine.reset()"""


class Pin:
    IN = 0
    OUT = 1
    PULL_UP = 2
    levels = {}  # pin number -> level, shared by every Pin object on that number
    history = []  # (pin number, level) of every write

    def __init__(self, number, mode=IN, pull=None, value=None):
        self.number = number
        if value is not None:
            self.value(value)

    def value(self, level=None):
        if level is None:
            return Pin.levels.get(self.number, 0)
        Pin.levels[self.number] = level
        Pin.history.append((self.number, level))


class WDT:
    instances = []

    def __init__(self, timeout):
        self.timeout = timeout
        self.feeds = 0
        WDT.instances.append(self)

    def feed(self):
        self.feeds += 1


class SoftI2C:
    writes = []
    replies = {}  # (SDA pin, address) -> bytes readfrom() returns, or a function of the last write there giving them; others do not answer

    def __init__(self, sda, scl, freq):
        self.sda = sda.number

    def writeto(self, address, data):
        SoftI2C.writes.append((self.sda, address, bytes(data)))

    def readfrom(self, address, size):
        if (self.sda, address) not in SoftI2C.replies:
            raise OSError(19)  # ENODEV: NACK
        reply = SoftI2C.replies[(self.sda, address)]
        if callable(reply):
            reply = reply([data for sda, written, data in SoftI2C.writes if (sda, written) == (self.sda, address)][-1])
        return reply[:size]


def reset():
    raise Reset()


class Partition:
    """Flash slots as bytearrays. set_boot() can be made to fail like the bootloader's image check."""

    RUNNING = 1
    SLOT_SIZE = 0x270000
    running_label = "ota_0"
    slots = {}
    booted = None
    marked_valid = 0
    reject = False

    def __init__(self, which, label=None):
        self.label = label or Partition.running_label

    def info(self):
        return (0, 0, 0, Partition.SLOT_SIZE, self.label, False)

    def get_next_update(self):
        return Partition(None, "ota_1" if self.label == "ota_0" else "ota_0")

    def readblocks(self, index, buffer):
        buffer[:] = Partition.slots[self.label][index * 4096 : (index + 1) * 4096]

    def writeblocks(self, index, buffer):
        assert len(buffer) == 4096
        Partition.slots.setdefault(self.label, bytearray(Partition.SLOT_SIZE))[index * 4096 : (index + 1) * 4096] = buffer

    def set_boot(self):
        if Partition.reject:
            raise OSError(-5379)
        Partition.booted = self.label

    @classmethod
    def mark_app_valid_cancel_rollback(cls):
        cls.marked_valid += 1

    @classmethod
    def boot(cls, running="ota_0", image_bytes=None):
        """Resets the flash to a single slot holding image_bytes (a v1.0.0 image by default), running."""
        cls.running_label = running
        cls.slots = {running: bytearray(image_bytes or image("v1.0.0"))}
        cls.booted = None
        cls.marked_valid = 0
        cls.reject = False


class NeoPixel:
    def __init__(self, pin, count):
        self.pin = pin.number
        self.pixels = [(0, 0, 0)] * count

    def __setitem__(self, index, rgb):
        self.pixels[index] = tuple(rgb)

    def __getitem__(self, index):
        return self.pixels[index]

    def write(self):
        pass


class WLAN:
    STA_IF = 0
    PM_NONE = 0
    connected = True

    def __init__(self, interface):
        pass

    def active(self, active):
        pass

    def config(self, **settings):
        pass

    connecting = False  # As the ESP32's Wi-Fi driver, whose state outlives a soft reboot
    connects = 0
    networks = {}  # SSID -> password: those connect() joins at once
    joined = None  # SSID of the last connect()
    scanned = []  # scan()'s tuples

    def connect(self, ssid, password):
        if WLAN.connecting or WLAN.connected:
            raise OSError("Wifi Internal State Error")
        WLAN.connecting = True
        WLAN.connects += 1
        WLAN.joined = ssid
        if WLAN.networks.get(ssid) == password:
            WLAN.connecting, WLAN.connected = False, True

    def ifconfig(self):
        return ("192.168.1.42", "255.255.255.0", "192.168.1.1", "192.168.1.1")

    def scan(self):
        return WLAN.scanned

    def disconnect(self):
        WLAN.connecting = WLAN.connected = False

    def isconnected(self):
        return WLAN.connected

    def status(self, name):
        return -50


class ClientSession:
    """aiohttp.ClientSession, answering GETs from `served`: {url: (status, body bytes[, headers])}, recording the other requests
    and the websocket connections, whose messages come from `received` and go to `sent`."""

    served = {}
    requests = []  # (method, url, kwargs)
    connections = []  # URLs
    received = []  # JSON messages, popped by receive_json()
    sent = []  # JSON messages

    def __init__(self, headers={}):
        self.headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url):
        status, body = ClientSession.served[url][:2]
        return _Context(_Response(status, body))

    async def request_raw(self, method, url, headers={}):
        """The response as it comes from the socket: status line, headers, body."""
        ClientSession.requests.append((method, url, {"headers": dict(headers)}))
        status, body, *response_headers = ClientSession.served[url]
        response_headers = "".join(f"{name}: {value}\r\n" for name, value in (response_headers[0] if response_headers else {}).items())
        stream = _Stream()
        stream.feed_data(f"HTTP/1.0 {status} Status\r\n{response_headers}\r\n".encode() + body)
        stream.feed_eof()
        return stream

    def request(self, method, url, **kwargs):
        ClientSession.requests.append((method, url, kwargs))
        return _Context(_Response(200, b"OK"))

    def ws_connect(self, url):
        ClientSession.connections.append(url)
        return _Context(_WebSocket())


class _WebSocket:
    async def receive_json(self):
        return ClientSession.received.pop(0)

    async def send_json(self, message):
        ClientSession.sent.append(message)


class _Stream(asyncio.StreamReader):
    """MicroPython's asyncio stream: read(n) returns up to n bytes, and aclose() closes it."""

    closed = 0

    async def aclose(self):
        _Stream.closed += 1


class _Context:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        pass


class _Response:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    async def json(self):
        return json.loads(self.body)

    async def text(self):
        return self.body.decode()


module("machine", Pin=Pin, WDT=WDT, SoftI2C=SoftI2C, reset=reset)
module("esp32", Partition=Partition, idf_heap_info=lambda kind: [(1000, 500, 400, 300)], HEAP_DATA=0, mcu_temperature=lambda: 40)
module("network", WLAN=WLAN, STA_IF=WLAN.STA_IF, hostname=lambda *args: "picokvm")
module("neopixel", NeoPixel=NeoPixel)
module("micropython", kbd_intr=lambda char: None)
module("aiohttp", ClientSession=ClientSession)
gc.mem_free = lambda: 100000
gc.mem_alloc = lambda: 50000
time.ticks_ms = lambda: int(time.monotonic() * 1000)
time.ticks_add = lambda ticks, delta: ticks + delta
time.ticks_diff = lambda end, start: end - start
sys.print_exception = lambda e: None


def image(version, size=10000, chip=9, prefix="picoKVM "):
    """An application image as the updater sees it: header, chip, application descriptor with its version."""
    data = bytearray(size)
    data[0] = 0xE9
    struct.pack_into("<H", data, 12, chip)
    struct.pack_into("<I", data, 32, 0xABCD5432)
    version = (prefix + version).encode()
    data[48 : 48 + len(version)] = version
    for i in range(80, size):
        data[i] = i * 7 % 251
    return bytes(data)


def reader(data, chunk=1000):
    """read(n) over data, returning at most chunk bytes at a time, like a socket."""
    position = 0

    async def read(size):
        nonlocal position
        out = data[position : position + min(size, chunk)]
        position += len(out)
        return out

    return read



class TestCase(unittest.IsolatedAsyncioTestCase):
    """Runs each test in an empty working directory (the board's filesystem), on fresh mocks."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._directory = tempfile.TemporaryDirectory()
        os.chdir(self._directory.name)
        Partition.boot()
        WDT.instances.clear()
        Pin.levels.clear()
        Pin.history.clear()
        WLAN.connected = True
        WLAN.connecting = False
        WLAN.connects = 0
        WLAN.networks = {}
        WLAN.joined = None
        WLAN.scanned = []
        SoftI2C.writes.clear()
        SoftI2C.replies.clear()
        for recorded in (ClientSession.served, ClientSession.requests, ClientSession.connections, ClientSession.received, ClientSession.sent):
            recorded.clear()

    def tearDown(self):
        os.chdir(self._cwd)
        self._directory.cleanup()
