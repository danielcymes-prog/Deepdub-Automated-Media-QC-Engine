"""Export JSON Schemas from the Pydantic domain models (ADR-004).

The Pydantic models are the canonical schema source; the files in schemas/
are generated artifacts for non-Python consumers (Composer, tooling).
CI runs this with --check and fails if the committed schemas have drifted.

Usage:
    python scripts/export_schemas.py          # write schemas/
    python scripts/export_schemas.py --check  # exit 1 on drift, write nothing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from deepdub_qc.models import Measurement, QCJob, QCPreset, QCResult
from deepdub_qc.models.finding import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"

EXPORTS: dict[str, type[BaseModel]] = {
    "qc-preset.schema.json": QCPreset,
    "qc-measurement.schema.json": Measurement,
    "qc-finding.schema.json": Finding,
    "qc-job.schema.json": QCJob,
    "qc-result.schema.json": QCResult,
}


def render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    drifted: list[str] = []

    for filename, model in EXPORTS.items():
        target = SCHEMA_DIR / filename
        content = render(model)
        if check:
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                drifted.append(filename)
        else:
            SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if check and drifted:
        print(
            "schema drift detected (run `make schemas` and commit): " + ", ".join(drifted),
            file=sys.stderr,
        )
        return 1
    if check:
        print("schemas up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
