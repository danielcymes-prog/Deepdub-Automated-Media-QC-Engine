"""EBU R128 loudness detector (single pass per audio stream).

Parses the ffmpeg ebur128 summary (integrated loudness, loudness range, true
peak) plus the per-interval momentary/short-term maxima. Raw filter output is
preserved at raw/ebur128_a<index>.log.

Values ffmpeg reports as nan (e.g. digital silence) produce no measurement:
the dependent rule then reports SKIPPED rather than a fabricated number.
"""

from __future__ import annotations

import math
import re

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

_SUMMARY_I = re.compile(r"^\s*I:\s+(-?[\d.]+|nan)\s+LUFS\s*$", re.MULTILINE)
_SUMMARY_LRA = re.compile(r"^\s*LRA:\s+(-?[\d.]+|nan)\s+LU\s*$", re.MULTILINE)
_SUMMARY_PEAK = re.compile(r"^\s*Peak:\s+(-?[\d.]+|nan|-inf)\s+dBFS\s*$", re.MULTILINE)
_INTERVAL_M = re.compile(r"\bM:\s*(-?[\d.]+)")
_INTERVAL_S = re.compile(r"\bS:\s*(-?[\d.]+)")


def parse_ebur128(stderr: str) -> dict[str, float]:
    """Extract loudness values from ebur128 stderr. Non-finite values omitted."""
    summary_start = stderr.rfind("Summary:")
    summary = stderr[summary_start:] if summary_start != -1 else ""
    values: dict[str, float] = {}

    def put(key: str, pattern: re.Pattern[str], text: str) -> None:
        match = pattern.search(text)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                return
            if math.isfinite(value):
                values[key] = value

    put("integrated_loudness", _SUMMARY_I, summary)
    put("loudness_range", _SUMMARY_LRA, summary)
    put("true_peak", _SUMMARY_PEAK, summary)

    momentary = [float(v) for v in _INTERVAL_M.findall(stderr)]
    short_term = [float(v) for v in _INTERVAL_S.findall(stderr)]
    if momentary:
        values["max_momentary"] = max(momentary)
    if short_term:
        values["max_short_term"] = max(short_term)
    return values


@register
class LoudnessDetector(Detector):
    """EBU R128 loudness per audio stream via ffmpeg ebur128 (peak=true)."""

    detector_id = "audio.loudness.ebur128"
    detector_version = "1.0.0"
    parameters = (
        "audio.integrated_loudness",
        "audio.loudness_range",
        "audio.true_peak",
        "audio.max_momentary_loudness",
        "audio.max_short_term_loudness",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True  # cheaply skips inside run() when no audio streams exist

    def run(self, context: QCContext) -> list[Measurement]:
        measurements: list[Measurement] = []
        for stream in list_audio_streams(context.input_path):
            stderr = run_audio_filter(context.input_path, stream.ordinal, "ebur128=peak=true")
            raw_name = f"ebur128_a{stream.index}.log"
            context.raw_dir.mkdir(parents=True, exist_ok=True)
            (context.raw_dir / raw_name).write_text(stderr, encoding="utf-8")

            values = parse_ebur128(stderr)
            spec = [
                ("integrated_loudness", "audio.integrated_loudness", "LUFS"),
                ("loudness_range", "audio.loudness_range", "LU"),
                ("true_peak", "audio.true_peak", "dBTP"),
                ("max_momentary", "audio.max_momentary_loudness", "LUFS"),
                ("max_short_term", "audio.max_short_term_loudness", "LUFS"),
            ]
            measurements.extend(
                self._measurement(context, stream, parameter, values[key], unit, raw_name)
                for key, parameter, unit in spec
                if key in values
            )
        return measurements

    def _measurement(
        self,
        context: QCContext,
        stream: AudioStreamRef,
        parameter_id: str,
        value: float,
        unit: str,
        raw_name: str,
    ) -> Measurement:
        return Measurement(
            measurement_id=ids.measurement_id(
                self.detector_id,
                self.detector_version,
                parameter_id,
                stream.index,
                None,
                None,
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
            raw_artifact_path=f"raw/{raw_name}",
        )
