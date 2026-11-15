import io
import json
from types import SimpleNamespace

import pytest
from engagelab_pipeline.recorder import Recorder, RecordingConflict, Source
from engagelab_pipeline.storage import SessionStore


def test_raw_timestamps_offsets_and_session_boundaries(tmp_path):
    recorder = Recorder(SessionStore(tmp_path))
    recorder._session = {"started_lsl": 100.0}
    recorder._stop_at = 103.0
    recorder._lsl = SimpleNamespace(local_clock=lambda: 110.0)
    inlet = SimpleNamespace(pull_chunk=lambda **_: ([[1], [float("nan")], [3]], [94, 96, 99]))
    data = io.StringIO()
    source = Source(inlet, {"sample_count": 0}, data, 5.0, 115.0)

    assert recorder._collect(source) == 3
    row = json.loads(data.getvalue())
    assert row["timestamps_lsl"] == [96]
    assert row["timestamps_local"] == [101]
    assert row["session_seconds"] == [1]
    assert row["clock_offset_seconds"] == 5
    assert row["values"] == [[None]]
    assert source.metadata["sample_count"] == 1


def test_sessions_are_isolated_and_cannot_escape_data_directory(tmp_path):
    store = SessionStore(tmp_path)
    first = store.create("Pilot 01", "Portal 2")
    second = store.create("Pilot 02")
    assert first["id"] != second["id"]
    assert store.get(first["id"])["game"] == "Portal 2"
    assert len(store.list()) == 2
    with pytest.raises(ValueError):
        store.directory("../../outside")
    with pytest.raises(ValueError):
        store.create("   ")


def test_duplicate_streams_and_restarting_completed_sessions_are_rejected(tmp_path):
    store = SessionStore(tmp_path)
    session = store.create("Pilot")
    recorder = Recorder(store)
    with pytest.raises(ValueError, match="duplicates"):
        recorder.start(session["id"], ["one", "one"])
    session["status"] = "completed"
    store.save(session)
    with pytest.raises(RecordingConflict):
        recorder.start(session["id"], ["one"])
    with pytest.raises(RecordingConflict):
        recorder.stop()
