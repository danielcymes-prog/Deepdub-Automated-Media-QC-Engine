"""Translate Vidchecker templates into draft QC presets (ADR-025).

The authoritative source is the Vidchecker 8.2.2 template export captured from
the production instance on 2026-07-27 (``presets/_sources/vidchecker/``). Each
template becomes one draft preset: checks that map onto IMPLEMENTED catalogue
parameters become rules; everything else is recorded as an uncovered check in
the preset header and in the generated coverage report
(``docs/vidchecker-import.md``). Nothing is silently dropped.

Translation policy (mirrors the hand-made marimba translations):
- Only IMPLEMENTED parameters are referenced; a rule over a planned parameter
  is a preset validation error by design (ADR-021).
- Vidchecker ``RejectOnError=true`` -> blocking error; ``false`` -> non-blocking
  warning.
- Vidchecker audio track selectors are 1-based; ``TrackUsePrevious`` inherits
  the previous group's track. A template whose only audio group selects track 1
  applies its audio rules to ALL audio streams (marimba precedent); anything
  else pins rules to the selected stream index.
- ALL thresholds are placeholders pending human approval (handoff section 30):
  every generated preset is ``status: draft``.

Usage:
    uv run python scripts/import_vidchecker_templates.py           # write missing
    uv run python scripts/import_vidchecker_templates.py --force   # rewrite generated presets

Existing preset files are never overwritten without --force, so hand-refined
translations survive re-runs. The coverage report is always rewritten.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from deepdub_qc.models.parameters import CATALOGUE, ImplementationStatus  # noqa: E402
from deepdub_qc.presets.loader import load_preset  # noqa: E402

SOURCE_DIR = REPO_ROOT / "presets" / "_sources" / "vidchecker"
LIBRARY_DIR = REPO_ROOT / "presets" / "library" / "vidchecker"
CLIENTS_DIR = REPO_ROOT / "presets" / "clients"
COVERAGE_DOC = REPO_ROOT / "docs" / "vidchecker-import.md"

NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
EXTRACTION_DATE = "2026-07-27"

#: Deepdub-authored templates: vidchecker id -> (client, preset_id, file_stem).
#: Client attribution confirmed by the operator on 2026-07-27.
CUSTOM_TEMPLATES = {
    110: ("topic", "topic_delivery", "delivery"),
    112: ("deepdub-internal", "deepdub_audio_stereo_test", "audio_stereo_test"),
    113: ("vanda", "vanda_51_audio", "51_audio"),
    114: ("vanda", "vanda_20_audio", "20_audio"),
    117: ("marimba", "marimba_delivery_51_audio", "delivery_51_audio"),
}

#: Templates already translated by hand and refined against real reports;
#: regenerating them would clobber that work (presets/clients/marimba/).
ALREADY_TRANSLATED = {
    115: "presets/clients/marimba/deliver_audio_v1.yaml",
    116: "presets/clients/marimba/delivery_v1.yaml",
}

VIDEO_CODECS = {
    "Dnxhd": "dnxhd",
    "DvcPro50": "dvvideo",
    "H264": "h264",
    "Jpeg2000": "jpeg2000",
    "Mpeg2": "mpeg2video",
    "ProRes": "prores",
}

CONTAINERS = {"Mov": "mov", "Mxf": "mxf", "Imf": "mxf"}

#: Vidchecker profile/level names -> ffprobe's reported strings (see the
#: video.profile / video.level catalogue limitations).
VIDEO_PROFILES = {
    "H264High422Intra": "High 4:2:2 Intra",
    "Mpeg2422": "4:2:2",
    "Mpeg2Main": "Main",
    "ProResHq": "HQ",
}
VIDEO_LEVELS = {
    "H264Level41": "41",
    "Mpeg2LevelHigh": "4",
    "Mpeg2LevelMain": "8",
}

CHANNEL_LAYOUTS: dict[tuple[str, ...], list[str]] = {
    ("Left", "Right"): ["stereo"],
    ("Center",): ["mono"],
    (
        "Left",
        "Right",
        "Center",
        "LFE",
        "LeftSurround",
        "RightSurround",
    ): ["5.1", "5.1(side)"],
}

#: Checks with no implemented counterpart. The reason is binding documentation:
#: it lands in the preset header and the coverage report.
UNCOVERED_CHECKS = {
    "AdvancedGopLengthTest": "GOP structure is not inspected (no bitstream detector)",
    "AudioBitrateTest": "audio stream bitrate is not measured",
    "AudioPhaseTest": "audio.phase_correlation is planned, no detector yet",
    "AudioTransientTest": "clicks-and-pops detection is not implemented",
    "ClosedCaps708Test": "closed-caption (CEA-708) presence is not inspected",
    "ContainerDropFrameTest": "container drop-frame flag is not rule-addressable",
    "ContainerEssenceConsistencyTest": "container/essence consistency is not inspected",
    "DualMonoDetectionTest": "audio.duplicate_channel_risk is planned, no detector yet",
    "EnhancedSyntaxTest": "codec bitstream syntax is not inspected",
    "GopLengthTest": "GOP length is not inspected (no bitstream detector)",
    "ITunesCompatibilityTest": "iTunes package conformance is not implemented",
    "ImfConformanceTest": "IMF conformance (Photon) is not implemented",
    "MxfOpTest": "MXF operational pattern is not inspected",
    "MxfTest": "MXF structural checks are not implemented",
    "NetflixPhotonTest": "IMF conformance (Photon) is not implemented",
    "SingleSampleDescriptionTest": "QuickTime sample description count is not inspected",
    "SpsPpsTest": "H.264 SPS/PPS conformance is not inspected",
    "VideoBitRateModeTest": "CBR/VBR mode is not rule-addressable",
    "VideoDropFrameTest": "video drop-frame flag is not rule-addressable",
    # VideoTest sub-tests
    "BlackLevelTest": "legal-level analysis (video.signal_range_event) is planned",
    "BlankingTest": "VBI blanking analysis is not implemented",
    "BlockinessTest": "blockiness analysis is not implemented",
    "CadenceTest": "cadence analysis is not implemented",
    "ChromaLevelTest": "legal-level analysis (video.signal_range_event) is planned",
    "ColourBarsTest": "colour-bars detection is not implemented",
    "CorruptFrameTest": "video.corrupt_frame_event is planned, no detector yet (backlog #36)",
    "DeadPixelTest": "dead-pixel analysis is not implemented",
    "DigitalDropoutTest": "digital dropout detection is not implemented",
    "DropoutTest": "analogue dropout detection is not implemented",
    "FlashTest": "PSE/flashing analysis is not implemented",
    "HdrTest": "HDR metadata checks are planned, no detector yet",
    "LetterboxingTest": "video.letterbox_detected is planned, no detector yet",
    "LossOfChromaTest": "loss-of-chroma detection is not implemented",
    "MediaOfflineTest": "media-offline slate detection is not implemented",
    "RgbGamutTest": "legal-level analysis (video.signal_range_event) is planned",
    "SDRInHDRTest": "SDR-in-HDR detection is not implemented",
    "SingleColorTest": "single-colour frame detection is not implemented",
    "StripeTest": "stripe detection is not implemented",
    "VideoSegmentDetectionTest": "segment detection is not implemented",
}

#: Vidchecker processing directives, not checks: nothing to translate and
#: nothing missing. Selector handling happens in the audio-group walk.
DIRECTIVES = {
    "AudioGroup",
    "AudioLayoutTest",
    "DolbyProgramSelectTest",
    "ForceColorSpaceTest",
    "IgnoreVbiTest",
    "TrackIdTest",
    "TrackSelectTest",
    "UseStartTimecodeTest",
    "VideoLayoutTest",
}


@dataclass
class Translation:
    """Everything one template translates into."""

    rules: list[dict] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _implemented(parameter_id: str) -> str:
    """Guard: the generator itself must not reference unimplemented parameters."""
    definition = CATALOGUE.get(parameter_id)
    if definition is None or definition.implementation is not ImplementationStatus.IMPLEMENTED:
        msg = f"generator bug: {parameter_id} is not an implemented parameter"
        raise RuntimeError(msg)
    return parameter_id


def _is_nil(element: ET.Element | None) -> bool:
    return element is None or element.get(NIL) == "true"


def _text(element: ET.Element, path: str) -> str | None:
    found = element.find(path)
    if _is_nil(found):
        return None
    assert found is not None
    return (found.text or "").strip()


def _float(element: ET.Element, path: str) -> float | None:
    raw = _text(element, path)
    return float(raw) if raw not in (None, "") else None


def _flag(element: ET.Element, path: str, default: bool = False) -> bool:
    raw = _text(element, path)
    return default if raw is None else raw == "true"


def _severity(element: ET.Element) -> dict:
    """RejectOnError=true -> blocking error (the preset default); false ->
    non-blocking warning, stated explicitly."""
    if _flag(element, "RejectOnError"):
        return {}
    return {"severity": "warning", "blocking": False}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return re.sub(r"_+", "_", slug)


# --------------------------------------------------------------------------- audio group tests


def _translate_audio_test(  # noqa: PLR0912, PLR0915 - one branch per Vidchecker check type
    group: ET.Element, applies_to: dict, suffix: str, out: Translation
) -> None:
    """Translate one Vidchecker AudioTest group into per-stream rules."""

    def add(rule: dict) -> None:
        rule["rule_id"] = rule["rule_id"] + suffix
        out.rules.append(rule)

    codec = group.find("AudioCodecTest")
    bit_depth = None
    bd_test = group.find("AudioBitDepthTest")
    if not _is_nil(bd_test):
        assert bd_test is not None
        bit_depth = _text(bd_test, "BitDepth")
    if not _is_nil(codec):
        assert codec is not None
        codec_name = _text(codec, "AudioCodec")
        if codec_name != "Pcm":
            out.uncovered.append(f"Audio Codec {codec_name}: only PCM has a mapping")
        elif bit_depth is not None:
            # Vidchecker checks codec and bit depth separately; audio.bit_depth
            # is a planned parameter, but the ffprobe codec token encodes both.
            add(
                {
                    "rule_id": "audio-codec",
                    "parameter_id": _implemented("audio.codec"),
                    "operator": "in",
                    "expected": {"values": [f"pcm_s{bit_depth}le", f"pcm_s{bit_depth}be"]},
                    "applies_to": applies_to,
                    "display_name": f"Audio Codec (PCM {bit_depth}-bit)",
                    **_severity(codec),
                }
            )
        else:
            add(
                {
                    "rule_id": "audio-codec",
                    "parameter_id": _implemented("audio.codec"),
                    "operator": "regex",
                    "expected": {"pattern": "^pcm_"},
                    "applies_to": applies_to,
                    "display_name": "Audio Codec (PCM)",
                    **_severity(codec),
                }
            )
    elif bit_depth is not None:
        assert bd_test is not None
        add(
            {
                "rule_id": "audio-bit-depth",
                "parameter_id": _implemented("audio.codec"),
                "operator": "regex",
                "expected": {"pattern": f"^pcm_[sfu]{bit_depth}"},
                "applies_to": applies_to,
                "display_name": f"Audio Bit Depth ({bit_depth}-bit, via PCM codec token)",
                **_severity(bd_test),
            }
        )

    rate = group.find("AudioSampleRateTest")
    if not _is_nil(rate):
        assert rate is not None
        khz = _float(rate, "SampleRate") or 0
        add(
            {
                "rule_id": "audio-sample-rate",
                "parameter_id": _implemented("audio.sample_rate"),
                "operator": "equals",
                "expected": {"value": int(khz * 1000), "unit": "Hz"},
                "applies_to": applies_to,
                "display_name": "Sample Rate",
                **_severity(rate),
            }
        )

    channels = group.find("AudioChannelsTest")
    if not _is_nil(channels):
        assert channels is not None
        count = _text(channels, "NumberOfChannels")
        add(
            {
                "rule_id": "audio-channel-count",
                "parameter_id": _implemented("audio.channel_count"),
                "operator": "equals",
                "expected": {"value": int(count or 0)},
                "applies_to": applies_to,
                "display_name": "Channel Count",
                **_severity(channels),
            }
        )

    positions = group.find("AudioChannelPositionsTest")
    if not _is_nil(positions):
        assert positions is not None
        declared = tuple(
            (p.text or "").strip()
            for p in positions.findall("ChanPositions/ChanPos")
            if (p.text or "").strip() not in ("", "Any")
        )
        layouts = CHANNEL_LAYOUTS.get(declared)
        if layouts is None:
            out.uncovered.append(
                f"Audio Channel Positions {'/'.join(declared)}: no channel-layout mapping"
            )
        else:
            add(
                {
                    "rule_id": "audio-channel-layout",
                    "parameter_id": _implemented("audio.channel_layout"),
                    "operator": "in",
                    "expected": {"values": layouts},
                    "applies_to": applies_to,
                    "display_name": f"Channel Layout ({layouts[0]})",
                    **_severity(positions),
                }
            )

    loudness = group.find("AudioLoudnessITest")
    if not _is_nil(loudness):
        assert loudness is not None
        level = _float(loudness, "LoudnessLevel") or 0.0
        tolerance = _float(loudness, "LoudnessTolerance") or 0.0
        mode = _text(loudness, "Mode") or ""
        standard = "EBU R128" if mode == "LoudnessModeEbuI" else "ITU-R BS.1770"
        add(
            {
                "rule_id": "integrated-loudness",
                "parameter_id": _implemented("audio.integrated_loudness"),
                "operator": "between",
                "expected": {"min": level - tolerance, "max": level + tolerance, "unit": "LUFS"},
                "applies_to": applies_to,
                "display_name": f"Integrated Loudness ({level:g} ±{tolerance:g} LUFS)",
                "description": f"Vidchecker mode: {standard}. Measured per stream; "
                "multi-mono channel groups need audio.group_integrated_loudness "
                "(planned, backlog #35).",
                **_severity(loudness),
            }
        )

    momentary = group.find("AudioLoudnessMTest")
    if not _is_nil(momentary):
        assert momentary is not None
        level = _float(momentary, "LoudnessLevel") or 0.0
        add(
            {
                "rule_id": "max-momentary-loudness",
                "parameter_id": _implemented("audio.max_momentary_loudness"),
                "operator": "less_than_or_equal",
                "expected": {"value": level, "unit": "LUFS"},
                "applies_to": applies_to,
                "display_name": "Max Momentary Loudness",
                **_severity(momentary),
            }
        )

    short_term = group.find("AudioLoudnessSTest")
    if not _is_nil(short_term):
        assert short_term is not None
        level = _float(short_term, "LoudnessLevel") or 0.0
        add(
            {
                "rule_id": "max-short-term-loudness",
                "parameter_id": _implemented("audio.max_short_term_loudness"),
                "operator": "less_than_or_equal",
                "expected": {"value": level, "unit": "LUFS"},
                "applies_to": applies_to,
                "display_name": "Max Short-Term Loudness",
                **_severity(short_term),
            }
        )

    lra = group.find("AudioLoudnessRangeTest")
    if not _is_nil(lra):
        assert lra is not None
        if _flag(lra, "DoMax"):
            add(
                {
                    "rule_id": "loudness-range-max",
                    "parameter_id": _implemented("audio.loudness_range"),
                    "operator": "less_than_or_equal",
                    "expected": {"value": _float(lra, "RangeMax") or 0.0, "unit": "LU"},
                    "applies_to": applies_to,
                    "display_name": "Loudness Range (max)",
                    **_severity(lra),
                }
            )
        if _flag(lra, "DoMin"):
            add(
                {
                    "rule_id": "loudness-range-min",
                    "parameter_id": _implemented("audio.loudness_range"),
                    "operator": "greater_than_or_equal",
                    "expected": {"value": _float(lra, "RangeMin") or 0.0, "unit": "LU"},
                    "applies_to": applies_to,
                    "display_name": "Loudness Range (min)",
                    **_severity(lra),
                }
            )

    peak = group.find("AudioPeakLevelTest")
    if not _is_nil(peak):
        assert peak is not None
        true_peak = _text(peak, "Unit") == "TruePeak"
        parameter = "audio.true_peak" if true_peak else "audio.peak_level"
        unit = "dBTP" if true_peak else "dBFS"
        if _flag(peak, "MaxPeakLevelEnabled"):
            add(
                {
                    "rule_id": "max-peak-level",
                    "parameter_id": _implemented(parameter),
                    "operator": "less_than_or_equal",
                    "expected": {"value": _float(peak, "MaxPeakLevel") or 0.0, "unit": unit},
                    "applies_to": applies_to,
                    "display_name": f"Peak Level ({'True Peak' if true_peak else 'Sample Peak'})",
                    **_severity(peak),
                }
            )
        if _flag(peak, "MinPeakLevelEnabled"):
            add(
                {
                    "rule_id": "min-peak-level",
                    "parameter_id": _implemented(parameter),
                    "operator": "greater_than_or_equal",
                    "expected": {"value": _float(peak, "MinPeakLevel") or 0.0, "unit": unit},
                    "applies_to": applies_to,
                    "display_name": "Minimum Peak Level",
                    **_severity(peak),
                }
            )

    clipping = group.find("AudioClippingTest")
    if not _is_nil(clipping):
        assert clipping is not None
        sensitivity = _text(clipping, "Sensitivity") or "Medium"
        # audio.clipping_event is planned; the marimba translation surfaces
        # clipping via the whole-stream astats indicators instead.
        add(
            {
                "rule_id": "clipping-flat-factor",
                "parameter_id": _implemented("audio.flat_factor"),
                "operator": "less_than_or_equal",
                "expected": {"value": 0.01},
                "applies_to": applies_to,
                "display_name": "Clipping (Flat Factor)",
                "description": f"Vidchecker clipping sensitivity: {sensitivity}. "
                "Whole-stream indicator, not per-event (audio.clipping_event is planned).",
                **_severity(clipping),
            }
        )
        add(
            {
                "rule_id": "clipping-peak-level",
                "parameter_id": _implemented("audio.peak_level"),
                "operator": "less_than_or_equal",
                "expected": {"value": -0.1, "unit": "dBFS"},
                "applies_to": applies_to,
                "display_name": "Clipping (Sample Peak)",
                **_severity(clipping),
            }
        )

    min_level = group.find("AudioMinLevelDurationTest")
    if not _is_nil(min_level):
        assert min_level is not None
        duration = _float(min_level, "Duration") or 0.0
        level = _float(min_level, "Level") or 0.0
        description = None
        if level != -90:
            description = (
                f"Vidchecker level was {level:g} dBFS; the windowed-RMS detector "
                "threshold is fixed at -90 dB (parameter caveat), so this rule "
                "approximates the original check."
            )
        rule = {
            "rule_id": "min-level",
            "parameter_id": _implemented("audio.low_rms_event"),
            "operator": "less_than_or_equal",
            "expected": {"value": duration, "unit": "s"},
            "applies_to": applies_to,
            "display_name": "Min Level (Windowed RMS)",
            **_severity(min_level),
        }
        if description:
            rule["description"] = description
        add(rule)

    silence = group.find("DigitalSilenceWholeTrackTest")
    if not _is_nil(silence):
        assert silence is not None
        threshold = _float(silence, "SilenceThreshold") or -70.0
        if _text(silence, "MustOrMustNotBeSilent") == "Must":
            add(
                {
                    "rule_id": "whole-track-silence",
                    "parameter_id": _implemented("audio.peak_level"),
                    "operator": "less_than_or_equal",
                    "expected": {"value": threshold, "unit": "dBFS"},
                    "applies_to": applies_to,
                    "display_name": "Track Must Be Silent",
                    "description": "Vidchecker requires digital silence on this track; "
                    "approximated as a sample-peak ceiling.",
                    **_severity(silence),
                }
            )
        else:
            out.uncovered.append("Digital Silence (must NOT be silent): no mapping")

    length = group.find("AudioLengthTest")
    if not _is_nil(length):
        assert length is not None
        add(
            {
                "rule_id": "audio-video-length",
                "parameter_id": _implemented("audio.video_duration_delta"),
                "operator": "approximately_equals",
                "expected": {"value": 0.0, "tolerance": 0.5, "unit": "s"},
                "applies_to": applies_to,
                "display_name": "Audio/Video Duration Match",
                "description": "Tolerance 0.5 s is a placeholder; Vidchecker's "
                "template carries no explicit tolerance.",
                **_severity(length),
            }
        )

    for check, reason in (
        ("AudioPhaseTest", UNCOVERED_CHECKS["AudioPhaseTest"]),
        ("DualMonoDetectionTest", UNCOVERED_CHECKS["DualMonoDetectionTest"]),
        ("AudioTransientTest", UNCOVERED_CHECKS["AudioTransientTest"]),
        ("AudioBitrateTest", UNCOVERED_CHECKS["AudioBitrateTest"]),
    ):
        if not _is_nil(group.find(check)):
            out.uncovered.append(f"{check.removesuffix('Test')}: {reason}")


# --------------------------------------------------------------------------- video / file tests


def _translate_video_incidents(container: ET.Element, out: Translation) -> None:  # noqa: PLR0912
    """VideoTest is a container of incident sub-tests (black, freeze, ...)."""
    black = container.find("BlackFrameTest")
    if not _is_nil(black):
        assert black is not None
        if _text(black, "RequiredOrAllowed") == "Required":
            out.uncovered.append(
                "Black Frame (required black segments): positional requirements "
                "are not expressible; only maximum-duration caps are"
            )
        else:
            max_allowed = _float(black, "MaxTimeAllowed") or 0.0
            in_frames = _text(black, "MaxTimeAllowedSecsOrFrames") == "Frames"
            if in_frames:
                out.uncovered.append(
                    "Black Frame (frame-denominated duration): only second-denominated "
                    "caps are translated"
                )
            elif max_allowed > 0:
                out.rules.append(
                    {
                        "rule_id": "black-frames",
                        "parameter_id": _implemented("video.black_frame_event"),
                        "operator": "less_than_or_equal",
                        "expected": {"value": max_allowed, "unit": "s"},
                        "applies_to": {"stream_type": "video", "quantifier": "all"},
                        "display_name": "Black Frame Spans",
                        "description": "Start/end-range allowances from the Vidchecker "
                        "template are not replicated; this caps every black span.",
                        **_severity(black),
                    }
                )
            else:
                out.rules.append(
                    {
                        "rule_id": "black-frames",
                        "parameter_id": _implemented("video.black_frame_event"),
                        "operator": "not_exists",
                        "applies_to": {"stream_type": "video", "quantifier": "all"},
                        "display_name": "No Black Frames",
                        **_severity(black),
                    }
                )

    freeze = container.find("FreezeFrameTest")
    if not _is_nil(freeze):
        assert freeze is not None
        max_allowed = _float(freeze, "MaxTimeAllowed") or 0.0
        rule = {
            "rule_id": "freeze-frames",
            "parameter_id": _implemented("video.freeze_frame_event"),
            "applies_to": {"stream_type": "video", "quantifier": "all"},
            "display_name": "Freeze Frame Spans",
            "description": "Legitimate static content (title cards, slates) registers "
            "as frozen - see the parameter caveat.",
            **_severity(freeze),
        }
        if max_allowed > 0:
            rule |= {
                "operator": "less_than_or_equal",
                "expected": {"value": max_allowed, "unit": "s"},
            }
        else:
            rule |= {"operator": "not_exists"}
        out.rules.append(rule)

    field_order = container.find("FieldOrderTest")
    if not _is_nil(field_order):
        assert field_order is not None
        flagged = _text(field_order, "FlaggedFieldOrder") or "UnknownFieldOrder"
        expected = {"Progressive": "progressive", "TopFieldFirst": "tff"}.get(flagged)
        if expected is None:
            out.uncovered.append(f"Field Order (flagged {flagged}): no field-order mapping")
        else:
            out.rules.append(
                {
                    "rule_id": "field-order",
                    "parameter_id": _implemented("video.field_order"),
                    "operator": "equals",
                    "expected": {"value": expected},
                    "applies_to": {"stream_type": "video", "quantifier": "all"},
                    "display_name": f"Field Order ({expected})",
                    "description": "Checks the declared stream flags; baseband "
                    "field-dominance analysis is not implemented.",
                    **_severity(field_order),
                }
            )

    handled = ("BlackFrameTest", "FreezeFrameTest", "FieldOrderTest")
    for child in container:
        if _is_nil(child) or child.tag in handled:
            continue
        if child.tag in DIRECTIVES:
            continue
        reason = UNCOVERED_CHECKS.get(child.tag)
        if reason is None:
            msg = f"unhandled VideoTest sub-test: {child.tag}"
            raise RuntimeError(msg)
        out.uncovered.append(f"{child.tag.removesuffix('Test')}: {reason}")


def _translate_flat_test(element: ET.Element, out: Translation) -> None:  # noqa: PLR0912, PLR0915
    """Translate one direct child of FileTests/VideoTests."""
    tag = element.tag

    if tag == "ContainerTest":
        declared = _text(element, "Container") or ""
        mapped = CONTAINERS.get(declared)
        if mapped is None:
            out.uncovered.append(f"Container {declared}: no container.format mapping")
            return
        rule = {
            "rule_id": "container-format",
            "parameter_id": _implemented("container.format"),
            "operator": "equals",
            "expected": {"value": mapped},
            "display_name": "Container Format",
            **_severity(element),
        }
        if declared == "Imf":
            rule["description"] = (
                "Vidchecker checked for an IMF package; the container probe "
                "normalizes IMF track files to mxf. Package-level IMF conformance "
                "is not covered."
            )
        out.rules.append(rule)

    elif tag == "VideoCodecTest":
        declared = _text(element, "VideoCodec") or ""
        mapped = VIDEO_CODECS.get(declared)
        if mapped is None:
            out.uncovered.append(f"Video Codec {declared}: no video.codec mapping")
        else:
            out.rules.append(
                {
                    "rule_id": "video-codec",
                    "parameter_id": _implemented("video.codec"),
                    "operator": "equals",
                    "expected": {"value": mapped},
                    "applies_to": {"stream_type": "video", "quantifier": "all"},
                    "display_name": f"Video Codec ({declared})",
                    **_severity(element),
                }
            )
        profile = _text(element, "VideoProfile") or "VideoProfileNone"
        level = _text(element, "VideoLevel") or "VideoLevelNone"
        if profile != "VideoProfileNone":
            ffprobe_profile = VIDEO_PROFILES.get(profile)
            if ffprobe_profile is None:
                out.uncovered.append(f"Video Profile {profile}: no ffprobe profile mapping")
            else:
                out.rules.append(
                    {
                        "rule_id": "video-profile",
                        "parameter_id": _implemented("video.profile"),
                        "operator": "equals",
                        "expected": {"value": ffprobe_profile},
                        "applies_to": {"stream_type": "video", "quantifier": "all"},
                        "display_name": f"Video Profile ({profile})",
                        "description": "Compared against ffprobe's profile string - "
                        "see the video.profile catalogue limitations.",
                        **_severity(element),
                    }
                )
        if level != "VideoLevelNone":
            ffprobe_level = VIDEO_LEVELS.get(level)
            if ffprobe_level is None:
                out.uncovered.append(f"Video Level {level}: no ffprobe level mapping")
            else:
                out.rules.append(
                    {
                        "rule_id": "video-level",
                        "parameter_id": _implemented("video.level"),
                        "operator": "equals",
                        "expected": {"value": ffprobe_level},
                        "applies_to": {"stream_type": "video", "quantifier": "all"},
                        "display_name": f"Video Level ({level})",
                        "description": "ffprobe reports numeric level codes - "
                        "see the video.level catalogue limitations.",
                        **_severity(element),
                    }
                )

    elif tag == "FramesizeTest":
        width = int(_float(element, "HorizontalSize") or 0)
        height = int(_float(element, "VerticalSize") or 0)
        severity = _severity(element)
        out.rules.append(
            {
                "rule_id": "video-width",
                "parameter_id": _implemented("video.width"),
                "operator": "equals",
                "expected": {"value": width, "unit": "px"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": "Frame Width",
                **severity,
            }
        )
        out.rules.append(
            {
                "rule_id": "video-height",
                "parameter_id": _implemented("video.height"),
                "operator": "equals",
                "expected": {"value": height, "unit": "px"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": "Frame Height",
                **severity,
            }
        )

    elif tag == "FramerateTest":
        numerator = _float(element, "FramerateNumerator") or 0.0
        denominator = _float(element, "FramerateDenominator") or 1.0
        rate = round(numerator / denominator, 3)
        out.rules.append(
            {
                "rule_id": "frame-rate",
                "parameter_id": _implemented("video.frame_rate"),
                "operator": "approximately_equals",
                "expected": {"value": rate, "tolerance": 0.01, "unit": "fps"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Frame Rate ({rate:g} fps)",
                **_severity(element),
            }
        )

    elif tag == "ChromaSubsamplingTest":
        declared = _text(element, "Subsampling") or ""
        digits = declared.removeprefix("Chroma")
        out.rules.append(
            {
                "rule_id": "chroma-subsampling",
                "parameter_id": _implemented("video.pixel_format"),
                "operator": "contains",
                "expected": {"value": digits},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Chroma Subsampling ({digits})",
                "description": "Checked via the pixel-format token (e.g. yuv422p10le).",
                **_severity(element),
            }
        )

    elif tag == "VideoBitDepthTest":
        depth = int(_float(element, "BitDepth") or 0)
        out.rules.append(
            {
                "rule_id": "video-bit-depth",
                "parameter_id": _implemented("video.bit_depth"),
                "operator": "equals",
                "expected": {"value": depth, "unit": "bit"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Video Bit Depth ({depth}-bit)",
                **_severity(element),
            }
        )

    elif tag == "FrameAspectRatioTest":
        numerator = int(_float(element, "FrameAspectRatioNumerator") or 0)
        denominator = int(_float(element, "FrameAspectRatioDenominator") or 1)
        out.rules.append(
            {
                "rule_id": "display-aspect-ratio",
                "parameter_id": _implemented("video.display_aspect_ratio"),
                "operator": "equals",
                "expected": {"value": f"{numerator}:{denominator}"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Display Aspect Ratio ({numerator}:{denominator})",
                **_severity(element),
            }
        )

    elif tag == "PixelAspectRatioTest":
        numerator = int(_float(element, "PixelAspectRatioNumerator") or 0)
        denominator = int(_float(element, "PixelAspectRatioDenominator") or 1)
        out.rules.append(
            {
                "rule_id": "sample-aspect-ratio",
                "parameter_id": _implemented("video.sample_aspect_ratio"),
                "operator": "equals",
                "expected": {"value": f"{numerator}:{denominator}"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Pixel Aspect Ratio ({numerator}:{denominator})",
                **_severity(element),
            }
        )

    elif tag == "VideoBitrateTest":
        lower = _float(element, "VideoBitrateLower") or 0.0
        upper = _float(element, "VideoBitrateUpper") or 0.0
        out.rules.append(
            {
                "rule_id": "video-bitrate",
                "parameter_id": _implemented("video.bitrate"),
                "operator": "between",
                "expected": {"min": lower * 1_000_000, "max": upper * 1_000_000, "unit": "bit/s"},
                "applies_to": {"stream_type": "video", "quantifier": "all"},
                "display_name": f"Video Bitrate ({lower:g}-{upper:g} Mbit/s)",
                "description": "Declared stream bitrate; streams without a declared "
                "bit rate skip this rule - see the video.bitrate catalogue "
                "limitations.",
                **_severity(element),
            }
        )

    elif tag == "FileBitrateTest":
        lower = _float(element, "FileBitrateLower") or 0.0
        upper = _float(element, "FileBitrateUpper") or 0.0
        out.rules.append(
            {
                "rule_id": "overall-bitrate",
                "parameter_id": _implemented("container.overall_bitrate"),
                "operator": "between",
                "expected": {"min": lower * 1_000_000, "max": upper * 1_000_000, "unit": "bit/s"},
                "display_name": f"Overall Bitrate ({lower:g}-{upper:g} Mbit/s)",
                **_severity(element),
            }
        )

    elif tag == "StartTimecodeTest":
        hours = int(_float(element, "Hours") or 0)
        minutes = int(_float(element, "Minutes") or 0)
        seconds = int(_float(element, "Seconds") or 0)
        frames = int(_float(element, "Frames") or 0)
        timecode = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
        tolerance = int(_float(element, "FramesTolerance") or 0)
        rule = {
            "rule_id": "start-timecode",
            "parameter_id": _implemented("container.timecode_start"),
            "operator": "equals",
            "expected": {"value": timecode},
            "display_name": f"Start Timecode ({timecode})",
            "description": "Drop-frame material reports its timecode with a ';' "
            "separator; adjust the expected value for drop-frame deliverables.",
            **_severity(element),
        }
        if tolerance:
            out.notes.append(
                f"Vidchecker allowed a {tolerance}-frame start-timecode tolerance; "
                "this rule requires an exact match."
            )
        out.rules.append(rule)

    elif tag == "AudioTracksTest":
        count = int(_float(element, "NumTracks") or 0)
        out.rules.append(
            {
                "rule_id": "audio-track-count",
                "parameter_id": _implemented("audio.stream_count"),
                "operator": "equals",
                "expected": {"value": count},
                "display_name": "Audio Track Count",
                **_severity(element),
            }
        )

    elif tag == "VideoTest":
        _translate_video_incidents(element, out)

    elif tag in DIRECTIVES:
        return

    else:
        reason = UNCOVERED_CHECKS.get(tag)
        if reason is None:
            msg = f"unhandled Vidchecker check: {tag}"
            raise RuntimeError(msg)
        out.uncovered.append(f"{tag.removesuffix('Test')}: {reason}")


# --------------------------------------------------------------------------- template walk


def translate_template(template: ET.Element) -> Translation:
    out = Translation()

    mxf = template.find("MxfTest")
    if not _is_nil(mxf):
        assert mxf is not None
        enabled = sum(1 for child in mxf if not _is_nil(child))
        out.uncovered.append(
            f"MXF structural checks ({enabled} sub-tests): {UNCOVERED_CHECKS['MxfTest']}"
        )

    for section in ("FileTests", "VideoTests"):
        parent = template.find(section)
        if _is_nil(parent):
            continue
        assert parent is not None
        for child in parent:
            if not _is_nil(child):
                _translate_flat_test(child, out)

    audio_tests = template.find("AudioTests")
    groups = [] if _is_nil(audio_tests) else list(audio_tests.findall("AudioTest"))  # type: ignore[union-attr]
    resolved: list[tuple[int, ET.Element]] = []
    previous_track = 1
    for group in groups:
        selector_type = _text(group, "TrackSelectTest/SelectorType") or "TrackIndex"
        selector = int(_float(group, "TrackSelectTest/Selector") or 1)
        track = previous_track if selector_type == "TrackUsePrevious" else max(selector, 1)
        previous_track = track
        resolved.append((track, group))

    # A single group on track 1 is the "check the programme audio" idiom; the
    # marimba translations apply those rules to every audio stream. Anything
    # more specific pins rules to the Vidchecker track (1-based -> 0-based).
    single_default_group = len(resolved) == 1 and resolved[0][0] == 1
    seen_tracks: dict[int, int] = {}
    for track, group in resolved:
        if single_default_group:
            applies_to = {"stream_type": "audio", "quantifier": "all"}
            suffix = ""
        else:
            applies_to = {"stream_type": "audio", "selector": {"index": track - 1}}
            occurrence = seen_tracks.get(track, 0) + 1
            seen_tracks[track] = occurrence
            suffix = f"-t{track}" if occurrence == 1 else f"-t{track}-g{occurrence}"
        _translate_audio_test(group, applies_to, suffix, out)

    if len(resolved) > 1 and any(count > 1 for count in seen_tracks.values()):
        out.notes.append(
            "Vidchecker configures multiple audio check groups on the same track; "
            "they are flattened conjunctively here and need review before approval."
        )
    return out


# --------------------------------------------------------------------------- YAML emission


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./+-]+", text) and not re.fullmatch(r"[\d.+-]+", text):
        return text
    return json.dumps(text)


def _emit_rule(rule: dict) -> list[str]:
    lines = [f"  - rule_id: {rule['rule_id']}"]
    lines.append(f"    parameter_id: {rule['parameter_id']}")
    lines.append(f"    operator: {rule['operator']}")
    expected = rule.get("expected")
    if expected:
        lines.append("    expected:")
        for key, value in expected.items():
            if isinstance(value, list):
                rendered = ", ".join(_scalar(item) for item in value)
                lines.append(f"      {key}: [{rendered}]")
            else:
                lines.append(f"      {key}: {_scalar(value)}")
    applies = rule.get("applies_to")
    if applies:
        lines.append("    applies_to:")
        lines.append(f"      stream_type: {applies['stream_type']}")
        selector = applies.get("selector")
        if selector:
            lines.append("      selector:")
            lines.append(f"        index: {selector['index']}")
        if applies.get("quantifier"):
            lines.append(f"      quantifier: {applies['quantifier']}")
    for key in ("display_name", "description"):
        if rule.get(key):
            lines.append(f"    {key}: {_scalar(rule[key])}")
    if "severity" in rule:
        lines.append(f"    severity: {rule['severity']}")
    if "blocking" in rule:
        lines.append(f"    blocking: {_scalar(rule['blocking'])}")
    return lines


def _wrap_comment(text: str, prefix: str = "#   ") -> list[str]:
    words, lines, current = text.split(), [], prefix.rstrip()
    for word in words:
        candidate = f"{current} {word}" if current != prefix.rstrip() else f"{prefix}{word}"
        if len(candidate) > 96 and current != prefix.rstrip():
            lines.append(current)
            current = f"{prefix}{word}"
        else:
            current = candidate
    lines.append(current)
    return lines


def render_preset(  # noqa: PLR0913 - one argument per preset identity field
    source_id: int,
    name: str,
    client: str,
    preset_id: str,
    content_type: str,
    translation: Translation,
    note_text: str | None,
) -> str:
    header = [
        f"# Generated from the Vidchecker 8.2.2 template {name!r} (template id "
        f"{source_id}) by scripts/import_vidchecker_templates.py.",
        f"# Source export: presets/_sources/vidchecker/ (captured {EXTRACTION_DATE}).",
        "#",
        "# ALL THRESHOLDS ARE PLACEHOLDERS PENDING HUMAN APPROVAL (handoff section 30).",
    ]
    if translation.uncovered:
        header.append("#")
        header.append("# Vidchecker checks NOT covered by this preset (no implemented")
        header.append("# parameter yet - see docs/vidchecker-import.md):")
        for item in translation.uncovered:
            header.extend(_wrap_comment(item, "#   - "))
    for note in translation.notes:
        header.append("#")
        header.extend(_wrap_comment(note, "# NOTE: "))

    description = f"Imported from the Vidchecker template {name!r}."
    if note_text:
        description += f" Vidchecker note: {note_text}"
    if translation.uncovered:
        description += (
            f" {len(translation.uncovered)} Vidchecker check(s) are not yet covered;"
            " see the preset file header."
        )

    lines = [
        *header,
        "schema_version: 1.0.0",
        "",
        "preset:",
        f"  id: {preset_id}",
        "  version: 1.0.0",
        f"  client: {client}",
        f"  content_type: {content_type}",
        f"  title: {_scalar(name.strip().lstrip('-').strip())}",
        f"  description: {json.dumps(description)}",
        "  owner: media-operations",
        "  status: draft",
        f"  effective_date: {EXTRACTION_DATE}",
        "",
        "defaults:",
        "  blocking: true",
        "  severity: error",
        "",
        "rules:",
    ]
    for index, rule in enumerate(translation.rules):
        if index:
            lines.append("")
        lines.extend(_emit_rule(rule))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main


def load_notes() -> dict[str, str]:
    notes_file = SOURCE_DIR / "template-notes.json"
    if not notes_file.is_file():
        return {}
    entries = json.loads(notes_file.read_text(encoding="utf-8-sig"))
    by_template: dict[str, str] = {}
    for entry in entries:
        text = (entry.get("Text") or "").strip()
        if text:
            by_template.setdefault(entry["Template"], text)
    return by_template


def main() -> int:
    force = "--force" in sys.argv
    source = SOURCE_DIR / "templates-combined.xml"
    if not source.is_file():
        print(f"source archive missing: {source}", file=sys.stderr)
        return 1

    notes = load_notes()
    tree = ET.parse(source)
    matrix: list[tuple[int, str, str, int, int]] = []  # id, name, outcome, rules, uncovered
    written: list[Path] = []
    failures: list[str] = []

    for template in tree.getroot().findall("Template"):
        source_id = int(template.get("sourceId") or 0)
        name = template.get("name") or f"template-{source_id}"

        if source_id in ALREADY_TRANSLATED:
            matrix.append(
                (source_id, name, f"hand-translated: {ALREADY_TRANSLATED[source_id]}", 0, 0)
            )
            continue

        translation = translate_template(template)
        if not translation.rules:
            matrix.append(
                (source_id, name, "skipped: no translatable checks", 0, len(translation.uncovered))
            )
            continue

        custom = CUSTOM_TEMPLATES.get(source_id)
        if custom:
            client, preset_id, stem = custom
            target = CLIENTS_DIR / client / f"{stem}_v1.yaml"
        else:
            client = "vidchecker-library"
            preset_id = f"vc{source_id:03d}_{slugify(name)}"
            target = LIBRARY_DIR / f"{preset_id}_v1.yaml"

        has_video = any(
            rule["parameter_id"].startswith(("video.", "container.")) for rule in translation.rules
        )
        content_type = "av_delivery" if has_video else "audio_delivery"

        text = render_preset(
            source_id,
            name,
            client,
            preset_id,
            content_type,
            translation,
            notes.get(name),
        )
        if target.exists() and not force:
            matrix.append(
                (
                    source_id,
                    name,
                    f"exists (kept): {target.relative_to(REPO_ROOT)}",
                    len(translation.rules),
                    len(translation.uncovered),
                )
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        try:
            load_preset(target)
        except Exception as exc:
            failures.append(f"{target}: {exc}")
        written.append(target)
        matrix.append(
            (
                source_id,
                name,
                f"imported: {target.relative_to(REPO_ROOT)}",
                len(translation.rules),
                len(translation.uncovered),
            )
        )

    doc = [
        "# Vidchecker Template Import",
        "",
        "<!-- GENERATED FILE - do not edit by hand.",
        "     Source: scripts/import_vidchecker_templates.py over",
        "     presets/_sources/vidchecker/. Regenerate by re-running the script. -->",
        "",
        f"Vidchecker 8.2.2 template export captured {EXTRACTION_DATE} from the",
        "production instance. One draft preset per template; checks without an",
        "implemented catalogue parameter are listed in each preset's header and",
        "counted below. Thresholds are placeholders pending human approval",
        "(handoff section 30, ADR-025).",
        "",
        "| Vidchecker id | Template | Outcome | Rules | Uncovered checks |",
        "|---|---|---|---|---|",
    ]
    for source_id, name, outcome, rules, uncovered in sorted(matrix):
        doc.append(f"| {source_id} | {name.strip()} | {outcome} | {rules} | {uncovered} |")
    doc.append("")
    COVERAGE_DOC.write_text("\n".join(doc), encoding="utf-8")

    print(f"presets written: {len(written)}")
    for path in written:
        print(f"  {path.relative_to(REPO_ROOT)}")
    print(f"coverage report: {COVERAGE_DOC.relative_to(REPO_ROOT)}")
    if failures:
        print("\nINVALID OUTPUT:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
