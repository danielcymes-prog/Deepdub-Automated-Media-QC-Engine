"""Preset governance: approved presets are immutable (ADR-003, ADR-013).

Mechanism: presets/approved.lock.json records the sha256 of every preset file
whose status is `approved`. CI verifies the lock on every run, so:

- editing an approved preset file breaks the build (create a new version
  instead - handoff section 12.3),
- demoting an approved preset back to draft breaks the build (deprecate it
  and supersede with a new version instead),
- approving a preset is an explicit, reviewable `deepdub-qc presets lock`
  commit that a human makes after client sign-off (handoff section 30).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from deepdub_qc.exceptions import PresetError
from deepdub_qc.models.enums import PresetStatus
from deepdub_qc.presets.loader import load_preset
from deepdub_qc.utils.hashing import sha256_file

logger = logging.getLogger(__name__)

LOCK_FILENAME = "approved.lock.json"


def discover_presets(root: Path) -> list[Path]:
    """All preset YAML files under a directory, in deterministic order."""
    return sorted(p for p in root.rglob("*.yaml") if p.is_file())


def build_lock(root: Path) -> dict[str, str]:
    """Map (posix relative path -> sha256) for every approved preset under root.

    Invalid preset files are skipped here; `presets validate` reports them.
    """
    lock: dict[str, str] = {}
    for path in discover_presets(root):
        try:
            preset = load_preset(path)
        except PresetError:
            continue
        if preset.preset.status is PresetStatus.APPROVED:
            lock[path.relative_to(root).as_posix()] = sha256_file(path)
    return lock


def write_lock(root: Path) -> Path:
    """Write the approval lock file and return its path."""
    target = root / LOCK_FILENAME
    target.write_text(
        json.dumps(build_lock(root), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def read_lock(root: Path) -> dict[str, str]:
    target = root / LOCK_FILENAME
    if not target.is_file():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"approval lock must be a JSON object: {target}"
        raise PresetError(msg)
    return {str(k): str(v) for k, v in data.items()}


def verify_approved(root: Path) -> list[str]:
    """Check every approved preset against the lock. Returns problems (empty = OK)."""
    problems: list[str] = []
    locked = read_lock(root)
    current = build_lock(root)

    for rel_path, digest in current.items():
        if rel_path not in locked:
            problems.append(
                f"{rel_path}: preset is approved but not recorded in {LOCK_FILENAME} "
                "(run `deepdub-qc presets lock` in a reviewed commit)"
            )
        elif locked[rel_path] != digest:
            problems.append(
                f"{rel_path}: approved preset content changed "
                "(approved versions are immutable - create a new version)"
            )

    for rel_path in locked:
        if rel_path not in current:
            path = root / rel_path
            if not path.is_file():
                problems.append(
                    f"{rel_path}: locked as approved but the file is missing "
                    "(approved presets may be deprecated, never deleted)"
                )
            else:
                problems.append(
                    f"{rel_path}: locked as approved but no longer has approved status "
                    "(deprecate and supersede instead of demoting)"
                )
    return problems
