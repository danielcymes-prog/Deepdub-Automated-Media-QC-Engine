# Deepdub QC Console — UI Design Specification (Phase 3.5)

- **Status:** Design proposal — final UI design requires human approval (handoff §30)
- **Companion to:** `docs/server-gui-spec.md` (functional contract — routes, error codes, session rules). This document defines *how it looks and feels*; that one defines *what it does*. Where they reference the same thing, the functional spec wins on behavior, this spec wins on presentation.
- **Consumer:** an engineering agent implementing Jinja2 templates + a single CSS file + minimal vanilla JS. No frontend framework, no build step, no external assets (all fonts/CSS/JS vendored — security §20).

---

## 1. Design Intent

This is an **operator instrument, not a marketing surface**. Two people use it all day on an RDP session to answer one question fast: *"can this file ship?"*

Principles, in priority order:

1. **Verdict-first.** The QC verdict (`PASS`/`WARNING`/`FAIL`/`ERROR`) is the most important pixel on any screen that has one. It is always a high-contrast badge, never plain text, never color-only (icon + label, for color-blind operators and grayscale RDP sessions).
2. **Two vocabularies, never blended.** Orchestration state ("did the job run": PENDING/RUNNING/COMPLETED/FAILED/CANCELLED) and QC verdict ("did the media pass") get *visually distinct systems* — orchestration is neutral/monochrome chips, verdicts are saturated color badges. An operator must never mistake "job FAILED (crashed)" for "media FAIL (bad loudness)".
3. **Dense but calm.** Tables over cards. One accent color used sparingly. No decoration that competes with status color.
4. **RDP-proof.** Assume 1080p, possible 125% Windows scaling, imperfect color reproduction, no smooth animation guarantees. Minimum body text 14px, minimum hit target 32px, no hover-only affordances (everything hoverable is also visible or clickable).
5. **Nothing invented.** The GUI displays pipeline output verbatim. No progress percentages (stage checklist only), no summarized verdicts, no rounding of measured values.

## 2. Design Tokens

Single source: one `:root` block in `app.css`. Engineering agent: implement tokens exactly; changing a token must restyle the whole console.

