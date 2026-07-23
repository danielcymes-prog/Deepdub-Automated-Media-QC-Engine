# Deepdub QC — Local Server & GUI Functional Specification (Phase 3.5)

- **Status:** Draft for implementation
- **Related:** `docs/adr/0004-local-web-gui-on-shared-rdp-host.md`, `docs/windows-deployment.md`, `docs/server-config-spec.md`, handoff §4.2 (report review), §17 (report requirements), §20 (security), §23 (Composer API contract)

## 1. Purpose and Non-Goals

`deepdub-qc serve` starts a FastAPI application on the shared Windows RDP host that gives operators a browser-based way to submit QC jobs, watch the queue, and open reports. The GUI is a thin shell over the existing core pipeline.

**Invariants (violations are architecture bugs):**

- The GUI contains **zero QC logic**. No thresholds, no pass/fail computation, no report content generation. It submits jobs, displays orchestration state, and serves artifacts the pipeline produced.
- The GUI never modifies `report.json` or any canonical artifact.
- A job submitted from the GUI and the same job run via `deepdub-qc analyze` produce identical canonical output (ADR-008 determinism, volatile fields excluded).

**Non-goals for Phase 3.5:** authentication/authorization, media upload, multi-host operation, preset editing, report annotation, AI explanations, Composer integration.

## 2. Architecture Placement

```text
Browser (localhost on RDP host)
        │  HTML + fetch polling
        ▼
FastAPI app (api/ + gui/ routes, server-rendered Jinja2 templates)
        │  enqueues JobRequest / reads job state
        ▼
SQLite job store (queue + status index; NOT QC results)
        │  claimed by
        ▼
In-process background worker (max_concurrent_jobs = 1)
        │  calls the same entrypoint as the CLI
        ▼
orchestration/ pipeline → job output directory (report.json, report.html, report.pdf, evidence/, raw/, logs/)
```

The API routes mirror the future Composer contract (handoff §23) so Phase 7 extraction changes deployment, not shape:

| Route | Method | Purpose |
|---|---|---|
| `/api/v1/qc/jobs` | POST | Submit a job (input path, preset id+version, `requested_by`) |
| `/api/v1/qc/jobs` | GET | List jobs (all users), newest first, paginated |
| `/api/v1/qc/jobs/{job_id}` | GET | Job detail: status, queue position, progress, summary when done |
| `/api/v1/qc/jobs/{job_id}/report` | GET | Canonical `report.json` |
| `/api/v1/qc/jobs/{job_id}/report.html` / `report.pdf` | GET | Rendered artifacts (served as static files from the job directory) |
| `/api/v1/qc/jobs/{job_id}/evidence/{evidence_id}` | GET | Evidence artifact |
| `/api/v1/qc/jobs/{job_id}/cancel` | POST | Cancel a pending or running job |
| `/api/v1/presets` | GET | List available presets (id, version, client, content type, status) |
| `/api/v1/health` | GET | Liveness + version + queue depth (used by deployment checks) |

GUI pages are server-rendered Jinja2 (reusing the report-template toolchain) with a small amount of vanilla JS for polling. No frontend framework, no build step. The generated *reports* remain JS-free per handoff §17.2; the GUI itself may poll.

## 3. Pages

### 3.1 Submit Job (`/`)

The landing page. Contents:

1. **Media path input** — a text field for an absolute path or UNC path (`\\server\share\...`) to the media file, plus a server-side path browser (see below). **There is no file upload.** The server reads media directly from disk/shares; uploading through the browser is explicitly out of scope (handoff §20: media never leaves the host; also multi-GB uploads to localhost are wasteful).
   - *Server-side path browser:* a modal that lists directories/files under the configured `media_roots` only (see `server-config-spec.md`). It never lists paths outside `media_roots`. Filterable by media extensions.
