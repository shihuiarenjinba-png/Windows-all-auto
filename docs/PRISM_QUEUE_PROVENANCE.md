# Prism historical queue provenance

The Identity-return commit is an unverified candidate, not an approved CAS receipt. Its claimed GitHub queue digest must be replayed against the historical central ledger at its claimed commit SHA. A mismatched digest is a fail-closed HOLD. The historical product-creation flag is read for comparison only and never authorizes another product creation.

Run the read-only worker `python -m scripts.prism_queue_provenance_audit` from an independent checkout with `--central-checkout`, `--source-checkout`, and `--manual-reference`. Keep original source SHA pinned, do not weaken remote HEAD checks, and do not treat CI, manual reference, or a one-file Identity commit as authenticated browser capture, local source sync, CAS approval, package PASS, or E2E PASS.

Next: reconcile historical queue receipt provenance; then independently verify physical Windows capture and explicit Provisioner CAS approval before any package build. No Store submission, merge, or main/release changes.
