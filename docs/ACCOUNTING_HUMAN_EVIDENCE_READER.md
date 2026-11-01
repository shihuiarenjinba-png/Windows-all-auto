# Accounting Windows screenshot evidence — read-only byte verifier

Stacked Draft on PR #109. This adapter is **not** a GUI test runner or a
certification decision. It verifies actual local evidence bytes rather than
trusting screenshot hashes copied from a queue. No Partner Center, Store,
CAS, package build, installation or submission action is performed.

After independent Windows GUI/install review, place an `evidence.json`
document conforming to `scripts/accounting_human_qa_gate.py` in a trusted
local folder and exactly five different screenshots in
`screenshots/<scenario>.png`. Each screenshot must be a complete PNG with
valid chunk CRC and exactly 1024×768 dimensions. The screenshot SHA-256
in each scenario must match its local file bytes.

A trusted caller passes exact local package and Checker report file paths:

```python
from functools import partial
from scripts.accounting_human_evidence_reader import read_local_accounting_human_evidence
from scripts.accounting_human_qa_gate import validate_accounting_human_qa

reader = partial(
    read_local_accounting_human_evidence,
    evidence_root=r"C:\qa\accounting\human-evidence",
    package_path=r"C:\qa\accounting\verified.msix",
    checker_report_path=r"C:\qa\accounting\checker.json",
)
result = validate_accounting_human_qa(job, fetch_reviewed_windows_evidence=reader)
assert result["e2e_pass"] is False
```

The reader checks actual MSIX ZIP header and streaming SHA-256, Checker
report SHA-256, screenshot PNG chunk CRCs **and bounded zlib pixel-stream
decoding** (expected scanline count and filter bytes), exact image dimensions,
distinct screenshot digests, symlink avoidance, duplicate JSON keys,
nonfinite JSON rejection and bounded file sizes. The reviewed screenshot
format is non-interlaced 8-bit RGB or RGBA; unsupported PNG encodings fail
closed rather than passing on chunk CRCs alone. Consecutive split IDAT
chunks and standard ancillary metadata are supported. A decoded PNG is
still not proof of an actual Windows screenshot or its visual contents. All exceptions are
sanitized HOLD codes. The existing pure contract then checks exact
request/source/build/product/market and five beginner workflow assertions.

**Trust boundary:** A PNG with valid bytes is not proof that it was captured
from a physical Windows machine. A matching package digest is not proof
of signature validity or installation. A matching Checker report digest is
not proof that Checker ran or that its report is authentic. The human
reviewer and real Windows/engine/install evidence remain independent
requirements. Mock fixtures do not advance GUI_QA_PASS or E2E_PASS.
The accounting four-SKU PRE_IDENTITY, MARKET_FIT, Version, tax/asset,
country-scope and signed-package gates remain HOLD until independently
proven. Do not register a scheduled production task based on this adapter.

Offline regression:
`python -m unittest tests.test_accounting_human_evidence_reader -v`
