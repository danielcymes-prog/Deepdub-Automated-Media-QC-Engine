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

- **Status:** Accepted (2026-07-22). **Implemented by ADR-022 (2026-07-26):**
  point 1 below described the intended policy, but until ADR-022 the Dockerfile
  used a floating tag and unversioned `apt-get install ffmpeg`, so nothing was
  actually pinned. `environment.lock` now holds the declaration and the build
  enforces it.
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

## ADR-012: Report rendering — Jinja2, self-contained HTML, content-based contract tests

- **Status:** Accepted (2026-07-22)
- **Context:** M2 adds report rendering; the handoff requires printable, JS-free reports readable by non-engineers (§17.2). New runtime dependencies require documentation (CLAUDE.md).
- **Alternatives:** (a) manual string/f-string HTML assembly — escaping bugs, unmaintainable; (b) client-side rendering of the JSON — violates the no-JS requirement; (c) Jinja2 server-side templating with autoescaping, CSS inlined into a single self-contained document.
- **Decision:** (c). Dependencies added: `jinja2` (templating) and `weasyprint` (per ADR-007). The PDF is rendered from the same HTML document, so the two visual formats cannot diverge. The HTML contract is enforced by content assertions (every finding, expected/actual values, timecodes, hashes, versions, no `<script>`), not golden HTML bytes, so cosmetic template changes don't break CI. The canonical `report.json` byte layout (sorted keys, two-space indent, trailing newline) IS locked by a golden file.
- **Consequences:** Native Pango libraries required for PDF output; installed in Docker and CI, with a typed, actionable error (`PdfRenderError`) where missing. Report generation timestamp is injectable and declared volatile (ADR-008).

## ADR-013: Approved-preset immutability via a hash lock file

- **Status:** Accepted (2026-07-22)
- **Context:** Approved preset versions must be immutable (handoff §12.3), and approval is a human decision (§30). The mechanism must work in the current git-only phase and survive Phase 7 (DB-backed presets).
- **Alternatives:** (a) convention only — unenforceable; (b) git hooks — bypassable, not visible in CI; (c) a committed `presets/approved.lock.json` mapping approved preset paths to sha256 digests, verified by a unit test on every CI run and a `deepdub-qc presets verify` command.
- **Decision:** (c). Approving a preset = a reviewed commit that flips `status: approved` and runs `deepdub-qc presets lock`. Editing, demoting, or deleting a locked preset breaks CI with an actionable message. The lock file is the natural seed for the Phase 7 `qc_preset_versions` table.
- **Consequences:** Approval becomes an explicit, auditable git event; the lock file must be updated in the same commit as any legitimate approval; drafts remain freely editable.

## ADR-014: Phase 3.5 — Local web GUI + persistent service on the shared RDP host

- **Status:** Accepted (2026-07-23). Authored during the parallel design effort
  as `docs/adr/0004-local-web-gui-on-shared-rdp-host.md`; folded here as the
  canonical record. Full context, alternatives (per-user server, native
  desktop app), and consequences live in that file.
- **Context:** Operators (max 2) need point-and-click submission, queue
  visibility, and report access on a shared Windows RDP host, before Composer
  integration (now the final step; M7 service extraction deferred).
- **Decision:** One persistent FastAPI service (`deepdub-qc serve`) with a
  server-rendered local web GUI (Jinja2 + vanilla JS, no framework, no CDN).
  Zero QC logic in the GUI. API routes mirror the future Composer contract
  (handoff section 23). Single in-process worker, max_concurrent_jobs=1.
  SQLite holds job orchestration state ONLY (partially supersedes ADR-005;
  report.json remains the sole source of truth per ADR-002). GUI sessions
  capped at 2. FFmpeg/ffprobe located via explicit config. New dependencies:
  fastapi, uvicorn (server); playwright optional for Windows PDF.
- **Amends ADR-007:** on the Windows deployment target, PDF rendering uses
  Playwright (headless Chromium) behind the existing PdfRenderer interface
  (ADR-012); WeasyPrint remains the Docker/Linux default. WeasyPrint's
  native Pango/Cairo stack is not reliably deterministic on Windows.
- **Specs:** docs/server-gui-spec.md (functional), docs/gui-design-spec.md
  (visual), docs/server-config-spec.md (configuration),
  docs/windows-deployment.md (service install/upgrade).
- **Consequences:** Windows service administration becomes part of the
  product; persistence arrives earlier than ADR-005 planned but only for
  queue state; Phase 7 extraction becomes a re-deployment of an existing
  API shape rather than a redesign.

## ADR-015: Console typefaces are self-hosted, not fetched from a CDN

- **Status:** Accepted (2026-07-26)
- **Context:** `static/app.css` declared `--font-ui: 'Onest', …` and
  `--font-mono: 'JetBrains Mono', …` but never loaded either face, so the
  console silently rendered in the system fallback (Segoe UI on the Windows RDP
  host) next to an SVG wordmark drawn in the real Deepdub typeface. Meanwhile
  `reports/templates/report.html.j2` pulls the same two families from Google
  Fonts via `@import`. Both are defects on the Phase 3.5 deployment target: the
  console had no font at all, and the report's CDN fetch cannot succeed on an
  air-gapped broadcast network — it degrades to system fonts without warning,
  which silently changes PDF text metrics and therefore page pagination.
  ADR-014 already commits to "no CDN" for the GUI; the report template predates
  and violates it.
