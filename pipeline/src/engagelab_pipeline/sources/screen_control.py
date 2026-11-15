"""Local session control for the standalone screen publisher."""

import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

SCHEMA = "engagelab.screen.mp4.v1"


class ScreenCaptureError(RuntimeError):
    pass


class ScreenServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, service):
        super().__init__(("127.0.0.1", 0), ScreenHandler)
        self.service = service
        self.token = secrets.token_urlsafe(32)

    def start(self):
        thread = threading.Thread(target=self.serve_forever, name="screen-control", daemon=True)
        thread.start()
        return thread


class ScreenHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {self.server.token}"):
            self.respond(403, b'{"error":"Invalid screen control token"}')
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != "/preview":
            self.respond(404, b"{}")
            return
        with self.server.service.lock:
            preview = self.server.service.preview
            error = self.server.service.error
        if error:
            self.respond(503, json.dumps({"error": error}).encode())
        elif preview is None:
            self.respond(204, b"")
        else:
            self.respond(200, preview, "image/jpeg")

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            if self.path == "/start":
                result = self.server.service.start(body["session_id"], body["stream_index"])
            elif self.path == "/stop":
                result = self.server.service.stop(body["session_id"])
            else:
                self.respond(404, b"{}")
                return
            self.respond(200, json.dumps(result).encode())
        except (ValueError, KeyError, TypeError, OSError, ScreenCaptureError) as exc:
            self.respond(409, json.dumps({"error": str(exc)}).encode())
        except Exception as exc:
            self.respond(500, json.dumps({"error": f"Video recorder failed: {exc}"}).encode())


class ScreenClient:
    def __init__(self, port: int, token: str):
        if not 1 <= port <= 65535 or not token or len(token) > 256:
            raise ScreenCaptureError("Invalid screen control metadata")
        self.base_url = f"http://127.0.0.1:{port}"
        self.token = token
        self.opener = build_opener(ProxyHandler({}))

    @classmethod
    def from_info(cls, info):
        desc = info.desc()
        if desc.child_value("schema") != SCHEMA:
            return None
        if desc.child_value("capture_host") != socket.gethostname():
            raise ScreenCaptureError("The MP4 screen source must run on the same computer")
        try:
            return cls(int(desc.child_value("control_port")), desc.child_value("control_token"))
        except ValueError as exc:
            raise ScreenCaptureError("Invalid screen control port") from exc

    def request(self, route, body=None):
        request = Request(
            self.base_url + route,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=8 if body is not None else 2) as response:
                return response.read()
        except HTTPError as exc:
            try:
                message = json.loads(exc.read())["error"]
            except (ValueError, KeyError):
                message = str(exc)
            raise ScreenCaptureError(message) from exc
        except (URLError, OSError) as exc:
            raise ScreenCaptureError(
                "Screen publisher is unavailable; restart Screen Stream"
            ) from exc

    def start(self, session_id: str, stream_index: int):
        return json.loads(
            self.request(
                "/start",
                {
                    "session_id": session_id,
                    "stream_index": stream_index,
                },
            )
        )

    def stop(self, session_id: str):
        return json.loads(self.request("/stop", {"session_id": session_id}))

    def preview(self):
        return self.request("/preview")
