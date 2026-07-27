"""The parameter catalogue: the vocabulary of measurable facts (ADR-021).

Why this exists
---------------
A `parameter_id` is the contract between a detector (which produces
measurements) and a preset (which writes rules about them). Before this module
nothing validated that contract, so a preset could reference a parameter no
detector emits. A blocking rule over a missing parameter escalates to `ERROR`
and is caught, but a **non-blocking** rule silently became `SKIPPED` — an
operator would see a complete-looking report for a check that never ran. That
is the one silent-pass path the design otherwise rules out, and preset
authoring is explicitly the extension point for non-engineers (ADR-003).

This catalogue is therefore the single declaration of what the system can
measure. It lives in `models/` because ARCHITECTURE.md section 4 designates
that layer "the only shared vocabulary": `detectors/` and `presets/` are
siblings and must not import each other, but both may be validated against a
model. It is deliberately declarative data, not derived from the detector
registry — a preset's validity must not depend on which detectors happen to be
imported.

Bindings that make it load-bearing rather than decorative:

1. `presets.loader` rejects rules whose `parameter_id` is not catalogued,
   suggesting near-matches (see `suggest`).
2. `tests/unit/test_parameter_catalogue.py` asserts every detector's declared
   `parameters` tuple is catalogued, and that every IMPLEMENTED parameter is
   claimed by exactly one detector. Adding one without the other fails CI.
3. `scripts/export_parameters.py` generates `docs/parameter-catalogue.md` and
   `schemas/parameter-catalogue.json`, drift-checked in CI (ADR-004 pattern).

Inputs: none (static data). Outputs: `CATALOGUE` and lookup helpers.
Side effects: none.
"""

from __future__ import annotations

import difflib
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict

from deepdub_qc.models.enums import Category
from deepdub_qc.models.types import NonEmptyStr


class DataType(StrEnum):
    """The Python/JSON type of a measurement's `value` for this parameter."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"


class ImplementationStatus(StrEnum):
    """Whether a detector actually produces this parameter today.

    Presets may only reference IMPLEMENTED parameters. PLANNED entries exist so
    the catalogue doubles as the agreed list of facts we intend to measure
    (handoff section 15) without silently accepting rules that cannot run.
    """

    IMPLEMENTED = "implemented"
    PLANNED = "planned"


class ValidationStatus(StrEnum):
    """How much external evidence backs this measurement's accuracy.

    Deliberately conservative: only `docs/VALIDATION.md` evidence justifies
    anything other than UNVALIDATED. A measurement being implemented and tested
    says nothing about whether it agrees with a broadcast meter.
    """

    #: Checked against a specification or reference test set (e.g. EBU 3341).
    VALIDATED = "validated"
    #: Compared with another tool on identical bytes, definitions differing.
    CROSS_CHECKED = "cross_checked"
    #: No external accuracy evidence yet.
    UNVALIDATED = "unvalidated"


class ParameterDefinition(BaseModel):
    """One catalogued parameter, carrying the fields handoff section 15 requires."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parameter_id: NonEmptyStr
    display_name: NonEmptyStr
    category: Category
    description: NonEmptyStr
    data_type: DataType
    #: Unit symbol as emitted in measurements (LUFS, dBTP, s, Hz, px...).
    unit: str | None = None
    #: The detector that produces it; None while PLANNED.
    detector_id: str | None = None
    #: True when measurements carry a stream_index.
    stream_scoped: bool = False
    #: True when measurements carry start/end seconds (event-style parameters).
    timestamped: bool = False
    implementation: ImplementationStatus = ImplementationStatus.PLANNED
    validation: ValidationStatus = ValidationStatus.UNVALIDATED
    #: Known measurement caveats a report reader or preset author must know.
    limitations: str | None = None


_FFPROBE: Final = "metadata.ffprobe"
_AUDIO: Final = "audio.analysis.ffmpeg"
_VIDEO: Final = "video.incidents.ffmpeg"

_IMPL: Final = ImplementationStatus.IMPLEMENTED

