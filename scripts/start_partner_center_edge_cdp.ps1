[CmdletBinding()]
param(
    [string]$CdpUrl = 'http://127.0.0.1:9223',
    [string]$ProfileDirectory = (Join-Path $env:LOCALAPPDATA 'PartnerCenterUploaderEdge')
)

$ErrorActionPreference = 'Stop'
$uri = [Uri]$CdpUrl
if (-not $uri.IsLoopback -or $uri.Scheme -ne 'http' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -notin @('', '/')) {
    throw 'CDP must be an HTTP loopback origin such as http://127.0.0.1:9223, without credentials or extra path.'
}

$targetUrl = 'https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview'
$targetUri = [Uri]$targetUrl
if ($targetUri.Scheme -ne 'https' -or $targetUri.Host -ne 'partner.microsoft.com' -or
    $targetUri.AbsolutePath -ne '/en-us/dashboard/apps-and-games/overview') {
    throw 'The configured start URL must be the Microsoft Partner Center Apps and games Overview.'
}

$baseUrl = $CdpUrl.TrimEnd('/')
$versionEndpoint = $baseUrl + '/json/version'
$listEndpoint = $baseUrl + '/json/list'

function Get-EdgeCdpVersion {
    try {
        $value = Invoke-RestMethod -Uri $versionEndpoint -TimeoutSec 3
        if ([string]$value.Browser -notmatch '^Edg/') {
            throw "The CDP endpoint is not Microsoft Edge: $($value.Browser)"
        }
        return $value
    } catch {
        if ($_.Exception.Message -like 'The CDP endpoint is not Microsoft Edge:*') { throw }
        return $null
    }
}

function Get-ExactOverviewTargets {
    try {
        $targets = @(Invoke-RestMethod -Uri $listEndpoint -TimeoutSec 3)
    } catch {
        throw 'Edge CDP is responding, but its target list could not be read. Do not run the uploader.'
    }
    return @($targets | Where-Object {
        $_.type -eq 'page' -and
        ([string]$_.url -split '[?#]', 2)[0] -ceq $targetUrl
    })
}

function Open-AppsAndGamesOverviewTab {
    $newTargetEndpoint = $baseUrl + '/json/new?' + [Uri]::EscapeDataString($targetUrl)
    try {
        Invoke-RestMethod -Method Put -Uri $newTargetEndpoint -TimeoutSec 5 | Out-Null
    } catch {
        throw 'Edge CDP is available, but it could not open Apps and games Overview. Open the official Overview URL manually in this same Edge window, then run Browser Doctor.'
    }
}

$existingVersion = Get-EdgeCdpVersion
if ($existingVersion) {
    Write-Host "Local Edge CDP is available: $($existingVersion.Browser)"
    $exactTargets = @(Get-ExactOverviewTargets)
    if ($exactTargets.Count -gt 1) {
        Write-Warning "Found $($exactTargets.Count) Apps and games Overview tabs. No tab was opened or closed; Browser Doctor will fail closed until duplicates are resolved."
    } elseif ($exactTargets.Count -eq 1) {
        Write-Host 'The Apps and games Overview tab is already open.'
    } else {
        Open-AppsAndGamesOverviewTab
        $opened = $false
        for ($i = 0; $i -lt 10; $i++) {
            $exactTargets = @(Get-ExactOverviewTargets)
            if ($exactTargets.Count -eq 1) {
                $opened = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not $opened) {
            throw 'Apps and games Overview did not appear after the CDP open request. Do not run the uploader.'
        }
        Write-Host 'Opened one new tab at Apps and games Overview. Existing tabs were left untouched.'
    }
    Write-Host 'Next: sign in manually if needed, then run the read-only Browser Doctor.'
    Write-Host 'No file was selected, no Save was clicked, and no Partner Center data was changed.'
    return
}

$programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
$edgeCandidates = @(
    (Join-Path $programFilesX86 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
)
$edge = $edgeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $edge) {
    $command = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($command) { $edge = $command.Source }
}
if (-not $edge) { throw 'Microsoft Edge executable was not found.' }
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) { throw 'ProfileDirectory cannot be empty.' }

New-Item -ItemType Directory -Force -Path $ProfileDirectory | Out-Null
$profilePath = (Resolve-Path -LiteralPath $ProfileDirectory).Path
$arguments = @(
    '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=9223',
    ('--user-data-dir="' + $profilePath + '"'),
    '--no-first-run',
    '--no-default-browser-check',
    $targetUrl
)
$process = Start-Process -FilePath $edge -ArgumentList $arguments -PassThru

$available = $false
for ($i = 0; $i -lt 20; $i++) {
    if ($process.HasExited) {
        throw "The dedicated Edge process exited before CDP became ready (exit code $($process.ExitCode))."
    }
    $version = Get-EdgeCdpVersion
    if ($version) {
        $available = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $available) {
    throw 'Edge started, but the local CDP endpoint did not become available. Do not retry an upload.'
}

$exactTargets = @(Get-ExactOverviewTargets)
if ($exactTargets.Count -ne 1) {
    throw "Expected one Apps and games Overview tab after Edge startup; found $($exactTargets.Count). Do not run the uploader."
}

Write-Host 'A dedicated Edge profile has been opened on loopback CDP for Data Contract Auditor.' -ForegroundColor Green
Write-Host 'The initial tab is Apps and games Overview; automation must select the exact Product and existing Draft from there.'
Write-Host 'Sign in to Partner Center manually in this Edge window and complete MFA there.'
Write-Host 'No credentials are collected or stored by this script.'
Write-Host "CDP endpoint: $CdpUrl"
Write-Host "Profile directory: $profilePath"
Write-Host "Edge process ID: $($process.Id)"
Write-Host 'Next: run the read-only Browser Doctor. Do not run -Execute unless Doctor returns READY_EXACT_DRAFT_TAB.'
