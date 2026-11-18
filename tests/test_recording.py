from types import SimpleNamespace

import pytest
from engagelab_pipeline.recorder import Recorder, RecordingConflict, Source
from engagelab_pipeline.storage import SessionStore


def test_live_monitor_respects_clock_offsets_and_session_boundaries(tmp_path):
    recorder = Recorder(SessionStore(tmp_path))
    recorder._session = {"started_lsl": 100.0}
    recorder._stop_at = 103.0
    recorder._lsl = SimpleNamespace(local_clock=lambda: 110.0)
    inlet = SimpleNamespace(pull_chunk=lambda **_: ([[1], [float("nan")], [3]], [94, 96, 99]))
    source = Source(inlet, {"sample_count": 0}, 5.0, 115.0)

    assert recorder._collect(source) == 3
    assert source.metadata["sample_count"] == 1
    assert source.metadata["last_sample_local"] == 101


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
