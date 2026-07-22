"""Finding model: the result of evaluating measurements against one rule (handoff section 10).

A finding must be reproducible from (measurements, rule) alone. It records
both the rule identity and the parameter identity (ADR-009).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from deepdub_qc.models.enums import Category, QCStatus, Severity
from deepdub_qc.models.rule import Expected
from deepdub_qc.models.types import NonEmptyStr, SemVer

FINDING_SCHEMA_VERSION = "1.0.0"


class ActualValue(BaseModel):
    """The measured value a rule was evaluated against."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: JsonValue
    unit: str | None = None


class Finding(BaseModel):
    """Outcome of one rule evaluation.

    Canonical `message` text is produced from deterministic templates.
    AI-generated explanations are never stored here (ADR-001); they belong to
    the separate `ai_summary` structure on the report.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer = FINDING_SCHEMA_VERSION
    finding_id: UUID
    job_id: UUID
    rule_id: NonEmptyStr
    parameter_id: NonEmptyStr
    category: Category
    display_name: NonEmptyStr
    status: QCStatus
    severity: Severity
    expected: Expected | None = None
    actual: ActualValue | None = None
    message: NonEmptyStr
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    start_timecode: str | None = None
    end_timecode: str | None = None
    stream_index: int | None = Field(default=None, ge=0)
    measurement_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    suggested_action: str | None = None
    blocking: bool
    rule_version: SemVer
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
