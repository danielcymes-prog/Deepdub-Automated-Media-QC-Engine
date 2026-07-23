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

ASTATS_FIELDS = {
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
        if name in ASTATS_FIELDS and name not in values:
            try:
                value = float(match.group(2))
            except ValueError:
                continue
            if math.isfinite(value):
                values[name] = value
    return values
