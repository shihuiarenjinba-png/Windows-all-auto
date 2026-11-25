[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,63}$')]
    [string]$Product,

    [Parameter(Mandatory = $true)]
    [string]$Package,

    [string]$CdpUrl = 'http://127.0.0.1:9223',
    [string]$Workdir = '.uploader-run',
    [string]$ReceiptLedger,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot

$packageItem = Get-Item -LiteralPath $Package -ErrorAction Stop
if ($packageItem.PSIsContainer -or $packageItem.Extension -ine '.msix') {
    throw 'Package must be an existing .msix file.'
}

$python = Get-Command python -ErrorAction Stop
$arguments = @(
    '-m', 'uploader.run',
    '--product', $Product,
    '--package', $packageItem.FullName,
    '--workdir', $Workdir
)
if ($ReceiptLedger) {
    $arguments += @('--receipt-ledger', $ReceiptLedger)
}

if ($Execute) {
    $configPath = Join-Path $repoRoot ("uploader/config/" + $Product + ".job.json")
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Missing registered product job configuration: $configPath"
    }
    $jobConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    if ($jobConfig.upload_approved -ne $true) {
        throw "Live package write is disabled for '$Product'. Resolve the product-specific hold reasons and explicitly approve this exact job first."
    }
    if ($jobConfig.expected_sha256 -notmatch '^[0-9a-fA-F]{64}
    if (-not $uri.IsLoopback -or $uri.Scheme -ne 'http') {
        throw 'For this no-extra-service route, CDP must be an HTTP loopback address (127.0.0.1 / localhost).'
    }
    $versionEndpoint = $CdpUrl.TrimEnd('/') + '/json/version'
    try {
        $null = Invoke-RestMethod -Uri $versionEndpoint -TimeoutSec 3
    } catch {
        throw "Local Edge CDP is unavailable at $versionEndpoint. Start the already-authenticated Partner Center Edge session with remote debugging enabled; do not enter credentials in this script."
    }
    $env:PARTNER_CENTER_CDP_URL = $CdpUrl
    $arguments += '--execute'
    Write-Host "LIVE MODE: exact MSIX will be uploaded to the configured existing Draft for '$Product', then Packages Save/reload will be checked." -ForegroundColor Yellow
} else {
    Write-Host 'DRY RUN: package hash and manifest are checked; Partner Center is not contacted.'
}

& $python.Source @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "Store package operation failed with exit code $exitCode. Inspect $Workdir/receipt.json before retrying."
}
) {
        throw "Live package write requires an exact 64-character expected_sha256 in the product job config."
    }
    if ([IO.Path]::GetFileName([string]$jobConfig.path) -cne $packageItem.Name) {
        throw "Local MSIX filename does not match the registered exact package filename."
    }
    $uri = [Uri]$CdpUrl
    if (-not $uri.IsLoopback -or $uri.Scheme -ne 'http') {
        throw 'For this no-extra-service route, CDP must be an HTTP loopback address (127.0.0.1 / localhost).'
    }
    $versionEndpoint = $CdpUrl.TrimEnd('/') + '/json/version'
    try {
        $null = Invoke-RestMethod -Uri $versionEndpoint -TimeoutSec 3
    } catch {
        throw "Local Edge CDP is unavailable at $versionEndpoint. Start the already-authenticated Partner Center Edge session with remote debugging enabled; do not enter credentials in this script."
    }
    $env:PARTNER_CENTER_CDP_URL = $CdpUrl
    $arguments += '--execute'
    Write-Host "LIVE MODE: exact MSIX will be uploaded to the configured existing Draft for '$Product', then Packages Save/reload will be checked." -ForegroundColor Yellow
} else {
    Write-Host 'DRY RUN: package hash and manifest are checked; Partner Center is not contacted.'
}

& $python.Source @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "Store package operation failed with exit code $exitCode. Inspect $Workdir/receipt.json before retrying."
}
