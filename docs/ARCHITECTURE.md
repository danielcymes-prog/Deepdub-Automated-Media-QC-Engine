# Deepdub QC Engine — Architecture

Status: current as of 2026-07-26 (M1–M6 delivered, M6.5 local server and operator GUI functionally complete). Companion documents: `DECISIONS.md` (why), `ROADMAP.md` (when), `RISKS.md` (what could go wrong), `DATA_MODEL_REVIEW.md` (schema validation), `parameter-catalogue.md` (what can be measured).

Governing principle:

> AI explains. Software measures. Rules decide.

---

## 1. System Overview

```text
                        ┌─────────────────────────────────────────────┐
                        │                 Entry Points                │
                        │   CLI (Typer)   →   REST API (FastAPI, P7)  │
                        └──────────────────────┬──────────────────────┘
                                               │ QCJobRequest
                                               ▼
┌───────────────┐              ┌──────────────────────────────┐
│ Preset Engine │─ QCPreset ──▶│      Orchestration           │
│ load/validate │              │  pipeline · job context      │
└───────────────┘              └──────┬───────────────┬───────┘
                                      │               │
                                      ▼               ▼
                          ┌────────────────┐  ┌────────────────┐
                          │ Detector Engine│  │ Evidence Engine│
                          │ ffprobe/ffmpeg │  │ thumbs/waves   │
                          └───────┬────────┘  └───────┬────────┘
                                  │ Measurements       │ Evidence
                                  ▼                    │
                          ┌────────────────┐           │
                          │  Rule Engine   │           │
                          │ operators only │           │
                          └───────┬────────┘           │
                                  │ Findings           │
                                  ▼                    ▼
                          ┌──────────────────────────────┐
                          │        Report Engine         │
                          │ JSON (canonical) → HTML/PDF  │
                          └───────┬──────────────────────┘
                                  │ QCResult (JSON = source of truth)
                                  ▼
                          ┌──────────────────────────────┐
                          │   Storage (job directory)    │
                          │   filesystem now, DB in P7   │
                          └──────────────────────────────┘

              AI layer (Phase 9, off by default): consumes QCResult,
              produces explanations stored SEPARATELY from canonical output.
```

---

## 2. Subsystem Responsibilities

| Subsystem | Responsibility | Explicitly NOT responsible for |
|---|---|---|
| **CLI** (`cli.py`) | Argument parsing, exit codes, human console output | Any QC logic; it only calls orchestration |
| **Server** (`server/`, ADR-014) | Local FastAPI service: job queue (SQLite, orchestration state only), single background worker, operator GUI, artifact serving | Any QC logic, thresholds, or report content; it submits jobs and displays what the pipeline produced |
| **Comparison** (`comparison/`) | Parse third-party QC reports (Vidchecker XML) and diff them against our canonical result for parity evidence | Producing measurements or verdicts of its own |
| **Orchestration** (`orchestration/`) | Job lifecycle, pipeline sequencing, job context, output directory layout | Measuring, evaluating, rendering |
| **Preset Engine** (`presets/`) | Load, schema-validate, and version YAML presets | Knowing how detectors work |
| **Detector Engine** (`detectors/`) | Run tools (ffprobe/ffmpeg), parse output, emit normalized `Measurement`s, preserve raw output | Pass/fail decisions, thresholds, client knowledge |
| **Rule Engine** (`rules/`) | Evaluate measurements against preset rules with generic operators; emit `Finding`s; aggregate overall status | How measurements were produced; rendering |
| **Evidence Engine** (`evidence/`) | Generate thumbnails/waveforms/clips for timestamped findings | Deciding what failed |
| **Report Engine** (`reports/`) | Build canonical `QCResult` JSON; render HTML/PDF from it | Computing or altering findings |
| **Models** (`models/`) | Pydantic domain models, the parameter catalogue (ADR-021), and exported JSON Schemas; the shared vocabulary | Behavior |
| **Storage** (`storage/`, deferred to P7) | Persist jobs/results behind a repository interface | Being required by the MVP (filesystem job dir suffices) |
| **Utilities** (`utils/`) | Safe subprocess, timecode math, hashing, path safety | Domain logic |
| **AI layer** (Phase 9) | Explain, summarize, suggest remediation, draft presets | Measurements, findings, thresholds, approval |

---

## 3. Data Flow

