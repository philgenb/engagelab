"""Record screen video as MP4 and publish frame indices with LSL timestamps."""

import ctypes
import math
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..lsl import load_lsl
from .video_control import SCREEN_SCHEMA, VideoCaptureError, VideoServer
from .video_service import VideoService


@dataclass(frozen=True)
class ScreenConfig:
    monitor: int = 1
    fps: float = 30.0
    max_width: int = 1280
    crf: int = 23
    data_dir: Path | None = None

    def __post_init__(self):
        if self.monitor < 1:
            raise ValueError("--monitor must be at least 1; use --list-monitors to find displays")
        if not math.isfinite(self.fps) or not 0 < self.fps <= 60:
            raise ValueError("--fps must be greater than 0 and no greater than 60")
        if self.max_width < 0 or self.max_width == 1:
            raise ValueError("--max-width must be at least 2, or 0 for the original resolution")
        if not 0 <= self.crf <= 51:
            raise ValueError("--crf must be between 0 and 51; lower values increase quality")


def capture_dependencies():
    try:
        import av  # noqa: F401
        from mss import mss
        from PIL import Image
    except ImportError as exc:
        raise VideoCaptureError(
            "Screen capture dependencies are missing. Run: pip install -e '.[screen]'"
        ) from exc
    return mss, Image


def check_permission() -> None:
    if sys.platform != "darwin":
        return
    core_graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    preflight = core_graphics.CGPreflightScreenCaptureAccess
    preflight.argtypes = []
    preflight.restype = ctypes.c_bool
    if not preflight():
        raise VideoCaptureError(
            "Screen recording permission is missing. In macOS System Settings > Privacy & "
            "Security > Screen & System Audio Recording, allow the application running Python "
            "(for example PyCharm or Terminal), then restart that application."
        )


def list_monitors() -> list[dict]:
    mss, _ = capture_dependencies()
    with mss() as capture:
        # MSS index zero represents the virtual desktop, not a single display.
        return [
            {"index": index, **monitor}
            for index, monitor in enumerate(capture.monitors)
            if index > 0
        ]


def frame_size(monitor: dict, max_width: int) -> tuple[int, int]:
    width, height = monitor["width"], monitor["height"]
    scale = min(1.0, max_width / width) if max_width else 1.0
    # H.264 with yuv420p requires even dimensions.
    return max(2, round(width * scale) // 2 * 2), max(2, round(height * scale) // 2 * 2)


def create_stream_info(lsl, config: ScreenConfig, monitor: dict, server):
    width, height = frame_size(monitor, config.max_width)
    info = lsl.StreamInfo(
        "Screen recording",
        "ScreenRecording",
        1,
        0,
        "int64",
        f"engagelab-screen-{uuid4().hex}",
    )
    desc = info.desc()
    for key, value in {
        "schema": SCREEN_SCHEMA,
        "video_format": "mp4",
        "video_codec": "h264",
        "frame_index_base": 0,
        "width": width,
        "height": height,
        "crf": config.crf,
        "monitor_index": config.monitor,
        "monitor_left": monitor["left"],
        "monitor_top": monitor["top"],
        "monitor_width": monitor["width"],
        "monitor_height": monitor["height"],
        "target_fps": config.fps,
        "capture_host": socket.gethostname(),
        "control_port": server.server_address[1],
        "control_token": server.token,
        "video_file_template": "{session_id}/stream_{stream_index:02d}.mp4",
        "timestamp_reference": "midpoint of LSL clock readings before and after screen grab",
    }.items():
        desc.append_child_value(key, str(value))
    channel = desc.append_child("channels").append_child("channel")
    channel.append_child_value("label", "frame_index")
    channel.append_child_value("unit", "index")
    return info


class ScreenService(VideoService):
    def __init__(self, config: ScreenConfig, size: tuple[int, int]):
        super().__init__(config, size, "Screen recording")

    def capture_frame(self, capture, monitor, image_module, lsl, outlet):
        with self.lock:
            if self.writer is None:
                return
            try:
                before = lsl.local_clock()
                shot = capture.grab(monitor)
                stamp = (before + lsl.local_clock()) / 2.0
                image = image_module.frombytes("RGB", shot.size, shot.rgb)
                if image.size != self.size:
                    image = image.resize(self.size, image_module.Resampling.LANCZOS)
                self.write_image(image, stamp, outlet)
            except Exception as exc:
                self.error = f"Screen recording failed: {exc}"
                self.stop(self.session_id)


def run_screen(stop: threading.Event, config: ScreenConfig) -> None:
    mss, image_module = capture_dependencies()
    check_permission()
    lsl = load_lsl()
    service = None
    server = None
    try:
        with mss() as capture:
            monitors = capture.monitors
            if config.monitor >= len(monitors):
                raise VideoCaptureError(
                    f"Monitor {config.monitor} does not exist. Use screen --list-monitors."
                )
            monitor = monitors[config.monitor]
            size = frame_size(monitor, config.max_width)
            service = ScreenService(config, size)
            server = VideoServer(service)
            server.start()
            info = create_stream_info(lsl, config, monitor, server)
            outlet = lsl.StreamOutlet(info, chunk_size=1, max_buffered=60)
            print(
                f"MP4 screen source available: monitor {config.monitor}, "
                f"{size[0]} x {size[1]}, target {config.fps:g} fps. "
                "Select it in EngageLab. Start/stop in the UI controls video recording. "
                "Ctrl+C stops the publisher.",
                flush=True,
            )
            period = 1.0 / config.fps
            deadline = time.monotonic()
            while not stop.is_set():
                if stop.wait(max(0.0, deadline - time.monotonic())):
                    break
                service.capture_frame(capture, monitor, image_module, lsl, outlet)
                deadline = max(deadline + period, time.monotonic())
    except VideoCaptureError:
        raise
    except Exception as exc:
        raise VideoCaptureError(f"Screen capture failed: {exc}") from exc
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if service and service.session_id:
            service.stop(service.session_id)
