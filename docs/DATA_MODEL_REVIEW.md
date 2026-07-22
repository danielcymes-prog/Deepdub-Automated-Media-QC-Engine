# Data Model Review (Phase 0)

Validation of the schemas in handoff §§8–12 against the product goals. Verdict: the split into Measurement / Rule / Finding / Evidence / Report is correct and should be kept exactly as designed. The issues below should be resolved **before** M1 model implementation, because each one is a breaking schema change if discovered later.

## Required changes

**1. Separate rule identity from parameter identity (ADR-009).**
`check_id` currently serves as both the rule's identity and the parameter reference. This makes it impossible to define two rules on the same parameter — e.g., loudness on the dubbed dialogue stream vs. the M&E stem, or different silence thresholds per language track. For a dubbing company this is not an edge case; it is the main case.
Change: rules get `rule_id` (unique in preset) + `parameter_id` (from the catalogue). Findings carry both.

**2. Add stream selectors to rules.**
Measurements have `stream_index`, but rules have no way to say which stream they target, or how to quantify over streams ("every audio stream is 48 kHz" vs "at least one stream has language=deu"). Proposed `applies_to`:

```yaml
applies_to:
  stream_type: audio          # audio | video | subtitle | container
  selector: { language: deu } # or { index: 1 }, or all
  quantifier: all             # all | any | exactly_one
```

Default (`applies_to` omitted): container/file scope, current behavior. Selector resolution failures produce `SKIPPED` findings with a reason, never silent passes.

**3. Define the determinism contract in the schema (ADR-008).**
Random UUIDs and timestamps contradict "identical canonical findings." Enumerate volatile fields; derive `measurement_id`/`finding_id` as UUIDv5 of stable content. Add to `QCResult`:

```json
"environment": {
  "ffmpeg_version": "7.1",
  "ffprobe_version": "7.1",
  "platform": "linux/amd64",
  "docker_image": "deepdub-qc:0.1.0"
}
```

**4. Record the preset file hash, not just its version.**
`preset_version` is self-declared and mutable while a preset is in `draft`. Add `preset.sha256` to `QCResult` so every report is traceable to exact preset bytes.

**5. Formalize per-operator `expected` shapes.**
`expected` is currently free-form (`{value}`, `{min,max}`, `{values}`, `{pattern, tolerance…}`). Model it as a discriminated union keyed by `operator`, both in Pydantic and in the exported JSON Schema. Otherwise preset validation cannot catch `between` without `min`, `regex` with an invalid pattern, etc., and the rule engine fills with defensive branching.

**6. Define an Evidence schema.**
Evidence is described (§7.4) but has no schema. Minimum:

```json
{
  "evidence_id": "…", "finding_id": "…", "type": "thumbnail|waveform|clip|raw",
  "path": "evidence/thumbnails/…", "start_seconds": 252.0, "end_seconds": null,
  "generated_by": "evidence.thumbnails/1.0.0", "sha256": "…"
}
```

**7. Pin the status semantics.**
`QCStatus` has both `SKIPPED` and `NOT_APPLICABLE`; define them once:
`NOT_APPLICABLE` = rule disabled, or `applies_to` matches nothing *by design* (e.g., subtitle rules on a file with no subtitle requirement). `SKIPPED` = required measurement unavailable though expected (upstream detector didn't run). Detector crash on an enabled rule ⇒ `ERROR`. Aggregation stays as handoff §17.3, with `SKIPPED` of an enabled blocking rule escalating to `ERROR` — a QC tool must not pass a file it failed to inspect.

**8. Canonical time is seconds; timecodes are derived.**
Store `start_seconds`/`end_seconds` as canonical (Decimal or float with documented precision). `start_timecode` is render-derived using the asset frame rate; store the frame rate used for derivation in `media_summary`. Rational frame rates (24000/1001) must be preserved as rationals in measurements, with float only at comparison time (`approximately_equals` tolerance).

## Acceptable as specified

- `Measurement.value` polymorphism (str/int/float/bool/list/object) — implement as a constrained `JsonValue`; the exported JSON Schema uses `oneOf`.
- `confidence` — keep, but fixed at 1.0 for deterministic detectors; documented as reserved for future heuristic detectors (letterboxing, corrupt-frame).
- Enums in §8 — sufficient. Add members only via minor schema version.
- Job result envelope (§11) — sound, with additions from items 3–4.

## Missing but deliberately deferred

- DB schema (§24): deferred with storage to Phase 7 (ADR-005). The "measurements independent from findings" rule is already honored by the model split.
- `ai_summary` structure (§25): schema-stub it in M1 (so the report layout reserves the slot) but implement in M9.
- Subtitle and Deepdub-specific parameters: catalogue entries exist; no schema work needed until their detectors are scheduled.
