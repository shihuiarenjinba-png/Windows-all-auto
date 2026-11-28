# Windows-all-auto — Microsoft Store提出工程の統合コーディネーター

WindowsアプリやゲームをMicrosoft Storeへ登録するときの **GitHub → Windowsビルド/MSIX → 提出前監査 → Partner Center下書き登録 → 結果集計** をつなぐ内部運用ツールです。一般ユーザーのPC操作自動化アプリではありません。

## 現在の到達点（2026-11-28）
- GitHubの作業ブランチのみで開発（main/release直接変更なし）。
- オフライン事前検証コア、日英切替GUI、CLI、SQLiteの安全なキュー台帳に加え、Product-key Store workflow、Overview起点のナビゲーション、共通フォーム入力、SHA固定Artifact取得、ローカルpackage archiveを実装。
- 最新統合コミットは `c8a0121cf09ae09efd4c4d4ef4330476584c6e71`。ローカル回帰は **452件PASS / 5件SKIP**。PR #166のWindows・Ubuntu CIも成功し、Playwright/Chromiumのフォーム統合テストが実行されました。CI成功はPartner Center実アップロードやMSIX runtime QAを意味しません。
- 2026-11-28に、Windows実行環境の読み取り専用MSIX診断、アーカイブ再取得、終了コード判定、外部バックアップ承認ゲート、Partner Center読み取り観測、同じ値のフォーム再Save抑止を追加し、CI成功済みです。
- Windows-data / Windows-checker / Windows-Automator の読取専用JSON契約アダプタを追加済み。未知schema/statusはfail-closedで停止し、Windows-Automatorの `DONE` は引き続き `DRY_RUN_DONE` として扱います。
- Windows-Automator live v2 の `DRAFT_SAVED` は、execution_mode、Save後の再読込、package validation/section completion、全必須section、証拠、Store ID / package SHA / source SHA / Identity / Versionの期待値一致をすべて確認した場合だけ受理します。Submit/Certified/Publishedのclaimは拒否します。
- Windows-Automator結果の `restricted_capability`、説明のconfirmed/saved、`certification_gate` を中央表示用に正規化します。Capability重複や、未確認なのに保存済みという矛盾はfail-closedです。
- **未完成/未検証**: 3ツールのsubprocess実行アダプタ、Actionsから接続する実Partner Center session、DCA exact MSIXのInstall/Launch runtime QA、Partner Center Packages Save。DCAの候補はSHA/Manifest固定済みですが、unsigned状態でローカルInstallがAccess Denied、EXE launchも未確認のためruntime QAはPASSではありません。
- Package upload adapterは下記のとおり実装済みですが、live uploadは製品ごとのSHA・Identity・Draft・認可・認証session gateが全てPASSするまで停止。Submit for certification、公開、名前予約、Store商品ID/Identity推測は禁止。

## Cloud Auto Uploader（2026-11-23）
- 過去のPartner Center実操作証跡を再利用し、認証済みPlaywright/CDPブラウザーによる既存Draft `Packages` upload → Microsoft analysis → Save → Overview reload/reconcileを実装。
- 既知の成功画面マップを `uploader/partner_center_browser.py` に移植。対象Draft URLを優先する同一selectorをBrowser Doctorと実行経路で共有し、CDP接続・認証・Draft行照合が終わるまでupload試行を予約しない。設定ファイルにはProduct ID、Submission ID、MSIXのGitHub repo/ref/path、期待SHA、Identity/Publisher/Version/Architectureを保持する。
- 実行例: `python -m uploader.run --product data-contract-auditor`（dry-run）、承認済みかつ凍結SHA・認証済みCDP sessionがある場合だけ `--execute`。
- GitHub Actionsはworkflow dispatch / `repository_dispatch: store-package-ready`から実行可能。CDP endpointはGitHub Secret `PARTNER_CENTER_CDP_URL`。ログに接続URLを出さない。ログイン、MFA、CAPTCHAは自動化しない。
- Data Contract Auditorは指定source SHAのSHA固定済みunsigned候補と既存Draft向けowner upload approvalを持つ。package固有のインストール/実行QAは未確認であり、CDP Doctorが`READY_*`になり、Product/Draftの実read-only照合を通るまでLive writeは停止する。QA_UNSIGNED packageは対象にしない。
- CertificationとPublishの操作コードはない。公開実績とPackage Draft保存実績を混同しない。
- 詳細は [Cloud Auto Uploader runbook](docs/automation/CLOUD_AUTO_UPLOADER.md) と [browser route teacher receipt](ops/cloud_uploader_browser_route_teacher_v1.json) を参照。

### Product-key Store command and exact-package gate（2026-11-28）
- 統合入口: `python -m all_auto store run --product data-contract-auditor`。製品設定、Artifact/local MSIX、Source evidence、Owner decisionsを集め、保存済みの承認範囲だけ実行します。DCAは現在 `PLAN_ONLY` のままです。
- `store run`、`store apply --section packages`、`uploader.run --execute`、内部の`process_job`は共通のexact-package QA・Product/Draft承認・Device family承認ゲートを通ります。どの入口からも未承認のQAを迂回できません。
- CDP画面遷移はApps and games Overviewから開始し、製品とDraftの表示リンクをたどります。Identity直リンクでの移動は使用しません。
- CI Artifactをローカルに長期保管するときは `python -m all_auto store archive --product data-contract-auditor` を使用します。SHA-addressedな追加専用アーカイブとReceiptを作ります。Artifact expiry、外部バックアップ、公開Releaseを含む保管方針は [Store archive and live gates](docs/automation/STORE_LOCAL_ARCHIVE_AND_LIVE_GATES.md) を参照してください。

