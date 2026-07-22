"""Measurement model: an objective fact produced by a detector (handoff section 9).

Measurements never contain pass/fail judgements. Findings are derived from
measurements by the rule engine and stored separately, so a stored measurement
set can be re-evaluated against a new preset without rerunning detectors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from deepdub_qc.models.enums import Category
from deepdub_qc.models.types import NonEmptyStr, SemVer

MEASUREMENT_SCHEMA_VERSION = "1.0.0"


class Measurement(BaseModel):
    """One normalized value extracted from a media asset by a detector.

    Determinism (ADR-008): `measurement_id` is a content-derived UUIDv5
    (see deepdub_qc.utils.ids). `created_at` is a declared volatile field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer = MEASUREMENT_SCHEMA_VERSION
    measurement_id: UUID
    job_id: UUID
    detector_id: NonEmptyStr
    detector_version: SemVer
    parameter_id: NonEmptyStr
    category: Category
    value: JsonValue
    unit: str | None = None
    stream_index: int | None = Field(default=None, ge=0)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    start_timecode: str | None = None
    end_timecode: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    raw_artifact_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
