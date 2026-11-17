param(
    [Parameter(Mandatory=$true)][string]$ProductRepoPath,
    [Parameter(Mandatory=$true)][string]$PackagePath,
    [Parameter(Mandatory=$true)][string]$HandoffPath,
    [Parameter(Mandatory=$true)][string]$MainExeName,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$AssetsDir = "",
    [ValidateSet("ExactHead","ContainedCommit")][string]$SourceCheckoutMode = "ExactHead"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) { throw "Windows only" }

$root = Split-Path -Parent $PSScriptRoot
$preflightOut = Join-Path $OutputDirectory "exact-package-preflight"
$readinessOut = Join-Path $OutputDirectory "store-preupload-readiness.json"

pwsh -File (Join-Path $PSScriptRoot "run_local_exact_package_preflight.ps1") `
    -ProductRepoPath $ProductRepoPath `
    -PackagePath $PackagePath `
    -HandoffPath $HandoffPath `
    -MainExeName $MainExeName `
    -OutputDirectory $preflightOut `
    -SourceCheckoutMode $SourceCheckoutMode

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$argsList = @(
    (Join-Path $PSScriptRoot "check_local_store_upload_candidate.py"),
    "--handoff", $HandoffPath,
    "--package-path", $PackagePath,
    "--output", $readinessOut
)
if ($AssetsDir) {
    $argsList += @("--assets-dir", $AssetsDir)
}

python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$receipt = Get-Content -LiteralPath $readinessOut -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.status -cne "READY_FOR_MSIX_UPLOAD_APPROVAL") {
    throw "Pre-upload readiness did not reach READY_FOR_MSIX_UPLOAD_APPROVAL"
}
if ($receipt.package_upload_executed -or $receipt.certification_executed -or $receipt.published) {
    throw "Pre-upload readiness performed an external Store write"
}

Write-Host ("STORE_PREUPLOAD_READY receipt=" + $readinessOut)
