"""Video incident detector: black frames, freeze frames, signal statistics.

Design note: one detector, one decode. Video decoding dominates analysis cost
on large masters (RISKS R9), so blackdetect, freezedetect, and signalstats
share a single filter chain instead of three full decodes. Detector
granularity is an implementation choice; the parameters remain independent
and individually replaceable.

Detection constants (thresholds below) define what counts as a measured
event - they are measurement definitions, not client policy (ADR-001).
Client presets judge the resulting events/counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import fmean

from deepdub_qc.detectors.base import Detector, DetectorRunError, QCContext
from deepdub_qc.detectors.registry import register
from deepdub_qc.models.enums import Category
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.utils import ids
from deepdub_qc.utils.subprocess import ToolError, run_tool

#: Detector constants (measurement definition, not client policy).
BLACK_MIN_DURATION = 0.5  # seconds
BLACK_PIXEL_THRESHOLD = 0.10  # luminance ratio considered black
FREEZE_NOISE_DB = -60.0
FREEZE_MIN_DURATION = 1.0  # seconds

VIDEO_ANALYSIS_TIMEOUT = 7200.0
RAW_FILENAME = "video_incidents.log"

_BLACK = re.compile(r"black_start:(-?[\d.]+)\s+black_end:(-?[\d.]+)\s+black_duration:(-?[\d.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*(-?[\d.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*(-?[\d.]+)")
_LUMA = re.compile(r"lavfi\.signalstats\.(YMIN|YMAX|YAVG)=(-?[\d.]+)")


@dataclass(frozen=True)
class Span:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def parse_black_events(stderr: str) -> list[Span]:
    return [Span(start=float(m.group(1)), end=float(m.group(2))) for m in _BLACK.finditer(stderr)]


def parse_freeze_events(stderr: str, stream_duration: float | None) -> list[Span]:
    """Pair freeze_start/freeze_end; an open freeze is closed at stream end."""
    starts = [float(m.group(1)) for m in _FREEZE_START.finditer(stderr)]
    ends = [float(m.group(1)) for m in _FREEZE_END.finditer(stderr)]
    spans = []
    for i, start in enumerate(starts):
        if i < len(ends):
            spans.append(Span(start=start, end=ends[i]))
        elif stream_duration is not None:
            spans.append(Span(start=start, end=stream_duration))
    return spans


def parse_luma_stats(stdout: str) -> dict[str, float]:
    """Aggregate per-frame signalstats: min(YMIN), max(YMAX), mean(YAVG)."""
    mins: list[float] = []
    maxes: list[float] = []
    avgs: list[float] = []
    for match in _LUMA.finditer(stdout):
        value = float(match.group(2))
        if match.group(1) == "YMIN":
            mins.append(value)
        elif match.group(1) == "YMAX":
            maxes.append(value)
        else:
            avgs.append(value)
    values: dict[str, float] = {}
    if mins:
        values["luma_min"] = min(mins)
    if maxes:
        values["luma_max"] = max(maxes)
    if avgs:
        values["luma_avg"] = round(fmean(avgs), 3)
    return values


@register
class VideoIncidentDetector(Detector):
    """Black/freeze frame events and luma statistics for the first video stream."""

    detector_id = "video.incidents.ffmpeg"
    detector_version = "1.0.0"
    parameters = (
        "video.black_frame_event",
        "video.black_frame_count",
        "video.freeze_frame_event",
        "video.freeze_frame_count",
        "video.luma_min",
        "video.luma_max",
        "video.luma_avg",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True  # emits nothing for files without a video stream

    def run(self, context: QCContext) -> list[Measurement]:
        probe = self._probe_video(context)
        if probe is None:
            return []  # no video stream: dependent rules will SKIP
        stream_index, duration = probe

        video_filter = (
            f"blackdetect=d={BLACK_MIN_DURATION}:pix_th={BLACK_PIXEL_THRESHOLD},"
            f"freezedetect=n={FREEZE_NOISE_DB}dB:d={FREEZE_MIN_DURATION},"
            "signalstats,metadata=print:file=-"
        )
        args = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(context.input_path),
            "-map",
            "0:v:0",
            "-vf",
            video_filter,
            "-f",
            "null",
            "-",
        ]
        try:
            result = run_tool(args, timeout=VIDEO_ANALYSIS_TIMEOUT)
        except ToolError as exc:
            raise DetectorRunError(f"ffmpeg video analysis failed: {exc}") from exc

        context.raw_dir.mkdir(parents=True, exist_ok=True)
        (context.raw_dir / RAW_FILENAME).write_text(result.stderr, encoding="utf-8")

        black = parse_black_events(result.stderr)
        freeze = parse_freeze_events(result.stderr, duration)
        luma = parse_luma_stats(result.stdout)

        measurements = [
            self._measurement(context, "video.black_frame_count", len(black), None, stream_index),
            self._measurement(context, "video.freeze_frame_count", len(freeze), None, stream_index),
        ]
        measurements.extend(
            self._measurement(
                context,
                "video.black_frame_event",
                span.duration,
                "s",
                stream_index,
                start=span.start,
                end=span.end,
            )
            for span in black
        )
        measurements.extend(
            self._measurement(
                context,
                "video.freeze_frame_event",
                span.duration,
                "s",
                stream_index,
                start=span.start,
                end=span.end,
            )
            for span in freeze
        )
        measurements.extend(
            self._measurement(context, f"video.{key}", value, None, stream_index)
            for key, value in sorted(luma.items())
        )
        return measurements

    def _probe_video(self, context: QCContext) -> tuple[int, float | None] | None:
        """Return (global stream index, duration) of the first video stream."""
        args = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=index,duration",
            "-show_entries",
            "format=duration",
            "-print_format",
            "json",
            str(context.input_path),
        ]
        try:
            result = run_tool(args, timeout=120.0)
        except ToolError as exc:
            raise DetectorRunError(f"ffprobe video probe failed: {exc}") from exc
        import json  # noqa: PLC0415

        parsed = json.loads(result.stdout)
        streams = parsed.get("streams", [])
        if not streams:
            return None
        duration_raw = streams[0].get("duration") or parsed.get("format", {}).get("duration")
        try:
            duration = float(duration_raw) if duration_raw is not None else None
        except (TypeError, ValueError):
            duration = None
        return int(streams[0]["index"]), duration

    def _measurement(
        self,
        context: QCContext,
        parameter_id: str,
        value: float | int,
        unit: str | None,
        stream_index: int,
        start: float | None = None,
        end: float | None = None,
    ) -> Measurement:
        return Measurement(
            measurement_id=ids.measurement_id(
                self.detector_id,
                self.detector_version,
                parameter_id,
                stream_index,
                start,
                end,
                value,
            ),
            job_id=context.job_id,
            detector_id=self.detector_id,
            detector_version=self.detector_version,
            parameter_id=parameter_id,
            category=Category.VIDEO,
            value=value,
            unit=unit,
            stream_index=stream_index,
            start_seconds=round(start, 3) if start is not None else None,
            end_seconds=round(end, 3) if end is not None else None,
            metadata={
                "black_min_duration": BLACK_MIN_DURATION,
                "black_pixel_threshold": BLACK_PIXEL_THRESHOLD,
                "freeze_noise_db": FREEZE_NOISE_DB,
                "freeze_min_duration": FREEZE_MIN_DURATION,
            },
            raw_artifact_path=f"raw/{RAW_FILENAME}",
        )
