# 保守用コード

| 場所 | 責務 |
|---|---|
| `toolpack/` | 追加ツールの検査・配置・隔離実行・登録・管理 |
| `office/` | Excel・Word・PowerPointの処理本体 |
| `tests/toolpack/` | 追加ツール管理のテスト |
| `tests/office/` | Office処理のテスト |
| `tests/webui/` | Pipe・画面・ヘルプのテスト |
| `tests/runtime/` | 起動・診断・安全制限・構成のテスト |

直下の `toolpack_*.py`・`office_*.py`・`excel_*.py`・`check_sheet_presence.py` は互換入口です。
編集する本体は各サブフォルダにあります。旧CLIは従来どおり使えます。
`_compat.py` がimport先の同一性を保ち、状態や処理が二重にならないようにしています。

Open WebUIへ登録するPipeは単独ファイルとして必要なので、直下のままです。
サービス起動・監視・診断も、タスクや既存手順から使う入口として維持しています。
リポジトリの位置は `repo_paths.py` が定義します。

全テスト: `text-processing-bridge/.venv/Scripts/python.exe -m pytest tools -q`

詳細は[保守構成](../docs/maintenance/CODE_LAYOUT.md)を参照してください。

再追加は `toolpack/toolpack_selection.py` が確認内容を作り、利用者の選択をコアへ渡します。
`toolpack_install` の `restore_saved=True` は保存版の照合・再検査・再登録、
`new_version="1.0.1"` は元ZIPを保持した新版採番です。GUIとCLIで同じ検査を使用します。

保存一覧は `toolpack/toolpack_saved.py`、版選択とチェック画面は `toolpack/toolpack_dialogs.py`。
未登録の保存原本から再登録でき、完全削除は `toolpack_manage.command_purge_saved` を通します。
登録中・状態未確認・処理中の削除を拒否し、確認後に変わった保存内容も選び直しになります。
