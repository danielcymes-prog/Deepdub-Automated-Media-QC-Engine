# ADR 0004: Local Web GUI on a Shared Windows RDP Host

- **Status:** Accepted (2026-07-23)
- **Phase:** 3.5 (local server + GUI, between Phase 3 metadata MVP and Phase 7 service extraction)
- **Related documents:** `docs/server-gui-spec.md`, `docs/windows-deployment.md`, `docs/server-config-spec.md`, `DEEPDUB_QC_CLAUDE_CODE_HANDOFF.md`

> **FOLDED:** this decision is canonically recorded as **ADR-014** in `docs/DECISIONS.md` (2026-07-23). This file remains as the full-length context/alternatives record.
>
> **Filing note.** `docs/DECISIONS.md` (ADR-006) mandates a single decisions file, and its numbering already reaches ADR-013. This record was authored as a standalone file during a parallel design effort to avoid write collisions with the active Phase 1 build. When the repository is quiet, the owner of `DECISIONS.md` should fold this record in as **ADR-014** (or the next free number) and replace this file with a pointer, or supersede ADR-006. Do not treat the "0004" filename as this decision's canonical number. This is listed as an open question below.

---

## Context

QC operators (at most 2, usually 1) work on a shared Windows RDP server. macOS users either RDP into that host or run the tool locally on their own machine. Operators are not comfortable driving the tool from the command line for day-to-day work; they need a point-and-click way to submit a media file, pick a client preset, watch progress, and open the resulting report.

The Phase 3 CLI (`deepdub-qc analyze`) already contains the complete QC pipeline: preset loading, detectors, rule engine, report generation, exit codes. The GUI must not duplicate or fork any of that. Per the handoff (§2, §17) and ADR-001/ADR-002, all QC logic stays in the deterministic core and `report.json` remains the single source of truth.

Constraints that shaped this decision:

- Media lives on network shares (`\\server\...` UNC paths) reachable from the RDP host. Media must never be uploaded to any external service (handoff §20), and uploading multi-gigabyte files through a browser to a local server that can already read the share directly would be pointless and slow.
- The team wants no new infrastructure: no PostgreSQL, no Redis, no Celery, no message broker (handoff §5.3 warns against introducing orchestration systems).
- The host is Windows. Anything that assumes Unix paths, Unix service managers, or Unix-only native libraries needs a Windows answer.
- Concurrency needs are tiny: one job at a time is acceptable; two simultaneous human users is the realistic maximum.

## Alternatives Considered

### A. Per-user local server (each operator runs `deepdub-qc serve` on demand)

Each operator starts the server themselves (double-click a launcher, server binds a local port, browser opens).

- Pros: no service administration; process lifetime matches usage; no shared state between users.
- Cons: two operators on the same RDP host means two servers, two SQLite databases, two job queues — and two jobs hammering the same disk/CPU with no coordination. Job history fragments per user session. FFmpeg contention is invisible. Operators must understand starting/stopping a server, and an operator who closes their session kills their running job. On a *shared* host this model actively fights the environment.

### B. Native desktop app (Tauri/Electron/PyQt wrapper around the core)

- Pros: familiar desktop ergonomics; no port management.
- Cons: a second UI technology stack to build and maintain for an internal tool with ≤2 users; packaging/signing burden on Windows; and it does nothing to solve shared-host coordination — two app instances have the same contention problems as alternative A. Worst of all, it is a dead end: Phase 8 integrates QC into Composer's web frontend, so investment in a native shell transfers nowhere.

### C. Shared persistent service on the RDP host (chosen)

One FastAPI process runs permanently on the host as a Windows service, serving a local web UI. All operators on the host use the same service, the same queue, and the same job history. Desktop "app" is just a browser shortcut to `http://localhost:<port>`.

- Pros: one queue serializes FFmpeg work naturally; job history is shared and complete ("who ran what" via `requested_by`); jobs survive operator logoff because the service outlives RDP sessions; the FastAPI wrapper is a direct down-payment on Phase 7 service extraction; the web UI skills/templates transfer toward Phase 8 Composer integration.
- Cons: requires service registration and an upgrade procedure on Windows (documented in `docs/windows-deployment.md`); introduces persistence (SQLite) earlier than ADR-005 planned; a single service is a single point of failure for both operators (acceptable at this scale — restart is seconds).

## Decision

Build alternative **C**:

