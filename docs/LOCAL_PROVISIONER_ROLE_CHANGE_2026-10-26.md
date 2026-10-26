# ローカル担当・変更指示：3 Provisioner は新規リポジトリ作成から「Package + Identity 往復」へ変更
2026-10-26 / **この文書が旧「リポジトリ自動作成」指示より優先** / 確認済み範囲のみ実装

## 新しい責務
Factoryで**すでに決まっている製品名・slug・製品タイプ・GitHub source repository/branch/commit SHA**を安全な入力として受け取り、対象ソースを正確なSHAで取得し、ローカルWindowsでWindowsビルド/必要なQA/MSIX候補生成、パッケージ内のIdentityと署名状態・SHA-256を収集する。必要であれば**認証済みPartner Center**で製品を登録・名前を予約して**公式Store ID、Identity Name、Publisher**を取得する。取得した公式値のみを元製品のFactory作業ブランチに返却し、GitHub Windows Runner側で正式IdentityによるStore用MSIXを再生成する。その後Windows-all-autoのArtifact搬送へ接続する。

**新規リポジトリを大量生成する機能は今回の標準動作から除外。** 以前の provisioner.py は名前の提案のみ（create_allowed=false）のまま維持可能だが、今回の完了要件ではない。Factory本体、Windows-all-autoの他工程、3D生産タイマーをローカル担当が直接変更しない。

- APP: AI-App-Factory → Repository-Provisioner-app → AI-App-Factory
- GAME: AI-Game-Factory → Repository-Provisioner-game → AI-Game-Factory
- GAME_3D: 3d-game-factory → Repository-Provisioner-3D → 3d-game-factory
- 共通の認証済みGitHub返却ルータは Windows-all-auto/all_auto/identity_route.py および identity_commit.py。ユーザーによるStore操作の真正性はJSONのoperator_verifiedだけでは保証されない。

## 正しい順序
1. Factoryから機械可読ジョブを受信。ジョブの所有者と発行元はallowlistとAPI上の最新値により検証。request_idの重複をローカル台帳で抑止。同じsource SHA以外は取り違え禁止。
2. GitHubの対象work branchをHEAD照合した上で、**detached exact source SHA**でソースを取得。ジョブ指定の不審な任意URL、任意コマンドは実行しない。ソースを未検証で実機起動しない。
3. 対応種別のパッケージをWindowsでビルド。APP/GAMEは既存build workflowを優先。3DはGodot project.godotを検証し、Windows export・3d-build-qaの構築を別に必要とする。ソースをGitHubに戻す必要はない。重いbuildやモデル素材をGit履歴へコミットしない。
4. Windows EXE/QA_UNSIGNED MSIX候補の成否、ZIP manifest Identity、PFN/SID（計算可能な場合）、署名の有無、正確なsource SHA、package SHA256とサイズを記録。**MSIX内のIdentityから新規Store IDを算出したと扱ってはならない。** Store登録前に正式Identityが無い場合、承認済みQA専用Identityでのテストのみ可能。なければQA実行物とIdentity工程はHOLD。
5. Microsoft Partner Centerで製品を予約/登録するには認証、操作権限、名称衝突対策とユーザーの事前許可が必要。必要ならログイン済みローカルブラウザで読取り、公式 Store ID、Identity Name、Publisher、選択したversionを人間が照合する。未確認値の自動補完は禁止。CAPTCHA/MFA回避禁止。
6. 公式Identityの証跡（Partner CenterページURL、認証済み担当者ID、確認日時、request_id）を保管し、Windows-all-auto のidentity_route / identity_commitに渡す。**GitHubのbranch HEADに対するexpected SHAのcompare-and-swapが必要**。元製品slug、タイプ、manifest/3D projectとの一致確認をする。既存approved-identity.jsonを自動上書きしない。
7. 返却先：
   - APP: shihuiarenjinba-png/AI-App-Factory, branch codex/factory-autoloop-20261026, path products/<slug>/store/approved-identity.json
   - GAME: shihuiarenjinba-png/AI-Game-Factory, branch codex/factory-autoloop-20261026, 同一相対パス
   - GAME_3D: shihuiarenjinba-png/3d-game-factory, branch codex/3d-factory-bootstrap-20261026, 同一相対パス（3D専用ルータ/manifest照合が実装・テスト済みの場合のみ、そうでなければHOLD）
