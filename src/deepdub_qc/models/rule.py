"""Rule model: a preset-defined expectation over a measured parameter.

Design (ADR-009): a rule has its own identity (`rule_id`) and references a
parameter from the parameter catalogue (`parameter_id`). This allows multiple
rules over the same parameter (e.g. loudness on the dubbed dialogue stream vs.
the M&E stem). Rules never know how measurements are produced.

The `expected` payload is a discriminated shape chosen by `operator`
(docs/DATA_MODEL_REVIEW.md item 5): preset validation rejects e.g. a
`between` rule without `min`/`max` at load time, not at evaluation time.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deepdub_qc.models.enums import Operator, Quantifier, Severity, StreamType
from deepdub_qc.models.types import NonEmptyStr, SemVer

# --------------------------------------------------------------------------- expected payloads


class _ExpectedBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: str | None = None


class ExpectedValue(_ExpectedBase):
    """A single comparison value (equals, ordering, contains, count_*)."""

    value: Any


class ExpectedValues(_ExpectedBase):
    """A set of allowed/forbidden values (in, not_in, contains_all)."""

    values: list[Any] = Field(min_length=1)


class ExpectedRange(_ExpectedBase):
    """An inclusive numeric range (between)."""

    min: float
    max: float

    @model_validator(mode="after")
    def _check_bounds(self) -> ExpectedRange:
        if self.min > self.max:
            msg = f"range min ({self.min}) must be <= max ({self.max})"
            raise ValueError(msg)
        return self


class ExpectedApprox(_ExpectedBase):
    """A target value with tolerance (approximately_equals)."""

    value: float
    tolerance: float = Field(gt=0)


class ExpectedPattern(_ExpectedBase):
    """A regular expression the actual value must match (regex)."""

    pattern: NonEmptyStr

    @field_validator("pattern")
    @classmethod
    def _check_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            msg = f"invalid regular expression: {exc}"
            raise ValueError(msg) from exc
        return value


class ExpectedNothing(_ExpectedBase):
    """No payload (exists, not_exists)."""


Expected = (
    ExpectedValue
    | ExpectedValues
    | ExpectedRange
    | ExpectedApprox
    | ExpectedPattern
    | ExpectedNothing
)

_OPERATOR_EXPECTED: dict[Operator, type[_ExpectedBase]] = {
    Operator.EQUALS: ExpectedValue,
    Operator.NOT_EQUALS: ExpectedValue,
    Operator.IN: ExpectedValues,
    Operator.NOT_IN: ExpectedValues,
    Operator.GREATER_THAN: ExpectedValue,
    Operator.GREATER_THAN_OR_EQUAL: ExpectedValue,
    Operator.LESS_THAN: ExpectedValue,
    Operator.LESS_THAN_OR_EQUAL: ExpectedValue,
    Operator.BETWEEN: ExpectedRange,
    Operator.APPROXIMATELY_EQUALS: ExpectedApprox,
    Operator.CONTAINS: ExpectedValue,
    Operator.CONTAINS_ALL: ExpectedValues,
    Operator.REGEX: ExpectedPattern,
    Operator.EXISTS: ExpectedNothing,
    Operator.NOT_EXISTS: ExpectedNothing,
    Operator.COUNT_EQUALS: ExpectedValue,
    Operator.COUNT_AT_LEAST: ExpectedValue,
    Operator.COUNT_AT_MOST: ExpectedValue,
}

# --------------------------------------------------------------------------- stream selection


class StreamSelector(BaseModel):
    """Selects streams by index or language tag; empty selector = all streams of type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int | None = Field(default=None, ge=0)
    language: str | None = None

    @model_validator(mode="after")
    def _at_most_one(self) -> StreamSelector:
        if self.index is not None and self.language is not None:
            msg = "stream selector may set index or language, not both"
            raise ValueError(msg)
        return self


class AppliesTo(BaseModel):
    """Stream scope of a rule (ADR-009). Omitted = file/container scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_type: StreamType
    selector: StreamSelector = StreamSelector()
    quantifier: Quantifier = Quantifier.ALL


# --------------------------------------------------------------------------- rule


class Rule(BaseModel):
    """A single preset rule: compare a measured parameter against an expectation.

    `severity` and `blocking` may be omitted in preset YAML, in which case the
    preset's `defaults` section fills them in at load time (see QCPreset).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: NonEmptyStr
    parameter_id: NonEmptyStr
    enabled: bool = True
    operator: Operator
    expected: Expected = ExpectedNothing()
    severity: Severity | None = None
    blocking: bool | None = None
    applies_to: AppliesTo | None = None
    display_name: str | None = None
    description: str | None = None
    suggested_action: str | None = None
    rule_version: SemVer = "1.0.0"

    @model_validator(mode="before")
    @classmethod
    def _coerce_expected(cls, data: Any) -> Any:
        """Parse `expected` into the payload shape dictated by `operator`.

        This makes the union deterministic: the operator, not duck-typing,
        decides which Expected model applies.
        """
        if not isinstance(data, dict):
            return data
        operator = data.get("operator")
        expected = data.get("expected")
        if operator is None or isinstance(expected, _ExpectedBase):
            return data
        try:
            op = Operator(operator)
        except ValueError:
            return data  # let the enum field produce the error
        expected_type = _OPERATOR_EXPECTED[op]
        data = dict(data)
        data["expected"] = expected_type.model_validate(expected if expected is not None else {})
        return data

    @model_validator(mode="after")
    def _check_expected_matches_operator(self) -> Rule:
        expected_type = _OPERATOR_EXPECTED[self.operator]
        if type(self.expected) is not expected_type:
            msg = (
                f"rule {self.rule_id!r}: operator {self.operator.value!r} requires "
                f"{expected_type.__name__} expected payload, got {type(self.expected).__name__}"
            )
            raise ValueError(msg)
        if self.operator in (
            Operator.COUNT_EQUALS,
            Operator.COUNT_AT_LEAST,
            Operator.COUNT_AT_MOST,
        ):
            value = self.expected.value if isinstance(self.expected, ExpectedValue) else None
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                msg = f"rule {self.rule_id!r}: count operators require a non-negative integer value"
                raise ValueError(msg)
        return self
