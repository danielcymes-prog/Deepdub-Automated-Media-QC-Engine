# Deepdub QC — roll back to a previous commit (docs/windows-deployment.md section 8.2).
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\rollback.ps1
#
# Default target is the commit recorded before the last upgrade. Pass
# -DatabaseBackup to also restore the SQLite state from a backup directory
# (upgrade.ps1 does this automatically when its smoke test fails, because
# the failed version's startup may already have migrated the schema).

param(
    [string]$Root = 'C:\DeepdubQC',
    [string]$Commit = '',
    [string]$DatabaseBackup = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Administrator
$state = Read-DeployState -Root $Root
Initialize-DeployLog -Root $Root -Action 'rollback'
$repoRoot = $state.repoRoot
$serviceName = $state.serviceName
$port = $state.port

if (-not $Commit) {
    $Commit = $state.previousCommit
    if (-not $Commit) { throw 'No previous commit recorded and no -Commit given — nothing to roll back to.' }
}

Stop-QcService -ServiceName $serviceName

if ($DatabaseBackup) {
    if (-not (Test-Path $DatabaseBackup)) { throw "Backup directory not found: $DatabaseBackup" }
    # Remove current WAL sidecars first: restoring an older main DB under a
    # newer -wal would replay the wrong journal.
    foreach ($suffix in @('', '-wal', '-shm')) {
        Remove-Item (Join-Path $Root "data\qc.sqlite3$suffix") -ErrorAction SilentlyContinue
    }
    Copy-Item (Join-Path $DatabaseBackup '*') (Join-Path $Root 'data\') -Force
    Write-Log "Database restored from $DatabaseBackup"
}

$fromCommit = Get-RepoCommit -RepoRoot $repoRoot
& git -C $repoRoot reset --hard $Commit
if ($LASTEXITCODE -ne 0) { throw "git reset --hard $Commit failed." }
Write-Log "Checkout: $fromCommit -> $Commit"

Invoke-RuntimeSync -RepoRoot $repoRoot | Out-Null
Start-QcService -ServiceName $serviceName
Invoke-SmokeTest -Root $Root -Port $port | Out-Null

Write-DeployState -Root $Root -State @{
    repoRoot        = $state.repoRoot
    serviceName     = $state.serviceName
    port            = $state.port
    nssmPath        = $state.nssmPath
    serviceIdentity = $state.serviceIdentity
    currentCommit   = $Commit
    previousCommit  = $fromCommit
    installedAt     = $state.installedAt
    rolledBackAt    = (Get-Date -Format o)
}
Write-Log "Rollback complete: running $Commit" 'Green'