1. **`deepdub-qc serve`** starts a FastAPI application that serves both a JSON API and a server-rendered local web UI. The GUI contains **zero QC logic**: every submission goes through the exact same core pipeline (`orchestration/`) the CLI uses. The API surface mirrors the future Composer contract (handoff §23: `POST /api/v1/qc/jobs`, `GET /api/v1/qc/jobs/{id}`, report/evidence retrieval, cancel) so Phase 7 is an extraction, not a redesign.
2. **Deployment** is a persistent Windows service on the RDP host, registered via NSSM (preferred) or Task Scheduler fallback, starting at boot. Desktop access is a `.url`/`.lnk` shortcut with the Deepdub icon pointing at the running service; the shortcut launches nothing. See `docs/windows-deployment.md`.
3. **Job execution** is a single in-process background worker. `max_concurrent_jobs = 1` by default (configurable); additional submissions queue with a visible position. No Celery, no Redis, no subprocess pool manager.
4. **Persistence** is SQLite, holding *job orchestration state only* (queue, status, `requested_by`, paths, timestamps). The canonical QC result remains the `report.json` in the job output directory — ADR-002 is untouched. SQLite is an index over job directories, never a second source of truth. This partially supersedes ADR-005's "no SQL before Phase 7": the queue is a cross-request, cross-restart concern the filesystem cannot serve safely, which is exactly the consumer ADR-005 said didn't exist yet.
5. **GUI sessions are capped at 2** (configurable), matching the operator ceiling and keeping the service honest about what it is.
6. **PDF rendering on Windows uses Playwright (headless Chromium), not WeasyPrint.** WeasyPrint's Pango/Cairo native dependencies are painful to install and keep deterministic on Windows outside Docker. ADR-012 already put rendering behind a `PdfRenderer` interface, so this is a second implementation selected by configuration, not a rewrite. On the Docker/Linux path WeasyPrint may remain the default. This **amends ADR-007** for the Windows deployment target; ADR-007's owner should record the amendment in `DECISIONS.md`.
7. **FFmpeg/FFprobe are located via configuration** (`docs/server-config-spec.md`), never assumed on a Unix path or `PATH`. All path handling uses `pathlib` and must be UNC-aware, since input media typically lives on `\\server\` shares.
8. Every job records **`requested_by`**; the job list shows all users' jobs. There is no authentication in Phase 3.5 (localhost-only binding; the RDP host's own login is the perimeter) — identity is self-declared and used for attribution, not authorization.

Security requirements from handoff §20 apply unchanged: no shell interpolation (subprocess argument arrays only), path validation against a configurable allowlist of media roots, no path traversal in report output, no external media upload, subprocess timeouts, and file-size/job-duration ceilings.

## Consequences

- Operators get a shared queue, shared history, and jobs that survive logoff; the cost is a small amount of Windows service administration, fully scripted and documented.
- The FastAPI layer and job/queue persistence built here are the seed of Phase 7. **Scaling beyond this single host is Phase 7 service extraction (real workers, object storage, Deepdub auth) — not tuning `max_concurrent_jobs` or `max_gui_sessions` upward.** Those caps encode the design envelope of a single shared host; raising them meaningfully requires the Phase 7 architecture.
- Two PDF renderer implementations must be kept behind one interface with shared contract tests, and CI needs a Windows-path (or at least Playwright-path) rendering test.
- SQLite arrives with a schema and therefore migrations (Alembic or hand-rolled versioned DDL — see open questions). The schema must stay small: it indexes job directories, it does not store measurements or findings.
- The no-JS report requirement (handoff §17.2) applies to *generated reports*, not to the GUI itself; the GUI may use minimal JavaScript for polling. Reports opened from the GUI are the same static artifacts the CLI produces.
- Determinism (ADR-008) is unchanged: the worker invokes the same pipeline; job records in SQLite are orchestration metadata and are excluded from determinism comparisons.

## Open Questions (require human approval — do not resolve in code)

1. **ADR numbering/location:** fold this record into `docs/DECISIONS.md` as ADR-014, or supersede ADR-006 and adopt a `docs/adr/` directory? (Blocked on the Phase 1 session finishing to avoid edit collisions.)
2. **ADR-007 amendment:** confirm WeasyPrint stays the Docker/Linux default with Playwright Windows-only, or standardize on Playwright everywhere for single-renderer simplicity.
3. **Migration tooling for SQLite:** Alembic (already in the handoff's preferred list) vs. minimal versioned DDL scripts.
4. **Retention policy** for job records and job output directories on the RDP host (disk is finite; handoff §30 reserves data-retention policy for humans).
5. **Identity source for `requested_by`:** free-text name field vs. reading the Windows session username of the RDP user. (Spec proposes a default; see `docs/server-gui-spec.md` §Open Questions.)
