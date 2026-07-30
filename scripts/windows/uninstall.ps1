# Deepdub QC — uninstall the service (docs/windows-deployment.md section 8.3).
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall.ps1
#
# Deregisters the service and removes binaries and shortcuts. data\ (job
# history — client-relevant QC evidence) and logs\ stay in place unless
# -PurgeData is passed: deletion is a separate, deliberate act. The repo
# checkout is never touched.

param(
    [string]$Root = 'C:\DeepdubQC',
    [switch]$PurgeData
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Administrator
$state = Read-DeployState -Root $Root
Initialize-DeployLog -Root $Root -Action 'uninstall'

Stop-QcService -ServiceName $state.serviceName
& $state.nssmPath remove $state.serviceName confirm
Write-Log "Service $($state.serviceName) deregistered."

Remove-Item "$env:PUBLIC\Desktop\Deepdub QC.url" -ErrorAction SilentlyContinue
foreach ($dir in @('bin', 'browsers', 'shortcuts')) {
    Remove-Item (Join-Path $Root $dir) -Recurse -Force -ErrorAction SilentlyContinue
}

if ($PurgeData) {
    Write-Log 'PURGING data\, logs\ and config\ — job history is gone after this.' 'Red'
    Remove-Item $Root -Recurse -Force
} else {
    Write-Log "Kept: $Root\data (QC evidence), logs\, config\. Remove manually or re-run with -PurgeData." 'Yellow'
}
Write-Log 'Uninstalled.' 'Green'
