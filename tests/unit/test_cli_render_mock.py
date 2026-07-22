"""render-mock CLI command."""

from pathlib import Path

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

    def test_writes_pdf_when_backend_available(self, tmp_path: Path) -> None:
        try:
            import weasyprint  # noqa: F401, PLC0415
        except (ImportError, OSError):
            import pytest  # noqa: PLC0415

            pytest.skip("WeasyPrint native libraries unavailable")
        result = runner.invoke(app, ["render-mock", "--output", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "report.pdf").is_file()
