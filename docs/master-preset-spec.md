# Deepdub QC — Master Presets and the Console Preset Editor

- **Status:** Accepted (2026-07-28) — direction and §8 decisions confirmed by the operator
  (per post-production A/V engineer feedback). Implementation ADRs: ADR-030 (masters +
  demotion), ADR-031 (editor) as they land.
- **Related:** ADR-003 (client presets), ADR-013 (preset governance), ADR-025
  (Vidchecker import), `docs/vidchecker-import.md`, handoff §30 (thresholds are
  human decisions).
- **Audience:** the implementing engineer; the post-production engineer approving
  master defaults.

## 1. Problem and goal

The Vidchecker import (ADR-025) put 53 presets in the submit dropdown. Operator
feedback: a massive preset list is not helpful — deliveries should run against
**one well-known Master Preset that is easy to inspect and change**, with the
imported library serving as reference, not interface.

**Goal:** the dropdown offers a small number of master presets; the console can
edit a preset's thresholds/severities and save the result as a new, versioned,
draft preset — no YAML editing required for day-to-day threshold work.

**Non-goals (v1):**
- Adding new rules or changing operators/scoping in the GUI (YAML remains the
  authoring surface for structure; the editor edits *values*, not *shape*).
- Editing approved presets in place — approval and locking are unchanged
  (ADR-013); the editor always produces a new DRAFT version.
- Deleting the Vidchecker library (it seeds master defaults and remains the
  parity record for shadow validation against Vidchecker).

## 2. Master presets: two, not one or fifty-three

Two masters, mirroring how Vidchecker templates are actually used:

| Preset | id | Covers |
|---|---|---|
| Master — Video Delivery | `master_video` | container/video/audio checks for picture masters (ProRes/XDCAM/AVC-Intra deliveries) |
| Master — Audio Delivery | `master_audio` | audio-only deliveries (dubbed WAV mixes) |

One combined master was rejected: video-structure rules evaluated against a WAV
produce a wall of NOT_APPLICABLE noise and make every report longer; the
video/audio split is the natural content-type boundary every client template
already respects.

Both masters live under `presets/master/`, client `deepdub`, status **draft**
until the post-production engineer approves the defaults (§30 — the entire
point of this feature is making that review easy).

## 3. Synthesizing the defaults

`scripts/build_master_presets.py` (checked in, re-runnable) derives each
master from the imported library plus the hand-refined client presets:

- **Rule union:** every distinct check type that appears in any library preset
  and is IMPLEMENTED in the parameter catalogue becomes one rule in the master.
- **Default values:** the most common expected value across the library; where
  templates disagree, the generated YAML carries a comment listing the
  distribution (e.g. `# library values: -23 LUFS ±0.5 (31 templates), -24 ±2 (9)`)
  so the approving engineer sees the spread, not just the winner.
- **Severity:** blocking/error where the majority of library templates set
  RejectOnError, warning otherwise — same policy as the importer.
- Regeneration never overwrites an edited master (same `--force` contract as
  the Vidchecker importer).

## 4. Library demotion

The catalog gains a **`listed`** flag: presets under `presets/library/` are
`listed: false`. Unlisted presets:

- do NOT appear in the submit dropdown;
- remain fully loadable — watch folders may still bind them, the CLI can still
  run them by path or id, and shadow-validation runs can still target them;
- remain visible on the Presets governance page under a collapsed "Library
  (reference)" group.

Hand-made client presets (marimba, njarka, alphorn, topic, vanda,
deepdub-internal) stay listed — they are real delivery contracts, not library
noise. The dropdown therefore shows: the two masters first, then the client
presets. From ~53 entries to ~10.

## 5. The editor

Entry point: the Presets page. Any **draft** preset gets an "Edit" action;
approved presets get "New draft from this version" (identical editor, base
pinned to the approved content). The editor is generic — masters are simply
the presets people will edit most.

**Editable per rule (v1):** expected value / min / max, severity, blocking,
enabled. **Rendered read-only:** rule id, parameter, operator, applies_to,
the parameter's catalogue description and limitations (so the person changing
a threshold sees what the measurement actually means).

**Enable/disable:** the rule model has a native `enabled` flag the rule
engine already honors, so a disabled rule stays in the saved YAML with
`enabled: false` — visible, re-enableable, nothing is ever lost by unticking
a box. (Simpler than the originally sketched union-with-template approach,
and strictly better: the file itself is the record.)

**Save = new version:**
- Minor version bump (1.0.0 → 1.1.0), new YAML file next to the base, status
  `draft`, header comment recording who saved (the requested_by-style name
  field), when, from which base version, and the operator-entered change note.
- The saved YAML round-trips through the real preset loader before the file is
  written; a validation failure is shown inline and nothing is saved (schema
  validation is never bypassed).
- **Conflict guard:** the save request carries the base version; if a newer
  version of that preset id exists, the save is rejected with a "reload and
  reapply" error. Last-write-wins is not acceptable for QC policy.

**API:**
- `GET /api/v1/presets/{id}/{version}/editable` — parsed rule model + catalogue
  metadata for the form.
- `POST /api/v1/presets/{id}/versions` — `{base_version, edited_by, note,
  rules: [...]}` → creates the draft, returns the new version.

## 6. Storage reality (named, not hidden)

The editor writes YAML files under `paths.presets_root`. On the RDP host that
is the git checkout: editor-created versions appear as untracked files. This
is a feature in v1 — `git status` is the audit of what the host changed — but
those files must be committed back during maintenance or they exist on one
host only. A dedicated presets store outside the checkout is a later phase if
editing volume warrants it.

## 7. Testing obligations

- Synthesis: master generation is deterministic over the committed library;
  distribution comments match the library's actual value spread; regeneration
  refuses to clobber without `--force`.
- Demotion: unlisted presets absent from the dropdown, still resolvable by
  watch folders and the API.
- Editor: value/severity/enable round-trip through the loader; version bump +
  file creation; conflict guard; validation failure saves nothing; approved
  presets are not editable in place; the new draft appears in the catalog
  without restart (or the save response says a restart is needed — whichever
  the implementation does, the UI must tell the truth).

## 8. Operator decisions (confirmed 2026-07-28)

1. **Edit surface:** web console editor (not YAML-only).
2. **Edit model:** versioned saves — every save is a new draft version with an
   audit trail; no unversioned per-job tweaks in v1.
3. **Library fate:** demoted to reference — out of the dropdown, kept on disk
   and on the governance page.

**Still reserved for humans (§30):** approving the synthesized master defaults
(the generated distribution comments exist precisely to make this review
fast), and the eventual `presets lock` of a master version.

## 9. Delivery phases

- **PR A — masters + demotion:** synthesis script, the two generated masters,
  `listed` flag, dropdown filtering, governance-page grouping.
- **PR B — editor:** editable API, editor page, versioned save + conflict
  guard.
