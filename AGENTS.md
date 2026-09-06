# minutes-pipeline — 議事録処理パイプライン

病院の会議文字起こしから整形済み議事録(docx)を生成するシステム。全てローカルで動作する。

## 最初に判定する: 追加ツールの制作依頼か、本体の保守依頼か

**「このリポジトリを読み、追加ツールを作って」という依頼の標準成果物は `.zip` ファイルです。**
表示名・ID・機能だけが指定された場合も同じです。利用者に内部規格を書き直させず、
まず [tool-packages/SPEC.md](tool-packages/SPEC.md) を最後まで読み、
`tool-packages/example_line_count/` を参考に制作・検査・パッケージ化まで行ってください。

- 制作するのは独立した `tool-packages/<tool_id>/` の内容のみ。参照元リポジトリは資料として扱う。
- `tools/open_webui_*.py` や既存Pipe・ハブを変更しない。Pipeと登録は院内管理アプリが用意する。
- **完成した `.zip` をダウンロードできる形で渡すまでが制作作業。** PRやソースコードだけで完了にしない。
- **PR作成・push・マージ・本番登録は、依頼者の明示的な指示があるときだけ。**
  単なる「作って」「実装して」「追加して」は、その指示に含めない。
- 実行や添付ができない場合は未完了の工程を伝える。勝手にPR提出へ切り替えない。
- 以下のGitブランチ・コミット・`push local` の手順は**本体保守向け**であり、
  追加ツール制作依頼に対してリポジトリを書き換えたり提出したりする根拠にしない。

本体の修正・規格の改修が明示的に依頼された場合は、以降の保守手順と台帳に従います。

## アーキテクチャ(データの流れ)

コンテナで動くのは Open WebUI だけ。他は全部 Windows 上のプロセスである。

```
Open WebUI (公開 port 3000 → コンテナ 8080, docker run で稼働)
  ├─ tools/open_webui_text_processing_pipe.py が「文章処理」モデルとして動く
  │    └─ HTTP → 文章処理ブリッジ (FastAPI, port 8008, Windows)
  │         └─ HTTP → Ollama gemma4:26b (Windows, localhost:11434)
  └─ tools/open_webui_excel_analysis_pipe.py が「Excel分析」モデルとして動く
       └─ 読み取りもコメント生成も HTTP → ハブ (port 8010, Windows) → tools/*.py

8010と8008は1プロセスで動く。ログオン時に自動起動する:
  タスク minutes-pipeline-local-services → tools/start_local_services.py
  手動:  text-processing-bridge\.venv\Scripts\python.exe tools\start_local_services.py
  状態:  http://localhost:8010/ (繋がっているツールと周辺サービスの一覧)
  ログ:  logs/local_services.log
```

停止からの復旧はタスク `minutes-pipeline-local-services-watchdog` が1分ごとに監視する。
`tools/install_local_services_watchdog.ps1` で登録。`pythonw` と非表示子プロセスを使い、黒い窓は出さない。
両ポートが閉じ、サービスのタスクが有効かつ停止中の場合だけ起動する。稼働中のプロセスは終了しない。
保守で止め続ける場合はサービスのタスクを**無効化**する（停止だけでは監視が起こす）。
記録は `logs/local_services_watchdog.jsonl`（検知日時・状態・終了コード・復旧結果、最大約4MB）。
Docker/Open WebUIの起動はこの監視の対象外。

2026-08-14 に Dify を撤去した。分岐1つとプロンプト5本のために14コンテナを要し、
プロンプトがGUI側にあってKiloから編集できなかったため。
プロンプトは `text-processing-bridge/app/prompts.py` へ移し、
呼び出しは `app/local_workflow.py` と `app/ollama_client.py` が担う。
同日、ブリッジの相手がWindows側のOllamaだけになったためコンテナから降ろした
(コンテナ境界を2回またぐ理由が無くなったため)。

## ディレクトリ

