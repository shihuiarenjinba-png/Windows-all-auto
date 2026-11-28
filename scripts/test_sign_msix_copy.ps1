[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$IdentityName,
    [Parameter(Mandatory = $true)][string]$Publisher,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][ValidateSet('x86','x64','arm64')][string]$Architecture,
    [Parameter(Mandatory = $true)][string]$ApplicationId,
    [Parameter(Mandatory = $true)][string]$SmokeMarkerPath,
    [string]$OutputDirectory = $env:RUNNER_TEMP
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
if ($env:GITHUB_ACTIONS -ne 'true') {
    throw 'Test signing and trust are restricted to an ephemeral GitHub Actions runner.'
}
if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'ExpectedSha256 must be a full SHA-256.' }
$source = (Resolve-Path -LiteralPath $Package).Path
$sourceHashBefore = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
if ($sourceHashBefore -ne $ExpectedSha256.ToUpperInvariant()) { throw 'Frozen source SHA-256 mismatch.' }
if ((Get-AuthenticodeSignature -LiteralPath $source).Status -ne 'NotSigned') {
    throw 'This test lane only accepts the frozen unsigned Store candidate.'
}

$manifest = [System.IO.Compression.ZipFile]::OpenRead($source)
try {
    $entry = $manifest.GetEntry('AppxManifest.xml')
    if (-not $entry) { throw 'AppxManifest.xml missing.' }
    $reader = [System.IO.StreamReader]::new($entry.Open())
    try { [xml]$xml = $reader.ReadToEnd() } finally { $reader.Dispose() }
} finally { $manifest.Dispose() }
$ns = [System.Xml.XmlNamespaceManager]::new($xml.NameTable)
$ns.AddNamespace('f', 'http://schemas.microsoft.com/appx/manifest/foundation/windows10')
$identity = $xml.SelectSingleNode('/f:Package/f:Identity', $ns)
$application = $xml.SelectSingleNode('/f:Package/f:Applications/f:Application', $ns)
if (-not $identity -or -not $application) { throw 'Manifest Identity or Application missing.' }
if ($identity.Name -ne $IdentityName -or $identity.Publisher -ne $Publisher -or
    $identity.Version -ne $Version -or $identity.ProcessorArchitecture -ne $Architecture -or
    $application.Id -ne $ApplicationId) { throw 'Manifest tuple does not match the requested profile.' }

$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$runId = [Guid]::NewGuid().ToString('N')
$derived = Join-Path $OutputDirectory ("test-signed-{0}.msix" -f $runId)
$report = Join-Path $OutputDirectory ("test-signature-derivative-{0}.json" -f $runId)
$receipt = Join-Path $OutputDirectory ("test-signature-qa-receipt-{0}.json" -f $runId)
$cert = $null
$installed = $null
$trustedCert = $null
$originalMarkerPresent = Test-Path -LiteralPath $SmokeMarkerPath
if ($originalMarkerPresent) { throw 'SmokeMarkerPath already exists; refusing to accept stale launch evidence.' }
try {
    Copy-Item -LiteralPath $source -Destination $derived
    $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher `
        -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 2048 `
        -KeyUsage DigitalSignature -NotAfter (Get-Date).AddDays(2) `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
    $signTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signTool) {
        $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $signTool = Get-ChildItem -LiteralPath $sdkRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $signTool) { throw 'Windows SDK SignTool was not found.' }
    & $signTool sign /fd SHA256 /sha1 $cert.Thumbprint $derived
    if ($LASTEXITCODE -ne 0) { throw 'SignTool signing failed.' }
    $publicCert = Join-Path $OutputDirectory ("test-cert-{0}.cer" -f $runId)
    Export-Certificate -Cert $cert -FilePath $publicCert | Out-Null
    $trustedCert = Import-Certificate -FilePath $publicCert -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople'
    & $signTool verify /pa /v $derived
    if ($LASTEXITCODE -ne 0) { throw 'SignTool signature verification failed after ephemeral trust was installed.' }
    python -m all_auto.msix_derivative --source $source --derived $derived `
        --expected-source-sha256 $ExpectedSha256 --identity-name $IdentityName `
        --publisher $Publisher --version $Version --architecture $Architecture --report $report
    if ($LASTEXITCODE -ne 0) { throw 'Signature-only derivative verification failed.' }

    Add-AppxPackage -Path $derived -ErrorAction Stop
    $installed = Get-AppxPackage -Name $IdentityName | Where-Object { $_.Publisher -eq $Publisher } |
        Sort-Object Version -Descending | Select-Object -First 1
    if (-not $installed) { throw 'Installed package was not discoverable by exact Identity and Publisher.' }
    $appxFamily = $installed.PackageFamilyName
    $activationSource = @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IApplicationActivationManager {
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
}
[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
class ApplicationActivationManager { }
public static class PackageActivation {
    public static uint Activate(string appUserModelId) {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint processId;
        int hr = manager.ActivateApplication(appUserModelId, null, 0, out processId);
        Marshal.ThrowExceptionForHR(hr);
        return processId;
    }
}
'@
    Add-Type -TypeDefinition $activationSource
    $appUserModelId = "$appxFamily!$ApplicationId"
    $activatedProcessId = [PackageActivation]::Activate($appUserModelId)
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath $SmokeMarkerPath)) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $SmokeMarkerPath)) {
        $processStillRunning = [bool](Get-Process -Id $activatedProcessId -ErrorAction SilentlyContinue)
        throw "Packaged activation returned process $activatedProcessId but no smoke marker arrived before timeout (process_still_running=$processStillRunning)."
    }
    $marker = Get-Content -LiteralPath $SmokeMarkerPath -Raw
    if ($marker.Trim() -ne 'BASIC_FUNCTION_SMOKE_PASS') { throw 'Packaged app reported a failed basic-function smoke.' }

    $sourceHashAfter = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($sourceHashAfter -ne $sourceHashBefore) { throw 'Frozen source package changed during test signing.' }
    $derivativeHash = (Get-FileHash -LiteralPath $derived -Algorithm SHA256).Hash
    if ($derivativeHash -eq $sourceHashBefore) { throw 'Signed derivative unexpectedly has the source SHA.' }
    $evidence = @{ status='TEST_SIGNED_DERIVATIVE_INSTALL_LAUNCH_SMOKE_PASS';
        source_sha256=$sourceHashBefore; derived_sha256=$derivativeHash;
        certificate_thumbprint=$cert.Thumbprint; created_at_utc=[DateTime]::UtcNow.ToString('o');
        host_os=(Get-CimInstance Win32_OperatingSystem).Caption;
        identity=$IdentityName; publisher=$Publisher; version=$Version;
        architecture=$Architecture; install='PASS'; launch='PASS'; basic_function='PASS';
        activation_app_user_model_id=$appUserModelId; activation_process_id=$activatedProcessId;
        store_candidate_unchanged=$true; diagnostic_only=$true; report=$report }
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding UTF8
    Write-Output ($evidence | ConvertTo-Json -Compress)
}
finally {
    if ($installed) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction SilentlyContinue }
    if ($trustedCert) { Remove-Item -LiteralPath "Cert:\LocalMachine\TrustedPeople\$($trustedCert.Thumbprint)" -Force -ErrorAction SilentlyContinue }
    if ($cert) { Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $derived -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $OutputDirectory ("test-cert-{0}.cer" -f $runId)) -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $SmokeMarkerPath -Force -ErrorAction SilentlyContinue
}
