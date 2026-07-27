# Phase Entry Review — 2026-07-26

Incoming-architect review of the repository against
`DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md`, `docs/DECISIONS.md`, `docs/ARCHITECTURE.md`
and `docs/ROADMAP.md`. Purpose: establish an honest baseline before the next
phase of work is scoped. No code was changed.

---

## 1. Verification basis

Read in full: handoff (all 34 sections), `CLAUDE.md`, `ARCHITECTURE.md`,
`DECISIONS.md` (ADR-001…014), `ROADMAP.md`, `BACKLOG.md`, `RISKS.md`,
`VALIDATION.md`, `DATA_MODEL_REVIEW.md`, `README.md`, `server-gui-spec.md`,
`Dockerfile`, `pyproject.toml`, `.github/workflows/ci.yml`. Audited the import
graph and all 7,528 lines under `src/deepdub_qc/`. Inventoried 271 test
functions across 29 test modules.

**Not verified — must be run on the host:**

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
uv run python scripts/export_schemas.py --check
```

The review environment has only Python 3.10 and no network access to fetch
3.13, so the gate in `CLAUDE.md` could not be executed. Every claim below is
from static reading, not from a green test run.

---

## 2. State of the build

M1–M6 are delivered and M6.5 (Phase 3.5 server + operator GUI) is
functionally complete: `serve`, SQLite queue, single worker, session cap,
Composer-shaped API, Playwright/WeasyPrint PDF split, Windows service
installer. Beyond the roadmap there is also a batch runner
(`orchestration/batch.py`) and a Vidchecker comparison harness
(`comparison/`), plus three real client preset families (alphorn, marimba,
njarka).

**The working tree is dirty.** Five modified files and an untracked
`src/deepdub_qc/server/static/fonts/` directory (brand rebrand work) are
uncommitted. Phase 3.5 is not closed out.

### Architectural health: strong

Every hard rule in `ARCHITECTURE.md` §4 holds:

- `rules/` does not import `detectors/`; `detectors/` does not import
  `presets/`; `reports/` touches only model types; `models/` imports only
  stdlib and Pydantic.
- Zero occurrences of any client name (`alphorn`, `marimba`, `njarka`,
  `netflix`) anywhere in `src/`.
- All eight `DATA_MODEL_REVIEW.md` required changes are implemented, including
  the ones most easily skipped: `Environment` block (`models/report.py:56`),
  preset byte hash (`models/report.py:53`), and the `SKIPPED`/`NOT_APPLICABLE`
  distinction with blocking-`SKIPPED` escalation to `ERROR`
  (`rules/engine.py:317`) — a QC tool that refuses to pass a file it failed to
  inspect.
- Subprocess discipline is clean: `shell=False` is the only `shell=` in the
  tree (`utils/subprocess.py:118`), every ffmpeg/ffprobe call routes through
  `run_tool()`, all with explicit timeouts.
- `mypy strict = true` with exemptions only for `weasyprint.*` and
  `playwright.*`. No `print()`, no bare `except:`, no TODO/FIXME markers in
  application code.

The separation the handoff is built around — measurements are facts, rules
decide, reports render — has been held under six milestones of pressure. That
is the hard part and it was done well.

---

## 3. Gaps that matter, ranked

### G1 — CI does not install FFmpeg, so no end-to-end behavior is tested (High)

`ci.yml` installs Pango for WeasyPrint but never FFmpeg. Every integration
test is guarded by `skipif(shutil.which("ffmpeg") is None)`
(`tests/integration/test_analyze_e2e.py:30`, `test_audio_e2e.py:24`,
`test_video_e2e.py:21`, `test_batch_e2e.py:27`, `test_serve_e2e.py:30`,
`test_ebu_conformance.py:35`). All of them skip in CI. The `docker` job runs
only `deepdub-qc version`, not an analysis.

Consequence: CI enforces unit-level correctness only. The detectors, the
pipeline, the report renderers on real media, and the whole server stack are
covered by tests that never execute on a merge. `pytest -q` reports green
while testing none of it.

*Fix:* add `apt-get install ffmpeg` to the quality job, or better, run the
integration suite inside the Docker image so it exercises the canonical
environment. Small change, largest single confidence gain available.

### G2 — FFmpeg is not actually pinned (High)

`ADR-008`, `RISKS.md` R1, `ARCHITECTURE.md` §6, and `README.md` all state that
FFmpeg is pinned in Docker. It is not. `Dockerfile:6` uses the floating tag
`python:3.13-slim-bookworm` and `Dockerfile:12` installs unversioned `ffmpeg`
from the Debian repository. The Dockerfile comment is candid that the pin is
deferred ("At release time, pin this image by digest"), but four other
documents assert it as fact.

Consequence: the determinism baseline the project's credibility rests on is
aspirational. A rebuild months apart can silently change `ebur128`,
`blackdetect` and `silencedetect` output — exactly R1.

*Fix:* pin the base image by digest and the ffmpeg package by version, record
both in the release notes, and correct the four documents. Small.

### ~~G3 — No determinism test~~ — WITHDRAWN, I was wrong (Low)

**Correction (same day, before any code was written).** My first pass claimed
backlog #22 was unstarted. It is not. `TestDeterminism::
test_repeat_runs_identical_modulo_volatile_fields`
(`tests/integration/test_analyze_e2e.py:111-131`) runs `analyze` twice with
fixed job ids, masks exactly the five volatile fields ADR-008 declares
(`test_analyze_e2e.py:97`), and compares sorted-key JSON. That is precisely
what backlog #22 specifies, and it is a correct implementation.

The error was mine: I grepped for `determinis` and truncated the output with
`head -20`, which cut the integration-test hits. The lesson is that the
finding was based on absence of evidence produced by my own tooling — I should
have read the integration tests before asserting a missing test.

What remains true, and is a much smaller point: the test only executes when
ffmpeg is on PATH, so **it skips in CI** — which is G1, not a separate gap.
Backlog #22 is also still unticked in `BACKLOG.md` despite being done, which
is what made the claim plausible.

*Fix:* nothing to build. Tick backlog #22, and let G1 make the existing test
actually run. The determinism guarantee is better covered than I first stated.

### G4 — No parameter catalogue and no parameter registry (High)

Handoff §15 requires `docs/parameter-catalogue.md` plus a machine-readable
registry. Neither exists. The only parameter knowledge in code is a
prefix-to-category map (`rules/engine.py:31-40`); nothing validates that a
preset's `parameter_id` corresponds to a parameter some detector actually
emits (`presets/` has no `parameter_id` handling at all — the string appears
only in `models/rule.py:157`).

Consequence: a typo or an aspirational `parameter_id` in a client preset
passes `presets validate` cleanly, then produces a `SKIPPED` finding at
runtime. A blocking rule escalates to `ERROR` and is caught — but a
**non-blocking rule silently becomes SKIPPED**, and the operator sees a report
that looks complete while a check they believe is running never ran. This is
the closest thing in the codebase to a silent pass, and it will bite as
non-engineers author presets.

*Fix:* a registry module that detectors declare into (they already declare
`parameters` on the `Detector` interface), validated at preset-load time with
an actionable error; generate the catalogue doc from it. Medium, and I would
put it first on correctness grounds.

### G5 — Real Deepdub asset shapes are not yet measurable (High, product)

`VALIDATION.md:71-99` documents the finding that matters most commercially:
on multi-mono localization masters — "the dominant Deepdub asset shape" —
Vidchecker produced **zero measurements** on two different clients' real
deliveries, while deepdub-qc measured all eight tracks. That is the
differentiator, and it is already demonstrated.

But the follow-up is unbuilt. Filename targets like `-27LU` apply to the 5.1
program measured jointly with ITU-1770 weighting, not per mono track
(`VALIDATION.md:97-99`). Backlog #35 (audio groups, channel-role-aware
selectors so LFE is exempt from loudness bounds) is the gap between "we
measure more than Vidchecker" and "our numbers are the ones the client's spec
is written against." Until it lands, the alphorn AD preset produces a WARNING
on the LFE track that is correct behavior but wrong answer.

*Fix:* backlog #35 as specified. Large-ish, and the highest-value engineering
item on the board.

### G6 — Validation rests on three different FFmpeg versions (Medium)

`VALIDATION.md:13` records the Vidchecker parity run on ffmpeg
`N-121567-g00c23bafb0`; `VALIDATION.md:67` records EBU Tech 3341/3342
conformance (68/68) on ffmpeg 4.4.2 in a dev sandbox; the Docker image ships
whatever bookworm currently has (G2). Three different toolchains behind the
project's accuracy claims, none of them the canonical one.

**Partial correction.** My first pass added that "the EBU test set is not in
the repository, so the suite skips silently for anyone who hasn't fetched it
manually," implying an oversight. It is a deliberate, documented decision:
`tests/fixtures/ebu/README.md` records that EBU licenses the material for
technical testing only, `.gitignore:31-32` excludes just the WAVs, the
expected values live in the committed `ebu_manifest.yaml`, and the fixtures are
present on this machine. I re-ran the suite while writing this review and all
**68 vectors pass in 9 seconds** on ffmpeg 4.4.2. So "cannot be reproduced on
demand" was wrong — it reproduces immediately for anyone holding the set.

What remains: the conformance evidence has never been produced on the pinned
image, and no CI job gates on it, so a future FFmpeg bump would not be caught
by the strongest accuracy test the project owns.

*Fix:* re-run both on the pinned image now that G2 has landed; add a
conformance job that fails, rather than skips, when the fixtures are absent —
with the WAVs supplied out of band to respect the licence.

### G7 — Layering is convention-only (Medium)

Backlog #30 (import-linter in CI) is unstarted; `ARCHITECTURE.md:122` admits
the rules are "enforced by review and, later, import-linter". The boundaries
are currently intact, which makes this the cheapest possible moment to
mechanize them — R6 predicts erosion under deadline pressure, and the project
now has more surface (`server/`, `comparison/`) than when the rules were
written.

*Fix:* `importlinter` contracts in `pyproject.toml` + a CI step. Small.

### G8 — Phase 3.5 acceptance criteria unverified on the target platform (Medium)

`server-gui-spec.md` §10 lists ten criteria. Three cannot have been met in a
Linux dev environment: #2 (GUI job byte-identical to CLI job), #8 (FFmpeg
process tree verified terminated on Windows, no orphaned `ffmpeg.exe`), #10
(all acceptance tests pass on Windows with media on a UNC path). Note that
`utils/subprocess.py:27-29` reasons correctly that ffmpeg spawns no children
so killing the direct child suffices — but that reasoning has not been
exercised on Windows, where `Popen.kill()` semantics differ.

*Fix:* a scripted acceptance run on the RDP host before Phase 3.5 is called
done.

### G9 — Documentation drift (Low, but corrodes trust in the docs)

- `README.md:13-20` says "Milestone 6 … Next: service extraction (M7)".
  `ROADMAP.md:67-82` says M6.5 is active and M7 is deliberately deferred until
  after it.
- `ARCHITECTURE.md:3` still reads "Status: Phase 0 baseline". Its subsystem
  table (§2), data-flow diagram (§1) and layering rules (§4) do not mention
  `server/` or `comparison/` at all — two of the largest packages in the tree
  (1,608 and 510 lines).
- ADR-006 decides against a `docs/adr/` directory, yet
  `docs/adr/0004-local-web-gui-on-shared-rdp-host.md` exists. ADR-014
  acknowledges the duplication rather than resolving it.
- Handoff §6 specifies six docs that do not exist:
  `parameter-catalogue.md` (see G4), `detector-development.md`,
  `preset-authoring.md`, `report-contract.md`, `testing-strategy.md`,
  `composer-integration.md`. `preset-authoring.md` matters most — preset
  authoring is the designed extension point for non-engineers.

### G10 — Whole check categories absent (Low for now, by design)

No subtitle QC beyond `subtitle.stream_count`
(`detectors/metadata/ffprobe.py:265`) — none of the 13 subtitle parameters in
handoff §15.4 (overlap, CPS, zero-duration, out-of-bounds) are implemented.
No `detectors/deepdub/` at all — the eleven §15.5 parameters that constitute
the Composer-state QC advantage. No waveform evidence (thumbnails only).
No `evidence/waveforms.py`, no `utils/timecode.py` (timecode formatting lives
in `reports/html_renderer.py:83-99`, which is a layering smell: derived-time
logic belongs in `utils/`, not the renderer).

---

## 4. Human decisions still outstanding

From handoff §30 and `RISKS.md`, unchanged since Phase 0:

1. Real client thresholds — all three client preset families remain `draft`.
   No approved preset exists, so `presets/approved.lock.json` protects
   nothing yet and ADR-013's CI enforcement is untested against a real
   approval.
2. Blocking vs warning severity per check.
3. Channel mappings / audio group definitions (blocks G5).
4. Whether reports may carry client-identifying information —
   `server-gui-spec.md:194` re-raises it for the shared console.
5. Deepdub queue / storage / auth stack (blocks M7 design).
6. Data-retention policy for job outputs and evidence.
7. Whether any AI provider may ever receive report content (default: no).
8. The five Phase 3.5 open questions in `server-gui-spec.md` §11.

---

## 5. Recommended sequencing

Before new scope, a short hardening pass — every item small, and together they
convert the project's central claims from asserted to tested:

| # | Item | Gap | Size | Status |
|---|---|---|---|---|
| 1 | FFmpeg in CI; run integration suite in the Docker image (this alone activates the existing determinism test) | G1, G3 | S | **done** (ADR-022) |
| 2 | Pin base image by digest + assert the ffmpeg version; fix the four docs | G2 | S | **done** except the version token — needs `make pin-ffmpeg` on a Docker host |
| 3 | Parameter registry + preset-load validation + generated catalogue | G4 | M | **done** (ADR-021) |
| 4 | import-linter contracts in CI | G7 | S | **done**, 6 contracts, all passing |
| 5 | Commit the brand work; scripted Phase 3.5 acceptance run on the RDP host | G8 | S | open — needs the RDP host |
| 6 | Refresh README status, ARCHITECTURE (add `server/`, `comparison/`), resolve ADR-006; tick backlog #22 | G9 | S | **done** except ADR-006 vs `docs/adr/` |

Then the substantive next phase. The three candidates are not equivalent:

- **Audio groups (backlog #35, G5)** — closes the gap between what we measure
  and what client specs actually specify, on the asset shape that dominates
  Deepdub's catalogue and that Vidchecker demonstrably cannot handle. Highest
  commercial value; validated against two real client masters.
- **Deepdub-specific detectors (§15.5)** — the North Star differentiator
  (Composer project-state QC, segment coverage, unresolved markers). Needs
  Composer data access, so it likely needs M7 first.
- **M7 service extraction** — blocked on infra decisions (§30 items 5), and
  `ROADMAP.md:78-81` deliberately sequences it after the GUI.

My recommendation: items 1–5 of the hardening pass first (roughly a week,
mostly CI and one medium module), then backlog #35. Deferring the hardening
means every subsequent measurement claim inherits an unpinned toolchain and an
untested reproducibility guarantee — the two things a broadcast engineer would
ask about first.

---

## 5a. What was actually implemented on 2026-07-26

Items 1–4 and most of 6 are done. Recorded as ADR-021 (parameter catalogue) and
ADR-022 (canonical environment and test run).

**Verified in this environment:** `ruff format --check` and `ruff check` clean
across `src`, `scripts`, `tests`; all six import-linter contracts pass; schema
and parameter-catalogue drift checks pass; **418 tests pass, 2 skipped** (both
WeasyPrint, absent from the review sandbox), including the full integration
suite and the EBU conformance run.

**Not verified, and needs the host:** `mypy` (the sandbox has Python 3.10 and
cannot fetch 3.13; every other check was run under a shimmed 3.10 interpreter,
which is why `mypy --strict` specifically remains unrun), the Docker build and
`make docker-test`, and anything Windows-specific.

Two counts worth keeping honest: the catalogue holds 96 parameters, of which 43
are implemented — exactly the 43 the three detectors declare, verified both
directions by contract test. Enforcement broke none of the eight shipped
presets: every `parameter_id` they reference was already implemented.

**ADR numbering collision.** ADR-015 and ADR-016 were taken concurrently by
parallel console work (typefaces, shell chrome) while this pass was in flight.
Mine were renumbered to ADR-021 and ADR-022 and moved to the end of
`DECISIONS.md`; the concurrent records were left untouched. Worth a convention
if two streams keep running in parallel — claim the number in a stub commit
first.

Also noted from that concurrent work: backlog #37 identifies a real
reproducibility bug I had missed — `reports/templates/report.html.j2` imports
fonts from Google Fonts, so on an air-gapped host the fallback changes text
metrics and therefore PDF pagination. The same `report.json` can paginate
differently on two machines. That belongs on the hardening list.

---

## 6. Assessment

This is unusually disciplined work for a greenfield project six milestones in.
The invariants that make QC tools trustworthy are intact, the ADR trail
explains every deviation from the handoff, and `VALIDATION.md` records
negative and inconclusive results alongside the wins — including two cases
where the incumbent tool produced nothing to compare against, stated as
capability evidence rather than parity.

The weakness is not in the design. It is that the tests which prove the
project's central claims — determinism included — never run in CI because
FFmpeg is not installed there (G1), the pinning those claims depend on is
deferred by a Dockerfile comment while four documents assert it as fact (G2),
and preset authoring, the extension point intended for non-engineers, has no
parameter-level validation behind it (G4). All three are small-to-medium fixes
available now, while the codebase is still small enough that they are cheap.

One note on the review itself: G3 as originally written was wrong, and the
withdrawal is recorded above rather than deleted. The determinism work was
already done properly; my tooling truncated the evidence and I asserted too
early. Worth stating plainly in a document whose purpose is to establish an
honest baseline.
