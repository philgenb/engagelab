"""Join MP4 frame presentation times to the received, clock-corrected LSL markers."""

import json
import math
from pathlib import Path

from .xdf import load_recording, session_samples


def load_video_timing(directory: Path, stream_index: int, duration: float) -> dict:
    """Return pairs of session seconds and MP4 presentation seconds for one stream.

    Join clock-corrected XDF markers to the video sidecar by frame index.
    Earlier sessions use their recorded JSON Lines markers and stored duration.
    Reject missing files, unmatched frames, and non-monotonic time mappings.
    """
    directory = directory.resolve()
    paths = [directory / f"stream_{stream_index:02d}.frames.jsonl"]
    session_file = directory / "session.json"
    session = json.loads(session_file.read_text(encoding="utf-8")) if session_file.is_file() else {}
    xdf = session.get("recording_format") == "xdf"
    if not xdf:
        paths.append(directory / f"stream_{stream_index:02d}.jsonl")
    for path in paths:
        if not path.is_file() or path.resolve().parent != directory:
            raise FileNotFoundError("Video frame timing or LSL marker file is missing")
    try:
        video_times = {}
        with paths[0].open(encoding="utf-8") as timing:
            for line in timing:
                row = json.loads(line)
                index, seconds = row["frame_index"], row["video_seconds"]
                if (
                    type(index) is not int
                    or index < 0
                    or not math.isfinite(seconds)
                    or seconds < 0
                    or index in video_times
                ):
                    raise ValueError("Invalid MP4 frame timing")
                video_times[index] = seconds
        if xdf:
            recorded, start, stop = load_recording(directory, session)
            stream = recorded[session["streams"][stream_index]["uid"]]
            values, times = session_samples(stream, start, stop)
            rows = zip(values.tolist(), times.tolist(), strict=True)
            duration = stop - start
        else:
            rows = legacy_markers(paths[1])
        points = []
        for sample, session_seconds in rows:
            if len(sample) != 1:
                raise ValueError("Expected one frame index per LSL marker")
            index = sample[0]
            if (
                not isinstance(index, (int, float))
                or not math.isfinite(index)
                or index != int(index)
                or index not in video_times
            ):
                raise ValueError("LSL marker has no matching MP4 frame")
            seconds = video_times[index]
            if not math.isfinite(session_seconds) or not 0 <= session_seconds <= duration:
                raise ValueError("Invalid session time in LSL marker")
            if points and (session_seconds <= points[-1][0] or seconds <= points[-1][1]):
                raise ValueError("Video synchronization timestamps are not monotonic")
            points.append([session_seconds, seconds])
        if not points:
            raise ValueError("No recorded LSL frame markers are available for synchronization")
        return {"points": points, "duration_seconds": duration}
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Video synchronization files are malformed") from exc


def legacy_markers(path: Path):
    """Yield frame index samples and session times from an older JSON Lines recording."""
    with path.open(encoding="utf-8") as markers:
        for line in markers:
            chunk = json.loads(line)
            yield from zip(chunk["values"], chunk["session_seconds"], strict=True)
