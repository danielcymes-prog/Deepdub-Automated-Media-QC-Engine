# Deepdub QC — Windows RDP Host Deployment (Phase 3.5)

- **Status:** Implemented (ADR-032) — the scripts in `scripts/windows/` are the executable form of this document.
- **Related:** `docs/adr/0004-local-web-gui-on-shared-rdp-host.md`, `docs/server-gui-spec.md`, `docs/server-config-spec.md`, ADR-032
- **Audience:** the engineer installing/upgrading the service on the shared RDP host; assumes local Administrator rights and no prior knowledge of this project.

This document specifies *how the service is installed*; it contains no application code. The scripts (`scripts/windows/install.ps1`, `upgrade.ps1`, `rollback.ps1`, `status.ps1`, `uninstall.ps1`) implement it — where a detail here and a script disagree, fix one of them; do not let them drift silently.

## 1. Target Environment

- Windows Server (RDP host shared by ≤2 QC operators). Exact OS version: record in the install log at install time.
- Python 3.13+ (64-bit), installed for all users.
- Media on local disks and/or UNC shares (`\\server\...`) readable by the service account.
- No Docker on this host. Docker remains the canonical *determinism* environment (ADR-008); Windows-native runs must record their full tool environment in every `QCResult` so results are attributable to this host's pinned FFmpeg build (§4).

## 2. Directory Layout on the Host

All paths configurable (`server-config-spec.md`); these are the defaults the install script creates:

```text
C:\DeepdubQC\
├── bin\
│   └── ffmpeg\
│       ├── ffmpeg.exe        # pinned build (§4)
│       ├── ffprobe.exe
│       └── VERSION.txt       # exact build string + sha256, written at install
├── browsers\                 # Playwright Chromium (PLAYWRIGHT_BROWSERS_PATH; §8.1)
├── config\
│   ├── server.yaml           # the single config file (server-config-spec.md)
│   └── deploy-state.json     # what is deployed: repo path, commits, service identity
├── data\
│   ├── qc.sqlite3            # job orchestration DB (WAL mode)
│   ├── jobs\                 # jobs_root: one directory per job (canonical results)
│   └── backups\              # pre-upgrade database backups (§8.2)
├── logs\
│   ├── install-*.log         # every install/upgrade/rollback/uninstall run
│   ├── service\              # NSSM-captured stdout/stderr
│   └── app\                  # structured application logs (rotated)
└── shortcuts\
    └── Deepdub QC.url        # master copy of the desktop shortcut (§7)
```

