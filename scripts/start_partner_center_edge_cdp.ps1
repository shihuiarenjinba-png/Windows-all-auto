[CmdletBinding()]
param(
    [string]$CdpUrl = 'http://127.0.0.1:9223',
    [string]$ProfileDirectory = (Join-Path $env:LOCALAPPDATA 'PartnerCenterUploaderEdge')
)

$ErrorActionPreference = 'Stop'
$uri = [Uri]$CdpUrl
if (-not $uri.IsLoopback -or $uri.Scheme -ne 'http') {
    throw 'CDP must use an HTTP loopback address such as http://127.0.0.1:9223.'
}
$endpoint = $CdpUrl.TrimEnd('/') + '/json/version'
try {
    $version = Invoke-RestMethod -Uri $endpoint -TimeoutSec 2
    if ([string]$version.Browser -notmatch 'Edg/') { throw "Port 9223 is responding, but it is not Microsoft Edge: $($version.Browser)" }
    Write-Host "Local Edge CDP is already available: $($version.Browser)"
    Write-Host 'Use the single Partner Center tab in that session. No new browser was launched.'
    return
} catch {
    # Start a dedicated local profile below; no existing Edge process is terminated.
}

$edgeCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
)
$edge = $edgeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $edge) {
    $command = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($command) { $edge = $command.Source }
}
if (-not $edge) { throw 'Microsoft Edge executable was not found.' }

New-Item -ItemType Directory -Force -Path $ProfileDirectory | Out-Null
$arguments = @(
    '--remote-debugging-port=9223',
    ('--user-data-dir="' + $ProfileDirectory + '"'),
    '--no-first-run',
    '--no-default-browser-check',
    'https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview'
)
$process = Start-Process -FilePath $edge -ArgumentList $arguments -PassThru

$available = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $version = Invoke-RestMethod -Uri $endpoint -TimeoutSec 2
        $available = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $available) {
    throw 'Edge started, but the local CDP endpoint did not become available. Do not retry an upload.'
}

Write-Host 'A dedicated Edge profile has been opened for local Partner Center automation.' -ForegroundColor Green
Write-Host 'Sign in to Partner Center manually in this Edge window and complete MFA there.'
Write-Host 'No credentials are collected or stored by this script.'
Write-Host "CDP endpoint: $CdpUrl"
Write-Host "Profile directory: $ProfileDirectory"
Write-Host "Edge process ID: $($process.Id)"
