import asyncio
import binascii
import re
import json
import sys
import index_html
from config import Config


class WebServer:
    def __init__(self, controller, metrics_provider, updater):
        self.metrics_provider = metrics_provider
        self.controller = controller
        self.updater = updater
        self._single_page_content = index_html.content  # Generated from index.html by firmware/generate.py
        for key, value in {"hostname": Config.wireless_network["hostname"]}.items():
            self._single_page_content = self._single_page_content.replace(f"{{{{{key}}}}}", value)

    async def handle_client(self, reader, writer):
        try:
            request_line = await reader.readline()
            if request_line:  # Browsers routinely open a connection and close it without sending anything
                headers = {}
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break
                    name, _, value = line.decode().partition(":")
                    headers[name.strip().lower()] = value.strip()
                await self.route(reader, writer, request_line, headers)
                await writer.drain()
        except Exception as e:
            print("Error with client handing:", e)
            sys.print_exception(e)
        finally:
            await writer.wait_closed()

    async def route(self, reader, writer, request_line, headers):
        try:
            method, path, _ = request_line.decode("utf-8").split(" ", 2)
        except (ValueError, UnicodeError):
            self.write_response(writer, "400 Bad Request", json.dumps({"message": "Bad Request"}))
            return
        if path.startswith("/api/"):
            await self.api(reader, writer, method, path, headers)
        elif self.metrics_provider and path == "/metrics" and method == "GET":
            await self.metrics(writer)
        elif path == "/" and method == "GET":
            await self.single_page(writer)
        else:
            self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))

    def write_response(self, writer, status_code, content, content_type="application/json", headers={}):
        content = content.encode()
        extra_headers = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        writer.write(f"HTTP/1.1 {status_code}\r\nContent-Type: {content_type}\r\nContent-Length: {len(content)}\r\n{extra_headers}Connection: close\r\n\r\n")
        writer.write(content)

    async def metrics(self, writer):
        self.write_response(writer, "200 OK", self.metrics_provider.metrics(), "text/plain")

    async def single_page(self, writer):
        self.write_response(writer, "200 OK", self._single_page_content, "text/html")

    def authorized(self, writer, headers):
        """Checks the request's HTTP Basic credentials against admin_password; otherwise answers the request."""
        if not Config.admin_password:
            self.write_response(writer, "403 Forbidden", json.dumps({"message": "Set admin_password in config.json to enable this"}))
            return False
        scheme, _, credentials = headers.get("authorization", "").partition(" ")
        try:
            password = binascii.a2b_base64(credentials).decode().partition(":")[2]
        except ValueError:
            password = None
        if scheme.lower() != "basic" or password != Config.admin_password:
            self.write_response(writer, "401 Unauthorized", json.dumps({"message": "Unauthorized"}), headers={"WWW-Authenticate": 'Basic realm="picoKVM"'})
            return False
        return True

    async def upload_update(self, reader, writer, headers):
        if not self.authorized(writer, headers):
            return
        try:
            size = int(headers["content-length"])
        except (KeyError, ValueError):
            self.write_response(writer, "411 Length Required", json.dumps({"message": "Content-Length required"}))
            return
        if headers.get("expect", "").lower() == "100-continue":  # curl asks before sending a large body
            writer.write("HTTP/1.1 100 Continue\r\n\r\n")
            await writer.drain()
        await self.install_update(writer, lambda: self.updater.install(reader.read, size))

    async def install_latest_release(self):
        return await self.updater.install_release(await self.updater.latest_release(Config.update_repository))

    async def install_update(self, writer, install):
        try:
            async with self.controller.lock:  # No switch while the flash is being written
                version = await install()
        except ValueError as e:
            self.write_response(writer, "400 Bad Request", json.dumps({"message": str(e)}))
        except Exception as e:
            self.write_response(writer, "500 Internal Server Error", json.dumps({"message": str(e)}))
        else:
            self.write_response(writer, "200 OK", json.dumps({"message": f"Restarting into {version}", "version": version}))
            asyncio.create_task(self.updater.restart())

    async def api(self, reader, writer, method, path, headers):
        if method == "POST":
            match = re.match(r"^/api/active_input/?(?:/([AB])/?)?$", path)
            if match:
                try:
                    await self.controller.set_active_input(match.group(1))
                    self.write_response(writer, "200 OK", json.dumps({"active_input": {self.controller.selected_input: Config.inputs[self.controller.selected_input]}}))
                except Exception as e:
                    self.write_response(writer, "500 Internal Server Error", json.dumps({"message": str(e)}))
            elif re.match(r"^/api/update/?$", path):
                await self.upload_update(reader, writer, headers)
            elif re.match(r"^/api/update/latest/?$", path):
                if self.authorized(writer, headers):
                    await self.install_update(writer, self.install_latest_release)
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        elif method == "GET":
            if re.match(r"^/api/active_input/?$", path):
                self.write_response(writer, "200 OK", json.dumps({"active_input": {self.controller.selected_input: Config.inputs[self.controller.selected_input]}}))
            elif re.match(r"^/api/update/?$", path):
                self.write_response(writer, "200 OK", json.dumps({"version": self.updater.version, "status": self.updater.status}))
            elif re.match(r"^/api/update/latest/?$", path):
                try:
                    latest = (await self.updater.latest_release(Config.update_repository))["version"]
                    self.write_response(writer, "200 OK", json.dumps({"version": self.updater.version, "latest": latest, "update_available": latest != self.updater.version}))
                except Exception as e:
                    self.write_response(writer, "502 Bad Gateway", json.dumps({"message": str(e)}))
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        else:
            self.write_response(writer, "405 Method Not Allowed", json.dumps({"message": "Method Not Allowed"}))
