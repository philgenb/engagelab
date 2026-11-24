"""Synthetic streams for testing the full pipeline without recording personal data."""

import math
import threading
import time
from uuid import uuid4

from .lsl import load_lsl


def run_demo(stop: threading.Event) -> None:
    """Publish synthetic heart-rate, input, and game metrics until the stop event is set."""
    lsl = load_lsl()
    run_id = uuid4().hex
    specs = [
        ("Demo Heart Rate", "HeartRate", ["bpm"], ["bpm"], 1.0),
        (
            "Demo Input",
            "Input",
            ["keys", "clicks", "mouse_distance"],
            ["count", "count", "px"],
            10.0,
        ),
        ("Demo Game", "Game", ["optical_flow", "audio_rms"], ["a.u.", "a.u."], 10.0),
    ]
    outlets = []
    for name, modality, labels, units, rate in specs:
        info = lsl.StreamInfo(
            name, modality, len(labels), rate, "float32", f"engagelab-demo-{run_id}-{modality}"
        )
        info.desc().append_child_value("synthetic", "true")
        channels = info.desc().append_child("channels")
        for label, unit in zip(labels, units, strict=True):
            channel = channels.append_child("channel")
            channel.append_child_value("label", label)
            channel.append_child_value("unit", unit)
        outlets.append((lsl.StreamOutlet(info), modality, rate, 0.0))
    started = time.monotonic()
    while not stop.is_set():
        now = time.monotonic()
        elapsed = now - started
        for index, (outlet, modality, rate, next_sample) in enumerate(outlets):
            if now < next_sample:
                continue
            if modality == "HeartRate":
                values = [72 + 5 * math.sin(elapsed / 8)]
            elif modality == "Input":
                values = [
                    float(int(elapsed) % 4),
                    float(int(elapsed / 2) % 2),
                    100 + 60 * math.sin(elapsed),
                ]
            else:
                values = [0.4 + 0.2 * math.sin(elapsed / 3), 0.2 + 0.1 * math.cos(elapsed)]
            outlet.push_sample(values, timestamp=lsl.local_clock())
            outlets[index] = (outlet, modality, rate, now + 1.0 / rate)
        stop.wait(0.005)