- **Alternatives:** (a) add the Google Fonts `@import` to the console, matching
  the report — zero repo weight, but inherits the air-gap failure and makes
  rendering depend on egress rules we do not control; (b) drop the brand faces
  and standardise on a system stack — maximally robust, but abandons brand
  typography and still leaves report/console PDF metrics host-dependent;
  (c) vendor woff2 files into `static/fonts/` with local `@font-face` rules.
- **Decision:** (c), using the **variable-weight** builds (one file per family
  per unicode subset, `font-weight: 100 900`). Variable axes are not a nicety
  here: the existing type scale specifies weights 550 and 650, which static
  instances cannot render and would round to 600 or synthesise. Scope is
  latin + latin-ext (~120 KB total, SIL OFL, licences committed alongside).
  Fonts are `<link rel=preload>`ed in the shell so first paint does not flash.
- **Consequences:** The console renders identically on any host, online or not,
  which matters more for the PDF path than the screen path — deterministic text
  metrics are a precondition for reproducible report pagination (ADR-002,
  ADR-012). Binary assets now live in the repo and must be refreshed manually
  on upstream font updates; the pinned files are the reproducibility guarantee,
  so this is the intended trade. Hatchling already ships non-Python files under
  `src/deepdub_qc`, so no packaging change was required.
- **Follow-up:** `reports/templates/report.html.j2` still `@import`s from Google
  Fonts and should be migrated to the same local faces before any air-gapped
  PDF delivery is trusted. Tracked in docs/BACKLOG.md.

## ADR-016: Shell chrome derives from layout tokens; accent colours are reserved

- **Status:** Accepted (2026-07-26)
- **Context:** The console shell had accumulated coupled magic numbers and a
  colour collision. `.shell-header` was `height: 60px` while
  `.data-table th` was `position: sticky; top: 60px` — two independent
  literals that must agree or sticky table headers slide under the app bar.
  The header used `padding: 0 28px` while `main` used
  `max-width: 1200px; margin: 0 auto`, so header content never aligned with
  page content at any viewport above 1256 px. Separately, the active nav
  underline used violet, which `--qc-error` also uses to mean "the pipeline
  could not finish" — spending a reserved status colour on navigation chrome.
- **Alternatives:** (a) leave the literals and document the coupling in a
  comment; (b) compute sticky offsets in JS from the measured header height;
  (c) declare `--shell-header-h`, `--content-max`, `--content-pad` in `:root`
  and derive every dependent rule from them.
- **Decision:** (c), plus a `.shell-header-inner` container that shares
  `--content-max`/`--content-pad` with `main` so the bar spans the viewport
  while its contents sit on the content column. The active nav state is
  `--dd-accent` magenta **and** a 500→600 weight step, so it is not signalled
  by colour alone. Violet remains reserved for the ERROR verdict; the status
  palette is never used for chrome.
- **Consequences:** Header height changes in one place. The verdict palette
  keeps a 1:1 colour-to-meaning mapping, which is the property that lets an
  operator read a verdict at a glance without consulting a legend. Option (b)
  was rejected as it reintroduces layout-dependent JS into a shell that
  ADR-014 requires to work without it.

## ADR-017: QC coverage grows through the pinned FFmpeg binary, not a source build

- **Status:** Proposed (2026-07-26)
- **Context:** Evaluated incorporating the FFmpeg source repository
  (github.com/FFmpeg/FFmpeg) into the build for "additional tools". The repo
  is the source for the binaries we already ship, not a separate toolbox.
  Verified capabilities of the pinned build (`ffmpeg 5.1.9-0+deb12u1` from
  Debian bookworm, per the Dockerfile): QC-relevant filters we do **not** yet
  use are present — `axcorrelate`, `asdr`, `photosensitivity`, `idet`,
  `cropdetect`, `blockdetect`, `blurdetect`, `scdet`, `siti`, `ssim`, `psnr`,
  `entropy`, `bitplanenoise` — plus the `framemd5`/`streamhash` muxers and
  the full `-err_detect` flag set. **Not** present: `libvmaf` (compiled out
  of the Debian build) and `apsnr`/`asisdr` (added upstream in FFmpeg 6.1).
- **Alternatives:** (a) build FFmpeg from source — heavy C build, LGPL/GPL
  compliance obligations for a shipped image, we inherit Debian's security-
  patch burden, and it complicates rather than helps the ADR-008 pinning
  story; (b) link `libav*` in-process (PyAV) — marginal performance win
  (detectors already batch filters into shared graphs) at the cost of the
  subprocess audit discipline (argument arrays, timeouts, preserved raw
  stderr); (c) keep the pinned distro binary and widen filter usage, swapping
  to a different *pre-built* pinned distribution (e.g. BtbN static builds
  with libvmaf) only if VMAF becomes a requirement.
- **Decision:** (c). New detectors (ADR-018–020) require zero build changes.
- **Consequences:** VMAF full-reference scoring is deferred; adopting it — or
  any 6.1+ filter such as `apsnr` — means changing the FFmpeg binary, which
  is a release event with a full golden-corpus re-run per ADR-008. The filter
  inventory above was verified against the exact pinned build, not
  documentation; re-verify on any FFmpeg upgrade.

