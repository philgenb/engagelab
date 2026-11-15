"""Record selected LSL streams without discarding their original timestamps."""

import copy
import json
import math
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import IO

from .lsl import describe, load_lsl
from .storage import SessionStore, utc_now


class RecordingConflict(RuntimeError):
    pass


def clean_values(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (list, tuple)):
        return [clean_values(item) for item in value]
    return value


def append_json(file: IO[str], value: dict) -> None:
    file.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")
    file.flush()


@dataclass
class Source:
    inlet: object
    metadata: dict
    file: IO[str]
    correction: float
    next_correction: float


class Recorder:
    """A single recording coordinator shared by the CLI or one API process."""

    def __init__(self, store: SessionStore):
        self.store = store
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session: dict | None = None
        self._stop_at: float | None = None
        self._lsl = None

    def snapshot(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._session)

    def start(self, session_id: str, stream_uids: list[str]) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RecordingConflict("Another session is already recording")
            if not stream_uids or len(stream_uids) != len(set(stream_uids)):
                raise ValueError("Select at least one stream, without duplicates")
            session = self.store.get(session_id)
            if session["status"] != "created":
                raise RecordingConflict("Only a new session can be started")
            lsl = load_lsl()
            available = {info.uid(): info for info in lsl.resolve_streams(wait_time=1.0)}
            missing = set(stream_uids) - available.keys()
            if missing:
                raise ValueError("Selected streams disappeared; refresh the stream list")
            resources = ExitStack()
            try:
                directory = self.store.directory(session_id)
                offsets = resources.enter_context(
                    (directory / "clock_offsets.jsonl").open("x", encoding="utf-8")
                )
                events = resources.enter_context(
                    (directory / "events.jsonl").open("x", encoding="utf-8")
                )
                sources = []
                for index, uid in enumerate(stream_uids):
                    inlet = lsl.StreamInlet(available[uid], max_buflen=60, processing_flags=0)
                    resources.callback(inlet.close_stream)
                    inlet.open_stream(timeout=2.0)
                    info = inlet.info(timeout=2.0)
                    correction = inlet.time_correction(timeout=2.0)
                    filename = f"stream_{index:02d}.jsonl"
                    metadata = {
                        **describe(info),
                        "data_file": filename,
                        "metadata_file": f"stream_{index:02d}.xml",
                        "sample_count": 0,
                        "status": "recording",
                        "last_sample_local": None,
                    }
                    (directory / metadata["metadata_file"]).write_text(
                        info.as_xml(), encoding="utf-8"
                    )
                    data = resources.enter_context(
                        (directory / filename).open("x", encoding="utf-8")
                    )
                    now = lsl.local_clock()
                    append_json(
                        offsets,
                        {"stream_uid": uid, "measured_at_lsl": now, "offset_seconds": correction},
                    )
                    sources.append(Source(inlet, metadata, data, correction, now + 5.0))
                # Discard pre-session buffering; timestamps define the actual recording boundary.
                for source in sources:
                    source.inlet.flush()
                start = lsl.local_clock()
                session.update(
                    {
                        "status": "recording",
                        "started_at": utc_now(),
                        "started_lsl": start,
                        "streams": [s.metadata for s in sources],
                        "timestamp_policy": "raw LSL + separately logged clock offsets",
                        "non_finite_values": "stored as null",
                    }
                )
                self._session = session
                self._lsl = lsl
                self._stop_at = None
                self._stop.clear()
                self.store.save(session)
                append_json(events, {"event": "recording_started", "local_lsl": start})
                self._thread = threading.Thread(
                    target=self._run,
                    args=(sources, offsets, events, resources),
                    name="engagelab-recorder",
                    daemon=False,
                )
                self._thread.start()
            except Exception as exc:
                resources.close()
                session.update({"status": "failed", "error": str(exc), "ended_at": utc_now()})
                self._session = session
                self.store.save(session)
                raise
            return copy.deepcopy(session)

    def _collect(self, source: Source) -> int:
        samples, timestamps = source.inlet.pull_chunk(timeout=0.0, max_samples=1024)
        if not timestamps:
            return 0
        received = self._lsl.local_clock()
        with self._lock:
            start = self._session["started_lsl"]
            cutoff = self._stop_at
        rows = [
            (sample, stamp, stamp + source.correction)
            for sample, stamp in zip(samples, timestamps, strict=True)
            if stamp + source.correction >= start
            and (cutoff is None or stamp + source.correction < cutoff)
        ]
        if rows:
            append_json(
                source.file,
                {
                    "received_lsl": received,
                    "clock_offset_seconds": source.correction,
                    "timestamps_lsl": [row[1] for row in rows],
                    "timestamps_local": [row[2] for row in rows],
                    "session_seconds": [row[2] - start for row in rows],
                    "values": [clean_values(row[0]) for row in rows],
                },
            )
            with self._lock:
                source.metadata["sample_count"] += len(rows)
                source.metadata["last_sample_local"] = rows[-1][2]
        return len(timestamps)

    def _run(self, sources, offsets, events, resources) -> None:
        error = None
        try:
            while not self._stop.is_set():
                for source in sources:
                    now = self._lsl.local_clock()
                    if now >= source.next_correction:
                        try:
                            source.correction = source.inlet.time_correction(timeout=0.05)
                            append_json(
                                offsets,
                                {
                                    "stream_uid": source.metadata["uid"],
                                    "measured_at_lsl": now,
                                    "offset_seconds": source.correction,
                                },
                            )
                        except self._lsl.TimeoutError:
                            append_json(
                                events,
                                {
                                    "event": "clock_correction_timeout",
                                    "stream_uid": source.metadata["uid"],
                                    "local_lsl": now,
                                },
                            )
                        source.next_correction = now + 5.0
                    for _ in range(4):
                        if not self._collect(source):
                            break
                self._stop.wait(0.01)
            # Drain queued samples up to the stop boundary, without following a live stream forever.
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if not sum(self._collect(source) for source in sources):
                    break
        except Exception as exc:
            error = str(exc)
        finally:
            try:
                with self._lock:
                    end = self._stop_at or self._lsl.local_clock()
                    for source in sources:
                        source.metadata["status"] = "failed" if error else "completed"
                        if not source.metadata["sample_count"]:
                            source.metadata["status"] = "empty"
                    self._session.update(
                        {
                            "status": "failed" if error else "completed",
                            "ended_at": utc_now(),
                            "ended_lsl": end,
                            "duration_seconds": end - self._session["started_lsl"],
                        }
                    )
                    if error:
                        self._session["error"] = error
                    append_json(
                        events, {"event": "recording_stopped", "local_lsl": end, "error": error}
                    )
                    self.store.save(self._session)
            finally:
                resources.close()

    def stop(self) -> dict:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                raise RecordingConflict("No recording is running")
            if self._stop_at is None:
                self._stop_at = self._lsl.local_clock()
            self._stop.set()
            thread = self._thread
        thread.join(timeout=10.0)
        if thread.is_alive():
            raise RuntimeError("Recorder is still shutting down")
        return self.snapshot()

    def close(self) -> None:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
        if running:
            self.stop()
