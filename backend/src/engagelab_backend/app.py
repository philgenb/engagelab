"""Local API for stream discovery and session recording."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from engagelab_pipeline.lsl import LSLUnavailable, discover
from engagelab_pipeline.recorder import Recorder, RecordingConflict
from engagelab_pipeline.sources.video_control import VideoCaptureError
from engagelab_pipeline.storage import SessionStore
from engagelab_pipeline.video_timing import load_video_timing
from engagelab_pipeline.xdf import XDFUnavailable
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


class NewSession(BaseModel):
    """Validate the name and optional game for a new session."""

    name: str = Field(min_length=1, max_length=120)
    game: str = Field(default="", max_length=120)


class StartRecording(BaseModel):
    """Carry the LSL stream UIDs selected for recording."""

    stream_uids: list[str] = Field(min_length=1, max_length=32)


def create_app(data_dir: Path | None = None) -> FastAPI:
    """Build the local API with a session store and one recording coordinator."""
    store = SessionStore(data_dir)
    recorder = Recorder(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Finalize any active recording during application shutdown."""
        yield
        await run_in_threadpool(recorder.close)

    app = FastAPI(title="EngageLab", version="0.1.0", lifespan=lifespan)
    app.state.recorder = recorder
    app.state.store = store

    @app.get("/api/health")
    def health():
        """Report that the HTTP service is responding."""
        return {"status": "ok"}

    @app.get("/api/streams")
    def streams():
        """List LSL streams currently discoverable by the backend."""
        try:
            return discover()
        except LSLUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/sessions")
    def sessions():
        """List saved session metadata, newest first."""
        return store.list()

    @app.post("/api/sessions", status_code=201)
    def create_session(body: NewSession):
        """Create a session record before capture starts."""
        try:
            return store.create(body.name, body.game)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sessions/{session_id}")
    def session(session_id: UUID):
        """Return the live session state when available, or the stored metadata."""
        try:
            current = recorder.snapshot()
            if current and current["id"] == str(session_id):
                return current
            return store.get(str(session_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: UUID):
        """Delete a session and its local files once recording has ended."""
        try:
            recorder.delete_session(str(session_id))
            return {"deleted": str(session_id)}
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc
        except RecordingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Could not delete the session files") from exc

    @app.post("/api/sessions/{session_id}/start")
    def start(session_id: UUID, body: StartRecording):
        """Start recording the selected LSL streams for the given session."""
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
        except VideoCaptureError as exc:
            raise HTTPException(503, str(exc)) from exc
        except XDFUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "Could not connect to all selected LSL streams") from exc

    @app.get("/api/sessions/{session_id}/streams/{stream_index}/preview")
    async def preview(session_id: UUID, stream_index: int, request: Request):
        """Stream successive JPEG previews from an active video source."""
        try:
            initial = await run_in_threadpool(recorder.preview, str(session_id), stream_index)
        except RecordingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except VideoCaptureError as exc:
            raise HTTPException(503, str(exc)) from exc

        async def frames():
            """Yield multipart JPEG frames until capture ends or the client disconnects."""
            frame = initial
            while not await request.is_disconnected():
                if frame:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(frame)).encode()
                        + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                await asyncio.sleep(0.2)
                try:
                    frame = await run_in_threadpool(recorder.preview, str(session_id), stream_index)
                except (RecordingConflict, ValueError, VideoCaptureError):
                    break

        return StreamingResponse(
            frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    def saved_video(session_id: UUID, stream_index: int):
        """Resolve a finalized MP4 within the requested session directory."""
        try:
            saved = store.get(str(session_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc
        if not 0 <= stream_index < len(saved["streams"]):
            raise HTTPException(404, "Video source not found")
        stream = saved["streams"][stream_index]
        if saved["status"] == "recording":
            raise HTTPException(409, "Stop the recording before opening the MP4")
        directory = store.directory(str(session_id)).resolve()
        path = directory / f"stream_{stream_index:02d}.mp4"
        if (
            stream.get("video_status") != "ready"
            or not path.is_file()
            or path.resolve().parent != directory
        ):
            raise HTTPException(404, "No finalized MP4 is available for this source")
        return saved, directory, path

    @app.get("/api/sessions/{session_id}/streams/{stream_index}/video-timing")
    def video_timing(session_id: UUID, stream_index: int):
        """Return the mapping from session time to MP4 playback time."""
        saved, directory, _ = saved_video(session_id, stream_index)
        try:
            return load_video_timing(directory, stream_index, saved["duration_seconds"])
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sessions/{session_id}/xdf")
    def recording_xdf(session_id: UUID):
        """Download the XDF recording after the session has stopped."""
        try:
            saved = store.get(str(session_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Session not found") from exc
        if saved["status"] == "recording":
            raise HTTPException(409, "Stop the recording before downloading the XDF")
        directory = store.directory(str(session_id)).resolve()
        path = directory / "recording.xdf"
        if (
            saved.get("recording_format") != "xdf"
            or not path.is_file()
            or path.resolve().parent != directory
        ):
            raise HTTPException(404, "No XDF recording is available for this session")
        return FileResponse(
            path, media_type="application/octet-stream", filename=f"{session_id}.xdf"
        )

    @app.get("/api/sessions/{session_id}/streams/{stream_index}/video")
    def video(session_id: UUID, stream_index: int, download: bool = False):
        """Serve a finalized MP4 for playback or download."""
        _, _, path = saved_video(session_id, stream_index)
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=path.name,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/recording")
    def recording():
        """Return the current recording status or null when no session is tracked."""
        return recorder.snapshot()

    @app.post("/api/recording/stop")
    def stop():
        """Stop the current recording and return the finalized session metadata."""
        try:
            return recorder.stop()
        except RecordingConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    return app


app = create_app()
