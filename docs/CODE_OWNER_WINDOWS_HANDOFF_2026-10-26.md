# Windows-all-auto — Windows実機コード担当引継ぎ（2026-10-26）

## 現況（必ず引継ぎ時に最新HEADと比較）
- 対象: https://github.com/shihuiarenjinba-png/Windows-all-auto
- 作業ブランチ: codex/windows-all-auto-integration-20261026。main / release直接変更・マージ禁止。
- 総合開発仕様: https://github.com/shihuiarenjinba-png/Windows-all-auto/issues/1
- 初回調査: 新リポジトリは空/default main。今回work branchから開始。
- 本体: all_auto/core.py（オフライン多製品検査）、all_auto/__main__.py（CLI）、all_auto/gui.py（日英・検証画面）、all_auto/contracts.py（3上流の読取JSON契約）、all_auto/queue.py（SQLite/WAL・衝突検査）、tests/（58件の自動テスト）、.github/workflows/offline-qa.yml（Windows/Linux CI）。
- 2026-10-26追補: Store ID衝突時の再検査によるHOLD/BLOCKED→READY抜け道を修正。大文字小文字違いのStore IDも衝突として扱う。Windows/Ubuntuで58件PASS: https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/40273761799 。
- 上流確認時HEAD: Windows-data `664b9afcbed63539b89f594892d831d97b9d4118` / Windows-checker `7780647efd80dea6b2ebc629172cfb2c743a9dcb` / Windows-Automator `24eb7e8c4da9d048f4036ac5a941a79699eac704`。実行時pinと実subprocess接続は未実装。
- **制限**: ここまでは事前検証コードのみ。実Microsoft Store操作、MSIXの実ビルド、Partner Centerの下書き保存、実機インストールは成功未確認。結果が「READY_FOR_WINDOWS_QA」であってもStore合格ではない。

## 役割分担 — 既存3Repoの実装を使う
1. Windows-data : https://github.com/shihuiarenjinba-png/Windows-data / codex/msix-auto-build-identity-20261025。github source→Windowsビルド→MSIX→Identity/SHA-256確認。レポートは msix-identity-report.json と windows-checker-submission.json を含む。収集時にStore/Publisher/Versionは推測しない。
2. Windows-checker（private）: https://github.com/shihuiarenjinba-png/Windows-checker / codex/store-readiness-checker-20261025。batch_audit.pyの本当の入力・出力契約に従う。BLOCKED / NEEDS_REVIEW / READY_CANDIDATE_NOT_CERTIFIEDの意味を守る。Windows-checker自体は販売アプリにしない。
3. Windows-Automator : https://github.com/shihuiarenjinba-png/Windows-Automator / codex/store-submission-automation-20261026。固定ルール、Ollama候補、安全確認、下書き計画がある。Partner Centerのlive selectorと実保存は未検証。store_manager/partner_center.pyはDry Run中心。
4. Windows-all-auto : キュー・証拠の照合・手動確認のゲート・状態遷移・再開・全体結果を管理する。上流コードを複製しない。

## ローカル開始コマンド（Windows）
git clone https://github.com/shihuiarenjinba-png/Windows-all-auto.git
cd Windows-all-auto
git fetch origin
git switch codex/windows-all-auto-integration-20261026
py -3.12 -m unittest discover -s tests -v
py -3.12 -m compileall -q all_auto
py -3.12 -m all_auto gui
py -3.12 -m all_auto preflight --manifest examples/products.example.json --out qa/reports

※サンプル入力には架空情報を入れている。正常にHOLDを返すことが期待結果。外部アップロードは行わない。

