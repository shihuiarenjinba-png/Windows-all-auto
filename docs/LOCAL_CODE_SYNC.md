# Local Factory source snapshot sync

Purpose: prove that exact Factory product source can be retrieved from GitHub onto
Windows for local Codex/QA work without modifying a development checkout.

The worker consumes a JSON object with `jobs` (or `items`) containing
`repository`, `branch`, `source_sha`, `slug`, and optional `request_id`.
It allowlists `shihuiarenjinba-png/*`, requires a `codex/*` branch, verifies the
remote branch HEAD equals the immutable 40-character SHA, then creates:

`<root>/<repository-name>/<first12(source_sha)>`

Each directory is a detached exact-SHA snapshot. Existing exact clean snapshots
are reused. Dirty, linked/junction, wrong-origin or wrong-SHA directories HOLD
instead of being reset. Product code is not executed.

Example:

```powershell
py -3 -m scripts.local_code_sync `
  --manifest "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\pre-identity-jobs.json" `
  --root "$env:LOCALAPPDATA\FactoryCodeMirror" `
  --receipt "$env:LOCALAPPDATA\FactoryCodeMirror\state\last-code-sync.json"
```

For the initial smoke test, `tests/fixtures/local_code_sync_targets.json` pins
three current real Factory products: Offline Notes Canary, Signal Sprint, and
Prism Route 3D. The Windows CI workflow downloads all three, verifies exact HEAD
SHA, then repeats the sync and requires idempotent reuse.

The optional Task Scheduler installer runs the same sync every 15 minutes with
`MultipleInstances IgnoreNew` and a 14-minute limit. It requires explicit
operator installation and existing `gh auth login`; it never stores GitHub
tokens in the manifest/receipt.

This worker is source retrieval only. It does not merge, edit source, run the
product, install packages, perform Identity CAS, build MSIX/GDK packages, or
submit to Microsoft Store. Codex should create a separate writable worktree or
working copy if edits are required; the managed snapshot is the immutable source
reference.
