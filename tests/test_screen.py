"""Exercise video timing and session control without capturing the user's screen."""

import io
import json
from types import SimpleNamespace

import pytest
from engagelab_pipeline.recorder import Recorder, Source
from engagelab_pipeline.sources.screen import ScreenConfig, ScreenService
from engagelab_pipeline.sources.video import Mp4Recording
from engagelab_pipeline.sources.video_control import VideoCaptureError, VideoClient, VideoServer
from engagelab_pipeline.storage import SessionStore


def test_mp4_preserves_variable_frame_times(tmp_path):
    av = pytest.importorskip("av")
    image = pytest.importorskip("PIL.Image")
    path = tmp_path / "capture.mp4"
    writer = Mp4Recording(path, (64, 48), fps=10, crf=23)
    for stamp in [50.0, 50.1, 50.45]:
        writer.write(image.new("RGB", (64, 48), "red"), stamp)
    result = writer.close()
    assert result["video_frame_count"] == 3
    assert result["video_first_frame_lsl"] == 50.0
    assert result["video_status"] == "ready"
    with av.open(str(path)) as video:
        frames = list(video.decode(video=0))
        assert video.streams.video[0].codec_context.name == "h264"
        assert [float(frame.pts * frame.time_base) for frame in frames] == pytest.approx(
            [0.0, 0.1, 0.45],
            abs=0.00001,
        )
    timing = [
        json.loads(line) for line in path.with_suffix(".frames.jsonl").read_text().splitlines()
    ]
    assert [row["frame_index"] for row in timing] == [0, 1, 2]
    assert [row["timestamp_lsl"] for row in timing] == [50.0, 50.1, 50.45]
    with pytest.raises(FileExistsError):
        Mp4Recording(path, (64, 48), fps=10, crf=23)


def test_source_control_records_only_during_a_session(tmp_path):
    pytest.importorskip("av")
    image = pytest.importorskip("PIL.Image")
    store = SessionStore(tmp_path)
    first = store.create("First")
    second = store.create("Second")
    service = ScreenService(ScreenConfig(data_dir=tmp_path), (64, 48))
    server = VideoServer(service)
    thread = server.start()
    client = VideoClient(server.server_address[1], server.token)
    grabbed = []
    markers = []
    shot = SimpleNamespace(size=(64, 48), rgb=image.new("RGB", (64, 48), "blue").tobytes())
    capture = SimpleNamespace(grab=lambda monitor: grabbed.append(monitor) or shot)
    stamps = iter([100.0, 100.02, 100.2, 100.22])
    lsl = SimpleNamespace(local_clock=lambda: next(stamps))
    outlet = SimpleNamespace(
        push_sample=lambda value, timestamp: markers.append((value, timestamp))
    )
    try:
        # Idle discovery and preview never read desktop pixels or create video files.
        service.capture_frame(capture, {}, image, lsl, outlet)
        assert not grabbed
        assert client.preview() == b""
        with pytest.raises(VideoCaptureError, match="token"):
            VideoClient(server.server_address[1], "wrong").preview()
        client.start(first["id"], 0)
        with pytest.raises(VideoCaptureError, match="already recording"):
            client.start(second["id"], 0)
        service.capture_frame(capture, {}, image, lsl, outlet)
        assert client.preview().startswith(b"\xff\xd8")
        result = client.stop(first["id"])
        assert result["video_frame_count"] == 1
        assert result["video_status"] == "ready"
        assert markers[0][0] == [0]
        assert markers[0][1] == pytest.approx(100.01)
        assert client.stop(first["id"]) == result
        service.capture_frame(capture, {}, image, lsl, outlet)
        assert len(grabbed) == 1
        client.start(second["id"], 0)
        assert client.preview() == b""
        service.capture_frame(capture, {}, image, lsl, outlet)
        assert markers[1][0] == [0]
        assert client.stop(second["id"])["video_status"] == "ready"
        assert (store.directory(first["id"]) / "stream_00.mp4").is_file()
        assert (store.directory(second["id"]) / "stream_00.mp4").is_file()
    finally:
        if service.session_id:
            service.stop(service.session_id)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_recorder_links_video_to_session_and_reports_finalize_errors(tmp_path):
    recorder = Recorder(SessionStore(tmp_path))
    result = {
        "video_status": "ready",
        "video_frame_count": 3,
        "video_first_frame_lsl": 100.25,
        "video_file": "../../other.mp4",
    }
    source = Source(
        None,
        {
            "video_status": "recording",
            "video_file": "stream_00.mp4",
            "data_file": "stream_00.jsonl",
            "video_first_frame_session_seconds": 0.3,
        },
        io.StringIO(),
        0.1,
        200,
        SimpleNamespace(stop=lambda _: result),
    )
    recorder._finish_video(source, "session", 100)
    assert source.metadata["video_file"] == "stream_00.mp4"
    assert source.metadata["video_first_frame_session_seconds"] == 0.3
    assert source.metadata["video_timing_file"] == "stream_00.frames.jsonl"

    def unavailable(_):
        raise VideoCaptureError("Publisher disconnected")

    source.metadata["video_status"] = "recording"
    source.video = SimpleNamespace(stop=unavailable)
    recorder._finish_video(source, "session", 100)
    assert source.metadata["video_status"] == "failed"
    assert "disconnected" in source.metadata["video_error"]
