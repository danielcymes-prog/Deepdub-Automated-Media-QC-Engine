"""Report contract tests (ADR-002): JSON is canonical; HTML renders it faithfully."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deepdub_qc.models import QCResult
from deepdub_qc.reports.html_renderer import render_html, write_html_report
from deepdub_qc.reports.json_renderer import render_json, write_json_report
from deepdub_qc.reports.mock_result import build_mock_result

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_REPORT = REPO_ROOT / "tests" / "golden" / "mock_report.json"
FIXED_TIMESTAMP = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


class TestJsonRenderer:
    def test_canonical_json_round_trips(self) -> None:
        result = build_mock_result()
        text = render_json(result)
        assert QCResult.model_validate_json(text) == result

    def test_canonical_json_is_stable(self) -> None:
        result = build_mock_result()
        assert render_json(result) == render_json(result)
        assert render_json(result).endswith("\n")

    def test_write_json_report(self, tmp_path: Path) -> None:
        target = write_json_report(build_mock_result(), tmp_path)
        assert target.name == "report.json"
        assert json.loads(target.read_text(encoding="utf-8"))["schema_version"]

    def test_golden_file(self) -> None:
        """The canonical mock report is a committed golden file.

        If this fails after an intentional model/mock change, regenerate via:
        uv run deepdub-qc render-mock -o /tmp/mock --no-pdf
        and copy report.json over tests/golden/mock_report.json.
        """
        assert GOLDEN_REPORT.is_file(), f"missing golden file: {GOLDEN_REPORT}"
        assert render_json(build_mock_result()) == GOLDEN_REPORT.read_text(encoding="utf-8")


class TestHtmlContract:
    """Everything a reviewer needs must be present in the HTML rendering."""

    @pytest.fixture(scope="class")
    @staticmethod
    def html() -> str:
        return render_html(build_mock_result(), generated_at=FIXED_TIMESTAMP)

    def test_deterministic_given_fixed_timestamp(self) -> None:
        result = build_mock_result()
        assert render_html(result, FIXED_TIMESTAMP) == render_html(result, FIXED_TIMESTAMP)

    def test_no_javascript(self, html: str) -> None:
        assert "<script" not in html.lower()

    def test_overall_status_and_counts(self, html: str) -> None:
        assert "Overall status: FAIL" in html
        assert "2 blocking failure(s)" in html

    def test_every_finding_is_rendered(self, html: str) -> None:
        for finding in build_mock_result().findings:
            assert finding.display_name in html, finding.rule_id
            assert finding.rule_id in html

    def test_expected_and_actual_values_shown(self, html: str) -> None:
        assert "-24.0 to -22.0 LUFS" in html  # expected range
        assert "-19.7 LUFS" in html  # actual value

    def test_timecodes_and_stream_indices_shown(self, html: str) -> None:
        assert "00:04:12:00" in html
        assert "stream 1" in html

    def test_identity_and_versions_shown(self, html: str) -> None:
        result = build_mock_result()
        assert result.asset.sha256 in html
        assert result.preset.sha256 in html
        assert f"v{result.preset.preset_version}" in html
        assert f"deepdub-qc {result.job.tool_version}" in html
        assert str(result.job.job_id) in html
        assert "2026-07-22 12:00:00 UTC" in html  # generation timestamp

    def test_evidence_and_remediation_shown(self, html: str) -> None:
        assert "evidence/thumbnails/black_00-04-12.png" in html
        assert "Normalize the final mix" in html

    def test_blocking_flag_visible(self, html: str) -> None:
        assert "blocking" in html

    def test_write_html_report(self, tmp_path: Path) -> None:
        target = write_html_report(build_mock_result(), tmp_path, FIXED_TIMESTAMP)
        assert target.name == "report.html"
        assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


class TestPdfRenderer:
    def test_pdf_renders_from_same_model(self, tmp_path: Path) -> None:
        weasyprint = pytest.importorskip("weasyprint")
        assert weasyprint is not None
        from deepdub_qc.reports.pdf_renderer import write_pdf_report  # noqa: PLC0415

        target = write_pdf_report(build_mock_result(), tmp_path, FIXED_TIMESTAMP)
        data = target.read_bytes()
        assert data.startswith(b"%PDF-")
        assert len(data) > 10_000  # a real multi-section document, not a stub
