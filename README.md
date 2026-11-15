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

## PyCharm

Open `engagelab/` as the project. Shared configurations are in `.run/` and use
`.venv/bin/python`: **EngageLab Demo Streams**, **EngageLab Discover Streams**,
**EngageLab Record Demo**, and **EngageLab Backend**. Start Demo Streams before
Record Demo. Stop the demo publisher manually when finished.

## Screen recording stream

Install the optional capture dependencies with `pip install -e '.[screen]'`.
Start **EngageLab Screen Stream** in PyCharm, or run:

```sh
engagelab screen --list-monitors
engagelab screen --monitor 1 --fps 10 --max-width 1280 --quality 75
```

In the frontend, discover streams, select **Screen recording**, and start a session.
The publisher runs until stopped and only captures pixels while a receiver subscribes.
On macOS, allow Screen & System Audio Recording for the application running Python
(e.g. PyCharm or Terminal) in System Settings > Privacy & Security, then restart it.

Each LSL sample is one base64-encoded JPEG in a single string channel. Resolution,
encoding and capture settings are in the stream XML. Timestamps estimate capture time
using the midpoint of LSL clock readings before and after each screen grab, before JPEG
encoding. FPS is a target, not a guarantee. The recorder stores the frames in its normal
JSONL files; MP4 export and frontend video playback are not implemented yet. Image
streams can create large recordings; lower FPS, width or JPEG quality to reduce size.

## Record without the UI

With the demo publisher running:

```sh
engagelab discover
engagelab record --name "Pilot 01" --game "Demo" --demo-streams --duration 10
```

For real sources, repeat `--stream UID` using UIDs from `engagelab discover`.
Other devices must already publish LSL streams. Additional hardware adapters, MP4
export, annotation, and analysis are not implemented yet.

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