## ADR-018: Decode-integrity detector (full-decode error census)

- **Status:** Proposed (2026-07-26)
- **Context:** A file can carry compliant metadata and loudness yet fail to
  decode cleanly (truncated GOPs, embedded-CRC failures, bitstream
  corruption). Vidchecker counts decode errors; we currently have no
  equivalent, and our existing analysis decodes run at FFmpeg's default
  error tolerance, which silently conceals exactly this class of defect.
- **Alternatives:** (a) piggyback error parsing onto the existing audio/video
  analysis runs — couples unrelated failure modes and would change those
  detectors' decode behavior, breaking golden files; (b) a dedicated
  detector: one full decode of all streams with
  `-err_detect crccheck+bitstream+buffer -v error -f null -`, counting
  stderr error lines and recording the first-error position; (c) also emit
  `framemd5` per-frame hashes as reproducibility evidence.
- **Decision:** (b). Measurements: `media.decode_error_count` and
  `media.decode_first_error` (nullable timecode/offset string). Raw stderr
  preserved at `raw/decode_integrity.log`. Whether N errors is blocking is a
  preset threshold — human-approved per handoff §30; the detector emits
  counts only (ADR-001).
- **Consequences:** One additional full decode per job, bounded by the
  existing timeout discipline. Catches the corruption class that metadata
  checks structurally cannot. Option (c) deferred until a use-case consumes
  frame hashes; the muxer is confirmed available in the pinned build.

## ADR-019: Dub-vs-source audio comparison via `axcorrelate`/`asdr`

- **Status:** Proposed (2026-07-26)
- **Context:** The delivered dub must stay sync- and level-consistent with
  the source master; this is the QC check most specific to Deepdub's actual
  product. The comparison module today diffs *reports* (ours vs Vidchecker,
  same file bytes); it has no media-vs-media capability. The pinned build
  provides `axcorrelate` (windowed normalized cross-correlation of two audio
  streams) and `asdr` (signal-to-distortion ratio against a reference).
- **Alternatives:** (a) external alignment tools (audio-offset-finder,
  chromaprint) — new dependencies, new ADRs, overkill for nominally-aligned
  masters; (b) FFmpeg two-input filter graph: mono-downmix both files,
  `axcorrelate` streamed to stdout as PCM, Python reduces it to per-window
  correlation measurements; `asdr` for a scalar level/distortion figure;
  (c) defer entirely until a client demands it.
- **Decision:** (b), as a new *two-input* detector class. This extends the
  pipeline contract: `QCContext` gains an optional `reference_path`, and
  reference-requiring detectors are skipped (not failed) when no reference
  is supplied. Measurements: `comparison.audio_correlation_min`,
  `comparison.audio_correlation_windows_below` (count under a fixed
  measurement constant, not a client threshold), `comparison.audio_sdr_db`.
  Sustained low correlation localizes desync/content-mismatch regions.
- **Consequences:** First detector that reads two inputs — the schema,
  registry `is_applicable`, and CLI must grow a reference-file argument
  (schema regeneration required). Absolute lag *estimation* (e.g. FFT
  cross-correlation to report "dub is +40 ms") is explicitly out of scope
  for v1: `axcorrelate` measures similarity over time, not global offset;
  estimating offset well needs a Python-side DSP dependency and its own ADR.

## ADR-020: Broadcast-compliance video detectors (`photosensitivity`, `idet`, `cropdetect`)

- **Status:** Proposed (2026-07-26)
- **Context:** Three delivery-blocking defect classes are invisible to the
  current video detector (black/freeze/luma): photosensitive-epilepsy flash
  risk (Harding-style, mandated by UK/JP broadcasters), interlaced content
  mislabeled as progressive (ffprobe reports the *declared* field order, not
  the actual one), and active-picture errors (unintended letterbox/pillarbox
  or dirty edges).
- **Alternatives:** (a) license commercial PSE analysis (Harding FPA) —
  cost, licensing, and a non-deterministic external dependency; (b) extend
  the existing `video.incidents.ffmpeg` filter chain — one decode, but any
  addition perturbs its raw-log golden files and couples five defect classes
  to one detector version; (c) a second video detector with its own chain:
  `photosensitivity,idet,cropdetect,metadata=print:file=-`, reusing the
  single-decode / raw-log pattern of the existing video detector.
- **Decision:** (c). Measurements: `video.pse_frames_over_badness`
  (photosensitivity filter's per-frame badness census — explicitly *not* a
  Harding certification, and reports must never claim it is),
  `video.interlace_detected_ratio` (idet TFF+BFF vs progressive frame
  counts) cross-checked against the ffprobe-declared field order, and
  `video.active_picture_bbox` (modal cropdetect rectangle vs coded
  dimensions). All thresholds preset-governed per handoff §30.
- **Consequences:** One additional video decode per job (acceptable; audio
  and video detectors already run separate decodes). PSE output is a
  screening signal, not a legal compliance certificate — the report wording
  must say so, which is a renderer contract-test item. Filters confirmed
  present in the pinned 5.1.9 build.

## ADR-021: The parameter catalogue is a first-class registry in `models/`

