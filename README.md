# Deepdub QC Engine

Automated media quality-control engine: deterministic media analysis, rule
evaluation, and QC reporting for localization and dubbing deliveries.

> AI explains. Software measures. Rules decide.

Media analysis is always deterministic and reproducible. AI may summarize and
explain findings, but never produces measurements or pass/fail decisions.

## Status

Milestone 6.5 (local server + operator GUI). All three check tiers run end to
end (metadata, audio, video incidents with thumbnail evidence); client presets
are governed — `deepdub-qc presets validate` accepts directories, approved
presets are locked immutable via `presets/approved.lock.json` (ADR-013,
CI-enforced), and the first real client presets, translated from production
Vidchecker "Delivery" templates, live under `presets/clients/` in draft status
pending threshold approval. `deepdub-qc serve` provides the operator web
console (ADR-014).

M7 service extraction and Composer integration come **after** M6.5 — Composer
is deliberately the final step. See `docs/ROADMAP.md`.

Every rule's `parameter_id` is validated against the parameter catalogue at
load time (ADR-021), so a typo is a validation error rather than a check that
silently never runs. See `docs/parameter-catalogue.md` for what can be
measured.

Preset governance:

```bash
uv run deepdub-qc presets validate presets   # schema + invariants, all presets
uv run deepdub-qc presets verify presets     # approved presets unmodified?
uv run deepdub-qc presets lock presets       # record approvals (reviewed commit)
```

Analyze a file:

```bash
uv run deepdub-qc analyze \
  --input /path/to/delivery.mov \
  --preset presets/examples/generic_broadcast_v1.yaml \
  --output reports/job_001
```

Analyze a whole directory (one job per file + `batch_summary.json`; exit
code is the worst individual result):

```bash
uv run deepdub-qc batch \
  --input-dir /path/to/season_deliveries \
  --preset presets/clients/marimba/delivery_v1.yaml \
  --output-dir reports/season_08
```

Compare against a Vidchecker XML report of the same file (parity harness;
refuses to compare different bytes):

```bash
uv run deepdub-qc compare \
  --report reports/job_001/report.json \
  --vidchecker /path/to/vidchecker_export.xml
```

Run the operator web console (Phase 3.5 — submit jobs, watch the queue,
open reports from a browser):

```bash
cp config/server.example.yaml server.yaml   # edit media_roots + tool paths
uv run deepdub-qc serve --config server.yaml
# open http://127.0.0.1:8571
```

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- FFmpeg (from M3 onward; the Docker image ships a pinned version)

Optional, for local PDF rendering: WeasyPrint binds Pango/Cairo natively, and
those libraries are not present by default on macOS. Without them the PDF
renderer test skips (`brew install pango`; Debian: `libpango-1.0-0
libpangoft2-1.0-0`). The Docker image installs them, and the Windows deployment
target uses Playwright instead (ADR-014), so this affects local development only.

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

On a delivery host, install runtime dependencies only:

```bash
uv sync --frozen --no-dev
uv run --no-dev deepdub-qc serve --config server.yaml
```

`--no-dev` omits the `dev` and `lint` groups. Test and lint tooling must never
be in the dependency path of the service — see `docs/windows-deployment.md`.

```bash
make check       # format check + lint + type check + layering + tests
make fmt         # auto-format
make layers      # import-linter: the ARCHITECTURE section 4 contracts
make schemas     # regenerate JSON schemas from the Pydantic models
make params      # regenerate the parameter catalogue artifacts
make docker      # build the canonical execution image
make docker-test # run the full suite inside the pinned image (canonical)
make pin-ffmpeg  # print the FFmpeg version the pinned base resolves to
make js-tests    # console client-side behaviour in jsdom (needs Node; ADR-023)
```

Every PR must pass `make check`, the schema and parameter-catalogue drift
checks, and `make docker-test` in CI.

### Determinism

The canonical execution environment is the Docker image (ADR-008, ADR-022):
base pinned by digest, FFmpeg version declared in `environment.lock` and
asserted at build time. Integration tests run inside it, so
`test_repeat_runs_identical_modulo_volatile_fields` verifies reproducibility on
the toolchain we ship. Setting `DEEPDUB_QC_REQUIRE_TOOLCHAIN=1` turns a missing
FFmpeg into a hard failure instead of a silent skip.

Upgrading FFmpeg is a release event: edit `environment.lock`, re-run the golden
corpus, and add a `docs/VALIDATION.md` entry (`docs/RISKS.md` R1).

## Project layout

```text
docs/            Architecture, ADRs, roadmap, backlog, risks, parameter catalogue
presets/         Versioned YAML client presets (data, never code)
schemas/         Generated from the Pydantic models: JSON Schemas + parameter registry
scripts/         Development utilities (schema/parameter export, test media)
src/deepdub_qc   Domain models, detectors, rule engine, reports, server, CLI
tests/           Unit, integration, and golden tests
environment.lock The pinned canonical toolchain (ADR-022)
```

## Documentation

- `docs/ARCHITECTURE.md` — system design, module boundaries, data flow
- `docs/DECISIONS.md` — architecture decision records
- `docs/parameter-catalogue.md` — every measurable parameter (generated)
- `docs/VALIDATION.md` — Vidchecker parity and EBU conformance evidence
- `docs/ROADMAP.md` — milestones and acceptance criteria
- `docs/BACKLOG.md` — prioritized engineering backlog
- `docs/RISKS.md` — risk register
- `DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md` — original build specification
