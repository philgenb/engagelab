"""Publish timestamped JPEG screen frames through a standard LSL string channel."""

import base64
import ctypes
import io
import math
import sys
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from ..lsl import load_lsl


class ScreenCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScreenConfig:
    monitor: int = 1
    fps: float = 10.0
    max_width: int = 1280
    quality: int = 75

    def __post_init__(self):
        if self.monitor < 1:
            raise ValueError("--monitor must be at least 1; use --list-monitors to find displays")
        if not math.isfinite(self.fps) or not 0 < self.fps <= 60:
            raise ValueError("--fps must be greater than 0 and no greater than 60")
        if self.max_width < 0:
            raise ValueError("--max-width must be positive, or 0 to use the reported monitor width")
        if not 1 <= self.quality <= 95:
            raise ValueError("--quality must be between 1 and 95")


def capture_dependencies():
    try:
        from mss import mss
        from PIL import Image
    except ImportError as exc:
        raise ScreenCaptureError(
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
        raise ScreenCaptureError(
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
    width = monitor["width"]
    height = monitor["height"]
    scale = min(1.0, max_width / width) if max_width else 1.0
    return max(1, round(width * scale)), max(1, round(height * scale))


def encode_frame(shot, image_module, size: tuple[int, int], quality: int) -> str:
    image = image_module.frombytes("RGB", shot.size, shot.rgb)
    if image.size != size:
        image = image.resize(size, image_module.Resampling.LANCZOS)
    with io.BytesIO() as output:
        image.save(output, format="JPEG", quality=quality)
        return base64.b64encode(output.getvalue()).decode("ascii")


def create_stream_info(lsl, config: ScreenConfig, monitor: dict):
    width, height = frame_size(monitor, config.max_width)
    info = lsl.StreamInfo(
        "Screen recording",
        "ScreenRecording",
        1,
        config.fps,
        "string",
        f"engagelab-screen-{uuid4().hex}",
    )
    desc = info.desc()
    for key, value in {
        "schema": "engagelab.screen.v1",
        "encoding": "base64",
        "content_type": "image/jpeg",
        "width": width,
        "height": height,
        "jpeg_quality": config.quality,
        "monitor_index": config.monitor,
        "monitor_left": monitor["left"],
        "monitor_top": monitor["top"],
        "monitor_width": monitor["width"],
        "monitor_height": monitor["height"],
        "target_fps": config.fps,
        "timestamp_reference": "midpoint of LSL clock readings before and after screen grab",
    }.items():
        desc.append_child_value(key, str(value))
    channel = desc.append_child("channels").append_child("channel")
    channel.append_child_value("label", "jpeg_frame")
    channel.append_child_value("unit", "base64_jpeg")
    return info


def run_screen(stop: threading.Event, config: ScreenConfig) -> None:
    mss, image_module = capture_dependencies()
    check_permission()
    lsl = load_lsl()
    try:
        with mss() as capture:
            monitors = capture.monitors
            if config.monitor >= len(monitors):
                raise ScreenCaptureError(
                    f"Monitor {config.monitor} does not exist. Use screen --list-monitors."
                )
            monitor = monitors[config.monitor]
            size = frame_size(monitor, config.max_width)
            info = create_stream_info(lsl, config, monitor)
            # Bound sender buffering because image samples are much larger than sensor samples.
            outlet = lsl.StreamOutlet(info, chunk_size=1, max_buffered=2)
            print(
                f"Screen recording stream available: monitor {config.monitor}, "
                f"{size[0]} x {size[1]}, target {config.fps:g} fps. "
                "Select it in EngageLab to record. Ctrl+C stops publishing.",
                flush=True,
            )
            period = 1.0 / config.fps
            deadline = time.monotonic()
            while not stop.is_set():
                # Do not acquire desktop pixels until an inlet actually subscribes.
                if not outlet.have_consumers():
                    stop.wait(0.1)
                    deadline = time.monotonic()
                    continue
                if stop.wait(max(0.0, deadline - time.monotonic())):
                    break
                before = lsl.local_clock()
                shot = capture.grab(monitor)
                after = lsl.local_clock()
                payload = encode_frame(shot, image_module, size, config.quality)
                if stop.is_set():
                    break
                outlet.push_sample([payload], timestamp=(before + after) / 2.0)
                deadline = max(deadline + period, time.monotonic())
    except ScreenCaptureError:
        raise
    except Exception as exc:
        raise ScreenCaptureError(f"Screen capture failed: {exc}") from exc
