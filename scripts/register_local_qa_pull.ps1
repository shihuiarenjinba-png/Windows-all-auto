# Explicit opt-in installation of the local 15-minute pull + checker task.
param(
  [string]$Inbox = "$env:LOCALAPPDATA\WindowsAllAuto\QA-Inbox",
  [string]$Checker = "C:\src\Windows-checker",
  [string]$Reports = "$env:LOCALAPPDATA\WindowsAllAuto\QA-Reports",
  [string]$StateRoot = "$env:LOCALAPPDATA\WindowsAllAuto\QA-State"
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command py.exe -ErrorAction Stop).Source
$gh = (Get-Command gh.exe -ErrorAction Stop).Source
& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI login required: gh auth login' }
$name='WindowsAllAuto-Factory-QA-Pull'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
  throw "Task already exists: $name. Review before replacing."
}
$arguments = '-3 -m scripts.local_periodic_qa --inbox "' + $Inbox + '" --checker "' + $Checker + '" --reports "' + $Reports + '" --state-root "' + $StateRoot + '"'
$action=New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$user="$env:USERDOMAIN\$env:USERNAME"
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 14)
Register-ScheduledTask -TaskName $name -Description 'Read-only MSIX pull and checker preflight (never installs or submits)' -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Host "Registered: $name. QA files go to $Inbox"
Write-Host "Checker reports go to $Reports"
Write-Host 'No MSIX is installed, archived, signed or submitted by this task.'
