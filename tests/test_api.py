from uuid import uuid4

from engagelab_backend.app import create_app
from engagelab_pipeline.lsl import LSLUnavailable
from fastapi.testclient import TestClient


def test_session_api_validation_and_recording_conflicts(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.post("/api/sessions", json={"name": "  "}).status_code == 422
        created = client.post("/api/sessions", json={"name": "Pilot", "game": "Celeste"})
        assert created.status_code == 201
        session = created.json()
        assert client.get(f"/api/sessions/{session['id']}").json() == session
        assert client.get("/api/sessions").json() == [session]
        assert client.get(f"/api/sessions/{uuid4()}").status_code == 404
        assert client.get("/api/sessions/not-a-uuid").status_code == 422
        assert client.post("/api/recording/stop").status_code == 409
        assert (
            client.post(
                f"/api/sessions/{session['id']}/start", json={"stream_uids": []}
            ).status_code
            == 422
        )
        assert client.get("/api/recording").json() is None


def test_missing_lsl_returns_an_actionable_error(tmp_path, monkeypatch):
    def unavailable():
        raise LSLUnavailable("Install liblsl")

    monkeypatch.setattr("engagelab_backend.app.discover", unavailable)
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/streams")
        assert response.status_code == 503
        assert response.json()["detail"] == "Install liblsl"


def test_video_playback_range_download_and_recording_guard(tmp_path):
    app = create_app(tmp_path)
    session = app.state.store.create("Video")
    session.update(status="completed", streams=[{"video_status": "ready"}])
    app.state.store.save(session)
    video = app.state.store.directory(session["id"]) / "stream_00.mp4"
    video.write_bytes(b"0123456789")
    url = f"/api/sessions/{session['id']}/streams/0/video"
    with TestClient(app) as client:
        response = client.get(url, headers={"Range": "bytes=2-5"})
        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-type"] == "video/mp4"
        assert response.headers["content-disposition"].startswith("inline")
        assert (
            client.get(url + "?download=true")
            .headers["content-disposition"]
            .startswith("attachment")
        )
        assert client.get(url.replace("streams/0", "streams/-1")).status_code == 404
        session["status"] = "recording"
        app.state.store.save(session)
        assert client.get(url).status_code == 409
        session.update(status="failed", streams=[{"video_status": "failed"}])
        app.state.store.save(session)
        assert client.get(url).status_code == 404


def test_preview_is_one_stream_and_stops_when_recording_ends(tmp_path, monkeypatch):
    from engagelab_pipeline.recorder import RecordingConflict

    app = create_app(tmp_path)
    calls = []

    def preview(session_id, index):
        calls.append((session_id, index))
        if len(calls) > 1:
            raise RecordingConflict("Recording stopped")
        return b"fake-jpeg"

    monkeypatch.setattr(app.state.recorder, "preview", preview)
    session_id = str(uuid4())
    url = f"/api/sessions/{session_id}/streams/0/preview"
    with TestClient(app) as client:
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
        assert b"fake-jpeg" in response.content
        assert response.content.count(b"--frame") == 1
        assert client.get(url).status_code == 409
