"""Lazy liblsl loading keeps the API usable when the native library is missing."""

import importlib


class LSLUnavailable(RuntimeError):
    """Report that the Python LSL binding or its native library could not load."""

    pass


def load_lsl():
    """Import pylsl on demand and report native-library failures as LSLUnavailable."""
    try:
        return importlib.import_module("pylsl")
    except (ImportError, RuntimeError, OSError) as exc:
        raise LSLUnavailable(
            "LSL is unavailable. Install liblsl and pylsl; see README.md. "
            "On macOS: brew install labstreaminglayer/tap/lsl"
        ) from exc


def describe(info) -> dict:
    """Extract the identifiers, channel format, and other public stream metadata."""
    return {
        "uid": info.uid(),
        "source_id": info.source_id(),
        "name": info.name(),
        "type": info.type(),
        "channel_count": info.channel_count(),
        "nominal_srate": info.nominal_srate(),
        "channel_format": info.channel_format(),
        "hostname": info.hostname(),
    }


def discover(timeout: float = 1.0) -> list[dict]:
    """Return metadata for the LSL streams discovered within the timeout in seconds."""
    lsl = load_lsl()
    return [describe(info) for info in lsl.resolve_streams(wait_time=timeout)]