ローカルCDPの読み取り専用診断: `python scripts/partner_center_browser_doctor.py --product data-contract-auditor --cdp-url http://127.0.0.1:9223`。`READY_EXACT_DRAFT_TAB` のときだけ、設定済みのProduct/Draft routeが一意です。Browser Doctorはページ遷移、クリック、ファイル選択、Saveを行いません。

## 関連リポジトリ（役割を分離）
| 内部ツール | 業務 | 運用上の位置付け |
| --- | --- | --- |
| [Windows-data](https://github.com/shihuiarenjinba-png/Windows-data/tree/codex/msix-auto-build-identity-20261025) | GitHubソース照合・EXE/MSIXビルド・実MSIX IdentityとSHA-256 | ビルド担当 |
| [Windows-checker](https://github.com/shihuiarenjinba-png/Windows-checker/tree/codex/store-readiness-checker-20261025) (private) | MSIX/掲載画像/提出情報のBLOCKED/NEEDS_REVIEW/READY_CANDIDATE_NOT_CERTIFIED | 提出前監査・**販売アプリ化は不要** |
| [Windows-Automator](https://github.com/shihuiarenjinba-png/Windows-Automator/tree/codex/store-submission-automation-20261026) | 定型回答・セキュリティ確認・Partner Center下書き入力 | 申請担当、現時点ではDry Run中心 |
| **Windows-all-auto** | 一括処理の指揮、証拠照合、キュー、レポート、再送禁止 | 統合担当 |

## 起動（ソース段階）
Python 3.12以上を想定。現在のオフライン検査に追加PyPIライブラリは不要です。

    python -m unittest discover -s tests -v
    python -m compileall -q all_auto
    python -m all_auto gui
    python -m all_auto preflight --manifest examples/products.example.json --out qa/results

サンプルは架空であり、正常系のPASSサンプルではありません。HOLD/BLOCKEDになるのが正しい結果です。本物の提出前診断には、承認済みパッケージ・SHA・Windows-dataとWindows-checkerの本物のレポート・ユーザーが確認したセキュリティ項目を指定してください。

### ステータスの意味
- BLOCKED: 不一致・不正なパッケージ情報など、先に修正すべき問題。
- HOLD: 根拠や明示確認が不足。
- READY_FOR_WINDOWS_QA: **オフライン証拠検証を通過したWindows担当者の確認候補**。Windows Checkerの公式認定でも、Microsoft Store認定でもありません。
- PENDING_OPERATOR: SQLite台帳でオペレーターのWindows確認待ち。**遠隔操作は行っていない**。
- UNKNOWN: オペレーターが記録した結果不明状態。**自動再送禁止**。

オフラインCLIは summary.json / summary.md / audit-<id>.json を書き出します。件数は入力製品から算出し、架空の審査合格件数は生成しません。all_auto/queue.pyのSQLite台帳は安全な中断・再開の基盤ですが、実アップロード・再送照合の完全実装はコード担当が受け持ちます。

## 販売・実機引継ぎの判定
**Store Draft完成・本番申請はNO-GO**。このリポジトリは内部オーケストレーションツールです。DCAの正確なMSIXとManifestは確認済みですが、Install/Launchの原因は未解決で、Partner Center各セクションは読み取り観測のみ、Packages保存も未実施です。3ツールの実subprocess接続とActions上のPartner Center sessionも未検証です。

- [販売移行ゲート・監査結果](docs/SALES_RELEASE_GATE_2026-10-26.md)

## 実機引継ぎ
- [統合完全版の仕様 Issue #1](https://github.com/shihuiarenjinba-png/Windows-all-auto/issues/1)
- [Windows担当の詳細手順](docs/CODE_OWNER_WINDOWS_HANDOFF_2026-10-26.md)

Windows実機/Partner Centerの実操作で正規の確認が取れるまで本番販売・提出はHOLDです。アプリ/ゲーム別固定ルールを用い、**セキュリティ系宣言・価格・Identity・Store Product IDは人間が根拠付きで確定**してください。

### 2026-11-28実機精査・安全な再開
- Exact DCA MSIXは静的SHA/Manifest一致を再確認できるが、未署名でローカルInstall/Launchは未実証。scripts/diagnose_msix_runtime.ps1はACL、署名、MOTW、AppXイベント、AppLocker/CiTool、OS/VM情報を読み取り専用で採取し、インストール・起動を行わない。原因が未確定ならruntime QAは未PASSのまま保つ。
- Partner CenterのOverviewからProperties、Store listings、Pricing、Age ratings、Submission Options、Packagesを読み取り観測した。観測は読み取り専用で、UI mapのverifiedや本番書き込み許可は変更しない。全レポートはdocs/automation/PARTNER_CENTER_DCA_READ_ONLY_OBSERVATION_20261128.md。
- Store form engineは要求値と現在値が一致する場合にALREADY_MATCHESを返し、入力・Saveを省略する。ファイル入力はブラウザから保存値を復元できないため、明示的なsaved_labelsが一致する場合だけ重複を避ける。
- store runはローカル承認済みアーカイブからSHA/製品結合を再検証して作業キャッシュへコピー可能。外部バックアップは製品別の保存先承認がない限り転送しない。
