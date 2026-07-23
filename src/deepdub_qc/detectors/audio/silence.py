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