8. GitHub Actions Windows Runnerが正式Package Identityに合わせてMSIX候補を再生成し、Package Identity/SHA照合→Factory artifact→Windows-all-auto intake→ローカルQAへ搬送。3Dには別途Godot export/MSIX実装が必要。Storeの正式提出とは分ける。

## 受信JSON v1.0（例：DRY_RUN）
\`\`\`json
{
  "schema_version":"1.0",
  "request_id":"factory-20261026-demo-01",
  "product_type":"GAME_3D",
  "source_factory":"3d-game-factory",
  "source_repository":"shihuiarenjinba-png/3d-game-factory",
  "source_branch":"codex/3d-factory-bootstrap-20261026",
  "source_sha":"0000000000000000000000000000000000000000",
  "slug":"experimental-3d-demo",
  "display_name":"Experimental 3D Demo",
  "target_owner":"shihuiarenjinba-png",
  "dry_run":true,
  "requested_actions":["BUILD_WINDOWS","INSPECT_PACKAGE","LOOKUP_OFFICIAL_IDENTITY","PROPOSE_GITHUB_RETURN"]
}
\`\`\`
SHA/slug/名前は説明用の架空値であり実投入不可。名前だけの入力で任意のrepositoryを推測しない。実際の元ソース・承認されたStore登録と一致する場合だけ進む。

## 返却JSON v1.0（概要）
\`\`\`json
{
 "schema_version":"1.0",
 "request_id":"factory-20261026-demo-01",
 "product_type":"GAME_3D",
 "status":"HOLD",
 "source_repository":"shihuiarenjinba-png/3d-game-factory",
 "source_sha":"0000000000000000000000000000000000000000",
 "package":{"status":"NOT_BUILT","sha256":null,"artifact_url":null,"package_identity":null},
 "official_identity":{"status":"UNVERIFIED","store_id":null,"name":null,"publisher":null,"version":null,"official_evidence_url":null},
 "github_return":{"status":"NOT_APPLIED","repository":"shihuiarenjinba-png/3d-game-factory","branch":"codex/3d-factory-bootstrap-20261026","path":"products/experimental-3d-demo/store/approved-identity.json","commit_sha":null},
 "errors":["No verified Microsoft Store product identity; do not invent it"],
 "next_stage":"WAIT_FOR_OFFICIAL_IDENTITY"
}
\`\`\`
公開情報とパッケージ解析情報は別々に記録。返却欄の「成功」は実際にGitHubが返したcommit SHAを確認した場合だけ。既存のidentity_route/identity_commit入力は schema_version=1/type=app|game/slug/expected_head_sha/official_evidence_url/operator_verified/verified_by/identity を使用。今回のv1.0受信契約から厳密なアダプタを挟む。GAME_3D用は専用検証を追加してから使用する。

## セキュリティと試験
- DRY_RUNはPackage build、Store新規登録、GitHub書込を一切しない。外部GitHub read-onlyの検証も明示設定時のみ。
- GitHub認証がない、Identity未取得、名前衝突、branch HEAD変更、パッケージIdentity不一致、既存のIdentityファイル、Store操作権限不足、未完成3D exportは個別のHOLD/CONFLICT/FAILEDにする。
- タイムアウト後は公式サイト/リポジトリ再照会、Idempotency key=request_id+source_sha、HOLD時の無制限retry禁止。
- APP/GAME/GAME_3Dの型隔離、同名衝突、他Factoryへの誤返却、SHA mismatch、dry-run副作用、公式ID偽装、GitHub API 401/403/404/422/429、通信断・タイムアウト、成果物SHA変化、パッケージなし、3D大型素材/無許可コマンド実行をユニット/モックテスト。
- Windows実ビルド/MSIX作成と、Partner Center登録成功と、正しいGitHub branchへの返却をそれぞれ別工程の実績として報告。**テストPASSだけで完結と宣言しない。**
- トークン、Cookie、認証情報や証明書秘密鍵、個人向けセキュリティ入力をGitに保存しない。
- 3つのProvisionerについて docs/LOCAL_PROVISIONER_HANDOFF.md に最新のリポジトリSHA/差分/CI/DRY_RUN/ローカル実機/実API試験/正しい返却先/未達を記載。
