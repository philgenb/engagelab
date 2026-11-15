import json
import threading
import time

import pytest
from engagelab_pipeline.demo import run_demo
from engagelab_pipeline.lsl import discover, load_lsl
from engagelab_pipeline.recorder import Recorder
from engagelab_pipeline.storage import SessionStore


@pytest.mark.integration
def test_three_real_lsl_streams_are_recorded_and_closed(tmp_path):
    load_lsl()
    stop = threading.Event()
    publisher = threading.Thread(target=run_demo, args=(stop,), daemon=True)
    publisher.start()
    recorder = Recorder(SessionStore(tmp_path))
    try:
        deadline = time.monotonic() + 15
        streams = []
        while time.monotonic() < deadline:
            streams = [
                s for s in discover(timeout=1.0) if s["source_id"].startswith("engagelab-demo-")
            ]
            if len(streams) == 3:
                break
        assert len(streams) == 3, "The three demo outlets must be discoverable"
        session = recorder.store.create("Integration test", "Synthetic game")
        started = recorder.start(session["id"], [stream["uid"] for stream in streams])
        time.sleep(2.2)
        result = recorder.stop()
        assert result["status"] == "completed"
        assert result["duration_seconds"] >= 2
        directory = recorder.store.directory(session["id"])
        assert recorder.store.get(session["id"])["status"] == "completed"
        for stream in result["streams"]:
            assert stream["sample_count"] > 0
            assert "<info>" in (directory / stream["metadata_file"]).read_text()
            chunks = [
                json.loads(line)
                for line in (directory / stream["data_file"]).read_text().splitlines()
            ]
            assert sum(len(chunk["values"]) for chunk in chunks) == stream["sample_count"]
            for chunk in chunks:
                assert len(chunk["values"]) == len(chunk["timestamps_lsl"])
                for raw, local, relative in zip(
                    chunk["timestamps_lsl"],
                    chunk["timestamps_local"],
                    chunk["session_seconds"],
                    strict=True,
                ):
                    assert local == pytest.approx(raw + chunk["clock_offset_seconds"])
                    assert relative == pytest.approx(local - started["started_lsl"])
                    assert 0 <= relative < result["duration_seconds"]
        offsets = [
            json.loads(line)
            for line in (directory / "clock_offsets.jsonl").read_text().splitlines()
        ]
        assert {row["stream_uid"] for row in offsets} == {s["uid"] for s in streams}
    finally:
        recorder.close()
        stop.set()
        publisher.join(timeout=3)
        assert not publisher.is_alive()
