"""Local API for stream discovery and session recording."""

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from engagelab_pipeline.lsl import LSLUnavailable, discover
from engagelab_pipeline.recorder import Recorder, RecordingConflict
from engagelab_pipeline.storage import SessionStore
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


class NewSession(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    game: str = Field(default="", max_length=120)


class StartRecording(BaseModel):
    stream_uids: list[str] = Field(min_length=1, max_length=32)


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = SessionStore(data_dir)
    recorder = Recorder(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await run_in_threadpool(recorder.close)

    app = FastAPI(title="EngageLab", version="0.1.0", lifespan=lifespan)
    app.state.recorder = recorder
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/streams")
    def streams():
        try:
            return discover()
        except LSLUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/sessions")
    def sessions():
        return store.list()

    @app.post("/api/sessions", status_code=201)
    def create_session(body: NewSession):
        try:
            return store.create(body.name, body.game)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sessions/{session_id}")
    def session(session_id: UUID):
        try:
            current = recorder.snapshot()
            if current and current["id"] == str(session_id):
                return current
            return store.get(str(session_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc

    @app.post("/api/sessions/{session_id}/start")
    def start(session_id: UUID, body: StartRecording):
        try:
            return recorder.start(str(session_id), body.stream_uids)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc
        except RecordingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except LSLUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "Could not connect to all selected LSL streams") from exc

    @app.get("/api/recording")
    def recording():
        return recorder.snapshot()

    @app.post("/api/recording/stop")
    def stop():
        try:
            return recorder.stop()
        except RecordingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    return app


app = create_app()
