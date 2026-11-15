"""Small command-line interface for discovery, demos, and timed recordings."""

import argparse
import json
import signal
import threading
from pathlib import Path

from .demo import run_demo
from .lsl import discover
from .recorder import Recorder
from .sources.screen import ScreenCaptureError, ScreenConfig, list_monitors, run_screen
from .storage import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="engagelab")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("discover", help="List available LSL streams")
    commands.add_parser("demo", help="Publish three synthetic modality streams")
    screen = commands.add_parser("screen", help="Publish a real screen-capture LSL stream")
    screen.add_argument("--list-monitors", action="store_true")
    screen.add_argument("--monitor", type=int, default=1)
    screen.add_argument("--fps", type=float, default=10.0)
    screen.add_argument("--max-width", type=int, default=1280)
    screen.add_argument("--crf", type=int, default=23, help="H.264 quality: lower is better (0-51)")
    screen.add_argument("--data-dir", type=Path)
    record = commands.add_parser("record", help="Record selected LSL streams")
    record.add_argument("--name", required=True)
    record.add_argument("--game", default="")
    selection = record.add_mutually_exclusive_group(required=True)
    selection.add_argument("--stream", action="append", help="Stream UID; may be repeated")
    selection.add_argument(
        "--demo-streams", action="store_true", help="Select only EngageLab demos"
    )
    record.add_argument("--duration", type=float, default=10.0)
    record.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.command == "discover":
        print(json.dumps(discover(), indent=2))
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if args.command == "demo":
        print(
            "Publishing synthetic HeartRate, Input, and Game streams. Ctrl+C to stop.", flush=True
        )
        run_demo(stop)
        return
    if args.command == "screen":
        try:
            if args.list_monitors:
                print(json.dumps(list_monitors(), indent=2))
                return
            config = ScreenConfig(args.monitor, args.fps, args.max_width, args.crf, args.data_dir)
            run_screen(stop, config)
        except (ScreenCaptureError, ValueError) as exc:
            parser.exit(2, f"Error: {exc}\n")
        return
    if args.duration <= 0:
        parser.error("--duration must be positive")
    uids = args.stream
    if args.demo_streams:
        uids = [
            stream["uid"]
            for stream in discover()
            if stream["source_id"].startswith("engagelab-demo-")
        ]
    store = SessionStore(args.data_dir)
    session = store.create(args.name, args.game)
    recorder = Recorder(store)
    try:
        recorder.start(session["id"], uids)
        print(f"Recording {session['id']} for {args.duration:g} seconds.", flush=True)
        stop.wait(args.duration)
    finally:
        recorder.close()
    result = store.get(session["id"])
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)
