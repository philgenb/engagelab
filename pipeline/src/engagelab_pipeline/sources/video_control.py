"""Local session control for standalone MP4 video publishers."""

import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

SCREEN_SCHEMA = "engagelab.screen.mp4.v1"
WEBCAM_SCHEMA = "engagelab.webcam.mp4.v1"


class VideoCaptureError(RuntimeError):
    """Report failures in video capture, recording, or publisher control."""

    pass


class VideoServer(ThreadingHTTPServer):
    """Serve recording and preview requests on a local video publisher."""

    daemon_threads = True

    def __init__(self, service):
        """Bind a loopback port and generate the publisher's bearer token."""
        super().__init__(("127.0.0.1", 0), VideoHandler)
        self.service = service
        self.token = secrets.token_urlsafe(32)

    def start(self):
        """Run the HTTP server on a daemon thread and return that thread."""
        thread = threading.Thread(target=self.serve_forever, name="video-control", daemon=True)
        thread.start()
        return thread


class VideoHandler(BaseHTTPRequestHandler):
    """Handle authenticated start, stop, and preview requests."""

    def log_message(self, *_):
        """Suppress the standard HTTP request log."""
        pass

    def respond(self, status, body, content_type="application/json"):
        """Send response bytes with the content type and caching disabled."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        """Check the bearer token and send a 403 response if it is invalid."""
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {self.server.token}"):
            self.respond(403, b'{"error":"Invalid video control token"}')
            return False
        return True

    def do_GET(self):
        """Serve the latest preview, an empty response, or a capture error."""
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
        """Dispatch a bounded JSON request to start or stop a video session."""
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            if self.path == "/start":
                result = self.server.service.start(
                    body["session_id"],
                    body["stream_index"],
                    body.get("start_deadline"),
                )
            elif self.path == "/stop":
                result = self.server.service.stop(body["session_id"])
            else:
                self.respond(404, b"{}")
                return
            self.respond(200, json.dumps(result).encode())
        except (ValueError, KeyError, TypeError, OSError, VideoCaptureError) as exc:
            self.respond(409, json.dumps({"error": str(exc)}).encode())
        except Exception as exc:
            self.respond(500, json.dumps({"error": f"Video recorder failed: {exc}"}).encode())


class VideoClient:
    """Send control and preview requests to a video publisher on this host."""

    def __init__(self, port: int, token: str):
        """Configure an authenticated loopback client that bypasses proxies."""
        if not 1 <= port <= 65535 or not token or len(token) > 256:
            raise VideoCaptureError("Invalid video control metadata")
        self.base_url = f"http://127.0.0.1:{port}"
        self.token = token
        self.opener = build_opener(ProxyHandler({}))

    @classmethod
    def from_info(cls, info):
        """Build a client using control metadata in an LSL stream descriptor.

        Return None for streams without a recognized EngageLab video schema.
        Recognized publishers must advertise this host and a valid control port.
        """
        desc = info.desc()
        if desc.child_value("schema") not in {SCREEN_SCHEMA, WEBCAM_SCHEMA}:
            return None
        if desc.child_value("capture_host") != socket.gethostname():
            raise VideoCaptureError("The MP4 video source must run on the same computer")
        try:
            return cls(int(desc.child_value("control_port")), desc.child_value("control_token"))
        except ValueError as exc:
            raise VideoCaptureError("Invalid video control port") from exc

    def request(self, route, body=None, timeout=None):
        """Send an authenticated GET or JSON POST and return the response bytes.

        Convert HTTP and connection failures to VideoCaptureError for the caller.
        """
        request = Request(
            self.base_url + route,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            timeout = timeout if timeout is not None else (8 if body is not None else 2)
            with self.opener.open(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            try:
                message = json.loads(exc.read())["error"]
            except (ValueError, KeyError):
                message = str(exc)
            raise VideoCaptureError(message) from exc
        except (URLError, OSError) as exc:
            raise VideoCaptureError(
                "Video publisher is unavailable; restart the corresponding video source"
            ) from exc

    def start(self, session_id: str, stream_index: int):
        """Request MP4 capture for a session and return the publisher's recording status."""
        return json.loads(
            self.request(
                "/start",
                {
                    "session_id": session_id,
                    "stream_index": stream_index,
                    "start_deadline": time.monotonic() + 55,
                },
                timeout=60,
            )
        )

    def stop(self, session_id: str):
        """Finalize the session's MP4 and return the publisher's result."""
        return json.loads(self.request("/stop", {"session_id": session_id}))

    def preview(self):
        """Fetch the latest preview JPEG, or empty bytes if it is not available yet."""
        return self.request("/preview")
