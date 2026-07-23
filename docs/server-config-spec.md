# Deepdub QC — Server Configuration Specification (Phase 3.5)

- **Status:** Draft for implementation
- **Related:** `docs/adr/0004-local-web-gui-on-shared-rdp-host.md`, `docs/server-gui-spec.md`, `docs/windows-deployment.md`

## 1. Principles

1. **One file, explicit path.** The entire server configuration lives in a single YAML file passed as `deepdub-qc serve --config <path>` (default location on the RDP host: `C:\DeepdubQC\config\server.yaml`). No config discovery walk, no merging of multiple files — on a shared host, "which config is actually live" must have exactly one answer.
2. **Validated by a Pydantic settings model.** Same pattern as the rest of the codebase (ADR-004): the YAML is parsed into a typed `ServerConfig` model; unknown keys are **errors** (typo protection), invalid values abort startup with a message naming the key, the given value, and the constraint. The server never starts on a bad config.
3. **Environment-variable overrides** with prefix `DEEPDUB_QC_` (e.g., `DEEPDUB_QC_SERVER__PORT=9000`, double underscore as section separator) exist for CI and ad-hoc testing, and are logged at startup when used. The YAML file is the operational norm.
4. **Every path is `pathlib`-handled and UNC-aware.** Windows `\\server\share\...` values must round-trip correctly; forward or back slashes both accepted in YAML.
5. **Defaults encode the ADR 0004 envelope.** The caps below are design statements, not tuning knobs: raising them materially means Phase 7, not a config edit.
6. **No secrets.** Phase 3.5 config contains no credentials. Adding a secret field requires a decision on secret storage first.
7. **Startup echo:** the effective config (all keys, resolved values) is written to the structured log at startup — this is safe *because* no secrets exist; that property must be preserved.

## 2. Configuration Surface

### 2.1 `server` — network and GUI

| Key | Type | Default | Rationale |
|---|---|---|---|
| `server.host` | str | `127.0.0.1` | Localhost-only: RDP login is the perimeter (`server-gui-spec.md` §7). Binding non-loopback is allowed but logged as a prominent startup WARNING, since there is no authentication. |
| `server.port` | int (1024–65535) | `8571` | Fixed non-ephemeral port so the desktop shortcut URL stays valid. 8571 avoids common dev ports (8000/8080) that other tools on a shared host may grab. |
| `server.max_gui_sessions` | int ≥1 | `2` | Operator ceiling per ADR 0004. Deliberately small; see Principle 5. |
| `server.gui_session_ttl_minutes` | int ≥1 | `15` | Idle time before a GUI session slot is reclaimed. Long enough to survive a coffee break, short enough that an operator who logged off doesn't block the second slot all afternoon. |
| `server.queue_poll_interval_seconds` | int 1–60 | `2` | GUI polling cadence. 2s feels live to a human; at ≤2 sessions the load is negligible (~1 req/s worst case). |

### 2.2 `jobs` — queue and execution

| Key | Type | Default | Rationale |
|---|---|---|---|
| `jobs.max_concurrent_jobs` | int ≥1 | `1` | Serial execution: FFmpeg saturates the host per job; serialization keeps runtimes predictable and per-job wall times honest. Values >1 are accepted (the knob exists per the Phase 3.5 requirements) but startup logs a WARNING that concurrent runs on one host contend for disk/CPU and blur runtime metrics. |
| `jobs.max_queue_length` | int ≥1 | `20` | Backstop against runaway scripted submission. Two humans will never legitimately queue 20 jobs; hitting this signals a bug or misuse (GUI error E6). |
| `jobs.max_job_duration_minutes` | int ≥1 | `240` | Handoff §20 requires a job-duration ceiling. 4h accommodates slower-than-real-time full-file analysis of feature-length content (handoff §29); a hung FFmpeg is killed rather than blocking the queue forever. |
| `jobs.max_file_size_gb` | int ≥1 | `150` | Handoff §20 requires a file-size ceiling; architecture already assumes >100 GB masters are real (project instructions), so the default must not reject legitimate deliverables. |
| `jobs.duplicate_inflight_policy` | enum: `warn_confirm` \| `reject` \| `allow` | `warn_confirm` | Same input hash + preset id+version already pending/running → GUI warns and requires explicit override (E5). `reject`/`allow` cover future scripted use. |

### 2.3 `paths` — filesystem layout

| Key | Type | Default (Windows host) | Rationale |
|---|---|---|---|
| `paths.media_roots` | list[path], min 1 item | — **(required, no default)** | The allowlist of directories/shares from which input media may be read (security §20: path validation). No safe default exists; forcing an explicit choice at install time is the point. Each entry must exist and be readable at startup (WARNING if a share is temporarily unreachable, ERROR if none are usable). |
| `paths.jobs_root` | path | `C:\DeepdubQC\data\jobs` | Where job output directories are created. Local disk strongly recommended (evidence + raw output are write-heavy); a UNC value is accepted with a startup WARNING. |
| `paths.database` | path | `C:\DeepdubQC\data\qc.sqlite3` | SQLite file (WAL mode). Must be on a local disk — SQLite on SMB is a known corruption risk, so a UNC value here is a startup **ERROR**, not a warning. |
| `paths.presets_root` | path | `<app>\presets` | Where the preset loader reads client presets from — the same directory structure git tracks (ADR-003, ADR-013). Overridable so a host can pin a specific checkout. |

### 2.4 `tools` — external binaries

