"""FFprobe normalization helpers (pure functions, no subprocess)."""

from deepdub_qc.detectors.metadata.ffprobe import (
    build_media_summary,
    normalize_container_format,
    parse_frame_rate,
)

PARSED = {
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "2.002000",
        "bit_rate": "1234567",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "24000/1001",
            "pix_fmt": "yuv420p",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "pcm_s16le",
            "sample_rate": "48000",
            "channels": 2,
            "channel_layout": "stereo",
            "tags": {"language": "deu"},
        },
    ],
}


class TestParseFrameRate:
    def test_rational_ntsc(self) -> None:
        assert parse_frame_rate("24000/1001") == (23.976, "24000/1001")

    def test_integer_rate(self) -> None:
        assert parse_frame_rate("25/1") == (25.0, "25/1")

    def test_degenerate_values(self) -> None:
        assert parse_frame_rate("0/0")[0] is None
        assert parse_frame_rate(None)[0] is None
        assert parse_frame_rate("garbage")[0] is None


class TestNormalizeContainerFormat:
    def test_extension_resolves_demuxer_group(self) -> None:
        assert normalize_container_format("mov,mp4,m4a,3gp,3g2,mj2", "mov") == "mov"
        assert normalize_container_format("mov,mp4,m4a,3gp,3g2,mj2", "mp4") == "mp4"

    def test_unknown_extension_falls_back_to_first(self) -> None:
        assert normalize_container_format("mov,mp4,m4a,3gp,3g2,mj2", "xyz") == "mov"

    def test_single_format_passthrough(self) -> None:
        assert normalize_container_format("mxf", "mxf") == "mxf"
        assert normalize_container_format(None, "mov") is None


class TestBuildMediaSummary:
    def test_stream_maps_and_timecode_rate(self) -> None:
        summary = build_media_summary(PARSED)
        assert summary["timecode_frame_rate"] == 23.976
        assert summary["container"]["duration_seconds"] == 2.002
        video = summary["video_streams"][0]
        assert video["resolution"] == "1920x1080"
        assert video["frame_rate"] == 23.976
        audio = summary["audio_streams"][0]
        assert audio["sample_rate"] == 48000
        assert audio["language"] == "deu"
        assert summary["subtitle_streams"] == []
