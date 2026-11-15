"""Write H.264 MP4 video and an exact per-frame LSL timestamp mapping."""

import json
from fractions import Fraction
from pathlib import Path

TIME_BASE = Fraction(1, 1_000_000)


class Mp4Recording:
    def __init__(self, path: Path, size: tuple[int, int], fps: float, crf: int):
        import av

        self.path = path
        self.timing_path = path.with_suffix(".frames.jsonl")
        if path.exists() or self.timing_path.exists():
            raise FileExistsError(f"Recording already exists: {path}")
        self.first_timestamp = None
        self.frame_count = 0
        self.last_pts = -1
        self.container = av.open(
            str(path), mode="w", format="mp4", options={"movflags": "+faststart"}
        )
        try:
            self.stream = self.container.add_stream("libx264", rate=Fraction(str(fps)))
            self.stream.width, self.stream.height = size
            self.stream.pix_fmt = "yuv420p"
            self.stream.time_base = TIME_BASE
            self.stream.codec_context.time_base = TIME_BASE
            self.stream.options = {"crf": str(crf), "preset": "veryfast", "bf": "0"}
            self.timing = self.timing_path.open("x", encoding="utf-8")
        except Exception:
            self.container.close()
            raise

    def write(self, image, timestamp: float) -> int:
        import av

        first = timestamp if self.first_timestamp is None else self.first_timestamp
        pts = max(self.last_pts + 1, round((timestamp - first) / TIME_BASE))
        frame = av.VideoFrame.from_image(image)
        frame.pts = pts
        frame.time_base = TIME_BASE
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        index = self.frame_count
        self.timing.write(
            json.dumps(
                {
                    "frame_index": index,
                    "timestamp_lsl": timestamp,
                    "video_seconds": float(pts * TIME_BASE),
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        self.timing.flush()
        self.first_timestamp = first
        self.last_pts = pts
        self.frame_count += 1
        return index

    def close(self) -> dict:
        try:
            for packet in self.stream.encode():
                self.container.mux(packet)
        finally:
            try:
                self.container.close()
            finally:
                self.timing.close()
        return {
            "video_file": self.path.name,
            "video_timing_file": self.timing_path.name,
            "video_frame_count": self.frame_count,
            "video_first_frame_lsl": self.first_timestamp,
            "video_status": "ready" if self.frame_count else "empty",
        }
