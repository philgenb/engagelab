"""Record webcam MP4 video with timestamped LSL frame markers."""

import math
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..lsl import load_lsl
from .video_control import WEBCAM_SCHEMA, VideoCaptureError, VideoServer
from .video_service import VideoService


@dataclass(frozen=True)
class WebcamConfig:
    device: int = 0
    fps: float = 30.0
    width: int = 1280
    height: int = 720
    crf: int = 23
    data_dir: Path | None = None

    def __post_init__(self):
        if self.device < 0:
            raise ValueError("--device must be a non-negative camera index")
        if not math.isfinite(self.fps) or not 0 < self.fps <= 60:
            raise ValueError("--fps must be greater than 0 and no greater than 60")
        if self.width < 2 or self.height < 2 or self.width % 2 or self.height % 2:
            raise ValueError("--width and --height must be even integers of at least 2")
        if not 0 <= self.crf <= 51:
            raise ValueError("--crf must be between 0 and 51; lower values increase quality")


def capture_dependencies():
    try:
        import av  # noqa: F401
        import cv2
        from PIL import Image
    except ImportError as exc:
        raise VideoCaptureError(
            "Webcam dependencies are missing. Run: pip install -e '.[webcam]'"
        ) from exc
    return cv2, Image


def create_stream_info(lsl, config: WebcamConfig, server):
    info = lsl.StreamInfo(
        "Webcam",
        "Webcam",
        1,
        0,
        "int32",
        f"engagelab-webcam-{uuid4().hex}",
    )
    desc = info.desc()
    for key, value in {
        "schema": WEBCAM_SCHEMA,
        "video_format": "mp4",
        "video_codec": "h264",
        "frame_index_base": 0,
        "device_index": config.device,
        "width": config.width,
        "height": config.height,
        "target_fps": config.fps,
        "crf": config.crf,
        "capture_host": socket.gethostname(),
        "control_port": server.server_address[1],
        "control_token": server.token,
        "video_file_template": "{session_id}/stream_{stream_index:02d}.mp4",
        "timestamp_reference": "LSL clock immediately after successful camera read",
        "timestamp_limitations": "camera exposure and driver buffering latency are not corrected",
        "sizing": "aspect ratio preserved with black padding when needed",
    }.items():
        desc.append_child_value(key, str(value))
    channel = desc.append_child("channels").append_child("channel")
    channel.append_child_value("label", "frame_index")
    channel.append_child_value("unit", "index")
    return info


class WebcamService(VideoService):
    def __init__(self, config: WebcamConfig, cv2, image_module, lsl):
        super().__init__(config, (config.width, config.height), "Webcam")
        self.cv2 = cv2
        self.image_module = image_module
        self.lsl = lsl
        self.camera = None
        self.pending = None

    def open_capture(self):
        # Open on session start, so discovery does not activate the camera.
        camera = self.cv2.VideoCapture(self.config.device)
        self.camera = camera
        try:
            if not camera.isOpened():
                raise VideoCaptureError(
                    f"Cannot open webcam {self.config.device}. Check --device, close other "
                    "camera applications and allow camera access for PyCharm or Terminal "
                    "in system privacy settings, then restart that application."
                )
            camera.set(self.cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            camera.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            camera.set(self.cv2.CAP_PROP_FPS, self.config.fps)
            # Some backends ignore this setting; timestamps do not remove driver latency.
            camera.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = camera.read()
            stamp = self.lsl.local_clock()
            if not ok or frame is None:
                raise VideoCaptureError("Webcam opened but did not provide a frame")
            self.pending = (frame, stamp)
        except Exception:
            self.close_capture()
            raise

    def close_capture(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.pending = None

    def capture_frame(self, outlet):
        with self.lock:
            if self.writer is None:
                return
            try:
                if self.pending is not None:
                    frame, stamp = self.pending
                    self.pending = None
                else:
                    ok, frame = self.camera.read()
                    stamp = self.lsl.local_clock()
                    if not ok or frame is None:
                        raise VideoCaptureError("Webcam stopped delivering frames or disconnected")
                image = self.image_module.fromarray(
                    self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
                )
                if image.size != self.size:
                    image.thumbnail(self.size, self.image_module.Resampling.LANCZOS)
                    canvas = self.image_module.new("RGB", self.size, "black")
                    canvas.paste(
                        image,
                        ((self.size[0] - image.width) // 2, (self.size[1] - image.height) // 2),
                    )
                    image = canvas
                self.write_image(image, stamp, outlet)
            except Exception as exc:
                self.error = f"Webcam recording failed: {exc}"
                self.stop(self.session_id)


def run_webcam(stop: threading.Event, config: WebcamConfig) -> None:
    cv2, image_module = capture_dependencies()
    lsl = load_lsl()
    service = WebcamService(config, cv2, image_module, lsl)
    server = VideoServer(service)
    try:
        server.start()
        info = create_stream_info(lsl, config, server)
        outlet = lsl.StreamOutlet(info, chunk_size=1, max_buffered=60)
        print(
            f"Webcam source available: camera {config.device}, "
            f"{config.width} x {config.height}, target {config.fps:g} fps. "
            "Select Webcam in EngageLab. The camera opens on session start and closes on stop. "
            "Ctrl+C stops the publisher.",
            flush=True,
        )
        period = 1.0 / config.fps
        deadline = time.monotonic()
        while not stop.is_set():
            if stop.wait(max(0.0, deadline - time.monotonic())):
                break
            service.capture_frame(outlet)
            deadline = max(deadline + period, time.monotonic())
    except VideoCaptureError:
        raise
    except Exception as exc:
        raise VideoCaptureError(f"Webcam publisher failed: {exc}") from exc
    finally:
        server.shutdown()
        server.server_close()
        if service.session_id:
            service.stop(service.session_id)
        else:
            service.close_capture()