2. **Preset picker** — grouped by client, showing `title`, `preset_id`, `version`, and `status` badge (`draft` / `approved` / `deprecated`). Default selection: none (operator must choose). Deprecated presets are visible but require an explicit confirmation checkbox; draft presets show a "not approved for delivery decisions" caption. Data comes from the existing preset loader — the GUI does not parse YAML itself.
3. **Requested by** — text field, pre-filled with the detected Windows session username if available, editable. Required, non-empty. Persisted in the job record.
4. **Output location** — read-only display of where the job directory will be created (`jobs_root/<job_id>/`), for operator orientation.
5. **Submit button** — disabled until path, preset, and requested_by are valid.

On submit, the server validates *before* enqueueing (see §6 error states): path exists, is a file, is under an allowed media root, is readable, size under the configured ceiling; preset id+version resolves and validates. Validation failures return the form with inline errors; nothing is enqueued. Success redirects to the Job Detail page.

### 3.2 Job Queue / Status (`/jobs`)

A table of **all users' jobs** (not filtered to the current operator), newest first, paginated (default 50/page). Columns:

| Column | Content |
|---|---|
| Job ID | short prefix, links to detail |
| Media file | filename (full path on hover/detail) |
| Preset | `preset_id@version` |
| Requested by | attribution string |
| Submitted | local timestamp |
| Status | `PENDING (position N)` / `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED` |
| Result | overall QC status badge (`PASS`/`WARNING`/`FAIL`/`ERROR`) when completed — taken verbatim from `report.json` |
| Actions | View report · Cancel (pending/running only) |

Status semantics: `JobStatus` (handoff §8) describes *orchestration* ("did the job run"); `QCStatus` describes the *verdict* ("did the media pass"). The GUI must display both and never conflate them — a `COMPLETED` job whose media failed QC is `COMPLETED` + `FAIL`.

The page polls `GET /api/v1/qc/jobs` every `queue_poll_interval_seconds` (default 2s) and re-renders rows. Queue position is computed by the server from the pending queue order and shown for pending jobs.

### 3.3 Job Detail (`/jobs/{job_id}`)

- Header: media filename, full path, preset id/version/client, requested_by, submitted/started/completed timestamps, job status.
- **While pending:** "Queued — position N of M. One job runs at a time." with a cancel button.
- **While running:** progress display (§5) and a cancel button.
- **When completed:** summary block rendered from `report.json` — overall status, counts (passed/warnings/failed/errors, blocking failures), then buttons: **Open HTML report** (new tab), **Download PDF**, **Download JSON**, **Open job folder** (displays the path for copy-paste; the server does not shell out to open Explorer).
- **When failed (orchestration error):** the error category and message, the tail of the job's `qc.log`, and a link to the full log. Detector failures are never hidden (handoff §17.2).
- **When cancelled:** who cancelled and when.

### 3.4 Report Viewer

The report viewer is **the existing self-contained `report.html`**, served as a static file from the job directory in a new tab. No re-rendering, no GUI-specific report template — this guarantees the GUI can never show report content that diverges from the canonical artifacts (ADR-002). Evidence links inside the HTML resolve because the whole job directory is mounted read-only under `/api/v1/qc/jobs/{job_id}/files/...` with path-traversal protection (resolved path must remain inside the job directory).

### 3.5 Preset Picker (component + `/presets` page)

Besides the submit-form component (§3.1), a read-only `/presets` page lists every preset with id, version, client, content type, status, title, description, and effective date — the operator's reference for "which preset do I use for this client." No editing. Preset authoring stays in git (ADR-003, ADR-013).

## 4. User Flows

**F1 — Submit and review (happy path):** open shortcut → browser opens Submit page → pick media via path browser → pick preset → confirm requested_by → Submit → redirected to Job Detail (position 1, starts immediately) → progress stages advance → completed with `FAIL` → operator opens HTML report → reads blocking failures with expected/actual and timecodes → makes delivery decision.

**F2 — Queued behind another job:** second operator submits while a job runs → detail page shows "Queued — position 1" → page polls; when the running job finishes, status flips to `RUNNING` automatically. No action needed. Operators can log off RDP; the service and job continue.

