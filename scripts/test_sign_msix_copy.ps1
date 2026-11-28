[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$IdentityName,
    [Parameter(Mandatory = $true)][string]$Publisher,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][ValidateSet('x86','x64','arm64')][string]$Architecture,
    [Parameter(Mandatory = $true)][string]$ApplicationId,
    [string]$SmokeMarkerPath,
    [ValidateSet('MarkerSmoke','ProcessLaunch')][string]$LaunchMode = 'MarkerSmoke',
    [ValidateRange(30,1800)][int]$OperationTimeoutSeconds = 300,
    [string]$OutputDirectory = $env:RUNNER_TEMP
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
if ($env:GITHUB_ACTIONS -ne 'true') {
    throw 'Test signing and trust are restricted to an ephemeral GitHub Actions runner.'
}
if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'ExpectedSha256 must be a full SHA-256.' }
if ($LaunchMode -eq 'MarkerSmoke' -and [string]::IsNullOrWhiteSpace($SmokeMarkerPath)) { throw 'MarkerSmoke requires SmokeMarkerPath.' }
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
$phaseTimings = [System.Collections.Generic.List[object]]::new()
$currentPhase = $null
$finalStatus = 'RUNNING'
$originalMarkerPresent = $false
if ($LaunchMode -eq 'MarkerSmoke') {
    $originalMarkerPresent = Test-Path -LiteralPath $SmokeMarkerPath
    if ($originalMarkerPresent) { throw 'SmokeMarkerPath already exists; refusing to accept stale launch evidence.' }
}
function Save-QAReceipt {
    param([string]$Status,[string]$ErrorMessage=$null)
    $value = [ordered]@{
        schema_version='all-auto-msix-test-sign-install/2'; status=$Status
        created_at_utc=[DateTime]::UtcNow.ToString('o'); run_id=$runId; phase=$currentPhase
        phase_timings=@($phaseTimings); source_sha256=$sourceHashBefore
        derived_sha256=$(if (Test-Path -LiteralPath $derived) { (Get-FileHash -LiteralPath $derived -Algorithm SHA256).Hash } else { $null })
        identity=$IdentityName; publisher=$Publisher; version=$Version; architecture=$Architecture
        launch_mode=$LaunchMode; failure=$ErrorMessage
        store_write_performed=$false; certification_executed=$false; publish_executed=$false
    }
    $tmp = "$receipt.tmp"
    $value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $receipt -Force
}
function Invoke-QAPhase {
    param([Parameter(Mandatory=$true)][string]$Name,[Parameter(Mandatory=$true)][scriptblock]$Action)
    $script:currentPhase = $Name
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $record = [ordered]@{phase=$Name;status='RUNNING';started_at_utc=[DateTime]::UtcNow.ToString('o');elapsed_ms=0;timeout_seconds=$OperationTimeoutSeconds}
    $phaseTimings.Add($record)
    Save-QAReceipt -Status 'RUNNING'
    try {
        $result = & $Action
        $watch.Stop()
        $record.elapsed_ms = $watch.ElapsedMilliseconds
        $record.completed_at_utc = [DateTime]::UtcNow.ToString('o')
        if ($watch.Elapsed.TotalSeconds -gt $OperationTimeoutSeconds) {
            $record.status = 'TIMEOUT'
            Save-QAReceipt -Status 'PHASE_TIMEOUT' -ErrorMessage "Phase $Name exceeded $OperationTimeoutSeconds seconds."
            throw "Phase $Name exceeded $OperationTimeoutSeconds seconds."
        }
        $record.status = 'PASS'
        Save-QAReceipt -Status 'RUNNING'
        return $result
    } catch {
        $watch.Stop()
        if ($record.status -eq 'RUNNING') {
            $record.status='FAILED'; $record.elapsed_ms=$watch.ElapsedMilliseconds
            $record.completed_at_utc=[DateTime]::UtcNow.ToString('o'); $record.error_type=$_.Exception.GetType().Name
        }
        Save-QAReceipt -Status 'PHASE_FAILED' -ErrorMessage $_.Exception.Message
        throw
    }
}
Save-QAReceipt -Status 'RUNNING'
try {
    Invoke-QAPhase -Name 'COPY_FROZEN_PACKAGE' -Action { Copy-Item -LiteralPath $source -Destination $derived } | Out-Null
    $cert = Invoke-QAPhase -Name 'CREATE_EPHEMERAL_CERTIFICATE' -Action { New-SelfSignedCertificate -Type Custom -Subject $Publisher -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 2048 -KeyUsage DigitalSignature -NotAfter (Get-Date).AddDays(2) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')}
    $signTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signTool) {
        $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $signTool = Get-ChildItem -LiteralPath $sdkRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $signTool) { throw 'Windows SDK SignTool was not found.' }
    Invoke-QAPhase -Name 'SIGN_TEST_DERIVATIVE' -Action { & $signTool sign /fd SHA256 /sha1 $cert.Thumbprint $derived; if ($LASTEXITCODE -ne 0) { throw 'SignTool signing failed.' } } | Out-Null
    $publicCert = Join-Path $OutputDirectory ("test-cert-{0}.cer" -f $runId)
    Invoke-QAPhase -Name 'EXPORT_PUBLIC_CERTIFICATE' -Action { Export-Certificate -Cert $cert -FilePath $publicCert | Out-Null } | Out-Null
    $trustedCert = Invoke-QAPhase -Name 'IMPORT_EPHEMERAL_TRUST' -Action { Import-Certificate -FilePath $publicCert -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' }
    Invoke-QAPhase -Name 'VERIFY_TEST_SIGNATURE' -Action { & $signTool verify /pa /v $derived; if ($LASTEXITCODE -ne 0) { throw 'SignTool signature verification failed after ephemeral trust was installed.' } } | Out-Null
    Invoke-QAPhase -Name 'VERIFY_NON_SIGNATURE_PAYLOAD' -Action { Push-Location $PSScriptRoot; try { python -m all_auto.msix_derivative --source $source --derived $derived --expected-source-sha256 $ExpectedSha256 --identity-name $IdentityName --publisher $Publisher --version $Version --architecture $Architecture --report $report; if ($LASTEXITCODE -ne 0) { throw 'Signature-only derivative verification failed.' } } finally { Pop-Location } } | Out-Null

    Invoke-QAPhase -Name 'INSTALL_TEST_SIGNED_COPY' -Action { Add-AppxPackage -Path $derived -ErrorAction Stop } | Out-Null
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
    public static uint Activate(string appUserModelId, string arguments) {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint processId;
        int hr = manager.ActivateApplication(appUserModelId, arguments, 0, out processId);
        Marshal.ThrowExceptionForHR(hr);
        return processId;
    }
}
'@
    Add-Type -TypeDefinition $activationSource
    $appUserModelId = "$appxFamily!$ApplicationId"
    $activationStarted = Get-Date
    $markerArgument = if ($LaunchMode -eq 'MarkerSmoke') { '"' + $SmokeMarkerPath.Replace('"', '\"') + '"' } else { '' }
    $activatedProcessId = Invoke-QAPhase -Name 'ACTIVATE_AUMID' -Action { [PackageActivation]::Activate($appUserModelId, $markerArgument) }
    $deadline = (Get-Date).AddSeconds(45)
    $markerContent = ''
    if ($LaunchMode -eq 'ProcessLaunch') {
        while ((Get-Date) -lt $deadline -and -not (Get-Process -Id $activatedProcessId -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 }
        if (-not (Get-Process -Id $activatedProcessId -ErrorAction SilentlyContinue)) { throw 'AUMID did not start the packaged process within 45 seconds.' }
        $registeredActivation = 'PASS'; $activationDiagnostics = @(); $launchMethod = 'AUMID_PROCESS_START_ONLY'; $markerContent = 'NOT_APPLICABLE'
    } else {
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $SmokeMarkerPath) {
            $markerContent = (Get-Content -LiteralPath $SmokeMarkerPath -Raw).Trim()
            if ($markerContent -eq 'BASIC_FUNCTION_SMOKE_PASS' -or $markerContent -like 'ERROR:*' -or
                $markerContent -eq 'BASIC_FUNCTION_SMOKE_FAIL') { break }
        }
        Start-Sleep -Milliseconds 500
    }
    $registeredActivation = 'PASS'
    $activationDiagnostics = @()
    $launchMethod = 'AUMID'
    if (-not (Test-Path -LiteralPath $SmokeMarkerPath)) {
        $registeredActivation = 'UNCONFIRMED_IN_HOSTED_RUNNER'
        $processStillRunning = [bool](Get-Process -Id $activatedProcessId -ErrorAction SilentlyContinue)
        foreach ($logName in @('Microsoft-Windows-AppModel-Runtime/Admin',
                               'Microsoft-Windows-AppModel-Runtime/Operational',
                               'Microsoft-Windows-AppXDeploymentServer/Operational')) {
            try {
                $activationDiagnostics += Get-WinEvent -FilterHashtable @{ LogName=$logName; StartTime=$activationStarted } `
                    -ErrorAction Stop | Where-Object { $_.Message -match [regex]::Escape($appUserModelId) -or
                        $_.Message -match [regex]::Escape($IdentityName) -or $_.Message -match "\b$activatedProcessId\b" } |
                    Select-Object -Last 5 | ForEach-Object { "$($_.LogName) EventId=$($_.Id) Level=$($_.LevelDisplayName): $($_.Message)" }
            } catch { }
        }
        if (-not $activationDiagnostics.Count) { $activationDiagnostics = @('no matching AppModel/AppX events found') }
        $launchMethod = 'installed-package-executable'
        $installedExecutable = Join-Path $installed.InstallLocation $application.Executable
        if (-not (Test-Path -LiteralPath $installedExecutable)) { throw 'Installed package executable is missing after AUMID activation returned without smoke evidence.' }
        $directProcess = Start-Process -FilePath $installedExecutable -ArgumentList $markerArgument -PassThru -Wait
        if ($directProcess.ExitCode -ne 0) { throw "Installed package executable exited with code $($directProcess.ExitCode); AUMID activation was unconfirmed. Diagnostics: $($activationDiagnostics -join ' | ')" }
        if (-not (Test-Path -LiteralPath $SmokeMarkerPath)) { throw "Installed package executable exited successfully without writing its smoke marker; AUMID activation was unconfirmed (process_still_running=$processStillRunning). Diagnostics: $($activationDiagnostics -join ' | ')" }
        $markerContent = (Get-Content -LiteralPath $SmokeMarkerPath -Raw).Trim()
    }
    }
    if ($LaunchMode -eq 'MarkerSmoke' -and $markerContent -ne 'BASIC_FUNCTION_SMOKE_PASS') {
        throw "Packaged app did not complete basic-function smoke. Marker: $markerContent"
    }

    $sourceHashAfter = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($sourceHashAfter -ne $sourceHashBefore) { throw 'Frozen source package changed during test signing.' }
    $derivativeHash = (Get-FileHash -LiteralPath $derived -Algorithm SHA256).Hash
    if ($derivativeHash -eq $sourceHashBefore) { throw 'Signed derivative unexpectedly has the source SHA.' }
    $evidenceStatus = if ($LaunchMode -eq 'ProcessLaunch') { 'TEST_SIGNED_DERIVATIVE_INSTALL_PROCESS_LAUNCH_PASS_FUNCTIONS_NOT_RUN' } elseif ($registeredActivation -eq 'PASS') { 'TEST_SIGNED_DERIVATIVE_INSTALL_LAUNCH_SMOKE_PASS' } else { 'TEST_SIGNED_DERIVATIVE_INSTALL_EXECUTABLE_SMOKE_PASS_ACTIVATION_UNCONFIRMED' }
    $evidence = @{ schema_version='all-auto-msix-test-sign-install/2'; phase_timings=@($phaseTimings); status=$evidenceStatus;
        source_sha256=$sourceHashBefore; derived_sha256=$derivativeHash;
        certificate_thumbprint=$cert.Thumbprint; created_at_utc=[DateTime]::UtcNow.ToString('o');
        host_os=(Get-CimInstance Win32_OperatingSystem).Caption;
        identity=$IdentityName; publisher=$Publisher; version=$Version;
        architecture=$Architecture; install='PASS'; launch='PASS'; basic_function=$(if ($LaunchMode -eq 'MarkerSmoke') { 'PASS' } else { 'NOT_RUN' });
        activation_app_user_model_id=$appUserModelId; activation_process_id=$activatedProcessId;
        registered_activation=$registeredActivation; launch_method=$launchMethod;
        activation_diagnostics=$activationDiagnostics;
        store_candidate_unchanged=$true; diagnostic_only=$true; report=$report }
    $finalStatus = $evidenceStatus
    $phaseTimings.Add([ordered]@{phase='COMPLETE';status='PASS';completed_at_utc=[DateTime]::UtcNow.ToString('o')})
    Save-QAReceipt -Status $finalStatus
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding UTF8
    Write-Output ($evidence | ConvertTo-Json -Compress)
}
catch {
    $failure = $_.Exception.Message
    $finalStatus = if ($failure -match 'exceeded .* seconds') { 'PHASE_TIMEOUT' } else { 'FAILED' }
    try { Save-QAReceipt -Status $finalStatus -ErrorMessage $failure } catch { Write-Error 'Could not persist QA failure receipt.' }
    throw
}
finally {
    if ($installed) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction SilentlyContinue }
    if ($trustedCert) { Remove-Item -LiteralPath "Cert:\LocalMachine\TrustedPeople\$($trustedCert.Thumbprint)" -Force -ErrorAction SilentlyContinue }
    if ($cert) { Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $derived -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $OutputDirectory ("test-cert-{0}.cer" -f $runId)) -Force -ErrorAction SilentlyContinue
    if ($LaunchMode -eq 'MarkerSmoke' -and $SmokeMarkerPath) { Remove-Item -LiteralPath $SmokeMarkerPath -Force -ErrorAction SilentlyContinue }
}
