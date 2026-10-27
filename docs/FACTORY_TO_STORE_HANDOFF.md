# Factory → Windows-all-auto → ローカルWindows 受け渡し設計

## 目標
アプリとゲームのFactoryが開発・テストを完了したら、MSIX候補・証拠・SHAをGitHub Actions Artifactとして渡す。
Windows-all-autoが自動取得・検証し、ローカルPCが引き取り、実機QA・商品登録工程へ移す。
**リポジトリにMSIXをコミットしない。ローカルにもHOLD品や同一パッケージを無制限保存しない。**

## 実装済みのデータ経路

1. Factory: Windows Runnerの .github/workflows/msix-export.yml。
   products/<slug>/main.py と公式確認済み approved-identity.json、PNG画像がそろった時だけ
   tools/build_windows_msix.py がPyInstaller→MakeAppxで unsigned QA MSIXを作る。
2. Factory: tools/msix_handoff.py が package.msix + handoff.json を生成。
   名前 factory-msix-handoff-<slug> のGitHub Actions Artifactとして最大5日保存。
3. Windows-all-auto: .github/workflows/factory-msix-intake.yml が毎時12,27,42,57分 (UTC) に確認。
   Factory用read-only tokenで新着artifactをダウンロードし、
   all_auto/handoff_bridge.py がMSIX内のIdentity、SHA、出所/ソースSHAを照合。
   ops/factory_handoff_ledger.json のArtifact IDで再取込を防止。
4. 受信合格品だけを verified-msix-local-qa-<run> として2日保存。
5. Windowsローカル: scripts/local_handoff_pull.py が gh CLI経由で受信済みArtifactを取得。
   複数Artifactの取りこぼし対策、同一SHAの重複回避、20パッケージ/2GiB上限。
   scripts/register_local_qa_pull.ps1 を所有者が明示実行した場合のみ
   タスクスケジューラに15分ごとの取得・Windows-checker処理を設定。
   同時実行はTask Schedulerとローカルlockの両方で拒否し、同じpackage SHAと
   checker versionの組合せはローカル台帳により再実行しない。
6. checker完了だけでは保存先を移動しない。`scripts/local_qa_archive.py` は、
   同じrequest/source/packageに結びついたchecker receiptとGUI/install PASS receiptが
   両方ある場合だけ、所有者の明示実行でローカルarchiveへ移動する。

## 初回に必要な設定

- Windows-all-auto の Settings → Secrets and variables → Actions:
  FACTORY_READ_TOKEN (2つのFactoryだけに actions:read を許可した fine-grained token)。
  チャットやリポジトリへトークン文字列を書かない。
- Factoryの開発ブランチに実際の products/<slug>/main.py と
  products/<slug>/manifest.json が存在すること。
- 製品Identityが確定後、products/<slug>/store/approved-identity.json に
  reviewed:true / source:"partner_center" / store_id / name / publisher / version を記入し、
  対象の製品の画像資産 StoreLogo.png, Square150.png, Square44.png を入れる。
  これは実際にPartner Centerから確認した値のみ。推測・テスト用IDの転用は禁止。
- ローカルWindowsで gh CLIログイン後、
  python -m scripts.local_periodic_qa --inbox "<QA inbox>" --checker "<Windows-checker checkout>" --reports "<QA reports>" --state-root "<local state>"
  を実行。無人実行を希望する場合だけ PowerShell登録スクリプトを実行する。

## 未完成で必ず止める工程

**現在のFactoryは依然として15分ごとの連続開発が稼働していない。**
製品コードの自動生成を本流へ反映するループ、実際のモデル生成実験、
商品IDの新規予約、認証済みMSIX署名、実機インストール、UI操作/スクリーンショット、
価格設定、セキュリティ確認、正式なMicrosoft Store提出は別工程。

新規製品のStore Identityが未確定なら先に新製品名予約・ID確認が必要。
本来は「Factoryで製品企画/コード生成 → Windows-all-autoで新製品登録とIdentity取得
→ Factoryへ承認済みIdentity返信 → Windows MSIX生成 → 受信 → ローカルQA
→ Windows-checker → Windows-Automator → 正式申請」という二段階経路が必要。
Signal Sprint用のlocal-only Identity workerは実装済みだが、正式Identityが無い現在は
`WAITING_OFFICIAL_IDENTITY / EXTERNAL_IDENTITY` が正しい停止位置である。
Partner Center値の真正性を推測・自動認定せず、未登録製品はMSIXビルドをHOLDする。

## 品質・経費・権限

- QA_UNSIGNEDはStoreへの実提出可能状態を意味しない。署名/WACK/Store審査は別途必要。
- ZIPとしてのMSIXフォーマット検査はインストール・起動成功の証明ではない。
- 完全なStore入力情報とセキュリティの本人確認なしで送信してはならない。
- 商品生成/ローカル取得は原則AI不要。Codexは開発・改修時だけ。Ollamaは任意。
- Actionsには実行時間/Artifact保管コスト、APIには利用料・制限がある。無限無料ではない。
- 15分GitHub scheduleはbest effort。遅延・欠落がある。
- 大量投入時、Artifact/製品のSHA・状態を管理し、UNKNOWNは自動再送しない。

## 実証状況の区別

「Python契約テストPASS」→「GitHub Actionsスクリプト起動PASS」→
「初めて実MSIXをFactoryから転送し中央のArtifactへ保存PASS」→
「ローカル実機MSIX動作/画像取得PASS」→「Partner Center下書き保存PASS」→
「審査提出PASS」を別々に報告する。下流を推測でPASSへ昇格させない。
