# Deepdub QC - fresh install / re-install (docs/windows-deployment.md section 8.1).
# Run as Administrator from the repo checkout:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 `
#     -NssmPath C:\tools\nssm.exe -FfmpegDir C:\Downloads\ffmpeg-7.1\bin `
#     -MediaRoots 'D:\qc-media'
#
# Creates the C:\DeepdubQC tree, pins ffmpeg (sha256-recorded), writes the
# initial config, builds the runtime venv, registers the NSSM service under a
# least-privilege identity, grants that identity exactly the ACLs it needs,
# starts the service, and smoke-tests it. Idempotent: re-running refreshes
# the service definition and never overwrites an existing config or database.

param(
    [string]$Root = 'C:\DeepdubQC',
    [Parameter(Mandatory = $true)][string]$NssmPath,
    [Parameter(Mandatory = $true)][string]$FfmpegDir,   # dir containing ffmpeg.exe/ffprobe.exe
    [string]$ServiceName = 'DeepdubQC',
    [int]$Port = 8571,
    # Default: the per-service virtual account NT SERVICE\<name> - no password,
    # least privilege, cannot read other users' profiles. Pass a real account
    # (DOMAIN\user or .\user) only when the service must reach UNC shares.
    [string]$ServiceAccount = '',
    [string[]]$MediaRoots = @(),
    [switch]$SkipPlaywright,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Administrator
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
foreach ($dir in @('config', 'data\jobs', 'data\backups', 'logs\service', 'logs\app',
                   'bin\ffmpeg', 'browsers', 'shortcuts')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}
Initialize-DeployLog -Root $Root -Action 'install'
Write-Log "Repo: $RepoRoot"

# 0. On a re-install, stop the service FIRST: Windows locks a running exe,
#    so copying ffmpeg over the previous pin fails while the service is up.
Stop-QcService -ServiceName $ServiceName

# 1. Pinned ffmpeg + attribution record (section 4). The first line of
#    VERSION.txt is the exact string the smoke test later demands from the
#    running service's /api/v1/health.
foreach ($exe in @('ffmpeg.exe', 'ffprobe.exe')) {
    $source = Join-Path $FfmpegDir $exe
    if (-not (Test-Path $source)) { throw "Not found: $source" }
    Copy-Item $source (Join-Path $Root "bin\ffmpeg\$exe") -Force
}
$versionLine = [string](& (Join-Path $Root 'bin\ffmpeg\ffmpeg.exe') -version 2>&1 | Select-Object -First 1)
$ffmpegHash = (Get-FileHash (Join-Path $Root 'bin\ffmpeg\ffmpeg.exe') -Algorithm SHA256).Hash
"$versionLine`nsha256=$ffmpegHash`nsource_dir=$FfmpegDir`ninstalled=$(Get-Date -Format o)" |
    Set-Content (Join-Path $Root 'bin\ffmpeg\VERSION.txt')
Write-Log "Pinned ffmpeg: $versionLine (sha256=$ffmpegHash)"
$nssmHash = (Get-FileHash $NssmPath -Algorithm SHA256).Hash
Write-Log "NSSM: $NssmPath (sha256=$nssmHash)"

# 2. Initial config (never overwrite an existing one - it is operator state).
$configPath = Join-Path $Root 'config\server.yaml'
$configExisted = Test-Path $configPath
if (-not $configExisted) {
    $config = Get-Content (Join-Path $RepoRoot 'config\server.example.yaml') -Raw
    $config = $config -replace "ffmpeg_path: '[^']*'", "ffmpeg_path: '$Root\bin\ffmpeg\ffmpeg.exe'"
    $config = $config -replace "ffprobe_path: '[^']*'", "ffprobe_path: '$Root\bin\ffmpeg\ffprobe.exe'"
    $config = $config -replace "presets_root: '[^']*'", "presets_root: '$RepoRoot\presets'"
    $config = $config -replace 'port: \d+', "port: $Port"
    # Arm the determinism guard (ADR-008) with the build just pinned: the
    # service refuses to start if the binary on disk stops matching.
    $versionToken = ($versionLine -split '\s+')[2]
    $config = $config -replace "# expected_ffmpeg_version: '[^']*'", "expected_ffmpeg_version: '$versionToken'"
    if ($MediaRoots.Count -gt 0) {
        $block = "media_roots:`n" + (($MediaRoots | ForEach-Object { "    - '$_'" }) -join "`n")
        $config = $config -replace "media_roots:\s*\r?\n(\s*- '[^']*'\s*\r?\n)+", "$block`n"
    }
    Set-Content $configPath $config
    Write-Log "Wrote initial config: $configPath"
    if ($MediaRoots.Count -eq 0) {
        Write-Log 'media_roots still holds example paths - EDIT the config before first start.' 'Yellow'
    }
} else {
    Write-Log "Config exists, leaving untouched: $configPath"
}

# 3. Runtime venv from the committed lock (section 8.1 step 4).
$entry = Invoke-RuntimeSync -RepoRoot $RepoRoot

# 4. Chromium for PDF rendering - into a shared, service-readable location.
#    Playwright installs browsers under the CURRENT USER's profile by default,
#    which the service account cannot read; PLAYWRIGHT_BROWSERS_PATH makes the
#    location explicit for both this install step and the service (step 5).
#    Best-effort: without Chromium, PDF degrades with a note and HTML/JSON
#    (the canonical outputs) still render.
$browsersDir = Join-Path $Root 'browsers'
if (-not $SkipPlaywright) {
    $env:PLAYWRIGHT_BROWSERS_PATH = $browsersDir
    $playwright = Join-Path $RepoRoot '.venv\Scripts\playwright.exe'
    if (Test-Path $playwright) {
        & $playwright install chromium
        if ($LASTEXITCODE -ne 0) { Write-Log 'Playwright install failed - PDF rendering will degrade (HTML/JSON unaffected).' 'Yellow' }
    } else {
        Write-Log 'playwright.exe not in venv - PDF rendering will degrade (HTML/JSON unaffected).' 'Yellow'
    }
}

# 5. NSSM service registration (section 3).
$serviceIdentity = if ($ServiceAccount) { $ServiceAccount } else { "NT SERVICE\$ServiceName" }
# stop/remove are EXPECTED to fail on first install; PS 5.1 can escalate
# native stderr to a terminating error under ErrorActionPreference=Stop.
$eap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $NssmPath stop $ServiceName 2>$null | Out-Null
& $NssmPath remove $ServiceName confirm 2>$null | Out-Null
$ErrorActionPreference = $eap
& $NssmPath install $ServiceName $entry "serve --config `"$configPath`""
if ($LASTEXITCODE -ne 0) { throw "nssm install failed (exit $LASTEXITCODE)" }
& $NssmPath set $ServiceName DisplayName 'Deepdub QC Server'
& $NssmPath set $ServiceName Description 'Deepdub automated media QC service (Phase 3.5)'
& $NssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START
& $NssmPath set $ServiceName AppDirectory $RepoRoot
& $NssmPath set $ServiceName AppEnvironmentExtra "PLAYWRIGHT_BROWSERS_PATH=$browsersDir"
& $NssmPath set $ServiceName AppStdout (Join-Path $Root 'logs\service\service-out.log')
& $NssmPath set $ServiceName AppStderr (Join-Path $Root 'logs\service\service-err.log')
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760
& $NssmPath set $ServiceName AppStopMethodSkip 0
& $NssmPath set $ServiceName AppStopMethodConsole 30000   # CtrlC grace: worker marks the running job
& $NssmPath set $ServiceName AppThrottle 5000             # crash-loop protection
if ($ServiceAccount) {
    # Real account: NSSM prompts for (and verifies) the password, and grants
    # the log-on-as-a-service right. Never pass passwords on a command line.
    Write-Log "Setting service account $ServiceAccount (password prompt follows)..."
    $credential = Get-Credential -UserName $ServiceAccount -Message "Password for $ServiceAccount"
    $plain = $credential.GetNetworkCredential().Password
    & $NssmPath set $ServiceName ObjectName $ServiceAccount $plain
    if ($LASTEXITCODE -ne 0) { throw "Failed to set service account $ServiceAccount" }
} else {
    # Per-service virtual account: no password, no profile, least privilege.
    # NOT LocalSystem (the NSSM default) - untrusted media goes through
    # FFmpeg under this identity; blast radius must stay small (section 3).
    # sc.exe rather than nssm: it sets passwordless identities reliably.
    & sc.exe config $ServiceName obj= $serviceIdentity
    if ($LASTEXITCODE -ne 0) { throw "Failed to set service account $serviceIdentity" }
}
Write-Log "Service $ServiceName registered as $serviceIdentity"

# 6. ACLs - exactly what the identity needs, nothing more (section 3):
#    modify on data\ and logs\, read on the rest of the tree and the repo
#    (the venv, presets, and templates live in the checkout).
foreach ($grant in @(
    @{ Path = (Join-Path $Root 'data');     Rights = 'M' },
    @{ Path = (Join-Path $Root 'logs');     Rights = 'M' },
    @{ Path = (Join-Path $Root 'bin');      Rights = 'RX' },
    @{ Path = (Join-Path $Root 'config');   Rights = 'RX' },
    @{ Path = (Join-Path $Root 'browsers'); Rights = 'RX' },
    @{ Path = $RepoRoot;                    Rights = 'RX' }
)) {
    & icacls $grant.Path /grant "${serviceIdentity}:(OI)(CI)$($grant.Rights)" /T /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $($grant.Path)" }
}
Write-Log 'ACLs granted (data/logs: modify; bin/config/browsers/repo: read).'
if ($MediaRoots.Count -gt 0) {
    foreach ($mediaRoot in $MediaRoots) {
        if (Test-Path $mediaRoot) {
            & icacls $mediaRoot /grant "${serviceIdentity}:(OI)(CI)RX" /Q | Out-Null
        } else {
            Write-Log "media root does not exist yet, no ACL granted: $mediaRoot" 'Yellow'
        }
    }
}

# 7. Browser shortcut (section 7) - launches nothing, never starts the server.
$shortcut = "[InternetShortcut]`nURL=http://127.0.0.1:$Port/"
Set-Content (Join-Path $Root 'shortcuts\Deepdub QC.url') $shortcut
Copy-Item (Join-Path $Root 'shortcuts\Deepdub QC.url') "$env:PUBLIC\Desktop\Deepdub QC.url" -Force

# 8. Deployment state (read by upgrade.ps1/rollback.ps1/uninstall.ps1).
$commit = Get-RepoCommit -RepoRoot $RepoRoot
Write-DeployState -Root $Root -State @{
    repoRoot        = $RepoRoot
    serviceName     = $ServiceName
    port            = $Port
    nssmPath        = (Resolve-Path $NssmPath).Path
    serviceIdentity = $serviceIdentity
    currentCommit   = $commit
    previousCommit  = $null
    installedAt     = (Get-Date -Format o)
}
Write-Log "Deployment state written (commit $commit)."

# 9. Start + smoke test - only when the config is real. A fresh config with
#    example media_roots makes the server refuse to start (by design), so
#    starting it would just record a crash loop.
if ($NoStart -or (-not $configExisted -and $MediaRoots.Count -eq 0)) {
    Write-Log ''
    Write-Log 'Service registered but NOT started. Next steps:' 'Yellow'
    Write-Log "  1. Edit $configPath (media_roots!)"
    Write-Log "  2. Start-Service $ServiceName"
    Write-Log "  3. powershell -File scripts\windows\status.ps1"
} else {
    Start-QcService -ServiceName $ServiceName
    Invoke-SmokeTest -Root $Root -Port $Port | Out-Null
    Write-Log ''
    Write-Log "Installed and healthy. Console: http://127.0.0.1:$Port (desktop shortcut: 'Deepdub QC')" 'Green'
}
