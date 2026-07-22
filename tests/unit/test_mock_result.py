"""Mock QCResult: validity, determinism, and summary consistency."""

from deepdub_qc.models import QCStatus
from deepdub_qc.reports.mock_result import build_mock_result


class TestMockResult:
    def test_builds_and_is_deterministic(self) -> None:
        a = build_mock_result()
        b = build_mock_result()
        assert a == b
        assert a.model_dump_json() == b.model_dump_json()

    def test_summary_counts_match_findings(self) -> None:
        result = build_mock_result()
        by_status = {
            status: sum(1 for f in result.findings if f.status is status) for status in QCStatus
        }
        assert result.summary.total_checks == len(result.findings)
        assert result.summary.passed == by_status[QCStatus.PASS]
        assert result.summary.warnings == by_status[QCStatus.WARNING]
        assert result.summary.failed == by_status[QCStatus.FAIL]
        assert result.summary.errors == by_status[QCStatus.ERROR]
        assert result.summary.skipped == by_status[QCStatus.SKIPPED]
        assert result.summary.blocking_failures == sum(
            1 for f in result.findings if f.status is QCStatus.FAIL and f.blocking
        )

    def test_demonstrates_every_report_feature(self) -> None:
        """The mock must exercise the full report surface for stakeholder review."""
        result = build_mock_result()
        statuses = {f.status for f in result.findings}
        assert QCStatus.PASS in statuses
        assert QCStatus.WARNING in statuses
        assert QCStatus.FAIL in statuses
        assert QCStatus.SKIPPED in statuses
        assert result.summary.overall_status is QCStatus.FAIL
        assert any(f.start_seconds is not None for f in result.findings), "timestamped incident"
        assert any(f.stream_index is not None for f in result.findings), "per-stream finding"
        assert any(f.evidence_ids for f in result.findings), "evidence-linked finding"
        assert any(f.suggested_action for f in result.findings), "remediation"
        assert result.evidence, "evidence artifacts"
        assert result.media_summary.get("audio_streams"), "stream map"

    def test_finding_references_resolve(self) -> None:
        result = build_mock_result()
        measurement_ids = {m.measurement_id for m in result.measurements}
        evidence_ids = {e.evidence_id for e in result.evidence}
        for f in result.findings:
            assert set(f.measurement_ids) <= measurement_ids
            assert set(f.evidence_ids) <= evidence_ids
