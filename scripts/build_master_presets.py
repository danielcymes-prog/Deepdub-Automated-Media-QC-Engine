#!/usr/bin/env python3
"""Synthesize the two Master Presets from the preset corpus (ADR-030).

Why: operators work from one well-known master per content type, not from 53
imported Vidchecker templates (docs/master-preset-spec.md). This script derives
`master_video` and `master_audio` from the imported library plus the
hand-refined client presets:

- every distinct IMPLEMENTED check (parameter) in the corpus becomes one rule;
- the most common (operator, expected, scope) variant wins; every variant the
  corpus contains is listed in a comment above the rule with its count, so the
  approving engineer reviews the spread, not just the winner (handoff section
  30 - thresholds are human decisions; the masters ship as DRAFT);
- severity/blocking follow the corpus majority (the importer already encoded
  Vidchecker's RejectOnError as blocking-vs-warning).

Never overwrites an existing master without --force (same contract as
import_vidchecker_templates.py): a master that has been hand-edited or
version-bumped must not be silently regenerated.

Inputs: presets/library/vidchecker/*.yaml + presets/clients/**/*.yaml.
Outputs: presets/master/master_{video,audio}_v1.yaml (validated via the real
loader before this script exits 0). Side effects: writes those two files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from deepdub_qc.presets.loader import load_preset  # noqa: E402

CORPUS_DIRS = ("presets/library/vidchecker", "presets/clients")
OUTPUT_DIR = REPO_ROOT / "presets" / "master"

#: Rule emission order: container facts first, then picture, then sound.
_SECTION_ORDER = {"container": 0, "video": 1, "audio": 2}


@dataclass(frozen=True)
class Occurrence:
    """One rule as it appears in one corpus preset (defaults resolved)."""

    rule_id: str
    parameter_id: str
    operator: str
    expected: dict[str, Any] | None
    applies_to: dict[str, Any] | None
    display_name: str
    description: str | None
    severity: str
    blocking: bool


def load_corpus() -> list[dict[str, Any]]:
    documents = []
    for rel in CORPUS_DIRS:
        for path in sorted((REPO_ROOT / rel).rglob("*.yaml")):
            documents.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return documents


def classify(document: dict[str, Any]) -> str:
    """'video' if the preset checks any picture parameter, else 'audio'."""
    for rule in document.get("rules", []):
        if str(rule.get("parameter_id", "")).startswith("video."):
            return "video"
    return "audio"


def occurrences_of(document: dict[str, Any]) -> list[Occurrence]:
    defaults = document.get("defaults", {})
    default_severity = defaults.get("severity", "error")
    default_blocking = bool(defaults.get("blocking", True))
    resolved = []
    for rule in document.get("rules", []):
        resolved.append(
            Occurrence(
                rule_id=rule["rule_id"],
                parameter_id=rule["parameter_id"],
                operator=rule.get("operator", "not_exists"),
                expected=rule.get("expected"),
                applies_to=rule.get("applies_to"),
                display_name=rule.get("display_name", rule["rule_id"]),
                description=rule.get("description"),
                severity=rule.get("severity", default_severity),
                blocking=bool(rule.get("blocking", default_blocking)),
            )
        )
    return resolved


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _variant_key(occ: Occurrence) -> str:
    return _canon({"op": occ.operator, "expected": occ.expected, "applies": occ.applies_to})


def _plain(value: Any) -> Any:
    """Integral floats print as ints so -26.0 and -26 read as one variant."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _describe_variant(occ: Occurrence) -> str:
    expected = occ.expected or {}
    unit = expected.get("unit")
    if "min" in expected or "max" in expected:
        body = f"{_plain(expected.get('min'))}..{_plain(expected.get('max'))}"
    elif "value" in expected:
        body = _canon(_plain(expected["value"]))
    else:
        body = ""
    text = f"{occ.operator} {body}".strip()
    return f"{text} {unit}".strip() if unit else text


