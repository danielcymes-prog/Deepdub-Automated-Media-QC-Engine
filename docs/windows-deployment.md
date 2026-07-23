# Deepdub QC — Windows RDP Host Deployment (Phase 3.5)

- **Status:** Draft for implementation
- **Related:** `docs/adr/0004-local-web-gui-on-shared-rdp-host.md`, `docs/server-gui-spec.md`, `docs/server-config-spec.md`
- **Audience:** the engineer installing/upgrading the service on the shared RDP host; assumes local Administrator rights and no prior knowledge of this project.

This document specifies *how the service will be installed*; it contains no application code. Install scripts referenced here (`scripts/windows/...`) are Phase 3.5 implementation deliverables.

## 1. Target Environment

- Windows Server (RDP host shared by ≤2 QC operators). Exact OS version: record in the install log at install time.
- Python 3.13+ (64-bit), installed for all users.
- Media on local disks and/or UNC shares (`\\server\...`) readable by the service account.
- No Docker on this host. Docker remains the canonical *determinism* environment (ADR-008); Windows-native runs must record their full tool environment in every `QCResult` so results are attributable to this host's pinned FFmpeg build (§4).

## 2. Directory Layout on the Host

All paths configurable (`server-config-spec.md`); these are the defaults the install script creates:

```text
C:\DeepdubQC\
├── app\                      # the installed application
│   ├── .venv\                # uv-managed virtualenv
│   ├── current\              # junction/copy of the active release (see §8)
│   └── releases\
│       ├── 0.4.0\            # one directory per installed version
│       └── 0.4.1\
├── bin\
│   └── ffmpeg\
│       ├── ffmpeg.exe        # pinned build (§4)
│       ├── ffprobe.exe
│       └── VERSION.txt       # exact build string + sha256, written at install
├── config\
│   └── server.yaml           # the single config file (server-config-spec.md)
├── data\
│   ├── qc.sqlite3            # job orchestration DB (WAL mode)
│   └── jobs\                 # jobs_root: one directory per job (canonical results)
├── logs\
│   ├── service\              # NSSM-captured stdout/stderr
│   └── app\                  # structured application logs (rotated)
└── shortcuts\
    └── Deepdub QC.url        # master copy of the desktop shortcut (§7)
```

