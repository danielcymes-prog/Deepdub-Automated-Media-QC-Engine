# Deepdub QC - shared deployment helpers (docs/windows-deployment.md).
# Dot-sourced by the scripts in this directory; not runnable on its own.
# Windows PowerShell 5.1 compatible: no pwsh-only syntax.

Set-StrictMode -Version 3.0

$script:LogFile = $null

function Initialize-DeployLog {
    param([string]$Root, [string]$Action)
    $logDir = Join-Path $Root 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:LogFile = Join-Path $logDir "install-$stamp.log"
    Write-Log "== Deepdub QC $Action - $stamp =="
}

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    Write-Host $Message -ForegroundColor $Color
    if ($script:LogFile) {
        "$(Get-Date -Format o)  $Message" | Add-Content -Path $script:LogFile
    }
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This script must run from an elevated (Administrator) PowerShell.'
    }
}

# --- deployment state -------------------------------------------------------
# One JSON file records what the scripts need across invocations: where the
# repo checkout lives, which commit is running, which ran before (rollback
# target), and where NSSM is. Never contains secrets.

function Get-StatePath { param([string]$Root) Join-Path $Root 'config\deploy-state.json' }

function Read-DeployState {
    param([string]$Root)
    $path = Get-StatePath $Root
    if (-not (Test-Path $path)) {
        throw "No deployment state at $path - run install.ps1 first."
    }
    Get-Content $path -Raw | ConvertFrom-Json
}

function Write-DeployState {
    param([string]$Root, [hashtable]$State)
    $State | ConvertTo-Json | Set-Content (Get-StatePath $Root)
}

# --- git / venv --------------------------------------------------------------

function Get-RepoCommit {
    param([string]$RepoRoot)
    (& git -C $RepoRoot rev-parse HEAD).Trim()
}

function Invoke-RuntimeSync {
    # Runtime dependencies ONLY (--no-dev): a delivery host has no use for
    # pytest/ruff/mypy and may be unable to fetch them; --frozen means the
    # committed lock is the contract (docs/windows-deployment.md section 8.1).
    # --group pdf adds playwright so report.pdf renders on this host.
    param([string]$RepoRoot)
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv not found on PATH - install uv first (https://docs.astral.sh/uv/).'
    }
    # copy, never hardlink: uv's default hardlinks venv files from the
    # per-user cache, and a hardlinked file keeps the CACHE's ACLs - the
    # service account cannot read the installing user's profile, so imports
    # failed intermittently depending on which files happened to be linked
    # (first observed as 'No module named deepdub_qc' on the RDP host).
    $env:UV_LINK_MODE = 'copy'
    Push-Location $RepoRoot
    try {
        & uv sync --frozen --no-dev --group pdf
        if ($LASTEXITCODE -ne 0) { throw "uv sync --frozen --no-dev --group pdf failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    $entry = Join-Path $RepoRoot '.venv\Scripts\deepdub-qc.exe'
    if (-not (Test-Path $entry)) {
        throw "Entrypoint missing after sync: $entry - incomplete checkout or stale lockfile."
    }
    $entry
}

# --- health / smoke test -----------------------------------------------------

function Get-Health {
    param([int]$Port)
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 5
}

function Wait-Healthy {
    param([int]$Port, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try { return Get-Health -Port $Port } catch { Start-Sleep -Seconds 3 }
    }
    throw "Service did not answer /api/v1/health within ${TimeoutSeconds}s."
}

function Invoke-SmokeTest {
    # Script-enforced (docs/windows-deployment.md section 8.1 step 8): the
    # service must be healthy AND attributable - app version present, the
    # ffmpeg it resolved is the pinned one, the DB is the expected file.
    param([string]$Root, [int]$Port)
    $health = Wait-Healthy -Port $Port
    if (-not $health.version) { throw 'Smoke test: health reports no app version.' }
    $pinned = Get-Content (Join-Path $Root 'bin\ffmpeg\VERSION.txt') | Select-Object -First 1
    if (-not $health.ffmpeg_version) {
        throw 'Smoke test: health reports no ffmpeg version (service cannot run the pinned binary?).'
    }
    if ($health.ffmpeg_version -ne $pinned) {
        throw "Smoke test: service ffmpeg '$($health.ffmpeg_version)' != pinned '$pinned' (determinism guard, ADR-008)."
    }
    $expectedDb = Join-Path $Root 'data\qc.sqlite3'
    if ($health.database -ne $expectedDb) {
        Write-Log "NOTE: database is $($health.database) (host default is $expectedDb)" 'Yellow'
    }
    Write-Log "Smoke test passed: v$($health.version), $($health.ffmpeg_version), queue=$($health.queue_depth)" 'Green'
    $health
}

# --- service control ---------------------------------------------------------

function Stop-QcService {
    param([string]$ServiceName)
    $service = Get-Service $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne 'Stopped') {
        Write-Log "Stopping $ServiceName (CtrlC grace lets the worker mark a running job)..."
        Stop-Service $ServiceName
        $service.WaitForStatus('Stopped', (New-TimeSpan -Seconds 60))
    }
}

function Start-QcService {
    param([string]$ServiceName)
    Write-Log "Starting $ServiceName..."
    Start-Service $ServiceName
}

function Backup-Database {
    # SQLite in WAL mode: the -wal/-shm sidecars are part of the database
    # state and must travel with it. Only valid while the service is STOPPED.
    param([string]$Root, [string]$Label)
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $Root "data\backups\$Label-$stamp"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $copied = 0
    foreach ($suffix in @('', '-wal', '-shm')) {
        $file = Join-Path $Root "data\qc.sqlite3$suffix"
        if (Test-Path $file) { Copy-Item $file $backupDir; $copied++ }
    }
    Write-Log "Database backup ($copied file(s)): $backupDir"
    $backupDir
}
