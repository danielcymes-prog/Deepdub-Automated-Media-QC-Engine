"""Dual-mono detection: filter-graph contract, astats parsing, decision rule."""

from deepdub_qc.detectors.audio.dual_mono import (
    CONTENT_FLOOR_DB,
    DIGITAL_SILENCE_DB,
    DUPLICATE_DIFF_THRESHOLD_DB,
    MAX_ANALYZED_CHANNELS,
    assess_duplicate_risk,
    channel_pairs,
    pair_analysis_filter,
    parse_channel_rms,
)


def astats_stderr(rms_values: list[str]) -> str:
    """Synthesize astats stderr with one channel block per value + Overall."""
    lines = []
    for position, value in enumerate(rms_values, start=1):
        lines.append(f"[Parsed_astats_0 @ 0x1] Channel: {position}")
        lines.append(f"[Parsed_astats_0 @ 0x1] RMS level dB: {value}")
    lines.append("[Parsed_astats_0 @ 0x1] Overall")
    lines.append("[Parsed_astats_0 @ 0x1] RMS level dB: -20.0")
    return "\n".join(lines)


class TestChannelPairs:
    def test_stereo_is_one_pair(self) -> None:
        assert channel_pairs(2) == [(0, 1)]

    def test_five_one_is_fifteen_pairs(self) -> None:
        assert len(channel_pairs(6)) == 15

    def test_wide_streams_are_capped(self) -> None:
        assert channel_pairs(32) == channel_pairs(MAX_ANALYZED_CHANNELS)


class TestPairAnalysisFilter:
    def test_stereo_graph_shape(self) -> None:
        graph = pair_analysis_filter(0, 2)
        assert "[0:a:0]asplit=3" in graph
        assert "pan=mono|c0=c0[m0]" in graph
        assert "pan=mono|c0=c1[m1]" in graph
        assert "pan=mono|c0=c0-c1[m2]" in graph
        assert "amerge=inputs=3,astats[probe]" in graph

    def test_ordinal_selects_the_stream(self) -> None:
        assert pair_analysis_filter(3, 2).startswith("[0:a:3]")


class TestParseChannelRms:
    def test_channel_blocks_in_order(self) -> None:
        stderr = astats_stderr(["-20.5", "-21.0", "-90.3"])
        assert parse_channel_rms(stderr) == [-20.5, -21.0, -90.3]

    def test_overall_block_is_excluded(self) -> None:
        assert len(parse_channel_rms(astats_stderr(["-20.0"]))) == 1

    def test_digital_silence_becomes_numeric(self) -> None:
        assert parse_channel_rms(astats_stderr(["-inf"])) == [DIGITAL_SILENCE_DB]


class TestAssessDuplicateRisk:
    def test_identical_content_pair_is_flagged(self) -> None:
        flagged = assess_duplicate_risk(
            channel_rms=[-20.0, -20.0], pair_rms=[DIGITAL_SILENCE_DB], pairs=[(0, 1)]
        )
        assert len(flagged) == 1
        assert (flagged[0].channel_a, flagged[0].channel_b) == (0, 1)

    def test_true_stereo_is_not_flagged(self) -> None:
        assert not assess_duplicate_risk(
            channel_rms=[-20.0, -20.0], pair_rms=[-25.0], pairs=[(0, 1)]
        )

    def test_silent_pair_is_silence_not_dual_mono(self) -> None:
        silent = CONTENT_FLOOR_DB - 20
        assert not assess_duplicate_risk(
            channel_rms=[silent, silent], pair_rms=[DIGITAL_SILENCE_DB], pairs=[(0, 1)]
        )

    def test_one_loud_channel_is_enough_content(self) -> None:
        flagged = assess_duplicate_risk(
            channel_rms=[-20.0, CONTENT_FLOOR_DB - 20],
            pair_rms=[DUPLICATE_DIFF_THRESHOLD_DB],
            pairs=[(0, 1)],
        )
        assert len(flagged) == 1

    def test_only_the_duplicate_pair_in_a_surround_stream_is_flagged(self) -> None:
        channel_rms = [-20.0, -20.0, -18.0]
        pairs = [(0, 1), (0, 2), (1, 2)]
        pair_rms = [DIGITAL_SILENCE_DB, -22.0, -22.0]
        flagged = assess_duplicate_risk(channel_rms, pair_rms, pairs)
        assert [(p.channel_a, p.channel_b) for p in flagged] == [(0, 1)]