```text
input file + preset path
  → Preset Engine: parse YAML → validate schema + semver → QCPreset
  → Orchestration: create job (job_id, output dir, hash input file)
  → Detector Engine: select applicable detectors from rule set
       → run tools with timeouts, no shell → raw output saved to raw/
       → parse → list[Measurement]
  → Rule Engine: for each enabled rule
       → find measurement(s) by parameter_id + stream selector
       → apply operator → Finding (PASS/WARNING/FAIL/SKIPPED/ERROR)
       → aggregate → overall status
  → Evidence Engine: for timestamped findings → evidence/ artifacts
  → Report Engine: assemble QCResult → report.json
       → render report.html (Jinja2) → report.pdf (WeasyPrint)
  → CLI: map overall status → documented exit code
```

Key invariants:

1. Measurements are facts; they never contain pass/fail.
2. Findings are pure functions of (measurements, rule). Re-running rules on stored measurements must reproduce identical findings.
3. `report.json` is canonical; HTML/PDF are renderings and must never contain information absent from the JSON.
4. Detector failures surface as `ERROR` findings — never silently dropped.
5. AI output lives in a separate `ai_summary` structure, never inside canonical findings.

---

## 4. Module Boundaries and Dependency Rules

Import direction (a module may import only from layers below it):

```text
cli
   │
server (ADR-014; the future P7 API replaces the deployment, not the shape)
   │
orchestration
   │
┌──┴──────────────┬──────────────┬───────────────┬──────────────┐
detectors      rules          reports        evidence      comparison
└──┬──────────────┴──────────────┴───────────────┴──────────────┘
   │
presets (consumed by orchestration; never by detectors)
   │
models  ←  the only shared vocabulary (incl. the parameter catalogue)
   │
utils
```

Hard rules — **mechanized since 2026-07-26** as six import-linter contracts in
`pyproject.toml`, run by `make layers` and in CI (ADR-010, backlog #30). All
six pass; they were added while the boundaries were still intact, which is the
cheapest moment (risk R6).

- `rules/` never imports `detectors/`. They communicate only via `Measurement` models.
- `detectors/` never imports `presets/` or `rules/`. Detectors do not know thresholds or clients.
- `reports/` consumes only `QCResult`/`Finding`/`Measurement` models.
- `models/` imports nothing from the application (only stdlib + Pydantic).
- The core (`orchestration` and below) never imports `cli` or `server`, so it stays usable as a library (ADR-010).
- No module hardcodes client names. Ever. *(Not mechanically enforceable — this one stays a review rule.)*

Two notes on the graph above:

- `cli` sits above `server` rather than beside it, because the `serve` command legitimately constructs the server app.
- `detectors` and `presets` are siblings that must not import each other, which is why the parameter catalogue lives in `models/`: it is the one layer both may be validated against (ADR-021).

---

## 5. Repository Layout (target)

As specified in the handoff §6, with amendments recorded in `DECISIONS.md` (ADR-005, ADR-006):

- `docs/adr/` replaced by a single `docs/DECISIONS.md` (per project instructions).
- `src/deepdub_qc/storage/` deferred to Phase 7 — no SQLite/SQLAlchemy in the MVP; the job output directory is the persistence layer.
- `schemas/` contains **exported** JSON Schemas generated from the Pydantic models (ADR-004); a contract test fails CI if they drift.

---

## 6. Deployment Evolution

```text
Phase 1–6: Local CLI (pip/uv install, or Docker image)
             deepdub-qc analyze --input … --preset … --output …
Phase 7:   Same core wrapped by FastAPI + job persistence (Postgres)
             CLI and API call the identical orchestration pipeline
Phase 8:   Composer calls the API; workers run detector jobs
Phase 9:   AI layer over stored QCResults (opt-in, audited)
```

The core (`models` → `orchestration`) must remain importable as a pure library with no CLI, API, or DB dependencies, so service extraction is a wrapper, not a rewrite. Enforced by an import-linter contract, not just intent.

Canonical execution environment is the Docker image, pinned by base-image digest with the FFmpeg version declared in `environment.lock` and asserted at build time (ADR-008, ADR-022): determinism across machines is otherwise not guaranteed. The full test suite runs inside that image (`make docker-test`), so reproducibility is verified on the toolchain we ship rather than on whatever a developer or CI runner happens to have.

---

## 7. Dependency Graph (external)

| Dependency | Used by | Phase |
|---|---|---|
| FFmpeg / ffprobe (pinned) | detectors | 3+ |
| Pydantic v2 | models | 1 |
| Typer + Rich | cli | 1 |
| PyYAML | presets | 1 |
| Jinja2 | reports (HTML) | 2 |
| WeasyPrint | reports (PDF) | 2 |
| pytest, ruff, mypy | dev | 1 |
| FastAPI, SQLAlchemy, Alembic, Postgres | api/storage | 7 |
| MediaInfo, pysubs2, OpenCV, libvmaf | optional detectors | post-MVP |

New runtime dependencies require an ADR entry.
