# Deepdub QC — Windows service installation (docs/windows-deployment.md).
# Run as Administrator from the repo checkout:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install-service.ps1 `
#     -NssmPath C:\tools\nssm.exe -FfmpegDir C:\ffmpeg\bin
#
# Creates the C:\DeepdubQC tree, copies a pinned ffmpeg, writes an initial
# config (if absent), registers the NSSM service, and drops the browser
# shortcut. Idempotent: re-running updates the service definition.

param(
    [string]$Root = 'C:\DeepdubQC',
    [Parameter(Mandatory = $true)][string]$NssmPath,
    [Parameter(Mandatory = $true)][string]$FfmpegDir,   # dir containing ffmpeg.exe/ffprobe.exe
    [string]$ServiceName = 'DeepdubQC',
    [int]$Port = 8571,
    [string]$ServiceAccount = ''                        # empty = LocalService fallback; prefer svc-deepdub-qc
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

Write-Host "== Deepdub QC service install ==" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

# 1. Directory tree (docs/windows-deployment.md section 2)
foreach ($dir in @('config', 'data\jobs', 'logs\service', 'logs\app', 'bin\ffmpeg', 'shortcuts')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}

# 2. Pinned ffmpeg copy + VERSION.txt (section 4)
foreach ($exe in @('ffmpeg.exe', 'ffprobe.exe')) {
    $source = Join-Path $FfmpegDir $exe
    if (-not (Test-Path $source)) { throw "Not found: $source" }
    Copy-Item $source (Join-Path $Root "bin\ffmpeg\$exe") -Force
}
$versionLine = (& (Join-Path $Root 'bin\ffmpeg\ffmpeg.exe') -version 2>&1 | Select-Object -First 1)
$hash = (Get-FileHash (Join-Path $Root 'bin\ffmpeg\ffmpeg.exe') -Algorithm SHA256).Hash
"$versionLine`nsha256=$hash`ninstalled=$(Get-Date -Format o)" |
    Set-Content (Join-Path $Root 'bin\ffmpeg\VERSION.txt')
Write-Host "Pinned ffmpeg: $versionLine"

# 3. Initial config from the example (never overwrite an existing one)
$configPath = Join-Path $Root 'config\server.yaml'
if (-not (Test-Path $configPath)) {
    $config = Get-Content (Join-Path $RepoRoot 'config\server.example.yaml') -Raw
    $config = $config -replace "ffmpeg_path: '[^']*'", "ffmpeg_path: '$Root\bin\ffmpeg\ffmpeg.exe'"
    $config = $config -replace "ffprobe_path: '[^']*'", "ffprobe_path: '$Root\bin\ffmpeg\ffprobe.exe'"
    $config = $config -replace "presets_root: '[^']*'", "presets_root: '$RepoRoot\presets'"
    $config = $config -replace 'port: \d+', "port: $Port"
    Set-Content $configPath $config
    Write-Host "Wrote initial config: $configPath — EDIT media_roots before first start!" -ForegroundColor Yellow
} else {
    Write-Host "Config exists, leaving untouched: $configPath"
}

# 4. Locate the entrypoint (uv-managed venv in the repo)
$entry = Join-Path $RepoRoot '.venv\Scripts\deepdub-qc.exe'
if (-not (Test-Path $entry)) { throw "Entrypoint not found: $entry — run 'uv sync' in the repo first." }

# 5. NSSM service registration (section 3)
& $NssmPath stop $ServiceName 2>$null | Out-Null
& $NssmPath remove $ServiceName confirm 2>$null | Out-Null
& $NssmPath install $ServiceName $entry "serve --config `"$configPath`""
& $NssmPath set $ServiceName DisplayName 'Deepdub QC Server'
& $NssmPath set $ServiceName Description 'Deepdub automated media QC service (Phase 3.5)'
& $NssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START
& $NssmPath set $ServiceName AppDirectory $RepoRoot
& $NssmPath set $ServiceName AppStdout (Join-Path $Root 'logs\service\service-out.log')
& $NssmPath set $ServiceName AppStderr (Join-Path $Root 'logs\service\service-err.log')
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760
& $NssmPath set $ServiceName AppStopMethodSkip 0
& $NssmPath set $ServiceName AppStopMethodConsole 30000   # CtrlC grace: worker marks the running job
& $NssmPath set $ServiceName AppThrottle 5000             # crash-loop protection
if ($ServiceAccount) {
    Write-Host "Set the service account manually: services.msc -> $ServiceName -> Log On -> $ServiceAccount" -ForegroundColor Yellow
}

# 6. Browser shortcut (section 7)
$shortcut = @"
[InternetShortcut]
URL=http://127.0.0.1:$Port/
"@
Set-Content (Join-Path $Root 'shortcuts\Deepdub QC.url') $shortcut
Copy-Item (Join-Path $Root 'shortcuts\Deepdub QC.url') "$env:PUBLIC\Desktop\Deepdub QC.url" -Force

Write-Host ''
Write-Host "Installed. Next steps:" -ForegroundColor Green
Write-Host "  1. Edit $configPath (media_roots!)"
Write-Host "  2. Start-Service $ServiceName"
Write-Host "  3. Open http://127.0.0.1:$Port (desktop shortcut: 'Deepdub QC')"
