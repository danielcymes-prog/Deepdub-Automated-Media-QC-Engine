"""Rule engine: selection, quantifiers, SKIPPED/ERROR semantics, aggregation."""

from uuid import UUID

from deepdub_qc.models.enums import Category, QCStatus, Severity
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.models.preset import QCPreset
from deepdub_qc.rules.engine import aggregate_status, build_summary, evaluate
from deepdub_qc.utils import ids

JOB_ID = UUID("00000000-0000-4000-8000-00000000abcd")


def measurement(parameter_id: str, value: object, stream_index: int | None = None) -> Measurement:
    return Measurement(
        measurement_id=ids.measurement_id(
            "test.detector", "1.0.0", parameter_id, stream_index, None, None, value
        ),
        job_id=JOB_ID,
        detector_id="test.detector",
        detector_version="1.0.0",
        parameter_id=parameter_id,
        category=Category.AUDIO,
        value=value,  # type: ignore[arg-type]
        stream_index=stream_index,
    )


def preset(rules: list[dict[str, object]]) -> QCPreset:
    return QCPreset.model_validate(
        {
            "schema_version": "1.0.0",
            "preset": {
                "id": "test",
                "version": "1.0.0",
                "client": "generic",
                "content_type": "test",
                "title": "Test",
                "owner": "qa",
                "status": "draft",
                "effective_date": "2026-07-22",
            },
            "rules": rules,
        }
    )


class TestBasicEvaluation:
    def test_pass_and_fail(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "width",
                    "parameter_id": "video.width",
                    "operator": "equals",
                    "expected": {"value": 1920},
                },
                {
                    "rule_id": "height",
                    "parameter_id": "video.height",
                    "operator": "equals",
                    "expected": {"value": 1080},
                },
            ]
        )
        findings = evaluate(
            p,
            [measurement("video.width", 1920, 0), measurement("video.height", 720, 0)],
            JOB_ID,
        )
        by_id = {f.rule_id: f for f in findings}
        assert by_id["width"].status is QCStatus.PASS
        assert by_id["height"].status is QCStatus.FAIL
        assert by_id["height"].actual is not None
        assert by_id["height"].actual.value == 720
        assert by_id["height"].measurement_ids

    def test_findings_preserve_preset_rule_order(self) -> None:
        rules = [
            {
                "rule_id": f"r{i}",
                "parameter_id": "video.width",
                "operator": "equals",
                "expected": {"value": 1920},
            }
            for i in range(5)
        ]
        findings = evaluate(preset(rules), [measurement("video.width", 1920, 0)], JOB_ID)
        assert [f.rule_id for f in findings] == [f"r{i}" for i in range(5)]

    def test_warning_severity_fails_as_warning(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "name",
                    "parameter_id": "filename.pattern",
                    "operator": "regex",
                    "expected": {"pattern": r"^\S+$"},
                    "severity": "warning",
                    "blocking": False,
                }
            ]
        )
        findings = evaluate(p, [measurement("filename.pattern", "has space.mov")], JOB_ID)
        assert findings[0].status is QCStatus.WARNING

    def test_deterministic_finding_ids(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "width",
                    "parameter_id": "video.width",
                    "operator": "equals",
                    "expected": {"value": 1920},
                }
            ]
        )
        ms = [measurement("video.width", 1920, 0)]
        assert evaluate(p, ms, JOB_ID)[0].finding_id == evaluate(p, ms, JOB_ID)[0].finding_id


class TestMissingAndFailed:
    def test_missing_measurement_is_skipped(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "loudness",
                    "parameter_id": "audio.integrated_loudness",
                    "operator": "between",
                    "expected": {"min": -24.0, "max": -22.0},
                }
            ]
        )
        findings = evaluate(p, [], JOB_ID)
        assert findings[0].status is QCStatus.SKIPPED

    def test_failed_detector_yields_error(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "loudness",
                    "parameter_id": "audio.integrated_loudness",
                    "operator": "between",
                    "expected": {"min": -24.0, "max": -22.0},
                }
            ]
        )
        findings = evaluate(
            p,
            [],
            JOB_ID,
            failed_parameters=frozenset({"audio.integrated_loudness"}),
            failure_reasons={"audio.integrated_loudness": "ffmpeg crashed"},
        )
        assert findings[0].status is QCStatus.ERROR
        assert "ffmpeg crashed" in findings[0].message

    def test_disabled_rule_is_not_applicable(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "width",
                    "parameter_id": "video.width",
                    "operator": "equals",
                    "expected": {"value": 1920},
                    "enabled": False,
                }
            ]
        )
        findings = evaluate(p, [measurement("video.width", 1280, 0)], JOB_ID)
        assert findings[0].status is QCStatus.NOT_APPLICABLE

    def test_type_mismatch_yields_error_not_crash(self) -> None:
        p = preset(
            [
                {
                    "rule_id": "duration",
                    "parameter_id": "container.duration",
                    "operator": "greater_than",
                    "expected": {"value": 1.0},
                }
            ]
        )
        findings = evaluate(p, [measurement("container.duration", "n/a")], JOB_ID)
        assert findings[0].status is QCStatus.ERROR


