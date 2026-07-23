"""Windowed-RMS min-level parsing and event merging (backlog #34)."""

import pytest

from deepdub_qc.detectors.audio.min_rms import (
    DIGITAL_SILENCE_DB,
    RmsWindow,
    merge_low_rms_events,
    parse_windowed_rms,
    windowed_rms_filter,
)

SAMPLE_STDOUT = """\
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-27.094561
frame:1    pts:240000  pts_time:5
lavfi.astats.Overall.RMS_level=-95.5
frame:2    pts:480000  pts_time:10
lavfi.astats.Overall.RMS_level=-inf
frame:3    pts:720000  pts_time:15
lavfi.astats.Overall.RMS_level=-30.2
"""


class TestParsing:
    def test_pairs_pts_time_with_rms(self) -> None:
        windows = parse_windowed_rms(SAMPLE_STDOUT)
        assert [w.start for w in windows] == [0.0, 5.0, 10.0, 15.0]
        assert windows[0].rms_db == pytest.approx(-27.094561)
        assert windows[2].rms_db == DIGITAL_SILENCE_DB  # -inf mapped numerically

    def test_empty_input(self) -> None:
        assert parse_windowed_rms("") == []

    def test_filter_uses_sample_rate(self) -> None:
        assert "asetnsamples=n=240000" in windowed_rms_filter(48000)
        assert "asetnsamples=n=220500" in windowed_rms_filter(44100)


class TestMerging:
    def test_consecutive_low_windows_merge(self) -> None:
        windows = parse_windowed_rms(SAMPLE_STDOUT)
        events = merge_low_rms_events(windows, stream_duration=20.0)
        assert len(events) == 1
        event = events[0]
        assert event.start == 5.0
        assert event.end == 15.0  # closed by the -30.2 window at t=15
        assert event.duration == 10.0
        assert event.min_rms_db == DIGITAL_SILENCE_DB

    def test_trailing_low_run_capped_at_stream_end(self) -> None:
        windows = [RmsWindow(0.0, -20.0), RmsWindow(5.0, -100.0), RmsWindow(10.0, -100.0)]
        events = merge_low_rms_events(windows, stream_duration=13.2)
        assert len(events) == 1
        assert events[0].start == 5.0
        assert events[0].end == 13.2  # not 15.0: capped at EOF

    def test_no_low_windows_no_events(self) -> None:
        windows = [RmsWindow(0.0, -20.0), RmsWindow(5.0, -30.0)]
        assert merge_low_rms_events(windows, stream_duration=10.0) == []

    def test_threshold_boundary_is_strict(self) -> None:
        windows = [RmsWindow(0.0, -90.0)]  # exactly at threshold: not below
        assert merge_low_rms_events(windows, stream_duration=5.0) == []
