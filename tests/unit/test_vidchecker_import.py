"""Vidchecker template importer contract (ADR-025).

The importer must translate faithfully (severity, track selection, thresholds),
must never reference unimplemented parameters, and must fail loudly on a check
type it does not know - silent drops are how template content disappears.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deepdub_qc.models.parameters import CATALOGUE, ImplementationStatus  # noqa: E402
from deepdub_qc.presets.loader import load_preset  # noqa: E402
from import_vidchecker_templates import (  # noqa: E402
    SOURCE_DIR,
    render_preset,
    translate_template,
)

XSI = 'xmlns:i="http://www.w3.org/2001/XMLSchema-instance"'


def template(body: str) -> ET.Element:
    return ET.fromstring(f'<Template sourceId="999" name="synthetic" {XSI}>{body}</Template>')


AUDIO_GROUP = """
<AudioTests>
  <AudioTest>
    <TrackSelectTest><Selector>1</Selector><SelectorType>TrackIndex</SelectorType></TrackSelectTest>
    <AudioCodecTest><AudioCodec>Pcm</AudioCodec><RejectOnError>true</RejectOnError></AudioCodecTest>
    <AudioBitDepthTest><BitDepth>24</BitDepth><RejectOnError>false</RejectOnError></AudioBitDepthTest>
    <AudioSampleRateTest><SampleRate>48</SampleRate><RejectOnError>false</RejectOnError></AudioSampleRateTest>
    <AudioLoudnessITest>
      <LoudnessLevel>-24</LoudnessLevel><LoudnessTolerance>2</LoudnessTolerance>
      <Mode>LoudnessModeEbuI</Mode><RejectOnError>false</RejectOnError>
    </AudioLoudnessITest>
    <DualMonoDetectionTest><Window>5</Window><RejectOnError>false</RejectOnError></DualMonoDetectionTest>
  </AudioTest>
</AudioTests>
"""


class TestAudioTranslation:
    def test_codec_and_bit_depth_fold_into_pcm_token(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        codec = next(r for r in result.rules if r["rule_id"] == "audio-codec")
        assert codec["operator"] == "in"
        assert codec["expected"]["values"] == ["pcm_s24le", "pcm_s24be"]

    def test_sample_rate_converted_to_hz(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        rate = next(r for r in result.rules if r["rule_id"] == "audio-sample-rate")
        assert rate["expected"]["value"] == 48000

    def test_loudness_tolerance_becomes_between_range(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        loudness = next(r for r in result.rules if r["rule_id"] == "integrated-loudness")
        assert loudness["operator"] == "between"
        assert loudness["expected"]["min"] == -26
        assert loudness["expected"]["max"] == -22

    def test_reject_on_error_maps_to_severity(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        codec = next(r for r in result.rules if r["rule_id"] == "audio-codec")
        assert "severity" not in codec, "RejectOnError=true keeps the blocking-error default"
        rate = next(r for r in result.rules if r["rule_id"] == "audio-sample-rate")
        assert rate["severity"] == "warning"
        assert rate["blocking"] is False

    def test_single_default_group_applies_to_all_streams(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        codec = next(r for r in result.rules if r["rule_id"] == "audio-codec")
        assert codec["applies_to"] == {"stream_type": "audio", "quantifier": "all"}

    def test_uncovered_checks_are_recorded_not_dropped(self) -> None:
        result = translate_template(template(AUDIO_GROUP))
        assert any("DualMonoDetection" in item for item in result.uncovered)

    def test_multi_track_selectors_convert_to_zero_based_indices(self) -> None:
        two_tracks = AUDIO_GROUP.replace(
            "</AudioTests>",
            """<AudioTest>
                 <TrackSelectTest><Selector>2</Selector><SelectorType>TrackIndex</SelectorType></TrackSelectTest>
                 <AudioSampleRateTest><SampleRate>48</SampleRate><RejectOnError>false</RejectOnError></AudioSampleRateTest>
               </AudioTest></AudioTests>""",
        )
        result = translate_template(template(two_tracks))
        rates = [r for r in result.rules if r["rule_id"].startswith("audio-sample-rate")]
        indices = sorted(r["applies_to"]["selector"]["index"] for r in rates)
        assert indices == [0, 1]


TIER1_VIDEO = """
<FileTests>
  <FileBitrateTest><FileBitrateLower>48</FileBitrateLower><FileBitrateUpper>52</FileBitrateUpper>
    <RejectOnError>false</RejectOnError></FileBitrateTest>
  <StartTimecodeTest><RangeMethod>StartTcAt</RangeMethod>
    <Hours>0</Hours><Minutes>59</Minutes><Seconds>30</Seconds><Frames>0</Frames>
    <FramesTolerance>0</FramesTolerance><RejectOnError>true</RejectOnError></StartTimecodeTest>
