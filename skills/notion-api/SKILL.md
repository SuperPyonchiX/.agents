---
name: notion-api
description: NotionをREST API経由で操作する基盤スキル。DBスキーマ取得・クエリ・ページ作成・アーカイブ・Markdown→ブロック変換を標準ライブラリのみのスクリプトで行う。「NotionをAPIで操作して」「NotionのDBにページを作って」で使う。他のNotion系スキルの書き込み基盤でもある。
---

# notion-api

Notion を REST API で操作するための基盤。ワークフローは持たない。
「トークンを確認 → スクリプトを呼ぶ」の直列だけで、判断が要るのはペイロードの中身と、
どのスクリプトをどの順で呼ぶかのみ。

他の Notion 系スキル（notion-knowhow-page / youtube-member-summary）から書き込み基盤として
参照される。それらのスキルが発火している場合、承認ゲートや対象 DB の規約は**呼び出し元の
スキルの記述が優先**。このスキルは経路（API の呼び方）だけを提供する。

## 前提: NOTION_TOKEN

トークンは環境変数 `NOTION_TOKEN` から読む。スクリプトは未設定なら**終了コード2で止まり、
設定手順を stderr に出す**。その案内をそのままユーザーに伝えて中断すること。
トークン未設定のまま代替手段で「操作した」ことにしてはならない。

初回セットアップ（インテグレーション発行と対象ページへの接続共有）の詳細は
`references/api-guide.md` の冒頭にある。ユーザーへ案内するときに読む。

## スクリプト

すべて標準ライブラリのみで動く。外部パッケージ不要。
`notion_http.py` は共通処理（認証ヘッダ・リトライ・JSON引数の解釈）で、単体では実行しない。

| スクリプト | 用途 |
| --- | --- |
| `scripts/md2blocks.py` | Markdown → ブロック JSON 変換。2000字分割を吸収。Markdown の表は table ブロックにする（1表100行まで）。コードフェンスの `csharp` `cpp` などは Notion の言語名（`c#` `c++`）へ直す |
| `scripts/notion_page.py` | `create`（目次付きページ作成と分割追送）/ `append`（読み戻しで照合した不足分の追送）/ `set-icon` / `archive`。create/appendは `--progress <json>` で途中結果を保存する |
| `scripts/notion_query.py` | `schema`（プロパティ定義と選択肢一覧）/ `query`（全件クエリ。`--compact` は `icon` も返す）/ `blocks`（本文読み戻し） |

終了コードは3本とも共通: **0=成功 / 1=APIエラー（レスポンス本文を stderr に表示）/
2=引数・トークン・入力の不備**（md2blocks.py は API を呼ばないので 0 か 2 のみ）。notion_page.pyには **3=部分成功・結果不明・進捗保存失敗** もある。stdoutのstatusとidを必ず確認する。

呼び出し例:

```bash
# スキーマ確認（select の既存選択肢を見る）
python scripts/notion_query.py schema --data-source-id <uuid>

# Markdown 本文つきでページ作成
python scripts/md2blocks.py --file body.md --out blocks.json
python scripts/notion_page.py create --data-source-id <uuid> \
  --properties props.json --blocks blocks.json --icon "📜" --progress progress.json

# アイコンの付け忘れを後から直す
python scripts/notion_page.py set-icon --page-id <page-id> --icon "📜"

# 登録済み一覧の確認（値だけに間引く。icon 列でアイコン漏れも見える）
python scripts/notion_query.py query --data-source-id <uuid> --compact
```

**`create` の `--icon` は省略しない。** 省略できてしまうが、アイコンなしのページは
一覧で内容を見分けられず、後からまとめて付け直すのは手間がかかる。内容に合う絵文字を
毎回1つ選ぶ。同じ絵文字を全ページに使い回すのもアイコンなしと変わらないので避ける。

**作成するページの先頭行は Notion の目次にする。** `create` が本文の先頭に目次ブロック
（`table_of_contents`）を自動で入れるので、`md2blocks.py` の出力に自分で足さない（先頭が既に目次なら重ねない）。
`PATCH /v1/blocks/<page-id>/children` で本文を差し替えるなど `create` 以外の経路で書くときは、
目次が自動では入らない。差し替え後も先頭が目次になるよう、送るブロックの先頭に
`{"type": "table_of_contents", "table_of_contents": {"color": "default"}}` を置く。

`--properties` `--blocks` `--filter` は JSON リテラルでもファイルパスでもよい。
長い JSON は一時ファイルに書いてパスを渡す（コマンドラインに長文を載せない）。

## 典型的な流れ

1. **スキーマ確認** — 書き込む前に `notion_query.py schema` でプロパティ名・型・select の
   既存選択肢を確認する。**存在しない選択肢名を渡すと選択肢が勝手に増える**ため、
   推測でプロパティ JSON を組んではならない
2. **ペイロード作成** — プロパティ値の JSON は `references/api-guide.md` の形に従う。
   本文があれば `md2blocks.py` で変換する
3. **書き込み** — `notion_page.py create`。`--icon` を必ず添える。出力の `url` を控える
4. **読み戻し** — 内容が重要な書き込みは `notion_query.py query --compact` や
   `blocks` で読み戻して確認する。`--compact` の `icon` が null のページはアイコン漏れ

一括投入では、投入済み記録を持ち、二重投入を防ぐ。作法は `references/api-guide.md` の
「重複排除の作法」を読む。

終了3のときはcreateを繰り返さない。`partial`は作成済みIDあり、`unknown`は作成結果未確認。`complete`でも進捗保存失敗なら終了3になるため、まず読み戻す。`confirmed_blocks`は応答を確認した件数で、`pending_blocks`の成否は未確定。DBを一意キーで照合し、既存本文と元のblocksを内容・順序まで比較する。確認できた不足分だけを `remaining.json` に書き、次を実行する。

強制終了・Ctrl+Cなどでは終了3や最終JSONを返せない。終了コードによらず、進捗の`creating`は結果不明、`sending`／`appending`は部分成功と同じ復旧手順で扱う。`--progress`を付け、親フォルダを先に作る。進捗を失った場合もDBを一意キーで照合するまで再作成しない。createのAPIエラーは保守的に結果不明の終了3として返す。共通HTTP処理の自動再試行は429に対する最大2回だけで、タイムアウトや5xxの作成・追送は自動再試行しない。

```
python scripts/notion_page.py append --page-id <id> --blocks remaining.json --expected-count <読み戻した直下ブロック数> --progress progress.json
```

appendは件数が変わっていれば終了2で止まる。同じ件数の編集や確認後の同時更新は検出できないので、同じページへの並行書き込みを止めて実行し、追送後にも読み戻す。目次はcreateが加えるため、復旧時の比較にも含める。

## references/ を読むタイミング

| ファイル | 読むタイミング |
| --- | --- |
| `references/api-guide.md` | プロパティ値・フィルタの JSON を組むとき、トークンのセットアップを案内するとき、重複が出たとき |

## 禁止事項

- トークンを標準出力・ログ・git 管理下のファイルに書き出すこと
- ページの完全削除（アーカイブのみ。復元可能な操作に限る）
- `schema` で確認せずに select / multi_select へ新しい選択肢名を書き込むこと
- 旧 API バージョン（`2022-06-28`）や `database_id` parent で自前のリクエストを組むこと
  （複数データソース化した DB で全滅する。理由は `references/api-guide.md`）
- API エラーを握りつぶして成功扱いにすること。終了コード1の内容はそのまま報告する
