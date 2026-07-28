# Deepdub QC — Watch Folders (Hot Folders) Specification

- **Status:** Accepted (2026-07-27) — §9 decisions confirmed by the operator. Implementation ADR: ADR-027.
- **Related:** `docs/server-config-spec.md`, `docs/server-gui-spec.md`, `docs/windows-deployment.md`, ADR-003 (presets), ADR-025 (Vidchecker import), `docs/vidchecker-import.md`
- **Origin:** Vidchecker's dropbox model (`AddDropbox`/`ListDropboxes`/`GetWatchFolderStatusDetails`) — the automation backbone of file-based QC operations. This spec adapts it to the existing single-node server.
- **Audience:** reviewer deciding the open questions in §9, then the implementing engineer.

## 1. Goal and non-goals

**Goal:** a file dropped into a monitored folder is QC'd automatically against
the preset bound to that folder, with no console interaction, and the result
is visible in the existing jobs list exactly like a manually submitted job.

**Non-goals (v1):**
- Cloud bucket watchers (S3/GCS) — the watcher interface must not preclude
  them, but v1 is local/UNC directories only.
- Console-based CRUD of watch folders — v1 declares them in `server.yaml`
  (versionable, no new mutating admin surface on the shared host); the console
  gets a read-only status panel. Runtime CRUD is a later phase if operators
  need it.
- Correction — a §30-reserved policy conversation before any code.
- ~~Verdict-based file routing and webhooks~~ — delivered in the routing
  follow-up (§10, ADR-028).

## 2. Operating model

The watcher runs inside the existing server process (same lifecycle as the
queue worker; NSSM restarts cover it). Each configured watch folder is scanned
by polling — no OS-specific notification APIs, because the RDP host reads from
UNC/network shares where change notification is unreliable. Poll interval is
per-folder with a sane default (10 s).

A scan enqueues a file only when ALL of:

1. Its extension is in the folder's `extensions` allowlist.
2. It is **stable**: same size and mtime across two consecutive scans AND its
   mtime is at least `settle_seconds` (default 30) in the past. Files still
   being copied over the network must never trigger a job.
3. It has not already been enqueued by the watcher (§4 dedup).
4. The queue has capacity; a full queue defers the file to a later scan
   (never dropped, logged at WARNING).

Jobs enter through the existing `JobStore.enqueue` path with
`requested_by: "watch:<folder-name>"`, so provenance is visible in the console
and reports. The existing single-worker, one-job-at-a-time model is unchanged.

## 3. Configuration shape (server.yaml)

```yaml
watch_folders:
  - name: marimba-deliveries          # unique, shown in console + requested_by
    path: 'D:\dropboxes\marimba'      # must be inside media_roots
    preset: marimba_deliver_audio@1.0.0
    extensions: [wav, mov, mxf]       # lowercase, no dot
    enabled: true
    poll_seconds: 10                  # optional, default 10
    settle_seconds: 30                # optional, default 30
    recursive: false                  # v1 default: top level only
    # Verdict routing + webhook (§10, ADR-028) — all optional:
    on_pass:    { move_to: 'D:\qc\pass' }
    on_warning: { move_to: 'D:\qc\warning' }   # or copy_to; exactly one per action
    on_reject:  { move_to: 'D:\qc\reject' }
    webhook_url: 'https://example.internal/hooks/qc'
```

Validation at startup (server refuses to start on violation, matching the
strict config policy):
- `path` exists, is a directory, and is inside a configured media root.
- `preset` resolves in the catalog and loads.
- names unique; extensions non-empty.

A preset that later becomes unloadable (e.g. edited to reference an unknown
parameter) disables that folder at scan time with an ERROR log and a visible
error state in the console panel — it must not crash the watcher loop or
affect other folders.

## 4. Deduplication and re-drops

The store already keys duplicates by `(input_path, size, preset_id,
preset_version)`. The watcher-specific rules:

- **Same file, unchanged:** never re-enqueued. The watcher records
  `(path, size, mtime)` of everything it has enqueued in a new
  `watch_seen` table (persistent — a service restart must not re-QC a folder
  full of already-processed files).
- **Same path, new bytes (re-delivery):** size or mtime changed after the file
  settled again → enqueued as a NEW job with `duplicate_override` set (the
  store's inflight-duplicate confirm flow is a console interaction; the
  watcher bypasses it deliberately and the report notes the re-drop).
- **File deleted and re-dropped identical:** treated as a re-delivery
  (mtime changes). This matches operator intent: "I dropped it again because
  I want it QC'd again."

## 5. Failure semantics

