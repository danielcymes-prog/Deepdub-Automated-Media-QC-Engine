"""Consolidated audio analysis: loudness + silence + clipping in ONE decode.

Why: the original three audio detectors each decoded the full file, so a
49-minute master was read three times per stream (plus probes and hashing).
On network storage or antivirus-scanned hosts that multiplied into unusable
runtimes (field report, 2026-07-22; RISKS R9). This detector chains
ebur128, silencedetect, and astats into a single ffmpeg filter graph, reading
each audio stream exactly once. Vidchecker achieves its speed the same way.

Parameter IDs are identical to the detectors it replaces, so presets and
rules are untouched - detector replaceability paying off (ADR-010).
"""

from __future__ import annotations

from deepdub_qc.detectors.audio.clipping import ASTATS_FIELDS, parse_astats_overall
from deepdub_qc.detectors.audio.common import (
    AudioStreamRef,
    list_audio_streams,
    run_audio_filter,
)
from deepdub_qc.detectors.audio.loudness import parse_ebur128
from deepdub_qc.detectors.audio.silence import (
    MIN_SILENCE_SECONDS,
    NOISE_FLOOR_DB,
    classify,
    parse_silences,
)
from deepdub_qc.detectors.base import Detector, QCContext
from deepdub_qc.detectors.registry import register
from deepdub_qc.models.enums import Category
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.utils import ids

_LOUDNESS_SPEC = [
    ("integrated_loudness", "audio.integrated_loudness", "LUFS"),
    ("loudness_range", "audio.loudness_range", "LU"),
    ("true_peak", "audio.true_peak", "dBTP"),
    ("max_momentary", "audio.max_momentary_loudness", "LUFS"),
    ("max_short_term", "audio.max_short_term_loudness", "LUFS"),
]

COMBINED_FILTER = (
    f"ebur128=peak=true,silencedetect=noise={NOISE_FLOOR_DB}dB:d={MIN_SILENCE_SECONDS},astats"
)


@register
class AudioAnalysisDetector(Detector):
    """Loudness, silence, and clipping indicators in a single pass per stream."""

    detector_id = "audio.analysis.ffmpeg"
    detector_version = "1.0.0"
    parameters = (
        "audio.integrated_loudness",
        "audio.loudness_range",
        "audio.true_peak",
        "audio.max_momentary_loudness",
        "audio.max_short_term_loudness",
        "audio.head_silence_duration",
        "audio.tail_silence_duration",
        "audio.internal_silence_count",
        "audio.internal_silence_event",
        "audio.peak_level",
        "audio.flat_factor",
        "audio.peak_count",
        "audio.dc_offset",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True  # emits nothing when the file has no audio streams

    def run(self, context: QCContext) -> list[Measurement]:
        measurements: list[Measurement] = []
        for stream in list_audio_streams(context.input_path):
            stderr = run_audio_filter(context.input_path, stream.ordinal, COMBINED_FILTER)
            raw_name = f"audio_analysis_a{stream.index}.log"
            context.raw_dir.mkdir(parents=True, exist_ok=True)
            (context.raw_dir / raw_name).write_text(stderr, encoding="utf-8")

            measurements.extend(self._loudness(context, stream, stderr, raw_name))
            measurements.extend(self._silence(context, stream, stderr, raw_name))
            measurements.extend(self._clipping(context, stream, stderr, raw_name))
        return measurements

    # ------------------------------------------------------------------ sections

    def _loudness(
        self, context: QCContext, stream: AudioStreamRef, stderr: str, raw_name: str
    ) -> list[Measurement]:
        values = parse_ebur128(stderr)
        return [
            self._measurement(context, stream, parameter, values[key], unit, raw_name)
            for key, parameter, unit in _LOUDNESS_SPEC
            if key in values
        ]

    def _silence(
        self, context: QCContext, stream: AudioStreamRef, stderr: str, raw_name: str
    ) -> list[Measurement]:
        spans = parse_silences(stderr, stream.duration_seconds)
        head, tail, internal = classify(spans, stream.duration_seconds)
        out = [
            self._measurement(
                context,
                stream,
                "audio.head_silence_duration",
                head,
                "s",
                raw_name,
                start=0.0 if head > 0 else None,
                end=head if head > 0 else None,
            ),
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
            ),
            self._measurement(
                context, stream, "audio.internal_silence_count", len(internal), None, raw_name
            ),
        ]
        out.extend(
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
        return out

    def _clipping(
        self, context: QCContext, stream: AudioStreamRef, stderr: str, raw_name: str
    ) -> list[Measurement]:
        values = parse_astats_overall(stderr)
        return [
            self._measurement(context, stream, parameter_id, values[field], unit, raw_name)
            for field, (parameter_id, unit) in ASTATS_FIELDS.items()
            if field in values
        ]

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
