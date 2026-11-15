# EngageLab

An interactive tool for recording and exploring multimodal data during video game sessions.

- `pipeline/`: independent Python LSL discovery, recording, and demo publishers.
- `backend/`: FastAPI session and recording API.
- `frontend/`: React + TypeScript interface.
- `data/`: local recordings, excluded from Git.
- `tests/`: pipeline and API checks.

## Run locally

Requires Python 3.11+, Node.js 22.12+, and liblsl. If pylsl cannot load liblsl on macOS,
install it with `brew install labstreaminglayer/tap/lsl`.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn engagelab_backend.app:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the Vite URL. Run `engagelab demo` in a third terminal to publish synthetic heart-rate,
input, and gameplay metrics, then refresh and select the streams in the interface.
API documentation: <http://127.0.0.1:8000/docs>.

## Record without the UI

With the demo publisher running:

```sh
engagelab discover
engagelab record --name "Pilot 01" --game "Demo" --demo-streams --duration 10
```

For real sources, repeat `--stream UID` using UIDs from `engagelab discover`.
Devices must already publish LSL streams; hardware adapters, MP4 capture, annotation,
and analysis are not implemented yet.

Each recording contains `session.json`, per-stream XML metadata and chunked JSONL data,
`clock_offsets.jsonl`, and `events.jsonl`. Samples retain original LSL timestamps,
receiver-clock timestamps, and seconds relative to session start. Clock offsets are
logged separately and refreshed every five seconds. Non-finite values become `null`.
This is a basic JSONL recorder, not an XDF implementation or drift-correcting offline importer.
For XDF acquisition and offline synchronization, use
[LabRecorder](https://github.com/labstreaminglayer/App-LabRecorder).

Recordings default to `data/`; set `ENGAGELAB_DATA_DIR` to change the location.
Use one backend process and keep it bound to localhost. After an interrupted process,
recordings may remain marked as recording; their already-flushed files are preserved.

## Check

```sh
ruff check .
pytest -m 'not integration'
pytest -m integration       # requires local LSL network discovery
cd frontend && npm run build
```
