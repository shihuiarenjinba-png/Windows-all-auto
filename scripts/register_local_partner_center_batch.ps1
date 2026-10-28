[CmdletBinding()]
param(
    [string]$TaskName = 'WindowsAllAuto-PartnerCenter-Batch',
    [string]$RunnerRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'WindowsAllAuto\PartnerCenterBatch'),
    [string]$ProvisionerRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'provisioner-app-ui-attestation')
)

$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $StateDir 'final-batch-receipt.json'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    throw 'TERMINAL_4_OF_4_PASS_REQUIRED'
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.status -ne 'LOCAL_WINDOWS_NO_LLM_AUTOMATION_PASS' -or
    $receipt.batch_status -ne 'MULTI_PRODUCT_IDENTITY_BATCH_PASS' -or
    $receipt.processed -ne 4 -or $receipt.replay -ne 4) {
    throw 'TERMINAL_4_OF_4_PASS_REQUIRED'
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    throw 'SCHEDULED_TASK_ALREADY_EXISTS_NO_OVERWRITE'
}

$python = (Get-Command py.exe -ErrorAction Stop).Source
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
    status = 'REGISTERED'
    task = $TaskName
    frequency = '12 HOURS'
    multiple_instances = $registered.Settings.MultipleInstances
    run_level = $registered.Principal.RunLevel
    logon_type = $registered.Principal.LogonType
    runner = (Join-Path $RunnerRoot 'scripts\run_local_partner_center_batch.py')
    state_dir = $StateDir
} | ConvertTo-Json -Depth 5
