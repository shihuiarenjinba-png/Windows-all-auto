param(
    [Parameter(Mandatory=$true)][string]$ProductRepoPath,
    [Parameter(Mandatory=$true)][string]$PackagePath,
    [Parameter(Mandatory=$true)][string]$HandoffPath,
    [Parameter(Mandatory=$true)][string]$MainExeName,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$RunSelfTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) { throw "Windows only" }
$repo = (Resolve-Path -LiteralPath $ProductRepoPath).Path
$package = (Resolve-Path -LiteralPath $PackagePath).Path
$handoffFile = (Resolve-Path -LiteralPath $HandoffPath).Path
if (-not (Test-Path -LiteralPath $repo -PathType Container)) { throw "Product repository missing" }
if (-not (Test-Path -LiteralPath $package -PathType Leaf)) { throw "MSIX missing" }
if (-not (Test-Path -LiteralPath $handoffFile -PathType Leaf)) { throw "Handoff missing" }

$handoff = Get-Content -LiteralPath $handoffFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($handoff.schema_version -cne "store-product-handoff/2") { throw "Unsupported handoff schema" }

$head = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -cne [string]$handoff.product.source_sha) {
    throw "Local product repository HEAD does not match handoff source SHA"
}

$actualPackageSha = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPackageSha -cne [string]$handoff.package.package_sha256) {
    throw "MSIX SHA256 does not match handoff"
}
if ((Split-Path -Leaf $package) -cne [string]$handoff.package.file_name) {
    throw "MSIX filename does not match handoff"
}

$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw "OutputDirectory already exists; refusing to overwrite QA evidence" }
New-Item -ItemType Directory -Path $out | Out-Null
$unpack = Join-Path $out "msix-unpacked"
New-Item -ItemType Directory -Path $unpack | Out-Null

$kit = Join-Path ([Environment]::GetEnvironmentVariable("ProgramFiles(x86)")) "Windows Kits\10\bin"
$makeappx = Get-ChildItem -LiteralPath $kit -Recurse -Filter MakeAppx.exe -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Directory.Name -ceq "x64" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if ($null -eq $makeappx) { throw "x64 MakeAppx.exe not installed" }

& $makeappx.FullName unpack /p $package /d $unpack
if ($LASTEXITCODE -ne 0) { throw "MakeAppx unpack FAILED: $LASTEXITCODE" }

$manifestPath = Join-Path $unpack "AppxManifest.xml"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "AppxManifest.xml missing" }
[xml]$xml = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
$ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
$ns.AddNamespace("f","http://schemas.microsoft.com/appx/manifest/foundation/windows10")
$identity = $xml.SelectSingleNode("/f:Package/f:Identity",$ns)
if ($null -eq $identity) { throw "Manifest Identity missing" }
if ($identity.Name -cne [string]$handoff.identity.name) { throw "Manifest Identity Name mismatch" }
if ($identity.Publisher -cne [string]$handoff.identity.publisher) { throw "Manifest Publisher mismatch" }
if ($identity.Version -cne [string]$handoff.identity.version) { throw "Manifest Version mismatch" }
if ($identity.ProcessorArchitecture -cne [string]$handoff.identity.architecture) { throw "Manifest architecture mismatch" }

$mainExe = Join-Path $unpack $MainExeName
if (-not (Test-Path -LiteralPath $mainExe -PathType Leaf)) { throw "Main EXE missing after unpack: $MainExeName" }
$actualExeSha = (Get-FileHash -LiteralPath $mainExe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualExeSha -cne [string]$handoff.package.exe_sha256) { throw "Unpacked main EXE SHA256 mismatch" }

$selfTestPass = $null
if ($RunSelfTest) {
    $process = Start-Process -FilePath $mainExe -ArgumentList "--self-test" -PassThru -Wait
    $selfTestPass = ($process.ExitCode -eq 0)
    if (-not $selfTestPass) { throw "Packaged EXE self-test failed with exit code $($process.ExitCode)" }
}

$report = [ordered]@{
    schema_version = "local-static-package-preflight/1"
    status = "PASS"
    store_id = [string]$handoff.identity.store_id
    source_sha = [string]$handoff.product.source_sha
    package_sha256 = $actualPackageSha
    unpacked_exe_sha256 = $actualExeSha
    manifest_identity_verified = $true
    package_rebuilt = $false
    security_bypass_used = $false
    self_test_pass = $selfTestPass
    unpacked_path = $unpack
}
$reportPath = Join-Path $out "local-static-preflight.json"
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host ("LOCAL_STATIC_PREFLIGHT_PASS report=" + $reportPath)
