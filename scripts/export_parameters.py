"""Export the parameter catalogue to documentation and machine-readable form (ADR-021).

`deepdub_qc.models.parameters` is the canonical source. This script renders it
to `docs/parameter-catalogue.md` (for preset authors and report readers) and
`schemas/parameter-catalogue.json` (for tooling and, later, a Composer preset
editor). Handoff section 15 requires both.

Follows the ADR-004 export-and-diff pattern: CI runs this with --check and
fails if the committed artifacts have drifted from the models.

Usage:
    python scripts/export_parameters.py          # write both artifacts
    python scripts/export_parameters.py --check  # exit 1 on drift, write nothing
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from deepdub_qc.models.enums import Category
from deepdub_qc.models.parameters import (
    CATALOGUE,
    ImplementationStatus,
    ParameterDefinition,
    ValidationStatus,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_TARGET = REPO_ROOT / "docs" / "parameter-catalogue.md"
JSON_TARGET = REPO_ROOT / "schemas" / "parameter-catalogue.json"

#: Category order in the rendered document, matching handoff section 15.
CATEGORY_ORDER: tuple[Category, ...] = (
    Category.FILE,
    Category.CONTAINER,
    Category.VIDEO,
    Category.AUDIO,
    Category.SUBTITLE,
    Category.METADATA,
    Category.DEEPDUB,
)

CATEGORY_TITLES: dict[Category, str] = {
    Category.FILE: "File",
    Category.CONTAINER: "Container",
    Category.VIDEO: "Video",
    Category.AUDIO: "Audio",
    Category.SUBTITLE: "Subtitle and caption",
    Category.METADATA: "Metadata",
    Category.DEEPDUB: "Deepdub workflow",
}

_STATUS_LABEL = {
    ValidationStatus.VALIDATED: "validated",
    ValidationStatus.CROSS_CHECKED: "cross-checked",
    ValidationStatus.UNVALIDATED: "—",
}


def _cell(value: str | None) -> str:
    """Render an optional value for a markdown table cell, escaping pipes."""
    if not value:
        return "—"
    return value.replace("|", "\\|")


def _scope(definition: ParameterDefinition) -> str:
    parts = ["stream" if definition.stream_scoped else "file"]
    if definition.timestamped:
        parts.append("timed")
    return ", ".join(parts)


def render_markdown() -> str:
    """Render the catalogue as a document organized by category."""
    by_category: dict[Category, list[ParameterDefinition]] = defaultdict(list)
    for definition in CATALOGUE.values():
        by_category[definition.category].append(definition)

    implemented = sum(
        1 for d in CATALOGUE.values() if d.implementation is ImplementationStatus.IMPLEMENTED
    )

    lines = [
        "# Parameter Catalogue",
        "",
        "<!-- GENERATED FILE — do not edit by hand.",
        "     Source: src/deepdub_qc/models/parameters.py",
        "     Regenerate: make params   (CI fails on drift) -->",
        "",
        "The vocabulary of measurable facts. A `parameter_id` is the contract "
        "between a detector, which produces measurements, and a preset, which "
        "writes rules about them (ADR-021).",
        "",
        f"**{implemented} implemented**, {len(CATALOGUE) - implemented} planned, "
        f"{len(CATALOGUE)} catalogued in total.",
        "",
        "## How to read this",
        "",
        "- **Implemented** parameters are produced by a detector today. A preset "
        "may only reference these; `deepdub-qc presets validate` rejects "
        "anything else, with a suggestion for near-misses.",
        "- **Planned** parameters are agreed facts we intend to measure "
        "(handoff section 15). They are catalogued so the intent is reviewable, "
        "but a rule referencing one is a validation error, not a silent skip.",
        "- **Scope** `file` means one measurement per asset; `stream` means one "
        "per stream, carrying a `stream_index` that rule selectors can target. "
        "`timed` means the parameter is event-style: one measurement per "
        "occurrence, carrying start and end seconds.",
        "- **Accuracy** is deliberately conservative. `validated` means checked "
        "against a specification or reference test set; `cross-checked` means "
        "compared with another tool on identical bytes where the definitions "
        "differ. Everything else is blank: implemented and unit-tested says "
        "nothing about agreement with a broadcast meter. See "
        "`docs/VALIDATION.md`.",
        "- **Caveats** are binding on preset authors. A threshold written "
        "without reading them may not mean what the author intends.",
        "",
    ]

    for category in CATEGORY_ORDER:
        definitions = sorted(by_category.get(category, []), key=lambda d: d.parameter_id)
        if not definitions:
            continue

        lines += [
            f"## {CATEGORY_TITLES[category]}",
            "",
            "| Parameter | Name | Type | Unit | Scope | Detector | Accuracy | Description |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for definition in definitions:
            implemented_here = definition.implementation is ImplementationStatus.IMPLEMENTED
            detector = _cell(definition.detector_id) if implemented_here else "*planned*"
            lines.append(
                f"| `{definition.parameter_id}` "
                f"| {_cell(definition.display_name)} "
                f"| {definition.data_type.value} "
                f"| {_cell(definition.unit)} "
                f"| {_scope(definition)} "
                f"| {detector} "
                f"| {_STATUS_LABEL[definition.validation]} "
                f"| {_cell(definition.description)} |"
            )
        lines.append("")

        caveats = [d for d in definitions if d.limitations]
        if caveats:
            lines += [f"### {CATEGORY_TITLES[category]} caveats", ""]
            lines += [f"- `{d.parameter_id}` — {d.limitations}" for d in caveats]
            lines.append("")

    return "\n".join(lines)


def render_json() -> str:
    """Render the catalogue as a stable, sorted JSON registry."""
    payload = {
        "$comment": (
            "Generated from src/deepdub_qc/models/parameters.py — do not edit by "
            "hand. Regenerate with `make params`."
        ),
        "parameters": [
            CATALOGUE[key].model_dump(mode="json", exclude_none=False) for key in sorted(CATALOGUE)
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    artifacts = ((MARKDOWN_TARGET, render_markdown()), (JSON_TARGET, render_json()))
    drifted: list[str] = []

    for target, content in artifacts:
        if check:
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                drifted.append(str(target.relative_to(REPO_ROOT)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if check and drifted:
        print(
            "parameter catalogue drift detected (run `make params` and commit): "
            + ", ".join(drifted),
            file=sys.stderr,
        )
        return 1
    if check:
        print("parameter catalogue up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
