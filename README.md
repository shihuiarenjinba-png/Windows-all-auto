# Windows-all-auto

Windows向けの **Microsoft Store申請工程を管理する内部運用ツール**。一般ユーザーのWindows操作自動化アプリではありません。

## 開発状況

現在は**安全な統合基盤の開発版**です。Microsoft Storeへの実アップロード、下書き保存、本番審査提出、公開を完了したわけではありません。実機でのPartner Center検証はコード担当に引き継ぎます。

### 役割

- Windows-data: GitHub source/build/MSIX Identity/SHA-256収集
- Windows-checker (private): 事前監査。BLOCKED / NEEDS_REVIEW / READY_CANDIDATE_NOT_CERTIFIED
- Windows-Automator: アプリ・ゲームの固定プリセット、必須セキュリティ確認、Partner Centerの下書き入力
- **Windows-all-auto (このRepo)**: 製品キュー、証拠の受渡し、権限・Identity照合、安全ゲート、再実行防止、総合集計

## 安全上の境界

ライブStore書込みは既定で常時無効。このRepoは、他ツールが成功したと**偽装するダミー結果**を出さない。Partner Center実画面の未検証selector、Microsoft Store Product ID/Publisher/PFN/Versionの推測を禁止。Partner Center Submit for certification/公開/新規製品予約を自動で行わない。未知の結果はUNKNOWN/HOLD扱い。

## 仕様・作業指示

[統合設計・実機コード担当引継ぎ Issue #1](https://github.com/shihuiarenjinba-png/Windows-all-auto/issues/1)

Windows環境に移る前に、ソース・自動テストを確認すること。CIがあってもパッケージの動作や審査通過を保証しません。
