---
name: notebooklm
description: 資料が3件以上、または合計1万字を超える読み込み・要約・比較をNotebookLMへ任せる。「NotebookLMで調べて」「資料群を要約して」「複数資料を比較して」で使う。リポジトリ内のコード読解は対象外。
---

# NotebookLM連携スキル

## 役割分担
- Claude Code＝司令塔（判断・指示・アウトプットに集中する）
- NotebookLM＝調査エンジン（大量資料の読み込み・要約・成果物生成。処理はGoogle側）
- 結果は必ずファイルで残す（保存先と手順はフェーズ6）

## 使う/使わないの判断基準
- 資料が3件以上、または合計1万字を超えそうな読み込み・要約・比較 → NotebookLMに外注する
- スライド・音声概要・インフォグラフィック・レポートが欲しい → NotebookLMのスタジオ機能を使う
- 手元のファイルを1〜2個読むだけ → 外注せず直接読む
- 今日のニュースを1件調べるだけ → Web検索で直接調べる

## コマンドの調べ方（迷ったらまずこれ）

`nlm --ai` がこのCLI自身のAI向け正式リファレンスを出力する。以下の記載と食い違ったら `nlm --ai` を正とする。

コマンドは名詞先行・動詞先行の2系統があり、どちらも同じ処理を呼ぶ。以下は名詞先行で統一。

- 名詞先行: `nlm notebook create "Title"` / `nlm source add <id> --url ...`
- 動詞先行: `nlm create notebook "Title"` / `nlm add url <id> <url>`

**ID引数は省略できない。** ノートブックIDやソースIDを渡さないコマンドは全て失敗する。IDは `nlm alias set <名前> <id>` で短い別名を付けておくと以降の指定が楽になる（`nlm alias list` で既存を確認してから作る）。

## 手順

### 1. 認証確認
```
nlm login --check
```
切れていたら `nlm login --help` で導入済み版の方法を確認し、`nlm login` でユーザーにログインしてもらう。普段のChromeを勝手に終了せず、同じ認証方法の再試行は1回までにする。Googleログインは人間の担当。**パスワードは絶対に聞かない。**

保存済みCookieは数週間持つ。401等は3層の自動リカバリが走るので、`unverified` が出ただけで期限切れと決めつけて再ログインしない。

### 2. ノートブックを作る
```
nlm notebook list
nlm notebook create "YYYY-MM-DD_テーマ"
```
同じテーマの既存ノートがあれば `nlm notebook list` で探して再利用する。

### 3. 資料を投入する

送る資料とGoogleへの送信範囲を明らかにする。会話で承認済みなら再確認は不要。自動発火しても未承認の資料は送信せず、必要な範囲の許可を得る。機密・個人情報はソース化しない。
```
nlm source add <notebook-id> --url "https://..." --wait
nlm source add <notebook-id> --file /path/to/doc.pdf --wait
nlm source add <notebook-id> --text "本文" --title "タイトル"
nlm source add <notebook-id> --drive <doc-id> --type doc
```
- YouTubeのURLは `--url` に渡す。導入済み版のhelpに `--youtube` があればそれも使える
- `--wait` を付けると処理完了まで待つ。付けないと未処理のまま次に進んでしまう
- 対応拡張子: .pdf .txt .md .docx .csv .pptx .epub、画像・音声・動画各種
- 投入後は `nlm source list <notebook-id>` で入ったか確認する

資料そのものを探すところからやるなら:
```
nlm research start "調べたいこと" --notebook-id <id> --auto-import
nlm research status <notebook-id>
```
`--mode deep` で約5分・40〜80件。既定の fast は約30秒・10件程度。

- **`--auto-import` を付けたら `nlm research import` を手で打たない。** `research status` は auto-import 中でも「import を実行せよ」と表示するが、従うと同じソースが二重登録される。`start` コマンドの終了を待てば取り込まれている
- research は1ノートブックに同時1本。複数テーマは順に完了を待ってから投げる
- 二重登録してしまったら `nlm source list` で URL の重複を拾い、`nlm source delete <id> --confirm` を**1件ずつ**回す（複数 ID の一括指定は失敗する）

