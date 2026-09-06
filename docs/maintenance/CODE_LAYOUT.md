# 保守構成と変更時の確認

## 基本原則

処理本体は1か所だけ。古いCLI・importと利用者の起動方法は互換入口で維持する。
パッケージのZIP規格・request.json・返却JSON・承認区分は、構成整理では変更しない。

## どこを変更するか

| 対象 | 本体 | 確認するテスト |
|---|---|---|
| 追加ツール管理 | `tools/toolpack/` | `tools/tests/toolpack/` |
| Office処理 | `tools/office/` | `tools/tests/office/` |
| Open WebUIのPipe・登録 | `tools/open_webui_*.py` | `tools/tests/webui/` |
| 起動・監視・診断 | `tools/start_local_services.py`・`doctor.py`・各監視 | `tools/tests/runtime/` |
| 画面素材 | `webui_tour/assets/`・`tour.js`・`tours/` | `tools/tests/webui/` とNodeテスト |

旧 `tools/toolpack_*.py`・`office_*.py`・`excel_*.py`・`check_sheet_presence.py` は互換入口。
そこへ処理を書き足さない。入口を削除すると、既存のタスク・CLI・Kiloの許可済みコマンドが壊れる。
新しいコードの同一グループ内のimportは相対importを使い、入口経由に戻さない。
`__init__.py` で全機能をimportしない。検証器・梱包器は標準ライブラリだけで使える必要がある。

## 隔離と自動検査

隔離子・共通textio・単体テスト入口・Pipeひな型は `tools/toolpack/` の実体を使う。
互換入口をコピーしてはならない。監査対象の追加ツールへtools全体の読み取りを許可しない。
`test_module_layout.py` が旧importの同一性・CLI起動・コピー元・読取制限を検査する。

pre-commitはtools配下を再帰的に構文検査し、全テストを実行する。
ヘルプ同期は両グループの処理本体を収集する。過去資料は対象外。

## 変更しない場所

`data/`・実テンプレート・`input/`・`output/`・`additional-tools/`・venvの位置は維持する。
稼働中のジョブを終了して整理しない。処理本体の変更をサービスへ反映する場合は、
利用中のジョブがないことを確認してから再起動する。

旧画面設定スクリプトは `scripts/legacy/` に記録として保存し、実行は拒否する。
今後は機能追加・修正の対象に合わせて分割し、外部の呼び出しを調べずに入口を消さない。
