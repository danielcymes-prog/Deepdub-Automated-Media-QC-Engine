"""Preset catalog: what the GUI picker and /api/v1/presets serve.

Why: the GUI never parses YAML itself (spec section 3.1) - it consumes this
catalog, built with the same loader/validator the pipeline uses (ADR-003).

Inputs: a presets root directory. Outputs: PresetInfo entries.
Side effects: none (reads files).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from deepdub_qc.exceptions import PresetError, preset_error_detail
from deepdub_qc.presets.governance import discover_presets
from deepdub_qc.presets.loader import load_preset

logger = logging.getLogger(__name__)


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
    #: Unlisted presets (the imported Vidchecker library) stay out of the
    #: submit picker but remain fully loadable - watch folders, the API and
    #: shadow-validation runs can still target them (master-preset-spec §4).
    listed: bool = True


def build_catalog(presets_root: Path) -> list[PresetInfo]:
    """All loadable presets under the root, sorted by client then title.

    Presets that fail validation are skipped (they cannot be submitted
    anyway) and logged HERE, at the swallow point: an unloadable preset
    otherwise vanishes from the picker and /api/v1/presets with no trace,
    and the loader's actionable message (including its did-you-mean
    parameter suggestions) is discarded.
    """
    entries = []
    for path in discover_presets(presets_root):
        try:
            preset = load_preset(path)
        except PresetError as exc:
            logger.warning(
                "preset skipped from catalog: %s failed to load: %s",
                path,
                preset_error_detail(exc),
            )
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
                listed=path.relative_to(presets_root).parts[0] != "library",
            )
        )
    return sorted(entries, key=lambda e: (e.client, e.title, e.version))


#: The masters' client value; their picker group is pinned first (spec section 4).
MASTER_CLIENT = "deepdub"


def version_key(version: str) -> tuple[int, ...]:
    """Numeric ordering for dotted versions ('1.10.0' sorts above '1.9.0')."""
    return tuple(int(part) for part in version.split("."))


def split_current(
    catalog: list[PresetInfo],
) -> tuple[list[PresetInfo], dict[str, list[PresetInfo]]]:
    """(newest version of each preset id, superseded versions keyed by id).

    The GUI treats a preset as one thing with a history, not as peer rows per
    version: only the newest version is a row or a picker option (ADR-033).
    Superseded versions are never deleted - report.json cites the exact
    version that judged a file (ADR-013) - they are just presented as history,
    newest first, and stay loadable by the API and watch folders.
    """
    newest: dict[str, PresetInfo] = {}
    for entry in catalog:
        held = newest.get(entry.preset_id)
        if held is None or version_key(entry.version) > version_key(held.version):
            newest[entry.preset_id] = entry
    current = [entry for entry in catalog if newest[entry.preset_id] is entry]
    history: dict[str, list[PresetInfo]] = {}
    for entry in catalog:
        if newest[entry.preset_id] is not entry:
            history.setdefault(entry.preset_id, []).append(entry)
    for versions in history.values():
        versions.sort(key=lambda e: version_key(e.version), reverse=True)
    return current, history


def picker_groups(catalog: list[PresetInfo]) -> list[tuple[str, list[PresetInfo]]]:
    """Listed presets grouped by client for the submit picker, masters first.

    Only each preset's newest version is offered: a superseded draft is
    history, not a choice an operator should be able to make by accident.
    """
    current, _ = split_current(catalog)
    groups: dict[str, list[PresetInfo]] = {}
    for entry in current:
        if entry.listed:
            groups.setdefault(entry.client, []).append(entry)
    return sorted(groups.items(), key=lambda kv: (kv[0] != MASTER_CLIENT, kv[0]))


def find_preset(catalog: list[PresetInfo], preset_id: str, version: str) -> PresetInfo | None:
    for entry in catalog:
        if entry.preset_id == preset_id and entry.version == version:
            return entry
    return None
