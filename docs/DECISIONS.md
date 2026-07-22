# Architecture Decision Records

One record per decision. Statuses: Proposed → Accepted → Superseded. Never edit an Accepted ADR's decision; supersede it.

---

## ADR-001: Deterministic core, AI at the edges

- **Status:** Accepted (2026-07-22)
- **Context:** LLMs could plausibly "watch" media and judge acceptability. QC results must be reproducible, auditable, and defensible to clients.
- **Alternatives:** (a) LLM-in-the-loop evaluation; (b) hybrid where AI can override rules; (c) fully deterministic pipeline with AI limited to explanation.
- **Decision:** (c). Detectors measure, rules decide, reports render. AI may only consume the canonical result and produce separately-stored explanations, disabled by default.
- **Consequences:** Reproducible results; more upfront engineering per check; AI features become an additive layer that cannot corrupt QC integrity.

## ADR-002: `report.json` is the single source of truth

- **Status:** Accepted (2026-07-22)
- **Context:** Three report formats (JSON/HTML/PDF) must never disagree.
- **Alternatives:** (a) independent renderers per format; (b) HTML canonical, others derived; (c) canonical JSON, HTML rendered from it, PDF rendered from the HTML.
- **Decision:** (c). Renderers are pure functions of the `QCResult` model. Contract tests assert HTML content matches JSON.
- **Consequences:** One place to version the report contract; PDF fidelity depends on the HTML/CSS (see ADR-007).

## ADR-003: Client requirements are versioned YAML presets, never code

- **Status:** Accepted (2026-07-22)
- **Context:** Client-specific conditionals in Python are the fastest route to an unmaintainable system and were explicitly banned in the handoff.
- **Alternatives:** (a) per-client Python plugins; (b) database-stored rules with admin UI; (c) versioned YAML files in-repo, schema-validated.
- **Decision:** (c) for now; (b) becomes the storage backend in Phase 7+ without changing the preset model. Semver rules per handoff §12.3; approved versions are immutable (CI-enforced from M6).
- **Consequences:** Presets are reviewable in PRs, diffable, and testable. Preset governance (who approves thresholds) is a human process — see handoff §30.

## ADR-004: Pydantic models are the canonical schema; JSON Schemas are exported artifacts

- **Status:** Accepted (2026-07-22)
- **Context:** The handoff specifies both Pydantic models and JSON Schema files. Two hand-maintained sources will drift.
- **Alternatives:** (a) JSON Schema first, generate Python (codegen churn, weak typing); (b) hand-maintain both (guaranteed drift); (c) Pydantic first, export schemas via `model_json_schema()`, commit them, contract-test for drift.
- **Decision:** (c). `schemas/` holds exported files; a CI test regenerates and diffs them.
- **Consequences:** Python is the source of truth (acceptable: core is Python); non-Python consumers (Composer) get stable, versioned JSON Schemas.

## ADR-005: Filesystem job directory is MVP persistence; SQL deferred to Phase 7

- **Status:** Accepted (2026-07-22) — *deviation from handoff §5.1, which lists SQLite/SQLAlchemy in the MVP stack*
- **Context:** The MVP is a single-file, single-job CLI. The job output directory already contains the complete, canonical result. Nothing in Phases 1–6 needs cross-job queries.
- **Alternatives:** (a) SQLite + SQLAlchemy + Alembic from day one; (b) filesystem only, with a `ResultRepository` interface so Phase 7 adds Postgres behind it.
- **Decision:** (b). SQLite in the MVP is schema-migration burden with no consumer, and risks the DB quietly becoming a second source of truth in violation of ADR-002.
- **Consequences:** Less code and no migrations until a service actually needs them; Phase 7 must implement the repository interface (planned); job history queries before P7 are `ls` + `jq`, which is acceptable for a local tool.

## ADR-006: Single `docs/DECISIONS.md` instead of `docs/adr/` directory

