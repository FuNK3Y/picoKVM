import re, json
from controller import Controller

class WebServer:
    def __init__(self):
        self.controller=Controller()
    
    def write_response(self, writer, status_code, content, content_type="application/json"):
        writer.write(f"HTTP/1.1 {status_code}\r\nContent-Type: {content_type}\r\nContent-Length: {len(content)}\r\nConnection: close\r\n\r\n")
        writer.write(content)
    
    async def single_page(self, writer):
        with open("index.html", "r") as file:
            content=file.read()
        self.write_response(writer, "200 OK", content, "text/html")
    
    async def api(self, writer, method, path):
        if method == "POST":
            match = re.match(r"^/api/set_active_input/?(?:/([AB])/?)?$", path)
            if  match:
                try:
                    await self.controller.set_input(match.group(1))
                    self.write_response(writer, "200 OK", json.dumps({"active_input": self.controller.selected_input}))
                except Exception as e:
                    self.write_response(writer, "500 Internal Server Error", json.dumps({"message": e}))
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        elif method == "GET":
            match = re.match(r"^/api/get_active_input/?$", path)
            if match:
                self.write_response(writer, "200 OK", json.dumps({"active_input": self.controller.selected_input}))
            else:
                self.write_response(writer, "404 Not Found", json.dumps({"message": "404 Not Found"}))
        else:
            self.write_response(writer, "405 Method Not Allowed", json.dumps({"message": "Method Not Allowed"}))