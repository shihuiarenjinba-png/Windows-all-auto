[CmdletBinding()]
param(
    [string]$PackageRoot = 'C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\attempt-20261125',
    [string]$CdpUrl = 'http://127.0.0.1:9223',
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot

$expectedName = 'DataContractSchemaDrift_1.0.0.0_x64.msix'
if (-not (Test-Path -LiteralPath $PackageRoot -PathType Container)) {
    throw "Package root does not exist: $PackageRoot"
}
$matches = @(Get-ChildItem -LiteralPath $PackageRoot -Filter $expectedName -File -Recurse)
if ($matches.Count -ne 1) {
    $paths = $matches | ForEach-Object { $_.FullName }
    throw "Expected exactly one $expectedName under $PackageRoot; found $($matches.Count). Do not guess between attempts. Matches: $($paths -join '; ')"
}

$uploadScript = Join-Path $PSScriptRoot 'upload_store_msix.ps1'
$arguments = @(
    '-Product', 'data-contract-auditor',
    '-Package', $matches[0].FullName,
    '-CdpUrl', $CdpUrl
)
if ($Execute) {
    $arguments += '-Execute'
    Write-Host 'Executing the owner-authorized single DCA package upload/Save to the existing Draft only.' -ForegroundColor Yellow
} else {
    Write-Host 'Dry-run only: no Partner Center write will occur.'
}

& $uploadScript @arguments
if ($LASTEXITCODE -ne 0) {
    throw "DCA Store package operation failed. Inspect .uploader-run\data-contract-auditor\receipt.json before retrying."
}
