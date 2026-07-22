# Risk Register (Phase 0)

Impact/likelihood: H/M/L. Owner defaults to engineering unless noted.

## Technical risks

**R1. FFmpeg version drift breaks determinism (H/H).**
Filter outputs (`ebur128`, `blackdetect`, `silencedetect`) change subtly between FFmpeg releases; the same file can yield different measurements on different machines.
*Mitigation:* Pin FFmpeg in Docker (ADR-008); record versions in every result; treat FFmpeg upgrades as releases with full golden-corpus re-runs; CI determinism test runs inside the pinned image.

**R2. Loudness accuracy vs. Vidchecker/Dolby disagreement (H/M).**
Clients compare our LUFS numbers against Vidchecker's. Divergence past ~0.1 LU erodes trust in the whole tool.
*Mitigation:* Validate `ebur128` against EBU R128 reference test vectors in M4; build the Vidchecker comparison harness (backlog #32); document known measurement deltas per check.

**R3. Parsing fragile FFmpeg text output (M/H).**
`blackdetect`/`freezedetect`/`silencedetect` emit unstructured stderr text, not JSON.
*Mitigation:* One parser per detector with raw output always preserved; parser unit tests against captured fixtures per pinned FFmpeg version; parse failures ⇒ `ERROR` finding, never a silent pass.

**R4. WeasyPrint native dependencies (L/M).**
Pango/Cairo installs vary across dev machines.
*Mitigation:* Docker is canonical (ADR-007/008); document local install; PDF renderer behind an interface.

**R5. Synthetic golden corpus doesn't reproduce real failure modes (M/M).**
Generated test media may miss the artifacts real deliveries exhibit (encoder quirks, truncation patterns).
*Mitigation:* M0 collects real passing/failing files; corpus mixes synthetic + sanitized real media; every field-discovered bug adds a regression fixture.

## Architecture risks

**R6. Layering erosion (M/M).**
Under deadline pressure, detectors grow threshold knowledge or the rule engine learns about clients — the exact failure mode that makes Vidchecker-class tools unmaintainable.
*Mitigation:* import-linter rules in CI (backlog #30); ADR-001/003 as review checklist; preset schema forbids executable logic.

**R7. Report contract instability after detectors exist (M/M).**
Changing the `QCResult` schema post-M3 ripples through renderers, golden files, and (later) Composer.
*Mitigation:* Report-first order (ADR-011); stakeholder sign-off gate in M2; schema versioning with drift tests (ADR-004).

**R8. Phase 7 infra unknowns (M/M).**
Queue, storage, and auth must reuse existing Deepdub infrastructure (handoff §5.3/§30), which is undocumented in this repo.
*Mitigation:* Human decision requested before M7 planning; core stays library-first (ADR-010) so any worker model wraps it; no Celery/Redis introduced unilaterally.

## Performance and scalability risks

**R9. 100 GB masters, slower-than-real-time analysis (H/M).**
Full-file audio+video analysis of ProRes masters can take hours if each detector decodes independently.
*Mitigation:* Streaming-only design (never load media into RAM); measure and record runtime from M3; plan a shared single-decode filtergraph for M4/M5 detectors where safe; configurable max-file-size/max-duration guards (§20); parallel detector execution is a designed-for optimization, not an MVP feature.

**R10. Evidence generation cost (M/L).**
Thumbnails/clips for incident-heavy files can dwarf analysis time.
*Mitigation:* Evidence capped per finding and configurable per preset (`report.include_evidence`); generated only for non-PASS findings.

**R11. Preset sprawl (M/M — grows with client count).**
Dozens of near-duplicate client presets with unmanaged thresholds.
*Mitigation:* M6 approval workflow + immutability; defer preset inheritance until ≥3 real presets exist and the duplication pattern is visible (avoid speculative resolver complexity).

## Unknowns needing human input (handoff §30)

- First client preset and real thresholds (blocks M0 exit, not M1–M3).
- Whether reports may contain client-identifying info (blocks report header design — placeholder until answered).
- Existing Deepdub queue/storage/auth stack (blocks M7 design only).
- Data-retention policy for job outputs and evidence.
- Sanitized real media availability for the golden corpus (R5).
- Whether any AI provider may ever receive report content (blocks M9; default: no).
