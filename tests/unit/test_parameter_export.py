"""Parameter catalogue drift contract (ADR-021, ADR-004 pattern).

The committed catalogue artifacts must match the models. Mirrors
`test_schema_export.py`: CI also runs `export_parameters.py --check`, but a
contributor running `pytest` locally should see the drift too.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from export_parameters import (  # noqa: E402
    JSON_TARGET,
    MARKDOWN_TARGET,
    render_json,
    render_markdown,
)


class TestParameterCatalogueDrift:
    def test_markdown_committed_and_current(self) -> None:
        assert MARKDOWN_TARGET.is_file(), "missing docs/parameter-catalogue.md (run `make params`)"
        assert MARKDOWN_TARGET.read_text(encoding="utf-8") == render_markdown(), (
            "parameter catalogue drift: run `make params` and commit the result"
        )

    def test_json_registry_committed_and_current(self) -> None:
        assert JSON_TARGET.is_file(), "missing schemas/parameter-catalogue.json (run `make params`)"
        assert JSON_TARGET.read_text(encoding="utf-8") == render_json(), (
            "parameter registry drift: run `make params` and commit the result"
        )

    def test_export_is_deterministic(self) -> None:
        assert render_markdown() == render_markdown()
        assert render_json() == render_json()

    def test_every_catalogued_parameter_appears_in_the_document(self) -> None:
        """Guards a rendering bug silently dropping a whole category."""
        from deepdub_qc.models.parameters import CATALOGUE  # noqa: PLC0415

        rendered = render_markdown()
        for parameter_id in CATALOGUE:
            assert f"`{parameter_id}`" in rendered, f"{parameter_id} missing from the document"
