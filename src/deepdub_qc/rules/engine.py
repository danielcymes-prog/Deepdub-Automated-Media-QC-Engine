"""Rule engine: deterministic evaluation of measurements against a preset.

Semantics (DATA_MODEL_REVIEW item 7):
- NOT_APPLICABLE: rule disabled.
- SKIPPED: required measurement unavailable though expected.
- ERROR: the detector owning the parameter failed for this job.
- Aggregation: a blocking rule that is ERROR or SKIPPED escalates the job to
  ERROR - the tool must never pass a file it failed to inspect.

Findings are pure functions of (measurements, rule): deterministic IDs,
deterministic message templates, preset rule order preserved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from deepdub_qc.models.enums import Category, Operator, QCStatus, Quantifier, Severity
from deepdub_qc.models.finding import ActualValue, Finding
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.models.report import Summary
from deepdub_qc.models.rule import ExpectedNothing, Rule
from deepdub_qc.rules.evaluators import EvaluationError, evaluate_operator
from deepdub_qc.utils import ids
from deepdub_qc.utils.language import normalize_language

if TYPE_CHECKING:
    from deepdub_qc.models.preset import QCPreset

_PARAMETER_CATEGORY: dict[str, Category] = {
    "file": Category.FILE,
    "filename": Category.FILE,
    "container": Category.CONTAINER,
    "video": Category.VIDEO,
    "audio": Category.AUDIO,
    "subtitle": Category.SUBTITLE,
    "metadata": Category.METADATA,
    "deepdub": Category.DEEPDUB,
}


def evaluate(
    preset: QCPreset,
    measurements: list[Measurement],
    job_id: UUID,
    failed_parameters: frozenset[str] = frozenset(),
    failure_reasons: dict[str, str] | None = None,
) -> list[Finding]:
    """Evaluate every enabled preset rule against the measurement set.

    Args:
        preset: the resolved client preset (defaults already applied).
        measurements: all measurements produced for the job.
        job_id: the job the findings belong to.
        failed_parameters: parameter IDs owned by detectors that crashed;
            rules over them yield ERROR findings.
        failure_reasons: optional parameter_id -> human-readable failure cause.
    """
    by_parameter: dict[str, list[Measurement]] = {}
    for m in sorted(measurements, key=_measurement_sort_key):
        by_parameter.setdefault(m.parameter_id, []).append(m)

    findings = []
    for rule in preset.rules:
        findings.append(
            _evaluate_rule(rule, by_parameter, job_id, failed_parameters, failure_reasons or {})
        )
    return findings


def _measurement_sort_key(m: Measurement) -> tuple[str, int]:
    return (m.parameter_id, m.stream_index if m.stream_index is not None else -1)


def _display_name(rule: Rule) -> str:
    if rule.display_name:
        return rule.display_name
    tail = rule.parameter_id.split(".")[-1]
    return tail.replace("_", " ").title()


def _category(rule: Rule) -> Category:
    prefix = rule.parameter_id.split(".")[0]
    return _PARAMETER_CATEGORY.get(prefix, Category.METADATA)


def _select(rule: Rule, candidates: list[Measurement]) -> list[Measurement]:
    """Apply the rule's stream selector (ADR-009)."""
    applies = rule.applies_to
    if applies is None:
        return candidates
    selected = candidates
    if applies.selector.index is not None:
        selected = [m for m in selected if m.stream_index == applies.selector.index]
    # Language-based selection resolves through <stream_type>.language measurements.
    elif applies.selector.language is not None:
        return selected  # resolved by caller via language map; kept for M4+ streams
    return selected


def _resolve_language_indices(
    rule: Rule, by_parameter: dict[str, list[Measurement]]
) -> set[int] | None:
    applies = rule.applies_to
    if applies is None or applies.selector.language is None:
        return None
    language_parameter = f"{applies.stream_type.value}.language"
    # Both sides normalized (backlog #33): presets may say "ger", "deu" or
    # "de"; measurements are already canonical, tolerate legacy reports.
    wanted = normalize_language(applies.selector.language)
    return {
        m.stream_index
        for m in by_parameter.get(language_parameter, [])
        if isinstance(m.value, str)
        and normalize_language(m.value) == wanted
        and m.stream_index is not None
    }


