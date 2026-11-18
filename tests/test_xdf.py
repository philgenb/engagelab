import numpy as np
import pytest
from engagelab_pipeline.xdf import XDFUnavailable, find_labrecorder, session_samples


def test_explicit_recorder_configuration_reports_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGAGELAB_LABRECORDER", str(tmp_path / "missing"))
    with pytest.raises(XDFUnavailable, match="ENGAGELAB_LABRECORDER"):
        find_labrecorder()


def test_session_filter_preserves_numeric_nan_and_string_values():
    stream = {
        "time_stamps": np.asarray([10, 11, 12, 13]),
        "time_series": np.asarray([[1], [float("nan")], [3], [4]]),
    }
    values, times = session_samples(stream, 11, 13)
    assert np.isnan(values[0][0])
    assert values[1][0] == 3
    assert times.tolist() == [0, 1]
    stream["time_series"] = [["before"], ["start"], ["inside"], ["stop"]]
    values, times = session_samples(stream, 11, 13)
    assert values == [["start"], ["inside"]]


def test_native_stream_errors_are_not_silently_accepted(monkeypatch, tmp_path):
    from engagelab_pipeline.xdf import LabRecorder

    executable = tmp_path / "LabRecorderCLI"
    executable.touch()
    monkeypatch.setenv("ENGAGELAB_LABRECORDER", str(executable))
    log = tmp_path / "labrecorder.log"
    recorder = LabRecorder(tmp_path / "recording.xdf", log)
    log.write_text("Error in the record_from_streaminfo thread: Unsupported channel format\n")
    with pytest.raises(XDFUnavailable, match="could not record"):
        recorder.check_log()


def test_offline_clock_sync_uses_xdf_session_markers_and_caches_import(monkeypatch, tmp_path):
    import engagelab_pipeline.xdf as xdf
    from engagelab_pipeline.xdf import load_recording

    calls = []
    markers = {
        "info": {"uid": ["markers"], "source_id": ["session-markers"]},
        "time_series": [["start"], ["stop"]],
        "time_stamps": np.array([1002.0, 1005.0]),
    }
    video = {
        "info": {"uid": ["camera"], "source_id": ["camera-source"]},
        "time_series": np.array([[0], [1]]),
        "time_stamps": np.array([1002.5, 1003.0]),
    }

    def load(path, **options):
        calls.append(options)
        return [markers, video], {}

    monkeypatch.setattr(xdf.pyxdf, "load_xdf", load)
    (tmp_path / "recording.xdf").write_bytes(b"XDF:fixture")
    session = {
        "started_lsl": 999,
        "session_marker_source_id": "session-markers",
        "streams": [{"uid": "camera", "name": "Webcam"}],
    }
    streams, start, stop = load_recording(tmp_path, session)
    _, times = session_samples(streams["camera"], start, stop)
    assert times.tolist() == [0.5, 1.0]
    assert stop - start == 3
    load_recording(tmp_path, session)
    assert calls == [{"synchronize_clocks": True, "dejitter_timestamps": False}]
