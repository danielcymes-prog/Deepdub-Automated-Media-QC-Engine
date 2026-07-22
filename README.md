# Deepdub QC Engine

Automated media quality-control engine: deterministic media analysis, rule
evaluation, and QC reporting for localization and dubbing deliveries.

> AI explains. Software measures. Rules decide.

Media analysis is always deterministic and reproducible. AI may summarize and
explain findings, but never produces measurements or pass/fail decisions.

## Status

Milestone 2 (report-first prototype). Domain models, preset engine, CLI,
schemas, CI, and JSON/HTML/PDF report rendering from a mock result.
Detectors and the rule engine land in M3 — see `docs/ROADMAP.md`.

Render the mock report for stakeholder review:

```bash
uv run deepdub-qc render-mock --output reports/mock
```

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg (from M3 onward; the Docker image ships a pinned version)

## Quick start

```bash
uv sync                                   # install
uv run deepdub-qc --help
uv run deepdub-qc version
uv run deepdub-qc presets validate presets/examples/generic_broadcast_v1.yaml
```

## Exit codes

Stable, machine-readable contract for pipeline automation. Never renumbered.

| Code | Meaning |
|------|---------|
| 0 | QC completed, overall status PASS |
| 1 | QC completed with WARNING |
| 2 | QC completed with FAIL |
| 3 | QC execution ERROR |
| 4 | Invalid preset or configuration |
| 5 | Invalid input or unreadable media |
| 6 | Internal application error |

## Development

```bash
make check     # format check + lint + type check + tests
make fmt       # auto-format
make schemas   # regenerate JSON schemas from the Pydantic models
make docker    # build the canonical execution image
```

Every PR must pass `make check` and the schema drift check in CI.

## Project layout

```text
docs/          Architecture, ADRs, roadmap, backlog, risks, data-model review
presets/       Versioned YAML client presets (data, never code)
schemas/       JSON Schemas exported from the Pydantic models (generated)
scripts/       Development utilities (schema export, ...)
src/deepdub_qc Domain models, preset engine, CLI, utilities
tests/         Unit tests (integration and golden tests arrive with M3)
```

## Documentation

- `docs/ARCHITECTURE.md` — system design, module boundaries, data flow
- `docs/DECISIONS.md` — architecture decision records
- `docs/ROADMAP.md` — milestones and acceptance criteria
- `docs/BACKLOG.md` — prioritized engineering backlog
- `docs/RISKS.md` — risk register
- `DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md` — original build specification