- **Status:** Accepted (2026-07-26)
- **Context:** Handoff §15 requires a parameter catalogue plus a
  machine-readable registry; neither existed. Consequently nothing validated
  that a preset's `parameter_id` corresponds to a parameter any detector
  emits. A typo'd or aspirational `parameter_id` passed `presets validate`
  cleanly and produced a `SKIPPED` finding at runtime. For a *blocking* rule
  the aggregation in `rules/engine.py` escalates that to `ERROR` and it is
  caught — but a **non-blocking** rule silently became `SKIPPED`, presenting
  the operator with a complete-looking report for a check that never ran.
  That is the one silent-pass path in the system, and preset authoring is
  explicitly the extension point for non-engineers (ADR-003).
- **Alternatives:**
  (a) Derive the valid parameter set from the detector registry at preset-load
  time. Rejected: it makes `presets/` depend on `detectors/`, and the
  ARCHITECTURE §4 graph deliberately keeps them siblings. It also means the
  legal preset vocabulary changes with which detectors happen to be
  registered, so a preset's validity would depend on load order.
  (b) A hand-maintained markdown catalogue with no code binding. Rejected:
  guaranteed drift, same failure mode ADR-004 rejected for schemas.
  (c) A declarative catalogue in `models/` — the layer ARCHITECTURE §4 already
  designates "the only shared vocabulary" — that both `detectors/` and
  `presets/` are validated *against*, with the markdown and JSON artifacts
  generated from it.
- **Decision:** (c). `models/parameters.py` holds a `ParameterDefinition` per
  parameter with the twelve fields handoff §15 requires, plus an
  implementation status (`implemented` / `planned`) and a validation status
  that may only claim `validated` where `docs/VALIDATION.md` actually backs
  it. Three bindings make it load-bearing rather than decorative:
  1. `presets/loader.py` rejects any rule whose `parameter_id` is absent from
     the catalogue, with a `difflib` close-match suggestion.
  2. A contract test asserts every detector's declared `parameters` tuple is a
     subset of the catalogue, and that every `implemented` parameter is
     claimed by exactly one detector — so adding a detector parameter without
     cataloguing it fails CI, and vice versa.
  3. `scripts/export_parameters.py` generates `docs/parameter-catalogue.md`
     and `schemas/parameter-catalogue.json` with a `--check` drift mode,
     mirroring ADR-004's export-and-diff pattern.
- **Consequences:** Preset typos fail at load with an actionable message
  instead of degrading into a silent skip. The catalogue becomes the reviewable
  place where "what can we measure" is stated, which is also what Composer
  needs to populate a preset editor later. Cost: adding a parameter now means
  editing two places (detector + catalogue), enforced by the contract test —
  deliberate friction, since an uncatalogued parameter is unusable by presets
  anyway. Rules referencing `planned` parameters are rejected too, which is
  stricter than the status quo and may require correcting existing draft
  presets; that is the bug being fixed, not a regression.

## ADR-022: The canonical environment is pinned and the canonical test run happens inside it

- **Status:** Accepted (2026-07-26)
- **Context:** ADR-008 makes determinism testable in principle, and
  `tests/integration/test_analyze_e2e.py:111` implements the repeat-run
  byte-comparison correctly. But `ci.yml` never installed FFmpeg, so every
  integration test — determinism, audio, video, batch, server, EBU
  conformance — was guarded by `skipif(which("ffmpeg") is None)` and skipped
  on every merge, while `pytest -q` reported green. Separately, ADR-008,
  `RISKS.md` R1, `ARCHITECTURE.md` §6 and `README.md` all asserted FFmpeg was
  pinned in Docker; `Dockerfile` used a floating tag and unversioned
  `apt-get install ffmpeg`, with a comment deferring the pin to "release
  time". The project's two central claims — reproducible measurements and a
  fixed toolchain — were therefore documented more strongly than enforced.
- **Alternatives for the toolchain pin:**
  (a) `apt-get install ffmpeg=<exact version>`. Rejected: Debian drops
  superseded versions from the mirror on security updates, so this converts
  drift into a hard build failure at an arbitrary future date, with no signal
  about what changed.
  (b) Vendor a static FFmpeg build. Rejected: large maintenance surface, and
  loses Debian's security patching.
  (c) Pin the base image by digest (fixing the OS and Python layers exactly),
  and treat the FFmpeg version as a *declared expectation asserted at build
  time* — the same guard pattern already used at runtime by
  `server/config.py:222-234` (`expected_ffmpeg_version`).
- **Decision:** (c), plus moving the canonical test run into the image.
  1. `FROM python:3.13-slim-bookworm@sha256:fcbd8dfc…` — pinned by digest.
  2. `environment.lock` at the repo root is the single declaration of the
     canonical toolchain (base digest, expected FFmpeg version). The Docker
     build asserts the installed FFmpeg matches and fails loudly on
     divergence, so an upgrade is a visible, reviewed event per R1 rather
     than silent behavior change.
  3. CI gains an `integration` job that builds the image and runs the full
     suite inside it, and the quality job installs FFmpeg so nothing skips
     silently. A designated CI job that cannot find FFmpeg must fail, not
     skip.
