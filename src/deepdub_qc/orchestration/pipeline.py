"""End-to-end analysis pipeline: file + preset -> QCResult + rendered reports.

Sequence (ARCHITECTURE section 3): hash asset -> run detectors (failures
recorded, never hidden) -> evaluate rules -> assemble canonical QCResult ->
render JSON/HTML/PDF into the job output directory.

The pipeline is a pure library entry point: no CLI or API imports, so service
extraction (Phase 7) wraps this function unchanged.
"""

from __future__ import annotations

import json
import logging
import platform as platform_module
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from deepdub_qc import __version__
from deepdub_qc.detectors.base import Detector, DetectorRunError, QCContext
from deepdub_qc.detectors.metadata.ffprobe import RAW_FILENAME, build_media_summary
from deepdub_qc.detectors.registry import all_detectors
from deepdub_qc.exceptions import DeepdubQCError
from deepdub_qc.models.asset import Asset
from deepdub_qc.models.enums import JobStatus
from deepdub_qc.models.evidence import Evidence
from deepdub_qc.models.job import QCJob
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.models.report import ArtifactPaths, Environment, PresetRef, QCResult
from deepdub_qc.presets.loader import load_preset, preset_sha256
from deepdub_qc.reports.html_renderer import write_html_report
from deepdub_qc.reports.json_renderer import write_json_report
from deepdub_qc.rules.engine import build_summary, evaluate
from deepdub_qc.utils.hashing import sha256_file
from deepdub_qc.utils.subprocess import ToolError, run_tool

logger = logging.getLogger(__name__)


class InputFileError(DeepdubQCError):
    """The input media file is missing or unreadable."""


@dataclass(frozen=True)
class AnalysisOptions:
    """Pipeline options. Defaults match the local CLI."""

    render_pdf: bool = True
    job_id: UUID | None = None  # injectable for tests; random by default
    #: Optional stage-progress callback (message, fraction complete in [0, 1]).
    #: Long analyses would otherwise be silent: full-file decodes and hashing
    #: take minutes on large masters. The fraction is stage-weighted (see
    #: _ProgressReporter), display only - never canonical data.
    on_progress: Callable[[str, float], None] | None = None


class _ProgressReporter:
    """Translates stage completions into (message, fraction) callbacks.

    The fraction is STAGE-weighted, not time-weighted: each applicable
    detector and each fixed post-stage (rules, evidence, hashing, rendering)
    counts as one unit, so a wheel driven by it advances monotonically but
    not at wall-clock rate - a full-file loudness decode and a millisecond
    rule pass each move it one step. Honest about work completed, silent
    about time remaining. Display only, never canonical (ADR-001).
    """

    FIXED_STAGES = 4  # rules, evidence, hashing, rendering

    def __init__(self, callback: Callable[[str, float], None] | None) -> None:
        self._callback = callback or (lambda _message, _fraction: None)
        self._done = 0
        self._total = self.FIXED_STAGES

    def plan(self, detector_count: int) -> None:
        """Fix the denominator once the applicable detector list is known."""
        self._total = detector_count + self.FIXED_STAGES

    def announce(self, message: str) -> None:
        """A stage is starting; the fraction reports work completed so far."""
        self._callback(message, self._fraction())

    def finish_stage(self, message: str | None = None) -> None:
        """A stage finished (a skipped stage passes no message but still counts)."""
        self._done += 1
        if message is not None:
            self._callback(message, self._fraction())

    def _fraction(self) -> float:
        return round(self._done / self._total, 4)


