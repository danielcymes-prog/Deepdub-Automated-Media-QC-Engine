"""Deterministic diff between a deepdub-qc report.json and a Vidchecker report.

Why: parity claims require identical bytes and reproducible comparison
(docs/VALIDATION.md method notes). This engine encodes that method: verify
file identity first, then map Vidchecker alerts onto deepdub-qc measurements
with explicit tolerances. No AI, no judgment - rows and numbers only.

Inputs: the canonical report.json parsed as a dict (source of truth,
ADR-002) and a parsed ``VidcheckerTask``.
Outputs: a ``ComparisonResult`` of typed rows.
Side effects: none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePath, PureWindowsPath
from typing import Any

from deepdub_qc.comparison.vidchecker import (
    ALERT_CLIPPING,
    ALERT_LOUDNESS_INFO,
    ALERT_LOUDNESS_INTEGRATED,
    ALERT_MIN_LEVEL,
    VidcheckerAlert,
    VidcheckerTask,
)
from deepdub_qc.exceptions import DeepdubQCError

#: Vidchecker stream indices are 1-based; deepdub-qc stream_index is 0-based.
_STREAM_OFFSET = 1


class IdentityMismatchError(DeepdubQCError):
    """The two reports do not describe the same file bytes."""


class RowStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    VIDCHECKER_NOT_RUN = "VIDCHECKER_NOT_RUN"
    INFO = "INFO"


@dataclass(frozen=True)
class Tolerances:
    """Agreement thresholds. Defaults reflect broadcast practice and the

    cross-tool definitional differences documented in docs/VALIDATION.md.
    """

    loudness_lu: float = 0.3
    span_seconds: float = 1.0


@dataclass(frozen=True)
class ComparisonRow:
    check: str
    stream: str
    vidchecker: str
    deepdub: str
    delta: str
    status: RowStatus
    note: str = ""


@dataclass
class ComparisonResult:
    filename: str
    file_size: int
    rows: list[ComparisonRow] = field(default_factory=list)

    @property
    def mismatches(self) -> int:
        return sum(1 for row in self.rows if row.status is RowStatus.MISMATCH)

    @property
    def matches(self) -> int:
        return sum(1 for row in self.rows if row.status is RowStatus.MATCH)

    @property
    def not_run(self) -> int:
        return sum(1 for row in self.rows if row.status is RowStatus.VIDCHECKER_NOT_RUN)

    def to_markdown(self) -> str:
        lines = [
            f"Parity comparison — `{PurePath(self.filename).name}` "
            f"({self.file_size:,} bytes, identical in both reports)",
            "",
            "| Check | Stream | Vidchecker | deepdub-qc | Delta | Status | Note |",
            "|---|---|---|---|---|---|---|",
        ]
        lines.extend(
            f"| {r.check} | {r.stream} | {r.vidchecker} | {r.deepdub} "
            f"| {r.delta} | {r.status.value} | {r.note} |"
            for r in self.rows
        )
        return "\n".join(lines) + "\n"


def _measurements(report: dict[str, Any], parameter_id: str) -> list[dict[str, Any]]:
    return [m for m in report.get("measurements", []) if m.get("parameter_id") == parameter_id]


def _for_stream(
    measurements: list[dict[str, Any]], stream_index: int | None
) -> list[dict[str, Any]]:
    if stream_index is None:
        return measurements
    return [m for m in measurements if m.get("stream_index") == stream_index]


def _stream_label(alert: VidcheckerAlert) -> str:
    if alert.stream_index is None:
        return "—"
    label = f"track {alert.stream_index}"
    return f"{label} ch {alert.channels}" if alert.channels else label


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _verify_identity(report: dict[str, Any], task: VidcheckerTask) -> tuple[str, int]:
    asset = report.get("asset", {})
    our_size = asset.get("file_size_bytes")
    our_name = PurePath(str(asset.get("input_path") or asset.get("filename") or "")).name
    vc_name = PureWindowsPath(task.filename).name
    if our_size is None or task.file_size is None:
        raise IdentityMismatchError(
            "Cannot verify file identity: file size missing from one of the reports"
        )
    if our_size != task.file_size:
        raise IdentityMismatchError(
            f"Reports describe different files: deepdub-qc {our_name} ({our_size:,} bytes) "
            f"vs Vidchecker {vc_name} ({task.file_size:,} bytes). "
            "Parity comparison requires identical bytes."
        )
    return our_name or vc_name, our_size


def _loudness_rows(
    report: dict[str, Any], task: VidcheckerTask, tolerances: Tolerances
) -> list[ComparisonRow]:
    rows = []
    ours_all = _measurements(report, "audio.integrated_loudness")
    for alert in task.alerts:
        if alert.alert_type_id not in (ALERT_LOUDNESS_INTEGRATED, ALERT_LOUDNESS_INFO):
            continue
        if alert.not_run or alert.loudness_db is None:
            continue
        stream = alert.stream_index - _STREAM_OFFSET if alert.stream_index is not None else None
        ours = _for_stream(ours_all, stream) or ours_all
        if not ours:
            rows.append(
                ComparisonRow(
                    check="Integrated loudness",
                    stream=_stream_label(alert),
                    vidchecker=f"{alert.loudness_db} LUFS",
                    deepdub="no measurement",
                    delta="—",
                    status=RowStatus.MISMATCH,
                    note="deepdub-qc produced no loudness measurement for this stream",
                )
            )
            continue
        value = float(ours[0]["value"])
        delta = abs(value - alert.loudness_db)
        rows.append(
            ComparisonRow(
                check="Integrated loudness",
                stream=_stream_label(alert),
                vidchecker=f"{alert.loudness_db} LUFS",
                deepdub=f"{value} LUFS",
                delta=f"{delta:.2f} LU",
                status=RowStatus.MATCH if delta <= tolerances.loudness_lu else RowStatus.MISMATCH,
                note=f"tolerance {tolerances.loudness_lu} LU",
            )
        )
    return rows


def _min_level_rows(
    report: dict[str, Any], task: VidcheckerTask, tolerances: Tolerances
) -> list[ComparisonRow]:
    rows = []
    # low_rms_event is the exact Min-Level counterpart (windowed RMS);
    # silence spans remain as fallbacks for reports from older detectors.
    span_parameters = (
        "audio.low_rms_event",
        "audio.tail_silence_duration",
        "audio.internal_silence_event",
    )
    for alert in task.alerts:
        if alert.alert_type_id != ALERT_MIN_LEVEL or alert.not_run:
            continue
        if alert.begin_seconds is None or alert.end_seconds is None:
            continue
        stream = alert.stream_index - _STREAM_OFFSET if alert.stream_index is not None else None
        candidates = [
            m
            for parameter in span_parameters
            for m in _for_stream(_measurements(report, parameter), stream)
            if m.get("start_seconds") is not None
            and m.get("end_seconds") is not None
            and float(m.get("value") or 0) > 0
        ]
        vc_span = f"{alert.begin_seconds:.0f}-{alert.end_seconds:.0f}s"
        best = max(
            candidates,
            key=lambda m: _overlap(
                alert.begin_seconds or 0.0,
                alert.end_seconds or 0.0,
                float(m["start_seconds"]),
                float(m["end_seconds"]),
            ),
            default=None,
        )
        if best is None or (
            _overlap(
                alert.begin_seconds,
                alert.end_seconds,
                float(best["start_seconds"]),
                float(best["end_seconds"]),
            )
            == 0.0
        ):
            rows.append(
                ComparisonRow(
                    check="Min level / silence span",
                    stream=_stream_label(alert),
                    vidchecker=vc_span,
                    deepdub="no overlapping silence span",
                    delta="—",
                    status=RowStatus.MISMATCH,
                    note="Vidchecker reports a low-level span deepdub-qc did not detect",
                )
            )
            continue
        vc_duration = alert.end_seconds - alert.begin_seconds
        our_start, our_end = float(best["start_seconds"]), float(best["end_seconds"])
        our_duration = float(best["value"])
        delta = abs(our_duration - vc_duration)
        rows.append(
            ComparisonRow(
                check="Min level / silence span",
                stream=_stream_label(alert),
                vidchecker=f"{vc_span} ({vc_duration:.1f}s)",
                deepdub=f"{our_start:.1f}-{our_end:.1f}s ({our_duration:.3f}s)",
                delta=f"{delta:.2f} s",
                status=(
                    RowStatus.MATCH if delta <= tolerances.span_seconds else RowStatus.MISMATCH
                ),
                note=f"tolerance {tolerances.span_seconds} s; definitions differ "
                "(-95 dB RMS windowed vs -60 dB silencedetect)",
            )
        )
    return rows


def _clipping_row(report: dict[str, Any], task: VidcheckerTask) -> ComparisonRow | None:
    clip_alerts = [a for a in task.alerts if a.alert_type_id == ALERT_CLIPPING]
    if any(a.not_run for a in clip_alerts):
        return None  # covered by the not-run rows
    flats = [float(m["value"]) for m in _measurements(report, "audio.flat_factor")]
    if not flats:
        return None
    our_flat = max(flats)
    real_alerts = [a for a in clip_alerts if not a.not_run]
    vc_text = f"{len(real_alerts)} clipping alert(s)" if real_alerts else "no clipping alerts"
    our_text = f"max flat factor {our_flat}"
    agree = bool(real_alerts) == (our_flat > 0.0)
    return ComparisonRow(
        check="Clipping",
        stream="all audio",
        vidchecker=vc_text,
        deepdub=our_text,
        delta="—",
        status=RowStatus.MATCH if agree else RowStatus.MISMATCH,
        note="presence agreement (definitions differ: consecutive equal samples vs flat factor)",
    )


def compare_reports(
    report: dict[str, Any],
    task: VidcheckerTask,
    tolerances: Tolerances | None = None,
) -> ComparisonResult:
    """Compare a deepdub-qc report.json dict against a Vidchecker task.

    Raises IdentityMismatchError unless both reports describe the same bytes.
    """
    tolerances = tolerances or Tolerances()
    filename, file_size = _verify_identity(report, task)
    result = ComparisonResult(filename=filename, file_size=file_size)

    result.rows.extend(_loudness_rows(report, task, tolerances))
    result.rows.extend(_min_level_rows(report, task, tolerances))
    clipping = _clipping_row(report, task)
    if clipping is not None:
        result.rows.append(clipping)

    result.rows.extend(
        ComparisonRow(
            check=alert.type_name or "Unknown test",
            stream=_stream_label(alert),
            vidchecker="test not run",
            deepdub="measured (see report.json)",
            delta="—",
            status=RowStatus.VIDCHECKER_NOT_RUN,
            note=alert.detail,
        )
        for alert in task.alerts
        if alert.not_run
    )

    our_verdict = str(report.get("summary", {}).get("overall_status", ""))
    result.rows.append(
        ComparisonRow(
            check="Overall verdict",
            stream="—",
            vidchecker=task.verdict,
            deepdub=our_verdict,
            delta="—",
            status=RowStatus.INFO,
            note="verdicts depend on template/preset policy, not only measurements",
        )
    )
    return result