Rationale: one tree under `C:\DeepdubQC` makes backup, permissions, and upgrades comprehensible; `data\` and `config\` survive upgrades untouched; `app\releases\` enables rollback (§8).

## 3. Service Registration

**Primary approach: NSSM** (Non-Sucking Service Manager) wrapping the venv's entrypoint as a real Windows service.

Service definition (performed by `scripts/windows/install-service.ps1`):

| Setting | Value |
|---|---|
| Service name | `DeepdubQC` |
| Display name | `Deepdub QC Server` |
| Application | `C:\DeepdubQC\app\current\.venv\Scripts\deepdub-qc.exe` |
| Arguments | `serve --config C:\DeepdubQC\config\server.yaml` |
| Startup | Automatic (Delayed Start) — waits for network so UNC shares resolve |
| Account | dedicated local/service account `svc-deepdub-qc` (see below), **not** LocalSystem |
| AppStdout/AppStderr | `C:\DeepdubQC\logs\service\service-out.log` / `service-err.log`, NSSM rotation ≥10 MB |
| AppExit (default) | Restart, throttle 5s (crash loop protection) |
| Shutdown | CtrlC first with 30s grace (lets the worker mark the running job), then terminate |

**Service account:** `svc-deepdub-qc` with log-on-as-a-service right, read access to the media shares, and full control of `C:\DeepdubQC\data` and `C:\DeepdubQC\logs` only. Do not run as LocalSystem: the service reads UNC shares (needs a real identity for share ACLs) and executes FFmpeg on untrusted media (least privilege limits blast radius). If domain policy makes a service account slow to obtain, a gMSA is the preferred variant — flagged as an open question.

**Fallback approach: Task Scheduler**, only if NSSM cannot be approved on the host: a task triggered At Startup, running as `svc-deepdub-qc`, "restart on failure" every 1 minute × 3, `Start-Process` of the same entrypoint. Limitations to record if used: no stdout capture (application file logging becomes the only log), weaker restart semantics, no graceful-stop hook. The application must therefore never rely on NSSM-specific behavior.

The service binds `127.0.0.1:<port>` (default 8571) only. Nothing is exposed off-host; RDP login is the access perimeter (`server-gui-spec.md` §7).

## 4. FFmpeg / FFprobe Placement

- A **pinned static build** of FFmpeg/FFprobe is placed in `C:\DeepdubQC\bin\ffmpeg\` by the install script. The exact build (version string, source, sha256) is recorded in `VERSION.txt` and in the install log.
- The config file points to the binaries explicitly (`tools.ffmpeg_path`, `tools.ffprobe_path`). **The application never searches `PATH` and never assumes `/usr/bin/ffmpeg`.** On startup the server verifies both binaries exist, are executable, and reports their version strings on `/api/v1/health` and in the startup log; mismatch against the config's optional `tools.expected_ffmpeg_version` is a startup **error** (determinism guard, ADR-008).
- Upgrading FFmpeg is a deliberate event: new folder `bin\ffmpeg-<version>\`, config change, service restart, and a note in `docs/DECISIONS.md` if behavior-relevant — never an in-place overwrite while the service runs.

## 5. Configuration File

- Location: `C:\DeepdubQC\config\server.yaml` (path passed via `--config`; see `server-config-spec.md` for the full surface, defaults, and validation rules).
- The install script writes an initial config from a template, prompting for: port, media roots, FFmpeg paths.
- The server validates config at startup and **refuses to start** on invalid config (clear error in `service-err.log`), rather than running with guessed values.
- Secrets: none exist in Phase 3.5. The config must not gain secret fields without a corresponding decision on secret storage.

## 6. Logs

| Log | Location | Producer | Rotation |
|---|---|---|---|
| Service wrapper | `C:\DeepdubQC\logs\service\service-{out,err}.log` | NSSM | NSSM, ≥10 MB |
| Application (structured JSON) | `C:\DeepdubQC\logs\app\server-YYYYMMDD.jsonl` | app logging config | daily + size cap, retention `logging.retention_days` (default 30) |
| Per-job | `<jobs_root>\<job_id>\logs\qc.log` | pipeline (unchanged from CLI) | kept with the job directory (retention = job retention, open question) |

Application logs follow handoff §19 (job id, preset, detector, stage, duration, status, error type; never secrets/tokens/environments). Windows Event Log integration is deliberately omitted — NSSM writes service start/stop events there already, which suffices.

## 7. Desktop Shortcut

Per ADR 0004, the "app" on the desktop is a browser shortcut to the persistently running service. **The shortcut launches nothing and must never start the server.**

- Master copy at `C:\DeepdubQC\shortcuts\Deepdub QC.url`, created by the install script:

  ```ini
  [InternetShortcut]
  URL=http://127.0.0.1:8571/
  IconFile=C:\DeepdubQC\app\current\assets\deepdub-qc.ico
  IconIndex=0
  ```

- The install script copies it to `C:\Users\Public\Desktop\` so every RDP operator sees it. (A `.lnk` alternative targeting the default browser with the URL as argument is acceptable if `.url` icon handling proves unreliable on the host's Windows build; the install script owns this choice.)
- The `.ico` asset ships inside the application package so upgrades keep the icon path valid via the `current` junction.
- If the service is down, the browser shows a connection error; operator remedy is documented on the runbook card (§9): check the `DeepdubQC` service in `services.msc` or run `scripts\windows\status.ps1`.

## 8. Install and Upgrade Procedure

Deliverable scripts (PowerShell, in `scripts/windows/`): `install.ps1`, `upgrade.ps1`, `rollback.ps1`, `status.ps1`, `uninstall.ps1`. All idempotent, all logging to `C:\DeepdubQC\logs\install-YYYYMMDD-HHMMSS.log`.

### 8.1 Fresh install (`install.ps1`)

1. Verify prerequisites: 64-bit Python 3.13+, admin rights, NSSM present (bundled with the installer artifact).
2. Create the §2 directory tree and set ACLs (`svc-deepdub-qc`: modify on `data\`+`logs\`, read on the rest).
3. Place pinned FFmpeg build; write `VERSION.txt`.
4. Create `app\releases\<version>\`, unpack the application, create the venv (`uv sync --frozen` from the committed lockfile — no network resolution surprises), and run `playwright install chromium` into the release directory (Chromium is pinned by the Playwright version in `uv.lock`).
5. Point `app\current` (directory junction) at the new release.
6. Write `config\server.yaml` from template (interactive prompts or `-ConfigValues` parameter for scripted installs).
7. Register the `DeepdubQC` service (§3) and start it.
8. **Smoke test (script-enforced):** poll `GET /api/v1/health` until healthy (≤60s); verify reported app version, FFmpeg version, and DB path; fail loudly otherwise.
9. Create desktop shortcuts (§7).

### 8.2 Upgrade (`upgrade.ps1`)

Upgrades must not destroy queue state or job history, and must not interrupt a running job without record.

1. Preflight: `GET /api/v1/health`; report queue depth and whether a job is running. Default behavior **waits** (with timeout flag `-MaxWaitMinutes`, default 30) for the running job to finish while the queue holds new starts (server enters "draining" mode via a maintenance endpoint or, minimally, the script simply waits for `running == 0`). `-Force` skips waiting; the restart will then mark the running job `FAILED (interrupted_by_restart)` per `server-gui-spec.md` F5 — recorded, never silent.
2. Stop the service.
3. Back up `data\qc.sqlite3` (and `-wal`/`-shm`) to `data\backups\pre-<version>-<timestamp>\`.
4. Unpack the new release to `app\releases\<version>\`, build its venv from its lockfile, install its Chromium.
5. Run database migrations (`deepdub-qc db upgrade --config ...`) — migrations are forward-only scripts shipped with the release (tooling choice is an ADR 0004 open question).
6. Re-point the `current` junction. Config and data are untouched (new config keys must have defaults; a required new key without a default is a breaking release and must say so in its release notes).
7. Start the service; run the same smoke test as install step 8.
8. On smoke-test failure: automatic `rollback.ps1` — re-point junction to the previous release, restore the DB backup **only if** migrations ran, restart, re-run smoke test, and exit nonzero with both attempts logged.

### 8.3 Uninstall

Stop and deregister the service, remove `app\`, `bin\`, shortcuts — but leave `data\` and `logs\` in place unless `-PurgeData` is passed (job history is client-relevant evidence; deletion should be a separate, deliberate act pending the retention-policy decision).

## 9. Operator Runbook Card (to be printed/pinned on the host desktop)

- GUI not loading → `services.msc` → is `DeepdubQC` running? If stopped: Start. Still failing → `C:\DeepdubQC\logs\service\service-err.log`, last 50 lines.
- Job stuck `RUNNING` for hours → open job detail, check stage; if genuinely hung, Cancel from the GUI (kills the FFmpeg tree). Then check `logs\qc.log` in the job folder.
- Disk full → job directories under `C:\DeepdubQC\data\jobs\` are the usual growth; retention policy pending (open question) — coordinate before deleting anything.
- Never edit files under `data\jobs\` — they are canonical QC evidence.

## 10. Open Questions (require human approval)

1. **Service account:** local service account vs. domain gMSA (needed for UNC share ACLs under domain policy). Blocker for install on a domain-joined host.
2. **NSSM approval:** NSSM is GPL, widely used, but unmaintained upstream since ~2017 — acceptable for an internal host, or is the Task Scheduler fallback (or WinSW as a third option) preferred?
3. **Retention:** how long do job directories and DB job records live on this host, and is there an archive target? (Handoff §30 reserves retention for humans.)
4. **Backup:** should `data\` be included in an existing host backup regime, or is git-tracked preset + re-runnable QC considered sufficient?
5. **Windows FFmpeg build source:** which static build distribution is approved (e.g., gyan.dev vs. BtbN), given determinism pinning requires a stable, hash-verifiable source?