def run_analysis(
    input_path: Path,
    preset_path: Path,
    output_dir: Path,
    options: AnalysisOptions | None = None,
) -> QCResult:
    """Analyze one media file against one preset and render all reports.

    Raises:
        InputFileError: input missing/unreadable (CLI exit code 5).
        PresetError subclasses: invalid preset (CLI exit code 4).
    """
    options = options or AnalysisOptions()
    started_wall = datetime.now(UTC)
    started = time.monotonic()

    if not input_path.is_file():
        raise InputFileError(f"input file not found: {input_path}")

    preset = load_preset(preset_path)
    job_id = options.job_id or uuid4()
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "job started",
        extra={
            "job_id": str(job_id),
            "preset_id": preset.preset.id,
            "preset_version": preset.preset.version,
            "stage": "start",
        },
    )

    progress = _ProgressReporter(options.on_progress)

    context = QCContext(job_id=job_id, input_path=input_path, raw_dir=raw_dir)
    measurements, failed_parameters, failure_reasons = _run_detectors(context, progress)

    progress.announce("Evaluating rules")
    findings = evaluate(
        preset,
        measurements,
        job_id,
        failed_parameters=frozenset(failed_parameters),
        failure_reasons=failure_reasons,
    )
    progress.finish_stage()

    evidence: list[Evidence] = []
    if preset.report.include_evidence:
        from deepdub_qc.evidence.thumbnails import generate_thumbnails  # noqa: PLC0415

        progress.announce("Generating evidence")
        evidence, findings = generate_thumbnails(findings, input_path, output_dir)
    progress.finish_stage()

    summary = build_summary(findings)

    media_summary = _load_media_summary(raw_dir)
    duration = _container_duration(measurements)
    progress.announce(f"Hashing asset ({input_path.stat().st_size / 1_073_741_824:.2f} GB)")
    asset_sha256 = sha256_file(input_path)
    progress.finish_stage()
    completed_wall = datetime.now(UTC)

    result = QCResult(
        job=QCJob(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            started_at=started_wall,
            completed_at=completed_wall,
            duration_seconds=round(time.monotonic() - started, 3),
            tool_version=__version__,
        ),
        asset=Asset(
            input_path=str(input_path),
            filename=input_path.name,
            file_size_bytes=input_path.stat().st_size,
            sha256=asset_sha256,
            duration_seconds=duration,
        ),
        preset=PresetRef(
            preset_id=preset.preset.id,
            preset_version=preset.preset.version,
            client=preset.preset.client,
            content_type=preset.preset.content_type,
            sha256=preset_sha256(preset_path),
        ),
        environment=_environment(),
        summary=summary,
        media_summary=media_summary,
        measurements=measurements,
        findings=findings,
        evidence=evidence,
        artifacts=ArtifactPaths(
            html_report="report.html",
            pdf_report="report.pdf" if options.render_pdf else None,
            evidence_directory="evidence/" if evidence else None,
            raw_directory="raw/",
        ),
    )

    progress.announce("Rendering reports")
    write_json_report(result, output_dir)
    write_html_report(result, output_dir, generated_at=completed_wall)
    if options.render_pdf:
        from deepdub_qc.reports.pdf_renderer import write_pdf_report  # noqa: PLC0415

        write_pdf_report(result, output_dir, generated_at=completed_wall)

    logger.info(
        "job completed",
        extra={
            "job_id": str(job_id),
            "status": summary.overall_status.value,
            "duration": result.job.duration_seconds,
            "stage": "complete",
        },
    )
    return result


def _run_detectors(
    context: QCContext,
    progress: _ProgressReporter,
) -> tuple[list[Measurement], set[str], dict[str, str]]:
    """Run applicable detectors; failures become ERROR findings, never crashes."""
    measurements: list[Measurement] = []
    failed_parameters: set[str] = set()
    failure_reasons: dict[str, str] = {}
    detectors = [d for d in all_detectors() if d.is_applicable(context)]
    progress.plan(len(detectors))
    detector: Detector
    for index, detector in enumerate(detectors, start=1):
        progress.announce(f"[{index}/{len(detectors)}] Running {detector.detector_id}")
        started = time.monotonic()
        try:
            produced = detector.run(context)
        except DetectorRunError as exc:
            logger.error(
                "detector failed",
                extra={
                    "detector_id": detector.detector_id,
                    "job_id": str(context.job_id),
                    "error_type": type(exc).__name__,
                },
            )
            produced_ids = {m.parameter_id for m in measurements}
            for parameter in detector.parameters:
                if parameter not in produced_ids:
                    failed_parameters.add(parameter)
                    failure_reasons[parameter] = str(exc)
            progress.finish_stage(f"    {detector.detector_id} FAILED: {exc}")
            continue
        measurements.extend(produced)
        progress.finish_stage(
            f"    {detector.detector_id} done in {time.monotonic() - started:.1f}s "
            f"({len(produced)} measurements)"
        )
    return measurements, failed_parameters, failure_reasons


def _load_media_summary(raw_dir: Path) -> dict[str, JsonValue]:
    raw_file = raw_dir / RAW_FILENAME
    if not raw_file.is_file():
        return {}
    try:
        summary = build_media_summary(json.loads(raw_file.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}
    # build_media_summary emits only JSON-native values.
    return cast("dict[str, JsonValue]", summary)


def _container_duration(measurements: list[Measurement]) -> float | None:
    for m in measurements:
        if m.parameter_id == "container.duration" and isinstance(m.value, int | float):
            return float(m.value)
    return None


def _environment() -> Environment:
    return Environment(
        ffmpeg_version=_tool_version("ffmpeg"),
        ffprobe_version=_tool_version("ffprobe"),
        python_version=platform_module.python_version(),
        platform=f"{sys.platform}/{platform_module.machine()}",
        docker_image=None,
    )


def _tool_version(tool: str) -> str | None:
    try:
        result = run_tool([tool, "-version"], timeout=15.0)
    except ToolError:
        return None
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    # "ffprobe version 4.4.2-0ubuntu0.22.04.1 Copyright ..." -> "4.4.2-0ubuntu0.22.04.1"
    parts = first_line.split()
    return parts[2] if len(parts) > 2 else (first_line or None)
