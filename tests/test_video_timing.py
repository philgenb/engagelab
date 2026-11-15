import json

import pytest
from engagelab_backend.app import create_app
from engagelab_pipeline.video_timing import load_video_timing
from fastapi.testclient import TestClient


def write_timing(directory, index, frames, chunks):
    prefix = directory / f"stream_{index:02d}"
    prefix.with_suffix(".mp4").write_bytes(b"video")
    prefix.with_suffix(".frames.jsonl").write_text(
        "\n".join(json.dumps(row) for row in frames) + "\n"
    )
    prefix.with_suffix(".jsonl").write_text("\n".join(json.dumps(row) for row in chunks) + "\n")


def test_timing_uses_received_lsl_times_and_skips_unrecorded_frames(tmp_path):
    write_timing(
        tmp_path,
        0,
        [
            {"frame_index": i, "video_seconds": stamp}
            for i, stamp in enumerate([0, 0.04, 0.12, 0.2])
        ],
        [
            {"values": [[0], [2]], "session_seconds": [1.5, 1.63]},
        ],
    )
    timing = load_video_timing(tmp_path, 0, 3)
    assert timing["points"] == [[1.5, 0], [1.63, 0.12]]
    assert timing["duration_seconds"] == 3


def test_timing_rejects_non_monotonic_or_missing_markers(tmp_path):
    frames = [{"frame_index": 0, "video_seconds": 0}, {"frame_index": 1, "video_seconds": 0.04}]
    write_timing(tmp_path, 0, frames, [{"values": [[0], [1]], "session_seconds": [1, 0.9]}])
    with pytest.raises(ValueError, match="not monotonic"):
        load_video_timing(tmp_path, 0, 3)
    write_timing(tmp_path, 0, frames, [{"values": [[3]], "session_seconds": [1]}])
    with pytest.raises(ValueError, match="no matching"):
        load_video_timing(tmp_path, 0, 3)


def test_timing_api_preserves_different_video_start_times(tmp_path):
    app = create_app(tmp_path)
    session = app.state.store.create("Different starts")
    session.update(
        status="completed",
        duration_seconds=10,
        streams=[{"video_status": "ready"}, {"video_status": "ready"}],
    )
    app.state.store.save(session)
    directory = app.state.store.directory(session["id"])
    for index, offset in enumerate([0.1, 1.4]):
        write_timing(
            directory,
            index,
            [
                {"frame_index": 0, "video_seconds": 0},
                {"frame_index": 1, "video_seconds": 0.05},
            ],
            [{"values": [[0], [1]], "session_seconds": [offset, offset + 0.05]}],
        )
    with TestClient(app) as client:
        base = f"/api/sessions/{session['id']}/streams"
        assert client.get(f"{base}/0/video-timing").json()["points"][0] == [0.1, 0]
        assert client.get(f"{base}/1/video-timing").json()["points"][0] == [1.4, 0]
        (directory / "stream_01.frames.jsonl").unlink()
        assert client.get(f"{base}/1/video-timing").status_code == 404
        session["status"] = "recording"
        app.state.store.save(session)
        assert client.get(f"{base}/0/video-timing").status_code == 409
