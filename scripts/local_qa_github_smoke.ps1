# Real GitHub round-trip smoke test for the local QA evidence path.
# This script never installs packages, edits product source, changes Store state,
# registers Scheduled Tasks, or treats evidence-return success as product E2E.
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

  $login = (& $gh api user --jq '.login').Trim()
  if ($LASTEXITCODE -ne 0 -or -not $login) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: unable to read authenticated GitHub user'
  }

  $currentBranch = (& $git branch --show-current).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $currentBranch) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: detached HEAD or branch detection failed'
  }
  if (-not $CodeBranch) {
    $CodeBranch = $currentBranch
  }
  Assert-Equal $currentBranch $CodeBranch 'current branch'

  if ($EvidenceBranch -notmatch '^codex/local-qa-evidence-[A-Za-z0-9._/-]+$') {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: EvidenceBranch must use the codex/local-qa-evidence-* namespace'
  }
  if ($EvidenceBranch -eq $CodeBranch) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: evidence branch must be separate from the code branch'
  }

  $origin = (& $git remote get-url origin).Trim()
  if ($LASTEXITCODE -ne 0 -or $origin -notmatch [regex]::Escape($Repository)) {
    throw "LOCAL_GITHUB_SMOKE_HOLD: origin does not match $Repository"
  }

  $dirty = @(& $git status --porcelain)
  if ($LASTEXITCODE -ne 0) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: git status failed'
  }
  if ($dirty.Count -gt 0) {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: working tree must be clean before a provenance smoke test'
  }

  $localHead = (& $git rev-parse HEAD).Trim().ToLowerInvariant()
  $remoteHead = (& $gh api "repos/$Repository/git/ref/heads/$CodeBranch" --jq '.object.sha').Trim().ToLowerInvariant()
  if ($LASTEXITCODE -ne 0 -or $remoteHead -notmatch '^[0-9a-f]{40}$') {
    throw 'LOCAL_GITHUB_SMOKE_HOLD: unable to resolve remote code branch HEAD'
  }
  Assert-Equal $localHead $remoteHead 'local/remote code HEAD'

  $pythonVersion = (& $py -3 -c 'import platform; print(platform.python_version())').Trim()
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
    store_operations = $false
    scheduled_task_changes = $false
  }

  if (-not $AllowGitHubWrite) {
    $preflight | ConvertTo-Json -Depth 5
    Write-Host 'Preflight only. Re-run with -AllowGitHubWrite for the real sanitized GitHub round-trip.'
    return
  }

  New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $fixtureRoot = Join-Path $StateRoot "fixture-$stamp"
  $trustedRoot = Join-Path $fixtureRoot 'trusted'
  $jobRoot = Join-Path $fixtureRoot 'jobs'
  New-Item -ItemType Directory -Force -Path $trustedRoot, $jobRoot | Out-Null

  # Deliberately fake token-like text proves raw-local/sanitized-remote separation.
  # It is not a credential.
  $fakeSecret = 'github_pat_SMOKEONLY12345678901234567890'
  $fixturePath = Join-Path $trustedRoot 'smoke_fixture.py'
  @"
