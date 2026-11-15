"""Shared session lifecycle, MP4 output and preview for video sources."""

import io
import threading
import time

from ..storage import SessionStore
from .video import Mp4Recording
from .video_control import VideoCaptureError


class VideoService:
    def __init__(self, config, size: tuple[int, int], source_name: str):
        self.source_name = source_name
        self.config = config
        self.size = size
        self.store = SessionStore(config.data_dir)
        self.lock = threading.RLock()
        self.writer = None
        self.session_id = None
        self.last_session_id = None
        self.result = None
        self.preview = None
        self.next_preview = 0.0
        self.error = None

    def start(
        self, session_id: str, stream_index: int, start_deadline: float | None = None
    ) -> dict:
        with self.lock:
            if self.writer:
                raise VideoCaptureError(
                    f"{self.source_name} source is already recording another session"
                )
            if type(stream_index) is not int or not 0 <= stream_index < 32:
                raise ValueError("Invalid stream index")
            directory = self.store.directory(session_id)
            if not (directory / "session.json").is_file():
                raise VideoCaptureError(
                    "Session directory not found. Video source and backend must use the same "
                    "ENGAGELAB_DATA_DIR (or --data-dir)."
                )
            path = directory / f"stream_{stream_index:02d}.mp4"
            self.open_capture()
            try:
                # A delayed OS permission prompt must not leave an abandoned recording running.
                if start_deadline is not None and time.monotonic() > start_deadline:
                    raise VideoCaptureError(
                        "Video start timed out; retry after granting permission"
                    )
                self.writer = Mp4Recording(path, self.size, self.config.fps, self.config.crf)
            except Exception:
                self.close_capture()
                raise
            self.session_id = session_id
            self.preview = None
            self.error = None
            self.next_preview = 0.0
            self.result = None
            print(f"Recording MP4: {path}", flush=True)
            return {"video_file": path.name, "video_status": "recording", "video_format": "mp4"}

    def stop(self, session_id: str) -> dict:
        with self.lock:
            if self.session_id != session_id:
                if self.last_session_id == session_id and self.result:
                    return self.result
                raise VideoCaptureError(f"This session is not recording on {self.source_name}")
            try:
                self.result = self.writer.close()
            except Exception as exc:
                self.error = f"Could not finalize MP4: {exc}"
                self.result = {"video_status": "failed"}
            if self.error:
                self.result.update(video_status="failed", video_error=self.error)
            self.close_capture()
            self.last_session_id = session_id
            self.writer = None
            self.session_id = None
            self.preview = None
            print(f"MP4 recording stopped: {self.result}", flush=True)
            return self.result

    def open_capture(self):
        pass

    def close_capture(self):
        pass

    def write_image(self, image, stamp: float, outlet):
        index = self.writer.write(image, stamp)
        outlet.push_sample([index], timestamp=stamp)
        if time.monotonic() >= self.next_preview:
            thumbnail = image.copy()
            thumbnail.thumbnail((960, 540))
            with io.BytesIO() as output:
                thumbnail.save(output, format="JPEG", quality=65)
                self.preview = output.getvalue()
            self.next_preview = time.monotonic() + 0.2
