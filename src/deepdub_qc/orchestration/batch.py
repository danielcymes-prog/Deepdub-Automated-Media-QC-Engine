"""Batch analysis: run one preset over every media file in a directory.

Why: the operator workflow is a season at a time, not a file at a time.
Batch mode wraps ``run_analysis`` per file - one job directory and canonical
report.json each - and records a machine-readable batch summary. A failure
on one file never stops the batch; it is recorded as an ERROR item.

Inputs: an input directory, one preset, an output root directory.
Outputs: ``BatchItemResult`` per file plus ``batch_summary.json``.
Side effects: creates one job directory per file under the output root.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from deepdub_qc.exceptions import DeepdubQCError, PresetError
from deepdub_qc.orchestration.pipeline import AnalysisOptions, run_analysis

logger = logging.getLogger(__name__)

#: Default extensions considered media inputs (lowercase, with dot).
MEDIA_EXTENSIONS = frozenset(
    {".mov", ".mxf", ".mp4", ".mkv", ".wav", ".m4a", ".aif", ".aiff", ".flac"}
)

SUMMARY_FILENAME = "batch_summary.json"

#: Severity ordering for the batch verdict (worst wins).
_STATUS_RANK = {"PASS": 0, "WARNING": 1, "FAIL": 2, "ERROR": 3}


class EmptyBatchError(DeepdubQCError):
    """No media files matched in the input directory."""


@dataclass(frozen=True)
class BatchItemResult:
    """Outcome of one file in the batch."""

    filename: str
    output_dir: Path
    status: str  # PASS | WARNING | FAIL | ERROR
    passed: int = 0
    warnings: int = 0
    failed: int = 0
    errors: int = 0
    duration_seconds: float | None = None
    error_message: str | None = None


def discover_media(input_dir: Path, extensions: frozenset[str] = MEDIA_EXTENSIONS) -> list[Path]:
    """Media files directly inside ``input_dir``, sorted by name (deterministic)."""
    return sorted(
        (p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in extensions),
        key=lambda p: p.name,
    )


def batch_status(items: list[BatchItemResult]) -> str:
    """Worst individual status; the batch verdict."""
    return max((item.status for item in items), key=lambda s: _STATUS_RANK.get(s, 3))


def write_batch_summary(output_root: Path, items: list[BatchItemResult]) -> Path:
    """Write the machine-readable batch summary (canonical formatting)."""
    payload = {
        "batch_status": batch_status(items),
        "items": [
            {
                "duration_seconds": item.duration_seconds,
                "error_message": item.error_message,
                "errors": item.errors,
                "failed": item.failed,
                "filename": item.filename,
                "passed": item.passed,
                "report": str(item.output_dir / "report.json") if not item.error_message else None,
                "status": item.status,
                "warnings": item.warnings,
            }
            for item in items
        ],
        "total": len(items),
    }
    target = output_root / SUMMARY_FILENAME
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def run_batch(
    input_dir: Path,
    preset_path: Path,
    output_root: Path,
    options: AnalysisOptions | None = None,
    extensions: frozenset[str] = MEDIA_EXTENSIONS,
) -> list[BatchItemResult]:
    """Analyze every media file in ``input_dir`` against one preset.

    Per-file failures are recorded as ERROR items; preset errors abort the
    batch immediately (they would fail every file identically).

    Raises:
        EmptyBatchError: no media files found.
        PresetError: the preset is invalid.
    """
    if not input_dir.is_dir():
        raise EmptyBatchError(f"Input directory not found: {input_dir}")
    files = discover_media(input_dir, extensions)
    if not files:
        raise EmptyBatchError(
            f"No media files ({', '.join(sorted(extensions))}) found in {input_dir}"
        )

    options = options or AnalysisOptions()
    output_root.mkdir(parents=True, exist_ok=True)
    items: list[BatchItemResult] = []
    for index, media in enumerate(files, start=1):
        job_dir = output_root / media.name
        if options.on_progress is not None:
            options.on_progress(f"[{index}/{len(files)}] {media.name}")
        try:
            result = run_analysis(media, preset_path, job_dir, options)
        except PresetError:
            raise  # invalid preset fails every file; abort with exit code 4
        except DeepdubQCError as exc:
            logger.error("batch item failed", extra={"file": media.name, "error": str(exc)})
            items.append(
                BatchItemResult(
                    filename=media.name,
                    output_dir=job_dir,
                    status="ERROR",
                    error_message=str(exc),
                )
            )
            continue
        summary = result.summary
        items.append(
            BatchItemResult(
                filename=media.name,
                output_dir=job_dir,
                status=summary.overall_status.value,
                passed=summary.passed,
                warnings=summary.warnings,
                failed=summary.failed,
                errors=summary.errors,
                duration_seconds=result.job.duration_seconds,
            )
        )
    write_batch_summary(output_root, items)
    return items