### 4. 出典付きで質問する
```
nlm notebook query <notebook-id> "質問"
nlm notebook query <notebook-id> "質問" --json
nlm notebook query <notebook-id> "追い質問" --conversation-id <cid>
nlm notebook query <notebook-id> "質問" --source-ids <id1,id2>
```
`--json` を付けると `citations` / `references` / `cited_text` が構造化されて返る。出典を引用元つきで記録に残したいときはこちら。

### 5. 成果物を生成 → 状態確認 → ダウンロード

生成系は**全て `--confirm` が必須**（付けないと確認待ちで止まる）。
```
nlm slides create <notebook-id> --confirm            # detailed_deck / presenter_slides
nlm audio create <notebook-id> --format deep_dive --confirm   # deep_dive/brief/critique/debate
nlm infographic create <notebook-id> --confirm       # landscape/portrait/square
nlm report create <notebook-id> --format "Study Guide" --confirm
nlm mindmap create <notebook-id> --confirm
nlm video create <notebook-id> --confirm
nlm quiz create <notebook-id> --count 5 --confirm
nlm flashcards create <notebook-id> --confirm
nlm data-table create <notebook-id> "抽出したい内容" --confirm   # 説明文が必須
```
共通オプション: `--source-ids <id1,id2>` で対象ソースを絞る、`--language <BCP-47>` で言語指定（日本語は `ja`）。

完了確認とダウンロード:
```
nlm studio status <notebook-id>                      # completed になるまで待つ
nlm download slide-deck <notebook-id>                # --format pptx も可
nlm download audio <notebook-id> --output podcast.mp3
nlm download report <notebook-id> --output report.md
nlm download infographic <notebook-id>               # .png
nlm download mind-map <notebook-id>
nlm download data-table <notebook-id>                # .csv
nlm download quiz <notebook-id> <artifact-id> --format markdown
```
生成直後は必ず `nlm studio status` で completed を確認してから download する。

### 6. 結果を残す

**保存先は Obsidian vault の `リサーチ/` フォルダ。** カレントディレクトリの `リサーチ/` ではない。ファイル名は `YYYY-MM-DD_テーマ名.md`。

書き方は obsidian スキルの「リッチ表示ルール」に従う（人が読むページ扱い）。frontmatter（type / summary / updated / tags / cssclasses）、H1直下の顔callout、ピル行を付ける。構成の正本は obsidian スキルの references/design-guide.md と templates/ なので、**書き始める前にそちらを読む**。

内容は**結論・根拠・出典の3点**を最低限含める。NotebookLM が返した出典は消さない。

保存方法はobsidianスキルを正本とする。vault直下のAGENTS.mdを読み、本文全体はvault内の確定パスへ直接書く。既存ファイルがあれば内容と上書き意図を確認する。CLIが使えれば `obsidian file path="..."` で反映を確認する。長文を `content=` へ流し込まない。

**完了条件**: `obsidian read path="リサーチ/YYYY-MM-DD_テーマ名.md"` で読み戻し（CLI不通時はファイルを直接読む）、obsidian スキルの references/page-review.md の手順で検証して PASS になったこと。FIX なら指摘どおり直して読み戻す。**上限3周**。3周しても PASS にならなければ、残った指摘をそのままユーザーに提示して判断を仰ぐ。「保存した」で終わらせない。

**フォールバック**: CLI が不通ならObsidianを勝手に起動せず、確定済みvaultパスへの直接書き込み・読み戻しで続行し、代替した旨を報告する。vault自体へ書けない場合は作業フォルダに下書きを保管し、vault保存未完と伝える。

## 注意（守らないと事故る）
- 機密・個人情報はソース化しない（Googleに送られる）
- 1ノートブックのソース数には上限がある（無料プランは50件目安、契約プランにより変動）。テーマごとにノートブックを分ける
- 生成系コマンドに `--confirm` を付け忘れると止まる。ID引数を省くと必ず失敗する
- 非公式ツールなので突然壊れることがある。壊れたら `uv tool upgrade notebooklm-mcp-cli` で更新する（このマシンではシステムPythonが3.10でこのパッケージの要件3.11以上を満たさないため、pip3 では入らない。uv管理のPython 3.12上に隔離インストールしてある）
- 出典の裏付けがない情報を断定して書かない