</FileTests>
<VideoTests>
  <VideoCodecTest><VideoCodec>ProRes</VideoCodec><VideoProfile>ProResHq</VideoProfile>
    <VideoLevel>VideoLevelNone</VideoLevel><RejectOnError>true</RejectOnError></VideoCodecTest>
  <VideoBitDepthTest><BitDepth>10</BitDepth><RejectOnError>false</RejectOnError></VideoBitDepthTest>
  <FrameAspectRatioTest><FrameAspectRatioNumerator>16</FrameAspectRatioNumerator>
    <FrameAspectRatioDenominator>9</FrameAspectRatioDenominator>
    <RejectOnError>false</RejectOnError></FrameAspectRatioTest>
  <VideoBitrateTest><VideoBitrateLower>100</VideoBitrateLower>
    <VideoBitrateUpper>110</VideoBitrateUpper><RejectOnError>false</RejectOnError></VideoBitrateTest>
</VideoTests>
"""


class TestTierOneTranslations:
    def test_file_bitrate_converted_to_bits_per_second(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "overall-bitrate")
        assert rule["expected"]["min"] == 48_000_000
        assert rule["expected"]["max"] == 52_000_000

    def test_start_timecode_formats_smpte(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "start-timecode")
        assert rule["expected"]["value"] == "00:59:30:00"

    def test_video_profile_maps_to_ffprobe_string(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "video-profile")
        assert rule["expected"]["value"] == "HQ"
        assert not any(r["rule_id"] == "video-level" for r in result.rules), (
            "VideoLevelNone must not produce a level rule"
        )

    def test_bit_depth_uses_real_parameter(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "video-bit-depth")
        assert rule["parameter_id"] == "video.bit_depth"
        assert rule["expected"]["value"] == 10

    def test_display_aspect_ratio(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "display-aspect-ratio")
        assert rule["expected"]["value"] == "16:9"

    def test_video_bitrate_range(self) -> None:
        result = translate_template(template(TIER1_VIDEO))
        rule = next(r for r in result.rules if r["rule_id"] == "video-bitrate")
        assert rule["expected"] == {"min": 100_000_000, "max": 110_000_000, "unit": "bit/s"}


class TestFailLoudly:
    def test_unknown_check_raises_instead_of_dropping(self) -> None:
        unknown = template("<VideoTests><BrandNewShinyTest/></VideoTests>")
        with pytest.raises(RuntimeError, match="BrandNewShinyTest"):
            translate_template(unknown)


class TestGeneratedOutput:
    def test_render_produces_a_loadable_preset(self, tmp_path: Path) -> None:
        result = translate_template(template(AUDIO_GROUP))
        text = render_preset(
            999, "synthetic", "testclient", "test_synthetic", "audio_delivery", result, None
        )
        target = tmp_path / "synthetic_v1.yaml"
        target.write_text(text, encoding="utf-8")
        preset = load_preset(target)
        assert preset.preset.status.value == "draft"
        assert len(preset.rules) == len(result.rules)


class TestCommittedArchive:
    """The committed source archive must stay translatable end to end."""

    def test_every_template_translates_without_error(self) -> None:
        source = SOURCE_DIR / "templates-combined.xml"
        assert source.is_file(), "missing presets/_sources/vidchecker/templates-combined.xml"
        implemented = {
            pid
            for pid, definition in CATALOGUE.items()
            if definition.implementation is ImplementationStatus.IMPLEMENTED
        }
        translated = 0
        for element in ET.parse(source).getroot().findall("Template"):
            result = translate_template(element)
            for rule in result.rules:
                assert rule["parameter_id"] in implemented, (
                    f"{element.get('name')}: rule {rule['rule_id']} references "
                    f"unimplemented parameter {rule['parameter_id']}"
                )
            if result.rules:
                translated += 1
        assert translated >= 50, f"only {translated} templates produced rules"
