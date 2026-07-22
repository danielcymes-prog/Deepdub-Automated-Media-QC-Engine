"""Clipping-indicator detector via ffmpeg astats (Overall block).

Hard clipping shows as flat runs at peak level; astats reports this as
"Flat factor" (> 0 suspicious) and "Peak count" at a "Peak level dB" near 0.
These are indicators - the authoritative gate is audio.true_peak from the
loudness detector. DC offset is included as a cheap bonus health metric.

Non-finite values (e.g. -inf peak on digital silence) produce no measurement,
so dependent rules report SKIPPED instead of a fabricated number.
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

_FIELDS = {
    "DC offset": ("audio.dc_offset", None),
    "Peak level dB": ("audio.peak_level", "dBFS"),
    "Flat factor": ("audio.flat_factor", None),
    "Peak count": ("audio.peak_count", None),
}
_LINE = re.compile(r"\]\s*([A-Za-z ]+):\s*(-?[\d.]+|[-+]?inf|nan)\s*$", re.MULTILINE)


def parse_astats_overall(stderr: str) -> dict[str, float]:
    """Extract the Overall block fields we use. Non-finite values omitted."""
    overall_start = stderr.rfind("Overall")
    if overall_start == -1:
        return {}
    section = stderr[overall_start:]
    values: dict[str, float] = {}
    for match in _LINE.finditer(section):
        name = match.group(1).strip()
        if name in _FIELDS and name not in values:
            try:
                value = float(match.group(2))
            except ValueError:
                continue
            if math.isfinite(value):
                values[name] = value
    return values


@register
class ClippingDetector(Detector):
    """Peak/flatness clipping indicators per audio stream via ffmpeg astats."""

    detector_id = "audio.clipping.astats"
    detector_version = "1.0.0"
    parameters = (
        "audio.peak_level",
        "audio.flat_factor",
        "audio.peak_count",
        "audio.dc_offset",
    )

    def is_applicable(self, context: QCContext) -> bool:
        return True

    def run(self, context: QCContext) -> list[Measurement]:
        measurements: list[Measurement] = []
        for stream in list_audio_streams(context.input_path):
            stderr = run_audio_filter(context.input_path, stream.ordinal, "astats")
            raw_name = f"astats_a{stream.index}.log"
            context.raw_dir.mkdir(parents=True, exist_ok=True)
            (context.raw_dir / raw_name).write_text(stderr, encoding="utf-8")

            values = parse_astats_overall(stderr)
            for field, (parameter_id, unit) in _FIELDS.items():
                if field in values:
                    measurements.append(
                        self._measurement(
                            context, stream, parameter_id, values[field], unit, raw_name
                        )
                    )
        return measurements

    def _measurement(
        self,
        context: QCContext,
        stream: AudioStreamRef,
        parameter_id: str,
        value: float,
        unit: str | None,
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
