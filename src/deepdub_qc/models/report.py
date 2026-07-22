"""QC result envelope: the canonical JSON report (ADR-002, handoff section 11).

`QCResult` serialized to JSON *is* the report. HTML and PDF are renderings of
this model and must never contain information absent from it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from deepdub_qc.models.asset import Asset
from deepdub_qc.models.enums import QCStatus
from deepdub_qc.models.evidence import Evidence
from deepdub_qc.models.finding import Finding
from deepdub_qc.models.job import QCJob
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.models.types import NonEmptyStr, SemVer

RESULT_SCHEMA_VERSION = "1.0.0"

#: JSON paths excluded when comparing two runs for determinism (ADR-008).
#: Everything NOT listed here must be byte-identical across repeated runs
#: of the same input, preset, and environment.
VOLATILE_FIELDS: frozenset[str] = frozenset(
    {
        "job.job_id",
        "job.started_at",
        "job.completed_at",
        "job.duration_seconds",
        "measurements[].job_id",
        "measurements[].created_at",
        "findings[].job_id",
        "findings[].created_at",
        "evidence[].created_at",
        "generated_at",
    }
)


class PresetRef(BaseModel):
    """Reference to the exact preset a job used.

    `sha256` is the hash of the preset file bytes: `preset_version` alone is
    insufficient because draft presets are mutable (DATA_MODEL_REVIEW item 4).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: NonEmptyStr
    preset_version: SemVer
    client: NonEmptyStr
    content_type: NonEmptyStr
    sha256: NonEmptyStr


class Environment(BaseModel):
    """Execution environment fingerprint (ADR-008, DATA_MODEL_REVIEW item 3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None
    python_version: NonEmptyStr
    platform: NonEmptyStr
    docker_image: str | None = None


class Summary(BaseModel):
    """Aggregated counts and the overall verdict (handoff section 17.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_status: QCStatus
    total_checks: int = Field(ge=0)
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    skipped: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    blocking_failures: int = Field(ge=0)


class ArtifactPaths(BaseModel):
    """Relative paths of rendered artifacts inside the job output directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    html_report: str | None = None
    pdf_report: str | None = None
    evidence_directory: str | None = None
    raw_directory: str | None = None


class AISummary(BaseModel):
    """AI-generated commentary, stored strictly apart from canonical findings.

    Schema reserved in M1; populated only in Phase 9 (ADR-001). The presence
    or absence of this block must never change any canonical field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: NonEmptyStr
    model: NonEmptyStr
    prompt_version: SemVer
    generated_at: str
    content: str


class QCResult(BaseModel):
    """The canonical, versioned result of one QC job. Source of truth for all reports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer = RESULT_SCHEMA_VERSION
    job: QCJob
    asset: Asset
    preset: PresetRef
    environment: Environment
    summary: Summary
    media_summary: dict[str, JsonValue] = Field(default_factory=dict)
    measurements: list[Measurement] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    artifacts: ArtifactPaths = ArtifactPaths()
    ai_summary: AISummary | None = None
