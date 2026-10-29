[CmdletBinding()]
param(
    [string]$TaskName = 'WindowsAllAuto-PartnerCenter-Batch',
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'WindowsAllAuto\PartnerCenterBatch'),
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$marker = Join-Path $StateDir 'scheduler-manual-start.marker'
if (Test-Path -LiteralPath $marker) {
    throw 'MANUAL_START_MARKER_ALREADY_EXISTS'
}
New-Item -ItemType File -Path $marker -Force:$false | Out-Null
Start-ScheduledTask -TaskName $TaskName
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
} while ($task.State -eq 'Running' -and (Get-Date) -lt $deadline)

if ($task.State -eq 'Running') {
    throw 'SCHEDULED_TASK_MANUAL_START_TIMEOUT'
}
if ($info.LastTaskResult -ne 0) {
    throw ('SCHEDULED_TASK_LAST_RESULT_{0}' -f $info.LastTaskResult)
}
[ordered]@{
    status = 'PASS'
    task = $TaskName
    execution_origin = 'WINDOWS_TASK_SCHEDULER_MANUAL_START'
    last_run_time = $info.LastRunTime.ToString('o')
    last_task_result = $info.LastTaskResult
    receipt = (Join-Path $StateDir 'final-batch-receipt.json')
} | ConvertTo-Json -Depth 4
