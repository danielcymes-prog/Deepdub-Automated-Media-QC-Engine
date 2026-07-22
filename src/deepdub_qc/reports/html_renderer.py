"""HTML report rendering (ADR-002, ADR-012, handoff section 17).

Renders the canonical QCResult into a single self-contained HTML document:
no JavaScript, no external assets except brand webfonts (graceful fallback),
printable, styled with the Deepdub design system (dark-first #0A0A0A canvas,
magenta #FE338F accents, Onest type).

Layout follows post-production stakeholder review (2026-07-22): durations as
HH:MM:SS:FF timecode, no file paths, "Target Value" phrasing, channel mapping
instead of raw stream indices, no media-summary/remediation sections.

Inputs: a QCResult (+ optional fixed generation timestamp for tests).
Outputs: HTML text. Side effects: none.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from deepdub_qc.models.finding import ActualValue, Finding
from deepdub_qc.models.report import QCResult
from deepdub_qc.models.rule import (
    ExpectedApprox,
    ExpectedNothing,
    ExpectedPattern,
    ExpectedRange,
    ExpectedValue,
    ExpectedValues,
)

REPORT_HTML_FILENAME = "report.html"
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "report.html.j2"
_WORDMARK_FILE = _TEMPLATE_DIR / "deepdub_wordmark.svg"

#: Frame rate used for timecode derivation when the result does not carry one.
_DEFAULT_TIMECODE_FPS = 24.0


def _fmt_unit(value: object, unit: str | None) -> str:
    return f"{value} {unit}" if unit else f"{value}"


def format_expected(expected: object) -> str:
    """Human-readable rendering of a rule's target value."""
    match expected:
        case ExpectedRange(min=lo, max=hi, unit=unit):
            return f"{lo} to {_fmt_unit(hi, unit)}"
        case ExpectedApprox(value=value, tolerance=tol, unit=unit):
            return f"{_fmt_unit(value, unit)} (tolerance {tol})"
        case ExpectedValues(values=values, unit=unit):
            joined = ", ".join(str(v) for v in values)
            return f"one of: {_fmt_unit(joined, unit)}"
        case ExpectedPattern(pattern=pattern):
            return f"matches pattern {pattern}"
        case ExpectedValue(value=value, unit=unit):
            return _fmt_unit(value, unit)
        case ExpectedNothing() | None:
            return "—"
        case _:
            return str(expected)


def format_actual(actual: ActualValue | None) -> str:
    if actual is None:
        return "—"
    return _fmt_unit(actual.value, actual.unit)


def format_bytes(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or suffix == "TB":
            return f"{value:,.1f} {suffix}" if suffix != "B" else f"{int(value)} B"
        value /= 1024
    return f"{int(size)} B"


def format_timecode(seconds: float | None, fps: float = _DEFAULT_TIMECODE_FPS) -> str:
    """Render seconds as HH:MM:SS:FF timecode at the given frame rate.

    Canonical time is seconds (DATA_MODEL_REVIEW item 8); timecode is derived
    at render time. Frame component is floor()ed so a timecode never points
    past the actual event.
    """
    if seconds is None or seconds < 0:
        return "—"
    total = int(seconds)
    frames = int((seconds - total) * fps)  # floor: never point past the event
    if frames >= int(round(fps)):  # guard against float edge cases
        frames = 0
        total += 1
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def _build_channel_map(result: QCResult) -> dict[int, str]:
    """Map stream indices to reviewer-facing channel labels.

    Built from the canonical media_summary stream maps: audio streams show
    layout + language ("stereo · DEU"), video streams show "Video".
    """
    mapping: dict[int, str] = {}
    for stream in result.media_summary.get("video_streams", []):  # type: ignore[union-attr]
        if isinstance(stream, dict):
            index = stream.get("index")
            if isinstance(index, int):
                mapping[index] = "Video"
    for stream in result.media_summary.get("audio_streams", []):  # type: ignore[union-attr]
        if isinstance(stream, dict):
            index = stream.get("index")
            if isinstance(index, int):
                layout = str(stream.get("channel_layout") or "audio")
                language = stream.get("language")
                label = f"{layout} · {str(language).upper()}" if language else layout
                mapping[index] = label
    return mapping


def _channel(finding: Finding, channel_map: dict[int, str]) -> str:
    if finding.stream_index is None:
        return "—"
    return channel_map.get(finding.stream_index, f"stream {finding.stream_index}")


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["expected"] = format_expected
    env.filters["actual"] = format_actual
    env.filters["filesize"] = format_bytes
    return env


def render_html(result: QCResult, generated_at: datetime | None = None) -> str:
    """Render the canonical QCResult to a self-contained, branded HTML document.

    `generated_at` is injectable so tests can produce stable output; it is a
    declared volatile field and never part of the determinism contract.
    """
    generated = generated_at or datetime.now(UTC)
    env = _build_env()
    fps_raw = result.media_summary.get("timecode_frame_rate")
    fps = float(fps_raw) if isinstance(fps_raw, int | float) else _DEFAULT_TIMECODE_FPS
    env.filters["timecode"] = lambda s: format_timecode(s, fps)
    channel_map = _build_channel_map(result)
    env.filters["channel"] = lambda f: _channel(f, channel_map)

    findings = result.findings
    detector_versions = sorted({(m.detector_id, m.detector_version) for m in result.measurements})
    context = {
        "r": result,
        "wordmark": Markup(_WORDMARK_FILE.read_text(encoding="utf-8")),
        "generated_date": generated.strftime("%d %b %Y"),
        "generated_time": generated.strftime("%H:%M UTC"),
        "blocking_failures": [f for f in findings if f.status == "FAIL" and f.blocking],
        "non_blocking_failures": [f for f in findings if f.status == "FAIL" and not f.blocking],
        "warnings": [f for f in findings if f.status == "WARNING"],
        "errors": [f for f in findings if f.status == "ERROR"],
        "skipped": [f for f in findings if f.status in ("SKIPPED", "NOT_APPLICABLE")],
        "passed": [f for f in findings if f.status == "PASS"],
        "incidents": [f for f in findings if f.start_seconds is not None],
        "detector_versions": detector_versions,
    }
    template = env.get_template(_TEMPLATE_NAME)
    return template.render(**context)


def write_html_report(
    result: QCResult, output_dir: Path, generated_at: datetime | None = None
) -> Path:
    """Write report.html into the job output directory and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / REPORT_HTML_FILENAME
    target.write_text(render_html(result, generated_at), encoding="utf-8")
    return target