_DEFINITIONS: Final[tuple[ParameterDefinition, ...]] = (
    # --- File and container (handoff section 15.1) ---------------------------
    ParameterDefinition(
        parameter_id="file.readable",
        display_name="File Readable",
        category=Category.FILE,
        description="Whether the input file exists and is readable by the process.",
        data_type=DataType.BOOLEAN,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="file.extension",
        display_name="File Extension",
        category=Category.FILE,
        description="Lowercased file extension without the leading dot.",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="file.size_bytes",
        display_name="File Size",
        category=Category.FILE,
        description="Size of the input file in bytes.",
        data_type=DataType.INTEGER,
        unit="B",
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="filename.pattern",
        display_name="Filename",
        category=Category.FILE,
        description=(
            "The file's basename, for rules that match delivery naming "
            "conventions with the regex operator."
        ),
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="file.sha256",
        display_name="File SHA-256",
        category=Category.FILE,
        description=(
            "SHA-256 of the input bytes. Already recorded on the asset in every "
            "result; catalogued for completeness, not yet rule-addressable."
        ),
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="container.format",
        display_name="Container Format",
        category=Category.CONTAINER,
        description="Container format normalized to a single token (mov, mp4, mkv, wav).",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="container.duration",
        display_name="Container Duration",
        category=Category.CONTAINER,
        description="Total programme duration reported by the container.",
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="container.overall_bitrate",
        display_name="Overall Bitrate",
        category=Category.CONTAINER,
        description="Total bitrate across all streams.",
        data_type=DataType.INTEGER,
        unit="bit/s",
    ),
    ParameterDefinition(
        parameter_id="container.start_time",
        display_name="Container Start Time",
        category=Category.CONTAINER,
        description="Start time offset of the container timeline.",
        data_type=DataType.FLOAT,
        unit="s",
    ),
    ParameterDefinition(
        parameter_id="container.timecode_present",
        display_name="Timecode Track Present",
        category=Category.CONTAINER,
        description="Whether the container carries a timecode track.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="container.timecode_start",
        display_name="Start Timecode",
        category=Category.CONTAINER,
        description="First timecode value, as SMPTE HH:MM:SS:FF.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="container.truncated",
        display_name="Container Truncated",
        category=Category.CONTAINER,
        description="Whether the file appears cut short relative to its declared duration.",
        data_type=DataType.BOOLEAN,
    ),
    # --- Video structure (handoff section 15.2) ------------------------------
    ParameterDefinition(
        parameter_id="video.stream_count",
        display_name="Video Stream Count",
        category=Category.VIDEO,
        description="Number of video streams in the file.",
        data_type=DataType.INTEGER,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.codec",
        display_name="Video Codec",
        category=Category.VIDEO,
        description="Video codec name per stream (prores, h264, ...).",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.width",
        display_name="Video Width",
        category=Category.VIDEO,
        description="Coded frame width.",
        data_type=DataType.INTEGER,
        unit="px",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.height",
        display_name="Video Height",
        category=Category.VIDEO,
        description="Coded frame height.",
        data_type=DataType.INTEGER,
        unit="px",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.frame_rate",
        display_name="Frame Rate",
        category=Category.VIDEO,
        description="Average frame rate, normalized to three decimal places.",
        data_type=DataType.FLOAT,
        unit="fps",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
        limitations=(
            "Rational rates (24000/1001) are rounded for comparison; use the "
            "approximately_equals operator with a tolerance rather than equals."
        ),
    ),
    ParameterDefinition(
        parameter_id="video.pixel_format",
        display_name="Pixel Format",
        category=Category.VIDEO,
        description="Pixel format name (yuv422p10le, yuv420p, ...).",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.profile",
        display_name="Video Profile",
        category=Category.VIDEO,
        description="Codec profile (e.g. ProRes 422 HQ, High).",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.level",
        display_name="Video Level",
        category=Category.VIDEO,
        description="Codec level.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.frame_rate_mode",
        display_name="Frame Rate Mode",
        category=Category.VIDEO,
        description="Constant or variable frame rate.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.bit_depth",
        display_name="Video Bit Depth",
        category=Category.VIDEO,
        description="Bits per colour component.",
        data_type=DataType.INTEGER,
        unit="bit",
    ),
    ParameterDefinition(
        parameter_id="video.display_aspect_ratio",
        display_name="Display Aspect Ratio",
        category=Category.VIDEO,
        description="Display aspect ratio as declared by the stream.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.sample_aspect_ratio",
        display_name="Sample Aspect Ratio",
        category=Category.VIDEO,
        description="Pixel aspect ratio as declared by the stream.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.scan_type",
        display_name="Scan Type",
        category=Category.VIDEO,
        description="Progressive or interlaced.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.field_order",
        display_name="Field Order",
        category=Category.VIDEO,
        description="Field order for interlaced material (tff, bff).",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.color_primaries",
        display_name="Colour Primaries",
        category=Category.VIDEO,
        description="Colour primaries (bt709, bt2020, ...).",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.transfer_characteristics",
        display_name="Transfer Characteristics",
        category=Category.VIDEO,
        description="Transfer function (bt709, pq, hlg, ...).",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.color_space",
        display_name="Colour Space",
        category=Category.VIDEO,
        description="Matrix coefficients / colour space.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="video.hdr_metadata_present",
        display_name="HDR Metadata Present",
        category=Category.VIDEO,
        description="Whether HDR static or dynamic metadata is present.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="video.bitrate",
        display_name="Video Bitrate",
        category=Category.VIDEO,
        description="Video stream bitrate.",
        data_type=DataType.INTEGER,
        unit="bit/s",
    ),
    # --- Video incidents ----------------------------------------------------
    ParameterDefinition(
        parameter_id="video.black_frame_event",
        display_name="Black Frame Event",
        category=Category.VIDEO,
        description=(
            "Duration of one detected black span. Emitted once per span, with "
            "start and end seconds."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_VIDEO,
        stream_scoped=True,
        timestamped=True,
        implementation=_IMPL,
        limitations=(
            "ffmpeg blackdetect thresholds (0.5 s minimum, 0.10 pixel threshold) "
            "are detector constants, not preset-configurable. Spans shorter than "
            "the minimum are not reported."
        ),
    ),
    ParameterDefinition(
        parameter_id="video.black_frame_count",
        display_name="Black Frame Event Count",
        category=Category.VIDEO,
        description="Number of black spans detected in the stream.",
        data_type=DataType.INTEGER,
        detector_id=_VIDEO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.freeze_frame_event",
        display_name="Freeze Frame Event",
        category=Category.VIDEO,
        description=(
            "Duration of one detected frozen span. Emitted once per span, with "
            "start and end seconds."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_VIDEO,
        stream_scoped=True,
        timestamped=True,
        implementation=_IMPL,
        limitations=(
            "ffmpeg freezedetect thresholds (-60 dB noise, 1.0 s minimum) are "
            "detector constants. Legitimate static content (title cards, letter"
            "boxed slates) registers as frozen."
        ),
    ),
    ParameterDefinition(
        parameter_id="video.freeze_frame_count",
        display_name="Freeze Frame Event Count",
        category=Category.VIDEO,
        description="Number of frozen spans detected in the stream.",
        data_type=DataType.INTEGER,
        detector_id=_VIDEO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.luma_min",
        display_name="Luma Minimum",
        category=Category.VIDEO,
        description="Minimum Y value observed across the stream (signalstats).",
        data_type=DataType.FLOAT,
        detector_id=_VIDEO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.luma_max",
        display_name="Luma Maximum",
        category=Category.VIDEO,
        description="Maximum Y value observed across the stream (signalstats).",
        data_type=DataType.FLOAT,
        detector_id=_VIDEO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.luma_avg",
        display_name="Luma Average",
        category=Category.VIDEO,
        description="Mean Y value across the stream (signalstats).",
        data_type=DataType.FLOAT,
        detector_id=_VIDEO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="video.signal_range_event",
        display_name="Signal Range Event",
        category=Category.VIDEO,
        description="Span where luma or chroma exceeds the legal broadcast range.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="video.letterbox_detected",
        display_name="Letterbox Detected",
        category=Category.VIDEO,
        description="Whether the active picture is pillarboxed or letterboxed.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="video.corrupt_frame_event",
        display_name="Corrupt Frame Event",
        category=Category.VIDEO,
        description=(
            "A frame with decode errors or statistical outliers. Backlog #36: "
            "Vidchecker flagged such a frame on the RHOA M&E master that we "
            "localized only indirectly, via a one-frame gap between black spans."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    # --- Audio structure (handoff section 15.3) -----------------------------
    ParameterDefinition(
        parameter_id="audio.stream_count",
        display_name="Audio Stream Count",
        category=Category.AUDIO,
        description="Number of audio streams (tracks) in the file.",
        data_type=DataType.INTEGER,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.codec",
        display_name="Audio Codec",
        category=Category.AUDIO,
        description="Audio codec name per stream (pcm_s24le, aac, ...).",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.sample_rate",
        display_name="Sample Rate",
        category=Category.AUDIO,
        description="Sampling frequency per stream.",
        data_type=DataType.INTEGER,
        unit="Hz",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.channel_count",
        display_name="Channel Count",
        category=Category.AUDIO,
        description="Number of channels in the stream.",
        data_type=DataType.INTEGER,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.channel_layout",
        display_name="Channel Layout",
        category=Category.AUDIO,
        description="Channel layout descriptor (mono, stereo, 5.1).",
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.language",
        display_name="Audio Language",
        category=Category.AUDIO,
        description=(
            "Stream language tag, normalized to ISO 639-1 where possible so "
            "presets may reference either form (backlog #33)."
        ),
        data_type=DataType.STRING,
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
        limitations="Not emitted when the stream carries no language metadata.",
    ),
    ParameterDefinition(
        parameter_id="audio.duration",
        display_name="Audio Duration",
        category=Category.AUDIO,
        description="Duration of the audio stream.",
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.video_duration_delta",
        display_name="Audio/Video Duration Delta",
        category=Category.AUDIO,
        description="Audio stream duration minus video stream duration.",
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_FFPROBE,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.bit_depth",
        display_name="Audio Bit Depth",
        category=Category.AUDIO,
        description="Bits per sample for PCM streams.",
        data_type=DataType.INTEGER,
        unit="bit",
    ),
    # --- Audio loudness -----------------------------------------------------
    ParameterDefinition(
        parameter_id="audio.integrated_loudness",
        display_name="Integrated Loudness",
        category=Category.AUDIO,
        description="EBU R128 programme loudness over the whole stream.",
        data_type=DataType.FLOAT,
        unit="LUFS",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.VALIDATED,
        limitations=(
            "Measured per track. On multi-mono masters a channel-group target "
            "(e.g. 5.1 measured jointly with ITU-1770 weighting) is NOT what "
            "this reports — see backlog #35 and audio.group_integrated_loudness."
        ),
    ),
    ParameterDefinition(
        parameter_id="audio.loudness_range",
        display_name="Loudness Range",
        category=Category.AUDIO,
        description="EBU R128 loudness range (LRA).",
        data_type=DataType.FLOAT,
        unit="LU",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.VALIDATED,
    ),
    ParameterDefinition(
        parameter_id="audio.true_peak",
        display_name="True Peak",
        category=Category.AUDIO,
        description="EBU R128 maximum true peak level.",
        data_type=DataType.FLOAT,
        unit="dBTP",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.VALIDATED,
    ),
    ParameterDefinition(
        parameter_id="audio.max_short_term_loudness",
        display_name="Max Short-Term Loudness",
        category=Category.AUDIO,
        description="Highest 3-second short-term loudness value.",
        data_type=DataType.FLOAT,
        unit="LUFS",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.VALIDATED,
    ),
    ParameterDefinition(
        parameter_id="audio.max_momentary_loudness",
        display_name="Max Momentary Loudness",
        category=Category.AUDIO,
        description="Highest 400 ms momentary loudness value.",
        data_type=DataType.FLOAT,
        unit="LUFS",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.VALIDATED,
        limitations=(
            "Derived from 100 ms ebur128 log lines, which undersamples very "
            "short bursts by up to 0.5 LU (EBU 3341 case 13). Spec-grade "
            "metering is outstanding work in docs/VALIDATION.md."
        ),
    ),
    # --- Audio silence and level -------------------------------------------
    ParameterDefinition(
        parameter_id="audio.head_silence_duration",
        display_name="Head Silence",
        category=Category.AUDIO,
        description="Length of the silent span at the start of the stream.",
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        limitations="Silence is defined as below -60 dB for at least 0.5 s.",
    ),
    ParameterDefinition(
        parameter_id="audio.tail_silence_duration",
        display_name="Tail Silence",
        category=Category.AUDIO,
        description="Length of the silent span at the end of the stream.",
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
        validation=ValidationStatus.CROSS_CHECKED,
        limitations=(
            "Converged with Vidchecker's Min Level within 0.2 s on parity point 1 "
            "despite different definitions (-60 dB silencedetect vs -95 dB "
            "windowed RMS)."
        ),
    ),
    ParameterDefinition(
        parameter_id="audio.internal_silence_event",
        display_name="Internal Silence Event",
        category=Category.AUDIO,
        description=(
            "Duration of one silent span inside the programme. Emitted once per "
            "span, with start and end seconds."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_AUDIO,
        stream_scoped=True,
        timestamped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.internal_silence_count",
        display_name="Internal Silence Count",
        category=Category.AUDIO,
        description="Number of internal silent spans detected.",
        data_type=DataType.INTEGER,
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.low_rms_event",
        display_name="Low RMS Event",
        category=Category.AUDIO,
        description=(
            "Duration of one span whose windowed RMS stays at or below -90 dB. "
            "Approximates Vidchecker's Min Level test (backlog #34)."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        detector_id=_AUDIO,
        stream_scoped=True,
        timestamped=True,
        implementation=_IMPL,
        validation=ValidationStatus.CROSS_CHECKED,
        limitations="5-second RMS windows; -90 dB threshold is a detector constant.",
    ),
    ParameterDefinition(
        parameter_id="audio.low_rms_event_count",
        display_name="Low RMS Event Count",
        category=Category.AUDIO,
        description="Number of low-RMS spans detected after merging adjacent windows.",
        data_type=DataType.INTEGER,
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    # --- Audio clipping indicators -----------------------------------------
    ParameterDefinition(
        parameter_id="audio.peak_level",
        display_name="Peak Level",
        category=Category.AUDIO,
        description="Sample peak level from astats, a hard-clipping indicator.",
        data_type=DataType.FLOAT,
        unit="dBFS",
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.flat_factor",
        display_name="Flat Factor",
        category=Category.AUDIO,
        description=(
            "astats flat factor: consecutive samples pinned at peak. Greater "
            "than zero indicates clipping."
        ),
        data_type=DataType.FLOAT,
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.peak_count",
        display_name="Peak Count",
        category=Category.AUDIO,
        description="Number of samples at peak level (astats).",
        data_type=DataType.INTEGER,
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.dc_offset",
        display_name="DC Offset",
        category=Category.AUDIO,
        description="Mean sample offset from zero (astats); should be near zero.",
        data_type=DataType.FLOAT,
        detector_id=_AUDIO,
        stream_scoped=True,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="audio.clipping_event",
        display_name="Clipping Event",
        category=Category.AUDIO,
        description=(
            "A timestamped clipping occurrence. Not implemented: clipping is "
            "currently surfaced as the whole-stream indicators peak_level, "
            "flat_factor and peak_count rather than located in time."
        ),
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="audio.phase_correlation",
        display_name="Phase Correlation",
        category=Category.AUDIO,
        description="Inter-channel phase correlation, for detecting out-of-phase pairs.",
        data_type=DataType.FLOAT,
    ),
    ParameterDefinition(
        parameter_id="audio.duplicate_channel_risk",
        display_name="Duplicate Channel Risk",
        category=Category.AUDIO,
        description="Whether two channels are identical, indicating a dual-mono error.",
        data_type=DataType.BOOLEAN,
    ),
    # --- Audio channel groups (backlog #35) ---------------------------------
    ParameterDefinition(
        parameter_id="audio.group_integrated_loudness",
        display_name="Group Integrated Loudness",
        category=Category.AUDIO,
        description=(
            "Integrated loudness of a preset-declared channel group measured "
            "jointly with ITU-1770 weighting. This, not the per-track value, is "
            "what client filename targets such as '-27LU' refer to on multi-mono "
            "masters (backlog #35)."
        ),
        data_type=DataType.FLOAT,
        unit="LUFS",
    ),
    ParameterDefinition(
        parameter_id="audio.group_loudness_range",
        display_name="Group Loudness Range",
        category=Category.AUDIO,
        description="Loudness range of a preset-declared channel group (backlog #35).",
        data_type=DataType.FLOAT,
        unit="LU",
    ),
    ParameterDefinition(
        parameter_id="audio.group_true_peak",
        display_name="Group True Peak",
        category=Category.AUDIO,
        description="Maximum true peak across a preset-declared channel group (backlog #35).",
        data_type=DataType.FLOAT,
        unit="dBTP",
    ),
    # --- Subtitle and caption (handoff section 15.4) ------------------------
    ParameterDefinition(
        parameter_id="subtitle.stream_count",
        display_name="Subtitle Stream Count",
        category=Category.SUBTITLE,
        description="Number of subtitle streams in the file.",
        data_type=DataType.INTEGER,
        detector_id=_FFPROBE,
        implementation=_IMPL,
    ),
    ParameterDefinition(
        parameter_id="subtitle.codec",
        display_name="Subtitle Codec",
        category=Category.SUBTITLE,
        description="Subtitle codec or format per stream.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="subtitle.language",
        display_name="Subtitle Language",
        category=Category.SUBTITLE,
        description="Subtitle stream language tag.",
        data_type=DataType.STRING,
    ),
    ParameterDefinition(
        parameter_id="subtitle.default_flag",
        display_name="Subtitle Default Flag",
        category=Category.SUBTITLE,
        description="Whether the stream is marked default.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="subtitle.forced_flag",
        display_name="Subtitle Forced Flag",
        category=Category.SUBTITLE,
        description="Whether the stream is marked forced.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="subtitle.cue_count",
        display_name="Subtitle Cue Count",
        category=Category.SUBTITLE,
        description="Number of subtitle cues.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="subtitle.overlap_event",
        display_name="Subtitle Overlap Event",
        category=Category.SUBTITLE,
        description="Two cues displayed at the same time.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="subtitle.zero_duration_event",
        display_name="Zero-Duration Cue",
        category=Category.SUBTITLE,
        description="A cue whose out-time equals its in-time.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="subtitle.out_of_bounds_event",
        display_name="Out-of-Bounds Cue",
        category=Category.SUBTITLE,
        description="A cue timed outside the programme duration.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="subtitle.characters_per_second",
        display_name="Characters Per Second",
        category=Category.SUBTITLE,
        description="Reading-speed measure per cue.",
        data_type=DataType.FLOAT,
        unit="char/s",
    ),
    ParameterDefinition(
        parameter_id="subtitle.characters_per_line",
        display_name="Characters Per Line",
        category=Category.SUBTITLE,
        description="Maximum characters on any subtitle line.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="subtitle.line_count",
        display_name="Subtitle Line Count",
        category=Category.SUBTITLE,
        description="Maximum simultaneous lines in any cue.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="subtitle.invalid_markup_event",
        display_name="Invalid Markup",
        category=Category.SUBTITLE,
        description="A cue containing malformed markup.",
        data_type=DataType.STRING,
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="subtitle.encoding_error_event",
        display_name="Encoding Error",
        category=Category.SUBTITLE,
        description="A character that failed to decode in the declared encoding.",
        data_type=DataType.STRING,
        timestamped=True,
    ),
    # --- Deepdub workflow (handoff section 15.5) ----------------------------
    ParameterDefinition(
        parameter_id="deepdub.expected_episode_duration",
        display_name="Expected Episode Duration",
        category=Category.DEEPDUB,
        description="Duration the Composer project expects for this episode.",
        data_type=DataType.FLOAT,
        unit="s",
    ),
    ParameterDefinition(
        parameter_id="deepdub.export_duration_delta",
        display_name="Export Duration Delta",
        category=Category.DEEPDUB,
        description="Difference between the exported media and the Composer timeline.",
        data_type=DataType.FLOAT,
        unit="s",
    ),
    ParameterDefinition(
        parameter_id="deepdub.missing_generated_segments",
        display_name="Missing Generated Segments",
        category=Category.DEEPDUB,
        description="Segments with no generated dub audio.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="deepdub.missing_mix_segments",
        display_name="Missing Mix Segments",
        category=Category.DEEPDUB,
        description="Segments absent from the final mix.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="deepdub.unresolved_qc_markers",
        display_name="Unresolved QC Markers",
        category=Category.DEEPDUB,
        description="Composer QC markers still open at export time.",
        data_type=DataType.INTEGER,
    ),
    ParameterDefinition(
        parameter_id="deepdub.dialogue_outside_segment_event",
        display_name="Dialogue Outside Segment",
        category=Category.DEEPDUB,
        description="Speech detected outside any defined segment.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="deepdub.segment_overlap_event",
        display_name="Segment Overlap",
        category=Category.DEEPDUB,
        description="Two segments overlapping in time.",
        data_type=DataType.FLOAT,
        unit="s",
        timestamped=True,
    ),
    ParameterDefinition(
        parameter_id="deepdub.required_language_missing",
        display_name="Required Language Missing",
        category=Category.DEEPDUB,
        description="A language the delivery requires is absent.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="deepdub.required_stem_missing",
        display_name="Required Stem Missing",
        category=Category.DEEPDUB,
        description="A required stem (dialogue, M&E, effects) is absent.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="deepdub.export_version_mismatch",
        display_name="Export Version Mismatch",
        category=Category.DEEPDUB,
        description="The export does not match the Composer version it claims.",
        data_type=DataType.BOOLEAN,
    ),
    ParameterDefinition(
        parameter_id="deepdub.workspace_metadata_mismatch",
        display_name="Workspace Metadata Mismatch",
        category=Category.DEEPDUB,
        description="Asset metadata disagrees with the Composer workspace record.",
        data_type=DataType.BOOLEAN,
    ),
)


def _build_catalogue() -> MappingProxyType[str, ParameterDefinition]:
    """Key the definitions by parameter id, refusing duplicates.

    A dict comprehension would keep the last duplicate silently — a re-added
    id (e.g. a PLANNED copy of an IMPLEMENTED parameter) would demote the
    original with no signal until presets over it fail to load.
    """
    catalogue: dict[str, ParameterDefinition] = {}
    for definition in _DEFINITIONS:
        if definition.parameter_id in catalogue:
            raise ValueError(f"duplicate parameter_id in _DEFINITIONS: {definition.parameter_id!r}")
        catalogue[definition.parameter_id] = definition
    return MappingProxyType(catalogue)


#: The catalogue, keyed by parameter id. Read-only: presets and detectors are
#: validated against it, never mutate it.
CATALOGUE: Final[MappingProxyType[str, ParameterDefinition]] = _build_catalogue()


def get(parameter_id: str) -> ParameterDefinition | None:
    """Look up a parameter definition, or None if it is not catalogued."""
    return CATALOGUE.get(parameter_id)


def is_catalogued(parameter_id: str) -> bool:
    """Whether the parameter exists in the catalogue at all (any status)."""
    return parameter_id in CATALOGUE


def implemented_ids() -> frozenset[str]:
    """Parameter ids a detector actually produces today.

    Presets may only reference these: a rule over a PLANNED parameter can never
    find a measurement, and would degrade to a SKIPPED finding at runtime.
    """
    return frozenset(
        definition.parameter_id
        for definition in _DEFINITIONS
        if definition.implementation is ImplementationStatus.IMPLEMENTED
    )


def suggest(parameter_id: str, *, limit: int = 3) -> list[str]:
    """Closest catalogued ids to a misspelling, for actionable error messages.

    Only IMPLEMENTED ids are suggested, since those are the only ones a preset
    may legally use.
    """
    return difflib.get_close_matches(parameter_id, sorted(implemented_ids()), n=limit, cutoff=0.6)
