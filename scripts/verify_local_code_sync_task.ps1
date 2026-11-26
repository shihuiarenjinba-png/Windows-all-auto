param(
  [string]$TaskName = 'WindowsAllAuto-Factory-Code-Sync',
  [string]$Receipt = "$env:LOCALAPPDATA\FactoryCodeMirror\state\task-run.json",
  [string]$OutputReceipt = "$env:LOCALAPPDATA\FactoryCodeMirror\state\task-scheduler-receipt.json"
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows required' }

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
if ($task.State -eq 'Running') { throw 'Task is still running; verify after completion' }
if ([int]$info.LastTaskResult -ne 0) { throw "Task Scheduler LastTaskResult is not zero: $($info.LastTaskResult)" }
if ($info.LastRunTime -eq [datetime]::MinValue) { throw 'Task Scheduler has no completed run' }
if (-not (Test-Path -LiteralPath $Receipt -PathType Leaf)) { throw 'Task receipt is missing' }

$data = Get-Content -LiteralPath $Receipt -Raw | ConvertFrom-Json
if ($data.status -ne 'PASS' -or $data.snapshots -ne 2 -or
    $data.exact_three_sha_tuple_verified -ne $true -or
    $data.idempotent_reuse_verified -ne $true) {
  throw 'Task receipt is not an exact, idempotent two-target PASS'
}
$started = [DateTimeOffset]::Parse($data.started_at_utc).UtcDateTime
$finished = [DateTimeOffset]::Parse($data.finished_at_utc).UtcDateTime
$lastRun = $info.LastRunTime.ToUniversalTime()
if ($lastRun -lt $started.AddMinutes(-2) -or $lastRun -gt $finished.AddMinutes(2)) {
  throw 'Task Scheduler LastRunTime does not correlate with the task receipt timestamps'
}

$expected = @{
  'signal-sprint' = @{
    request_id = 'game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78'
    repository = 'shihuiarenjinba-png/AI-Game-Factory'
    branch = 'codex/signal-sprint-frozen-source-ref-20261124'
    sha = '1a349faa41663c417c40710140a4d50c79b62b78'
  }
  'prism-route-3d' = @{
    request_id = '3d-prism-route-3d-b03ce7b16c3f'
    repository = 'shihuiarenjinba-png/3d-game-factory'
    branch = 'codex/prism-tower1-hud-clearance-fix-20261103'
    sha = 'b03ce7b16c3f75c04fe20fdda224c45849eeba0d'
  }
}
$products = @($data.products)
if ($products.Count -ne 2) { throw 'Unexpected product count in task receipt' }
foreach ($product in $products) {
  $want = $expected[[string]$product.slug]
  if ($null -eq $want) { throw "Unexpected product in task receipt: $($product.slug)" }
  if ($product.request_id -ne $want.request_id -or
      $product.source_repository -ne $want.repository -or
      $product.source_branch -ne $want.branch -or
      $product.source_sha -ne $want.sha -or
      $product.remote_head_sha -ne $want.sha -or
      $product.local_head_sha -ne $want.sha -or
      $product.status -ne 'REUSED_EXACT_SNAPSHOT') {
    throw "Exact source/remote/local receipt mismatch: $($product.slug)"
  }
  if ($product.three_sha_tuple.source_sha -ne $want.sha -or
      $product.three_sha_tuple.remote_branch_head_sha -ne $want.sha -or
      $product.three_sha_tuple.local_checkout_head_sha -ne $want.sha) {
    throw "Three-SHA tuple mismatch: $($product.slug)"
  }
}

$receiptPath = (Resolve-Path -LiteralPath $Receipt).Path
$receiptHash = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$parent = Split-Path -Parent $OutputReceipt
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result = [ordered]@{
  schema_version = 1
  status = 'TASK_SCHEDULER_EXECUTION_VERIFIED'
  task_name = $TaskName
  last_run_time_utc = $lastRun.ToString('o')
  last_task_result = [int]$info.LastTaskResult
  source_receipt_path = $receiptPath
  source_receipt_sha256 = $receiptHash
  sync_started_at_utc = $data.started_at_utc
  sync_finished_at_utc = $data.finished_at_utc
  snapshots = $products.Count
  exact_three_sha_tuple_verified = $true
  idempotent_reuse_verified = $true
  products = @($products | ForEach-Object {
    [ordered]@{
      slug = $_.slug
      request_id = $_.request_id
      source_repository = $_.source_repository
      source_branch = $_.source_branch
      source_sha = $_.source_sha
      remote_head_sha = $_.remote_head_sha
      local_head_sha = $_.local_head_sha
      three_sha_tuple = $_.three_sha_tuple
      status = $_.status
    }
  })
  verified_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
  product_code_executed = $false
  package_installed = $false
  identity_cas_applied = $false
  store_submission = $false
  certification = $false
  publish = $false
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputReceipt -Encoding UTF8
Write-Output "TASK_SCHEDULER_EXECUTION_VERIFIED: $OutputReceipt"
