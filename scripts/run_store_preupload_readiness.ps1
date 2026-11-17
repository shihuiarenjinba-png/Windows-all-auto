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
if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$preflightOut = Join-Path $OutputDirectory "exact-package-preflight"
$readinessOut = Join-Path $OutputDirectory "store-preupload-readiness.json"

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
$candidateExit = $LASTEXITCODE
$receipt = Get-Content -LiteralPath $readinessOut -Raw -Encoding UTF8 | ConvertFrom-Json
if ($candidateExit -ne 0) {
    Write-Host ("STORE_PREUPLOAD_HOLD status=" + $receipt.status + " receipt=" + $readinessOut)
    exit $candidateExit
}
if ($receipt.status -cne "READY_FOR_MSIX_UPLOAD_APPROVAL") {
    throw "Pre-upload readiness did not reach READY_FOR_MSIX_UPLOAD_APPROVAL"
}

try {
    pwsh -File (Join-Path $PSScriptRoot "run_local_exact_package_preflight.ps1") `
        -ProductRepoPath $ProductRepoPath `
        -PackagePath $PackagePath `
        -HandoffPath $HandoffPath `
        -MainExeName $MainExeName `
        -OutputDirectory $preflightOut `
        -SourceCheckoutMode $SourceCheckoutMode
    if ($LASTEXITCODE -ne 0) { throw "exact package preflight returned $LASTEXITCODE" }
} catch {
    $failed = [ordered]@{
        schema_version = "store-preupload-readiness/1"
        status = "HOLD_EXACT_PACKAGE_MISMATCH"
        reason = ("exact package/manifest preflight failed: " + $_.Exception.Message)
        package_path = $PackagePath
        package_upload_executed = $false
        certification_executed = $false
        published = $false
    }
    $failed | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $readinessOut -Encoding UTF8
    Write-Host ("STORE_PREUPLOAD_HOLD status=HOLD_EXACT_PACKAGE_MISMATCH receipt=" + $readinessOut)
    exit 2
}

$receipt = Get-Content -LiteralPath $readinessOut -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.package_upload_executed -or $receipt.certification_executed -or $receipt.published) {
    throw "Pre-upload readiness performed an external Store write"
}

Write-Host ("STORE_PREUPLOAD_READY receipt=" + $readinessOut)
