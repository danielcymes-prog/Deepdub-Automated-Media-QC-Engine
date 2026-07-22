# Deepdub QC Engine — Architecture

Status: Phase 0 baseline. Companion documents: `DECISIONS.md` (why), `ROADMAP.md` (when), `RISKS.md` (what could go wrong), `DATA_MODEL_REVIEW.md` (schema validation).

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
| **CLI** (`cli/`) | Argument parsing, exit codes, human console output | Any QC logic; it only calls orchestration |
| **Orchestration** (`orchestration/`) | Job lifecycle, pipeline sequencing, job context, output directory layout | Measuring, evaluating, rendering |
| **Preset Engine** (`presets/`) | Load, schema-validate, and version YAML presets | Knowing how detectors work |
| **Detector Engine** (`detectors/`) | Run tools (ffprobe/ffmpeg), parse output, emit normalized `Measurement`s, preserve raw output | Pass/fail decisions, thresholds, client knowledge |
| **Rule Engine** (`rules/`) | Evaluate measurements against preset rules with generic operators; emit `Finding`s; aggregate overall status | How measurements were produced; rendering |
| **Evidence Engine** (`evidence/`) | Generate thumbnails/waveforms/clips for timestamped findings | Deciding what failed |
| **Report Engine** (`reports/`) | Build canonical `QCResult` JSON; render HTML/PDF from it | Computing or altering findings |
| **Models** (`models/`) | Pydantic domain models + exported JSON Schemas; the shared vocabulary | Behavior |
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
cli, api (P7)
   │
orchestration
   │
┌──┴──────────────┬──────────────┬───────────────┐
detectors      rules          reports        evidence
└──┬──────────────┴──────────────┴───────────────┘
   │
presets (parallel to the above; consumed by orchestration + rules)
   │
models  ←  the only shared vocabulary
   │
utils
```

Hard rules (enforced by review and, later, import-linter):

- `rules/` never imports `detectors/`. They communicate only via `Measurement` models.
- `detectors/` never imports `presets/`. Detectors do not know thresholds or clients.
- `reports/` consumes only `QCResult`/`Finding`/`Measurement` models.
- No module hardcodes client names. Ever.
- `models/` imports nothing from the application (only stdlib + Pydantic).

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

The core (`models` → `orchestration`) must remain importable as a pure library with no CLI, API, or DB dependencies, so service extraction is a wrapper, not a rewrite.

Canonical execution environment is the Docker image with a **pinned FFmpeg version** (ADR-008): determinism across machines is otherwise not guaranteed.

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
