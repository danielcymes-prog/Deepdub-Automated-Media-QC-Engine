# CLAUDE.md — Operating Rules for AI-Assisted Development

Read `DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md` and `docs/DECISIONS.md` before making
architectural changes. Record new architectural decisions as ADRs in
`docs/DECISIONS.md` (context, alternatives, decision, consequences).

## Non-negotiable principles

1. **AI explains. Software measures. Rules decide.** AI must never invent
   measurements, decide pass/fail, or alter canonical findings (ADR-001).
2. **Strict separation:** detectors measure; the rule engine evaluates;
   reports render. Detectors never see thresholds; rules never see clients;
   renderers only consume `QCResult` (docs/ARCHITECTURE.md section 4).
3. **No client-specific code.** Client behavior lives only in versioned YAML
   presets (ADR-003). Never write `if client == ...`.
4. **`report.json` is the source of truth** (ADR-002). HTML/PDF are renderings.
5. **Determinism** (ADR-008): content-derived IDs, declared volatile fields,
   pinned FFmpeg. Same input + preset + environment = identical canonical output.

## Development behavior

- Work in small, reviewable commits.
- No new dependencies without documenting why (ADR entry).
- Add or update tests for every behavior change; never silently relax a
  failing test; every bug fix gets a regression test.
- Type hints everywhere; keep public functions documented (why, inputs,
  outputs, side effects).
- Structured logging only; never `print()` in application code. Never log
  secrets, tokens, signed URLs, or full environments.
- Subprocesses: argument arrays, explicit timeouts, captured stdout/stderr,
  no `shell=True`, raw output preserved.
- Streaming for media files; never assume media fits in RAM.
- Do not bypass schema validation. Regenerate schemas via `make schemas`
  after model changes and commit the result.

## Required validation before completing any task

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run python scripts/export_schemas.py --check
```

## Completion requirements

Before marking a milestone complete: run the tests, report failures honestly,
update documentation, summarize changed files, list remaining risks. Never
claim success for untested behavior.

## Decisions reserved for humans (handoff section 30)

Client thresholds, blocking vs warning severity, channel mappings, external
AI data transmission, queue/storage/auth technology, retention policy, and
report client-identification. Use visible placeholders until approved.
