# Data Contract Auditor — Store listing draft (not yet approved)

Basis: source branch `codex/store-p0-data-contract-20261023`, source `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0`, plus `README.md`, `contract_auditor.py`, `validator.py`, `app.py`, `i18n.py`. Do not submit until a real UI capture, final artwork, formal version and owner approvals exist.

## Short description — Japanese

基準ファイルと今回のCSV/Excelを比較し、列やデータ品質の変化を確認できます。

## Short description — English

Compare baseline and current CSV/Excel files to review schema and data quality changes.

## Detailed description — Japanese

Data Contract Auditorは、基準ファイル（Baseline）と今回のファイル（Current）を読み取り専用で比較するWindows向けツールです。列の追加・削除、推定データ型、NULL率、数値範囲や平均値、カテゴリ値、指定キー列の重複率などの変化を確認できます。監査結果はJSONおよびCSVで保存し、基準ファイルから簡易Data Contract JSONを作成します。

結果は確認候補を示すもので、業務システムへの投入可否や完全なデータ品質を保証するものではありません。入力は上書きしません。CSV/Excelの対応範囲や検出結果を実運用データで確認してからご利用ください。

## Detailed description — English

Data Contract Auditor is a Windows tool for read-only comparison of a baseline file and a current CSV or Excel file. It reports changes such as added or removed columns, inferred data types, null rates, numeric ranges and mean shifts, category values, and duplicate rates for selected key columns. It saves JSON and CSV audit reports and can create a simple JSON data contract from the baseline.

Findings are items for review. They do not guarantee data quality or determine whether data is safe for production use. Input files are not overwritten. Verify compatibility and findings with representative data before relying on them operationally.

## Suggested fields — owner review required

- Category candidate: Productivity / Developer tools (confirm available Partner Center taxonomy).
- Attributes: local file processing; CSV and Excel comparison; JSON/CSV reports. Do not claim cloud sync, continuous monitoring, guaranteed compliance or automatic production approval.
- Age rating: complete the live IARC questionnaire from the actual app behavior; no age answer is pre-attested here.
- Price and markets: undecided. Preserve current Partner Center values until owner decides.
- Privacy: app reads user-selected local CSV/Excel files and writes reports to the selected output folder. Verify telemetry/network behavior before making a no-data-collection declaration. A reachable privacy policy URL and support URL are still required.

## Real screenshots and icons

Not yet captured or approved. Required real UI captures: initial Baseline/Current selection, comparison findings, filtered results, and generated output. Use synthetic data, record source SHA and EXE SHA, and capture from the actual running Windows UI. No mock screenshots or placeholder logos are approved as Store assets.

## Missing before Store submission

- Formal approved package version and manifest languages.
- Real Windows GUI launch, bilingual, DPI, close/relaunch and screenshot QA.
- Final owner-approved Store logo/icon assets and hashes.
- Real screenshots from exact release source.
- Owner confirmation of price and markets.
- Verified privacy policy and support URLs plus privacy behavior evidence.
- Completed live Properties and IARC answers.
- Exact formal MSIX hash and Partner Center upload/analysis/Save/reload receipt.
