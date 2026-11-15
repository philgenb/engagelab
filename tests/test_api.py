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
