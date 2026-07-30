# Deepdub QC — host status report (docs/windows-deployment.md section 9).
# No admin required:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\status.ps1
#
# One screen answering the runbook questions: is the service up, is it
# healthy, what exactly is it running (commit + pinned ffmpeg), how big is
# the data tree, and what were the last errors. Exit code 0 = healthy.

param(
    [string]$Root = 'C:\DeepdubQC'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$state = Read-DeployState -Root $Root
$healthy = $false

Write-Host "== Deepdub QC status ==" -ForegroundColor Cyan

$service = Get-Service $state.serviceName -ErrorAction SilentlyContinue
if ($service) {
    $color = if ($service.Status -eq 'Running') { 'Green' } else { 'Red' }
    Write-Host "Service:  $($state.serviceName) is $($service.Status) (account: $($state.serviceIdentity))" -ForegroundColor $color
} else {
    Write-Host "Service:  $($state.serviceName) NOT REGISTERED — run install.ps1" -ForegroundColor Red
}

try {
    $health = Get-Health -Port $state.port
    $healthy = $true
    Write-Host "Health:   v$($health.version) — queue_depth=$($health.queue_depth), gui_sessions=$($health.active_gui_sessions)" -ForegroundColor Green
    # Fields added with the deployment scripts; a pre-upgrade service omits them.
    foreach ($field in @('running', 'ffmpeg_version', 'database')) {
        if ($health.PSObject.Properties[$field]) {
            Write-Host ("{0,-9} {1}" -f "$($field):", $health.$field)
        }
    }
} catch {
    Write-Host "Health:   /api/v1/health not answering on port $($state.port)" -ForegroundColor Red
}

$commit = (& git -C $state.repoRoot log -1 --format='%h %s (%ci)' 2>$null)
Write-Host "Commit:   $commit"
$drafts = (& git -C $state.repoRoot status --porcelain 2>$null) | Where-Object { $_ -match '^\?\?' }
if ($drafts) {
    Write-Host "Drafts:   $(@($drafts).Count) untracked file(s) in the checkout (editor-created presets? commit them back)" -ForegroundColor Yellow
}

$pinned = Join-Path $Root 'bin\ffmpeg\VERSION.txt'
if (Test-Path $pinned) {
    Write-Host "Pinned:   $(Get-Content $pinned | Select-Object -First 1)"
}

$jobsDir = Join-Path $Root 'data\jobs'
if (Test-Path $jobsDir) {
    $jobs = Get-ChildItem $jobsDir -Directory -ErrorAction SilentlyContinue
    $bytes = (Get-ChildItem $jobsDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    $gb = if ($bytes) { [math]::Round($bytes / 1GB, 2) } else { 0 }
    Write-Host "Jobs:     $(@($jobs).Count) job dir(s), $gb GB under data\jobs (retention: keep everything — deletion is a human act)"
}

$errLog = Join-Path $Root 'logs\service\service-err.log'
if ((Test-Path $errLog) -and (Get-Item $errLog).Length -gt 0) {
    Write-Host "Last stderr lines ($errLog):" -ForegroundColor Yellow
    Get-Content $errLog -Tail 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
}

if (-not $healthy) { exit 1 }
