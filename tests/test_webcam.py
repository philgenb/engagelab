"""Test webcam recording with synthetic camera frames, without accessing hardware."""

import json
import socket
import time
from types import SimpleNamespace

import pytest
from engagelab_pipeline.sources.screen import ScreenConfig, ScreenService
from engagelab_pipeline.sources.video_control import (
    SCREEN_SCHEMA,
    WEBCAM_SCHEMA,
    VideoCaptureError,
    VideoClient,
)
from engagelab_pipeline.sources.webcam import WebcamConfig, WebcamService
from engagelab_pipeline.storage import SessionStore


class FakeCamera:
    def __init__(self, frame, opened=True):
        self.frame = frame
        self.opened = opened
        self.released = False
        self.settings = {}

    def isOpened(self):
        return self.opened

    def set(self, key, value):
        self.settings[key] = value
        return True

    def read(self):
        return self.frame is not None, self.frame

    def release(self):
        self.released = True


def camera_service(tmp_path, monkeypatch, *, opened=True):
    pytest.importorskip("av")
    cv2 = pytest.importorskip("cv2")
    image = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    frame = np.full((24, 32, 3), (0, 0, 255), dtype=np.uint8)
    cameras = []

    def open_camera(_):
        camera = FakeCamera(frame.copy(), opened=opened)
        cameras.append(camera)
        return camera

    monkeypatch.setattr(cv2, "VideoCapture", open_camera)
    stamps = iter([100.0, 100.13, 100.3, 100.5])
    service = WebcamService(
        WebcamConfig(width=64, height=48, data_dir=tmp_path),
        cv2,
        image,
        SimpleNamespace(local_clock=lambda: next(stamps)),
    )
    return service, cameras, image


def test_webcam_is_lazy_stops_releases_and_restarts(tmp_path, monkeypatch):
    av = pytest.importorskip("av")
    service, cameras, _ = camera_service(tmp_path, monkeypatch)
    store = SessionStore(tmp_path)
    first = store.create("First webcam session")
    markers = []
    outlet = SimpleNamespace(
        push_sample=lambda values, timestamp: markers.append((values, timestamp))
    )
    service.capture_frame(outlet)
    assert not cameras
    service.start(first["id"], 0)
    try:
        service.capture_frame(outlet)
        service.capture_frame(outlet)
        assert service.preview.startswith(b"\xff\xd8")
    finally:
        result = service.stop(first["id"])
    assert cameras[0].released
    assert result["video_status"] == "ready"
    assert markers == [([0], 100.0), ([1], 100.13)]
    with av.open(str(store.directory(first["id"]) / result["video_file"])) as video:
        frames = list(video.decode(video=0))
        assert [float(frame.pts * frame.time_base) for frame in frames] == pytest.approx([0, 0.13])
        rgb = frames[0].to_ndarray(format="rgb24")
        assert rgb[24, 32, 0] > 200
        assert rgb[24, 32, 2] < 20
    second = store.create("Second webcam session")
    service.start(second["id"], 0)
    try:
        assert service.preview is None
        service.capture_frame(outlet)
    finally:
        service.stop(second["id"])
    assert markers[-1] == ([0], 100.3)
    assert cameras[-1].released


def test_unavailable_camera_and_expired_start_leave_no_active_capture(tmp_path, monkeypatch):
    service, cameras, _ = camera_service(tmp_path, monkeypatch, opened=False)
    store = SessionStore(tmp_path)
    session = store.create("Unavailable camera")
    with pytest.raises(VideoCaptureError, match="Cannot open webcam"):
        service.start(session["id"], 0)
    assert cameras[0].released
    assert service.writer is None
    assert not list(store.directory(session["id"]).glob("*.mp4"))
    service, cameras, _ = camera_service(tmp_path, monkeypatch)
    with pytest.raises(VideoCaptureError, match="timed out"):
        service.start(session["id"], 0, start_deadline=time.monotonic() - 1)
    assert cameras[0].released
    assert service.writer is None


def test_camera_disconnect_reports_failure_and_releases_device(tmp_path, monkeypatch):
    service, cameras, _ = camera_service(tmp_path, monkeypatch)
    session = SessionStore(tmp_path).create("Disconnected camera")
    service.start(session["id"], 0)
    outlet = SimpleNamespace(push_sample=lambda *_args, **_kwargs: None)
    service.capture_frame(outlet)
    cameras[0].frame = None
    service.capture_frame(outlet)
    assert service.writer is None
    assert cameras[0].released
    result = service.stop(session["id"])
    assert result["video_status"] == "failed"
    assert "disconnected" in result["video_error"]


def test_webcam_and_screen_write_separate_videos_in_one_session(tmp_path, monkeypatch):
    webcam, cameras, image = camera_service(tmp_path, monkeypatch)
    session = SessionStore(tmp_path).create("Multimodal session")
    screen = ScreenService(ScreenConfig(data_dir=tmp_path), (64, 48))
    outlet = SimpleNamespace(push_sample=lambda *_args, **_kwargs: None)
    screen.start(session["id"], 0)
    webcam.start(session["id"], 1)
    try:
        with screen.lock:
            screen.write_image(image.new("RGB", (64, 48), "blue"), 100.0, outlet)
        webcam.capture_frame(outlet)
    finally:
        screen_result = screen.stop(session["id"])
        webcam_result = webcam.stop(session["id"])
    assert cameras[0].released
    assert screen_result["video_file"] == "stream_00.mp4"
    assert webcam_result["video_file"] == "stream_01.mp4"
    assert screen_result["video_status"] == webcam_result["video_status"] == "ready"
    for index in [0, 1]:
        path = SessionStore(tmp_path).directory(session["id"]) / f"stream_{index:02d}.frames.jsonl"
        assert json.loads(path.read_text())["frame_index"] == 0


@pytest.mark.parametrize("schema", [SCREEN_SCHEMA, WEBCAM_SCHEMA])
def test_recorder_recognizes_both_video_source_schemas(schema):
    metadata = {
        "schema": schema,
        "capture_host": socket.gethostname(),
        "control_port": "12345",
        "control_token": "test-token",
    }
    info = SimpleNamespace(
        desc=lambda: SimpleNamespace(child_value=lambda key: metadata.get(key, ""))
    )
    assert isinstance(VideoClient.from_info(info), VideoClient)
    metadata["capture_host"] = "another-computer"
    with pytest.raises(VideoCaptureError, match="same computer"):
        VideoClient.from_info(info)


@pytest.mark.parametrize(
    "options",
    [
        {"device": -1},
        {"fps": 0},
        {"fps": float("nan")},
        {"width": 1279},
        {"height": 0},
        {"crf": 52},
    ],
)
def test_invalid_webcam_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        WebcamConfig(**options)