> **BRAND PLACEHOLDER — requires approval.** Accent and logo values below are provisional (Deepdub's public identity: dark surfaces, violet accent). The brand team must confirm `--dd-accent`, the wordmark/logo asset, and the icon before release. Everything else (neutrals, status colors, type scale) is proposed as final.

### 2.1 Color

```css
:root {
  /* Surfaces — dark theme (brand direction) */
  --dd-bg:          #121217;  /* app background */
  --dd-surface:     #1B1B22;  /* panels, table rows */
  --dd-surface-2:   #24242D;  /* raised: modals, hover rows, inputs */
  --dd-border:      #33333E;
  --dd-text:        #EDEDF2;  /* primary text  (≥12.5:1 on --dd-bg) */
  --dd-text-dim:    #A0A0AE;  /* secondary text (≥5.6:1) */

  /* Brand accent — PLACEHOLDER pending brand approval */
  --dd-accent:      #7C5CFF;  /* interactive: links, primary buttons, focus */
  --dd-accent-hover:#9678FF;

  /* QC verdict colors (saturated — reserved exclusively for verdicts) */
  --qc-pass:        #2FBF71;
  --qc-warning:     #E8A13C;
  --qc-fail:        #E5484D;
  --qc-error:       #B84DD9;  /* execution error ≠ media fail: distinct hue */

  /* Orchestration chips (neutral — never verdict-colored) */
  --job-pending:    #8A8A98;
  --job-running:    var(--dd-accent);
  --job-done:       #6E6E7A;
}
```

Rules: verdict colors appear **only** on verdict badges and blocking-failure accents — never on buttons, links, or decoration. `RUNNING` is the only orchestration state allowed to use the accent (it's the one state the operator is waiting on).

### 2.2 Typography

- UI face: **Inter** (vendored woff2; system-ui fallback stack). Data face: **JetBrains Mono** (vendored) for paths, hashes, timecodes, job IDs, measured values — anything an operator might copy or compare character-by-character.
- Scale (px): 24 page title / 18 section / 14 body & table / 13 chip & meta / 13 mono data. Line-height 1.5 body, 1.35 tables.
- Weights: 600 titles and verdict badges, 500 buttons and table headers, 400 everything else. No light weights (RDP rendering).

### 2.3 Spacing, radius, elevation

- 4px base grid; standard steps 4/8/12/16/24/32.
- Radius: 6px inputs & buttons, 8px panels & modals, 999px chips/badges.
- Elevation: borders, not shadows (dark theme + RDP). Modals get `--dd-border` outline plus a 60% black scrim.

### 2.4 Iconography

Inline SVG only (no icon font, no CDN). Set of ~14: pass ✓, warning ⚠ (triangle), fail ✕, error ◆ (diamond — deliberately not an X), pending ○, running (spinner), completed ●, cancelled ⊘, folder, file-video, copy, external-link, chevron, close. Stroke 1.5px, 16×16 in text, 20×20 in buttons.

## 3. App Shell

Every page shares this frame:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ▐DD▌ Deepdub QC        Submit   Jobs   Presets            ● Service │  56px header
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│                    content, max-width 1200px, centered               │
│                    24px page padding                                 │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│ deepdub-qc v0.4.1 · FFmpeg 7.1 · preset pack a3f9c21 · host RDP-QC1 │  32px footer
└──────────────────────────────────────────────────────────────────────┘
```

- Header: logo (placeholder wordmark) links to Submit; active nav item gets a 2px `--dd-accent` underline. Right side: service health dot (green ok / amber degraded / red down, from `/api/v1/health`), tooltip shows queue depth.
- Footer: version provenance line (auditability, handoff §29) — always visible, `--dd-text-dim`, mono.
- No sidebar. Three destinations don't need one.

## 4. Component Library

Engineering agent: build these as Jinja2 macros in `components.html.j2`; pages compose them. One macro per component below.

### 4.1 `verdict_badge(status, size)`

Pill, icon + uppercase label, 600 weight. `PASS` filled `--qc-pass`/white text; `WARNING` filled `--qc-warning`/black text; `FAIL` filled `--qc-fail`/white; `ERROR` filled `--qc-error`/white. Sizes: `sm` 20px (table rows), `lg` 32px (job detail hero).

### 4.2 `job_chip(status, queue_position=None)`

Outlined (not filled) pill, neutral colors per token block. `PENDING` renders `○ Queued · #2`; `RUNNING` renders spinner + `Running`; `FAILED` renders `◆ Job failed` — the word "Job" is mandatory in the label to disambiguate from a media FAIL.

### 4.3 `data_table(columns, rows)`

Full-width, 40px rows, header row sticky, `--dd-surface` rows on `--dd-bg`, 1px `--dd-border` row separators, row hover `--dd-surface-2`. Whole row clickable when it links (plus a visible chevron in the last cell — no hover-only affordance). Zebra striping: no (status colors provide enough rhythm).

### 4.4 `path_field` + `path_browser_modal`

Text input (mono) with trailing `folder` icon button. Modal: 720×480, two panes — left: `media_roots` list; right: directory listing (folders first, then media files with size), breadcrumb top, filter box, Select/Cancel. Paths render mono, truncated middle (`\\server\…\S02E04\`) with full value in `title`. The modal lists only within `media_roots` (functional spec §3.1) — design communicates this with a caption under the breadcrumb: *"Showing allowed media locations only."*

### 4.5 `preset_picker`

Grouped listbox (native `<select>` with `<optgroup>` per client is acceptable v1; custom listbox optional later). Below it, a **preset summary card** appears once selected: title, `preset_id@version` (mono), client, content type, status pill (`approved` green-outline / `draft` amber-outline / `deprecated` gray-outline strikethrough). Draft caption: *"Draft preset — not approved for delivery decisions."* Deprecated adds a confirm checkbox (functional spec §3.1).

### 4.6 `stage_checklist(stages)`

Vertical list, one row per stage: state icon (done ✓ dim-green / running spinner accent / pending ○ dim) + stage label + right-aligned mono elapsed time. Detector stages nest one level under "Analysis" with `detector 3 of 7` counter in the group header. No progress bar anywhere — a bar implies fabricated percentage (design principle 5).

### 4.7 `finding_row` (job-detail summary; full detail lives in report.html)

Left 4px border in verdict color; check display name; expected vs. actual as two mono columns labeled `expected` / `measured`; timecode chip when present (mono, click = copy); `BLOCKING` tag (filled `--qc-fail`, 11px) when blocking.

### 4.8 Banners & dialogs

- `banner(kind)`: full-width, icon + text + optional action button; kinds info (accent-tinted), warning (amber-tinted), danger (red-tinted). Used for degraded-PDF (E10), service draining, duplicate-job warning (E5).
- `confirm_dialog`: 480px modal, title, body, danger-styled confirm for destructive acts (Cancel job). Exact copy in §6.
- Field errors: 13px `--qc-fail` text under the field + 1px red field border. Never toast-only — errors must persist until fixed.

## 5. Pages — Wireframes & Annotations

Routes and behavior per `server-gui-spec.md` §3. Wireframes are 1200px content width.

### 5.1 Submit (`/`)

```text
┌ Submit a QC job ────────────────────────────────────────────────────┐
│                                                                     │
│  Media file                                                         │
│  ┌───────────────────────────────────────────────────────┐ ┌────┐  │
│  │ \\mediaserver\deliveries\alphorn\S02E04_de.mov        │ │ 📁 │  │
│  └───────────────────────────────────────────────────────┘ └────┘  │
│  ✓ 4.2 GB · found · readable                            (validate) │
│                                                                     │
│  Client preset                                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ Alphorn — Workout Final Delivery (v1.0.0)              ▾      │ │
│  └───────────────────────────────────────────────────────────────┘ │
│  ┌ preset summary card ──────────────────────────────────────────┐ │
│  │ alphorn_workout_delivery@1.0.0   [approved]                   │ │
│  │ Client: Alphorn · Content: workout · Effective 2026-07-22     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  Requested by                                                       │
│  ┌──────────────────────┐                                           │
│  │ baruch               │   Shown on the shared job list.           │
│  └──────────────────────┘                                           │
│                                                                     │
│  Output: C:\DeepdubQC\data\jobs\<job-id>\        (dim, mono)        │
│                                                                     │
│                                        ┌──────────────────────┐     │
│                                        │   Run QC  ▶          │     │
│                                        └──────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

Annotations:

- Single centered column, max 640px — a form, not a dashboard.
- Path field validates on blur (`✓ size · found · readable` line, dim green; or inline E1–E3 error). The check line doubles as the operator's "I picked the right file" confirmation, so it always shows the file size.
- **Run QC** is the page's only primary (accent-filled) button; disabled state at 40% opacity with a `title` explaining what's missing. Primary-button rule: max one per page, always accent, never a verdict color.
- On success → redirect to Job Detail. No toast needed; the destination *is* the confirmation.

### 5.2 Jobs (`/jobs`)

```text
┌ Jobs ───────────────────────────────────────────────────────────────┐
│                                                    [ New QC job ▶ ] │
│ ┌───────┬──────────────────────┬─────────────────┬──────────┬──────┬─────────┬───┐
│ │ Job   │ Media                │ Preset          │ By       │ State│ Verdict │   │
│ ├───────┼──────────────────────┼─────────────────┼──────────┼──────┼─────────┼───┤
│ │ a3f9… │ S02E04_de.mov        │ alphorn_wo…@1.0 │ baruch   │ ⟳ Running │  —  │ › │
│ │ 77b1… │ S02E03_de.mov        │ alphorn_wo…@1.0 │ dana     │ ○ Queued·#1│ —  │ › │
│ │ c04a… │ EP101_fr_final.mov   │ generic_bro…@1  │ baruch   │ ● Done │ [✕ FAIL] │ › │
│ │ 9e2d… │ EP100_fr_final.mov   │ generic_bro…@1  │ dana     │ ● Done │ [✓ PASS] │ › │
│ │ 5512… │ trailer_v2.mov       │ alphorn_wo…@1.0 │ baruch   │ ◆ Job failed │ — │ › │
│ └───────┴──────────────────────┴─────────────────┴──────────┴──────┴─────────┴───┘
│  ‹ 1 2 3 ›                              Updated 2s ago · auto-refresh │
└──────────────────────────────────────────────────────────────────────┘
```

Annotations:

- **State and Verdict are separate columns** — the load-bearing design decision (principle 2). Verdict cell is `—` until COMPLETED.
- Media column shows filename only; full path in `title` and on the detail page. Job ID: first 8 chars, mono.
- Polling refresh must not jump scroll or reflow row heights; changed cells may flash `--dd-surface-2` for 300ms (the only animation in the console).
- "Updated Ns ago" caption is the polling heartbeat; if polling fails 3×, it becomes a warning banner: *"Lost contact with the QC service — retrying."*
- Empty state (no jobs yet): centered dim illustration-free block — *"No QC jobs yet. Run your first from the Submit page."* + secondary button.

### 5.3 Job Detail (`/jobs/{id}`) — four states

**Hero block** (all states): filename (18px, mono) → full path (13px dim mono, copy icon) → meta row: preset `id@version` · requested by · submitted time → right side: the state's chip/badge, `lg`.

**A — Queued:**

```text
│  ○ Queued — position 2 of 3                                        │
│  One job runs at a time. This job starts automatically.            │
│                                              [ Cancel job ]        │
```

**B — Running:** stage checklist (§4.6) + elapsed total + `[ Cancel job ]` (danger-outline). Nothing else — resist the urge to preview partial findings; partial results presented as results violate handoff §29.

**C — Completed:** verdict hero + summary + actions:

```text
│  [ ✕ FAIL ]  (lg badge)                                            │
│  24 checks · 20 passed · 2 warnings · 2 failed · 2 blocking        │
│                                                                    │
│  Blocking failures                                                 │
│  ┃ Integrated Loudness      expected −24…−22 LUFS   measured −19.7 │
│  ┃ Audio Stream Count       expected 4              measured 3     │
│                                                                    │
│  [ Open HTML report ↗ ]  [ PDF ] [ JSON ]  ·  Job folder: C:\…(⧉) │
```

“Open HTML report” is the primary action (accent). Blocking failures render via `finding_row` — max 5, then *"…and N more in the full report."* The GUI summary never re-computes anything: counts and rows come verbatim from `report.json`.

**D — Job failed / cancelled:** `◆ Job failed` chip + plain-language reason (*"FFprobe could not read this file. It may be corrupt or still copying."*) + collapsed `<details>` log tail (mono, 12 lines, dark inset) + `[ Resubmit ]` secondary button. Never show a bare traceback outside the log tail.

### 5.4 Presets (`/presets`)

Read-only `data_table` grouped by client (group header row, 600 weight): Title · `id@version` (mono) · content type · status pill · effective date. Caption under the page title: *"Presets are versioned files managed in git — this list is read-only. To change thresholds, talk to the preset owner."* (Sets the governance expectation in the UI itself.)

### 5.5 Session cap (503 page)

Centered 480px panel: logo, *"Both operator slots are in use"*, body: *"The QC console allows 2 concurrent operators. A slot frees after 15 minutes of inactivity."* + `[ Retry ]`. No auto-retry loop (would fight the TTL).

### 5.6 Error pages (E6, E11, generic 500)

Same centered-panel pattern: icon ◆, one-sentence what-happened, one-sentence what-to-do, job/queue context when known. Copy in §6.

## 6. Microcopy (canonical strings)

Engineering agent: these strings are the spec — implement verbatim; UI copy changes go through this file.

| Key | String |
|---|---|
| submit.title | `Submit a QC job` |
| submit.path.help | `Paste a path or browse. Media is read directly from the share — nothing is uploaded.` |
| submit.error.E2 | `This location isn't an allowed media root. Allowed: {roots}` |
| submit.error.E3 | `File is {size} — the limit is {limit}. Contact the tool owner if this is a legitimate deliverable.` |
| submit.duplicate.E5 | `This exact file and preset are already {state} as job {id}. Submit anyway?` |
| queue.position | `Queued — position {n} of {m}` |
| queue.explain | `One job runs at a time. This job starts automatically.` |
| cancel.confirm.title | `Cancel this job?` |
| cancel.confirm.running | `This stops the analysis immediately. Partial output stays in the job folder, but no report is produced.` |
| job.failed.restart | `The QC service restarted while this job was running, so it was stopped for safety. Resubmit to run it again.` |
| job.degraded.pdf | `The PDF could not be generated ({error}). The HTML and JSON reports are complete and the QC verdict is unaffected.` |
| verdict.error.tooltip | `The pipeline could not finish — this is not a media verdict. Check the job log.` |
| cap.title | `Both operator slots are in use` |
| polling.lost | `Lost contact with the QC service — retrying.` |

Voice: plain, specific, no exclamation marks, no apology theater, never blames the operator. Always name the next action.

## 7. Interaction & Motion

- Motion budget: the 300ms cell flash (§5.2) and the running spinner. Nothing else animates — RDP.
- Focus: 2px `--dd-accent` outline, 2px offset, on every interactive element. The console must be fully keyboard-operable (tab order = visual order; modal traps focus; `Esc` closes).
- Copy affordances (paths, hashes, timecodes): click icon → icon swaps to ✓ for 1.5s. No toast.
- Times display in host-local time, `2026-07-23 14:02` format, with full ISO-8601 in `title`.

## 8. Accessibility

- WCAG 2.1 AA contrast minimums; all token pairs above already comply — engineering agent must re-verify if any token changes.
- Verdicts and states: icon + label always (no color-only meaning).
- `aria-live="polite"` on the stage checklist and the jobs-table update caption, so screen readers announce progress without spam.
- Native elements first: `<select>`, `<details>`, `<dialog>`, `<table>` — least custom-widget ARIA surface.

## 9. Engineering Handoff Map

| This spec | Implements against |
|---|---|
| §3 shell, §5 pages | `server-gui-spec.md` §3 pages, §4 flows |
| §4.2 job chip / §4.1 verdict badge | JobStatus vs QCStatus split, `server-gui-spec.md` §3.2 |
| §4.6 stage checklist | progress events, `server-gui-spec.md` §5 |
| §6 error strings | error states E1–E13, `server-gui-spec.md` §6 |
| §5.5 session cap page | `server-gui-spec.md` §7 / F4 |
| Tokens §2 | single `app.css`; no CDN (security §20 / §9.5) |

Deliverable files expected from implementation: `templates/gui/base.html.j2`, `components.html.j2`, one template per page, `static/app.css`, `static/app.js` (polling + modal + copy only), vendored `inter*.woff2`, `jetbrains-mono*.woff2`, `deepdub-qc.ico`.

## 10. Open Questions (require human approval)

1. **Brand tokens:** confirm `--dd-accent #7C5CFF`, wordmark asset, and `.ico` with the brand team — placeholder until then (handoff §30 reserves final UI design).
2. **Dark-only** is proposed (matches brand + evidence thumbnails read better on dark). Is a light mode required for any stakeholder who reviews over the operator's shoulder?
3. **Verdict `ERROR` hue** (violet `#B84DD9`): chosen to be maximally distinct from FAIL red; confirm it doesn't collide with the final brand accent.
4. Blocking-failures preview on Job Detail (§5.3C) shows expected/measured values — confirm this summary-level duplication of report content is acceptable, or whether the detail page should show counts only and defer everything to `report.html`.