import sys
print("LOCAL_QA_GITHUB_SMOKE_OK")
print("Authorization: Bearer $fakeSecret")
print("LOCAL_QA_GITHUB_SMOKE_STDERR", file=sys.stderr)
sys.exit(0)
"@ | Set-Content -Path $fixturePath -Encoding utf8 -NoNewline

  $artifactSha = (Get-FileHash -Algorithm SHA256 $fixturePath).Hash.ToLowerInvariant()
  $requestId = "local-smoke-$stamp"

  $job = [ordered]@{
    request_id = $requestId
    product_type = 'APP'
    source_repository = $Repository
    source_branch = $CodeBranch
    source_sha = $localHead
    artifact_sha256 = $artifactSha
    test_suite_version = 'local-github-smoke-v1'
    slug = 'windows-all-auto-local-smoke'
  }
  $profile = [ordered]@{
    allowed_executables = @($py)
    command = @($py, '-3', $fixturePath)
    cwd = $trustedRoot
    timeout_seconds = 60
    expected = @{ exit_code = 0 }
    gui_test = $false
  }

  $jobPath = Join-Path $jobRoot 'job.json'
  $profilePath = Join-Path $trustedRoot 'profile.json'
  $job | ConvertTo-Json -Depth 8 | Set-Content -Path $jobPath -Encoding utf8
  $profile | ConvertTo-Json -Depth 8 | Set-Content -Path $profilePath -Encoding utf8

  $workerStdout = Join-Path $fixtureRoot 'worker.stdout.json'
  $workerStderr = Join-Path $fixtureRoot 'worker.stderr.txt'
  $workerArgs = @(
    '-3', '-m', 'scripts.local_qa_evidence_worker',
    '--state-root', $StateRoot,
    '--job', $jobPath,
    '--profile', $profilePath,
    '--github-repository', $Repository,
    '--github-branch', $EvidenceBranch,
    '--github-base-ref', $CodeBranch
  )
  if ($EnableAI) {
    $workerArgs += @('--enable-ai-analysis', '--ai-model', 'windows-qa-analyst')
  }

  & $py @workerArgs 1> $workerStdout 2> $workerStderr
  $workerExit = $LASTEXITCODE
  if ($workerExit -ne 0) {
    $stderrText = if (Test-Path $workerStderr) { Get-Content $workerStderr -Raw } else { '' }
    throw "LOCAL_GITHUB_SMOKE_HOLD: evidence worker exit=$workerExit; $stderrText"
  }

  $workerResult = Get-Content $workerStdout -Raw | ConvertFrom-Json
  Assert-Equal $workerResult.test_status 'TEST_PASS' 'worker test_status'
  Assert-Equal ([bool]$workerResult.evidence_return_e2e_pass) $true 'evidence_return_e2e_pass'
  Assert-False $workerResult.product_e2e_pass 'product_e2e_pass'
  Assert-False $workerResult.e2e_pass 'deprecated e2e_pass'
  Assert-False $workerResult.release_ready 'release_ready'
  Assert-False $workerResult.store_submission_allowed 'store_submission_allowed'
  Assert-False $workerResult.user_product_approval 'user_product_approval'
  Assert-False $workerResult.user_price_approval 'user_price_approval'

  $runId = [string]$workerResult.run_id
  if ($runId -notmatch '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}$') {
    throw 'SMOKE_ASSERT_FAILED: invalid run_id'
  }

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
    throw 'SMOKE_ASSERT_FAILED: retry queue entry remained after verified GitHub readback'
  }

  $rawStdout = Get-Content $rawStdoutPath -Raw
  if (-not $rawStdout.Contains($fakeSecret)) {
    throw 'SMOKE_ASSERT_FAILED: synthetic raw-local secret marker was not preserved locally'
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

  # Independent second fetch verifies that the same sanitized object is actually
  # readable through GitHub, rather than trusting only the worker's local ack.
  $remoteResponseText = & $gh api "repos/$Repository/contents/$($ack.path)?ref=$EvidenceBranch"
  if ($LASTEXITCODE -ne 0 -or -not $remoteResponseText) {
    throw 'SMOKE_ASSERT_FAILED: independent GitHub evidence fetch failed'
  }
  $remoteResponse = $remoteResponseText | ConvertFrom-Json
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
    throw 'SMOKE_ASSERT_FAILED: synthetic secret marker leaked to GitHub evidence'
  }
  if (-not $remoteText.Contains('[REDACTED]')) {
    throw 'SMOKE_ASSERT_FAILED: sanitized GitHub evidence did not contain the expected redaction marker'
  }

  $final = [ordered]@{
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
    raw_local_secret_marker_present = $true
    remote_secret_marker_absent = $true
    evidence_return_e2e_pass = $true
    product_e2e_pass = $false
    e2e_pass = $false
    release_ready = $false
    store_submission_allowed = $false
    ai_enabled = [bool]$EnableAI
    ai_analysis_status = [string]$workerResult.ai_analysis_status
    scheduled_task_changes = $false
    store_operations = $false
    local_state_preserved = $StateRoot
  }
  $final | ConvertTo-Json -Depth 6
}
finally {
  Pop-Location
}