**The application itself runs from the git checkout** (its uv-managed `.venv\`
included), not from a releases tree. ADR-032: this project has no packaged
release artifacts — the repo *is* the release, and git already provides what
the earlier draft's `app\releases\` + junction design was for: exact version
identity (commit sha, recorded in `deploy-state.json`) and rollback
(`git reset --hard <previous commit>`). The checkout may live anywhere;
`install.ps1` records its location and grants the service identity read
access to it.

Rationale: one tree under `C:\DeepdubQC` makes backup, permissions, and
upgrades comprehensible; `data\` and `config\` survive upgrades untouched.

## 3. Service Registration

**Primary approach: NSSM** (Non-Sucking Service Manager) wrapping the venv's entrypoint as a real Windows service (retained by ADR-032: unmaintained upstream but stable and ubiquitous; its exe's sha256 is recorded in the install log).

Service definition (performed by `scripts/windows/install.ps1`):

| Setting | Value |
|---|---|
| Service name | `DeepdubQC` |
| Display name | `Deepdub QC Server` |
| Application | `<repo>\.venv\Scripts\deepdub-qc.exe` |
| Arguments | `serve --config C:\DeepdubQC\config\server.yaml` |
| Startup | Automatic (Delayed Start) — waits for network so UNC shares resolve |
| Account | `NT SERVICE\DeepdubQC` virtual account by default (see below), **not** LocalSystem |
| Environment | `PLAYWRIGHT_BROWSERS_PATH=C:\DeepdubQC\browsers` (§8.1 step 4) |
| AppStdout/AppStderr | `C:\DeepdubQC\logs\service\service-out.log` / `service-err.log`, NSSM rotation ≥10 MB |
| AppExit (default) | Restart, throttle 5s (crash loop protection) |
| Shutdown | CtrlC first with 30s grace (lets the worker mark the running job), then terminate |

**Service account (ADR-032):** default is the per-service **virtual account**
`NT SERVICE\DeepdubQC` — passwordless, profile-less, least privilege, and
grantable in ACLs like any principal. The installer grants it modify on
`data\` + `logs\`, read on the rest of the tree, the repo checkout, and any
`-MediaRoots` passed. Never LocalSystem: the service executes FFmpeg on
untrusted media, and blast radius must stay small.

Virtual accounts authenticate off-host as the machine account, which most
domain shares do not admit — **if the service must read UNC shares, pass a
real account** (`install.ps1 -ServiceAccount DOMAIN\svc-deepdub-qc`; the
password is prompted, never a command-line argument). A gMSA remains the
preferred variant under domain policy. For the shadow-validation phase with
media on local disks, the virtual-account default is sufficient.

**Fallback approach: Task Scheduler**, only if NSSM cannot be used on the host: a task triggered At Startup, running as the service account, "restart on failure" every 1 minute × 3, `Start-Process` of the same entrypoint. Limitations to record if used: no stdout capture (application file logging becomes the only log), weaker restart semantics, no graceful-stop hook. The application must therefore never rely on NSSM-specific behavior.

The service binds `127.0.0.1:<port>` (default 8571) only. Nothing is exposed off-host; RDP login is the access perimeter (`server-gui-spec.md` §7).

## 4. FFmpeg / FFprobe Placement

- A **pinned static build** of FFmpeg/FFprobe is placed in `C:\DeepdubQC\bin\ffmpeg\` by the install script. The exact build (version string, source, sha256) is recorded in `VERSION.txt` and in the install log.
- The config file points to the binaries explicitly (`tools.ffmpeg_path`, `tools.ffprobe_path`). **The application never searches `PATH` and never assumes `/usr/bin/ffmpeg`.** On startup the server verifies both binaries exist, are executable, and reports their version strings on `/api/v1/health` and in the startup log; mismatch against the config's optional `tools.expected_ffmpeg_version` is a startup **error** (determinism guard, ADR-008).
- Upgrading FFmpeg is a deliberate event: new folder `bin\ffmpeg-<version>\`, config change, service restart, and a note in `docs/DECISIONS.md` if behavior-relevant — never an in-place overwrite while the service runs.

## 5. Configuration File

- Location: `C:\DeepdubQC\config\server.yaml` (path passed via `--config`; see `server-config-spec.md` for the full surface, defaults, and validation rules).
- The install script writes an initial config from `config/server.example.yaml`, substituting port (`-Port`), media roots (`-MediaRoots`), and the pinned FFmpeg paths; an existing config is never overwritten.
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

The scripts (PowerShell 5.1, in `scripts/windows/`): `install.ps1`, `upgrade.ps1`, `rollback.ps1`, `status.ps1`, `uninstall.ps1`, sharing `common.ps1`. All idempotent, all logging to `C:\DeepdubQC\logs\install-YYYYMMDD-HHMMSS.log`. State they need across invocations (repo path, current/previous commit, service identity, NSSM path) lives in `config\deploy-state.json` — no secrets, ever.

### 8.1 Fresh install (`install.ps1`)

Run as Administrator **from the repo checkout**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 `
  -NssmPath C:\tools\nssm.exe -FfmpegDir C:\path\to\ffmpeg\bin `
  -MediaRoots 'D:\qc-media'
```

1. Verify prerequisites: admin rights, `uv` on PATH, NSSM at `-NssmPath` (its sha256 goes in the install log).
2. Create the §2 directory tree.
3. Place the pinned FFmpeg build; write `VERSION.txt` (version line + sha256 + source). A fresh config gets `tools.expected_ffmpeg_version` **set automatically** from the pinned build, arming the ADR-008 startup guard.
4. Build the venv **in the repo checkout** with **`uv sync --frozen --no-dev`**, then `playwright install chromium` with `PLAYWRIGHT_BROWSERS_PATH=C:\DeepdubQC\browsers` — Playwright's per-user default location is invisible to the service account, so the location must be explicit and shared. Chromium failure is a warning, not an error: PDF degrades with a note; HTML/JSON (canonical) always render.

   `--no-dev` is not optional. It omits the `dev` and `lint` dependency groups (pytest, ruff, mypy, import-linter), which a delivery host has no use for and may be unable to fetch. Without it, adding a lint tool to the repo becomes a deployment failure on this host. CI proves the CLI and `serve` still work with runtime dependencies only, so this path stays honest.

   Note that `--frozen` only means "do not re-resolve"; it does **not** verify that the lockfile matches `pyproject.toml`. Until 2026-07-26 the committed lock was missing `fastapi`, `uvicorn`, `httpx` and `python-multipart`, so this step could not have installed the server at all. CI now runs `uv lock --check` to make that drift unmergeable — but if a release ever fails here with a missing module, suspect a stale lock first.
5. Write `config\server.yaml` from `config/server.example.yaml` (never overwriting an existing one), substituting FFmpeg paths, presets root, port, and `-MediaRoots` when given.
6. Register the `DeepdubQC` service (§3) and grant the service identity its ACLs.
7. Start the service — **unless** the config is fresh and no `-MediaRoots` were passed (the server refuses example media roots by design; starting it would only record a crash loop). `-NoStart` forces the skip.
8. **Smoke test (script-enforced):** poll `GET /api/v1/health` until healthy (≤60s); verify the app version is reported, the service's `ffmpeg_version` **equals the pinned `VERSION.txt` line**, and the DB path is the expected file; fail loudly otherwise.
9. Create desktop shortcuts (§7) and write `deploy-state.json`.

### 8.2 Upgrade (`upgrade.ps1`)

Upgrades must not destroy queue state or job history, and must not interrupt a running job without record. Default target is `origin/main`; pass `-Ref` for a tag/branch/sha.

1. Preflight: `GET /api/v1/health`; report queue depth and running count. Default behavior **waits** (`-MaxWaitMinutes`, default 30) for `running == 0` — queued (PENDING) jobs survive the restart and are picked up by the new version. `-Force` skips waiting; the restart marks the interrupted job `FAILED (interrupted_by_restart)` per `server-gui-spec.md` F5 — recorded, never silent.
2. Stop the service.
3. Back up `data\qc.sqlite3` (and `-wal`/`-shm`) to `data\backups\pre-upgrade-<timestamp>\`.
4. `git fetch` + `git reset --hard <ref>` in the checkout. `reset --hard` discards local edits to **tracked** files (e.g. a `uv.lock` touched by an accidental plain `uv sync`) but preserves **untracked** files — console-editor preset drafts saved on this host live there until committed back, and an upgrade must never destroy them; the script lists any it finds.
5. Rebuild the venv: `uv sync --frozen --no-dev`.
6. Database migrations are **automatic at startup** (the store applies its schema and lightweight column migrations when the server opens the DB) — there is no separate migration step to run or to fail. Config and data are untouched (new config keys must have defaults; a required new key without a default is a breaking release and must say so in its release notes).
7. Start the service; run the same smoke test as install step 8.
8. On smoke-test failure: automatic `rollback.ps1 -Commit <previous> -DatabaseBackup <step-3 dir>` — the DB backup is restored because the failed version's startup may already have migrated the schema — then exit nonzero with both attempts logged.

### 8.3 Rollback (`rollback.ps1`)

Also runnable standalone (e.g. a regression noticed a day after a green upgrade): stops the service, optionally restores a DB backup (`-DatabaseBackup`), `git reset --hard` to the previous commit recorded in `deploy-state.json` (or `-Commit`), rebuilds the venv, starts, smoke-tests.

### 8.4 Uninstall (`uninstall.ps1`)

Stop and deregister the service, remove `bin\`, `browsers\`, shortcuts — but leave `data\`, `logs\` and `config\` in place unless `-PurgeData` is passed (job history is client-relevant evidence; deletion should be a separate, deliberate act). The repo checkout is never touched.

## 9. Operator Runbook Card (to be printed/pinned on the host desktop)

- GUI not loading → `services.msc` → is `DeepdubQC` running? If stopped: Start. Still failing → `C:\DeepdubQC\logs\service\service-err.log`, last 50 lines.
- Job stuck `RUNNING` for hours → open job detail, check stage; if genuinely hung, Cancel from the GUI (kills the FFmpeg tree). Then check `logs\qc.log` in the job folder.
- Disk full → job directories under `C:\DeepdubQC\data\jobs\` are the usual growth; retention policy pending (open question) — coordinate before deleting anything.
- Never edit files under `data\jobs\` — they are canonical QC evidence.

## 10. Formerly Open Questions — resolved by ADR-032

1. **Service account:** per-service virtual account `NT SERVICE\DeepdubQC` by default (passwordless, least privilege); a real account via `-ServiceAccount` only when UNC shares are in play; gMSA remains the preferred domain variant when IT provides one. See §3.
2. **NSSM:** retained (stable, ubiquitous; sha256 of the exe recorded in the install log). Task Scheduler stays the documented fallback; the application never relies on NSSM-specific behavior.
3. **Retention:** v1 keeps everything — no automatic deletion of job directories or DB records. Deletion remains a deliberate human act (handoff §30); `status.ps1` reports `data\jobs` size so growth is visible, and a retention policy can be revisited with usage data.
4. **Backup:** the scripts guarantee pre-upgrade DB backups under `data\backups\`; inclusion of `data\` in a host-level backup regime is an IT decision and does not block deployment.
5. **Windows FFmpeg build source:** gyan.dev release builds (versioned archives, stable URLs); BtbN GitHub builds are an acceptable alternative. Whichever is used, `VERSION.txt` + the auto-armed `expected_ffmpeg_version` pin make the choice attributable and drift-fatal.
