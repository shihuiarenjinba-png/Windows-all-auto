# Local periodic QA safety contract

This path consumes only verified APP/GAME MSIX handoff artifacts. It does not
generate products, process GAME_3D, install packages, sign, submit, or claim E2E
PASS.

## Queue and concurrency

- GitHub Actions Artifact is the durable backlog (30-day retention on the
  intake workflow); local Windows is a bounded work queue.
- Local limits remain 20 packages and 2 GiB. Full capacity returns
  `HOLD_LOCAL_CAPACITY` and leaves the remote Artifact available.
- `scripts.local_periodic_qa` holds a non-blocking local file lock for the
  entire pull + checker cycle. The opt-in scheduler also uses
  `MultipleInstances IgnoreNew` and a 14-minute execution limit on a 15-minute
  trigger.
- `local-qa-ledger.json` keys request ID, product type, immutable source SHA,
  Factory build HEAD, package SHA-256 and Windows-checker version. The exact
  same tuple is skipped; changed bytes or checker code runs again.

## Evidence boundary

`scripts.local_checker_queue` writes a preflight receipt with
`local_gui_qa=NOT_RUN`, `e2e_pass=false` and no Store submission authority.
Packages remain in the inbox. Explicit `scripts.local_qa_archive` accepts an
archive move only after both a correlated checker report and a separately
recorded GUI/install receipt with `status=PASS`, `install_status=PASS` and
`gui_launch_status=PASS`. Even that local archive receipt does not claim Store
submission or overall E2E PASS.

The Windows-checker PR #2 GitHub job currently has a failure with no steps
reported. Treat that as `CI_INFRA` unless new evidence proves a code failure;
local tests and product QA are reported separately.
