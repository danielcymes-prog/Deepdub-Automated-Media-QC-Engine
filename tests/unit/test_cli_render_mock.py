"""render-mock CLI command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from deepdub_qc.cli import app

runner = CliRunner()


class TestRenderMock:
    def test_writes_json_and_html(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["render-mock", "--output", str(tmp_path), "--no-pdf"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "report.json").is_file()
        assert (tmp_path / "report.html").is_file()
        assert not (tmp_path / "report.pdf").exists()
        assert "FAIL" in result.output  # overall status surfaced to the operator

    @pytest.mark.usefixtures("weasyprint_native")
    def test_writes_pdf_when_backend_available(self, tmp_path: Path) -> None:
        """Uses the shared `weasyprint_native` fixture (tests/conftest.py).

        The previous local guard only caught a failing *import*, which happens to
        be how macOS fails but is not how a partially-installed native stack
        fails — there the module imports and rendering raises. More importantly,
        a local `pytest.skip` cannot honour `DEEPDUB_QC_REQUIRE_TOOLCHAIN`, so the
        CI verification job would have skipped PDF CLI coverage while reporting
        green. That is the drift the conftest comment warns about.
        """
        result = runner.invoke(app, ["render-mock", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "report.pdf").is_file()