**F3 — Cancel:** operator opens a pending/running job → Cancel → confirmation dialog ("Cancelling a running job stops FFmpeg and marks the job CANCELLED; partial output is kept in the job folder for debugging but contains no report."). Pending jobs are removed from the queue instantly; running jobs get their subprocess tree terminated, and the worker marks the job `CANCELLED`.

**F4 — Session cap reached:** a third browser session opens the GUI → static page: "The QC console is limited to 2 concurrent operators and both slots are in use. Slots free up after ~{session_ttl} of inactivity." with a Retry button. See §7.

**F5 — Service restart mid-job:** service restarts (crash/upgrade) while a job is `RUNNING` → on startup the worker marks orphaned `RUNNING` jobs `FAILED` with reason `interrupted_by_restart` (a job must never be silently re-run — reruns are an explicit human action) → pending jobs remain queued in order → job detail shows the failure and a **Resubmit** button that pre-fills the Submit form.

## 5. Progress Surfacing

The pipeline already emits structured stage logs (handoff §19: stage, detector id, duration, status). Phase 3.5 surfaces progress **by stage, not by percentage**:

- The orchestration layer exposes a job-scoped progress callback/event hook (core change kept minimal: an optional `on_stage_event` callback on the pipeline entrypoint; the CLI passes nothing, the worker passes a recorder).
- The worker writes stage events to the job record: `probing`, `detector:<detector_id>` (started/finished, with per-detector wall time), `evaluating_rules`, `rendering_reports`.
- The GUI renders a checklist of stages with states (done / running / pending) and elapsed time. If detector count is known after probing, show "detector 3 of 7".
- **No fabricated percentages.** Estimating completion from media duration is a possible later enhancement, listed as an open question; inventing progress numbers contradicts the project's accuracy-first posture.

Polling, not WebSockets/SSE: at ≤2 users and 2-second intervals, polling is simpler, proxy-free, and sufficient. Revisit only in Phase 7.

## 6. Error States

Every error shown in the GUI must state *what happened* and *what the operator can do*. Categories:

| # | Condition | When detected | Behavior |
|---|---|---|---|
| E1 | Path does not exist / not a file / not readable | Submit (pre-enqueue) | Inline form error; nothing enqueued |
| E2 | Path outside configured `media_roots` | Submit | Inline error naming the allowed roots ("Media must be under: `\\server\deliveries`, `D:\qc-media`") |
| E3 | File exceeds `max_file_size_gb` | Submit | Inline error with the limit and the file's size |
| E4 | Preset missing / fails schema validation / version not found | Submit | Inline error with the preset validator's message |
| E5 | Duplicate in-flight job (same input hash + preset id+version already pending/running) | Submit | Warning page: link to the existing job + "Submit anyway" (explicit override, recorded on the job) |
| E6 | Queue full (`max_queue_length`) | Submit | Error page: queue length, oldest pending job, retry advice |
| E7 | Detector/pipeline failure during run | Worker | Job `FAILED`; detail shows error type, message, log tail; maps to CLI exit-code semantics 3/5/6 |
| E8 | Media unreadable/corrupt mid-analysis | Worker | As E7 with exit-code-5 semantics; message names the file, not a stack trace |
| E9 | Job exceeds `max_job_duration_minutes` | Worker | Subprocesses terminated; job `FAILED` with reason `timeout`; partial raw output kept |
| E10 | PDF rendering fails (Playwright/Chromium missing or crashed) | Worker | Job completes with a **degraded-artifacts warning**: JSON+HTML available, PDF marked unavailable with the `PdfRenderError` message. QC verdict is unaffected — rendering failure is not a QC failure, but it must be visible, never silent |
| E11 | SQLite locked/corrupt | Any | 500 page asking operator to contact the tool owner; structured log with details; health endpoint reports unhealthy |
| E12 | Session cap reached | GUI entry | §7 |
| E13 | Cancel raced with completion | Cancel | Idempotent: if the job finished first, show "Job already completed" and the result |

All server errors are structured-logged with job id, stage, and error type (handoff §19). Raw tracebacks go to logs, never to the GUI.

## 7. Session Cap Behavior

