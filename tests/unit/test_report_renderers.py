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
        assert "FAIL" in html
        assert "1 blocking failure(s)" in html

    def test_every_finding_is_rendered(self, html: str) -> None:
        for finding in build_mock_result().findings:
            assert finding.display_name in html, finding.rule_id

    def test_target_and_measured_values_shown(self, html: str) -> None:
        assert "Target Value" in html  # stakeholder-requested phrasing
        assert "-24.0 to -22.0 LUFS" in html  # target range
        assert "-19.7 LUFS" in html  # measured value

    def test_timecodes_and_channel_mapping_shown(self, html: str) -> None:
        assert "00:04:12:00" in html  # incident TC
        assert "00:24:12:04" in html  # asset duration as HH:MM:SS:FF @ 23.976
        assert "stereo · DEU" in html  # channel mapping instead of stream index

    def test_identity_and_versions_shown(self, html: str) -> None:
        result = build_mock_result()
        assert result.asset.sha256 in html
        assert result.preset.sha256[:16] in html
        assert f"v{result.preset.preset_version}" in html
        assert f"deepdub-qc {result.job.tool_version}" in html
        assert str(result.job.job_id) in html
        assert "22 Jul 2026" in html  # prominent date
        assert "12:00 UTC" in html

    def test_branding_present(self, html: str) -> None:
        assert "<title>Deepdub</title>" in html  # embedded wordmark SVG
        assert "#0A0A0A" in html  # brand canvas
        assert "Onest" in html  # brand typeface

    def test_stakeholder_removals(self, html: str) -> None:
        """Per post-production review: no file path, no remediation section."""
        result = build_mock_result()
        assert result.asset.input_path not in html
        assert "Normalize the final mix" not in html  # stays in JSON only
        assert "Suggested Remediation" not in html
        assert "Media Technical Summary" not in html

    def test_evidence_shown(self, html: str) -> None:
        assert "evidence/thumbnails/black_00-04-12.png" in html

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