- **Consequences:** The determinism guarantee moves from asserted to
  continuously verified, in the environment ADR-008 designates as canonical.
  CI gets slower (an image build plus real media analysis per run) — accepted:
  a QC tool whose own end-to-end behavior is untested cannot ask a broadcast
  engineer to trust it. FFmpeg upgrades now require a deliberate
  `environment.lock` edit accompanied by a golden-corpus re-run, which is
  exactly the release discipline R1 prescribes. The four documents that
  misstated the pin are corrected as part of this change.
- **Note on the EBU set:** `test_ebu_conformance.py` still skips when the
  fixtures are absent, because the EBU Loudness test set cannot be
  redistributed in-repo. It stays a skip locally but must be a hard failure in
  any job designated as the conformance gate; wiring that gate is follow-up
  work, tracked in `BACKLOG.md`.


## ADR-023: Client-side console behaviour is tested in jsdom, outside `make check`

- **Status:** Accepted (2026-07-27) — CI runs the suite; the skip path is local-only
- **Context:** The console's polling logic had a defect that every existing test
  layer was structurally incapable of catching. `app.js` refreshed the polled
  region with `region.innerHTML = fresh.innerHTML` every two seconds. On the job
  detail page that region contains the Cancel button, so an operator who tabbed
  to it lost focus to `<body>` on the next tick and could never activate it from
  the keyboard. Route tests returned 200. Template tests saw valid markup. The
  defect lived entirely in the interaction between a script and a live DOM, and
  the project had no layer that executed client code at all.
- **Alternatives:** (a) accept static source assertions only — cheap and
  dependency-free, but they can only check that the *shape* of the code looks
  right; nothing proves focus survives, which is the actual requirement;
  (b) Playwright, already a dependency for Windows PDF rendering (ADR-014) —
  real browser fidelity, but needs a downloaded browser binary and a running
  server, making it slow and heavy for what is a pure DOM question;
  (c) jsdom via Node, executing `app.js` against a synthetic document with
  `fetch` and timers under test control.
- **Decision:** both (a) and (c), at different costs. The static assertions live
  in `tests/unit/test_server_interaction_contract.py` and run everywhere with no
  new dependencies. The behavioural suite lives in `tests/js/console.test.mjs`,
  is wrapped by `tests/integration/test_console_behaviour.py`, and **skips** with
  an actionable message when Node or jsdom is missing — a missing optional
  toolchain must never read as a passing test. It is excluded from `make check`
  and available as `make js-tests`. Playwright is still the right tool for
  anything needing layout or paint; jsdom is chosen because focus, event
  dispatch and DOM identity are exactly what it models well.
- **Consequences:** The repository gains a second language toolchain in a test
  directory only — no production dependency, and `tests/js/node_modules` is
  gitignored. The suite is proven to discriminate: it reports 25 passes against
  the fixed script and 16 failures against the previous one, including
  `activeElement=BODY` on the Cancel button. Risk: because it is outside
  `make check`, it can silently stop being run. Mitigated by
  `test_js_suite_is_declared_correctly`, which runs without Node and fails if
  the entrypoint is renamed or the manifest drifts — a permanent skip would
  otherwise read as green.
- **Open question for review:** whether CI should install Node and run
  `make js-tests`, making the skip path dead code in CI while remaining a
  convenience locally. Recommended, but it adds a toolchain to the pipeline and
  that is a maintenance decision, not a technical one.
- **Resolution (2026-07-27):** yes — the review of this change found the suite
  skipping silently in both CI jobs, the exact failure mode ADR-022 exists to
  kill. Three mechanisms close it: the `quality` job installs jsdom
  (`npm install --prefix tests/js`) so the pytest wrapper executes the suite;
  the Docker `test` stage installs Node/npm and jsdom, since its own contract
  is that nothing may skip; and the `node_with_jsdom` fixture now fails —
  not skips — under `DEEPDUB_QC_REQUIRE_TOOLCHAIN=1`, mirroring
  `weasyprint_native`, so removing either install breaks the gate loudly.

## ADR-024: Console review remediation — fail-closed guards and shape-aware patching

- **Status:** Accepted (2026-07-27)
- **Context:** A recall-focused review of the console found four defects in
  `app.js` and three fail-open/driftable mechanisms elsewhere. The common
  thread: guards that existed as markup or convention rather than mechanism.
  (1) The `data-confirm` cancel guard failed OPEN if `app.js` did not load.
  (2) `patchElement` index-patched on equal child *counts* alone, so a
  pending→running transition under held focus spliced stage text into the
  wrong elements and stripped the live region's aria attributes; it also never
  synced attributes, leaving a focused form's `data-confirm` stale.
  (3) Per-button copy listeners re-bound after every focus-preserving patch,
  stacking one duplicate per poll tick. (4) The media browser rendered
  `/browse` error responses as an empty folder and pushed the failed
  destination onto the back stack. (5) New jobs were appended to the bottom of
  the newest-first table. (6) The Dockerfile carried a second, driftable copy
  of the base digest as an ARG default. (7) `install-service.ps1` documented
  `--no-dev` but accepted any venv containing the entrypoint.