class TestStreamSelection:
    def make_preset(self, quantifier: str, **selector: object) -> QCPreset:
        applies: dict[str, object] = {"stream_type": "audio", "quantifier": quantifier}
        if selector:
            applies["selector"] = selector
        return preset(
            [
                {
                    "rule_id": "sample-rate",
                    "parameter_id": "audio.sample_rate",
                    "operator": "equals",
                    "expected": {"value": 48000},
                    "applies_to": applies,
                }
            ]
        )

    def multi_stream(self) -> list[Measurement]:
        return [
            measurement("audio.sample_rate", 48000, 1),
            measurement("audio.sample_rate", 44100, 2),
            measurement("audio.language", "deu", 1),
            measurement("audio.language", "eng", 2),
        ]

    def test_quantifier_all_fails_on_offender(self) -> None:
        findings = evaluate(self.make_preset("all"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.FAIL
        assert findings[0].stream_index == 2  # the offending stream
        assert "1/2 streams conform" in findings[0].message

    def test_quantifier_any_passes(self) -> None:
        findings = evaluate(self.make_preset("any"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.PASS

    def test_quantifier_exactly_one(self) -> None:
        findings = evaluate(self.make_preset("exactly_one"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.PASS

    def test_index_selector(self) -> None:
        findings = evaluate(self.make_preset("all", index=2), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.FAIL

    def test_language_selector(self) -> None:
        findings = evaluate(self.make_preset("all", language="deu"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.PASS
        findings = evaluate(self.make_preset("all", language="eng"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.FAIL

    def test_language_selector_no_match_skips(self) -> None:
        findings = evaluate(self.make_preset("all", language="jpn"), self.multi_stream(), JOB_ID)
        assert findings[0].status is QCStatus.SKIPPED


class TestAggregation:
    def make_findings(self, *specs: tuple[str, bool]) -> list:
        rules = [
            {
                "rule_id": f"r{i}",
                "parameter_id": "video.width",
                "operator": "equals",
                "expected": {"value": 1920},
                "blocking": blocking,
                "severity": "error" if status != "WARNING" else "warning",
            }
            for i, (status, blocking) in enumerate(specs)
        ]
        # Build findings directly through evaluation where possible is complex;
        # aggregate_status only reads (status, blocking), so patch findings.
        p = preset(rules)
        findings = evaluate(p, [measurement("video.width", 1920, 0)], JOB_ID)
        patched = []
        for f, (status, _) in zip(findings, specs, strict=True):
            patched.append(f.model_copy(update={"status": QCStatus(status)}))
        return patched

    def test_all_pass(self) -> None:
        findings = self.make_findings(("PASS", True), ("PASS", False))
        assert aggregate_status(findings) is QCStatus.PASS

    def test_blocking_fail_wins(self) -> None:
        findings = self.make_findings(("PASS", True), ("FAIL", True), ("WARNING", False))
        assert aggregate_status(findings) is QCStatus.FAIL

    def test_non_blocking_fail_is_warning(self) -> None:
        findings = self.make_findings(("PASS", True), ("FAIL", False))
        assert aggregate_status(findings) is QCStatus.WARNING

    def test_blocking_skipped_escalates_to_error(self) -> None:
        findings = self.make_findings(("PASS", True), ("SKIPPED", True))
        assert aggregate_status(findings) is QCStatus.ERROR

    def test_non_blocking_skipped_does_not_escalate(self) -> None:
        findings = self.make_findings(("PASS", True), ("SKIPPED", False))
        assert aggregate_status(findings) is QCStatus.PASS

    def test_blocking_error_escalates(self) -> None:
        findings = self.make_findings(("ERROR", True), ("FAIL", True))
        assert aggregate_status(findings) is QCStatus.ERROR

    def test_summary_counts(self) -> None:
        findings = self.make_findings(
            ("PASS", True), ("FAIL", True), ("FAIL", False), ("WARNING", False), ("SKIPPED", False)
        )
        summary = build_summary(findings)
        assert summary.total_checks == 5
        assert summary.passed == 1
        assert summary.failed == 2
        assert summary.blocking_failures == 1
        assert summary.warnings == 1
        assert summary.skipped == 1
        assert summary.overall_status is QCStatus.FAIL


class TestSeverityDefaults:
    def test_severity_and_blocking_inherited_from_preset_defaults(self) -> None:
        p = QCPreset.model_validate(
            {
                "schema_version": "1.0.0",
                "preset": {
                    "id": "test",
                    "version": "1.0.0",
                    "client": "generic",
                    "content_type": "test",
                    "title": "Test",
                    "owner": "qa",
                    "status": "draft",
                    "effective_date": "2026-07-22",
                },
                "defaults": {"blocking": False, "severity": "warning"},
                "rules": [
                    {
                        "rule_id": "width",
                        "parameter_id": "video.width",
                        "operator": "equals",
                        "expected": {"value": 1920},
                    }
                ],
            }
        )
        findings = evaluate(p, [measurement("video.width", 1280, 0)], JOB_ID)
        assert findings[0].severity is Severity.WARNING
        assert findings[0].blocking is False
        assert findings[0].status is QCStatus.WARNING
