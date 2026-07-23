"""Preset catalog: what the GUI picker and /api/v1/presets serve.

Why: the GUI never parses YAML itself (spec section 3.1) - it consumes this
catalog, built with the same loader/validator the pipeline uses (ADR-003).

Inputs: a presets root directory. Outputs: PresetInfo entries.
Side effects: none (reads files).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deepdub_qc.exceptions import PresetError
from deepdub_qc.presets.governance import discover_presets
from deepdub_qc.presets.loader import load_preset


@dataclass(frozen=True)
class PresetInfo:
    """One selectable preset (metadata only; rules stay in the pipeline)."""

    preset_id: str
    version: str
    client: str
    content_type: str
    status: str
    title: str
    description: str
    effective_date: str
    path: Path


def build_catalog(presets_root: Path) -> list[PresetInfo]:
    """All loadable presets under the root, sorted by client then title.

    Presets that fail validation are skipped (they cannot be submitted
    anyway); the caller logs them.
    """
    entries = []
    for path in discover_presets(presets_root):
        try:
            preset = load_preset(path)
        except PresetError:
            continue
        meta = preset.preset
        entries.append(
            PresetInfo(
                preset_id=meta.id,
                version=str(meta.version),
                client=meta.client,
                content_type=meta.content_type,
                status=meta.status.value,
                title=meta.title,
                description=meta.description,
                effective_date=str(meta.effective_date),
                path=path,
            )
        )
    return sorted(entries, key=lambda e: (e.client, e.title, e.version))


def find_preset(catalog: list[PresetInfo], preset_id: str, version: str) -> PresetInfo | None:
    for entry in catalog:
        if entry.preset_id == preset_id and entry.version == version:
            return entry
    return None
