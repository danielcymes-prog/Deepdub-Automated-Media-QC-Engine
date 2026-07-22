"""Rule model: operator/expected coherence (DATA_MODEL_REVIEW item 5, ADR-009)."""

import pytest
from pydantic import ValidationError

from deepdub_qc.models.rule import (
    ExpectedApprox,
    ExpectedNothing,
    ExpectedPattern,
    ExpectedRange,
    ExpectedValue,
    ExpectedValues,
    Rule,
)


def make_rule(**overrides: object) -> Rule:
    data: dict[str, object] = {
        "rule_id": "test-rule",
        "parameter_id": "video.width",
        "operator": "equals",
        "expected": {"value": 1920},
    }
    data.update(overrides)
    return Rule.model_validate(data)


class TestExpectedCoercion:
    def test_equals_coerces_to_expected_value(self) -> None:
        rule = make_rule()
        assert isinstance(rule.expected, ExpectedValue)
        assert rule.expected.value == 1920

    def test_in_coerces_to_expected_values(self) -> None:
        rule = make_rule(operator="in", expected={"values": ["mov", "mxf"]})
        assert isinstance(rule.expected, ExpectedValues)

    def test_between_coerces_to_expected_range(self) -> None:
        rule = make_rule(operator="between", expected={"min": -24.0, "max": -22.0, "unit": "LUFS"})
        assert isinstance(rule.expected, ExpectedRange)

    def test_approximately_equals_requires_tolerance(self) -> None:
        rule = make_rule(
            operator="approximately_equals", expected={"value": 23.976, "tolerance": 0.001}
        )
        assert isinstance(rule.expected, ExpectedApprox)
        with pytest.raises(ValidationError):
            make_rule(operator="approximately_equals", expected={"value": 23.976})

    def test_regex_coerces_and_validates_pattern(self) -> None:
        rule = make_rule(operator="regex", expected={"pattern": r"^[a-z]+\.mov$"})
        assert isinstance(rule.expected, ExpectedPattern)
        with pytest.raises(ValidationError, match="invalid regular expression"):
            make_rule(operator="regex", expected={"pattern": "(unclosed"})

    def test_exists_takes_no_payload(self) -> None:
        rule = make_rule(operator="exists", expected=None)
        assert isinstance(rule.expected, ExpectedNothing)


class TestExpectedShapeErrors:
    def test_between_missing_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_rule(operator="between", expected={"min": -24.0})

    def test_between_inverted_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"min .* must be <="):
            make_rule(operator="between", expected={"min": 5.0, "max": 1.0})

    def test_extra_expected_keys_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_rule(expected={"value": 1920, "bogus": True})

    def test_count_operator_requires_nonnegative_int(self) -> None:
        rule = make_rule(operator="count_at_least", expected={"value": 2})
        assert isinstance(rule.expected, ExpectedValue)
        with pytest.raises(ValidationError, match="non-negative integer"):
            make_rule(operator="count_equals", expected={"value": -1})
        with pytest.raises(ValidationError, match="non-negative integer"):
            make_rule(operator="count_equals", expected={"value": 2.5})


class TestStreamSelectors:
    def test_applies_to_defaults(self) -> None:
        rule = make_rule(applies_to={"stream_type": "audio"})
        assert rule.applies_to is not None
        assert rule.applies_to.quantifier == "all"

    def test_selector_index_and_language_mutually_exclusive(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            make_rule(
                applies_to={
                    "stream_type": "audio",
                    "selector": {"index": 1, "language": "deu"},
                }
            )
