# Windows-all-auto — 販売移行ゲート / 追加監査（2026-10-26）

## 結論

- **一般消費者向け有料販売：NO-GO**
- **Microsoft Store申請の本番自動運用：NO-GO**
- **Windowsコード担当への継続開発・実機QA引継ぎ：GO（未達の証拠を引き継ぐ意味のみ）**

このリポジトリの本来の用途は、アプリ・ゲームをMicrosoft Storeへ登録する**所有者用の内部運用システム**であり、一般PCユーザー向けの有料自動化アプリではない（Issue #1）。実機・公式提出画面・Store APIの検証を伴わないオフラインPASSを、販売合格と混同しない。

## 確認済み情報

- Repo: `shihuiarenjinba-png/Windows-all-auto`
- Work branch: `codex/windows-all-auto-integration-20261026`
- 本監査開始HEAD: `6bc5582bf9e00ffc947c276aa10813e158b2ca29`
- 本監査コード修正HEAD: `4faadc2cfe960dcc8842c2467b3e6a43676def55`
- CI: https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/40284671809
- CI実行: ubuntu-latest、windows-latestでPython 3.12 compile+unittest、**75件PASS**、0 failure。
- PR: 監査開始時に確認できたopen PRは0。main/releaseへの書込み・マージなし。
- 上流pin参照: Windows-data `664b9afcbed63539b89f594892d831d97b9d4118` / Windows-checker `7780647efd80dea6b2ebc629172cfb2c743a9dcb` / Windows-Automator `24eb7e8c4da9d048f4036ac5a941a79699eac704`。
- 上流への変更なし。Partner CenterやMicrosoft APIへの書込みなし。

## 今回の修正・テスト

1. 複数製品preflightで、Store IDの大文字小文字違いを同一として重複BLOCK。
2. 不正型・unhashable Store IDを与えても一括実行がクラッシュしないよう防御。
3. 監査ステータスの自己申告だけで通さず、Windows-checker実レポートJSONのschema / verdict / product_type / pending reviews / BLOCK findings / MSIX SHA / manifest identityを照合。
4. Windows-data実レポートJSONのschema / READY状態 / HOLD不在 / repo / source SHA / Store ID / package SHA / identityを照合。
5. 改ざんではなく「矛盾を含むがSHAは更新されている」証拠に対しても、HOLD/BLOCKEDへ確実に戻す回帰テストを追加。
6. 既存の複数製品テストの証拠が別製品用Store IDを流用していたことを検出し、テストfixtureを製品単位の証拠に修正。

オフラインfixtureは模擬MSIXバイト列と模擬証拠を使用。**MSIXの正当性や署名が実証済みという意味ではない**。現行レポートSHAは、同じmanifestが提供した値との照合であり、独立した公式証拠の認証・出所保証ではない。

## 販売可否：購入者視点

現GUIはJSON manifest選択→オフライン検査→結果表示が主用途。修正済みの一覧表示、日英、動作無効化は良いが、一般消費者が購入価格を支払う実用価値を証明するには足りない。

- アプリ/ゲームのGUI選択・直接編集、固定プリセット、複数製品の簡易投入が未完成。
- 画面の実機スクリーンショット・1024×768/1280×720・操作導線・キーボード操作・高DPI・エラー表示を未確認。
- 実行キューは安全にロックされているが、主要業務の自動化は動作しない。
- 実Store登録の下書き保存や時間短縮を立証していない。
- 見た目だけでなく業務成果の証拠が必要。現状では「一般ユーザーに売れる」とは言えない。

## 本番移行を止める未達ゲート

| 優先 | 項目 | 判定 |
| --- | --- | --- |
| P0 | Windows-data / Windows-checker / Windows-Automatorを実CLIで起動、exit code / timeout / report SHAを永続証拠へ照合 | HOLD |
| P0 | MSIX実ファイルのManifest / Identity / 署名・パッケージ種類をWindows-data/Checkerの実物で検証 | HOLD |
| P0 | source branch/HEADとartifactの独立追跡および担当者承認・再送防止の実E2E | HOLD |
| P0 | Windows実機でGUI表示・主要操作・エラー回復・画面サイズ2条件 | HOLD |
| P1 | Partner Centerに所有済みapp/gameでDry Run→明示承認→パッケージValidation→Save draft→読み戻し | HOLD |
| P1 | 通信断 / ログイン切れ / UNKNOWN / 再起動 / 多製品キューで重複送信しないこと | HOLD |
| P1 | GUI入力、セキュリティ全項目、価格・対象市場・IARC実設問の人間確認 | HOLD |
| P1 | JSON/CSV/Markdown、成功/失敗/HOLD/UNKNOWNの最終集計、証拠とログの完全性 | HOLD |
| 販売 | ツール自体を製品化する意思決定・価値検証・独立した商用MSIX QA | 対象外・NO-GO |

現行Windows-checkerは単体MSIX中心。MSIXUPLOAD / MSIXBUNDLE等を実検査済みとして扱わない。価格0円/有料更新などの申請経路・仕様差も個別確認が必要。

## コード担当への次の順序

1. 本監査後の対象branch最新HEADを再取得し、ソース・ジョブ台帳を固定。
2. Windows-data → Checker → AutomatorのCLI実コマンドと実report fixtureを使ったsubprocess adapterを作成し、タイムアウト/非0 exit/契約変更をfail-closedにする。
3. Windows実機GUI（通常権限、1024×768・1280×720、JP/EN、複数製品、HOLD/ERROR/UNKNOWN）を画面収録と操作ログで検証。
4. 本人が所有する既存下書きだけでDry Runから開始。生のセキュリティ宣言・価格・Identityは本人承認のみ。MSIXアップロードやSave draftは別途明示承認後。
5. 実MSIXのhash、Store validation応答、draft URL / ID、キャンセル・認証切れ・再起動を照合。
6. 証拠がすべて揃ったあとに販売工程移行判定を再実施。認定提出・公開は別承認。

**現時点の判定を販売GOへ自動昇格させない。**
