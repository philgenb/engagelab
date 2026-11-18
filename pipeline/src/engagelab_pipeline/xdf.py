"""Run the official LabRecorder CLI and import synchronized XDF recordings."""

import os
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyxdf

ROOT = Path(__file__).resolve().parents[3]


class XDFUnavailable(RuntimeError):
    pass


def find_labrecorder() -> Path:
    configured = os.environ.get("ENGAGELAB_LABRECORDER")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()
        raise XDFUnavailable("ENGAGELAB_LABRECORDER does not point to a LabRecorderCLI executable")
    suffix = ".exe" if os.name == "nt" else ""
    candidates = [
        ROOT / ".tools" / "labrecorder" / f"LabRecorderCLI{suffix}",
        ROOT / ".tools" / "labrecorder" / "bin" / f"LabRecorderCLI{suffix}",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    executable = shutil.which("LabRecorderCLI")
    if executable:
        return Path(executable)
    raise XDFUnavailable(
        "LabRecorderCLI is missing. Run python scripts/setup_labrecorder.py after installing "
        ".[xdf-build], or set ENGAGELAB_LABRECORDER to an existing LabRecorderCLI executable."
    )


class LabRecorder:
    def __init__(self, path: Path, log_path: Path):
        self.executable = find_labrecorder()
        self.path = path.resolve()
        self.log_path = log_path
        self.process = None
        self.log = None
        self.next_log_check = 0.0

    def start(self, uids: list[str], marker_outlet, timeout: float = 20):
        if self.path.exists():
            raise FileExistsError(f"XDF recording already exists: {self.path}")
        if any(not uid or '"' in uid or "'" in uid for uid in uids):
            raise ValueError("Invalid LSL stream UID")
        self.log = self.log_path.open("xb")
        try:
            self.process = subprocess.Popen(
                [str(self.executable), str(self.path), *[f"uid='{uid}'" for uid in uids]],
                stdin=subprocess.PIPE,
                stdout=self.log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self.check()
                # LabRecorder enters this phase only after all selected headers are received.
                output = self.log_path.read_text(encoding="utf-8", errors="replace")
                if (
                    output.count("Started data collection for stream ") >= len(uids)
                    and marker_outlet.have_consumers()
                ):
                    return
                marker_outlet.push_sample(["prepare"])
                threading.Event().wait(0.05)
            raise XDFUnavailable(
                "LabRecorder did not connect to all selected streams; see labrecorder.log"
            )
        except Exception:
            self.close()
            raise

    def check(self):
        if self.process is not None and self.process.poll() is not None:
            raise XDFUnavailable(
                f"LabRecorder exited with code {self.process.returncode}; see labrecorder.log"
            )
        if time.monotonic() >= self.next_log_check:
            self.check_log()
            self.next_log_check = time.monotonic() + 1.0

    def check_log(self):
        if not self.log_path.exists():
            return
        output = self.log_path.read_text(encoding="utf-8", errors="replace")
        if (
            "Error in the record_from_streaminfo thread:" in output
            or "Error in transfer thread:" in output
        ):
            raise XDFUnavailable(
                "LabRecorder could not record a selected stream; see labrecorder.log"
            )

    def close(self):
        if self.process is None:
            if self.log:
                self.log.close()
            return
        try:
            if self.process.poll() is None:
                # The CLI pulls chunks every 500 ms; leave time to receive the final stop marker.
                threading.Event().wait(0.7)
                try:
                    self.process.stdin.write(b"\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    self.process.wait(timeout=30)
                except subprocess.TimeoutExpired as exc:
                    self.process.kill()
                    self.process.wait()
                    raise XDFUnavailable(
                        "LabRecorder could not finalize the XDF recording"
                    ) from exc
            if self.process.returncode != 0:
                raise XDFUnavailable(
                    f"LabRecorder exited with code {self.process.returncode}; see labrecorder.log"
                )
            self.check_log()
        finally:
            self.process.stdin.close()
            self.log.close()
            self.process = None


def info_value(stream: dict, name: str):
    return stream["info"].get(name, [None])[0]


@lru_cache(maxsize=2)
def _load_xdf(path: str, modified: int, size: int):
    # Preserve acquisition intervals. Clock correction remains enabled for every stream.
    streams, _ = pyxdf.load_xdf(path, synchronize_clocks=True, dejitter_timestamps=False)
    return streams


def load_recording(directory: Path, session: dict) -> tuple[dict[str, dict], float, float]:
    directory = directory.resolve()
    path = directory / "recording.xdf"
    if not path.is_file() or path.resolve().parent != directory:
        raise FileNotFoundError("XDF recording is missing")
    stat = path.stat()
    streams = _load_xdf(str(path), stat.st_mtime_ns, stat.st_size)
    by_uid = {info_value(stream, "uid"): stream for stream in streams}
    markers = next(
        (
            stream
            for stream in streams
            if info_value(stream, "source_id") == session["session_marker_source_id"]
        ),
        None,
    )
    if markers is None:
        raise ValueError("XDF session marker stream is missing")
    boundaries = {}
    for value, stamp in zip(markers["time_series"], markers["time_stamps"], strict=True):
        if value[0] in {"start", "stop"}:
            boundaries.setdefault(value[0], float(stamp))
    if not {"start", "stop"} <= boundaries.keys() or boundaries["stop"] < boundaries["start"]:
        raise ValueError("XDF session boundaries are incomplete")
    for stream in session["streams"]:
        if stream["uid"] not in by_uid:
            raise ValueError(f"Recorded stream is missing from XDF: {stream['name']}")
    return by_uid, boundaries["start"], boundaries["stop"]


def session_samples(stream: dict, start: float, stop: float):
    timestamps = stream["time_stamps"]
    mask = (timestamps >= start) & (timestamps < stop)
    values = stream["time_series"]
    if isinstance(values, list):
        values = [value for value, include in zip(values, mask, strict=True) if include]
    else:
        values = values[mask]
    return values, np.asarray(timestamps[mask] - start)
