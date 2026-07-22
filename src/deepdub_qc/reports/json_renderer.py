"""Canonical JSON report serialization (ADR-002).

`report.json` is the source of truth. This module defines its exact byte
layout: UTF-8, two-space indent, sorted keys, trailing newline. Golden-file
tests depend on this contract; changing it is a schema-relevant event.
"""

from __future__ import annotations

import json
from pathlib import Path

from deepdub_qc.models.report import QCResult

REPORT_JSON_FILENAME = "report.json"


def render_json(result: QCResult) -> str:
    """Serialize a QCResult to its canonical JSON text form."""
    payload = result.model_dump(mode="json", exclude_none=False)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json_report(result: QCResult, output_dir: Path) -> Path:
    """Write report.json into the job output directory and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / REPORT_JSON_FILENAME
    target.write_text(render_json(result), encoding="utf-8")
    return target
