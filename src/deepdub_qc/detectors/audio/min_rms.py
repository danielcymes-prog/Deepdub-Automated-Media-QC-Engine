"""Windowed-RMS low-level detection (Vidchecker "Min Level" equivalent).

Why: Vidchecker's Min Level check measures RMS over fixed windows and alerts
when it stays below a floor (e.g. -95 dB RMS for 5 s). Our silencedetect
approximation (-60 dB sample gate) converged on the same events in practice
(docs/VALIDATION.md), but this module measures the same *quantity* Vidchecker
does: per-window RMS via a second astats instance in the single-pass chain
(asetnsamples -> astats reset per frame -> ametadata print to stdout).

Detection constants below are measurement definitions, not client policy
(ADR-001): windows whose overall RMS is below LOW_RMS_THRESHOLD_DB merge
into events; presets judge event existence/duration/count.

Inputs: ffmpeg stdout containing ametadata window prints.
Outputs: parsed (window_start, rms_db) pairs and merged low-RMS spans.
Side effects: none (pure parsing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Measurement definition: a window is "low" below this overall RMS level.
LOW_RMS_THRESHOLD_DB = -90.0
#: Measurement definition: RMS window length in seconds.
RMS_WINDOW_SECONDS = 5.0
#: astats reports digital silence as -inf; represented numerically as this.
DIGITAL_SILENCE_DB = -144.0

_PTS_TIME = re.compile(r"pts_time:\s*(-?[\d.]+)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?(?:[\d.]+|inf))")


@dataclass(frozen=True)
class RmsWindow:
    start: float
    rms_db: float


def windowed_rms_filter(sample_rate: int) -> str:
    """Filter-chain suffix computing per-window overall RMS (prints to stdout)."""
    samples = max(1, int(sample_rate * RMS_WINDOW_SECONDS))
    return (
        f"asetnsamples=n={samples}:p=0,"
        "astats=metadata=1:reset=1,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )


def parse_windowed_rms(stdout: str) -> list[RmsWindow]:
    """Pair each ametadata frame header (pts_time) with its RMS_level line."""
    windows: list[RmsWindow] = []
    pending_start: float | None = None
    for line in stdout.splitlines():
        pts = _PTS_TIME.search(line)
        if pts is not None:
            pending_start = float(pts.group(1))
            continue
        rms = _RMS.search(line)
        if rms is not None and pending_start is not None:
            raw = rms.group(1)
            value = DIGITAL_SILENCE_DB if raw == "-inf" else float(raw)
            windows.append(RmsWindow(start=pending_start, rms_db=value))
            pending_start = None
    return windows


@dataclass(frozen=True)
class LowRmsSpan:
    start: float
    end: float
    min_rms_db: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


def merge_low_rms_events(
    windows: list[RmsWindow],
    stream_duration: float | None,
    threshold_db: float = LOW_RMS_THRESHOLD_DB,
    window_seconds: float = RMS_WINDOW_SECONDS,
) -> list[LowRmsSpan]:
    """Merge consecutive low windows into spans (last window capped at EOF)."""
    events: list[LowRmsSpan] = []
    run_start: float | None = None
    run_min = 0.0

    def close(end: float) -> None:
        nonlocal run_start
        if run_start is not None:
            capped = min(end, stream_duration) if stream_duration is not None else end
            events.append(
                LowRmsSpan(start=round(run_start, 3), end=round(capped, 3), min_rms_db=run_min)
            )
            run_start = None

    for window in windows:
        if window.rms_db < threshold_db:
            if run_start is None:
                run_start = window.start
                run_min = window.rms_db
            else:
                run_min = min(run_min, window.rms_db)
        else:
            close(window.start)
    if windows:
        close(windows[-1].start + window_seconds)
    return events
