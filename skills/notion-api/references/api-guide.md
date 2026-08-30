# Notion REST API ガイド

スクリプトが吸収しない部分（ペイロードの中身の書き方と、運用上の落とし穴）をまとめる。
エンドポイントの呼び出し自体は `scripts/` が行うので、ここで見るのは主に **JSON の形**。

## トークンの発行と共有（初回セットアップの詳細）

1. https://www.notion.so/profile/integrations で「新しいインテグレーション」を作成する。
   ワークスペースを選び、種類は「内部」。必要な権限はコンテンツの読み取り・更新・挿入
2. 発行された `ntn_` で始まるトークンを控える
3. **Notion 側で対象のページ / データベースにインテグレーションを接続する。**
   対象ページ右上の「…」→「接続」→ インテグレーション名を選ぶ。
   親ページに接続すれば配下にも効く。**これを忘れると全リクエストが 404 になる**
   （権限エラーではなく「見つからない」が返るので気づきにくい）
4. 環境変数 `NOTION_TOKEN` に設定する

```powershell
[Environment]::SetEnvironmentVariable('NOTION_TOKEN', 'ntn_xxxx', 'User')  # 永続（要シェル再起動）
$env:NOTION_TOKEN = 'ntn_xxxx'                                             # 現在のシェルのみ
```

トークンを標準出力・ログ・git 管理下のファイルに書かないこと。

## API バージョンと parent の形（重要）

- ヘッダは `Notion-Version: 2025-09-03`（スクリプトが常に付ける）
- ページ作成の parent は **`{"type": "data_source_id", "data_source_id": "<uuid>"}`**
- 旧バージョン `2022-06-28` + `{"database_id": ...}` は、DB が複数データソースになった瞬間に
  **全リクエストが `400 Databases with multiple data sources are not supported` で落ちる**（実測）。
  使わない
- データソース ID が分からないときは、DB ページの URL 末尾の ID を `GET /v1/databases/<id>` に
  渡すと `data_sources` 配列に入っている。MCP 表記 `collection://<uuid>` の uuid 部分と同じ

## プロパティ値の形（`notion_page.py create` の --properties）

プロパティ名は Notion 上の表示名を**そのまま**使う（`URL` は `URL` のまま。
MCP のような `userDefined:` 接頭辞は付けない）。

```json
{
  "タイトル": {"title": [{"text": {"content": "ページ名"}}]},
  "URL": {"url": "https://example.com"},
  "チャンネル": {"select": {"name": "選択肢名"}},
  "カテゴリ": {"multi_select": [{"name": "AI"}, {"name": "MCP"}]},
  "公開日": {"date": {"start": "2026-08-30"}},
  "メモ": {"rich_text": [{"text": {"content": "本文"}}]},
  "済": {"checkbox": true}
}
```

- select / multi_select に**存在しない選択肢名を渡すと、その選択肢が新規作成される**。
  意図しない選択肢を増やさないよう、書き込み前に `notion_query.py schema` で既存一覧を確認する
- `created_time` / `last_edited_time` 型は自動設定で書き込み不可。properties に含めない

## フィルタの形（`notion_query.py query` の --filter）

```json
{"property": "URL", "url": {"equals": "https://www.youtube.com/watch?v=xxxx"}}
{"property": "カテゴリ", "multi_select": {"contains": "AI"}}
{"and": [{"property": "済", "checkbox": {"equals": false}},
         {"property": "公開日", "date": {"after": "2026-08-01"}}]}
```

## ブロックの制約（スクリプトが吸収済み）

知識として持っておく。手で JSON を組むときに踏みやすい。

- rich_text の1要素は 2000 字未満（`md2blocks.py` が分割する）
- ページ作成・追記の children は1リクエスト 100 ブロックまで（`notion_page.py` が分割追送する）
- コードブロックの `language` は許可リスト外だと validation_error（`md2blocks.py` は plain text に落とす）
- API は Markdown を直接受け付けない。必ずブロック JSON に変換してから渡す

## 読み戻し検証

投稿後に内容を確かめるには:

- プロパティ → `notion_query.py query --compact` で該当ページを引く
- 本文 → `notion_query.py blocks --page-id <id>`。各ブロックの `rich_text[].plain_text` を見る

## 重複排除の作法

一括投入で重複が出たときの復旧手順。

1. `notion_query.py query --compact` で全件を取り、一意キー（URL プロパティなど）でグルーピングする
2. 各グループで**最も古い1件を残し**、残りを `notion_page.py archive` でアーカイブする
3. アーカイブはゴミ箱行きで復元可能。**完全削除の API は使わない**（スクリプトにも実装していない）

二重投入の予防は呼び出し側の責務。投入済み記録（TSV など）を持つ場合は、
**DB の実態（query の結果）から記録を作り直せる形**にしておくこと。
手作業と自動投入が混ざると記録漏れで重複が出る。

## レート制限

平均 3 リクエスト/秒。429 が返ったら `Retry-After` 秒待って再試行する
（`notion_http.py` が2回まで自動リトライする）。大量投入では1件ずつ直列に呼べば通常は当たらない。
