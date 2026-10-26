# 3 Factory → Windows-all-auto 運転開始チェックリスト (2026-10-26)

## 役割・周期
- AI-App-Factory: 毎時04/19/34/49分UTC、15分周期で research→build→improve1→improve2→next research。Work branch codex/factory-autoloop-20261026。
- AI-Game-Factory: 毎時11/26/41/56分UTC、同様。Work branch codex/factory-autoloop-20261026。
- Windows-all-auto Codex修正: 毎時01/16/31/46分UTC、専用ブランチ codex/factory-bridge-maintenance-20261026。Codexが生成したパッチは独立jobで全テストしてから保存。
- Windows-all-auto MSIX受信: 毎時12/27/42/57分UTC、FACTORY_READ_TOKENを使用。3Dも受信元に対応したが、3Dは未だMSIXを作らない。
- 3d-game-factory: 毎日UTC18:15にチェック、直近の合格プロトタイプから120時間未満なら生成しない。Godot 4の別工程。Work branch codex/3d-factory-bootstrap-20261026。
- Local PC: opt-inした15分タスクが受信済みWindows QA Artifactsを取得する。上限20件・2GiB。MSIXインストールや申請はしない。

## 開始条件 (GitHub Actionsの仕様)
- AI-App-Factory PR #2, AI-Game-Factory PR #2, 3d-game-factory PR #2がmainにマージされていること。現在Draftのため未マージ。
- 各FactoryにGitHub Actions secret OPENAI_API_KEY。外部のOpenAI API課金枠を別途設定。Plus加入だけではAPI呼出し不可。
- 通常両Factoryにリポジトリ変数 FACTORY_ENABLED=true。必要に応じ MAX_AUTONOMOUS_STAGES_PER_DAY=16〜32等。
- 3D側に FACTORY_3D_ENABLED=true。
- Windows-all-auto側に MAINTENANCE_ENABLED=true と OPENAI_API_KEY。Codex修正は最大24コミット/24時間・3失敗で停止。
- Windows-all-auto側に他3 FactoryのActions/Artifact読取権限を持つ FACTORY_READ_TOKEN。GitHub tokenをチャットやログに記入しない。
- Windows-all-auto本体は、現時点のデフォルトブランチ codex/windows-all-auto-integration-20261026 上にスケジュールを書込済み。
- GitHub Actions設定でワークフロー権限、停止状態、支出上限、スケジュール遅延を確認。

## 厳密に分ける合格判定
- 単体テストPASS ≠ 15分定期実行PASS
- scheduleイベント履歴が2回以上15分間隔で発生し、その双方でCodex API生成→audit→GitHub work branch保存まで成功した場合に限り自動開発PASS。
- MSIX候補はStore由来Identity・画像などの承認がない限り作らない。source repo→Windows MSIX Artifacts→Windows-all-auto intake→local QAダウンロードの1件E2Eの成功を別途要求。
- Godot 3Dは当面ユーザー実験候補で、Windows export/MSIX/販売への無条件自動投入は禁止。
- Windows GUIスクリーンショット、署名・WACK、権利・価格・無料承認・セキュリティ全項目、Partner Center提出は独立の最終ゲート。
- Microsoft Storeの審査合格は購入後の動作や売上の保証ではない。

## 市場調査の限界
GitHub open issueは需要の弱いシグナルに過ぎない。Microsoft Store/Steam等の公開情報、レビュー件数、需要の独立確認、利用規約・ライセンスを調べる必要がある。AIが「必ず売れる」「売上確定」と断定することは禁止。

## ユーザーへ表示する結果
時刻、source HEAD、work branch HEAD、Actions run、生成件数、MSIX個数とsha256、Windows GUIテスト結果、QA/HOLD/UNKNOWN、Store下書き/提出件数、費用見積・使用量（取得できる場合）を表示する。
