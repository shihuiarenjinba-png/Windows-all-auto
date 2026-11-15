# Safe real GitHub round-trip smoke for the local QA evidence transport.
# The synthetic driver uses a synthetic Event Log record so this public-repo smoke
# never returns unrelated real Windows Application events.
[CmdletBinding()]
param(
  [string]$Repository = 'shihuiarenjinba-png/Windows-all-auto',
  [string]$CodeBranch = '',
  [string]$EvidenceBranch = 'codex/local-qa-evidence-smoke',
  [string]$StateRoot = "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence-Smoke",
  [switch]$AllowGitHubWrite,
  [switch]$EnableAI
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Equal {
  param([object]$Actual, [object]$Expected, [string]$Name)
  if ($Actual -ne $Expected) {
    throw "SMOKE_ASSERT_FAILED: $Name expected '$Expected' but got '$Actual'"
  }
}

function Assert-False {
  param([object]$Actual, [string]$Name)
  if ([bool]$Actual) {
    throw "SMOKE_ASSERT_FAILED: $Name must remain false"
  }
}

if ($env:OS -ne 'Windows_NT') {
  throw 'LOCAL_GITHUB_SMOKE_HOLD: Windows is required'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$gh = (Get-Command gh.exe -ErrorAction Stop).Source
$git = (Get-Command git.exe -ErrorAction Stop).Source
$py = (Get-Command py.exe -ErrorAction Stop).Source

Push-Location $repoRoot
try {
  & $gh auth status *> $null
  if ($LASTEXITCODE -ne 0) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: gh auth status failed. Repair GitHub CLI login first.'
  }

  $login = ((& $gh api user --jq '.login') -join '').Trim()
  if ($LASTEXITCODE -ne 0 -or -not $login) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: unable to read authenticated GitHub user'
  }

  $currentBranch = ((& $git branch --show-current) -join '').Trim()
  if ($LASTEXITCODE -ne 0 -or -not $currentBranch) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: detached HEAD or branch detection failed'
  }
  if (-not $CodeBranch) {
    $CodeBranch = $currentBranch
  }
  Assert-Equal $currentBranch $CodeBranch 'current branch'

  if ($EvidenceBranch -notmatch '^codex/local-qa-evidence-[A-Za-z0-9._/-]+$') {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: EvidenceBranch must use codex/local-qa-evidence-*'
  }
  if ($EvidenceBranch -eq $CodeBranch) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: evidence branch must differ from the code branch'
  }

  $origin = ((& $git remote get-url origin) -join '').Trim()
  if ($LASTEXITCODE -ne 0 -or $origin -notmatch [regex]::Escape($Repository)) {
    throw "LOCAL_GITHUB_SMOKE_HOLD: origin does not match $Repository"
  }

  $dirty = @(& $git status --porcelain)
  if ($LASTEXITCODE -ne 0) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: git status failed'
  }
  if ($dirty.Count -gt 0) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: working tree must be clean'
  }

  $localHead = ((& $git rev-parse HEAD) -join '').Trim().ToLowerInvariant()
  $remoteHead = ((& $gh api "repos/$Repository/git/ref/heads/$CodeBranch" --jq '.object.sha') -join '').Trim().ToLowerInvariant()
  if ($LASTEXITCODE -ne 0 -or $remoteHead -notmatch '^[0-9a-f]{40}$') {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: unable to resolve remote code branch HEAD'
  }
  Assert-Equal $localHead $remoteHead 'local/remote code HEAD'

  $pythonVersion = ((& $py -3 -c 'import platform; print(platform.python_version())') -join '').Trim()
  if ($LASTEXITCODE -ne 0 -or -not $pythonVersion) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: Python launcher validation failed'
  }

  $preflight = [ordered]@{
    status = 'PREFLIGHT_PASS'
    repository = $Repository
    authenticated_user = $login
    code_branch = $CodeBranch
    code_head = $localHead
    evidence_branch = $EvidenceBranch
    python = $pythonVersion
    github_write_requested = [bool]$AllowGitHubWrite
    synthetic_event_log = $true
    real_windows_event_log_returned = $false
    store_operations = $false
    scheduled_task_changes = $false
  }

  if (-not $AllowGitHubWrite) {
    $preflight | ConvertTo-Json -Depth 5
    Write-Host 'Preflight only. Re-run with -AllowGitHubWrite for the sanitized GitHub round-trip.'
    return
  }

  New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $captureRoot = Join-Path $StateRoot "wrapper-$stamp"
  New-Item -ItemType Directory -Force -Path $captureRoot | Out-Null
  $driverStdout = Join-Path $captureRoot 'driver.stdout.json'
  $driverStderr = Join-Path $captureRoot 'driver.stderr.txt'

  $driverArgs = @(
    '-3', '-m', 'scripts.local_qa_github_smoke_driver',
    '--state-root', $StateRoot,
    '--repository', $Repository,
    '--code-branch', $CodeBranch,
    '--source-sha', $localHead,
    '--evidence-branch', $EvidenceBranch
  )
  if ($EnableAI) {
    $driverArgs += '--enable-ai'
  }

  & $py @driverArgs 1> $driverStdout 2> $driverStderr
  $driverExit = $LASTEXITCODE
  if ($driverExit -ne 0) {
    $stderrText = if (Test-Path $driverStderr) { Get-Content $driverStderr -Raw } else { '' }
    throw "LOCAL_GITHUB_SMOKE_HOLD: smoke driver exit=$driverExit; $stderrText"
  }

  $driverResult = Get-Content $driverStdout -Raw | ConvertFrom-Json
  Assert-Equal $driverResult.status 'LOCAL_GITHUB_EVIDENCE_SMOKE_DRIVER_PASS' 'driver status'
  Assert-Equal $driverResult.test_status 'TEST_PASS' 'test status'
  Assert-Equal ([bool]$driverResult.synthetic_event_log) $true 'synthetic event log marker'
  Assert-False $driverResult.real_windows_event_log_collected 'real Windows Event Log collection'
  Assert-Equal ([bool]$driverResult.evidence_return_e2e_pass) $true 'evidence_return_e2e_pass'
  Assert-False $driverResult.product_e2e_pass 'product_e2e_pass'
  Assert-False $driverResult.e2e_pass 'deprecated e2e_pass'
  Assert-False $driverResult.release_ready 'release_ready'
  Assert-False $driverResult.store_submission_allowed 'store_submission_allowed'
  Assert-False $driverResult.user_product_approval 'user_product_approval'
  Assert-False $driverResult.user_price_approval 'user_price_approval'

  $runId = [string]$driverResult.run_id
  if ($runId -notmatch '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}$') {
    throw 'SMOKE_ASSERT_FAILED: invalid run_id'
  }

  $requestId = [string]$driverResult.request_id
  $runRoot = Join-Path (Join-Path $StateRoot 'runs') $runId
  $manifestPath = Join-Path $runRoot 'manifest.json'
  $rawStdoutPath = Join-Path $runRoot 'stdout.log'
  $ackPath = Join-Path (Join-Path $StateRoot 'github-acks') "$runId.json"
  $queuePath = Join-Path (Join-Path $StateRoot 'retry-queue') "$runId.json"

  foreach ($requiredPath in @($manifestPath, $rawStdoutPath, $ackPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
      throw "SMOKE_ASSERT_FAILED: missing local receipt $requiredPath"
    }
  }
  if (Test-Path -LiteralPath $queuePath) {
    throw 'SMOKE_ASSERT_FAILED: retry entry remained after verified GitHub readback'
  }

  $fakeSecret = 'github_pat_' + 'SMOKEONLY' + '12345678901234567890'
  $rawStdout = Get-Content $rawStdoutPath -Raw
  if (-not $rawStdout.Contains($fakeSecret)) {
    throw 'SMOKE_ASSERT_FAILED: synthetic token marker was not preserved in raw local stdout'
  }

  $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
  Assert-Equal ([bool]$manifest.evidence_return_e2e_pass) $true 'manifest evidence_return_e2e_pass'
  Assert-False $manifest.product_e2e_pass 'manifest product_e2e_pass'
  Assert-False $manifest.e2e_pass 'manifest deprecated e2e_pass'
  Assert-False $manifest.release_ready 'manifest release_ready'
  Assert-False $manifest.store_submission_allowed 'manifest store_submission_allowed'

  $ack = Get-Content $ackPath -Raw | ConvertFrom-Json
  Assert-Equal $ack.status 'GITHUB_READBACK_VERIFIED' 'ack status'
  Assert-Equal $ack.request_id $requestId 'ack request_id'
  Assert-Equal $ack.source_sha $localHead 'ack source_sha'
  Assert-Equal $ack.branch $EvidenceBranch 'ack branch'
  if (-not $ack.path) {
    throw 'SMOKE_ASSERT_FAILED: acknowledgement has no remote evidence path'
  }

  # Independent second fetch: do not trust only the local acknowledgement.
  $remoteResponseLines = @(& $gh api "repos/$Repository/contents/$($ack.path)?ref=$EvidenceBranch")
  if ($LASTEXITCODE -ne 0 -or $remoteResponseLines.Count -eq 0) {
    throw 'SMOKE_ASSERT_FAILED: independent GitHub evidence fetch failed'
  }
  $remoteResponse = ($remoteResponseLines -join [Environment]::NewLine) | ConvertFrom-Json
  if ($remoteResponse.encoding -ne 'base64' -or -not $remoteResponse.content) {
    throw 'SMOKE_ASSERT_FAILED: GitHub evidence response was not base64 content'
  }

  $base64 = ([string]$remoteResponse.content) -replace '\s', ''
  $remoteBytes = [Convert]::FromBase64String($base64)
  $remoteText = [Text.Encoding]::UTF8.GetString($remoteBytes)
  $remoteEnvelope = $remoteText | ConvertFrom-Json
  Assert-Equal $remoteEnvelope.request_id $requestId 'remote request_id'
  Assert-Equal $remoteEnvelope.source_sha $localHead 'remote source_sha'
  Assert-Equal $remoteEnvelope.payload_sha256 $ack.payload_sha256 'remote payload_sha256'

  if ($remoteText.Contains($fakeSecret)) {
    throw 'SMOKE_ASSERT_FAILED: synthetic token marker leaked to GitHub evidence'
  }
  if (-not $remoteText.Contains('[REDACTED]')) {
    throw 'SMOKE_ASSERT_FAILED: expected redaction marker is absent from remote evidence'
  }

  [ordered]@{
    status = 'LOCAL_GITHUB_EVIDENCE_SMOKE_PASS'
    repository = $Repository
    authenticated_user = $login
    code_branch = $CodeBranch
    code_head = $localHead
    evidence_branch = $EvidenceBranch
    run_id = $runId
    request_id = $requestId
    github_ack = 'GITHUB_READBACK_VERIFIED'
    remote_path = [string]$ack.path
    synthetic_event_log = $true
    real_windows_event_log_returned = $false
    raw_local_secret_marker_present = $true
    remote_secret_marker_absent = $true
    evidence_return_e2e_pass = $true
    product_e2e_pass = $false
    e2e_pass = $false
    release_ready = $false
    store_submission_allowed = $false
    ai_enabled = [bool]$EnableAI
    ai_analysis_status = [string]$driverResult.ai_analysis_status
    scheduled_task_changes = $false
    store_operations = $false
    local_state_preserved = $StateRoot
  } | ConvertTo-Json -Depth 6
}
finally {
  Pop-Location
}
