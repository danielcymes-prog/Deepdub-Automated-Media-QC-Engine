"""Video incident parsers, tested against captured ffmpeg output shapes."""

from deepdub_qc.detectors.video.incidents import (
    Span,
    parse_black_events,
    parse_freeze_events,
    parse_luma_stats,
)

BLACK_STDERR = """\
[blackdetect @ 0x1] black_start:1.52 black_end:2.52 black_duration:1
[blackdetect @ 0x1] black_start:10 black_end:10.75 black_duration:0.75
"""

FREEZE_STDERR = """\
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 1.52
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 1
[freezedetect @ 0x2] lavfi.freezedetect.freeze_end: 2.52
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 3.6
"""

LUMA_STDOUT = """\
frame:0    pts:0       pts_time:0
lavfi.signalstats.YMIN=18
lavfi.signalstats.YAVG=124.745
lavfi.signalstats.YMAX=224
frame:1    pts:512     pts_time:0.04
lavfi.signalstats.YMIN=10
lavfi.signalstats.YAVG=125.155
lavfi.signalstats.YMAX=229
"""


class TestParseBlackEvents:
    def test_events_parsed(self) -> None:
        events = parse_black_events(BLACK_STDERR)
        assert events == [Span(start=1.52, end=2.52), Span(start=10.0, end=10.75)]
        assert events[0].duration == 1.0

    def test_empty(self) -> None:
        assert parse_black_events("no incidents") == []


class TestParseFreezeEvents:
    def test_closed_and_open_events(self) -> None:
        events = parse_freeze_events(FREEZE_STDERR, stream_duration=5.0)
        assert events == [Span(start=1.52, end=2.52), Span(start=3.6, end=5.0)]

    def test_open_event_without_duration_dropped(self) -> None:
        events = parse_freeze_events(FREEZE_STDERR, stream_duration=None)
        assert events == [Span(start=1.52, end=2.52)]


class TestParseLumaStats:
    def test_aggregation(self) -> None:
        stats = parse_luma_stats(LUMA_STDOUT)
        assert stats["luma_min"] == 10.0
        assert stats["luma_max"] == 229.0
        assert stats["luma_avg"] == 124.95

    def test_empty(self) -> None:
        assert parse_luma_stats("") == {}
