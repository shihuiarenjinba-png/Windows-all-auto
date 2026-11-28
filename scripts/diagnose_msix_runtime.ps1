param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $false)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$IdentityName,
    [Parameter(Mandatory = $true)][string]$Publisher,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $false)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$package = (Resolve-Path -LiteralPath $PackagePath).Path
$packageItem = Get-Item -LiteralPath $package
if ($packageItem.PSIsContainer) { throw 'PackagePath must name a file.' }
$actualHash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
$signature = (Get-AuthenticodeSignature -LiteralPath $package).Status.ToString()
$streams = @(Get-Item -LiteralPath $package -Stream * -ErrorAction SilentlyContinue | ForEach-Object { $_.Stream })
$zonePresent = $streams -contains 'Zone.Identifier'

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($package)
try {
    $manifestEntry = $zip.GetEntry('AppxManifest.xml')
    if ($null -eq $manifestEntry) { throw 'AppxManifest.xml is missing.' }
    $reader = [System.IO.StreamReader]::new($manifestEntry.Open())
    try { [xml]$manifest = $reader.ReadToEnd() } finally { $reader.Dispose() }
    $signatureBlockPresent = $null -ne $zip.GetEntry('AppxSignature.p7x')
} finally { $zip.Dispose() }

$identity = $manifest.Package.Identity
$targetFamilies = @($manifest.Package.Dependencies.TargetDeviceFamily | ForEach-Object {
    [pscustomobject]@{ Name = $_.Name; MinVersion = $_.MinVersion; MaxVersionTested = $_.MaxVersionTested }
})
$entryPoint = $manifest.Package.Applications.Application.EntryPoint
$capabilities = @($manifest.Package.Capabilities.ChildNodes | ForEach-Object { $_.Name })
$acl = @(Get-Acl -LiteralPath $package | Select-Object -ExpandProperty Access | ForEach-Object {
    [pscustomobject]@{ Identity = $_.IdentityReference.Value; Rights = $_.FileSystemRights.ToString(); Type = $_.AccessControlType.ToString(); Inherited = $_.IsInherited }
})

$exeFacts = $null
if ($ExecutablePath) {
    $exe = (Resolve-Path -LiteralPath $ExecutablePath).Path
    $exeItem = Get-Item -LiteralPath $exe
    $exeSignature = (Get-AuthenticodeSignature -LiteralPath $exe).Status.ToString()
    $exeStreams = @(Get-Item -LiteralPath $exe -Stream * -ErrorAction SilentlyContinue | ForEach-Object { $_.Stream })
    $exeAcl = @(Get-Acl -LiteralPath $exe | Select-Object -ExpandProperty Access | ForEach-Object {
        [pscustomobject]@{ Identity = $_.IdentityReference.Value; Rights = $_.FileSystemRights.ToString(); Type = $_.AccessControlType.ToString(); Inherited = $_.IsInherited }
    })
    $exeFacts = [pscustomobject]@{
        Path = $exe; SizeBytes = $exeItem.Length
        Sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
        Signature = $exeSignature; ZoneIdentifierPresent = ($exeStreams -contains 'Zone.Identifier')
        Acl = $exeAcl
    }
}

$appxRegistration = 'UNAVAILABLE'
try {
    $registered = @(Get-AppxPackage -Name $IdentityName -ErrorAction Stop)
    $appxRegistration = if ($registered.Count) { 'REGISTERED' } else { 'NOT_REGISTERED' }
} catch { $appxRegistration = 'ACCESS_DENIED_OR_UNAVAILABLE' }

$appLocker = 'UNAVAILABLE'
if (Get-Command Get-AppLockerPolicy -ErrorAction SilentlyContinue) {
    try {
        $effective = Get-AppLockerPolicy -Effective -ErrorAction Stop
        $appLocker = @((Select-Xml -Content $effective.ToXml() -XPath '//*[local-name()="RuleCollection"]' |
            ForEach-Object { $_.Node.GetAttribute('Type') + ':' + $_.Node.GetAttribute('EnforcementMode') }))
        if ($appLocker.Count -eq 0) { $appLocker = 'QUERY_RETURNED_NO_RULE_COLLECTIONS' }
    } catch { $appLocker = 'ACCESS_DENIED_OR_UNAVAILABLE' }
}
$ciTool = 'UNAVAILABLE'
if (Get-Command CiTool.exe -ErrorAction SilentlyContinue) {
    try { & CiTool.exe -lp *> $null; $ciTool = 'EXIT_' + [string]$LASTEXITCODE }
    catch { $ciTool = 'ACCESS_DENIED_OR_UNAVAILABLE' }
}

$windows = [pscustomobject]@{ Version = [Environment]::OSVersion.Version.ToString();
    Is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem; Is64BitProcess = [Environment]::Is64BitProcess }
$computer = $null
try { $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop | Select-Object Model, HypervisorPresent }
catch { $computer = [pscustomobject]@{ Model = 'UNAVAILABLE'; HypervisorPresent = $null } }
$executionPolicy = @(Get-ExecutionPolicy -List | ForEach-Object { $_.Scope.ToString() + ':' + $_.ExecutionPolicy.ToString() })
$eventMatchCount = 0
try {
    $recent = Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-AppXDeploymentServer/Operational'; StartTime = (Get-Date).AddDays(-14) } -MaxEvents 300 -ErrorAction Stop
    $eventMatchCount = @($recent | Where-Object { $_.Message -match [regex]::Escape($IdentityName) }).Count
} catch { $eventMatchCount = $null }

$report = [ordered]@{
    SchemaVersion = 'all-auto-msix-windows-diagnostic/1'; CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
    DiagnosticOnly = $true; InstallAttempted = $false; LaunchAttempted = $false
    Package = [pscustomobject]@{ Path = $package; SizeBytes = $packageItem.Length; LastWriteTimeUtc = $packageItem.LastWriteTimeUtc.ToString('o')
        Sha256 = $actualHash; ExpectedSha256Matches = ($actualHash -eq $ExpectedSha256.ToLowerInvariant())
        Signature = $signature; ZoneIdentifierPresent = $zonePresent; AppxSignatureBlockPresent = $signatureBlockPresent
        Identity = $identity.Name; Publisher = $identity.Publisher; Version = $identity.Version
        Architecture = $identity.ProcessorArchitecture; IdentityMatches = ($identity.Name -eq $IdentityName -and $identity.Publisher -eq $Publisher -and $identity.Version -eq $Version)
        ApplicationEntryPoint = $entryPoint; RunFullTrustCapabilityPresent = ($capabilities -contains 'runFullTrust')
        TargetDeviceFamilies = $targetFamilies; Acl = $acl }
    Executable = $exeFacts; Windows = $windows; Computer = $computer
    AppxRegistration = $appxRegistration; AppLockerEffective = $appLocker; CodeIntegrityQuery = $ciTool
    PowerShellExecutionPolicy = $executionPolicy; MatchingAppxEventsLast14Days = $eventMatchCount
    Assessment = 'RUNTIME_QA_UNRESOLVED'; Notes = @('No install or executable launch was performed by this diagnostic.','PowerShell execution policy does not govern native EXE execution.')
}
$json = $report | ConvertTo-Json -Depth 8
if ($OutputPath) { $json | Set-Content -LiteralPath $OutputPath -Encoding utf8 }
$json
