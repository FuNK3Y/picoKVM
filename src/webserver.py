import asyncio
import binascii
import json
import sys
import index_html
from config import Config


class Request:
    def __init__(self, reader, writer, headers, argument=None):
        self.reader = reader
        self.writer = writer
        self.headers = headers
        self.argument = argument  # The <input> of /api/active_input/<input>


class WebServer:
    def __init__(self, controller, metrics_provider, updater):
        self.metrics_provider = metrics_provider
        self.controller = controller
        self.updater = updater
        self._single_page_content = index_html.content.replace("{{hostname}}", Config.wireless_network["hostname"])
        self._routes = {
            ("GET", "/"): self.single_page,
            ("GET", "/metrics"): self.metrics,
            ("GET", "/api/active_input"): self.get_active_input,
            ("POST", "/api/active_input"): self.set_active_input,  # Toggles
            ("POST", "/api/active_input/<input>"): self.set_active_input,
            ("GET", "/api/update"): self.get_update,
            ("POST", "/api/update"): self.upload_update,
            ("GET", "/api/update/latest"): self.get_latest_release,
            ("POST", "/api/update/latest"): self.install_latest_release,
        }
        self._protected = {("POST", "/api/update"), ("POST", "/api/update/latest")}  # Require admin_password

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
            self.error(writer, "400 Bad Request", "Bad Request")
            return
        path = path.rstrip("/") or "/"
        argument = None
        if path.startswith("/api/active_input/"):
            argument = path[len("/api/active_input/") :]
            path = "/api/active_input/<input>" if argument in ("A", "B") else None
        handler = self._routes.get((method, path))
        if handler is None:
            if any(route_path == path for _, route_path in self._routes):
                self.error(writer, "405 Method Not Allowed", "Method Not Allowed")
            else:
                self.error(writer, "404 Not Found", "404 Not Found")
        elif (method, path) not in self._protected or self.authorized(writer, headers):
            await handler(Request(reader, writer, headers, argument))

    def write_response(self, writer, status_code, content, content_type="application/json", headers={}):
        content = content.encode()
        extra_headers = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
        writer.write(f"HTTP/1.1 {status_code}\r\nContent-Type: {content_type}\r\nContent-Length: {len(content)}\r\n{extra_headers}Connection: close\r\n\r\n")
        writer.write(content)

    def json_response(self, writer, status_code, data, headers={}):
        self.write_response(writer, status_code, json.dumps(data), headers=headers)

    def error(self, writer, status_code, message, headers={}):
        self.json_response(writer, status_code, {"message": message}, headers)

    def authorized(self, writer, headers):
        """Checks the request's HTTP Basic credentials against admin_password; otherwise answers the request."""
        if not Config.admin_password:
            self.error(writer, "403 Forbidden", "Set admin_password in config.json to enable this")
            return False
        scheme, _, credentials = headers.get("authorization", "").partition(" ")
        try:
            password = binascii.a2b_base64(credentials).decode().partition(":")[2]
        except ValueError:
            password = None
        if scheme.lower() != "basic" or password != Config.admin_password:
            self.error(writer, "401 Unauthorized", "Unauthorized", {"WWW-Authenticate": 'Basic realm="picoKVM"'})
            return False
        return True

    async def single_page(self, request):
        self.write_response(request.writer, "200 OK", self._single_page_content, "text/html")

    async def metrics(self, request):
        self.write_response(request.writer, "200 OK", self.metrics_provider.metrics(), "text/plain")

    async def get_active_input(self, request):
        input = self.controller.selected_input
        self.json_response(request.writer, "200 OK", {"active_input": {input: Config.inputs[input]}})

    async def set_active_input(self, request):
        try:
            await self.controller.set_active_input(request.argument)
        except Exception as e:
            self.error(request.writer, "500 Internal Server Error", str(e))
        else:
            await self.get_active_input(request)

    async def get_update(self, request):
        self.json_response(request.writer, "200 OK", {"version": self.updater.version, "status": self.updater.status})

    async def upload_update(self, request):
        try:
            size = int(request.headers["content-length"])
        except (KeyError, ValueError):
            self.error(request.writer, "411 Length Required", "Content-Length required")
            return
        if request.headers.get("expect", "").lower() == "100-continue":  # curl asks before sending a large body
            request.writer.write("HTTP/1.1 100 Continue\r\n\r\n")
            await request.writer.drain()
        await self.install_update(request.writer, lambda: self.updater.install(request.reader.read, size))

    async def get_latest_release(self, request):
        try:
            latest = (await self.updater.latest_release(Config.update_repository))["version"]
        except Exception as e:
            self.error(request.writer, "502 Bad Gateway", str(e))
        else:
            self.json_response(request.writer, "200 OK", {"version": self.updater.version, "latest": latest, "update_available": latest != self.updater.version})

    async def install_latest_release(self, request):
        async def install():
            return await self.updater.install_release(await self.updater.latest_release(Config.update_repository))

        await self.install_update(request.writer, install)

    async def install_update(self, writer, install):
        try:
            async with self.controller.lock:  # No switch while the flash is being written
                version = await install()
        except ValueError as e:
            self.error(writer, "400 Bad Request", str(e))
        except Exception as e:
            self.error(writer, "500 Internal Server Error", str(e))
        else:
            self.json_response(writer, "200 OK", {"message": f"Restarting into {version}", "version": version})
            asyncio.create_task(self.updater.restart())
