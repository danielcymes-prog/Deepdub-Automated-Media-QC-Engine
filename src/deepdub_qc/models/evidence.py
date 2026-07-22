"""Evidence model: a supporting artifact tied to a finding (docs/DATA_MODEL_REVIEW.md item 6)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from deepdub_qc.models.enums import EvidenceType
from deepdub_qc.models.types import NonEmptyStr, SemVer

EVIDENCE_SCHEMA_VERSION = "1.0.0"


class Evidence(BaseModel):
    """One evidence artifact (thumbnail, waveform, clip, or raw tool output)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer = EVIDENCE_SCHEMA_VERSION
    evidence_id: UUID
    finding_id: UUID | None = None
    type: EvidenceType
    path: NonEmptyStr
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    generated_by: NonEmptyStr
    sha256: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
