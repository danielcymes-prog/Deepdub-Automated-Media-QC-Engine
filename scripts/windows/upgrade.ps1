# Deepdub QC - upgrade to a newer commit (docs/windows-deployment.md section 8.2).
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\upgrade.ps1
#
# Waits for the running job to finish (queued jobs survive the restart and
# are picked up by the new version), backs up the database, moves the repo
# checkout to -Ref, rebuilds the runtime venv, restarts, and smoke-tests.
# On smoke-test failure it automatically rolls back to the previous commit.
# Schema migrations are automatic: the server migrates its SQLite schema at
# startup, so there is no separate migration step to run or to fail.

param(
    [string]$Root = 'C:\DeepdubQC',
    [string]$Ref = 'origin/main',
    [int]$MaxWaitMinutes = 30,
    [switch]$Force,       # skip draining; the interrupted job is marked FAILED (interrupted_by_restart), never silent
    # Leave the new state in place when the smoke test fails, instead of
    # rolling back. Use when the CURRENT version is already broken: rolling
    # back to a broken base ping-pongs between two bad states and hides the
    # real error (observed during the first RDP install).
    [switch]$NoRollback
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Administrator
$state = Read-DeployState -Root $Root
Initialize-DeployLog -Root $Root -Action "upgrade to $Ref"
$repoRoot = $state.repoRoot
$serviceName = $state.serviceName
$port = $state.port

# 1. Preflight: report queue state and drain the in-flight job.
#    Safe property access: the still-running OLD version may predate the
#    `running` field on health; queue_depth (pending+running) is the
#    conservative fallback for draining.
function Get-RunningCount {
    param($Health)
    if ($Health.PSObject.Properties['running']) { return [int]$Health.running }
    return [int]$Health.queue_depth
}
$preflightFailed = $false
try {
    $health = Get-Health -Port $port
    Write-Log "Preflight: v$($health.version), queue_depth=$($health.queue_depth), running=$(Get-RunningCount $health)"
} catch {
    Write-Log 'Service not answering (already stopped?) - skipping drain.' 'Yellow'
    $preflightFailed = $true
}
if (-not $preflightFailed -and -not $Force -and (Get-RunningCount $health) -gt 0) {
    Write-Log "Waiting for the running job to finish (up to $MaxWaitMinutes min; -Force to skip)..."
    $deadline = (Get-Date).AddMinutes($MaxWaitMinutes)
    while ((Get-RunningCount (Get-Health -Port $port)) -gt 0) {
        if ((Get-Date) -ge $deadline) {
            throw "Job still running after $MaxWaitMinutes min. Re-run with -Force to interrupt it (recorded as FAILED), or wait."
        }
        Start-Sleep -Seconds 15
    }
    Write-Log 'Drained: no job running.'
}

# 2. Stop, then back up the database while nothing writes to it.
Stop-QcService -ServiceName $serviceName
$backupDir = Backup-Database -Root $Root -Label 'pre-upgrade'

# 3. Move the checkout. reset --hard discards local edits to TRACKED files
#    (e.g. a uv.lock touched by an accidental plain `uv sync`) but preserves
#    UNTRACKED files - console-editor preset drafts saved on this host live
#    there until committed back, and an upgrade must never destroy them.
$previousCommit = Get-RepoCommit -RepoRoot $repoRoot
& git -C $repoRoot fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed - check network/credentials.' }
& git -C $repoRoot reset --hard $Ref
if ($LASTEXITCODE -ne 0) { throw "git reset --hard $Ref failed." }
$newCommit = Get-RepoCommit -RepoRoot $repoRoot
Write-Log "Checkout: $previousCommit -> $newCommit"
$drafts = (& git -C $repoRoot status --porcelain) | Where-Object { $_ -match '^\?\?' }
if ($drafts) {
    Write-Log "$(@($drafts).Count) untracked file(s) preserved (editor-created preset drafts?) - commit them back during maintenance:" 'Yellow'
    $drafts | ForEach-Object { Write-Log "  $_" 'Yellow' }
}

# 4. Rebuild the venv from the new lock, restart, smoke-test.
try {
    Invoke-RuntimeSync -RepoRoot $repoRoot | Out-Null
    Start-QcService -ServiceName $serviceName
    Invoke-SmokeTest -Root $Root -Port $port | Out-Null
} catch {
    Write-Log "UPGRADE FAILED: $_" 'Red'
    if ($NoRollback) {
        # Deliberate: the operator declared the base broken too. Keep the
        # new checkout so the failure can be diagnosed in place; the DB
        # backup from step 2 is untouched and named in the log above.
        Write-Log "-NoRollback: leaving $newCommit in place for diagnosis (service state unknown)." 'Yellow'
        throw "Upgrade to $Ref failed; NOT rolled back (-NoRollback). See the install log."
    }
    # Automatic rollback (section 8.2 step 8). The DB backup is restored
    # because the new version's startup may already have migrated the schema.
    Write-Log "Rolling back to $previousCommit..." 'Yellow'
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'rollback.ps1') `
        -Root $Root -Commit $previousCommit -DatabaseBackup $backupDir
    if ($LASTEXITCODE -ne 0) {
        Write-Log 'ROLLBACK ALSO FAILED - service needs manual attention (see log above).' 'Red'
    }
    throw "Upgrade to $Ref failed and was rolled back. Both attempts are in the install log."
}

# 5. Record the new state (previousCommit is the rollback target).
Write-DeployState -Root $Root -State @{
    repoRoot        = $state.repoRoot
    serviceName     = $state.serviceName
    port            = $state.port
    nssmPath        = $state.nssmPath
    serviceIdentity = $state.serviceIdentity
    currentCommit   = $newCommit
    previousCommit  = $previousCommit
    installedAt     = $state.installedAt
    upgradedAt      = (Get-Date -Format o)
}
Write-Log "Upgrade complete: $newCommit (rollback target: $previousCommit)" 'Green'
