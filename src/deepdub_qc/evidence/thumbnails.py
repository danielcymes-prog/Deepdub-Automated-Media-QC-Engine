"""Thumbnail evidence: a frame grab at each video incident timestamp.

Why: a reviewer deciding whether a black-frame failure blocks delivery wants
to see the frame, not just a timecode (handoff section 7.4). One thumbnail is
generated per failing video finding that carries a timestamp.

Evidence generation must never break a QC job: failures are logged and the
finding simply keeps an empty evidence list. Evidence never influences
findings (ADR-001: it supports review, it does not decide).
"""

from __future__ import annotations

import logging
from pathlib import Path

from deepdub_qc.models.enums import Category, EvidenceType, QCStatus
from deepdub_qc.models.evidence import Evidence
from deepdub_qc.models.finding import Finding
from deepdub_qc.utils import ids
from deepdub_qc.utils.hashing import sha256_file
from deepdub_qc.utils.subprocess import ToolError, run_tool

logger = logging.getLogger(__name__)

GENERATOR_ID = "evidence.thumbnails/1.0.0"
THUMBNAIL_DIR = "evidence/thumbnails"
_GRAB_TIMEOUT = 120.0
_FAILING = (QCStatus.FAIL, QCStatus.WARNING, QCStatus.ERROR)


def generate_thumbnails(
    findings: list[Finding],
    input_path: Path,
    output_dir: Path,
) -> tuple[list[Evidence], list[Finding]]:
    """Grab one frame per failing, timestamped video finding.

    Returns the evidence records and the findings updated with evidence_ids.
    Pure with respect to canonical results: findings' statuses, values, and
    messages are never altered - only their evidence links.
    """
    evidence: list[Evidence] = []
    updated: list[Finding] = []
    thumb_dir = output_dir / THUMBNAIL_DIR

    for finding in findings:
        eligible = (
            finding.status in _FAILING
            and finding.category is Category.VIDEO
            and finding.start_seconds is not None
        )
        if not eligible:
            updated.append(finding)
            continue

        assert finding.start_seconds is not None
        record = _grab(finding, input_path, thumb_dir, output_dir)
        if record is None:
            updated.append(finding)
            continue
        evidence.append(record)
        updated.append(finding.model_copy(update={"evidence_ids": [record.evidence_id]}))

    return evidence, updated


def _grab(finding: Finding, input_path: Path, thumb_dir: Path, output_dir: Path) -> Evidence | None:
    start = finding.start_seconds or 0.0
    filename = f"{finding.rule_id}_{round(start * 1000):08d}.png"
    target = thumb_dir / filename
    thumb_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-map",
        "0:v:0",
        str(target),
    ]
    try:
        run_tool(args, timeout=_GRAB_TIMEOUT)
    except ToolError as exc:
        logger.warning(
            "thumbnail generation failed",
            extra={"rule_id": finding.rule_id, "start_seconds": start, "error": str(exc)},
        )
        return None
    if not target.is_file() or target.stat().st_size == 0:
        return None

    return Evidence(
        evidence_id=ids.deterministic_id("evidence", "thumbnail", finding.rule_id, start),
        finding_id=finding.finding_id,
        type=EvidenceType.THUMBNAIL,
        path=str(target.relative_to(output_dir)),
        start_seconds=start,
        end_seconds=finding.end_seconds,
        generated_by=GENERATOR_ID,
        sha256=sha256_file(target),
    )
