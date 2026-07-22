# Deepdub QC Engine — Engineering Roadmap

Complexity scale: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ 2–4 weeks (single senior engineer). Estimates assume the data-model changes in `DATA_MODEL_REVIEW.md` are resolved first.

**MVP = M1 + M2 + M3.** Everything after M3 extends a working, report-producing tool.

---

## M0 — Discovery (human-driven, runs in parallel)

- **Objective:** Ground the tool in real delivery requirements.
- **Deliverables:** Collected Vidchecker reports, client specs, manual QC checklists, top-10 delivery-blocking failures, first client preset selection.
- **Complexity:** S–M (mostly coordination, not code).
- **Dependencies:** None.
- **Acceptance:** One client spec approved as MVP target; 10–15 parameters agreed; stakeholders approve report sections.
- **Note:** Does not block M1/M2. The generic preset carries development until M0 lands.

## M1 — Project Foundation

- **Objective:** Installable, tested, CI-verified skeleton with the domain model finalized.
- **Deliverables:** Repo scaffold; `pyproject.toml` (uv, Python 3.13); Typer CLI (`--help`, `version`, `presets validate`); structured logging; Pydantic models (job, asset, preset, rule, measurement, finding, report); exported JSON Schemas + drift contract test; preset loader/validator; example generic preset; Dockerfile with pinned FFmpeg; GitHub Actions CI; `CLAUDE.md`, `README.md`.
- **Complexity:** M.
- **Dependencies:** Data-model decisions (ADR-004, ADR-008, ADR-009).
- **Acceptance:** `deepdub-qc --help` works; sample preset validates; ruff/mypy/pytest green in CI; Docker image builds; schemas exported and drift-tested.

## M2 — Report-First Prototype

- **Objective:** Stakeholders review a realistic report before any detector exists.
- **Deliverables:** Hand-built mock `QCResult` fixture; JSON renderer; HTML report (Jinja2, printable, no JS); PDF renderer (WeasyPrint); `deepdub-qc render-mock` command; report contract tests + golden-file tests.
- **Complexity:** M.
- **Dependencies:** M1.
- **Acceptance:** JSON/HTML/PDF generated from one canonical model with consistent content; stakeholders sign off on report sections (feeds back into M0).
- **Rationale:** The report is the product. Locking its contract early prevents detector rework.

## M3 — Metadata MVP  ← first shippable

- **Objective:** Analyze one real file against one preset, end to end.
- **Deliverables:** Safe ffprobe wrapper (timeouts, no shell, raw output preserved); metadata normalization (rational frame rates, channel layouts); rule engine with all §13 operators + unit tests per operator; SKIPPED/ERROR semantics; status aggregation; Tier 1 checks (~15); `analyze` command; documented exit codes; integration tests; one generated media fixture.
- **Complexity:** L.
- **Dependencies:** M1, M2.
- **Acceptance:** Handoff §28 Definition of Done; identical canonical findings on repeated runs (determinism test in CI, run inside Docker).

## M4 — Audio QC

- **Objective:** The checks that most often block dubbing deliveries.
- **Deliverables:** EBU R128 loudness (integrated, LRA, true peak) via single-pass `ebur128`; silence (head/tail/internal); clipping indicators; audio/video duration delta; golden audio fixtures with expected-result files.
- **Complexity:** L (loudness validation against reference files is the long pole).
- **Dependencies:** M3.
- **Acceptance:** Golden fixtures produce expected findings; loudness reproducible run-to-run and within tolerance of EBU reference material.

## M5 — Video Incident QC

- **Objective:** Timestamped video findings with evidence.
- **Deliverables:** blackdetect, freezedetect, signalstats detectors; thumbnail evidence at incident timestamps; timecode rendering from canonical seconds.
- **Complexity:** M.
- **Dependencies:** M3 (evidence engine can start during M4).
- **Acceptance:** Timestamped findings show correct timecodes; each incident finding links to at least one evidence artifact.

## M6 — Preset Management

- **Objective:** New clients without code changes.
- **Deliverables:** Multiple client presets; semver enforcement; approval status workflow (draft/approved/deprecated); immutability check for approved versions; preset test fixtures; `presets validate` hardening.
- **Complexity:** S–M.
- **Dependencies:** M3.
- **Acceptance:** A new client preset added purely as YAML passes validation and runs; CI fails if an approved preset file changes.

## M7 — Service Extraction

- **Objective:** Same core, callable as a service.
- **Deliverables:** FastAPI wrapper implementing handoff §23 endpoints; job persistence (Postgres, repository interface from ADR-005); object-storage abstraction; idempotent job execution; worker abstraction aligned with existing Deepdub queue infra (**requires infra decision — see RISKS**).
- **Complexity:** L.
- **Dependencies:** M3–M6 stable; human decision on queue/storage/auth (handoff §30).
- **Acceptance:** CLI and API produce byte-identical canonical results for the same input; duplicate job submissions deduplicate.

## M8 — Composer Integration

- **Objective:** Run QC without leaving Composer.
- **Deliverables:** Job submission, preset resolution, progress, results panel, timestamp navigation, evidence preview, QC marker creation, report downloads.
- **Complexity:** L (joint with Composer frontend team).
- **Dependencies:** M7.
- **Acceptance:** Operator runs QC and inspects a failure timestamp end-to-end in Composer.

## M9 — AI Assistance

- **Objective:** Explanation and remediation, never adjudication.
- **Deliverables:** Explain-finding, summarize-report, suggest-remediation, preset drafting from client spec, report diffing; `ai_summary` stored separately; audit log; disabled by default.
- **Complexity:** M.
- **Dependencies:** M7 (needs stored results); human approval for any external data transmission (handoff §30).
- **Acceptance:** AI content visibly separated in reports; canonical JSON unchanged with AI on or off.
