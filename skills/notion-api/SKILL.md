---
name: notion-api
description: Notion を REST API（インテグレーショントークン）で操作する基盤スキル。DB スキーマ取得・クエリ、ページ作成・アーカイブ、Markdown から Notion ブロックへの変換を標準ライブラリのみの Python スクリプトで行う。「Notion を API で操作して」「Notion からデータを取得して」「ページを一括投入して」で使う。notion-knowhow-page と youtube-member-summary はこのスクリプトを呼ぶ。
metadata:
  web-description: NotionをREST API経由で操作する基盤スキル。DBスキーマ取得・クエリ・ページ作成・アーカイブ・Markdown→ブロック変換を標準ライブラリのみのスクリプトで行う。「NotionをAPIで操作して」「NotionのDBにページを作って」と言われたら使う。他のNotion系スキルの書き込み基盤でもある。
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
| `scripts/md2blocks.py` | Markdown → ブロック JSON 変換。2000字分割を吸収 |
| `scripts/notion_page.py` | `create`（ページ作成。100ブロック超は自動追送）/ `archive`（ゴミ箱送り） |
| `scripts/notion_query.py` | `schema`（プロパティ定義と選択肢一覧）/ `query`（全件クエリ）/ `blocks`（本文読み戻し） |

終了コードは3本とも共通: **0=成功 / 1=APIエラー（レスポンス本文を stderr に表示）/
2=引数・トークン・入力の不備**（md2blocks.py は API を呼ばないので 0 か 2 のみ）。

呼び出し例:

```bash
# スキーマ確認（select の既存選択肢を見る）
python scripts/notion_query.py schema --data-source-id <uuid>

# Markdown 本文つきでページ作成
python scripts/md2blocks.py --file body.md --out blocks.json
python scripts/notion_page.py create --data-source-id <uuid> \
  --properties props.json --blocks blocks.json --icon "📜"

# 登録済み一覧の確認（値だけに間引く）
python scripts/notion_query.py query --data-source-id <uuid> --compact
```

`--properties` `--blocks` `--filter` は JSON リテラルでもファイルパスでもよい。
長い JSON は一時ファイルに書いてパスを渡す（コマンドラインに長文を載せない）。

## 典型的な流れ

1. **スキーマ確認** — 書き込む前に `notion_query.py schema` でプロパティ名・型・select の
   既存選択肢を確認する。**存在しない選択肢名を渡すと選択肢が勝手に増える**ため、
   推測でプロパティ JSON を組んではならない
2. **ペイロード作成** — プロパティ値の JSON は `references/api-guide.md` の形に従う。
   本文があれば `md2blocks.py` で変換する
3. **書き込み** — `notion_page.py create`。出力の `url` を控える
4. **読み戻し** — 内容が重要な書き込みは `notion_query.py query --compact` や
   `blocks` で読み戻して確認する

一括投入では、投入済み記録を持ち、二重投入を防ぐ。作法は `references/api-guide.md` の
「重複排除の作法」を読む。

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