Purpose: keep the service within its designed envelope (ADR 0004 — scaling beyond 2 operators is Phase 7, not a config bump).

- **Session** = a browser identified by a `qc_session` cookie (random ID issued on first GUI page load). API-only clients (health checks, future scripting) do not consume GUI sessions.
- Active sessions are tracked in memory with last-seen timestamps, refreshed by page loads and polling.
- A session expires after `gui_session_ttl_minutes` (default 15) without a request. Expiry frees the slot.
- When `max_gui_sessions` (default 2) are active and a new browser arrives, it receives HTTP 503 with the friendly page from F4. Existing sessions are never evicted in favor of new ones.
- Session tracking is best-effort operator coordination, **not security**. The perimeter is the host: the server binds `127.0.0.1` by default, and access control is "can you log into the RDP host."

## 8. Identity (`requested_by`)

- Required on every submission; stored in the job record; displayed in the queue.
- Default value: the Windows username of the server process's session is *not* the browser user's identity (all RDP users hit the same service), so the server cannot reliably detect the requester. The field is therefore **operator-editable free text, pre-filled from the browser's remembered previous value** (localStorage on the client is acceptable here — this is the GUI, not a report).
- Whether to attempt Windows session identification (e.g., via an OS-level integration) is deliberately out of scope; flagged as an open question.

## 9. Security Requirements (binding, from handoff §20)

1. All subprocess invocations use argument arrays with explicit timeouts; `shell=True` is forbidden.
2. Input paths are untrusted: canonicalize with `pathlib` (UNC-aware, `Path.resolve(strict=True)` semantics on Windows), then verify containment in `media_roots`. Reject reparse-point tricks by containment-checking the *resolved* path.
3. Artifact serving containment-checks every resolved path against the job directory (no `..`, no absolute-path smuggling in `evidence_id`).
4. Filenames are sanitized in any server-generated artifact or header (`Content-Disposition` uses a sanitized name).
5. No media, transcripts, filenames, or client metadata leave the host. No external HTTP calls from server or GUI (no CDN assets — all CSS/JS vendored/inlined).
6. AI features: none. Disabled by default per handoff §20; Phase 3.5 includes no AI code path at all.
7. Configurable ceilings enforced: `max_file_size_gb`, `max_job_duration_minutes`, `max_queue_length`.
8. Logs never contain secrets, tokens, or full environments (there should be none, but the logging layer must not dump `os.environ`).

## 10. Acceptance Criteria

1. `deepdub-qc serve` starts the service; the Submit, Jobs, Job Detail, and Presets pages render.
2. A job submitted via GUI produces a job directory byte-identical (volatile fields masked, ADR-008) to the same job run via CLI.
3. Two jobs submitted concurrently run strictly serially; the second shows queue position 1 while waiting.
4. Job list shows both operators' jobs with `requested_by` attribution.
5. A third concurrent GUI session receives the session-cap page; after TTL expiry of an idle session it can enter.
6. Killing the service mid-job and restarting yields: orphaned job `FAILED (interrupted_by_restart)`, queue preserved, resubmit works.
7. Path outside `media_roots`, oversized file, and invalid preset each produce their specified inline errors and enqueue nothing.
8. Cancel works for pending and running jobs; FFmpeg process tree is verified terminated on Windows (no orphaned `ffmpeg.exe`).
9. Report viewer serves the canonical `report.html`; evidence links resolve; a crafted `../` evidence request returns 404.
10. All acceptance tests pass on Windows with media on a UNC path.

## 11. Open Questions (require human approval)

1. **`requested_by` identity:** keep free-text (proposed default) or invest in Windows session identification?
2. **Progress estimation:** stage-based only (proposed) or add media-duration-based time estimates later?
3. **Resubmit semantics:** pre-fill form only (proposed) vs. one-click rerun; does a rerun create a new job id linked to the original?
4. **Queue reordering:** none in Phase 3.5 (proposed FIFO only) — is priority bump needed for urgent deliveries?
5. **Report client-identification** (handoff §30): job list shows preset ids that embed client names; confirm this is acceptable for a shared internal console.