def _evaluate_rule(
    rule: Rule,
    by_parameter: dict[str, list[Measurement]],
    job_id: UUID,
    failed_parameters: frozenset[str],
    failure_reasons: dict[str, str],
) -> Finding:
    display = _display_name(rule)
    severity = rule.severity if rule.severity is not None else Severity.ERROR
    blocking = rule.blocking if rule.blocking is not None else True

    def make(  # noqa: PLR0913 - internal factory mirroring Finding fields
        status: QCStatus,
        message: str,
        actual: ActualValue | None = None,
        stream_index: int | None = None,
        measurement_ids: list[UUID] | None = None,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> Finding:
        return Finding(
            finding_id=ids.finding_id(
                rule.rule_id,
                rule.rule_version,
                rule.parameter_id,
                stream_index,
                start_seconds,
                status.value,
            ),
            job_id=job_id,
            rule_id=rule.rule_id,
            parameter_id=rule.parameter_id,
            category=_category(rule),
            display_name=display,
            status=status,
            severity=severity,
            expected=None if isinstance(rule.expected, ExpectedNothing) else rule.expected,
            actual=actual,
            message=message,
            stream_index=stream_index,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            measurement_ids=measurement_ids or [],
            suggested_action=rule.suggested_action,
            blocking=blocking,
            rule_version=rule.rule_version,
        )

    if not rule.enabled:
        return make(QCStatus.NOT_APPLICABLE, f"{display}: rule is disabled in the preset.")

    if rule.parameter_id in failed_parameters:
        reason = failure_reasons.get(rule.parameter_id, "detector execution failed")
        return make(QCStatus.ERROR, f"{display}: {reason}")

    candidates = by_parameter.get(rule.parameter_id, [])
    language_indices = _resolve_language_indices(rule, by_parameter)
    if language_indices is not None:
        candidates = [m for m in candidates if m.stream_index in language_indices]
    else:
        candidates = _select(rule, candidates)

    # exists/not_exists operate on measurement presence, not values.
    if rule.operator in (Operator.EXISTS, Operator.NOT_EXISTS):
        present = len(candidates) > 0
        passed = present if rule.operator is Operator.EXISTS else not present
        verb = "present" if present else "absent"
        # A failing not_exists over event measurements is a timestamped
        # incident: surface the first offending event's span and stream.
        offender = candidates[0] if (present and not passed) else None
        return make(
            QCStatus.PASS if passed else _fail_status(severity),
            f"{display}: measurement for {rule.parameter_id} is {verb}"
            + (f" ({len(candidates)} event(s))." if present else "."),
            actual=(ActualValue(value=offender.value, unit=offender.unit) if offender else None),
            stream_index=offender.stream_index if offender else None,
            start_seconds=offender.start_seconds if offender else None,
            end_seconds=offender.end_seconds if offender else None,
            measurement_ids=[m.measurement_id for m in candidates],
        )

    if not candidates:
        return make(
            QCStatus.SKIPPED,
            f"{display}: no measurement available for {rule.parameter_id}.",
        )

    quantifier = rule.applies_to.quantifier if rule.applies_to else Quantifier.ALL
    results: list[tuple[Measurement, bool]] = []
    try:
        for m in candidates:
            results.append((m, evaluate_operator(rule.operator, m.value, rule.expected)))
    except EvaluationError as exc:
        return make(
            QCStatus.ERROR,
            f"{display}: cannot evaluate measured value: {exc}",
            measurement_ids=[m.measurement_id for m in candidates],
        )

    passed, pass_count = _apply_quantifier(quantifier, results)

    exemplar = _exemplar(results, passed)
    actual = ActualValue(value=exemplar.value, unit=exemplar.unit)
    stream_index = (
        exemplar.stream_index
        if len(candidates) == 1
        else (exemplar.stream_index if not passed else None)
    )
    target = _describe_expected(rule)
    status = QCStatus.PASS if passed else _fail_status(severity)
    if passed:
        message = f"{display}: measured {_fmt(actual)}, target {target}."
    else:
        message = f"{display}: measured {_fmt(actual)}, target {target}."
        if len(results) > 1:
            message += (
                f" ({pass_count}/{len(results)} streams conform, {quantifier.value} required.)"
            )
    return make(
        status,
        message,
        actual=actual,
        stream_index=stream_index,
        # Timestamped measurements (silence spans, events) propagate their
        # span to failing findings so reports can show incident timecodes.
        start_seconds=exemplar.start_seconds if not passed else None,
        end_seconds=exemplar.end_seconds if not passed else None,
        measurement_ids=[m.measurement_id for m, _ in results],
    )


def _apply_quantifier(
    quantifier: Quantifier, results: list[tuple[Measurement, bool]]
) -> tuple[bool, int]:
    """Combine per-stream results per the rule's quantifier (ADR-009)."""
    pass_count = sum(1 for _, ok in results if ok)
    if quantifier is Quantifier.ALL:
        return pass_count == len(results), pass_count
    if quantifier is Quantifier.ANY:
        return pass_count >= 1, pass_count
    return pass_count == 1, pass_count  # EXACTLY_ONE


def _fail_status(severity: Severity) -> QCStatus:
    return QCStatus.WARNING if severity in (Severity.INFO, Severity.WARNING) else QCStatus.FAIL


def _exemplar(results: list[tuple[Measurement, bool]], passed: bool) -> Measurement:
    """The measurement shown as 'measured' in the finding.

    On failure: the first non-conforming measurement (the offender).
    On success: the first measurement.
    """
    if not passed:
        for m, ok in results:
            if not ok:
                return m
    return results[0][0]


def _fmt(actual: ActualValue) -> str:
    return f"{actual.value} {actual.unit}" if actual.unit else f"{actual.value}"


def _describe_expected(rule: Rule) -> str:
    from deepdub_qc.models.rule import (  # noqa: PLC0415
        ExpectedApprox,
        ExpectedPattern,
        ExpectedRange,
        ExpectedValue,
        ExpectedValues,
    )

    e = rule.expected
    op = rule.operator.value.replace("_", " ")
    match e:
        case ExpectedRange(min=lo, max=hi, unit=unit):
            return f"between {lo} and {hi}{' ' + unit if unit else ''}"
        case ExpectedApprox(value=v, tolerance=t, unit=unit):
            return f"{v}{' ' + unit if unit else ''} (±{t})"
        case ExpectedValues(values=vs, unit=unit):
            return f"{op}: {', '.join(str(v) for v in vs)}{' ' + unit if unit else ''}"
        case ExpectedPattern(pattern=p):
            return f"matches {p}"
        case ExpectedValue(value=v, unit=unit):
            return f"{op} {v}{' ' + unit if unit else ''}"
        case _:
            return op


# --------------------------------------------------------------------------- aggregation


def aggregate_status(findings: list[Finding]) -> QCStatus:
    """Overall job verdict (handoff section 17.3 + blocking-SKIPPED escalation)."""
    statuses = [(f.status, f.blocking) for f in findings]
    if any(s in (QCStatus.ERROR, QCStatus.SKIPPED) and blocking for s, blocking in statuses):
        return QCStatus.ERROR
    if any(s is QCStatus.FAIL and blocking for s, blocking in statuses):
        return QCStatus.FAIL
    if any(s in (QCStatus.FAIL, QCStatus.WARNING, QCStatus.ERROR) for s, _ in statuses):
        return QCStatus.WARNING
    return QCStatus.PASS


def build_summary(findings: list[Finding]) -> Summary:
    """Deterministic summary counts from the finding set."""

    def count(status: QCStatus) -> int:
        return sum(1 for f in findings if f.status is status)

    return Summary(
        overall_status=aggregate_status(findings),
        total_checks=len(findings),
        passed=count(QCStatus.PASS),
        warnings=count(QCStatus.WARNING),
        failed=count(QCStatus.FAIL),
        errors=count(QCStatus.ERROR),
        skipped=count(QCStatus.SKIPPED),
        not_applicable=count(QCStatus.NOT_APPLICABLE),
        blocking_failures=sum(1 for f in findings if f.status is QCStatus.FAIL and f.blocking),
    )
