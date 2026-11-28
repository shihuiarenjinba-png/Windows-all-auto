# Read-only Store status collector

Run from the Windows-all-auto repository root:

```powershell
python -m all_auto store status --product data-contract-auditor
```

The command only reads the registered job profile, searches the exact package
name under configured local package roots, hashes and parses the MSIX, checks
the registered GitHub Actions artifact when GitHub read access is available,
reads SQLite with `mode=ro` and the durable receipt files, then observes the
already-authenticated loopback CDP browser.

`STORE_PACKAGE_CACHE_ROOT` and `STORE_RECEIPT_ROOT` can point to local
evidence roots. By default, package discovery also searches the workspace's
`_runtime/store-fleet-sync` directory and the product's registered local cache.
No artifact is downloaded by `status`.

The browser collector never touches form controls or clicks Save. It binds the
exact Product ID, Product name, and existing Draft ID. If the exact Draft has
multiple open tabs, it returns `TAB_AMBIGUOUS`, inspects only their visible
read-only package state, and does not navigate. With exactly one target tab, it
uses a temporary tab to inspect section links and values so the existing tab
and its unsaved state are left untouched. A temporary-tab cleanup mismatch is
reported as `UNKNOWN`.

The report distinguishes local package SHA/Manifest proof from Partner Center
filename/version/validation evidence. Partner Center does not expose the
uploaded MSIX binary SHA in the observed page. A local file match is never
reported as proof that the same bytes are registered remotely.

The report is written to a unique file under `.store-workflow-runs/<product>`;
it does not alter SQLite, receipts, Partner Center, price, markets, certification,
or publication state.
