# Explicit opt-in: fetch immutable Factory product source snapshots every 15 minutes.
param(
  [Parameter(Mandatory=$true)][string]$Manifest,
  [string]$Root = "$env:LOCALAPPDATA\FactoryCodeMirror",
  [string]$Receipt = "$env:LOCALAPPDATA\FactoryCodeMirror\state\last-code-sync.json"
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = (Get-Command py.exe -ErrorAction Stop).Source
$git = (Get-Command git.exe -ErrorAction Stop).Source
$gh = (Get-Command gh.exe -ErrorAction Stop).Source
& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI login required: gh auth login' }
& $gh auth setup-git
if ($LASTEXITCODE -ne 0) { throw 'gh auth setup-git failed' }
$manifestPath = (Resolve-Path $Manifest).Path
$name = 'WindowsAllAuto-Factory-Code-Sync'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
  throw "Task already exists: $name. Review before replacing."
}
$arguments = '-3 -m scripts.local_code_sync --manifest "' + $manifestPath + '" --root "' + $Root + '" --receipt "' + $Receipt + '"'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 14)
Register-ScheduledTask -TaskName $name -Description 'Fetch exact immutable Factory source snapshots for local Codex/QA; no merge, execution, CAS or Store submit' -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Host "Registered: $name"
Write-Host "Snapshots: $Root\<repo>\<source-sha-prefix>"
Write-Host "Receipt: $Receipt"
Write-Host 'The task never pulls into or overwrites an existing development checkout.'
