# 15分間隔 GitHub → Windows ローカル検査キュー

## 役割と現状
- GitHub Actions: 7,22,37,52分 (UTC)、15分刻み。遅延・欠落の可能性あり。
- 対象: ops/portfolio.json に登録された app/game 7製品 (100件まで拡張可能)。
- 入力: GitHub所有リポジトリ・実ブランチ・正確なsource commit SHA。
- 出力: report.json / report.md / local-qa-queue.json (GitHub Actions Artifact)。
- Windowsの検査候補はsource SHAに一致したCI成功が確認できたものだけ。
- 出力は検査依頼であり、MSIX認定・Windows実機動作・販売許可ではない。
- 現在はWindows-data / Windows-checker / Windows-Automatorへの実subprocess接続は未完成。
- 現時点でGitHub ActionsがWindowsローカルPCを制御することはない。ローカル側は別の信頼済みWorkerが必要。

## 既存製品の自動化の流れ（達成前の設計）
1. GitHubで市場調査、開発、CI確認。結果をSHA固定。
2. GitHub上のWindows Runnerでビルド・アプリ起動・複数画面の操作・スクリーンショット撮影を実施。
3. Windows-dataで実MSIX、Identity、SHA256を収集。
4. Windows-checkerで実パッケージ、掲載画像、申請内容を監査。
5. Windows-all-autoで結果照合、SQLiteジョブ台帳、UNKNOWN再送停止。
6. Windows-Automatorで実際のPartner Centerログイン済み環境を使う。まずDry Runを記録。
7. 重要な情報を人が事前承認した対象だけ、下書きアップロードの最終実証を実施。

現在の15分ワークフローは **1の一部（ソース・CI監視）とローカルへの検査キュー生成** のみ実装。上記2～7を成功したと偽ってはならない。

## アプリ・ゲームの固定ルール
- type=app と type=game の必須フィールド、画像、カテゴリ、年齢区分は別契約で扱う。
- 汎用Yes/No回答は実際のPartner Center設問を正確に照合できた場合のみテンプレ化する。
- 価格・国／地域・年齢区分・プライバシー情報・安全性の宣言は根拠なしに確定しない。
- セキュリティ9項目: personal_data, external_accounts, external_communication, user_files,
  camera, microphone, location, restricted_capabilities, non_microsoft_driver_service。
- 人手確認にはパッケージSHA256・承認者・承認時刻を紐付ける。パッケージ差し替えで確認を破棄。
- 同じStore ID/Versionの再送禁止。UNKNOWNは自動再送しない。
- 自動アップロード成功、下書き保存、審査提出、審査合格、公開は異なる状態。

## GitHub トークンについて
- このリポジトリのGITHUB_TOKENは他のprivate repositoryにアクセスできない場合がある。
- 権限不足や存在しないブランチはHOLD。非公開製品の監視には最小権限GitHub Appのreadトークンを追加する。
- 秘密情報をIssue、Artifact、ログ、READMEへ書き出してはいけない。

## 現状検証
- Windows-all-auto既存のテストと追加schedulerテストをGitHub Actionsで実行。
- 手動のオフライン例: python -m all_auto.scheduler --inventory ops/portfolio.json --out reports/local --offline
  オフラインでは成功判定を出さず、全製品HOLDになる。
- GitHub Actions Artifactの実体、Runnerログ、ソースSHA、実機GUI、MSIX、Partner Centerの記録がない限り、販売へ自動昇格しない。
- 設定や新しいRepoを追加した場合はテストしてからops/portfolio.jsonへ追加する。

## 明日までに残る未完成の作業
- CIからWindows RunnerでのGUI実操作・スクリーンショット自動化と成果物の回収
- Windows-data / Checker / Automatorの実行アダプタとschema固定
- WindowsローカルWorkerによる署名・ソース・アプリ／ゲーム分岐
- Partner Center現行画面での新規・更新、価格、セキュリティ確認と下書き保存の実証
- エラー時の再開、認証期限、重複登録／UNKNOWN状態の実機テスト
- 本番アップロード・Submit for certificationは、事前に対象ごとの確定情報と承認を確認してから解禁

これらが未達の場合は「準備完了」と表示しない。
