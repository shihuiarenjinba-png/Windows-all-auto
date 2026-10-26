# Windows-all-auto — Microsoft Store提出工程の統合コーディネーター

WindowsアプリやゲームをMicrosoft Storeへ登録するときの **GitHub → Windowsビルド/MSIX → 提出前監査 → Partner Center下書き登録 → 結果集計** をつなぐ内部運用ツールです。一般ユーザーのPC操作自動化アプリではありません。

## 現在の到達点（2026-10-26）
- GitHubの作業ブランチのみで開発（main/release直接変更なし）。
- オフライン事前検証コア、日英切替の試験的GUI、CLI、SQLiteの安全なキュー台帳を実装。
- **自動テスト75件 / Windows・Ubuntuの両方でPASS**（オフライン検査のみ）。CI: https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/40284671809
- Windows-data / Windows-checker / Windows-Automator の読取専用JSON契約アダプタを追加済み。未知schema/statusはfail-closedで停止し、Windows-Automatorの現行 DONE は DRY_RUN_DONE として扱います。
- **未完成/未検証**: 3ツールのsubprocess実行アダプタ、Windows-Automatorの正式ライブ接続、Partner CenterのDOMセレクタ、MSIX実アップロード、保存成功確認、Windows実機GUI QA。これはStore登録の完成を意味しません。
- 全てのオンライン/高影響操作は未実装・停止状態。Submit for certification、公開、名前予約、Store商品ID/Identity推測は禁止。

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
**販売・本番申請はNO-GO**。本ツールは内部運用専用であり、一般消費者向け有料販売商品ではありません。GUI実機操作、3ツール実subprocess接続、MSIX内容と実ビルドの正規検証、Partner Center下書き保存は未確認です。**Windowsコード担当の継続開発・実機QAへの引継ぎのみ可**です。

- [販売移行ゲート・監査結果](docs/SALES_RELEASE_GATE_2026-10-26.md)

## 実機引継ぎ
- [統合完全版の仕様 Issue #1](https://github.com/shihuiarenjinba-png/Windows-all-auto/issues/1)
- [Windows担当の詳細手順](docs/CODE_OWNER_WINDOWS_HANDOFF_2026-10-26.md)

Windows実機/Partner Centerの実操作で正規の確認が取れるまで本番販売・提出はHOLDです。アプリ/ゲーム別固定ルールを用い、**セキュリティ系宣言・価格・Identity・Store Product IDは人間が根拠付きで確定**してください。
