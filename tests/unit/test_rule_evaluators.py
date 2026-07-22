"""Exhaustive operator evaluator tests (one class per operator family)."""

import pytest

from deepdub_qc.models.enums import Operator
from deepdub_qc.models.rule import (
    ExpectedApprox,
    ExpectedNothing,
    ExpectedPattern,
    ExpectedRange,
    ExpectedValue,
    ExpectedValues,
)
from deepdub_qc.rules.evaluators import EvaluationError, evaluate_operator


class TestEquality:
    def test_equals(self) -> None:
        assert evaluate_operator(Operator.EQUALS, 1920, ExpectedValue(value=1920))
        assert not evaluate_operator(Operator.EQUALS, 1280, ExpectedValue(value=1920))

    def test_equals_numeric_cross_type(self) -> None:
        assert evaluate_operator(Operator.EQUALS, 1920, ExpectedValue(value=1920.0))
        assert evaluate_operator(Operator.EQUALS, 48000.0, ExpectedValue(value=48000))

    def test_equals_bool_not_coerced_to_int(self) -> None:
        assert not evaluate_operator(Operator.EQUALS, True, ExpectedValue(value=1))

    def test_not_equals(self) -> None:
        assert evaluate_operator(Operator.NOT_EQUALS, "mp4", ExpectedValue(value="mov"))
        assert not evaluate_operator(Operator.NOT_EQUALS, "mov", ExpectedValue(value="mov"))


class TestMembership:
    def test_in(self) -> None:
        expected = ExpectedValues(values=["mov", "mxf"])
        assert evaluate_operator(Operator.IN, "mov", expected)
        assert not evaluate_operator(Operator.IN, "mp4", expected)

    def test_not_in(self) -> None:
        expected = ExpectedValues(values=["mp3", "aac"])
        assert evaluate_operator(Operator.NOT_IN, "pcm_s24le", expected)
        assert not evaluate_operator(Operator.NOT_IN, "aac", expected)


class TestOrdering:
    def test_greater_than(self) -> None:
        assert evaluate_operator(Operator.GREATER_THAN, 5, ExpectedValue(value=4))
        assert not evaluate_operator(Operator.GREATER_THAN, 4, ExpectedValue(value=4))

    def test_greater_than_or_equal(self) -> None:
        assert evaluate_operator(Operator.GREATER_THAN_OR_EQUAL, 4, ExpectedValue(value=4))

    def test_less_than(self) -> None:
        assert evaluate_operator(Operator.LESS_THAN, -2.5, ExpectedValue(value=-2.0))
        assert not evaluate_operator(Operator.LESS_THAN, -2.0, ExpectedValue(value=-2.0))

    def test_less_than_or_equal(self) -> None:
        assert evaluate_operator(Operator.LESS_THAN_OR_EQUAL, -2.0, ExpectedValue(value=-2.0))
        assert not evaluate_operator(Operator.LESS_THAN_OR_EQUAL, -1.9, ExpectedValue(value=-2.0))

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(EvaluationError):
            evaluate_operator(Operator.GREATER_THAN, "abc", ExpectedValue(value=4))


class TestRangeAndTolerance:
    def test_between_inclusive(self) -> None:
        expected = ExpectedRange(min=-24.0, max=-22.0)
        assert evaluate_operator(Operator.BETWEEN, -23.0, expected)
        assert evaluate_operator(Operator.BETWEEN, -24.0, expected)
        assert evaluate_operator(Operator.BETWEEN, -22.0, expected)
        assert not evaluate_operator(Operator.BETWEEN, -19.7, expected)

    def test_approximately_equals(self) -> None:
        expected = ExpectedApprox(value=23.976, tolerance=0.001)
        assert evaluate_operator(Operator.APPROXIMATELY_EQUALS, 23.976, expected)
        assert evaluate_operator(Operator.APPROXIMATELY_EQUALS, 23.9765, expected)
        assert not evaluate_operator(Operator.APPROXIMATELY_EQUALS, 25.0, expected)


class TestContains:
    def test_contains_string(self) -> None:
        assert evaluate_operator(Operator.CONTAINS, "yuv422p10le", ExpectedValue(value="422"))
        assert not evaluate_operator(Operator.CONTAINS, "yuv420p", ExpectedValue(value="422"))

    def test_contains_list(self) -> None:
        assert evaluate_operator(Operator.CONTAINS, ["deu", "eng"], ExpectedValue(value="deu"))

    def test_contains_all(self) -> None:
        expected = ExpectedValues(values=["deu", "eng"])
        assert evaluate_operator(Operator.CONTAINS_ALL, ["deu", "eng", "fra"], expected)
        assert not evaluate_operator(Operator.CONTAINS_ALL, ["deu"], expected)

    def test_contains_unsupported_type_raises(self) -> None:
        with pytest.raises(EvaluationError):
            evaluate_operator(Operator.CONTAINS, 42, ExpectedValue(value="4"))


class TestRegex:
    def test_regex_match(self) -> None:
        expected = ExpectedPattern(pattern=r"^[A-Za-z0-9._-]+\.(mov|mxf)$")
        assert evaluate_operator(Operator.REGEX, "final_v2.mov", expected)
        assert not evaluate_operator(Operator.REGEX, "final v2.mov", expected)

    def test_regex_non_string_raises(self) -> None:
        with pytest.raises(EvaluationError):
            evaluate_operator(Operator.REGEX, 42, ExpectedPattern(pattern="4"))


class TestExistence:
    def test_exists(self) -> None:
        assert evaluate_operator(Operator.EXISTS, "anything", ExpectedNothing())
        assert not evaluate_operator(Operator.EXISTS, None, ExpectedNothing())

    def test_not_exists(self) -> None:
        assert evaluate_operator(Operator.NOT_EXISTS, None, ExpectedNothing())
        assert not evaluate_operator(Operator.NOT_EXISTS, "x", ExpectedNothing())


class TestCounts:
    def test_count_equals_int_and_list(self) -> None:
        assert evaluate_operator(Operator.COUNT_EQUALS, 2, ExpectedValue(value=2))
        assert evaluate_operator(Operator.COUNT_EQUALS, ["a", "b"], ExpectedValue(value=2))

    def test_count_at_least(self) -> None:
        assert evaluate_operator(Operator.COUNT_AT_LEAST, 3, ExpectedValue(value=2))
        assert not evaluate_operator(Operator.COUNT_AT_LEAST, 1, ExpectedValue(value=2))

    def test_count_at_most(self) -> None:
        assert evaluate_operator(Operator.COUNT_AT_MOST, 2, ExpectedValue(value=2))
        assert not evaluate_operator(Operator.COUNT_AT_MOST, 3, ExpectedValue(value=2))

    def test_count_invalid_type_raises(self) -> None:
        with pytest.raises(EvaluationError):
            evaluate_operator(Operator.COUNT_EQUALS, "two", ExpectedValue(value=2))
        with pytest.raises(EvaluationError):
            evaluate_operator(Operator.COUNT_EQUALS, True, ExpectedValue(value=1))
