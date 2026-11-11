# Read-only status report. It never starts, replaces or removes a task.
param([string]$StateRoot = "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence")
$ErrorActionPreference = 'Stop'
$names = @('WindowsAllAuto-Factory-QA-Pull', 'WindowsAllAuto-Local-QA-Evidence-Retry')
foreach ($name in $names) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if (-not $task) {
    [pscustomobject]@{ TaskName = $name; State = 'NOT_REGISTERED'; LastRunTime = $null; LastTaskResult = $null }
    continue
  }
  $info = Get-ScheduledTaskInfo -TaskName $name
  [pscustomobject]@{ TaskName = $name; State = $task.State; LastRunTime = $info.LastRunTime; LastTaskResult = $info.LastTaskResult }
}
$queue = Join-Path $StateRoot 'retry-queue'
$runs = Join-Path $StateRoot 'runs'
[pscustomobject]@{
  EvidenceRoot = $StateRoot
  PendingReturns = if (Test-Path $queue) { @(Get-ChildItem $queue -Filter '*.json' -File).Count } else { 0 }
  DurableRuns = if (Test-Path $runs) { @(Get-ChildItem $runs -Directory).Count } else { 0 }
}
