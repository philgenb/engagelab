import threading
import time

import pytest
from engagelab_pipeline.demo import run_demo
from engagelab_pipeline.lsl import discover, load_lsl
from engagelab_pipeline.recorder import Recorder
from engagelab_pipeline.storage import SessionStore
from engagelab_pipeline.xdf import info_value, load_recording, session_samples


@pytest.mark.integration
def test_three_real_lsl_streams_are_recorded_to_xdf_and_closed(tmp_path):
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
        assert len(streams) == 3
        session = recorder.store.create("XDF integration", "Synthetic game")
        recorder.start(session["id"], [stream["uid"] for stream in streams])
        time.sleep(2.2)
        result = recorder.stop()
        assert result["status"] == "completed", result.get("error")
        assert result["recording_format"] == "xdf"
        assert result["duration_seconds"] >= 2
        directory = recorder.store.directory(session["id"])
        assert (directory / "recording.xdf").read_bytes().startswith(b"XDF:")
        assert not (directory / "clock_offsets.jsonl").exists()
        assert not (directory / "stream_00.jsonl").exists()
        recorded, start, end = load_recording(directory, result)
        assert len(recorded) == 4
        for stream in result["streams"]:
            data = recorded[stream["uid"]]
            values, times = session_samples(data, start, end)
            assert len(times) == stream["sample_count"] > 0
            assert len(values) == len(times)
            assert (times >= 0).all() and (times < result["duration_seconds"]).all()
            assert len(data["clock_values"]) > 0
            assert info_value(data, "source_id") == stream["source_id"]
            assert "<info>" in (directory / stream["metadata_file"]).read_text()
    finally:
        recorder.close()
        stop.set()
        publisher.join(timeout=3)
        assert not publisher.is_alive()


@pytest.mark.integration
def test_xdf_video_markers_drive_playback_for_two_different_start_times(tmp_path):
    import json

    from engagelab_pipeline.sources.screen import ScreenConfig, create_stream_info
    from engagelab_pipeline.sources.video_control import VideoServer
    from engagelab_pipeline.sources.video_service import VideoService
    from engagelab_pipeline.sources.webcam import WebcamConfig
    from engagelab_pipeline.sources.webcam import create_stream_info as webcam_info
    from engagelab_pipeline.video_timing import load_video_timing

    image = pytest.importorskip("PIL.Image")
    pytest.importorskip("av")
    lsl = load_lsl()

    class DelayedWebcam(VideoService):
        def open_capture(self):
            time.sleep(0.35)

    screen_config = ScreenConfig(fps=10, data_dir=tmp_path)
    camera_config = WebcamConfig(fps=10, width=64, height=48, data_dir=tmp_path)
    services = [
        VideoService(screen_config, (64, 48), "Synthetic screen"),
        DelayedWebcam(camera_config, (64, 48), "Synthetic webcam"),
    ]
    servers = [VideoServer(service) for service in services]
    for server in servers:
        server.start()
    infos = [
        create_stream_info(
            lsl, screen_config, {"width": 64, "height": 48, "left": 0, "top": 0}, servers[0]
        ),
        webcam_info(lsl, camera_config, servers[1]),
    ]
    outlets = [lsl.StreamOutlet(info) for info in infos]
    stop = threading.Event()

    def publish():
        while not stop.is_set():
            for service, outlet in zip(services, outlets, strict=True):
                # Avoid blocking the screen while the webcam simulates device startup.
                if not service.lock.acquire(blocking=False):
                    continue
                try:
                    if service.writer:
                        service.write_image(
                            image.new("RGB", (64, 48), "blue"), lsl.local_clock(), outlet
                        )
                finally:
                    service.lock.release()
            stop.wait(0.1)

    producer = threading.Thread(target=publish, daemon=True)
    producer.start()
    recorder = Recorder(SessionStore(tmp_path))
    try:
        session = recorder.store.create("Synthetic video synchronization")
        recorder.start(session["id"], [outlet.get_info().uid() for outlet in outlets])
        time.sleep(1.3)
        result = recorder.stop()
        assert result["status"] == "completed", result.get("error")
        directory = recorder.store.directory(session["id"])
        mappings = [
            load_video_timing(directory, index, result["duration_seconds"]) for index in range(2)
        ]
        assert mappings[1]["points"][0][0] - mappings[0]["points"][0][0] >= 0.25
        for index, timing in enumerate(mappings):
            assert len(timing["points"]) == result["streams"][index]["sample_count"] > 0
            assert timing["points"][0][1] == 0
            assert (directory / f"stream_{index:02d}.mp4").stat().st_size > 0
            assert not (directory / f"stream_{index:02d}.jsonl").exists()
            frames = [
                json.loads(line)
                for line in (directory / f"stream_{index:02d}.frames.jsonl")
                .read_text()
                .splitlines()
            ]
            assert len(frames) >= len(timing["points"])
            assert result["streams"][index]["video_status"] == "ready"
    finally:
        recorder.close()
        stop.set()
        producer.join(timeout=2)
        for service in services:
            if service.session_id:
                service.stop(service.session_id)
        for server in servers:
            server.shutdown()
            server.server_close()
