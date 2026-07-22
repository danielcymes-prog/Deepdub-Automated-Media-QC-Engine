# Engineering Backlog (Phase 0)

Priorities: **P0** = blocks everything downstream · **P1** = MVP path · **P2** = post-MVP. Effort: S ≈ ≤2 days, M ≈ 3–7 days, L ≈ >1 week.

| # | Item | Pri | Effort | Depends on | Milestone | Rationale |
|---|---|---|---|---|---|
| 1 | Fix repo folder name (trailing space), `git init`, first commit | P0 | S | — | M1 | Trailing space breaks tooling/paths; no history = no reviewable increments |
| 2 | Resolve data-model changes 1–8 (`DATA_MODEL_REVIEW.md`) | P0 | S | — | M1 | Every one is a breaking schema change if deferred |
| 3 | Repo scaffold: pyproject (uv, py3.13), ruff, mypy, pytest, pre-commit | P0 | S | 1 | M1 | Foundation for all code |
| 4 | Pydantic domain models + enums | P0 | M | 2,3 | M1 | Shared vocabulary of the whole system |
| 5 | JSON Schema export + drift contract test | P0 | S | 4 | M1 | ADR-004; Composer-facing contract |
| 6 | Structured JSON logging setup | P1 | S | 3 | M1 | Required by handoff §19; cheap now, painful retrofit |
| 7 | Typer CLI skeleton (`--help`, `version`) + exit-code map | P1 | S | 3 | M1 | Entry point; exit codes are part of the public contract |
| 8 | Preset YAML loader + schema/semver validation + `presets validate` | P0 | M | 4 | M1 | Presets gate everything; validation is the first user-visible value |
| 9 | Generic example preset (`generic_broadcast_v1.yaml`) | P1 | S | 8 | M1 | Carries development until first client preset approved (M0, human) |
| 10 | Dockerfile with pinned FFmpeg + CI (ruff/mypy/pytest/docker build) | P0 | M | 3 | M1 | ADR-008 determinism baseline; no unverified merges |
| 11 | CLAUDE.md + README | P1 | S | 3 | M1 | Handoff §26 operating rules; onboarding |
| 12 | Mock QCResult fixture (realistic, incl. failures/warnings/evidence refs) | P0 | S | 4 | M2 | Permanent contract-test fixture; unblocks report work |
| 13 | HTML report template (Jinja2, printable, no JS, §17 sections) | P0 | M | 12 | M2 | The report is the product |
| 14 | PDF renderer (WeasyPrint) + `render-mock` command | P1 | S | 13 | M2 | ADR-007 |
| 15 | Report contract + golden-file tests | P0 | S | 13 | M2 | Locks JSON↔HTML consistency |
| 16 | Stakeholder report review sign-off | P0 | S | 13,14 | M2 | Cheapest moment to change the report contract |
| 17 | Safe subprocess utility (arg arrays, timeouts, captured io, typed errors) | P0 | S | 3 | M3 | Security §20; every detector uses it |
| 18 | ffprobe detector + metadata normalization + raw output preservation | P0 | M | 17,4 | M3 | First real measurements |
| 19 | Rule engine: operators, registry, SKIPPED/ERROR semantics, aggregation | P0 | M | 4 | M3 | Core decision logic; unit test per operator |
| 20 | Orchestration pipeline + `analyze` command, job dir layout | P0 | M | 18,19,13 | M3 | End-to-end MVP |
| 21 | Test-media generator script + Tier 1 golden fixtures | P1 | M | 20 | M3 | Determinism + regression safety |
| 22 | CI determinism test (repeat run, volatile-field mask, byte compare) | P1 | S | 20,10 | M3 | Makes ADR-008 enforceable, not aspirational |
| 23 | Loudness detector (single-pass ebur128: I, LRA, TP) + EBU reference validation | P1 | L | 20 | M4 | Highest-value dubbing check; validation is the long pole |
| 24 | Silence detectors (head/tail/internal) | P1 | M | 20 | M4 | Common dubbing delivery blocker |
| 25 | Clipping + duration-delta checks | P1 | S | 20 | M4 | Cheap, high signal |
| 26 | Golden audio corpus + expected-result files | P1 | M | 23,24 | M4 | Confidence for delivery decisions |
| 27 | blackdetect / freezedetect / signalstats detectors | P2 | M | 20 | M5 | Timestamped video incidents |
| 28 | Evidence engine: thumbnails (+ waveforms) | P2 | M | 27 | M5 | Reviewer trust; seek-to-issue workflow |
| 29 | Preset immutability enforcement + approval workflow + fixtures | P2 | M | 8 | M6 | Client governance |
| 30 | import-linter layering rules in CI | P2 | S | 3 | M1–M3 | Enforces ADR-010 boundaries mechanically |
| 31 | FastAPI wrapper + Postgres repository + idempotent jobs | P2 | L | M3–M6, infra decisions | M7 | Service extraction; blocked on §30 human decisions |
| 32 | Vidchecker comparison harness (`compare_vidchecker.py`) | P2 | M | 26 | M4+ | Parity evidence on checks that matter |
| 33 | Language-code normalization (ISO 639-2 B/T: ger↔deu, fre↔fra) in detector + preset validation | P1 | S | 18 | M4 | MOV muxers store B codes; dubbing presets will reference both — discovered in M3 integration testing |
| 34 | Windowed-RMS min-level detector (`audio.min_rms_level`) | P1 | M | 20 | M6+ | Vidchecker "Min Level" check (-90 dBFS RMS for 10 s) has no exact equivalent yet; marimba presets approximate it with internal-silence |

Items 1–2 are this week's work. Items 3–11 are one coherent M1 sprint.
