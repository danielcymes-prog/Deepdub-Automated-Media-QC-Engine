"""Job model: execution metadata of one QC run (handoff section 11, `job` block)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from deepdub_qc.models.enums import JobStatus
from deepdub_qc.models.types import SemVer

JOB_SCHEMA_VERSION = "1.0.0"


class QCJob(BaseModel):
    """Execution record of a QC job.

    All timestamp/duration fields are declared volatile for determinism
    comparisons (ADR-008); `job_id` is the only random identifier in the system.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer = JOB_SCHEMA_VERSION
    job_id: UUID
    status: JobStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    tool_version: SemVer