def synthesize(corpus: list[dict[str, Any]]) -> list[tuple[Occurrence, list[str]]]:
    """One winning rule per parameter + the corpus value distribution comment."""
    by_parameter: dict[str, list[Occurrence]] = defaultdict(list)
    for document in corpus:
        for occ in occurrences_of(document):
            by_parameter[occ.parameter_id].append(occ)

    rules = []
    for parameter_id in sorted(
        by_parameter,
        key=lambda p: (_SECTION_ORDER.get(p.split(".")[0], 9), p),
    ):
        occs = by_parameter[parameter_id]
        variants = Counter(_variant_key(o) for o in occs)
        # Deterministic winner: highest count, then lexical key.
        winner_key, _ = sorted(variants.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        winner_occs = [o for o in occs if _variant_key(o) == winner_key]

        def majority(values: list[Any]) -> Any:
            counted = Counter(_canon(v) for v in values)
            top = sorted(counted.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            return json.loads(top)

        template = winner_occs[0]
        # Severity and blocking travel as a PAIR: independent majorities can
        # combine into a (severity, blocking) no corpus preset actually has.
        severity, blocking = majority([[o.severity, o.blocking] for o in occs])
        chosen = Occurrence(
            rule_id=majority([o.rule_id for o in winner_occs]),
            parameter_id=parameter_id,
            operator=template.operator,
            expected=template.expected,
            applies_to=template.applies_to,
            display_name=majority([o.display_name for o in winner_occs]),
            description=next((o.description for o in winner_occs if o.description), None),
            severity=severity,
            blocking=blocking,
        )
        # The comment aggregates by human-visible description, not by raw
        # variant key: variants that differ only in scope or int/float repr
        # would otherwise print as identical "x1" lines - noise, not signal.
        distribution = []
        described = Counter(_describe_variant(o) for o in occs)
        if len(described) > 1:
            ordered = sorted(described.items(), key=lambda kv: (-kv[1], kv[0]))
            distribution = [f"{text} x{count}" for text, count in ordered[:8]]
            if len(ordered) > 8:
                distribution.append(f"...and {len(ordered) - 8} more variants")
        rules.append((chosen, distribution))

    # rule_id uniqueness: majority ids can collide across parameters.
    seen: dict[str, int] = {}
    unique = []
    for chosen, distribution in rules:
        rule_id = chosen.rule_id
        if rule_id in seen:
            seen[rule_id] += 1
            rule_id = f"{rule_id}-{seen[chosen.rule_id]}"
        else:
            seen[rule_id] = 1
        unique.append((Occurrence(**{**chosen.__dict__, "rule_id": rule_id}), distribution))
    return unique


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def _emit_rule(occ: Occurrence, distribution: list[str]) -> list[str]:
    lines = []
    for note in distribution:
        prefix = "  # corpus values: " if note is distribution[0] else "  #                "
        lines.append(f"{prefix}{note}")
    lines.append(f"  - rule_id: {occ.rule_id}")
    lines.append(f"    parameter_id: {occ.parameter_id}")
    lines.append(f"    operator: {occ.operator}")
    if occ.expected is not None:
        lines.append("    expected:")
        for key in ("value", "values", "min", "max", "tolerance", "unit"):
            if key in occ.expected:
                value = occ.expected[key]
                if isinstance(value, list):
                    rendered = "[" + ", ".join(_scalar(v) for v in value) + "]"
                    lines.append(f"      {key}: {rendered}")
                else:
                    lines.append(f"      {key}: {_scalar(value)}")
    if occ.applies_to:
        lines.append("    applies_to:")
        for key in ("stream_type", "quantifier"):
            if key in occ.applies_to:
                lines.append(f"      {key}: {occ.applies_to[key]}")
    lines.append(f"    display_name: {_scalar(occ.display_name)}")
    if occ.description:
        lines.append(f"    description: {_scalar(occ.description)}")
    lines.append(f"    severity: {occ.severity}")
    lines.append(f"    blocking: {'true' if occ.blocking else 'false'}")
    return lines


def render_master(  # noqa: PLR0913 - one argument per preset identity field
    preset_id: str,
    title: str,
    content_type: str,
    corpus_size: int,
    rules: list[tuple[Occurrence, list[str]]],
    generated_on: str,
) -> str:
    lines = [
        f"# {title} - synthesized from {corpus_size} corpus presets by",
        "# scripts/build_master_presets.py (docs/master-preset-spec.md section 3).",
        "#",
        "# Each rule carries the most common corpus value; where the corpus",
        "# disagrees, the full distribution is in the comment above the rule.",
        "#",
        "# ALL THRESHOLDS ARE PLACEHOLDERS PENDING HUMAN APPROVAL (handoff section 30).",
        "schema_version: 1.0.0",
        "",
        "preset:",
        f"  id: {preset_id}",
        "  version: 1.0.0",
        "  client: deepdub",
        f"  content_type: {content_type}",
        f"  title: {_scalar(title)}",
        "  description: "
        + json.dumps(
            f"The single editable baseline for {content_type.replace('_', ' ')} QC. "
            f"Defaults synthesized from {corpus_size} presets (Vidchecker library + "
            "client presets); the per-rule comments show the corpus value spread. "
            "Draft until the post-production engineer approves the defaults.",
            ensure_ascii=False,
        ),
        "  owner: media-operations",
        "  status: draft",
        f"  effective_date: {generated_on}",
        "",
        "defaults:",
        "  blocking: true",
        "  severity: error",
        "",
        "rules:",
    ]
    for index, (occ, distribution) in enumerate(rules):
        if index:
            lines.append("")
        lines.extend(_emit_rule(occ, distribution))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing masters")
    args = parser.parse_args()

    corpus = load_corpus()
    generated_on = datetime.now(UTC).date().isoformat()
    targets = {
        "video": ("master_video", "Master - Video Delivery", "av_delivery"),
        "audio": ("master_audio", "Master - Audio Delivery", "dubbed_audio_delivery"),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for kind, (preset_id, title, content_type) in targets.items():
        subset = [d for d in corpus if classify(d) == kind]
        rules = synthesize(subset)
        output = OUTPUT_DIR / f"{preset_id}_v1.yaml"
        if output.exists() and not args.force:
            print(f"REFUSING to overwrite {output} (use --force)")
            return 1
        output.write_text(
            render_master(preset_id, title, content_type, len(subset), rules, generated_on),
            encoding="utf-8",
        )
        load_preset(output)  # fail loudly if the synthesis emitted invalid YAML
        print(
            f"wrote {output.relative_to(REPO_ROOT)}: {len(rules)} rules from {len(subset)} presets"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