- **Decision:** Make every guard mechanical and fail closed. Cancel buttons
  ship `disabled` with `data-requires-js`; `app.js` enables them only after
  the confirmation delegation is bound, and re-enables replacements arriving
  via polls. `patchElement` requires matching tag shape per index (not just
  counts) before positional patching, syncs attributes on every patched child
  (safe even on the focused path), and never swaps nodes, preserving live
  regions and focus identity. Copy buttons use one delegated document-level
  listener, like `data-confirm`. The browser checks `r.ok`, renders the
  server's error in the listing, and mutates the history stack only on
  successful navigations. `patchRows` walks the server's row order with an
  insertion cursor. The Dockerfile declares `BASE_IMAGE`/`BASE_DIGEST` with no
  defaults, so `environment.lock` is the single source and a plain
  `docker build .` fails at `FROM` instead of building a divergent base.
  The Windows installer runs `uv sync --frozen --no-dev` itself. Integration
  modules declare `pytest.mark.requires_toolchain`, derived in
  `tests/conftest.py` from `REQUIRED_TOOLS`, replacing per-module
  `shutil.which` guards that had already drifted.
- **Consequences:** Without JavaScript the Cancel button is inert rather than
  unguarded — acceptable for a console that is JS-dependent throughout. The
  jsdom suite grew regression cases for each defect (46 checks) and crashes
  loudly against the pre-fix script. A deliberately narrower guard remains in
  `test_ebu_conformance.py` (ffmpeg only), now annotated as intentional.

## ADR-025: Vidchecker template library imported as generated draft presets

- **Status:** Accepted (2026-07-27)
- **Context:** The production Vidchecker 8.2.2 instance holds 59 templates —
  7 Deepdub-authored (TOPIC, Vanda, marimba, internal) and ~50 Telestream
  factory templates (ARD/ZDF, DPP/AS-11, PBS, NPO, Netflix, Amazon, iTunes).
  Replacing Vidchecker requires these to exist here as selectable presets.
  Hand-translation (the marimba precedent) does not scale to 59, and many
  Vidchecker checks (MXF structure, GOP/SPS-PPS, IMF/Photon, PSE, dual mono,
  clicks-and-pops) have no implemented detector yet. Alternatives considered:
  (a) hand-translate on demand — slow, and the library is never visible;
  (b) import everything with rules over planned parameters — rejected,
  presets referencing unimplemented parameters are validation errors by
  design (ADR-021); (c) generate presets from the template export, restricted
  to implemented parameters, documenting every gap.
- **Decision:** (c). The raw SOAP export (`templates-combined.xml`, index,
  notes) is committed under `presets/_sources/vidchecker/` as the
  authoritative source artifact. `scripts/import_vidchecker_templates.py`
  translates each template into one draft preset: Deepdub-authored templates
  land under their clients (`topic`, `vanda`, `marimba`, `deepdub-internal` —
  attribution confirmed by the operator), factory templates under
  `presets/library/vidchecker/` with client `vidchecker-library`, which the
  existing client-grouped picker renders as its own optgroup with no UI
  change. Translation policy: `RejectOnError=true` → blocking error, else
  non-blocking warning; 1-based track selectors → 0-based stream indices,
  with the single-group-on-track-1 idiom widened to all audio streams
  (marimba precedent); bit depth and chroma subsampling checked via the
  codec/pixel-format tokens until their parameters are implemented. Checks
  with no implemented counterpart are written into the preset header and the
  generated coverage report (`docs/vidchecker-import.md`) — never silently
  dropped, and an unknown check type crashes the importer. Templates 115/116
  keep their refined hand translations; zero-rule templates are skipped and
  listed. The importer never overwrites an existing preset without `--force`,
  so post-generation human refinement survives re-runs.
- **Consequences:** 52 generated presets (all `status: draft`; thresholds
  remain human-reserved per handoff section 30) join the picker immediately.
  The coverage report doubles as the detector-gap backlog for real Vidchecker
  parity. Factory presets exercise only the implemented subset of their
  source templates — the header makes the gap explicit on every file, so a
  passing verdict cannot be mistaken for full spec conformance. The XML
  archive (840 kB) lives in the repo; acceptable for a text artifact that
  regeneration and audits depend on.

## ADR-026: Dual-mono detection as a standalone single-purpose detector

- **Status:** Accepted (2026-07-27)
- **Context:** Five of the seven Deepdub Vidchecker templates enable Dual
  Mono detection; `audio.duplicate_channel_risk` was planned with no
  detector. The measurement needs per-channel taps and per-pair difference
  signals (`pan` computing `cA-cB`), which requires an ffmpeg
  `-filter_complex` graph — inexpressible inside the consolidated
  `-filter:a` chain of `audio.analysis.ffmpeg` (ADR on RISKS R9 consolidated
  three decodes into one). Folding it into that chain is possible
  (`asplit` + a second `astats` instance) but makes every astats parse
  instance-scoped: the existing clipping parser takes the *last* `Overall`
  block, which a second instance would silently corrupt. Alternatives:
  (a) refactor the consolidated detector now; (b) a standalone detector
  with its own decode.