- **Status:** Accepted (2026-07-22)
- **Context:** Handoff §6 shows `docs/adr/0001-….md`; project instructions mandate `docs/DECISIONS.md`. Conflict must be resolved once.
- **Decision:** Single file, per project instructions (the more recent, binding document). One `##` section per ADR keeps ordering, linkability, and greppability.
- **Consequences:** Split into a directory later only if the file exceeds ~30 ADRs.

## ADR-007: WeasyPrint for PDF rendering

- **Status:** Accepted (2026-07-22)
- **Context:** Handoff allows Playwright or WeasyPrint. Reports must work without JavaScript (§17.2) anyway.
- **Alternatives:** (a) Playwright — full browser fidelity, heavyweight dependency (headless Chromium), slower, larger attack/maintenance surface; (b) WeasyPrint — pure CSS paged media, native libs (Pango/Cairo) but Docker makes that deterministic.
- **Decision:** (b). The no-JS requirement removes Playwright's main advantage. Renderer sits behind a small `PdfRenderer` interface so swapping later is cheap.
- **Consequences:** HTML/CSS must stay within WeasyPrint's supported subset; system deps handled in the Docker image and documented for local installs.

## ADR-008: Determinism policy — pinned tools, content-derived IDs, declared volatile fields

- **Status:** Accepted (2026-07-22)
- **Context:** The Definition of Done requires "the same input and preset produce identical canonical findings." Random UUIDs, timestamps, and unpinned FFmpeg versions all break this silently.
- **Decision:**
  1. FFmpeg/ffprobe versions are pinned in the Docker image; every `QCResult` records an `environment` block (tool versions, platform). Docker is the canonical execution environment; native runs are best-effort.
  2. `measurement_id` and `finding_id` are deterministic UUIDv5 values derived from (job-invariant) content: detector_id + parameter_id + stream selector + value + span. `job_id` alone is random.
  3. Volatile fields (`job_id`, `created_at`, `started_at`, `completed_at`, `duration_seconds`) are explicitly enumerated; the CI determinism test compares canonical output with volatile fields masked — everything else must be byte-identical across runs.
- **Consequences:** Reproducibility is testable, not aspirational; golden-file tests are stable; cross-FFmpeg-version drift becomes a visible, managed upgrade event rather than silent behavior change.

## ADR-009: Rule identity is separate from parameter identity; rules carry stream selectors

- **Status:** Accepted (2026-07-22) — *extension of handoff §12/§10*
- **Context:** In the handoff preset schema, `check_id` doubles as the parameter ID and the rule's identity. That forbids two rules on the same parameter (e.g., integrated loudness on the German dub stream vs. the M&E stem) — a core Deepdub scenario with multi-language, multi-stem deliveries.
- **Decision:** A rule has its own `rule_id` (unique within the preset), references a `parameter_id` from the parameter catalogue, and may carry an `applies_to` stream selector (by index, by type, by language tag, or `all`/`any` quantifier). Findings record both `rule_id` and `parameter_id`.
- **Consequences:** Slightly richer preset schema now; avoids a breaking preset-schema major version immediately after real multi-stream presets appear. Full selector semantics documented in `DATA_MODEL_REVIEW.md`.

## ADR-010: Single Python package, src layout, library-first core

- **Status:** Accepted (2026-07-22)
- **Context:** Future shape is CLI → API → workers → Composer.
- **Alternatives:** (a) separate packages per subsystem now (premature); (b) one package `deepdub_qc` with strict internal layering enforced by convention/import-linter, core importable without CLI/API deps.
- **Decision:** (b). Service extraction (P7) wraps the same library; packages split only if deployment actually requires it.
- **Consequences:** Simple dev experience; layering discipline must be actively enforced (CI import-linter rules from M1).

## ADR-011: Report-first build order

- **Status:** Accepted (2026-07-22)
- **Context:** The report is what operators and clients judge. Detector work is expensive; building it against an unvalidated report contract invites rework.
- **Decision:** M2 renders a fully mocked `QCResult` to JSON/HTML/PDF and gets stakeholder sign-off before any detector is written (M3+).
- **Consequences:** Report contract stabilizes early; mock fixture doubles as the permanent contract-test fixture.
