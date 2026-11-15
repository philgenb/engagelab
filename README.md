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
engagelab screen --monitor 1 --fps 30 --max-width 1280 --crf 23
```

In the frontend, discover streams, select **Screen recording**, and start a session.
**Live monitor** shows the gameplay preview during recording. Stop and save the session,
then open **View session** to play the MP4 or download it. Restart an already running
backend and screen publisher after upgrading from the earlier JPEG stream implementation.

The publisher runs until stopped, but only captures pixels during a session started by
EngageLab. Session start/stop controls the video through an authenticated loopback HTTP
connection; LSL carries the frame markers. A generic LSL subscriber alone does not start
video recording. The publisher and backend must run on the same computer and use the same
data directory (`ENGAGELAB_DATA_DIR`, or `--data-dir` for the CLI). The control port is
allocated automatically. Stop a recording in EngageLab before stopping the publisher.
On macOS, allow Screen & System Audio Recording for the application running Python
(e.g. PyCharm or Terminal) in System Settings > Privacy & Security, then restart it.

Video is saved directly as H.264 MP4 in the session directory, e.g. `stream_00.mp4`.
Each LSL sample contains a zero-based frame index in one int64 channel, with a capture
timestamp estimated from the midpoint of clock readings before and after the screen grab.
The stream has an irregular nominal rate because capture timing can vary. `--fps` sets
the target rate; `--crf` sets H.264 quality (lower is better, default 23). Capture is
video-only, without audio. XML metadata contains resolution, capture settings and the
video path template.

MP4 presentation timestamps preserve actual capture intervals, relative to the first
frame. `stream_00.frames.jsonl` maps every video frame to its original LSL timestamp and
video time. The regular `stream_00.jsonl` contains the received LSL markers with clock
offsets and session-relative times. `session.json` links the video, timing file and first
frame's session-relative time. Use these times for alignment rather than frame index
divided by target FPS. Recording boundaries apply to the received markers; the video can
contain a few additional frames while the publisher processes the stop request.

Live preview uses a reduced JPEG image at up to 5 fps over one streaming connection to
the backend. It does not send images over LSL or change the configured MP4 capture rate.
The connection closes when leaving the view or stopping the session. Preview failures
offer a manual retry, and missing frame markers produce a warning in the monitor.
Existing JPEG/JSONL recordings remain unchanged and are not automatically converted.

## Webcam stream

Install the optional dependencies with `pip install -e '.[webcam]'`, or use
`pip install -e '.[screen,webcam]'` for both video sources. Start **EngageLab Webcam Stream**
in PyCharm, or run:

```sh
engagelab webcam --device 0 --fps 30 --width 1280 --height 720 --crf 23
```

Restart the backend after upgrading, discover streams in the frontend, and select
**Webcam** alongside **Screen recording** or other modalities. Both sources start and stop
with the session. The recording monitor shows a preview for each selected video source;
session details provide separate players and MP4 downloads after stopping. Webcam defaults
to camera index 0; try `--device 1` for another camera. On macOS, allow Camera access for
PyCharm or Terminal in System Settings > Privacy & Security and restart the application
if necessary. Close other applications using the camera if it cannot be opened.

The camera is opened only when an EngageLab session starts, and released on stop or capture
failure. Merely running the publisher or discovering streams does not activate it.
The webcam uses the same local control protocol, data directory and file layout as the
screen source. Each video gets its own stream index, e.g. `stream_00.mp4` for the screen
and `stream_01.mp4` for the webcam, depending on selection order. The webcam records video
without audio, with zero-based LSL frame markers and a `.frames.jsonl` timing file.

FPS and camera resolution are requests to the device, which may provide different values.
Output is padded to the configured dimensions while preserving the captured aspect ratio.
Timestamps use the LSL clock immediately after a successful camera read, before encoding;
camera exposure and driver buffering latency are not corrected. Preview remains capped
at 5 fps. Actual device permissions and performance need checking on the target camera.

## Record without the UI

With the demo publisher running:

```sh
engagelab discover
engagelab record --name "Pilot 01" --game "Demo" --demo-streams --duration 10
```

For real sources, repeat `--stream UID` using UIDs from `engagelab discover`.
Other devices must already publish LSL streams. Additional hardware adapters,
annotation, and synchronized signal analysis are not implemented yet.

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