- **Decision:** (b). `audio.dualmono.ffmpeg` decodes each multichannel
  stream once through per-channel and per-pair `pan` branches merged into a
  single probe stream measured by one `astats`, so one parse yields every
  channel and pair RMS in deterministic order. Measurement definition
  (detector constants, not client policy): a pair is a duplicate when its
  difference RMS is <= -80 dB AND at least one channel exceeds -60 dB RMS
  (silent pairs are silence, not dual mono); streams wider than 8 channels
  compare their first 8; mono streams emit `false` so all-stream rules do
  not degrade to SKIPPED. Whole-stream measure — Vidchecker's windowed
  variant is documented as not replicated (parameter limitations).
- **Consequences:** Multichannel audio is read a second time per stream.
  The templates that enable this check are audio-only WAV deliveries, so
  the added read is small today; if R9-class runtimes regress on large A/V
  masters, the known follow-up is consolidating into the single-pass chain
  with instance-scoped astats parsing (detector replaceability, ADR-010,
  keeps presets untouched). Parity validation against real Vidchecker
  dual-mono alerts is outstanding (docs/VALIDATION.md).

## ADR-027: Watch folders as a config-declared, in-process polling watcher

- **Status:** Accepted (2026-07-27); spec: docs/watch-folders-spec.md
- **Context:** Every job requires manual console/CLI submission, but
  file-based QC operations run on drop folders (Vidchecker's dropboxes are
  its automation backbone). Alternatives considered: (a) OS filesystem
  notifications — unreliable on the UNC/SMB shares the RDP host reads from;
  (b) a separate watcher process/service — a second lifecycle to install,
  monitor and version on the host; (c) runtime CRUD of folders via the
  console — adds a mutating admin surface with no authentication story
  beyond RDP login.