| Key | Type | Default | Rationale |
|---|---|---|---|
| `tools.ffmpeg_path` | path | — **(required)** | Never resolved from `PATH`, never assumed Unix-located (ADR 0004 pt. 7). Must exist and be executable at startup. |
| `tools.ffprobe_path` | path | — **(required)** | Same. |
| `tools.expected_ffmpeg_version` | str \| null | `null` | When set, the reported version string must match at startup or the server refuses to run — the Windows-native equivalent of ADR-008's Docker pin. `windows-deployment.md` §4 sets this at install. |
| `tools.subprocess_timeout_seconds` | int ≥1 | `600` | Per-invocation ceiling for tool calls (handoff §14/§20), distinct from the whole-job ceiling. 10 min covers slow probes on large UNC-hosted files. |

### 2.5 `pdf` — report rendering

| Key | Type | Default | Rationale |
|---|---|---|---|
| `pdf.renderer` | enum: `playwright` \| `weasyprint` | `playwright` | Playwright/Chromium on Windows (ADR 0004 pt. 6, amending ADR-007). Both implementations sit behind the `PdfRenderer` interface (ADR-012); Docker/Linux deployments may set `weasyprint`. |
| `pdf.render_timeout_seconds` | int ≥1 | `120` | A wedged headless Chromium must not hold the worker; failure degrades to JSON+HTML with a visible warning (GUI error E10), never a hang. |

### 2.6 `logging`

| Key | Type | Default | Rationale |
|---|---|---|---|
| `logging.level` | enum: `DEBUG`\|`INFO`\|`WARNING`\|`ERROR` | `INFO` | Structured JSON app logs per handoff §19. |
| `logging.directory` | path | `C:\DeepdubQC\logs\app` | Separate from NSSM's service-wrapper logs (`windows-deployment.md` §6). |
| `logging.retention_days` | int ≥1 | `30` | Server log retention only. Job directory retention is a pending human decision and deliberately **not** a config key yet — adding a knob would pre-empt handoff §30. |

## 3. Example `server.yaml`

```yaml
# Deepdub QC server configuration — C:\DeepdubQC\config\server.yaml
schema_version: 1

server:
  host: 127.0.0.1
  port: 8571
  max_gui_sessions: 2
  gui_session_ttl_minutes: 15
  queue_poll_interval_seconds: 2

jobs:
  max_concurrent_jobs: 1
  max_queue_length: 20
  max_job_duration_minutes: 240
  max_file_size_gb: 150
  duplicate_inflight_policy: warn_confirm

paths:
  media_roots:
    - '\\mediaserver\deliveries'
    - 'D:\qc-media'
  jobs_root: 'C:\DeepdubQC\data\jobs'
  database: 'C:\DeepdubQC\data\qc.sqlite3'
  presets_root: 'C:\DeepdubQC\app\current\presets'

tools:
  ffmpeg_path: 'C:\DeepdubQC\bin\ffmpeg\ffmpeg.exe'
  ffprobe_path: 'C:\DeepdubQC\bin\ffmpeg\ffprobe.exe'
  expected_ffmpeg_version: '7.1'   # set by install script from VERSION.txt
  subprocess_timeout_seconds: 600

pdf:
  renderer: playwright
  render_timeout_seconds: 120

logging:
  level: INFO
  directory: 'C:\DeepdubQC\logs\app'
  retention_days: 30
```

`schema_version` guards future config-format migrations: the server rejects a config whose major schema version it does not understand, with a pointer to the upgrade notes.

## 4. Validation Summary (startup behavior)

| Condition | Behavior |
|---|---|
| Unknown key anywhere | ERROR — refuse to start (typo protection) |
| Missing required key (`media_roots`, `ffmpeg_path`, `ffprobe_path`) | ERROR with the key name and an example value |
| `paths.database` on UNC | ERROR (SQLite-on-SMB corruption risk) |
| `server.host` not loopback | start, but prominent WARNING (no auth exists) |
| `jobs.max_concurrent_jobs` > 1 | start, WARNING (contention + runtime-metric blur) |
| A `media_roots` entry unreachable | WARNING per entry; ERROR if none usable |
| FFmpeg version mismatch vs. `expected_ffmpeg_version` | ERROR (determinism guard, ADR-008) |
| Env-var override active | INFO log line per overridden key |
| Effective config | echoed to structured log at startup (no secrets exist by design) |

## 5. Explicit Non-Keys

Deliberately **not** configurable in Phase 3.5, to keep the envelope honest:

- Job-directory retention (pending human decision, handoff §30).
- Authentication/user management (Phase 7 uses Deepdub auth infrastructure).
- External AI providers (no AI code path exists in Phase 3.5; handoff §20).
- Worker pool type / queue backend (single in-process worker is the design, ADR 0004).
- Report content options — those belong to *presets* (`report:` block, handoff §12), never to server config: what a report contains must be reproducible from preset + input alone.

## 6. Open Questions (require human approval)

1. `jobs.max_file_size_gb = 150` — confirm against real current deliverable sizes (largest known master + margin).
2. `jobs.max_job_duration_minutes = 240` — confirm against measured Phase 4/5 full-analysis runtimes on the actual host hardware.
3. Should `server.port = 8571` be registered/reserved in internal IT documentation to prevent collisions with other tooling on the shared host?
4. `duplicate_inflight_policy` default (`warn_confirm`) — acceptable, or should operations prefer hard `reject`?