**保守時の注意:** `tools/toolpack_*.py`・`tools/office_*.py`・`tools/excel_*.py`・
`tools/check_sheet_presence.py` は旧CLI/import用の互換入口。
処理本体は同名の `tools/toolpack/` または `tools/office/` 配下にある。
修正は本体に行い、入口へ処理を追加しない。テストは `tools/tests/` 配下。
詳しい分担と確認方法は [保守構成](docs/maintenance/CODE_LAYOUT.md) を参照する。

追加時の同じIDの確認は `tools/toolpack/toolpack_selection.py` が担当する。
保存版の再登録か、画面で指定した新版番号での登録かを明示選択する。
元ZIP・既存版は上書きしない。採番済みZIPも全検査を通す(台帳第0章)。

| パス | 内容 |
|---|---|
| `tools/toolpack/toolpack_saved.py` | 未登録の保存ツール一覧・状態照合・保存原本からの再登録。削除先の絶対パス・リンク検査は `safe_tree`。実体削除は `toolpack_manage` → `toolpack_store` に委譲。試験は `tools/tests/toolpack/test_toolpack_saved.py` |
| `tools/toolpack/toolpack_dialogs.py` | 版の読み取り専用ドロップダウンと保存一覧の表示。行選択で再登録、チェックしたツールだけ確認後に完全削除。GUIは選択を返すだけで処理を持たない |
| `text-processing-bridge/` | 文章処理ブリッジ本体(FastAPI, port 8008)。テストあり。Windows上で稼働 |
| `local_tool_bridge/` | Open WebUIのPipeからWindows上のKilo既存ツールを呼ぶHTTP受付(port 8010、ログオン時に自動起動)。入口は固定で、ツール追加は `connectors/` へ1ファイル置くだけ(`.kilo/rules/09-hub-connector.md`)。業務ロジックは持たない。繋がっているツールは `http://localhost:8010/` で一覧できる |
| `text-processing-bridge/app/main.py` | エンドポイント定義のみ。処理本体は下の各モジュールへ委譲 |
| `text-processing-bridge/app/processing.py` | 汎用処理の実行制御。長文分割・再試行 + 数値改変ガード(LLMが数値を落とす/捏造すると再プロンプト) |
| `text-processing-bridge/app/structured.py` | 構造化議事録パイプライン(2周抽出・記号救済・話し言葉修正) |
| `text-processing-bridge/app/agenda_parse.py` | 次第(アジェンダ)の解析と骨格データ |
| `text-processing-bridge/app/roster.py` | 出席者名簿の解析、呼称の表記合わせ |
| `text-processing-bridge/app/instructions.py` | LLMへ渡す指示文の生成 |
| `text-processing-bridge/app/llm_lines.py` | LLM出力(##項目/##発言/#議題 行)の解析 |
| `text-processing-bridge/app/merge.py` | 分割ブロックの統合・重複除去・報告読み上げ判定 |
| `text-processing-bridge/app/document.py` | 描画用データ組み立て(出典マーカーの色分け) |
| `text-processing-bridge/app/kebatori.py` | ルールベースのケバ取り(フィラー除去)。ルールは `config/kebatori.yaml` |
| `text-processing-bridge/app/chunking.py` | 長文の段落・文境界分割(オーバーラップ分割含む) |
| `text-processing-bridge/app/prompts.py` | 操作ごとのプロンプトと生成条件(旧Difyワークフローから移設) |
| `text-processing-bridge/app/local_workflow.py` | 操作の振り分け。要約/整形/議事録/修正はLLM、ケバ取りはルールのみ、ケバ取り強はLLM検出+コード削除 |
| `text-processing-bridge/app/ollama_client.py` | Ollama `/api/chat` を1往復する薄いクライアント |
| `text-processing-bridge/app/render_minutes.py` | docx レンダラー。テンプレートの行XMLを複製して書式を完全保持。ハイライト色 = 出典マーカー(緑=文字起こし由来 / 黄=次第由来 / 赤=不明・要手動記入)。`/v1/render/minutes_docx` として公開 |
| `text-processing-bridge/app/export.py` | 結果の配布用ファイル生成(txt/md/csv/docx/xlsx)。`/v1/render/export` として公開 |
| `text-processing-bridge/app/result_page.py` | Tool の結果埋め込みページ(HTML)生成。`/v1/render/result_page` として公開 |
| `text-processing-bridge/app/oplog.py` | PIIレス運用ログ(件数・実行ID・状態のみ、本文不記録)。保存先はコンテナ外の `logs/` |
| `text-processing-bridge/app/archive.py` | 受け取った文章と生成成果物の控えを `work/imports/`・`output/` へ保存。両方ともgit管理外 |
| `tools/open_webui_text_processing_pipe.py` | Open WebUI の Pipe プラグイン。正規表現で操作(ケバ取り/整形/要約/議事録)と出力形式を判定。LLMにルーティングさせない設計。ファイル生成はブリッジの `/v1/render/*` に委譲 |
| `tools/open_webui_excel_analysis_pipe.py` | Open WebUI の Pipe。添付Excelへの操作を正規表現で判定し、処理はハブ(port 8010)へ委譲する |
| `tools/open_webui_deploy.py` | Open WebUIへのPipe/Tool登録・更新(管理API経由・localhost限定・対象は tools/ の open*webui*.py のみ)。無指定はdry-runで差分表示、`--apply` で反映し登録後に内容一致を検証。Kiloは実行のみ可(編集は不可) |
| `tools/open_webui_help_sync.py` | ヘルプRAGの資料同期。運用ドキュメントとコード本体をナレッジ「院内ツールヘルプ」へ入れる。**中身が変わったファイルだけ入れ直す**(前回のsha256を `logs/help_sync_state.json` に持つ)。`--full` で全件、`--reset` で作り直し。`data/`・`templates/`・`.env` は柵で除外。埋め込みはOllama(bge-m3)を通るため、Ollama更新中は実行しない。**ログオン5分後と2時間ごとに自動実行**(タスク `minutes-pipeline-help-sync`、ログは `logs/help_sync.log`)。すぐ反映したいときだけ手で `--apply` |
| `tools/open_webui_help_pipe.py` | 使い方ヘルプのPipe(利用者はこれを選んで質問する)。ナレッジを自分で検索し、その結果だけをLLMへ渡す。Open WebUIのナレッジ機能へ任せると、モデルが検索ツールを呼んだところで実行されず回答が空になる(2026-08-17に実測)ため、検索を確定的に行っている。作業依頼(議事録・Excelコメント)は正規表現で担当を判定し、回答の先頭に「文章処理」「Excel分析」への切替リンク(`?models=&q=&submit=false`)を出す。「どう頼めばいいか」と聞かれたときは、資料をもとにその場で依頼文を作り、固定文の代わりに `q=` へ入れる。`kilo:` で始めるとKiloへ貼る依頼文を作る(生成→機械検証→3回まで作り直し→通らなければ用件と検索結果を並べた形へ退避)(2026-08-18に追加) |
| `tools/excel_reader.py` ほか `office_*.py` | Office ファイル(Excel/Word/PowerPoint)の表示・編集・新規作成スクリプト。依頼者は `input/` へファイルを置き、結果は `output/` へ出る。`input/` は絶対に上書きしない |
| `tools/office_template.py` | Excel/Word上の差し込み目印を置換するGUI編集テンプレート試作。`minutes` は実運用の `render_minutes.py` で実物Wordをプレビュー。`check`/`preview`/`deploy` で、Wordで書式編集した議事録テンプレートを検証してからOpen WebUIへ反映する。元ファイルは上書きしない |
| `webui_tour/` ・ `tools/webui_tour.py` | Open WebUIの画面へ重ねる操作案内(ツアー)の試作。`tour.js`(実行本体)と `tours/*.json`(台本)が正本。差し込み口は Open WebUI が既定で読み込む `/static/loader.js` で、本体もindex.htmlも改造しない。入口は画面の隅の「?」ボタン1つで、押すまで案内は始まらない(URLの `#tour=<id>` でも開始可)。`check`/`preview`/`deploy`/`remove`、無指定はdry-run。**手順の文面はLLMに作らせない**(存在しない場所を指すため台本は固定) |
| `tools/webui_static_guard.py` | Open WebUIの画面カスタマイズ(custom.css・Excelアップロードガード・操作案内)が消えていないか見張り、消えていたら戻す。`open_webui` をコンテナ内でimportすると`STATIC_DIR` が初期化されるため、doctorを走らせるたびに消えていた(2026-08-18に特定) |
| `tools/excel_comment_report.py` | 複数シートへ書き込んだExcelコメント、貼付先リンク、参照表の静的コピーを別の確認用xlsxへ縦積みする。元ブックにはシートやVBAを追加しない |
| `tools/excel_comment_build.py` | Excelコメントの組み立て本体(抽出→検証済み下書き→LLM整形→一括書込)。**確認用レポートは既定で作らない**(`--report` で作る。単体なら excel_comment_report.py)。`--sheet`・`--no-llm` で実物1シートを短時間プレビューできる。結果はJSON1行 |
| `tools/ollama_watchdog.py` | Ollamaのコミット暴走を検知して再起動する見張り。15分ごとに自動実行。`--fix` 無しなら確認のみ |
| `tools/doctor.py` | オフライン運用の自己診断(読み取り専用)。障害時は最初にこれを実行し、出力の「対処」に従う |
| `tools/safe_task_runner.py` | Kiloが依頼ごとに `work/` へ生成したPythonを安全制限付きで実行。書き込みは `work/`・`output/` のみ。**追加ツール用ではない**(そちらは `toolpack_runner.py`。別物なので混ぜない) |
| `tools/toolpack_*.py` ・ `local_tool_bridge/installed_specs.py` ・ `job_lock.py` | **追加ツール受入基盤**。USB等で持ち込んだ `.zip` を検査し(`toolpack_verify`)、Git管理外の `additional-tools/` へ配置して(`toolpack_store`)、隔離実行し(`toolpack_runner` + `toolpack_child` + `toolpack_winjob` + `toolpack_winsec`。添付ファイルの読み取りは `toolpack_textio` がコア側で持つ)、固定ひな型からPipeを生成して(`toolpack_pipegen`)Open WebUIへ登録するところまでを `toolpack_install` が1本に繋ぐ(`--update` で入れ替え)。入った後の操作(無効化・削除・前の版へ戻す)は `toolpack_manage`、画面から使うなら `toolpack_gui`(`追加ツールの管理.cmd`)。ハブ側は `installed_specs` が registry を毎回読んで供給する。設計は `docs/design/TOOL_PACKAGE_DECISIONS.md`、工程は `docs/design/TOOL_PACKAGE_IMPLEMENTATION_PLAN.md` |
| `additional-tools/` | 追加ツールの実行時領域(git管理外)。パッケージ・registry・診断ログが入る。**コードやひな型はここへ置かない** |
| `tools/safe_file_import.py` | @メンション等で明示された外部ファイルを、元ファイル無変更で `work/imports/` へ複製 |
| `work/` | Kiloの依頼専用一時コードと外部ファイルの作業コピー(git管理外) |
| `.kilo/plugin/` | KiloのExcel操作ツール実体(excel_import/read/find/comment/write)とセッション制御。コメント本文の組み立ては `tools/excel_comment_build.py` へ委譲する |
| `data/` ・ `templates/` | 機密(実在の会議データ・議事録・名簿)。**読まない・コミットしない・変更しない** |
| `templates/gui/` | 例外: 利用者が書式(フォント・サイズ・色)をOfficeで編集するためのひな型(合成データ・個人名なし)。`excel_comment_gui_template.xlsx` はExcelコメントの書式の正本として接続済み。詳細は `templates/gui/README.md` |

関数レベルの索引とテストとの対応表は `.kilo/rules/02-map.md` にある。
文書の入口は [docs/README.md](docs/README.md)。利用手順・設計・保守・過去資料を分けている。
Roo専用の旧設定・手順書は廃止済み。現行の設定は `.kilo/` と `.kilocodeignore` を使う。

追加ツール受入・モデル管理構想(オフライン後もツールを追加できるようにする計画)の設計判断は
`docs/design/TOOL_PACKAGE_DECISIONS.md` に台帳としてまとめてある(確定/推奨/未決を区別)。
**この構想に関わる作業は、会話の要約ではなく、まず台帳を読む。**
「推奨(未決)」を実装の根拠にしてはいけない。

## テスト(変更後は必ず実行)

高速ループ(ホストvenv、数秒。Kiloプラグインの.tsテストもここから回る):

```powershell
cd text-processing-bridge
.\.venv\Scripts\python.exe -m pytest -q
```

venv再構築はオフラインで完結する(`wheelhouse-win/` にWindows用wheel同梱):

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse-win -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse-win -r requirements-office.txt
```

## デプロイ

- **ローカルサービス(ハブ・文章処理ブリッジ)**: コードを変えたら再起動する
  `Stop-ScheduledTask -TaskName minutes-pipeline-local-services; Start-ScheduledTask -TaskName minutes-pipeline-local-services`
- **pipe / tool**: `python tools\open_webui_deploy.py tools\<対象>.py` で差分を確認し、`--apply` を付けて反映する。登録IDはファイル先頭docstringの `id:` を使う(既存IDなら更新、無ければ新規作成+有効化)。管理画面(Workspace → Functions/Tools)への貼り付けは予備手段
  - 前提(1回だけ人の作業): Open WebUI 設定 → アカウント → APIキー を作成し、`%USERPROFILE%\.open-webui\admin_api_key.txt` へ保存(または環境変数 `OPEN_WEBUI_ADMIN_API_KEY`)。Gitや `.env` には置かない
- **Open WebUI本体の更新**: `docs/maintenance/OPEN_WEBUI_UPGRADE.md` の手順に従う。Pipeが内部Python APIに依存しているため、更新後は `doctor.py` と複数添付の目視確認が要る
- **画面のカスタマイズ(操作案内・custom.css・Excelアップロードガード)**: `python tools\webui_tour.py deploy --apply` の**1本にまとまっている**。差し込み先は index.html。**static/ には置かない** — `open_webui/config.py` がトップレベルで STATIC_DIR を全消しして初期状態を書き戻すため、**コンテナ内で open_webui を import する新しいプロセスが立つたびに消える**。`doctor.py` の内部API確認がまさにそれで、**doctorを走らせるたびに消えていた**(2026-08-18に原因特定・再現確認)。消えていないかは `tools/webui_static_guard.py` が5分ごとに見張って戻す(タスク `minutes-pipeline-webui-static-guard`)
- 旧 `Apply-WebUiTweaks.ps1` は `scripts/legacy/` へ移した過去資料。実行は拒否する。画面素材は `webui_tour/assets/` に集約。
- 出ないときは `python tools\webui_tour.py verify` で配信内容を確認。画面側の状態は `http://localhost:3000/#tour=debug` で見られる

## Git(ブランチ・バックアップ)

ネットを使わない。手順の全体は `docs/maintenance/GIT_BRANCH_WORKFLOW.md` にある。

- **履歴の預け先**: `git push local`(実体は `D:\offline-kit\git\minutes-pipeline.git`)。送り忘れは `doctor.py` が出す
- **1作業1ブランチ**: `git switch -c <名前>` → 作業・コミット → `git switch main` → `git merge --no-ff <名前>`。`--no-ff` を外すと作業の区切りが履歴から消える
- **ブランチを切り替えたらローカルサービスを再起動する**(サービスはこのフォルダのコードを直接読んでいる)
- **戻る目印はタグ**: 動作確認が取れた地点で `git tag -a stable-YYYY-MM-DD -m "..."`。戻すときは `git revert`(`reset`・`checkout` は使わない)
- **Kiloに許しているのは** 読み取り系と `add` / `commit` / `switch -c` / `push local` まで。切り替え・マージ・削除は人が行う(`kilo.jsonc` で強制)
- **worktree は使わない** — 新しいフォルダに `.venv` が無く、pre-commit がテストをスキップしてコミットを通してしまう

## 開発ツール(Kiloが扱える言語)

言語は「入れる」ものではなくモデルが既に書ける。要るのは**動かして確かめる道具**と、
**推測せずに読む資料**である。すべて `D:\offline-kit` にあり、**オフライン後は取り直せない**。

| 言語 | 道具 | 置き場 |
|---|---|---|
| Python | 3.12 + venv | `text-processing-bridge/.venv`(wheelは `wheelhouse-win/`) |
| JavaScript / TypeScript | node v22 / npm / tsc | `%LOCALAPPDATA%\Programs\nodejs\PFiles64\nodejs`、`D:\offline-kit\node-tools` |
| Java | JDK 21(Temurin) | `D:\offline-kit\java`(MSIは権限で入らないため `msiexec /a` で展開) |
| C / C++ | MinGW-w64 (gcc 16.2) | `D:\offline-kit\mingw` |
| 画面の確認 | Playwright + Chromium | `D:\offline-kit\node-tools`、ブラウザ実体は `D:\offline-kit\playwright-browsers` |
| Web仕様 | MDN(HTML/CSS/JS/DOM) | `offline-docs/web/content-main/files/en-us/web/` |

- **PATHに通っていないと Kilo から使えない。** node・java・gcc はユーザー環境変数のPATHへ入れてある。
  `doctor.py` が「開発ツールが使えます」で確認する(入っているかではなく、実行できるかを見る)
- オフラインで入れ直すときは `D:\offline-kit\npm\*.tgz` を使い、Playwrightのブラウザは
  `PLAYWRIGHT_BROWSERS_PATH=D:\offline-kit\playwright-browsers` を指す
- MDNは**RAGへ入れない**。使い方ヘルプのナレッジ(123ファイル)に対して30,932ファイルあり、
  混ぜると院内ツールの手順が埋もれる。Kiloが直接grepする資料として置く

## 重要な決まり

1. **パッチスクリプト禁止** — `_patch*.py` のような文字列置換スクリプトを書かない。ファイルを直接編集して git commit する
2. **`.env` に触らない** — 運用の接続設定が入っている(`text-processing-bridge/.env`)。雛形は `.env.example`
3. **`data/` に触らない** — 実在の病院会議データ(個人名入り)。テストには `text-processing-bridge/samples/meeting.txt`(架空データ)を使う
4. **最小差分** — 依頼された変更だけを行い、無関係なリファクタをしない
5. 議事録レンダラの実装は `text-processing-bridge/app/render_minutes.py` が唯一のソース。pipe への埋め込みは廃止済みで、pipe はブリッジの `/v1/render/minutes_docx` を呼ぶ。レンダラや出力形式(export.py)を変えたら **ローカルサービスの再起動**だけで反映される(Open WebUI への貼り直しは不要)
6. **同じ処理を2箇所に書かない** — Excelコメントの組み立ては `tools/excel_comment_build.py`、docx描画は `render_minutes.py` が唯一の実装。Kiloプラグイン・Pipe・ハブはそれらを呼ぶだけにする(経路で結果が食い違う事故を起こしたため)
7. **コミットは対象を選んで入れる** — `git add .` を使わず、`git status` と `git diff` で確かめてその依頼に関係するファイルだけを `git add` する。コミット後は `git push local` で預け先へ送る
8. **1コミット1目的** — 戻せる最小単位がコミットなので、目的を混ぜると片方だけを `revert` できなくなる。分けるのは作業中(区切りごとにコミット)であって、書き上げてからではない。実装とそのテスト、関数追加とコードマップの追従は同じコミットへ入れる