| Condition | Behavior |
|---|---|
| Unreadable file (locked, ACL) | Deferred with WARNING; retried next scan; after `max_attempts` (default 10) marked failed in the panel and skipped until it changes. |
| Folder unreachable (share down) | Folder enters error state (panel + ERROR log); scanning continues on other folders; recovers automatically when reachable. |
| Preset fails to load | Folder disabled in error state (§3). |
| Queue full | File deferred, not dropped (§2.4). |
| Server restart mid-scan | Safe: `watch_seen` is persistent; the settle rule re-applies; jobs already enqueued are in the store. |

Nothing in the *watcher* deletes or moves input files; post-QC movement is
the routing step's job (§10) and runs only after a terminal verdict.

## 6. Console surface (read-only, v1)

A "Watch folders" panel (new nav entry) listing each folder: name, path,
bound preset (with draft/approved pill), enabled/error state with reason,
last scan time, files enqueued today, and current deferrals. No mutations.
The jobs list gains nothing new — watcher jobs appear with their
`watch:<name>` requester.

## 7. Observability

Structured logs per event: scan started/completed (DEBUG), file enqueued
(INFO: folder, file, job id), deferral (WARNING with reason), folder error
(ERROR). A `watch_folder_status` section in the existing
`/api/v1/health`-style surface (or a dedicated `/api/v1/watch-folders`)
backs the console panel. No secrets, no directory listings in logs.

## 8. Testing obligations

- Unit: stability detection (growing file, mtime churn, settle boundary),
  dedup/re-drop matrix over a fake clock, config validation failures.
- Integration: temp-dir end-to-end — drop file → job appears PENDING with
  `watch:` provenance; unreadable-file deferral; restart-safety (re-instantiate
  watcher over same store, nothing re-enqueued).
- The watcher must be injectable with a fake scanner clock — no `sleep()`
  in tests.

## 9. Operator decisions (confirmed 2026-07-27)

1. **Folder inventory:** deferred to deployment — pure config entries; the
   shape supports any number.
2. **Draft presets:** ALLOWED. Consistent with the console; draft status is
   visible in the panel and reports; approval flow is unchanged.
3. **Recursive scanning:** TOP LEVEL ONLY in v1 (subfolders act as staging);
   per-folder `recursive: true` remains a config option for later.
4. **Post-QC file handling:** LEAVE FILES IN PLACE in v1; verdict-based
   moving arrives with the routing follow-up.
5. **`watch_seen` retention:** 90 days, pruned during scans (job-record
   retention remains a separately reserved decision).

## 10. Verdict routing and completion webhooks (follow-up, ADR-028)

Delivered after v1 shipped; activates the config keys reserved in §3. All
behavior is a **post-terminal step in the worker** — it runs strictly after
the job's terminal store write and can never alter a verdict, a report, or a
job status. Every outcome (success or degradation) is recorded as a progress
note on the job.

**Routing** (`on_pass` / `on_warning` / `on_reject`):

- Applies only to COMPLETED watch-folder jobs; the verdict maps PASS →
  `on_pass`, WARNING → `on_warning`, FAIL → `on_reject`. ERROR is not a
  media verdict and never routes. FAILED/CANCELLED jobs leave the file in
  place for investigation.
- An unset key means "leave the file in place". There is **no fallback**
  between verdicts (route warnings with passes by pointing `on_warning` at
  the same directory — explicit config over implied policy).
- Each action takes exactly one of `move_to` / `copy_to`. Destinations must
  exist at startup, live inside `media_roots`, and be outside the folder's
  scanned area (a destination the scanner can see would re-enqueue routed
  files forever; with `recursive: false` a subfolder of the dropbox is fine
  and idiomatic). Name collisions get a `_1`/`_2` suffix — never overwrite.
- A routing failure (file vanished, destination unwritable) logs ERROR and
  notes the job; the verdict stands and the file stays where it is.
- Routing policy lives on the folder binding, never in presets (ADR-003:
  presets describe media requirements, not site plumbing). Manual console
  submissions never route.

**Webhook** (`webhook_url`, per folder):

- Fires for COMPLETED and FAILED watch jobs (CANCELLED is a deliberate human
  act and notifies nobody). Payload: job identity, folder, preset,
  `qc_status`/error fields, where the file was routed, and the **full
  report.json verbatim** for completed jobs (ADR-002 — receivers get the
  source of truth, not a re-rendering).
- Delivery: POST with a 10 s timeout; connection errors and 5xx retry twice
  (1 s, 5 s); other statuses are treated as a misconfigured endpoint and not
  retried. Failure is logged and noted on the job — never blocks or fails it.
- Webhook URLs may embed tokens: they are never logged and never shown in
  the console; logs and notes carry only the target host.
