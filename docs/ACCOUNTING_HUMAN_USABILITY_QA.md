# Accounting beginner usability QA — reviewed evidence contract

This is a **Draft-only, pure fail-closed contract**, not a live physical Windows test and not a product certification. It is separate from market fit, accounting arithmetic/engine parity, tax and asset fixtures, signed MSIX, Windows-checker, Partner Center country availability and final Store submission. It does not access Partner Center or operate the local PC.

## Four independently bound products

- jp-freelance-ledger: JP / ja-JP / JPY
- jp-bookkeeping-desk: JP / ja-JP / JPY
- us-freelance-ledger: US / en-US / USD
- us-bookkeeping-desk: US / en-US / USD

The validate_accounting_human_qa function rejects missing exact source SHA, request ID, product SKU, market/locale/currency, Factory build HEAD, real MSIX digest, Checker report digest or Store ID. It rejects a missing independent reader, mismatched product evidence, malformed scenario records and non-boolean safety assertions. A handoff or queue JSON **cannot** assert a PASS.

## Five required physical Windows scenarios at 1024 × 768

1. Search for 家賃 / office rent. The beginner can see account candidates and when to use them.
2. Search for パソコン / computer equipment. Both expense and fixed-asset possibilities and a clear review-required state are visible.
3. Open an invoice / accounts receivable flow. The user can see which journal and ledger it affects.
4. Enter an owner-paid / personal-card expense. The UI explains the owner transaction and does not silently post an unconfirmed entry.
5. Import multiple receipts. Queue count, isolated failure and possible duplicates are visible. A single bad image must not silently erase the rest of the batch.

Every scenario must have independently reviewed physical-Windows steps, observed behavior, a screenshot SHA-256, beginner completion and the named behavior assertions. Advanced accounts must be hidden from the beginner's primary screen. JP additionally requires an understandable explanation of the five simplified books and double-entry workflow.

If OCR is implemented, the evidence must demonstrate confidence, original image reference, manual confirmation before posting, duplicate candidate detection and partial-batch failure preservation. If OCR is not implemented, the product must not claim that it exists. If parallel books are implemented, the primary book must remain unchanged. These are evidence requirements, **not proof** that an OCR engine or accounting backend is correct.

## Read-only local byte checks (Draft PR #112)

`read_local_accounting_human_evidence` hashes the actual package, Checker JSON and five distinct 1024×768 PNG files. It rejects symlink paths, duplicate JSON keys, corrupt/undecodable PNG data, wrong hashes and reused screenshots. The package check additionally opens the **same already-hashed file descriptor** as ZIP, rejects malformed central directories, unsafe or case-colliding entry paths, encrypted/symlink entries, and requires bounded parseable AppxManifest.xml, AppxBlockMap.xml and [Content_Types].xml with plausible manifest Identity fields. A matching SHA and a four-byte `PK` header alone do not establish a package.

This is only a structural MSIX plausibility check. **A ZIP containing synthetic XML can pass it**; the result is not a Microsoft signature verification, an authenticated Store Identity/version match, a real Windows-checker result or evidence that the application starts. Independently validate signature trust, embedded Identity, actual Checker output and physical Windows GUI/install/engine correctness before any sale-ready decision. Offline test fixtures intentionally do not claim these properties.

## Trust and completion boundary

The caller must supply an independently reviewed Windows evidence reader. It must inspect the actual application and bind screenshots and observed behavior to the exact package and Checker report. The current implementation only validates the **shape and correlation of its output**. It cannot independently authenticate a screenshot, physical Windows host, reviewer or calculations; the callback is a trust boundary. Mock callbacks in tests are not product evidence.

Even successful contract validation returns HUMAN_USABILITY_EVIDENCE_CONTRACT_VALIDATED with e2e_pass=false. A separate real Windows GUI/install review, engine parity and persistence verification, signed package check and reviewer decision are mandatory. The existing accounting PACKAGE intake gate remains fail-closed and is **not** relaxed by this contract. No production dispatcher is wired to treat this result as E2E approval.

## Test coverage and next implementation

Run: python -m unittest tests.test_accounting_human_qa_gate -v

Tests check all four SKUs, five scenarios, cross-country contamination, missing reader, false boolean, missing screenshot, unsafe OCR, JP ledger explanation, parallel-book isolation and sanitized reader failure. The test uses fabricated hashes and a mock callback; it is a schema regression only.

The next physical QA adapter should collect actual immutable screenshot files and hashes, an independently reviewed source/package/Checker binding and structured per-receipt queue counts. The engine parity runner must separately compare journal, ledger, trial balance, P/L, B/S, asset roll-forward and reconciliation from the same persisted source, and test independent parallel/tax/management books if present. Until these are observed, all four SKUs remain **HOLD** and must not enter Store submission or be marked GUI_QA_PASS / E2E_PASS.
