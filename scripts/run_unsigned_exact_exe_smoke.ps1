param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][string]$OutputReceipt,
    [ValidateRange(5,300)][int]$ObservationSeconds = 60
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }
if (Test-Path -LiteralPath $OutputReceipt) {
    throw 'refusing to overwrite existing launch evidence'
}

$exe = Get-Item -LiteralPath $ExePath -ErrorAction Stop
if (-not $exe.PSIsContainer -and $exe.Extension -ieq '.exe') {
    # expected
} else {
    throw 'ExePath must point to one existing .exe file'
}

$expected = $ExpectedSha256.Trim().ToLowerInvariant()
if ($expected -notmatch '^[0-9a-f]{64}$') {
    throw 'ExpectedSha256 must be exactly 64 hexadecimal characters'
}
$actual = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -cne $expected) {
    throw 'EXE SHA256 mismatch; refusing launch'
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($elevated) {
    throw 'refusing launch from elevated/admin PowerShell; use normal user context'
}

$outPath = [System.IO.Path]::GetFullPath($OutputReceipt)
$outDir = Split-Path -Parent $outPath
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$startedAt = Get-Date
$processStarted = $false
$normalExit = $false
$exitCode = $null
$processId = $null
$launchError = ''
$status = 'LAUNCH_FAILED'
$ciEventIds = @()
$ciEvents = @()
$ciEvidenceQueryAttempts = 0
$ciEvidenceQueryError = ''

try {
    $process = Start-Process -FilePath $exe.FullName -PassThru -ErrorAction Stop
    $processStarted = $true
    $processId = $process.Id

    $closed = $process.WaitForExit($ObservationSeconds * 1000)
    if ($closed) {
        $process.Refresh()
        $exitCode = $process.ExitCode
        if ($exitCode -eq 0) {
            $normalExit = $true
            $status = 'PASS_NORMAL_EXIT'
        } else {
            $status = 'EXITED_NONZERO'
        }
    } else {
        $status = 'STARTED_NOT_CLOSED_WITHIN_WINDOW'
        Write-Host 'Process is still running. Do not relaunch. Close it normally through the app UI.'
    }
}
catch {
    $launchError = $_.Exception.Message

    try {
        $windowStart = $startedAt.AddSeconds(-2)
        $namePattern = [regex]::Escape($exe.Name)
        $events = @()

        # Code Integrity events can arrive shortly after Start-Process returns
        # the blocking error. Poll the read-only log for a bounded interval;
        # never retry the executable itself.
        for ($pollAttempt = 1; $pollAttempt -le 6; $pollAttempt++) {
            $ciEvidenceQueryAttempts = $pollAttempt
            if ($pollAttempt -gt 1) {
                Start-Sleep -Milliseconds 500
            }
            $queryErrors = @()
            $windowEnd = (Get-Date).AddSeconds(2)
            $candidateEvents = @(Get-WinEvent -FilterHashtable @{
                LogName = 'Microsoft-Windows-CodeIntegrity/Operational'
                StartTime = $windowStart
            } -ErrorAction SilentlyContinue -ErrorVariable queryErrors |
                Where-Object {
                    $_.TimeCreated -le $windowEnd -and
                    (($_.ToXml() -match $namePattern) -or ($_.Message -match $namePattern))
                } |
                Select-Object -First 20)

            if ($queryErrors.Count -gt 0) {
                $ciEvidenceQueryError = [string]$queryErrors[0].Exception.Message
            }
            if ($candidateEvents.Count -gt 0) {
                $events = $candidateEvents
                break
            }
        }

        foreach ($evt in $events) {
            $ciEventIds += [int]$evt.Id
            $ciEvents += [ordered]@{
                event_id = [int]$evt.Id
                time_created = $evt.TimeCreated.ToUniversalTime().ToString('o')
                provider = [string]$evt.ProviderName
            }
        }
    } catch {
        # Evidence collection failure must never trigger a second launch attempt.
        $ciEvents += [ordered]@{
            event_id = 0
            time_created = (Get-Date).ToUniversalTime().ToString('o')
            provider = 'CodeIntegrityEvidenceUnavailable'
        }
    }

    $blockingEventIds = @(3033, 3077)
    $blockingEvidence = @($ciEventIds | Where-Object { $blockingEventIds -contains $_ })
    if ($blockingEvidence.Count -gt 0) {
        $status = 'APPLICATION_CONTROL_BLOCKED'
    } else {
        $status = 'LAUNCH_FAILED'
    }
}

$receipt = [ordered]@{
    schema_version = 'unsigned-exe-launch-receipt/1'
    status = $status
    exe_path = $exe.FullName
    expected_exe_sha256 = $expected
    actual_exe_sha256 = $actual
    launched_at_utc = $startedAt.ToUniversalTime().ToString('o')
    observation_seconds = $ObservationSeconds
    normal_user_context = $true
    elevated = $false
    launch_attempts = 1
    process_started = $processStarted
    process_id = $processId
    exit_code = $exitCode
    normal_exit = $normalExit
    launch_error = $launchError
    code_integrity_event_ids = @($ciEventIds)
    code_integrity_events = @($ciEvents)
    code_integrity_query_attempts = $ciEvidenceQueryAttempts
    code_integrity_query_error = $ciEvidenceQueryError
    package_rebuilt = $false
    security_bypass_used = $false
    security_policy_modified = $false
    certificate_store_modified = $false
    alternate_bypass_used = $false
    msix_installed = $false
    partner_center_write_performed = $false
    package_uploaded = $false
    certification_submitted = $false
    published = $false
}

$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $outPath -Encoding UTF8
Write-Host ("UNSIGNED_EXE_LAUNCH status=" + $status + " receipt=" + $outPath)

if ($status -eq 'PASS_NORMAL_EXIT') { exit 0 }
exit 2
