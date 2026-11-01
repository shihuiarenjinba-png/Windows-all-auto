# Accounting receipt/OCR and JP month-end PDF Windows QA gate

`validate_accounting_receipt_pdf_gate(job, read_reviewed_evidence=...)` is a **fail-closed evidence contract** for four country-specific accounting SKUs. It is separate from accounting arithmetic, country/Store availability, signed MSIX, Windows-checker, and the final human GUI/install review. It does not install software, read Partner Center secrets, post transactions, or submit a Store product.

The independent physical-Windows reviewer must bind each observation to exact source SHA, request ID, Factory build HEAD, real MSIX SHA-256, Checker report SHA-256, Store ID, market/locale/currency. A queue JSON is **not** an independent reviewer. The callback must verify these claims from actual local evidence and retain private receipt contents only on the local PC.

## Receipt/OCR batch

At least two inputs with consistent accepted/review/failed counts. No unconfirmed transaction may be posted. Source images survive, individual failures do not erase other queue items, and the queue survives restart. If OCR exists, eight high-risk fixtures are mandatory: low-resolution, skewed, mixed tax rates, refund, multi-item, ambiguous vendor (Amazon/retailers), mixed personal/business, and duplicate image. Each is REVIEW_REQUIRED with confidence, original-image link and no auto-post. Each of the eight high-risk test cases must have a distinct original-image SHA-256; reusing the same image for every named case is rejected as `HOLD_RECEIPT_PDF_OCR_FIXTURE_REUSED`. The `duplicate_image` case must separately demonstrate its duplicate within that case's test evidence. If OCR is not implemented, case evidence must be empty and the UI must not claim it exists. Accuracy percentages without measured benchmarks are prohibited.

## JP month-end pack

For both JP SKUs, the reviewer must verify HTML/CSV/JSON output and Edge headless PDF export from the same source. Evidence includes SHA-256 for each file, Japanese A4 visual inspection, totals matching across HTML/CSV/JSON/PDF, monthly-to-yearly reconciliation, original evidence references, unprocessed receipts, and no deletion or replacement of electronic source transactions. A PDF header alone does **not** prove readable Japanese/A4 rendering. Render and inspect PDF pages and compare monetary values to source data. US SKUs cannot inherit JP PDF evidence.

## Boundaries

This module validates the **shape and correlation** of independently supplied observations, not underlying bytes or physical Windows authenticity. Current tests use fabricated hashes and mock callbacks, not real receipts, OCR, PDF rendering, Store packages or Windows execution. A byte-level adapter, signed MSIX, actual Checker, GUI/install, accounting engine parity and human sign-off remain separate HOLD gates. Even validated evidence returns `e2e_pass=false` and `store_submission=NOT_PERFORMED`.

Run targeted regression: `python -m unittest tests.test_accounting_receipt_pdf_gate -v`.
