"""Domain models: the shared vocabulary of the QC engine.

This package imports nothing from the application layers (only stdlib and
Pydantic) so every subsystem can depend on it without coupling.
"""

from deepdub_qc.models.asset import Asset
from deepdub_qc.models.enums import (
    Category,
    EvidenceType,
    JobStatus,
    Operator,
    PresetStatus,
    QCStatus,
    Quantifier,
    Severity,
    StreamType,
)
from deepdub_qc.models.evidence import Evidence
from deepdub_qc.models.finding import ActualValue, Finding
from deepdub_qc.models.job import QCJob
from deepdub_qc.models.measurement import Measurement
from deepdub_qc.models.preset import PresetDefaults, PresetMeta, QCPreset, ReportConfig
from deepdub_qc.models.report import (
    VOLATILE_FIELDS,
    AISummary,
    ArtifactPaths,
    Environment,
    PresetRef,
    QCResult,
    Summary,
)
from deepdub_qc.models.rule import (
    AppliesTo,
    Expected,
    ExpectedApprox,
    ExpectedNothing,
    ExpectedPattern,
    ExpectedRange,
    ExpectedValue,
    ExpectedValues,
    Rule,
    StreamSelector,
)

__all__ = [
    "VOLATILE_FIELDS",
    "AISummary",
    "ActualValue",
    "AppliesTo",
    "ArtifactPaths",
    "Asset",
    "Category",
    "Environment",
    "Evidence",
    "EvidenceType",
    "Expected",
    "ExpectedApprox",
    "ExpectedNothing",
    "ExpectedPattern",
    "ExpectedRange",
    "ExpectedValue",
    "ExpectedValues",
    "Finding",
    "JobStatus",
    "Measurement",
    "Operator",
    "PresetDefaults",
    "PresetMeta",
    "PresetRef",
    "PresetStatus",
    "QCJob",
    "QCPreset",
    "QCResult",
    "QCStatus",
    "Quantifier",
    "ReportConfig",
    "Rule",
    "Severity",
    "StreamSelector",
    "StreamType",
    "Summary",
]
