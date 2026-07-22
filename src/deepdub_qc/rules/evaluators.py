"""Pure operator evaluators (handoff section 13).

Each evaluator is a pure function (measured value, expected payload) -> bool.
No I/O, no state, no client knowledge. Unit-tested exhaustively.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from deepdub_qc.models.enums import Operator
from deepdub_qc.models.rule import (
    Expected,
    ExpectedApprox,
    ExpectedPattern,
    ExpectedRange,
    ExpectedValue,
    ExpectedValues,
)


class EvaluationError(ValueError):
    """The measured value cannot be evaluated by this operator (type mismatch)."""


def _numeric(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{context}: expected a numeric value, got {type(value).__name__}"
        raise EvaluationError(msg)
    return float(value)


def _eq(measured: Any, expected: Any) -> bool:
    # Bools are never equal to numbers (True != 1): QC comparisons are type-strict.
    if isinstance(measured, bool) != isinstance(expected, bool):
        return False
    # Numeric cross-type equality (1920 == 1920.0).
    if (
        isinstance(measured, int | float)
        and isinstance(expected, int | float)
        and not isinstance(measured, bool)
    ):
        return math.isclose(float(measured), float(expected), rel_tol=0.0, abs_tol=1e-12)
    return bool(measured == expected)


def _value(expected: Expected) -> Any:
    assert isinstance(expected, ExpectedValue)
    return expected.value


def evaluate_operator(operator: Operator, measured: Any, expected: Expected) -> bool:
    """Apply one operator. Raises EvaluationError on type mismatches."""
    evaluator = _EVALUATORS[operator]
    return evaluator(measured, expected)


# --------------------------------------------------------------------------- evaluators


def _op_equals(measured: Any, expected: Expected) -> bool:
    return _eq(measured, _value(expected))


def _op_not_equals(measured: Any, expected: Expected) -> bool:
    return not _eq(measured, _value(expected))


def _op_in(measured: Any, expected: Expected) -> bool:
    assert isinstance(expected, ExpectedValues)
    return any(_eq(measured, v) for v in expected.values)


def _op_not_in(measured: Any, expected: Expected) -> bool:
    return not _op_in(measured, expected)


def _op_greater_than(measured: Any, expected: Expected) -> bool:
    return _numeric(measured, "greater_than") > _numeric(_value(expected), "greater_than")


def _op_greater_than_or_equal(measured: Any, expected: Expected) -> bool:
    return _numeric(measured, "greater_than_or_equal") >= _numeric(
        _value(expected), "greater_than_or_equal"
    )


def _op_less_than(measured: Any, expected: Expected) -> bool:
    return _numeric(measured, "less_than") < _numeric(_value(expected), "less_than")


def _op_less_than_or_equal(measured: Any, expected: Expected) -> bool:
    return _numeric(measured, "less_than_or_equal") <= _numeric(
        _value(expected), "less_than_or_equal"
    )


def _op_between(measured: Any, expected: Expected) -> bool:
    assert isinstance(expected, ExpectedRange)
    value = _numeric(measured, "between")
    return expected.min <= value <= expected.max


def _op_approximately_equals(measured: Any, expected: Expected) -> bool:
    assert isinstance(expected, ExpectedApprox)
    return abs(_numeric(measured, "approximately_equals") - expected.value) <= expected.tolerance


def _op_contains(measured: Any, expected: Expected) -> bool:
    target = _value(expected)
    if isinstance(measured, str):
        return str(target) in measured
    if isinstance(measured, list):
        return any(_eq(item, target) for item in measured)
    msg = f"contains: unsupported measured type {type(measured).__name__}"
    raise EvaluationError(msg)


def _op_contains_all(measured: Any, expected: Expected) -> bool:
    assert isinstance(expected, ExpectedValues)
    if isinstance(measured, str):
        return all(str(v) in measured for v in expected.values)
    if isinstance(measured, list):
        return all(any(_eq(item, v) for item in measured) for v in expected.values)
    msg = f"contains_all: unsupported measured type {type(measured).__name__}"
    raise EvaluationError(msg)


def _op_regex(measured: Any, expected: Expected) -> bool:
    assert isinstance(expected, ExpectedPattern)
    if not isinstance(measured, str):
        msg = f"regex: expected a string value, got {type(measured).__name__}"
        raise EvaluationError(msg)
    return re.search(expected.pattern, measured) is not None


def _op_exists(measured: Any, expected: Expected) -> bool:
    return measured is not None


def _op_not_exists(measured: Any, expected: Expected) -> bool:
    return measured is None


def _op_count_equals(measured: Any, expected: Expected) -> bool:
    return _count(measured) == int(_numeric(_value(expected), "count_equals"))


def _op_count_at_least(measured: Any, expected: Expected) -> bool:
    return _count(measured) >= int(_numeric(_value(expected), "count_at_least"))


def _op_count_at_most(measured: Any, expected: Expected) -> bool:
    return _count(measured) <= int(_numeric(_value(expected), "count_at_most"))


def _count(measured: Any) -> int:
    if isinstance(measured, bool):
        msg = "count operators require a list or integer value, got bool"
        raise EvaluationError(msg)
    if isinstance(measured, list):
        return len(measured)
    if isinstance(measured, int):
        return measured
    msg = f"count operators require a list or integer value, got {type(measured).__name__}"
    raise EvaluationError(msg)


_EVALUATORS: dict[Operator, Callable[[Any, Expected], bool]] = {
    Operator.EQUALS: _op_equals,
    Operator.NOT_EQUALS: _op_not_equals,
    Operator.IN: _op_in,
    Operator.NOT_IN: _op_not_in,
    Operator.GREATER_THAN: _op_greater_than,
    Operator.GREATER_THAN_OR_EQUAL: _op_greater_than_or_equal,
    Operator.LESS_THAN: _op_less_than,
    Operator.LESS_THAN_OR_EQUAL: _op_less_than_or_equal,
    Operator.BETWEEN: _op_between,
    Operator.APPROXIMATELY_EQUALS: _op_approximately_equals,
    Operator.CONTAINS: _op_contains,
    Operator.CONTAINS_ALL: _op_contains_all,
    Operator.REGEX: _op_regex,
    Operator.EXISTS: _op_exists,
    Operator.NOT_EXISTS: _op_not_exists,
    Operator.COUNT_EQUALS: _op_count_equals,
    Operator.COUNT_AT_LEAST: _op_count_at_least,
    Operator.COUNT_AT_MOST: _op_count_at_most,
}
