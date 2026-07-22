"""Schema drift contract (ADR-004): committed schemas must match the models."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_schemas import EXPORTS, SCHEMA_DIR, render  # noqa: E402


class TestSchemaDrift:
    def test_all_schemas_committed_and_current(self) -> None:
        for filename, model in EXPORTS.items():
            target = SCHEMA_DIR / filename
            assert target.is_file(), f"missing schema file: {filename} (run `make schemas`)"
            assert target.read_text(encoding="utf-8") == render(model), (
                f"schema drift in {filename}: run `make schemas` and commit the result"
            )

    def test_schema_export_is_deterministic(self) -> None:
        for model in EXPORTS.values():
            assert render(model) == render(model)
