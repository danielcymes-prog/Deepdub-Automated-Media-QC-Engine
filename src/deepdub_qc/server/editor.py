"""Console preset editor: value/severity/enable edits become new draft versions.

Why: thresholds are the thing operators actually need to change (the master
presets exist precisely so the A/V engineer can tune one baseline), and asking
a post-production engineer to hand-edit YAML defeats the point
(docs/master-preset-spec.md section 5, ADR-031).

Hard rules:
- The editor NEVER mutates a preset file in place. Every save produces a new
  file with a minor version bump, status `draft`, `supersedes` set to the base
  version, and a provenance header (who, when, from which base, why). Approval
  and locking are unchanged (ADR-013) - editing an approved preset simply
  drafts its successor.
- The editor edits VALUES, not shape: expected payload numbers/strings,
  severity, blocking, enabled. Operators, scoping and rule structure remain
  YAML work. Disabling a rule sets `enabled: false` - the rule stays in the
  file, so nothing is ever lost by unticking a box.
- Every save round-trips through the real preset loader BEFORE the file
  reaches its final name; a validation failure saves nothing (schema
  validation is never bypassed).
- Conflict guard: a save carries the base version it was edited from; if any
  newer version of that preset id exists, the save is rejected. Last-write-
  wins is not acceptable for QC policy.

Inputs: preset files + the parameter catalogue. Outputs: editable view models
and new draft preset files. Side effects: writes exactly one YAML file per
successful save.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from deepdub_qc.exceptions import DeepdubQCError, PresetError, preset_error_detail
from deepdub_qc.models.enums import Severity
from deepdub_qc.models.parameters import CATALOGUE
from deepdub_qc.presets.loader import load_preset
from deepdub_qc.server.catalog import PresetInfo

#: expected-payload keys the editor may change, in emission order. `unit` is
#: deliberately absent: it describes the measurement, it is not a threshold.
EDITABLE_EXPECTED_KEYS = ("value", "values", "min", "max", "tolerance", "pattern")


class EditorError(DeepdubQCError):
    """A save could not be performed; the message is operator-facing."""


class VersionConflictError(EditorError):
    """A newer version of the preset exists; the edit was based on stale data."""


@dataclass(frozen=True)
class RuleEdit:
    """One rule's submitted state (absent expected keys stay untouched)."""

    rule_id: str
    enabled: bool
    severity: str
    blocking: bool
    expected: dict[str, Any]


