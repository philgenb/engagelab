"""Record selected LSL streams without discarding their original timestamps."""

import copy
import json
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import IO

from .lsl import describe, load_lsl
from .sources.video_control import VideoCaptureError, VideoClient
from .storage import SessionStore, utc_now
from .xdf import LabRecorder, XDFUnavailable, load_recording, session_samples


class RecordingConflict(RuntimeError):
    pass


def append_json(file: IO[str], value: dict) -> None:
    file.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")
    file.flush()


@dataclass
class Source:
    inlet: object
    metadata: dict
    correction: float
    next_correction: float
    video: VideoClient | None = None


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
        self._sources: list[Source] = []
        self._markers = None
        self._xdf = None

    def delete_session(self, session_id: str) -> None:
        # Share the start/stop lock so a recording cannot start while it is being deleted.
        with self._lock:
            session = self.store.get(session_id)
            current = self._session and self._session["id"] == session_id
            if session["status"] == "recording" or (
                current and self._thread and self._thread.is_alive()
            ):
                raise RecordingConflict("Stop the recording before deleting this session")
            self.store.delete(session_id)
            if current:
                self._session = None
                self._sources = []
                self._thread = None
                self._lsl = None
                self._stop_at = None

    def preview(self, session_id: str, stream_index: int) -> bytes:
        with self._lock:
            if (
                not self._session
                or self._session["id"] != session_id
                or self._session["status"] != "recording"
            ):
                raise RecordingConflict("This session is not recording")
            if not 0 <= stream_index < len(self._sources):
                raise ValueError("Video source not found")
            source = self._sources[stream_index]
            client = source.video
            if client is None:
                raise ValueError("This source has no live preview")
            last_sample = source.metadata["last_sample_local"]
            if self._lsl.local_clock() - (last_sample or self._session["started_lsl"]) > 5:
                raise VideoCaptureError(f"No video frames received from {source.metadata['name']}")
        return client.preview()

    def snapshot(self) -> dict | None:
        with self._lock:
            session = copy.deepcopy(self._session)
            if session and session["status"] == "recording":
                for stream in session["streams"]:
                    last = stream.get("last_sample_local") or session["started_lsl"]
                    if stream.get("video_format") and self._lsl.local_clock() - last > 5:
                        stream["video_warning"] = (
                            f"No video frames received from {stream['name']} for more than "
                            "5 seconds. Check the corresponding video source."
                        )
            return session

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
                events = resources.enter_context(
                    (directory / "events.jsonl").open("x", encoding="utf-8")
                )
                sources = []
                for index, uid in enumerate(stream_uids):
                    inlet = lsl.StreamInlet(available[uid], max_buflen=60, processing_flags=0)
                    resources.callback(inlet.close_stream)
                    inlet.open_stream(timeout=2.0)
                    info = inlet.info(timeout=2.0)
                    if info.channel_format() == lsl.cf_int64:
                        raise XDFUnavailable(
                            f"{info.name()} uses int64, which LabRecorderCLI does not support. "
                            "Restart the updated screen/webcam publisher, "
                            "or publish int32/double64."
                        )
                    correction = inlet.time_correction(timeout=2.0)
                    filename = "recording.xdf"
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
                    now = lsl.local_clock()
                    sources.append(
                        Source(
                            inlet,
                            metadata,
                            correction,
                            now + 5.0,
                            VideoClient.from_info(info),
                        )
                    )
                marker_source = f"engagelab-session-{session_id}"
                marker_info = lsl.StreamInfo(
                    "EngageLab session", "Markers", 1, 0, "string", marker_source
                )
                marker_info.desc().append_child_value("session_id", session_id)
                marker_info.desc().append_child_value("session_name", session["name"])
                marker_info.desc().append_child_value("game", session["game"])
                marker_info.desc().append_child_value(
                    "video_files",
                    json.dumps(
                        [
                            {
                                "stream_uid": source.metadata["uid"],
                                "file": f"stream_{index:02d}.mp4",
                                "timing_file": f"stream_{index:02d}.frames.jsonl",
                            }
                            for index, source in enumerate(sources)
                            if source.video
                        ]
                    ),
                )
                self._markers = lsl.StreamOutlet(marker_info)
                self._xdf = LabRecorder(directory / "recording.xdf", directory / "labrecorder.log")
                resources.callback(self._xdf.close)
                self._xdf.start([*stream_uids, self._markers.get_info().uid()], self._markers)
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
                        "schema_version": 2,
                        "recording_format": "xdf",
                        "xdf_file": "recording.xdf",
                        "session_marker_source_id": marker_source,
                        "timestamp_policy": (
                            "raw LSL timestamps and clock offsets in XDF; "
                            "pyxdf offline clock synchronization"
                        ),
                        "non_finite_values": "preserved in XDF",
                    }
                )
                self._markers.push_sample(["start"], timestamp=start)
                self._session = session
                self._lsl = lsl
                self._sources = sources
                self._stop_at = None
                self._stop.clear()
                for index, source in enumerate(sources):
                    if source.video:
                        # Also stop the source if a start request succeeds but its response is lost.
                        source.metadata.update(
                            video_file=f"stream_{index:02d}.mp4",
                            video_format="mp4",
                            video_timing_file=f"stream_{index:02d}.frames.jsonl",
                            video_status="recording",
                        )
                        resources.callback(self._finish_video, source, session_id, start)
                        source.video.start(session_id, index)
                self.store.save(session)
                append_json(events, {"event": "recording_started", "local_lsl": start})
                self._thread = threading.Thread(
                    target=self._run,
                    args=(sources, events, resources),
                    name="engagelab-recorder",
                    daemon=False,
                )
                self._thread.start()
            except Exception as exc:
                try:
                    resources.close()
                except Exception as cleanup:
                    exc.add_note(f"Recording cleanup failed: {cleanup}")
                self._markers = None
                session.update({"status": "failed", "error": str(exc), "ended_at": utc_now()})
                self._session = session
                self.store.save(session)
                raise
            return copy.deepcopy(session)

    def _finish_video(self, source: Source, session_id: str, start: float) -> None:
        if source.metadata.get("video_status") != "recording":
            return
        try:
            result = source.video.stop(session_id)
            # Paths are fixed by the recorder, not accepted from the control response.
            allowed = {
                "video_frame_count",
                "video_first_frame_lsl",
                "video_status",
                "video_error",
            }
            source.metadata.update({key: value for key, value in result.items() if key in allowed})
            first = source.metadata.get("video_first_frame_lsl")
            if first is not None and "video_first_frame_session_seconds" not in source.metadata:
                source.metadata["video_first_frame_session_seconds"] = (
                    first + source.correction - start
                )
            source.metadata.setdefault(
                "video_timing_file",
                source.metadata.get("metadata_file", source.metadata["data_file"]).rsplit(".", 1)[0]
                + ".frames.jsonl",
            )
            if source.metadata["video_status"] == "failed":
                source.metadata.setdefault("video_error", "MP4 recording failed")
        except Exception as exc:
            source.metadata.update(video_status="failed", video_error=str(exc))

    def _collect(self, source: Source) -> int:
        samples, timestamps = source.inlet.pull_chunk(timeout=0.0, max_samples=1024)
        if not timestamps:
            return 0
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
            with self._lock:
                if source.video and "video_first_frame_session_seconds" not in source.metadata:
                    for sample, _stamp, local in rows:
                        if sample[0] == 0:
                            source.metadata["video_first_frame_session_seconds"] = local - start
                            break
                source.metadata["sample_count"] += len(rows)
                source.metadata["last_sample_local"] = rows[-1][2]
        return len(timestamps)

    def _run(self, sources, events, resources) -> None:
        error = None
        try:
            while not self._stop.is_set():
                self._xdf.check()
                for source in sources:
                    now = self._lsl.local_clock()
                    if now >= source.next_correction:
                        try:
                            source.correction = source.inlet.time_correction(timeout=0.05)
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
                    if self._stop_at is None:
                        self._stop_at = self._lsl.local_clock()
                        self._markers.push_sample(["stop"], timestamp=self._stop_at)
                for source in sources:
                    if source.video:
                        self._finish_video(
                            source, self._session["id"], self._session["started_lsl"]
                        )
                        if source.metadata.get("video_error"):
                            error = source.metadata["video_error"]
                try:
                    self._xdf.close()
                    streams, xdf_start, xdf_stop = load_recording(
                        self.store.directory(self._session["id"]), self._session
                    )
                    with self._lock:
                        for source in sources:
                            _, times = session_samples(
                                streams[source.metadata["uid"]], xdf_start, xdf_stop
                            )
                            source.metadata["sample_count"] = len(times)
                            source.metadata["last_sample_local"] = (
                                float(times[-1] + xdf_start) if len(times) else None
                            )
                        self._session["xdf_started_lsl"] = xdf_start
                        self._session["xdf_ended_lsl"] = xdf_stop
                except Exception as exc:
                    error = str(exc)
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
                            "duration_seconds": self._session.get("xdf_ended_lsl", end)
                            - self._session.get("xdf_started_lsl", self._session["started_lsl"]),
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
                self._markers = None

    def stop(self) -> dict:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                raise RecordingConflict("No recording is running")
            if self._stop_at is None:
                self._stop_at = self._lsl.local_clock()
                self._markers.push_sample(["stop"], timestamp=self._stop_at)
            self._stop.set()
            thread = self._thread
        thread.join(timeout=45.0)
        if thread.is_alive():
            raise RuntimeError("Recorder is still shutting down")
        return self.snapshot()

    def close(self) -> None:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
        if running:
            self.stop()
