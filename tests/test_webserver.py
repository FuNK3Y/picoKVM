import asyncio
import base64
import json
import unittest
from unittest.mock import patch

import mocks
from mocks import ClientSession, Partition, TestCase, image
from config import Config
from controller import Controller
from metrics_provider import MetricsProvider
from updater import Updater
from webserver import WebServer


class Device:
    def __init__(self):
        self.inputs = []

    async def set_active_input(self, input):
        self.inputs.append(input)

    def to_dict(self):
        return {}


class Writer:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data.encode() if isinstance(data, str) else data

    async def drain(self):
        pass

    async def wait_closed(self):
        pass


def credentials(password):
    return "Authorization: Basic " + base64.b64encode(b"admin:" + password.encode()).decode() + "\r\n"


class WebServerTest(TestCase):
    def setUp(self):
        super().setUp()
        Config.wireless_network = {"hostname": "kvm"}
        Config.admin_password = "secret"
        Config.update_repository = "owner/repo"
        Config.devices = [Device()]
        self.updater = Updater()
        self.restarts = 0

        async def restart():
            self.restarts += 1

        self.updater.restart = restart
        self.server = WebServer(Controller(), MetricsProvider(self.updater), self.updater)

    async def request(self, head, body=b""):
        """Returns the status line, the headers and the body of the response (JSON decoded when it is)."""
        reader = asyncio.StreamReader()
        reader.feed_data(head.encode() + b"\r\n" + body)
        reader.feed_eof()
        writer = Writer()
        await self.server.handle_client(reader, writer)
        if writer.data.startswith(b"HTTP/1.1 100 Continue\r\n\r\n"):
            writer.data = writer.data[25:]
        headers, _, content = writer.data.partition(b"\r\n\r\n")
        status, *headers = headers.decode().split("\r\n")
        if "Content-Type: application/json" in headers:
            content = json.loads(content)
        return status, headers, content

    def upload(self, data, auth="secret", extra=""):
        head = f"POST /api/update HTTP/1.1\r\nContent-Length: {len(data)}\r\n{extra}"
        return self.request(head + (credentials(auth) if auth else ""), data)

    async def test_page(self):
        status, _, content = await self.request("GET / HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b"<title>kvm</title>", content)

    async def test_stylesheet(self):
        status, headers, content = await self.request("GET /style.css HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn("Content-Type: text/css", headers)
        self.assertIn(b"prefers-color-scheme: dark", content)

    async def test_active_input(self):
        status, _, content = await self.request("POST /api/active_input/B HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(content, {"active_input": {"B": Config.inputs["B"]}})
        self.assertEqual(Config.devices[0].inputs, ["B"])
        status, _, content = await self.request("GET /api/active_input HTTP/1.1\r\n")
        self.assertEqual(content, {"active_input": {"B": Config.inputs["B"]}})

    async def test_unknown(self):
        self.assertEqual((await self.request("GET /nowhere HTTP/1.1\r\n"))[0], "HTTP/1.1 404 Not Found")
        self.assertEqual((await self.request("GET /api/nowhere HTTP/1.1\r\n"))[0], "HTTP/1.1 404 Not Found")
        self.assertEqual((await self.request("PUT /api/update HTTP/1.1\r\n"))[0], "HTTP/1.1 405 Method Not Allowed")
        self.assertEqual((await self.request("garbage\r\n"))[0], "HTTP/1.1 400 Bad Request")

    async def test_paths(self):
        self.assertEqual((await self.request("POST /api/active_input/B/ HTTP/1.1\r\n"))[0], "HTTP/1.1 200 OK")
        self.assertEqual((await self.request("POST /api/active_input/ HTTP/1.1\r\n"))[2], {"active_input": {"A": Config.inputs["A"]}})  # Toggles
        self.assertEqual((await self.request("POST /api/active_input/C HTTP/1.1\r\n"))[0], "HTTP/1.1 404 Not Found")
        self.assertEqual((await self.request("GET /api/active_input/A HTTP/1.1\r\n"))[0], "HTTP/1.1 405 Method Not Allowed")
        self.assertEqual((await self.request("GET /api/update/ HTTP/1.1\r\n"))[0], "HTTP/1.1 200 OK")

    async def test_errors(self):
        status, _, content = await self.request("POST /api/update HTTP/1.1\r\nAuthorization: Basic A\r\n")  # Not base64
        self.assertEqual(status, "HTTP/1.1 401 Unauthorized")
        Config.devices[0].set_active_input = None  # Not callable: the switch fails
        status, _, content = await self.request("POST /api/active_input/B HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 500 Internal Server Error")
        with patch.object(Updater, "install", side_effect=OSError("flash failure")):
            status, _, content = await self.upload(image("v2.0.0"))
        self.assertEqual((status, content), ("HTTP/1.1 500 Internal Server Error", {"message": "flash failure"}))
        status, _, _ = await self.request("GET / HTTP/1.1", b"\xff\r\n\r\n")  # Undecodable header: the connection is dropped
        self.assertEqual(status, "")

    async def test_metrics(self):
        status, _, content = await self.request("GET /metrics HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b'picokvm_info{version="v1.0.0"} 1', content)
        self.assertIn(b'usb_input_powered{input="A"}', content)

    async def test_update_needs_the_password(self):
        data = image("v2.0.0")
        Config.admin_password = None
        self.assertEqual((await self.upload(data))[0], "HTTP/1.1 403 Forbidden")
        Config.admin_password = "secret"
        for auth in ("wrong", None):
            status, headers, _ = await self.upload(data, auth)
            self.assertEqual(status, "HTTP/1.1 401 Unauthorized")
            self.assertIn('WWW-Authenticate: Basic realm="picoKVM"', headers)
        self.assertIsNone(Partition.booted)

    async def test_upload(self):
        status, _, content = await self.upload(image("v2.0.0"), extra="Expect: 100-continue\r\n")
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(content, {"message": "Restarting into v2.0.0", "version": "v2.0.0"})
        await asyncio.sleep(0)
        self.assertEqual(self.restarts, 1)
        self.assertEqual(Partition.booted, "ota_1")

    async def test_bad_uploads(self):
        status, _, content = await self.upload(image("v2.0.0", chip=0))
        self.assertEqual(status, "HTTP/1.1 400 Bad Request")
        self.assertIn("ESP32-S3", content["message"])
        status, _, _ = await self.request("POST /api/update HTTP/1.1\r\n" + credentials("secret"))
        self.assertEqual(status, "HTTP/1.1 411 Length Required")
        self.assertEqual(self.restarts, 0)

    async def test_version(self):
        status, _, content = await self.request("GET /api/update HTTP/1.1\r\n")
        self.assertEqual(content, {"version": "v1.0.0", "status": None})

    async def test_latest_release(self):
        from test_release import API, serve

        serve()
        _, _, content = await self.request("GET /api/update/latest HTTP/1.1\r\n")
        self.assertEqual(content, {"version": "v1.0.0", "latest": "v2.0.0", "update_available": True})
        self.assertEqual((await self.request("POST /api/update/latest HTTP/1.1\r\n"))[0], "HTTP/1.1 401 Unauthorized")
        status, _, content = await self.request("POST /api/update/latest HTTP/1.1\r\n" + credentials("secret"))
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(content["version"], "v2.0.0")
        ClientSession.served[API] = (500, b"{}")
        status, _, content = await self.request("GET /api/update/latest HTTP/1.1\r\n")
        self.assertEqual(status, "HTTP/1.1 502 Bad Gateway")
        self.assertIn("500", content["message"])


if __name__ == "__main__":
    unittest.main()