## 実装P0（ここからコード担当）
- 上流3ツールのCLIとレポート実物を読み、正規化adapterを設計。schema_versionを明示し、未対応形式やレポートhash不一致はHOLD/BLOCKED。任意PythonコードをJSONから実行する設計にしない。
- Windows-dataのWindowsビルド→Windows-checker判定→Windows-Automatorの本番下書き操作までを固定した順序でオーケストレーションする。ただし個別工程の検証証拠なしには次工程へ進めない。
- SQLite WALでジョブ状態、プロセスlease、再開情報、同じStore製品/パッケージ/コミットを誤再送しないfingerprintを保存する。UNKNOWNは自動再送しない。個別HOLD/ERRORで他製品を継続、ログイン認証切れなら全体停止。
- GUIを製品とファイル/自動入力と要確認/夜間キュー/結果と設定の4画面へ改善。ドラッグ選択・複数選択・パッケージファイル参照、固定アプリ/ゲームプリセット、AI候補を表示。実装されない操作を使えるように見せない。
- プライバシー/外部ログイン/通信/ファイルアクセス/カメラ/マイク/位置/Restricted Capability/ドライバー・Service等の確認を必須。human confirmed=trueとpackage SHAの一致を実行ゲートにする。パッケージ差替時は承認を無効化。
- 商品価格・市場・新規/更新・Store ID・Publisher・Versionは実根拠に基づく入力のみ。AIによる推測なし。IARCはPartner Center現行設問と選択肢のexact matchだけを認める。
- JSON/CSV/Markdownレポート。1件の成功・失敗と複数件の総数、下書き保存成功、失敗、HOLD、UNKNOWNを一画面で出す。DRAFT_SAVED、SUBMITTED、CERTIFIED、PUBLISHEDは混同禁止。

## 実機P1（ユーザーが別途コード担当へ委任する工程）
- 親リポジトリ、main/作業ref/HEADの記録。開始/終了headおよび権限を検査。
- app 1件とgame 1件、完全に所有/許可される既存下書きでPartner CenterのDOMとセレクターを確認。role/label/exact match。座標クリック禁止、固定sleepだけの判定禁止。
- Dry Run→本人明示承認→下書き入力→実MSIXアップロード→Microsoftのvalidation完了→Save draftのサーバー状態を読み戻す。最終Submit for certification/公開は禁止。
- 新しい有料MSIXと既存の有料更新での公式APIの適用可否を区分し、未対応は画面操作。Submission APIとCLIと画面操作を1件の申請中に無検証で切り替えない。
- 1件/複数件（10件等）の成功/失敗/HOLD/UNKNOWNを確認。通信断、認証失効、途中キャンセル、再起動、二重登録、価格差替、画像不足、MSIX破損、Identity不一致を再現。
- Windows GUI 1024×768/1280×720、JP/EN、Windows Defender・App Control、ログ秘密情報未出力を確認。セキュリティ設定変更・証明書の無断登録なし。
- 各元Repoに修正が必要な場合はそれぞれの作業ブランチへ修正。main/releaseへの直接変更禁止。

## 安全なAPI経路
Microsoft Store Developer CLIのMSIXアプリ更新は公式文書上無料製品のみサポートの注記がある。有料販売対象を自動サポート済み扱いにしない。MSI/EXE Submission APIは既存製品/初回申請の前提条件に注意。UWP Submission APIは価格バージョンやAPIで作った申請のUI編集制約などがあり、経路選択を個別確認する。

## 最終報告で必要
- Repo/branch/source HEAD/work HEAD/差分/PR、使用した上流3RepoのSHA。
- 本物のテスト件数とPASS/FAIL、Actions URLとjobs/steps、artifactとSHA-256。
- 実MSIX/Screenshot/Identity/Partner Center product IDの突合結果。
- 下書きSave/アップロードValidationの画面または公式APIの証跡と失敗時ログ。
- UIキャプチャ、セキュリティ回答、出荷未達(HOLD/UNKNOWN)一覧、次の修正。
- READMEの「動く」の意味を自動検査PASS/実機PASS/申請成功に分ける。

**今回の到達ライン: 安全な統合コード・文書・自動テストをGitHubへ置き、実機・Microsoft画面テストをコード担当へ引き渡す。販売/本番提出は一切実行しない。**
