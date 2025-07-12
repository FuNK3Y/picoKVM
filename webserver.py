import re
import json
import sys
from config import Config


class WebServer:
    def __init__(self, controller, metrics_provider=None):
        self.metrics_provider = metrics_provider
        self.controller = controller
        with open("index.html", "r") as file:
            self._single_page_content = file.read()
        for key, value in {"hostname": Config.wireless_network["hostname"]}.items():
            self._single_page_content = self._single_page_content.replace(f"{{{{{key}}}}}", value)

    async def handle_client(self, reader, writer):
        try:
            request = (await reader.read(1024)).decode("utf-8")
            method, path, _ = request.split(" ", 2)
            if path.startswith("/api/"):
                await self.api(writer, method, path)
            elif self.metrics_provider and path == "/metrics" and method == "GET":
                await self.metrics(writer)
            else:
                await self.single_page(writer)
            await writer.drain()
            await writer.wait_closed()
        except Exception as e:
            print("Error with client handing:", e)
            sys.print_exception(e)

    def write_response(self, writer, status_code, content, content_type="application/json"):
        writer.write(f"HTTP/1.1 {status_code}\r\nContent-Type: {content_type}\r\nContent-Length: {len(content)}\r\nConnection: close\r\n\r\n")
        writer.write(content)

    async def metrics(self, writer):
        self.write_response(writer, "200 OK", self.metrics_provider.metrics(), "text/plain")

    async def single_page(self, writer):
        self.write_response(writer, "200 OK", self._single_page_content, "text/html")

    async def api(self, writer, method, path):
        if method == "POST":
            match = re.match(r"^/api/active_input/?(?:/([AB])/?)?$", path)
            if match:
                try:
                    await self.controller.set_active_input(match.group(1))
                    self.write_response(writer, "200 OK", json.dumps({"active_input": {self.controller.selected_input: Config.inputs[self.controller.selected_input]}}))
                except Exception as e:
                    self.write_response(writer, "500 Internal Server Error", json.dumps({"message": e}))
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        elif method == "GET":
            match = re.match(r"^/api/active_input/?$", path)
            if match:
                self.write_response(writer, "200 OK", json.dumps({"active_input": {self.controller.selected_input: Config.inputs[self.controller.selected_input]}}))
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        else:
            self.write_response(writer, "405 Method Not Allowed", json.dumps({"message": "Method Not Allowed"}))
