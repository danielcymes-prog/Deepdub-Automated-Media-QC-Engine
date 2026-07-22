"""Silence detector: head/tail durations and timestamped internal events.

Detection parameters (noise floor, minimum duration) are detector constants,
not client thresholds: they define what counts as a measured silence event.
Client presets judge the resulting durations/counts (ADR-001 separation).

Emitted per audio stream:
- audio.head_silence_duration  (always; 0.0 when none)
- audio.tail_silence_duration  (always; 0.0 when none)
- audio.internal_silence_count (always)
- audio.internal_silence_event (one per event, value = duration, with span)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deepdub_qc.detectors.audio.common import (
    AudioStreamRef,
    list_audio_streams,
    run_audio_filter,
)
from deepdub_qc.detectors.base import Detector, QCContext
from deepdub_qc.detectors.registry import register
from deepdub_qc.models.enums import Category
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.utils import ids

#: Detector constants (measurement definition, not client policy).
NOISE_FLOOR_DB = -60.0
MIN_SILENCE_SECONDS = 0.5
#: Tolerance when deciding whether a silence touches the stream head/tail.
_EDGE_EPSILON = 0.1

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*(-?[\d.]+)")


@dataclass(frozen=True)
class SilenceSpan:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def parse_silences(stderr: str, stream_duration: float | None) -> list[SilenceSpan]:
    """Pair silence_start/silence_end lines into spans.

    A trailing silence_start without silence_end means silence until EOF;
    it is closed at the stream duration when known.
    """
    starts = [float(m.group(1)) for m in _START.finditer(stderr)]
    ends = [(float(m.group(1)), float(m.group(2))) for m in _END.finditer(stderr)]
    spans = []
    for i, start in enumerate(starts):
        if i < len(ends):
            spans.append(SilenceSpan(start=max(start, 0.0), end=ends[i][0]))
        elif stream_duration is not None:
            spans.append(SilenceSpan(start=max(start, 0.0), end=stream_duration))
    return spans


def classify(
    spans: list[SilenceSpan], stream_duration: float | None
) -> tuple[float, float, list[SilenceSpan]]:
    """Split spans into (head_duration, tail_duration, internal_events)."""
    head = 0.0
    tail = 0.0
    internal: list[SilenceSpan] = []
    for span in spans:
        is_head = span.start <= _EDGE_EPSILON
        is_tail = stream_duration is not None and span.end >= stream_duration - _EDGE_EPSILON
        if is_head:
            head = span.duration
        if is_tail:
            tail = span.duration
        if not is_head and not is_tail:
            internal.append(span)
    return head, tail, internal


@register
class SilenceDetector(Detector):
    """Head/tail/internal silence per audio stream via ffmpeg silencedetect."""

    detector_id = "audio.silence"
    detector_version = "1.0.0"
    parameters = (
        "audio.head_silence_duration",
        "audio.tail_silence_duration",
        "audio.internal_silence_count",
        "audio.internal_silence_event",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True

    def run(self, context: QCContext) -> list[Measurement]:
        audio_filter = f"silencedetect=noise={NOISE_FLOOR_DB}dB:d={MIN_SILENCE_SECONDS}"
        measurements: list[Measurement] = []
        for stream in list_audio_streams(context.input_path):
            stderr = run_audio_filter(context.input_path, stream.ordinal, audio_filter)
            raw_name = f"silencedetect_a{stream.index}.log"
            context.raw_dir.mkdir(parents=True, exist_ok=True)
            (context.raw_dir / raw_name).write_text(stderr, encoding="utf-8")

            spans = parse_silences(stderr, stream.duration_seconds)
            head, tail, internal = classify(spans, stream.duration_seconds)

            measurements.append(
                self._measurement(
                    context,
                    stream,
                    "audio.head_silence_duration",
                    head,
                    "s",
                    raw_name,
                    start=0.0 if head > 0 else None,
                    end=head if head > 0 else None,
                )
            )
            measurements.append(
                self._measurement(
                    context,
                    stream,
                    "audio.tail_silence_duration",
                    tail,
                    "s",
                    raw_name,
                    start=(
                        stream.duration_seconds - tail
                        if tail > 0 and stream.duration_seconds is not None
                        else None
                    ),
                    end=stream.duration_seconds if tail > 0 else None,
                )
            )
            measurements.append(
                self._measurement(
                    context, stream, "audio.internal_silence_count", len(internal), None, raw_name
                )
            )
            measurements.extend(
                self._measurement(
                    context,
                    stream,
                    "audio.internal_silence_event",
                    span.duration,
                    "s",
                    raw_name,
                    start=span.start,
                    end=span.end,
                )
                for span in internal
            )
        return measurements

    def _measurement(
        self,
        context: QCContext,
        stream: AudioStreamRef,
        parameter_id: str,
        value: float | int,
        unit: str | None,
        raw_name: str,
        start: float | None = None,
        end: float | None = None,
    ) -> Measurement:
        return Measurement(
            measurement_id=ids.measurement_id(
                self.detector_id,
                self.detector_version,
                parameter_id,
                stream.index,
                start,
                end,
                value,
            ),
            job_id=context.job_id,
            detector_id=self.detector_id,
            detector_version=self.detector_version,
            parameter_id=parameter_id,
            category=Category.AUDIO,
            value=value,
            unit=unit,
            stream_index=stream.index,
            start_seconds=round(start, 3) if start is not None else None,
            end_seconds=round(end, 3) if end is not None else None,
            metadata={
                "noise_floor_db": NOISE_FLOOR_DB,
                "min_silence_seconds": MIN_SILENCE_SECONDS,
            },
            raw_artifact_path=f"raw/{raw_name}",
        )
