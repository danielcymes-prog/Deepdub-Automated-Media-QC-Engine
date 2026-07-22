"""Deterministic mock QCResult for the report-first prototype (ADR-011).

Why this exists: stakeholders must review a realistic report before any
detector is written (M2). This module builds a fully deterministic QCResult -
fixed timestamps, fixed job ID, content-derived measurement/finding IDs - so
it doubles as the permanent golden fixture for report contract tests.

The content is ILLUSTRATIVE: rule outcomes, thresholds, and evidence paths
demonstrate every report feature (pass, warning, blocking failure, skipped
check, timestamped incident, per-stream finding, evidence links). It is not
produced by real detectors.

Inputs: none. Outputs: a valid, immutable QCResult. Side effects: none.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from deepdub_qc import __version__
from deepdub_qc.models import (
    Asset,
    Category,
    Environment,
    Evidence,
    EvidenceType,
    Finding,
    JobStatus,
    Measurement,
    PresetRef,
    QCJob,
    QCResult,
    QCStatus,
    Severity,
    Summary,
)
from deepdub_qc.models.finding import ActualValue
from deepdub_qc.models.report import ArtifactPaths
from deepdub_qc.models.rule import ExpectedPattern, ExpectedRange, ExpectedValue, ExpectedValues
from deepdub_qc.utils import ids

#: Fixed values keep the mock byte-stable for golden-file tests (ADR-008).
MOCK_JOB_ID = UUID("00000000-0000-4000-8000-000000000001")
_T0 = datetime(2026, 7, 22, 10, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 22, 10, 4, 12, tzinfo=UTC)


def _measurement(
    detector_id: str,
    parameter_id: str,
    category: Category,
    value: object,
    unit: str | None = None,
    stream_index: int | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    start_timecode: str | None = None,
    end_timecode: str | None = None,
    raw_artifact_path: str | None = None,
) -> Measurement:
    return Measurement(
        measurement_id=ids.measurement_id(
            detector_id, "1.0.0", parameter_id, stream_index, start_seconds, end_seconds, value
        ),
        job_id=MOCK_JOB_ID,
        detector_id=detector_id,
        detector_version="1.0.0",
        parameter_id=parameter_id,
        category=category,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        stream_index=stream_index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        start_timecode=start_timecode,
        end_timecode=end_timecode,
        raw_artifact_path=raw_artifact_path,
        created_at=_T1,
    )


def build_mock_result() -> QCResult:
    """Build the deterministic mock QC result used by `deepdub-qc render-mock`."""
    measurements = {
        "container.format": _measurement(
            "metadata.ffprobe", "container.format", Category.CONTAINER, "mov",
            raw_artifact_path="raw/ffprobe.json",
        ),
        "video.width": _measurement(
            "metadata.ffprobe", "video.width", Category.VIDEO, 1920, "px", stream_index=0
        ),
        "video.height": _measurement(
            "metadata.ffprobe", "video.height", Category.VIDEO, 1080, "px", stream_index=0
        ),
        "video.frame_rate": _measurement(
            "metadata.ffprobe", "video.frame_rate", Category.VIDEO, 23.976, "fps", stream_index=0
        ),
        "video.pixel_format": _measurement(
            "metadata.ffprobe", "video.pixel_format", Category.VIDEO, "yuv422p10le",
            stream_index=0,
        ),
        "audio.stream_count": _measurement(
            "metadata.ffprobe", "audio.stream_count", Category.AUDIO, 2
        ),
        "audio.sample_rate": _measurement(
            "metadata.ffprobe", "audio.sample_rate", Category.AUDIO, 48000, "Hz", stream_index=1
        ),
        "audio.integrated_loudness": _measurement(
            "audio.loudness.ebur128", "audio.integrated_loudness", Category.AUDIO, -19.7, "LUFS",
            stream_index=1, raw_artifact_path="raw/loudness.json",
        ),
        "audio.true_peak": _measurement(
            "audio.loudness.ebur128", "audio.true_peak", Category.AUDIO, -2.3, "dBTP",
            stream_index=1, raw_artifact_path="raw/loudness.json",
        ),
        "audio.head_silence_duration": _measurement(
            "audio.silence", "audio.head_silence_duration", Category.AUDIO, 1.85, "s",
            stream_index=1, start_seconds=0.0, end_seconds=1.85,
            start_timecode="00:00:00:00", end_timecode="00:00:01:20",
            raw_artifact_path="raw/silencedetect.log",
        ),
        "video.black_frame_event": _measurement(
            "video.black_frames", "video.black_frame_event", Category.VIDEO, 3.4, "s",
            stream_index=0, start_seconds=252.0, end_seconds=255.4,
            start_timecode="00:04:12:00", end_timecode="00:04:15:10",
            raw_artifact_path="raw/blackdetect.log",
        ),
        "filename.pattern": _measurement(
            "metadata.ffprobe", "filename.pattern", Category.FILE, "Final Delivery v2.mov"
        ),
    }

    evidence = [
        Evidence(
            evidence_id=ids.deterministic_id("evidence", "thumbnail", 252.0),
            finding_id=None,
            type=EvidenceType.THUMBNAIL,
            path="evidence/thumbnails/black_00-04-12.png",
            start_seconds=252.0,
            generated_by="evidence.thumbnails/1.0.0",
            created_at=_T1,
        ),
        Evidence(
            evidence_id=ids.deterministic_id("evidence", "thumbnail", 255.4),
            finding_id=None,
            type=EvidenceType.THUMBNAIL,
            path="evidence/thumbnails/black_00-04-15.png",
            start_seconds=255.4,
            generated_by="evidence.thumbnails/1.0.0",
            created_at=_T1,
        ),
        Evidence(
            evidence_id=ids.deterministic_id("evidence", "waveform", 1),
            finding_id=None,
            type=EvidenceType.WAVEFORM,
            path="evidence/waveforms/stream1_loudness.png",
            generated_by="evidence.waveforms/1.0.0",
            created_at=_T1,
        ),
    ]

    def finding(
        rule_id: str,
        parameter_id: str,
        category: Category,
        display_name: str,
        status: QCStatus,
        severity: Severity,
        message: str,
        blocking: bool,
        expected: ExpectedValue | ExpectedValues | ExpectedRange | ExpectedPattern | None = None,
        actual: ActualValue | None = None,
        stream_index: int | None = None,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        start_timecode: str | None = None,
        end_timecode: str | None = None,
        suggested_action: str | None = None,
        measurement_keys: tuple[str, ...] = (),
        evidence_indices: tuple[int, ...] = (),
    ) -> Finding:
        return Finding(
            finding_id=ids.finding_id(
                rule_id, "1.0.0", parameter_id, stream_index, start_seconds, status.value
            ),
            job_id=MOCK_JOB_ID,
            rule_id=rule_id,
            parameter_id=parameter_id,
            category=category,
            display_name=display_name,
            status=status,
            severity=severity,
            expected=expected,
            actual=actual,
            message=message,
            blocking=blocking,
            stream_index=stream_index,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            start_timecode=start_timecode,
            end_timecode=end_timecode,
            suggested_action=suggested_action,
            measurement_ids=[measurements[k].measurement_id for k in measurement_keys],
            evidence_ids=[evidence[i].evidence_id for i in evidence_indices],
            rule_version="1.0.0",
            created_at=_T1,
        )

    findings = [
        finding(
            "container-format", "container.format", Category.CONTAINER, "Container Format",
            QCStatus.PASS, Severity.ERROR,
            "Container format is 'mov', which is allowed.",
            blocking=True,
            expected=ExpectedValues(values=["mov", "mxf"]),
            actual=ActualValue(value="mov"),
            measurement_keys=("container.format",),
        ),
        finding(
            "video-width", "video.width", Category.VIDEO, "Video Width",
            QCStatus.PASS, Severity.ERROR,
            "Video width is 1920 px as required.",
            blocking=True,
            expected=ExpectedValue(value=1920, unit="px"),
            actual=ActualValue(value=1920, unit="px"),
            stream_index=0,
            measurement_keys=("video.width",),
        ),
        finding(
            "video-height", "video.height", Category.VIDEO, "Video Height",
            QCStatus.PASS, Severity.ERROR,
            "Video height is 1080 px as required.",
            blocking=True,
            expected=ExpectedValue(value=1080, unit="px"),
            actual=ActualValue(value=1080, unit="px"),
            stream_index=0,
            measurement_keys=("video.height",),
        ),
        finding(
            "video-frame-rate", "video.frame_rate", Category.VIDEO, "Frame Rate",
            QCStatus.PASS, Severity.ERROR,
            "Frame rate 23.976 fps is within tolerance of the required 23.976 fps.",
            blocking=True,
            expected=ExpectedValue(value=23.976, unit="fps"),
            actual=ActualValue(value=23.976, unit="fps"),
            stream_index=0,
            measurement_keys=("video.frame_rate",),
        ),
        finding(
            "video-pixel-format", "video.pixel_format", Category.VIDEO, "Pixel Format",
            QCStatus.PASS, Severity.ERROR,
            "Pixel format is yuv422p10le as required.",
            blocking=True,
            expected=ExpectedValue(value="yuv422p10le"),
            actual=ActualValue(value="yuv422p10le"),
            stream_index=0,
            measurement_keys=("video.pixel_format",),
        ),
        finding(
            "audio-stream-count", "audio.stream_count", Category.AUDIO, "Audio Stream Count",
            QCStatus.PASS, Severity.CRITICAL,
            "Found 2 audio streams as required.",
            blocking=True,
            expected=ExpectedValue(value=2),
            actual=ActualValue(value=2),
            measurement_keys=("audio.stream_count",),
        ),
        finding(
            "audio-sample-rate", "audio.sample_rate", Category.AUDIO, "Audio Sample Rate",
            QCStatus.PASS, Severity.ERROR,
            "All audio streams are 48000 Hz.",
            blocking=True,
            expected=ExpectedValue(value=48000, unit="Hz"),
            actual=ActualValue(value=48000, unit="Hz"),
            stream_index=1,
            measurement_keys=("audio.sample_rate",),
        ),
        finding(
            "audio-true-peak", "audio.true_peak", Category.AUDIO, "True Peak",
            QCStatus.PASS, Severity.ERROR,
            "True peak -2.3 dBTP is at or below the -2.0 dBTP ceiling.",
            blocking=True,
            expected=ExpectedValue(value=-2.0, unit="dBTP"),
            actual=ActualValue(value=-2.3, unit="dBTP"),
            stream_index=1,
            measurement_keys=("audio.true_peak",),
        ),
        finding(
            "audio-integrated-loudness", "audio.integrated_loudness", Category.AUDIO,
            "Integrated Loudness",
            QCStatus.FAIL, Severity.ERROR,
            "Integrated loudness -19.7 LUFS exceeds the permitted range of -24.0 to -22.0 LUFS.",
            blocking=True,
            expected=ExpectedRange(min=-24.0, max=-22.0, unit="LUFS"),
            actual=ActualValue(value=-19.7, unit="LUFS"),
            stream_index=1,
            suggested_action="Normalize the final mix to the client loudness target "
            "(-23.0 LUFS +/- 1.0 LU) and re-export.",
            measurement_keys=("audio.integrated_loudness",),
            evidence_indices=(2,),
        ),
        finding(
            "video-drop-frames", "video.black_frame_event", Category.VIDEO, "Drop Frames",
            QCStatus.FAIL, Severity.ERROR,
            "Drop-frame segment of 3.4 s detected at 00:04:12:00.",
            blocking=False,
            stream_index=0,
            start_seconds=252.0,
            end_seconds=255.4,
            start_timecode="00:04:12:00",
            end_timecode="00:04:15:10",
            actual=ActualValue(value=3.4, unit="s"),
            suggested_action="Inspect the timeline at 00:04:12 for a gap or disabled clip "
            "and re-export the affected segment.",
            measurement_keys=("video.black_frame_event",),
            evidence_indices=(0, 1),
        ),
        finding(
            "audio-head-silence", "audio.head_silence_duration", Category.AUDIO, "Head Silence",
            QCStatus.WARNING, Severity.WARNING,
            "Head silence of 1.85 s exceeds the preferred maximum of 1.0 s.",
            blocking=False,
            expected=ExpectedValue(value=1.0, unit="s"),
            actual=ActualValue(value=1.85, unit="s"),
            stream_index=1,
            start_seconds=0.0,
            end_seconds=1.85,
            start_timecode="00:00:00:00",
            end_timecode="00:00:01:20",
            suggested_action="Confirm the head silence matches the client slate/leader spec.",
            measurement_keys=("audio.head_silence_duration",),
        ),
        finding(
            "filename-pattern", "filename.pattern", Category.FILE, "Filename Pattern",
            QCStatus.WARNING, Severity.WARNING,
            "Filename 'Final Delivery v2.mov' contains spaces, which the delivery "
            "specification discourages.",
            blocking=False,
            expected=ExpectedPattern(pattern=r"^[A-Za-z0-9._-]+\.(mov|mxf)$"),
            actual=ActualValue(value="Final Delivery v2.mov"),
            suggested_action="Rename the file to match the client filename convention.",
            measurement_keys=("filename.pattern",),
        ),
        finding(
            "video-freeze-frames", "video.freeze_frame_event", Category.VIDEO, "Freeze Frames",
            QCStatus.SKIPPED, Severity.WARNING,
            "Freeze-frame detection did not run: detector not available in this configuration.",
            blocking=False,
        ),
    ]

    summary = Summary(
        overall_status=QCStatus.FAIL,
        total_checks=len(findings),
        passed=sum(1 for f in findings if f.status is QCStatus.PASS),
        warnings=sum(1 for f in findings if f.status is QCStatus.WARNING),
        failed=sum(1 for f in findings if f.status is QCStatus.FAIL),
        errors=sum(1 for f in findings if f.status is QCStatus.ERROR),
        skipped=sum(1 for f in findings if f.status is QCStatus.SKIPPED),
        not_applicable=sum(1 for f in findings if f.status is QCStatus.NOT_APPLICABLE),
        blocking_failures=sum(
            1 for f in findings if f.status is QCStatus.FAIL and f.blocking
        ),
    )

    media_summary: dict[str, object] = {
        # Frame rate used for HH:MM:SS:FF timecode derivation in renderings
        # (DATA_MODEL_REVIEW item 8: canonical time is seconds).
        "timecode_frame_rate": 23.976,
        "container": {"format": "mov", "duration_seconds": 1452.2, "overall_bitrate": "185 Mb/s"},
        "video_streams": [
            {
                "index": 0,
                "codec": "prores",
                "profile": "ProRes 422 HQ",
                "resolution": "1920x1080",
                "frame_rate": "23.976 fps",
                "pixel_format": "yuv422p10le",
                "scan_type": "progressive",
            }
        ],
        "audio_streams": [
            {
                "index": 1,
                "codec": "pcm_s24le",
                "sample_rate": "48000 Hz",
                "channels": 2,
                "channel_layout": "stereo",
                "language": "deu",
            },
            {
                "index": 2,
                "codec": "pcm_s24le",
                "sample_rate": "48000 Hz",
                "channels": 2,
                "channel_layout": "stereo",
                "language": "eng",
            },
        ],
        "subtitle_streams": [],
    }

    return QCResult(
        job=QCJob(
            job_id=MOCK_JOB_ID,
            status=JobStatus.COMPLETED,
            started_at=_T0,
            completed_at=_T1,
            duration_seconds=252.0,
            tool_version=__version__,
        ),
        asset=Asset(
            input_path="/media/deliveries/Final Delivery v2.mov",
            filename="Final Delivery v2.mov",
            file_size_bytes=33_554_432_000,
            sha256="9f2b7c1e4a8d3f6b5c0e9a2d7f4b8c1e6a3d9f2b7c4e8a1d5f0b3c6e9a2d7f4b",
            duration_seconds=1452.2,
        ),
        preset=PresetRef(
            preset_id="generic_broadcast",
            preset_version="1.0.0",
            client="generic",
            content_type="broadcast",
            sha256="5d2e7b150ac3a6b0cba8f2c9ba58b1dc385f7aabb381991c4e1834b3e26e0000",
        ),
        environment=Environment(
            ffmpeg_version="7.1 (pinned, docker)",
            ffprobe_version="7.1 (pinned, docker)",
            python_version="3.13",
            platform="linux/amd64",
            docker_image="deepdub-qc:0.1.0",
        ),
        summary=summary,
        media_summary=media_summary,  # type: ignore[arg-type]
        measurements=list(measurements.values()),
        findings=findings,
        evidence=evidence,
        artifacts=ArtifactPaths(
            html_report="report.html",
            pdf_report="report.pdf",
            evidence_directory="evidence/",
            raw_directory="raw/",
        ),
    )