def load_raw(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise EditorError(f"not a preset mapping: {path}")
    return document


def editable_model(path: Path) -> dict[str, Any]:
    """The editor's view of one preset: rules + catalogue context, defaults resolved."""
    document = load_raw(path)
    meta = document["preset"]
    defaults = document.get("defaults", {})
    rules = []
    for rule in document.get("rules", []):
        parameter = CATALOGUE.get(rule["parameter_id"])
        expected = rule.get("expected") or {}
        rules.append(
            {
                "rule_id": rule["rule_id"],
                "parameter_id": rule["parameter_id"],
                "display_name": rule.get("display_name", rule["rule_id"]),
                "description": rule.get("description"),
                "operator": rule.get("operator", "not_exists"),
                "enabled": bool(rule.get("enabled", True)),
                "severity": rule.get("severity", defaults.get("severity", "error")),
                "blocking": bool(rule.get("blocking", defaults.get("blocking", True))),
                "unit": expected.get("unit"),
                "expected": {
                    key: expected[key] for key in EDITABLE_EXPECTED_KEYS if key in expected
                },
                "applies_to": _scope_summary(rule.get("applies_to")),
                "section": rule["parameter_id"].split(".")[0],
                "catalogue_description": parameter.description if parameter else None,
                "catalogue_limitations": getattr(parameter, "limitations", None)
                if parameter
                else None,
            }
        )
    return {
        "preset_id": meta["id"],
        "version": str(meta["version"]),
        "title": meta["title"],
        "client": meta["client"],
        "status": meta.get("status", "draft"),
        "content_type": meta["content_type"],
        "severities": [s.value for s in Severity],
        "rules": rules,
    }


def _scope_summary(applies_to: dict[str, Any] | None) -> str:
    if not applies_to:
        return "file / container"
    parts = [str(applies_to.get("stream_type", ""))]
    selector = applies_to.get("selector") or {}
    if selector.get("index") is not None:
        parts.append(f"stream #{selector['index']}")
    if selector.get("language"):
        parts.append(f"lang {selector['language']}")
    parts.append(str(applies_to.get("quantifier", "all")))
    return " · ".join(p for p in parts if p)


def _bump_minor(version: str) -> str:
    major, minor, _patch = (int(part) for part in version.split("."))
    return f"{major}.{minor + 1}.0"


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _coerce_like(original: Any, submitted: Any) -> Any:  # noqa: PLR0911 - one return per type
    """Type an input string like the value it replaces (ints stay ints, etc.).

    Non-string input (the JSON API path) is passed through untyped - the
    loader round-trip validates it like everything else.
    """
    if not isinstance(submitted, str):
        return submitted
    if isinstance(original, bool):
        return submitted.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(original, int) and not isinstance(original, bool):
        try:
            return int(submitted)
        except ValueError:
            return float(submitted)  # 24 -> 23.5 is a legitimate edit
    if isinstance(original, float):
        return float(submitted)
    if isinstance(original, list):
        items = [part.strip() for part in submitted.split(",") if part.strip()]
        element = original[0] if original else ""
        return [_coerce_like(element, item) for item in items]
    return submitted


def apply_edits(  # noqa: PLR0913 - one argument per audited save field
    base_path: Path,
    base_version: str,
    catalog: list[PresetInfo],
    edits: list[RuleEdit],
    edited_by: str,
    note: str,
) -> Path:
    """Create the next draft version of a preset from submitted rule edits.

    Returns the new file's path. Raises VersionConflictError on stale base,
    EditorError on anything the operator must fix (message included).
    """
    document = load_raw(base_path)
    meta = document["preset"]
    if str(meta["version"]) != base_version:
        raise VersionConflictError(
            f"this file is version {meta['version']}, not {base_version} - reload the editor"
        )
    newest = max(
        (entry.version for entry in catalog if entry.preset_id == meta["id"]),
        key=_version_tuple,
        default=base_version,
    )
    if _version_tuple(newest) > _version_tuple(base_version):
        raise VersionConflictError(
            f"version {newest} of {meta['id']!r} already exists - your edit is based on "
            f"{base_version}. Reload the editor on the newest version and reapply."
        )
    if not edited_by.strip():
        raise EditorError("a name is required - every saved version records who changed it")

    by_id = {rule["rule_id"]: rule for rule in document.get("rules", [])}
    defaults = document.get("defaults", {})
    for edit in edits:
        rule = by_id.get(edit.rule_id)
        if rule is None:
            raise EditorError(f"unknown rule {edit.rule_id!r} - reload the editor")
        rule["enabled"] = edit.enabled
        rule["severity"] = edit.severity
        rule["blocking"] = edit.blocking
        expected = rule.get("expected")
        for key, submitted in edit.expected.items():
            if expected is None or key not in expected:
                raise EditorError(f"rule {edit.rule_id!r} has no editable {key!r} field")
            expected[key] = _coerce_like(expected[key], submitted)
    # Defaults exist for hand-written YAML terseness; an edited file is
    # explicit per rule, so drop nothing but keep the section for the loader.
    document["defaults"] = defaults

    new_version = _bump_minor(base_version)
    meta["version"] = new_version
    meta["status"] = "draft"
    meta["supersedes"] = base_version
    meta["effective_date"] = datetime.now(UTC).date().isoformat()

    major, minor, _ = new_version.split(".")
    new_path = base_path.parent / f"{meta['id']}_v{major}_{minor}.yaml"
    if new_path.exists():
        raise VersionConflictError(f"{new_path.name} already exists - reload the editor")

    header = [
        f"# {meta['title']} v{new_version} - saved from the console preset editor.",
        f"# Edited by: {edited_by.strip()}",
        f"# Edited at: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"# Base version: {base_version} ({base_path.name})",
    ]
    if note.strip():
        header.append(f"# Change note: {note.strip()}")
    header.append("# Status: draft - approval happens via `deepdub-qc presets lock` (ADR-013).")
    body = yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
    )
    text = "\n".join(header) + "\n" + body

    # Round-trip through the real loader BEFORE the file gets its final name:
    # an invalid edit must leave the presets directory exactly as it was.
    temp_path = base_path.parent / f".{new_path.name}.editing"
    temp_path.write_text(text, encoding="utf-8")
    try:
        load_preset(temp_path)
    except PresetError as exc:
        temp_path.unlink(missing_ok=True)
        raise EditorError(
            f"the edited preset failed validation: {preset_error_detail(exc)}"
        ) from exc
    temp_path.replace(new_path)
    return new_path


def edits_from_form(form: dict[str, str], model: dict[str, Any]) -> list[RuleEdit]:
    """Translate the editor form's flat fields into RuleEdits.

    Field naming: r__<rule_id>__<key>. Checkbox fields (enabled, blocking) are
    absent when unchecked - presence is the value.
    """
    edits = []
    for rule in model["rules"]:
        rule_id = rule["rule_id"]
        prefix = f"r__{rule_id}__"
        expected = {}
        for key in EDITABLE_EXPECTED_KEYS:
            if key in rule["expected"] and f"{prefix}{key}" in form:
                expected[key] = form[f"{prefix}{key}"]
        edits.append(
            RuleEdit(
                rule_id=rule_id,
                enabled=f"{prefix}enabled" in form,
                severity=form.get(f"{prefix}severity", rule["severity"]),
                blocking=f"{prefix}blocking" in form,
                expected=expected,
            )
        )
    return edits


def edits_from_payload(payload: list[dict[str, Any]]) -> list[RuleEdit]:
    """Translate the JSON API's rules array into RuleEdits (values kept typed)."""
    return [
        RuleEdit(
            rule_id=str(item["rule_id"]),
            enabled=bool(item.get("enabled", True)),
            severity=str(item.get("severity", "error")),
            blocking=bool(item.get("blocking", True)),
            expected=dict(item.get("expected") or {}),
        )
        for item in payload
    ]
