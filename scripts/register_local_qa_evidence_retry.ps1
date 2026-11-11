# Explicit opt-in registration for the evidence retry worker only.
param(
  [string]$StateRoot = "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence",
  [string]$Repository = 'shihuiarenjinba-png/Windows-all-auto',
  [string]$EvidenceBranch = 'codex/local-qa-evidence-inbox',
  [string]$BaseRef = 'codex/windows-all-auto-integration-20261026',
  [string]$TaskName = 'WindowsAllAuto-Local-QA-Evidence-Retry'
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command py.exe -ErrorAction Stop).Source
$gh = (Get-Command gh.exe -ErrorAction Stop).Source
& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI login required: gh auth login' }

$pullTask = Get-ScheduledTask -TaskName 'WindowsAllAuto-Factory-QA-Pull' -ErrorAction SilentlyContinue
if ($pullTask) {
  Write-Host 'Existing pull task detected and preserved: WindowsAllAuto-Factory-QA-Pull'
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  throw "Task already exists: $TaskName. Review it; this script never replaces tasks."
}

$arguments = @(
  '-3', '-m', 'scripts.local_qa_evidence_worker',
  '--state-root', ('"' + $StateRoot + '"'), '--retry-only',
  '--github-repository', $Repository, '--github-branch', $EvidenceBranch,
  '--github-base-ref', $BaseRef
) -join ' '
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 15) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName `
  -Description 'Retry sanitized local QA evidence return and GitHub readback; no Store operations' `
  -Action $action -Trigger $trigger -Principal $principal | Out-Null
Write-Host "Registered: $TaskName"
Write-Host "Durable state: $StateRoot"
Write-Host 'The existing five GitHub rotations and Factory QA pull task were not modified.'