- **Decision:** A single polling watcher thread inside the existing server
  process (Worker's lifecycle twin), declared in `server.yaml` under
  `watch_folders:` — versionable config, no new admin surface, strict
  validation at startup (unknown preset or folder outside media_roots
  refuses to start). Files enqueue through the normal `JobStore.enqueue`
  path with `watch:<name>` provenance only when stable (identical size and
  mtime across two consecutive scans plus a settle window), so files still
  copying never trigger. A persistent `watch_seen` table (path -> size,
  mtime) makes restarts safe and makes a changed file at the same path a
  deliberate re-delivery, enqueued with `duplicate_override`. Failures
  degrade per folder (unreachable directory, preset that stopped loading,
  full queue -> deferral, parked after repeated failures) and are visible
  in a read-only console panel; the watcher loop itself never dies. v1
  never moves or deletes inputs; a missing directory is an error state,
  not an empty folder — `glob` on a vanished share must not read as
  "no files today".
- **Consequences:** Operators get hands-off QC with the existing queue,
  concurrency and reporting unchanged. Folder changes require a service
  restart (accepted: config is the single source of truth on this host;
  runtime CRUD is a future phase). Verdict-based routing and completion
  webhooks are designed-for (reserved config keys) and land in the
  follow-up. Cloud bucket watchers remain out of scope until the tool
  leaves the RDP host.

## ADR-028: Verdict routing and completion webhooks as a post-terminal worker step

- **Status:** Accepted (2026-07-28); spec: docs/watch-folders-spec.md §10
- **Context:** Watch folders (ADR-027) automate intake, but results still
  require a human to look at the console: nothing tells downstream systems a
  file passed, and processed files pile up in the dropbox. Vidchecker's
  dropboxes move inputs to pass/reject folders that downstream automation
  watches. Alternatives considered: (a) routing policy in presets — rejected,
  presets describe media requirements, not site plumbing (ADR-003), and one
  preset serves many folders; (b) a separate notifier process tailing the
  store — a second lifecycle for a step that is causally tied to job
  completion; (c) routing inside the pipeline — would give QC code the power
  to move inputs, violating the measure/decide/render separation.
- **Decision:** A `PostCompletion` hook (`server/routing.py`) the worker
  invokes strictly AFTER the terminal store write, for COMPLETED and FAILED
  jobs only. Policy lives on the `WatchFolderEntry`: `on_pass`/`on_warning`/
  `on_reject` each take exactly one of `move_to`/`copy_to`; unset means
  leave-in-place with no fallback between verdicts; ERROR never routes.
  Destinations must exist at startup, sit inside `media_roots`, and be
  outside the folder's scanned area (self-loop guard); collisions get a
  `_1`/`_2` suffix. `webhook_url` POSTs the outcome with the full
  report.json verbatim (ADR-002) via httpx (already a dependency), 10 s
  timeout, retries on connection errors/5xx only; URLs may embed tokens so
  logs and progress notes carry only the host. Every outcome is recorded as
  a progress note on the job; any failure here degrades — it can never
  change a verdict, fail a job, or kill the worker. Manual submissions
  never route or notify.
- **Consequences:** The RDP host is fully unattended: drop → QC → file lands
  in a verdict folder → downstream system is notified. Webhook delivery
  blocks the single worker for at most ~36 s worst-case (accepted against
  multi-minute jobs; a delivery queue is the follow-up if that regresses).
  Chaining dropboxes (route into another watch folder) is possible and
  deliberate; accidental cycles self-limit via `watch_seen` dedup since
  moves preserve size and mtime.

## ADR-029: Stage-weighted progress fractions for the console wheel

- **Status:** Accepted (2026-07-28)
- **Context:** Running jobs showed only a stage log and an indeterminate
  spinner; operators watching a long master had no sense of completion. A
  true time-based percentage (parsing ffmpeg `-progress` against media
  duration) would require streaming-stderr surgery on the deterministic
  subprocess utility (which owns the kill registry for cancel/timeout) and
  threading progress callbacks into detectors - detectors measure, they do
  not report UI state (ADR-001 separation).
- **Decision:** The pipeline - the only layer that knows the stage plan -
  reports `(message, fraction)` through the existing on_progress callback.
  The fraction is STAGE-weighted: each applicable detector and each fixed
  post-stage (rules, evidence, hashing, rendering) is one unit; skipped
  stages still count so the denominator never lies. Monotonic and honest
  about work completed, silent about time remaining. The worker stores it
  as a display-only `percent` on progress events (never canonical, never
  in report.json); the console renders a server-side SVG ring on the job
  detail page plus a percent suffix in the jobs-list chip, both updated by
  the existing poller with zero new client JS. Events without a percent
  (pre-wheel rows) render the plain chip - absence of data must not look
  like a stalled job.
- **Consequences:** The wheel advances in steps at stage boundaries; a
  single long ffmpeg decode holds it still (the spinner still signals
  activity). If operators need within-stage motion, the known follow-up is
  ffmpeg `-progress` streaming confined to utils.subprocess with the
  fraction interpolated inside the current stage unit - the callback
  contract already carries it.

## ADR-030: Master presets synthesized from the corpus; Vidchecker library demoted to reference

- **Status:** Accepted (2026-07-28); spec: docs/master-preset-spec.md
- **Context:** The Vidchecker import (ADR-025) put 53 presets in the submit
  picker. Post-production feedback: a massive preset list is unhelpful —
  deliveries should run against one well-known, easily edited master.
  Alternatives considered: (a) one combined master — rejected, video rules
  against a WAV drown the report in NOT_APPLICABLE noise; (b) deleting the
  library — rejected, it seeds master defaults and remains the parity record
  for Vidchecker shadow validation; (c) hand-writing master defaults —
  rejected, 774 corpus rules encode real client policy that should be
  measured, not remembered.
- **Decision:** Two masters (`master_video`, `master_audio`, client
  `deepdub`, under `presets/master/`), generated by
  `scripts/build_master_presets.py` from the imported library plus the
  hand-refined client presets: one rule per implemented parameter, the most
  common (operator, expected, scope) variant wins deterministically, and
  every disagreement is written into a `# corpus values:` comment above the
  rule so the approving engineer reviews the spread, not just the winner.
  Severity/blocking are voted as a PAIR (independent majorities can invent a
  combination no corpus preset has). Masters ship DRAFT — approval is the
  human act this feature exists to make easy (§30). The catalog gains a
  `listed` flag: presets under `presets/library/` are unlisted — absent from
  the submit picker (which now pins the masters' group first), still on the
  governance page under a collapsed reference group, and still loadable by
  watch folders, the API and the CLI. Regeneration refuses to overwrite
  without `--force` (same contract as the importer).
- **Consequences:** The picker drops from ~53 entries to ~10. Master
  defaults are reviewable in one file per content type instead of 53. The
  console preset editor (ADR-031, PR B) builds on exactly this: editing a
  master produces a new draft version, never a silent change.

## ADR-031: Console preset editor — every save is a new draft version

- **Status:** Accepted (2026-07-28); spec: docs/master-preset-spec.md §5
- **Context:** The master presets (ADR-030) only pay off if the A/V engineer
  can change thresholds without YAML. Alternatives considered: (a) in-place
  editing of draft files — rejected, it destroys the audit trail and breaks
  determinism ("which preset judged this file" must have one answer);
  (b) unversioned per-job overrides — rejected by the operator (spec §8:
  versioned saves); (c) a full YAML editor in the browser — over-scoped and
  invites structural mistakes the form cannot make.
- **Decision:** `server/editor.py` + a server-rendered editor page (no new
  client JS). The editor changes VALUES only: expected payload fields
  (value/values/min/max/tolerance/pattern), severity, blocking, enabled —
  operators, scoping and new rules remain YAML work. Disabling uses the rule
  model's native `enabled` flag, so the rule stays in the file. Every save
  writes a NEW file: minor version bump, status draft, `supersedes` set,
  provenance header (who/when/base/note; a name is mandatory), and the text
  round-trips through the real preset loader under a temp name before it can
  reach its final one — an invalid edit leaves the directory untouched. A
  save carries its base version and is rejected (409) when a newer version
  exists: last-write-wins is unacceptable for QC policy. On success the
  in-process catalog refreshes, so the new draft is submittable immediately,
  and the GUI re-renders validation failures with the operator's typed
  values intact. Approved presets are never touched: the same editor drafts
  their successor ("New draft" is the only difference). Editor-created files
  land under presets_root (on the RDP host: the git checkout — `git status`
  is the audit; committing them back is a maintenance duty, spec §6).
- **Consequences:** Threshold review becomes a form, not a YAML lesson;
  ADR-013 governance is unchanged (drafts everywhere until `presets lock`).
  Comments from the base file (including ADR-030's corpus-spread comments)
  do not survive a save — the base version file remains on disk as the
  reviewable record. Concurrent editors get honest conflicts instead of
  silent overwrites.
