[CmdletBinding()]
param(
    [string]$TaskName = 'WindowsAllAuto-PartnerCenter-Batch',
    [string]$RunnerRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'WindowsAllAuto\PartnerCenterBatch'),
    [string]$ProvisionerRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'provisioner-app-ui-attestation')
)

$ErrorActionPreference = 'Stop'
# A terminal 4/4 PASS cannot be a registration prerequisite: the trusted
# scheduled-host trigger has not yet occurred. Require a live, side-effect-free
# GitHub queue/artifact/source preflight instead. This does NOT attest the
# saved ChatGPT 36-minute schedule or authorize Identity CAS.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    throw 'SCHEDULED_TASK_ALREADY_EXISTS_NO_OVERWRITE'
}

$python = (Get-Command py.exe -ErrorAction Stop).Source
Push-Location -LiteralPath $RunnerRoot
try {
    $preflightOutput = & $python -3 -m scripts.run_local_partner_center_batch `
        --preflight-only --execution-origin WINDOWS_TASK_SCHEDULER `
        --provisioner-root $ProvisionerRoot --state-dir $StateDir 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'BATCH_QUEUE_PREFLIGHT_HOLD'
    }
    $preflight = ($preflightOutput | Out-String | ConvertFrom-Json)
    if ($preflight.status -ne 'BATCH_PREFLIGHT_READY' -or
        $preflight.discovered_count -ne 4 -or
        $preflight.execution_trigger_proven -ne $false -or
        $preflight.local_execution -ne 'NOT_PERFORMED') {
        throw 'BATCH_QUEUE_PREFLIGHT_HOLD'
    }
}
finally {
    Pop-Location
}

$arguments = @(
    '-3', '-m', 'scripts.run_local_partner_center_batch',
    '--execution-origin', 'WINDOWS_TASK_SCHEDULER',
    '--state-dir', ('"{0}"' -f $StateDir),
    '--provisioner-root', ('"{0}"' -f $ProvisionerRoot)
) -join ' '
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RunnerRoot
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddHours(12)) `
    -RepetitionInterval (New-TimeSpan -Hours 12)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive `
    -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'No-LLM APP Partner Center Identity queue worker; no Store submission.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
[ordered]@{
    status = 'REGISTERED__SCHEDULE_PROOF_PENDING'
    registration_gate = 'LIVE_GITHUB_BATCH_PREFLIGHT_ONLY'
    scheduled_36_min_trigger_proven = $false
    preflight_central_head_sha = $preflight.central_head_sha
    task = $TaskName
    frequency = '12 HOURS'
    multiple_instances = $registered.Settings.MultipleInstances
    run_level = $registered.Principal.RunLevel
    logon_type = $registered.Principal.LogonType
    runner = (Join-Path $RunnerRoot 'scripts\run_local_partner_center_batch.py')
    state_dir = $StateDir
} | ConvertTo-Json -Depth 5
