"""Audio detector parsers, tested against captured ffmpeg output shapes."""

from deepdub_qc.detectors.audio.clipping import parse_astats_overall
from deepdub_qc.detectors.audio.loudness import parse_ebur128
from deepdub_qc.detectors.audio.silence import SilenceSpan, classify, parse_silences

EBUR128_STDERR = """\
[Parsed_ebur128_0 @ 0x1] t: 1.09998    TARGET:-23 LUFS    M: -22.5 S:-23.1     \
I: -23.0 LUFS       LRA:   1.2 LU  FTPK: -8.5 dBFS  TPK: -8.5 dBFS
[Parsed_ebur128_0 @ 0x1] t: 1.19998    TARGET:-23 LUFS    M: -21.8 S:-22.9     \
I: -23.0 LUFS       LRA:   1.2 LU  FTPK: -8.5 dBFS  TPK: -8.5 dBFS
size=N/A time=00:00:01.90 bitrate=N/A speed= 223x
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -23.0 LUFS
    Threshold: -33.1 LUFS

  Loudness range:
    LRA:         1.2 LU
    Threshold:   0.0 LUFS
    LRA low:     -24.0 LUFS
    LRA high:    -22.0 LUFS

  True peak:
    Peak:      -1.9 dBFS
"""

SILENCE_STDERR = """\
[silencedetect @ 0x2] silence_start: 0
[silencedetect @ 0x2] silence_end: 1.2 | silence_duration: 1.2
[silencedetect @ 0x2] silence_start: 3
[silencedetect @ 0x2] silence_end: 3.8 | silence_duration: 0.8
[silencedetect @ 0x2] silence_start: 4.5
"""

ASTATS_STDERR = """\
[Parsed_astats_0 @ 0x3] Channel: 1
[Parsed_astats_0 @ 0x3] Peak level dB: -5.000000
[Parsed_astats_0 @ 0x3] Flat factor: 0.000000
[Parsed_astats_0 @ 0x3] Overall
[Parsed_astats_0 @ 0x3] DC offset: -0.000013
[Parsed_astats_0 @ 0x3] Peak level dB: 0.000265
[Parsed_astats_0 @ 0x3] RMS level dB: -0.490276
[Parsed_astats_0 @ 0x3] Flat factor: 26.110255
[Parsed_astats_0 @ 0x3] Peak count: 40278.000000
[Parsed_astats_0 @ 0x3] Number of samples: 48000
"""


class TestParseEbur128:
    def test_summary_values(self) -> None:
        values = parse_ebur128(EBUR128_STDERR)
        assert values["integrated_loudness"] == -23.0
        assert values["loudness_range"] == 1.2
        assert values["true_peak"] == -1.9

    def test_interval_maxima(self) -> None:
        values = parse_ebur128(EBUR128_STDERR)
        assert values["max_momentary"] == -21.8
        assert values["max_short_term"] == -22.9

    def test_nan_values_omitted(self) -> None:
        silent = EBUR128_STDERR.replace("I:         -23.0", "I:           nan")
        assert "integrated_loudness" not in parse_ebur128(silent)

    def test_empty_output(self) -> None:
        assert parse_ebur128("") == {}


class TestParseSilences:
    def test_pairs_and_open_tail(self) -> None:
        spans = parse_silences(SILENCE_STDERR, stream_duration=6.0)
        assert spans == [
            SilenceSpan(start=0.0, end=1.2),
            SilenceSpan(start=3.0, end=3.8),
            SilenceSpan(start=4.5, end=6.0),
        ]

    def test_open_tail_without_duration_is_dropped(self) -> None:
        spans = parse_silences(SILENCE_STDERR, stream_duration=None)
        assert len(spans) == 2

    def test_classify_head_tail_internal(self) -> None:
        spans = parse_silences(SILENCE_STDERR, stream_duration=6.0)
        head, tail, internal = classify(spans, stream_duration=6.0)
        assert head == 1.2
        assert tail == 1.5
        assert internal == [SilenceSpan(start=3.0, end=3.8)]

    def test_fully_silent_stream_is_head_and_tail(self) -> None:
        spans = [SilenceSpan(start=0.0, end=6.0)]
        head, tail, internal = classify(spans, stream_duration=6.0)
        assert head == 6.0
        assert tail == 6.0
        assert internal == []

    def test_no_silence(self) -> None:
        head, tail, internal = classify([], stream_duration=6.0)
        assert (head, tail, internal) == (0.0, 0.0, [])


class TestParseAstats:
    def test_overall_block_only(self) -> None:
        values = parse_astats_overall(ASTATS_STDERR)
        assert values["Peak level dB"] == 0.000265  # Overall, not the -5.0 channel value
        assert values["Flat factor"] == 26.110255
        assert values["Peak count"] == 40278.0
        assert values["DC offset"] == -0.000013

    def test_non_finite_omitted(self) -> None:
        silent = ASTATS_STDERR.replace("Peak level dB: 0.000265", "Peak level dB: -inf")
        assert "Peak level dB" not in parse_astats_overall(silent)

    def test_missing_overall_block(self) -> None:
        assert parse_astats_overall("no astats here") == {}
