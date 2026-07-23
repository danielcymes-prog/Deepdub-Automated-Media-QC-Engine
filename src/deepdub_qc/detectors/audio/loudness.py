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
