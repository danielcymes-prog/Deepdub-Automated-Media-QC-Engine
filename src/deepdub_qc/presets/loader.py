"""Preset loading: YAML file -> validated QCPreset model.

Why this exists: presets are the only mechanism for client-specific behavior
(ADR-003). Everything downstream assumes a preset that passed this loader is
structurally sound, so all schema and invariant errors must surface here with
actionable messages.

Inputs: a filesystem path to a YAML preset.
Outputs: an immutable QCPreset, or a typed PresetError subclass.
Side effects: none (pure read).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from deepdub_qc.exceptions import PresetNotFoundError, PresetParseError, PresetValidationError
from deepdub_qc.models import parameters
from deepdub_qc.models.preset import QCPreset
from deepdub_qc.utils.hashing import sha256_file

logger = logging.getLogger(__name__)


def _parameter_errors(preset: QCPreset) -> list[str]:
    """Report rules whose `parameter_id` no detector can satisfy (ADR-021).

    Why: an uncatalogued or not-yet-implemented parameter cannot produce a
    measurement. A blocking rule over one escalates to ERROR and is noticed,
    but a non-blocking rule degrades to a SKIPPED finding — the operator gets a
    complete-looking report for a check that never ran. Catching it at load
    time is the difference between a typo being a validation error and a typo
    being a silent gap in QC coverage.

    Returns one message per offending rule; empty list when the preset is sound.
    """
    implemented = parameters.implemented_ids()
    errors = []
    for rule in preset.rules:
        if rule.parameter_id in implemented:
            continue

        definition = parameters.get(rule.parameter_id)
        if definition is not None:
            errors.append(
                f"rules.{rule.rule_id}.parameter_id: {rule.parameter_id!r} is catalogued "
                f"but not implemented yet (status: {definition.implementation.value}); "
                "no detector produces it, so this rule could never be evaluated"
            )
            continue

        message = (
            f"rules.{rule.rule_id}.parameter_id: {rule.parameter_id!r} is not in the "
            "parameter catalogue (see docs/parameter-catalogue.md)"
        )
        if suggestions := parameters.suggest(rule.parameter_id):
            message += f"; did you mean {' or '.join(repr(s) for s in suggestions)}?"
        errors.append(message)
    return errors


def load_preset(path: Path) -> QCPreset:
    """Load and fully validate a preset YAML file.

    Raises:
        PresetNotFoundError: path missing or not a file.
        PresetParseError: file is not valid YAML or not a mapping.
        PresetValidationError: YAML parsed but violates the preset schema, or
            references a `parameter_id` no detector can measure (ADR-021).
    """
    if not path.is_file():
        raise PresetNotFoundError(f"preset file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PresetParseError(f"preset is not valid YAML: {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise PresetParseError(f"preset root must be a mapping, got {type(raw).__name__}: {path}")

    try:
        preset = QCPreset.model_validate(raw)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
        raise PresetValidationError(
            f"preset failed validation with {len(errors)} error(s): {path}", errors=errors
        ) from exc

    if parameter_errors := _parameter_errors(preset):
        raise PresetValidationError(
            f"preset references {len(parameter_errors)} unmeasurable parameter(s): {path}",
            errors=parameter_errors,
        )

    logger.debug(
        "preset loaded",
        extra={
            "preset_id": preset.preset.id,
            "preset_version": preset.preset.version,
            "rule_count": len(preset.rules),
        },
    )
    return preset


def preset_sha256(path: Path) -> str:
    """Hash the exact preset file bytes for result traceability (DATA_MODEL_REVIEW item 4)."""
    if not path.is_file():
        raise PresetNotFoundError(f"preset file not found: {path}")
    return sha256_file(path)
