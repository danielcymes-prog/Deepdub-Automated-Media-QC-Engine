"""Preset models: client delivery requirements as versioned data (ADR-003).

A preset is pure data. It never contains executable logic, and no Python code
anywhere in the system may branch on a client name.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deepdub_qc.models.enums import PresetStatus, Severity
from deepdub_qc.models.rule import Rule
from deepdub_qc.models.types import NonEmptyStr, SemVer


class PresetMeta(BaseModel):
    """Identity and lifecycle metadata of a preset version (handoff section 12.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyStr
    version: SemVer
    client: NonEmptyStr
    content_type: NonEmptyStr
    title: NonEmptyStr
    description: str = ""
    owner: NonEmptyStr
    status: PresetStatus = PresetStatus.DRAFT
    effective_date: date
    supersedes: str | None = None


class PresetDefaults(BaseModel):
    """Fallback values applied to rules that omit severity/blocking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blocking: bool = True
    severity: Severity = Severity.ERROR


class ReportConfig(BaseModel):
    """Preset-controlled report rendering options (handoff section 12.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    include_passed_checks: bool = True
    include_raw_measurements: bool = False
    include_evidence: bool = True
    include_suggested_actions: bool = True


class QCPreset(BaseModel):
    """A complete, versioned client QC preset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SemVer
    preset: PresetMeta
    defaults: PresetDefaults = PresetDefaults()
    rules: list[Rule] = Field(min_length=1)
    report: ReportConfig = ReportConfig()

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> QCPreset:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for rule in self.rules:
            if rule.rule_id in seen:
                duplicates.add(rule.rule_id)
            seen.add(rule.rule_id)
        if duplicates:
            msg = f"duplicate rule_id values: {sorted(duplicates)}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _apply_defaults(self) -> QCPreset:
        """Fill omitted rule severity/blocking from preset defaults.

        Done at parse time so downstream consumers (rule engine, reports)
        never deal with unresolved None values.
        """
        if all(rule.severity is not None and rule.blocking is not None for rule in self.rules):
            return self
        resolved = [
            rule.model_copy(
                update={
                    "severity": rule.severity
                    if rule.severity is not None
                    else self.defaults.severity,
                    "blocking": rule.blocking
                    if rule.blocking is not None
                    else self.defaults.blocking,
                }
            )
            if rule.severity is None or rule.blocking is None
            else rule
            for rule in self.rules
        ]
        return self.model_copy(update={"rules": resolved})
